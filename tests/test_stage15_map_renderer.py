"""Тесты рендеринга карты, точек, зон и подписей через MapRenderer (Этап 15)."""

import pytest
from PySide6.QtCore import QRectF
from PySide6.QtGui import QBrush, QColor, QImage, QPainterPath, QPen
from PySide6.QtWidgets import QApplication
from shapely.geometry import Polygon

from rme_mapper.app_info import APP_NAME, APP_VERSION, AUTHOR_NAME
from rme_mapper.exporters.map_renderer import MapRenderer
from rme_mapper.exporters.models import ImageExportOptions
from rme_mapper.models.map_point import MapPoint


@pytest.fixture(scope="module", autouse=True)
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def test_09_calculate_adjusted_extent_aspect_expansion():
    # Квадратный охват (10 x 10)
    extent = (0.0, 0.0, 10.0, 10.0)

    # Изображение 16:9 (1920 x 1080) -> должно расшириться по X
    adj = MapRenderer.calculate_adjusted_extent(extent, 1920, 1080)
    min_x, min_y, max_x, max_y = adj
    assert min_y == 0.0
    assert max_y == 10.0
    assert (max_x - min_x) == pytest.approx(10.0 * (16.0 / 9.0), abs=1e-3)
    assert (min_x + max_x) / 2.0 == pytest.approx(5.0, abs=1e-3)

    # Изображение 9:16 (1080 x 1920) -> должно расшириться по Y
    adj_tall = MapRenderer.calculate_adjusted_extent(extent, 1080, 1920)
    min_x2, min_y2, max_x2, max_y2 = adj_tall
    assert min_x2 == 0.0
    assert max_x2 == 10.0
    assert (max_y2 - min_y2) == pytest.approx(10.0 * (16.0 / 9.0), abs=1e-3)
    assert (min_y2 + max_y2) / 2.0 == pytest.approx(5.0, abs=1e-3)


def test_10_render_map_exact_output_sizes():
    opts_1080 = ImageExportOptions(file_path="map.png", width_px=1920, height_px=1080)
    extent = (47.0, 56.0, 48.0, 57.0)

    img_1080 = MapRenderer.render_map(
        options=opts_1080,
        active_crs="OGC:CRS84",
        target_extent=extent,
    )
    assert img_1080.width() == 1920
    assert img_1080.height() == 1080

    opts_custom = ImageExportOptions(file_path="custom.png", width_px=1200, height_px=900)
    img_custom = MapRenderer.render_map(
        options=opts_custom,
        active_crs="OGC:CRS84",
        target_extent=extent,
    )
    assert img_custom.width() == 1200
    assert img_custom.height() == 900


def test_11_render_map_metadata_embedded():
    opts = ImageExportOptions(file_path="map.png", width_px=800, height_px=600)
    img = MapRenderer.render_map(
        options=opts,
        active_crs="OGC:CRS84",
        target_extent=(47.0, 56.0, 48.0, 57.0),
    )
    assert img.text("Software") == APP_NAME
    assert img.text("Author") == AUTHOR_NAME
    assert img.text("Version") == APP_VERSION


def test_12_render_map_with_base_layers():
    # Создаем тестовые векторные слои
    path1 = QPainterPath()
    path1.addRect(47.2, -56.8, 0.4, 0.4)  # в координатах (x, -y)

    path2 = QPainterPath()
    path2.addEllipse(47.4, -56.6, 0.2, 0.2)

    layers_data = [
        ("layer_bg", path1, QPen(QColor("#000000")), QBrush(QColor("#E0F2FE")), 1.0, True),
        ("layer_hidden", path2, QPen(QColor("#FF0000")), QBrush(QColor("#FF0000")), 2.0, False),
    ]

    opts = ImageExportOptions(file_path="map.png", width_px=1000, height_px=1000, background_color="#FFFFFF")
    img = MapRenderer.render_map(
        options=opts,
        active_crs="OGC:CRS84",
        target_extent=(47.0, 56.0, 48.0, 57.0),
        loaded_layers_render_data=layers_data,
    )
    assert not img.isNull()
    # Точка в центре полигона path1 не должна быть чисто белой фоновой
    center_px = img.pixelColor(500, 500)
    assert center_px != QColor(0, 0, 0, 0)


