"""Тесты высококачественного экспорта и оффскрин-рендеринга GeoTIFF (Этап 16)."""

from pathlib import Path
import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin
from PySide6.QtGui import QColor, QImage
from PySide6.QtWidgets import QApplication

from rme_mapper.exporters.image_export_service import ImageExportService
from rme_mapper.exporters.map_renderer import MapRenderer
from rme_mapper.exporters.models import ImageExportOptions
from rme_mapper.models.map_point import MapPoint


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


@pytest.fixture
def export_test_geotiff(tmp_path: Path) -> Path:
    """Создание тестового растра для проверки экспорта (100x80, яркий градиент)."""
    file_path = tmp_path / "export_geotiff.tif"
    w, h = 100, 80
    data = np.full((h, w), 220, dtype=np.uint8)
    # nodata в одном углу (5x5)
    data[0:5, 0:5] = 0
    transform = from_origin(500000, 6000000, 10.0, 10.0)

    with rasterio.open(
        file_path,
        "w",
        driver="GTiff",
        height=h,
        width=w,
        count=1,
        dtype=np.uint8,
        crs="EPSG:32637",
        transform=transform,
        nodata=0,
    ) as dst:
        dst.write(data, 1)

    return file_path


# =============================================================================
# Тесты MapRenderer с растром
# =============================================================================

def test_26_map_renderer_renders_raster_layer(qapp, export_test_geotiff: Path):
    """Проверка рендеринга растровой подложки в MapRenderer."""
    extent = (500000.0, 5999200.0, 501000.0, 6000000.0)
    opts = ImageExportOptions(
        file_path="dummy.png",
        format="PNG",
        width_px=500,
        height_px=400,
        background_color="#FFFFFF",
        transparent_background=False,
    )

    # 1. Рендеринг с включенным растром
    img_with_raster = MapRenderer.render_map(
        options=opts,
        active_crs="EPSG:32637",
        target_extent=extent,
        raster_source=export_test_geotiff,
        is_raster_visible=True,
    )

    assert isinstance(img_with_raster, QImage)
    assert img_with_raster.width() == 500
    assert img_with_raster.height() == 400

    # Проверяем цвет центрального пикселя:
    # В растре значение 220 (серый), поэтому цвет не должен быть чисто белым (#FFFFFF)
    center_color = img_with_raster.pixelColor(250, 200)
    assert center_color.red() < 255 or center_color.green() < 255 or center_color.blue() < 255

    # 2. Рендеринг с выключенным растром
    img_no_raster = MapRenderer.render_map(
        options=opts,
        active_crs="EPSG:32637",
        target_extent=extent,
        raster_source=export_test_geotiff,
        is_raster_visible=False,
    )

    # При выключенном растре фон должен остаться чисто белым
    no_raster_center = img_no_raster.pixelColor(250, 200)
    assert no_raster_center.name().upper() == "#FFFFFF"


def test_27_map_renderer_with_points_and_zones_on_raster(qapp, export_test_geotiff: Path):
    """Проверка наложения векторных точек и геодезических зон поверх растра."""
    extent = (500000.0, 5999200.0, 501000.0, 6000000.0)

    # Создаем красную точку в центре
    pt = MapPoint(
        id="pt1",
        name="Точка на растре",
        latitude=5999600.0,
        longitude=500500.0,
        source_crs="EPSG:32637",
        red=255,
        green=0,
        blue=0,
        size=12,
        zone_enabled=True,
        radius_m=200.0,
    )

    opts = ImageExportOptions(
        file_path="dummy.png",
        format="PNG",
        width_px=600,
        height_px=480,
        include_points=True,
        include_zones=True,
        include_labels=True,
        include_scale_bar=True,
        include_north_arrow=True,
        include_legend=True,
    )

    img = MapRenderer.render_map(
        options=opts,
        active_crs="EPSG:32637",
        target_extent=extent,
        points=[pt],
        selected_point_ids={"pt1"},
        raster_source=export_test_geotiff,
        is_raster_visible=True,
    )

    assert isinstance(img, QImage)
    assert not img.isNull()


# =============================================================================
# Тесты ImageExportService (Файловый экспорт PNG / JPEG)
# =============================================================================

def test_28_image_export_service_png_with_raster(qapp, tmp_path: Path, export_test_geotiff: Path):
    """Проверка экспорта в PNG с прозрачностью и растром."""
    out_file = tmp_path / "exported_map.png"
    extent = (500000.0, 5999200.0, 501000.0, 6000000.0)

    opts = ImageExportOptions(
        file_path=str(out_file),
        format="PNG",
        width_px=400,
        height_px=320,
        transparent_background=True,
    )

    res_path = ImageExportService.export_image(
        options=opts,
        active_crs="EPSG:32637",
        target_extent=extent,
        raster_source=export_test_geotiff,
        is_raster_visible=True,
    )

    assert res_path.exists()
    assert res_path.stat().st_size > 0

    img = QImage(str(res_path))
    assert not img.isNull()
    assert img.width() == 400
    assert img.height() == 320


def test_29_image_export_service_jpeg_with_raster(qapp, tmp_path: Path, export_test_geotiff: Path):
    """Проверка экспорта в JPEG с растром."""
    out_file = tmp_path / "exported_map.jpg"
    extent = (500000.0, 5999200.0, 501000.0, 6000000.0)

    opts = ImageExportOptions(
        file_path=str(out_file),
        format="JPEG",
        width_px=400,
        height_px=320,
        jpeg_quality=90,
    )

    res_path = ImageExportService.export_image(
        options=opts,
        active_crs="EPSG:32637",
        target_extent=extent,
        raster_source=export_test_geotiff,
        is_raster_visible=True,
    )

    assert res_path.exists()
    assert res_path.stat().st_size > 0

    img = QImage(str(res_path))
    assert not img.isNull()
    assert img.width() == 400
    assert img.height() == 320
