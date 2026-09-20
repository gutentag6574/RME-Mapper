"""Тесты геопривязки, преобразований координат QTransform и MapCanvas для GeoTIFF (Этап 16)."""

import math
from pathlib import Path
import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin, Affine
from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QImage, QPixmap, QTransform
from PySide6.QtWidgets import QApplication

from rme_mapper.backends.modern_raster import ModernGeoTiffBackend
from rme_mapper.maps.map_canvas import MapCanvas
from rme_mapper.models.map_layer import LayerRole, MapLayer
from rme_mapper.models.map_point import MapPoint
from rme_mapper.services.coordinate_service import CoordinateService


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


@pytest.fixture
def raster_without_crs(tmp_path: Path) -> Path:
    """GeoTIFF без системы координат (CRS=None)."""
    file_path = tmp_path / "no_crs.tif"
    data = np.ones((10, 10), dtype=np.uint8)
    with rasterio.open(
        file_path, "w", driver="GTiff", height=10, width=10, count=1, dtype=np.uint8, crs=None, transform=from_origin(10, 20, 1, 1)
    ) as dst:
        dst.write(data, 1)
    return file_path


@pytest.fixture
def raster_degenerate_transform(tmp_path: Path) -> Path:
    """GeoTIFF с вырожденной матрицей аффинного преобразования (det = 0)."""
    file_path = tmp_path / "degenerate.tif"
    data = np.ones((10, 10), dtype=np.uint8)
    # det = 0 * 0 - 0 * 0 = 0
    t = Affine(0, 0, 10, 0, 0, 20)
    with rasterio.open(
        file_path, "w", driver="GTiff", height=10, width=10, count=1, dtype=np.uint8, crs="EPSG:4326", transform=t
    ) as dst:
        dst.write(data, 1)
    return file_path


@pytest.fixture
def valid_geotiff(tmp_path: Path) -> Path:
    """Корректный GeoTIFF (EPSG:32637, 100x80 пикселей, размер пикселя 5м)."""
    file_path = tmp_path / "valid_utm.tif"
    w, h = 100, 80
    data = np.full((h, w), 120, dtype=np.uint8)
    # Верхний левый угол: X=500000, Y=6000000, пиксель 5м x 5м
    transform = from_origin(500000, 6000000, 5.0, 5.0)
    with rasterio.open(
        file_path, "w", driver="GTiff", height=h, width=w, count=1, dtype=np.uint8, crs="EPSG:32637", transform=transform
    ) as dst:
        dst.write(data, 1)
    return file_path


@pytest.fixture
def rotated_geotiff(tmp_path: Path) -> Path:
    """Повернутый GeoTIFF (поворот на 30 градусов)."""
    file_path = tmp_path / "rotated.tif"
    w, h = 60, 40
    data = np.full((h, w), 200, dtype=np.uint8)
    # Матрица поворота
    angle = math.radians(30)
    res = 2.0
    a = res * math.cos(angle)
    b = -res * math.sin(angle)
    c = 100000.0
    d = res * math.sin(angle)
    e = res * math.cos(angle)
    f = 200000.0
    t = Affine(a, b, c, d, e, f)

    with rasterio.open(
        file_path, "w", driver="GTiff", height=h, width=w, count=1, dtype=np.uint8, crs="EPSG:32637", transform=t
    ) as dst:
        dst.write(data, 1)
    return file_path


# =============================================================================
# Тесты валидации CRS и геопривязки
# =============================================================================

def test_13_reject_raster_without_crs(raster_without_crs: Path):
    """Проверка определения отсутствия CRS в растре."""
    backend = ModernGeoTiffBackend()
    info = backend.inspect_raster(raster_without_crs)

    assert info["crs"] is None
    assert info["is_valid_georef"] is False
    backend.close(raster_without_crs)


def test_14_reject_raster_degenerate_transform(raster_degenerate_transform: Path):
    """Проверка отклонения вырожденной аффинной матрицы трансформации."""
    backend = ModernGeoTiffBackend()
    info = backend.inspect_raster(raster_degenerate_transform)

    assert info["is_valid_georef"] is False
    backend.close(raster_degenerate_transform)