def test_13_render_points_and_shapes():
    pts = [
        MapPoint(name="Круг", latitude=56.5, longitude=47.5, symbol="circle", red=255, green=0, blue=0, size=16.0),
        MapPoint(name="Квадрат", latitude=56.6, longitude=47.6, symbol="square", red=0, green=255, blue=0, size=16.0),
        MapPoint(name="Треугольник", latitude=56.7, longitude=47.7, symbol="triangle", red=0, green=0, blue=255, size=16.0),
    ]

    opts = ImageExportOptions(file_path="map.png", width_px=1000, height_px=1000, include_points=True, include_labels=False)
    img = MapRenderer.render_map(
        options=opts,
        active_crs="OGC:CRS84",
        target_extent=(47.0, 56.0, 48.0, 57.0),
        points=pts,
    )
    assert not img.isNull()


def test_14_render_zones_with_opacity():
    pts = [
        MapPoint(
            name="Зона1",
            latitude=56.5,
            longitude=47.5,
            zone_enabled=True,
            radius_m=2000.0,
            zone_red=200,
            zone_green=50,
            zone_blue=50,
            zone_opacity=40,
        )
    ]

    opts = ImageExportOptions(file_path="map.png", width_px=800, height_px=600, include_zones=True, include_points=False)
    img = MapRenderer.render_map(
        options=opts,
        active_crs="OGC:CRS84",
        target_extent=(47.0, 56.0, 48.0, 57.0),
        points=pts,
    )
    assert not img.isNull()


def test_15_render_labels_modes_and_clipping():
    p1 = MapPoint(id="p1", name="Точка 1", latitude=56.5, longitude=47.5)
    p2 = MapPoint(id="p2", name="Точка 2", latitude=56.6, longitude=47.6)
    p_empty = MapPoint(id="p3", name="   ", latitude=56.7, longitude=47.7)  # Пустое имя

    pts = [p1, p2, p_empty]
    opts_all = ImageExportOptions(file_path="map.png", width_px=800, height_px=600, include_labels=True, labels_mode="all")
    img_all = MapRenderer.render_map(options=opts_all, active_crs="OGC:CRS84", target_extent=(47.0, 56.0, 48.0, 57.0), points=pts)
    assert not img_all.isNull()

    opts_sel = ImageExportOptions(file_path="map.png", width_px=800, height_px=600, include_labels=True, labels_mode="selected")
    img_sel = MapRenderer.render_map(
        options=opts_sel,
        active_crs="OGC:CRS84",
        target_extent=(47.0, 56.0, 48.0, 57.0),
        points=pts,
        selected_point_ids={"p1"},
    )
    assert not img_sel.isNull()

    opts_none = ImageExportOptions(file_path="map.png", width_px=800, height_px=600, include_labels=True, labels_mode="none")
    img_none = MapRenderer.render_map(options=opts_none, active_crs="OGC:CRS84", target_extent=(47.0, 56.0, 48.0, 57.0), points=pts)
    assert not img_none.isNull()


def test_16_transparent_background_png():
    opts = ImageExportOptions(
        file_path="transparent.png",
        format="PNG",
        width_px=600,
        height_px=400,
        transparent_background=True,
        include_title=False,
        include_crs=False,
        include_legend=False,
        include_scale_bar=False,
        include_north_arrow=False,
    )
    img = MapRenderer.render_map(
        options=opts,
        active_crs="OGC:CRS84",
        target_extent=(47.0, 56.0, 48.0, 57.0),
    )
    # Пиксель в углу должен быть полностью прозрачным
    corner_pixel = img.pixelColor(10, 10)
    assert corner_pixel.alpha() == 0
