"""Тесты моделей опций и рендерера картографического оформления (Этап 15)."""

import math
from pathlib import Path
import pytest
from PySide6.QtCore import QRectF
from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtWidgets import QApplication

from rme_mapper.exporters.decorations import MapDecorationRenderer
from rme_mapper.exporters.models import (
    ImageExportOptions,
    MAX_IMAGE_DIMENSION,
    MIN_IMAGE_DIMENSION,
)
from rme_mapper.models.map_point import MapPoint


@pytest.fixture(scope="module", autouse=True)
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def test_01_image_export_options_defaults():
    opts = ImageExportOptions(file_path="map.png")
    assert opts.format == "PNG"
    assert opts.width_px == 1920
    assert opts.height_px == 1080
    assert opts.extent_mode == "current_view"
    assert opts.include_points is True
    assert opts.include_zones is True
    assert opts.include_labels is True
    assert opts.include_title is True
    assert opts.include_crs is True
    assert opts.include_legend is True
    assert opts.include_scale_bar is True
    assert opts.include_north_arrow is True
    assert opts.jpeg_quality == 92
    assert opts.transparent_background is False
    assert opts.validate() == []


def test_02_image_export_options_normalization_and_validation():
    opts = ImageExportOptions(file_path="", format="jpg")
    assert opts.normalized_format() == "JPEG"
    errs = opts.validate()
    assert any("Не указан путь" in e for e in errs)

    opts.file_path = "out.jpg"
    assert opts.validate() == []

    # Некорректный размер
    opts.width_px = 100
    assert any(str(MIN_IMAGE_DIMENSION) in e for e in opts.validate())

    opts.width_px = 20000
    assert any(str(MAX_IMAGE_DIMENSION) in e for e in opts.validate())

    # Память
    opts.width_px = 16384
    opts.height_px = 16384
    assert any("Превышен допустимый объем памяти" in e for e in opts.validate())


def test_03_scale_factor_calculation():
    opts_1080 = ImageExportOptions(file_path="out.png", width_px=1920, height_px=1080)
    assert abs(opts_1080.scale_factor() - 1.0) < 1e-4

    opts_4k = ImageExportOptions(file_path="out.png", width_px=3840, height_px=2160)
    assert abs(opts_4k.scale_factor() - 2.0) < 1e-4

    opts_tiny = ImageExportOptions(file_path="out.png", width_px=300, height_px=200)
    assert opts_tiny.scale_factor() == 0.5  # Ограничение min 0.5


def test_04_render_title():
    img = QImage(800, 600, QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(QColor("#FFFFFF"))
    p = QPainter(img)

    rect = MapDecorationRenderer.render_title(
        painter=p,
        title="Тестовая карта Республики",
        image_rect=QRectF(0, 0, 800, 600),
        scale_factor=1.0,
        margin=20.0,
    )
    p.end()

    assert not rect.isEmpty()
    assert rect.center().x() == pytest.approx(400.0, abs=2.0)
    assert rect.top() == 20.0


def test_05_render_crs_label():
    img = QImage(800, 600, QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(QColor("#FFFFFF"))
    p = QPainter(img)

    rect = MapDecorationRenderer.render_crs_label(
        painter=p,
        crs_str="EPSG:3857",
        image_rect=QRectF(0, 0, 800, 600),
        scale_factor=1.0,
        margin=20.0,
    )
    p.end()

    assert not rect.isEmpty()
    assert rect.left() == 20.0
    assert rect.bottom() == pytest.approx(580.0, abs=2.0)


def test_06_render_legend_dynamic_elements():
    pts = [
        MapPoint(name="P1", latitude=56.0, longitude=47.0, symbol="circle", zone_enabled=False),
        MapPoint(name="P2", latitude=56.1, longitude=47.1, symbol="square", zone_enabled=True, radius_m=500.0),
    ]

    img = QImage(800, 600, QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(QColor("#FFFFFF"))
    p = QPainter(img)

    # Без зон
    rect_no_zone = MapDecorationRenderer.render_legend(
        painter=p,
        points=pts,
        include_zones=False,
        position="bottom_right",
        image_rect=QRectF(0, 0, 800, 600),
        scale_factor=1.0,
        margin=20.0,
    )
    assert not rect_no_zone.isEmpty()
    assert rect_no_zone.right() == pytest.approx(780.0, abs=2.0)

    # С зонами
    rect_with_zone = MapDecorationRenderer.render_legend(
        painter=p,
        points=pts,
        include_zones=True,
        position="top_left",
        image_rect=QRectF(0, 0, 800, 600),
        scale_factor=1.0,
        margin=20.0,
    )
    assert not rect_with_zone.isEmpty()
    assert rect_with_zone.left() == 20.0
    # С зонами высота легенды больше
    assert rect_with_zone.height() > rect_no_zone.height()

    p.end()


def test_07_render_scale_bar():
    img = QImage(1920, 1080, QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(QColor("#FFFFFF"))
    p = QPainter(img)

    # Охват в WGS84 вокруг Йошкар-Олы
    extent = (47.0, 56.0, 48.5, 57.0)
    rect = MapDecorationRenderer.render_scale_bar(
        painter=p,
        extent=extent,
        active_crs="OGC:CRS84",
        image_width=1920,
        scale_factor=1.0,
        margin=24.0,
        image_rect=QRectF(0, 0, 1920, 1080),
    )
    p.end()

    assert not rect.isEmpty()
    assert rect.bottom() == pytest.approx(1080 - 24, abs=2.0)


def test_08_true_north_angle_and_arrow():
    extent = (47.0, 56.0, 48.0, 57.0)
    # В географической OGC:CRS84 меридиан направлен строго вверх
    angle = MapDecorationRenderer.calculate_true_north_angle(extent, "OGC:CRS84")
    assert abs(angle) < 1.0  # угол около 0 градусов

    img = QImage(800, 600, QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(QColor("#FFFFFF"))
    p = QPainter(img)

    rect = MapDecorationRenderer.render_north_arrow(
        painter=p,
        extent=extent,
        active_crs="OGC:CRS84",
        image_rect=QRectF(0, 0, 800, 600),
        scale_factor=1.0,
        margin=20.0,
    )
    p.end()

    assert not rect.isEmpty()
    assert rect.top() == 20.0
    assert rect.right() == pytest.approx(780.0, abs=2.0)