# =============================================================================
# Тесты преобразования QTransform (без вертикального переворота)
# =============================================================================

def test_15_qtransform_corner_mapping(valid_geotiff: Path):
    """Проверка корректности отображения углов растра через QTransform в координаты сцены."""
    backend = ModernGeoTiffBackend()
    info = backend.inspect_raster(valid_geotiff)
    backend.close(valid_geotiff)

    a, b, c, d, e, f = info["transform"]
    w, h = info["width"], info["height"]

    # В MapCanvas для полноразмерного растра:
    # m11 = a, m12 = -d, m21 = b, m22 = -e, dx = c, dy = -f
    # (в стандартном северном растре e < 0, поэтому m22 = -e > 0)
    transform = QTransform(float(a), float(-d), float(b), float(-e), float(c), float(-f))

    # Верхний левый пиксель (0, 0)
    pt_tl = transform.map(QPointF(0, 0))
    # В координатах карты: map_x = c = 500000, map_y = f = 6000000
    # В сцене: scene_x = 500000, scene_y = -6000000
    assert pytest.approx(pt_tl.x(), rel=1e-5) == 500000.0
    assert pytest.approx(pt_tl.y(), rel=1e-5) == -6000000.0

    # Нижний правый пиксель (w, h)
    pt_br = transform.map(QPointF(w, h))
    # map_x = 500000 + 100 * 5 = 500500, map_y = 6000000 - 80 * 5 = 5999600
    # В сцене: scene_x = 500500, scene_y = -5999600
    assert pytest.approx(pt_br.x(), rel=1e-5) == 500500.0
    assert pytest.approx(pt_br.y(), rel=1e-5) == -5999600.0

    # Проверка, что Y в сцене для нижнего края БОЛЬШЕ (т.е. ниже по экрану), чем для верхнего:
    # scene_y_bottom (-5999600) > scene_y_top (-6000000)
    # Это означает, что изображение НЕ перевернуто вверх ногами!
    assert pt_br.y() > pt_tl.y()


def test_16_qtransform_rotated_raster(rotated_geotiff: Path):
    """Проверка формирования QTransform для повернутого растра."""
    backend = ModernGeoTiffBackend()
    info = backend.inspect_raster(rotated_geotiff)
    backend.close(rotated_geotiff)

    a, b, c, d, e, f = info["transform"]
    transform = QTransform(float(a), float(-d), float(b), float(-e), float(c), float(-f))

    # Определитель не равен 0
    det = transform.determinant()
    assert abs(det) > 1e-5

    # Угол (0, 0) мапится в (c, -f)
    pt0 = transform.map(QPointF(0, 0))
    assert pytest.approx(pt0.x(), rel=1e-5) == c
    assert pytest.approx(pt0.y(), rel=1e-5) == -f


# =============================================================================
# Тесты интеграции MapCanvas с растровым слоем
# =============================================================================

def test_17_map_canvas_add_raster_item_and_scene_rect(qapp, valid_geotiff: Path):
    """Проверка добавления растрового элемента на холст MapCanvas."""
    backend = ModernGeoTiffBackend()
    rgba, meta = backend.read_preview(valid_geotiff)
    info = backend.inspect_raster(valid_geotiff)
    backend.close(valid_geotiff)

    canvas = MapCanvas()
    canvas.resize(800, 600)

    layer = MapLayer(
        id="raster_base",
        source_name="raster",
        display_name="Растр",
        geometry_type="raster",
        crs="EPSG:32637",
        role=LayerRole.RASTER,
        z_order=5,
        visible=True,
    )

    canvas.add_raster_item(
        layer=layer,
        image_or_array=rgba,
        affine_coeffs=info["transform"],
        full_size=(info["width"], info["height"]),
    )

    # Проверка наличия элемента на сцене
    assert canvas._raster_item is not None
    assert canvas._raster_item.isVisible() is True
    assert canvas._raster_item.zValue() == 5

    # Охват сцены должен соответствовать охвату растра
    scene_rect = canvas.scene().sceneRect()
    assert pytest.approx(scene_rect.left(), rel=1e-5) == 500000.0
    assert pytest.approx(scene_rect.right(), rel=1e-5) == 500500.0
    assert pytest.approx(scene_rect.top(), rel=1e-5) == -6000000.0
    assert pytest.approx(scene_rect.bottom(), rel=1e-5) == -5999600.0


def test_18_map_canvas_raster_visibility_toggle(qapp, valid_geotiff: Path):
    """Проверка переключения видимости растрового слоя на сцене."""
    backend = ModernGeoTiffBackend()
    rgba, meta = backend.read_preview(valid_geotiff)
    info = backend.inspect_raster(valid_geotiff)
    backend.close(valid_geotiff)

    canvas = MapCanvas()
    layer = MapLayer(
        id="raster_base",
        source_name="raster",
        display_name="Растр",
        geometry_type="raster",
        crs="EPSG:32637",
        role=LayerRole.RASTER,
        z_order=5,
        visible=True,
    )

    canvas.add_raster_item(
        layer=layer,
        image_or_array=rgba,
        affine_coeffs=info["transform"],
        full_size=(info["width"], info["height"]),
    )

    assert canvas.is_layer_visible("raster_base") is True
    assert canvas._raster_item.isVisible() is True

    # Скрываем растровый слой
    canvas.set_layer_visibility("raster_base", False)
    assert canvas.is_layer_visible("raster_base") is False
    assert canvas._raster_item.isVisible() is False

    # Включаем обратно
    canvas.set_layer_visibility("raster_base", True)
    assert canvas.is_layer_visible("raster_base") is True
    assert canvas._raster_item.isVisible() is True


def test_19_map_points_on_top_of_raster(qapp, valid_geotiff: Path):
    """Проверка корректного наложения точек поверх растра в единой CRS."""
    backend = ModernGeoTiffBackend()
    rgba, meta = backend.read_preview(valid_geotiff)
    info = backend.inspect_raster(valid_geotiff)
    backend.close(valid_geotiff)

    canvas = MapCanvas()

    layer = MapLayer(
        id="raster_base",
        source_name="raster",
        display_name="Растр",
        geometry_type="raster",
        crs="EPSG:32637",
        role=LayerRole.RASTER,
        z_order=5,
        visible=True,
    )

    canvas.add_raster_item(
        layer=layer,
        image_or_array=rgba,
        affine_coeffs=info["transform"],
        full_size=(info["width"], info["height"]),
    )

    # Создаем точку в центре растра: X=500250, Y=5999800
    pt = MapPoint(
        id="pt_center",
        name="Центральная вышка",
        latitude=5999800.0,
        longitude=500250.0,
        source_crs="EPSG:32637",
    )

    canvas.add_user_point(pt, map_x=500250.0, map_y=5999800.0)

    # Проверяем, что точка добавлена и ее позиция лежит внутри boundingRect растра
    raster_bounds = canvas._raster_item.sceneBoundingRect()
    point_item = canvas._user_point_items.get("pt_center")
    assert point_item is not None

    pt_scene_pos = point_item.pos()
    assert pytest.approx(pt_scene_pos.x(), rel=1e-5) == 500250.0
    assert pytest.approx(pt_scene_pos.y(), rel=1e-5) == -5999800.0
    assert raster_bounds.contains(pt_scene_pos) is True


def test_20_map_canvas_clear_map_cleanup(qapp, valid_geotiff: Path):
    """Проверка очистки растровых ресурсов при вызове clear_map()."""
    backend = ModernGeoTiffBackend()
    rgba, meta = backend.read_preview(valid_geotiff)
    info = backend.inspect_raster(valid_geotiff)
    backend.close(valid_geotiff)

    canvas = MapCanvas()
    layer = MapLayer(
        id="raster_base",
        source_name="raster",
        display_name="Растр",
        geometry_type="raster",
        crs="EPSG:32637",
        role=LayerRole.RASTER,
        z_order=5,
        visible=True,
    )

    canvas.add_raster_item(
        layer=layer,
        image_or_array=rgba,
        affine_coeffs=info["transform"],
        full_size=(info["width"], info["height"]),
    )

    assert canvas._raster_item is not None
    canvas.clear_map()

    assert canvas._raster_item is None
    assert canvas._raster_window_item is None
    assert canvas._raster_debounce_timer.isActive() is False
    assert len(canvas.scene().items()) == 0
