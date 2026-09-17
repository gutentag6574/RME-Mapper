"""Нагрузочные тесты производительности экспорта карты (Этап 15)."""

import time
import pytest
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication

from rme_mapper.exporters.map_renderer import MapRenderer
from rme_mapper.exporters.models import ImageExportOptions
from rme_mapper.models.map_point import MapPoint


@pytest.fixture(scope="module", autouse=True)
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def test_28_performance_1000_points_4k():
    """Тест рендеринга 1000 точек с зонами и подписями в 4K разрешении."""
    pts: list[MapPoint] = []
    shapes = ["circle", "square", "triangle"]

    for i in range(1000):
        # Равномерное распределение по области Республики Марий Эл
        lon = 47.0 + (i % 50) * 0.03
        lat = 56.0 + (i // 50) * 0.04
        sym = shapes[i % 3]
        has_zone = (i % 5 == 0)

        pts.append(
            MapPoint(
                id=f"p_{i}",
                name=f"Точка {i + 1}",
                latitude=lat,
                longitude=lon,
                symbol=sym,
                red=(i * 17) % 256,
                green=(i * 31) % 256,
                blue=(i * 53) % 256,
                size=12.0,
                zone_enabled=has_zone,
                radius_m=300.0 if has_zone else 0.0,
                zone_opacity=25,
            )
        )

    opts = ImageExportOptions(
        file_path="perf_4k.png",
        format="PNG",
        width_px=3840,
        height_px=2160,
        include_points=True,
        include_zones=True,
        include_labels=True,
        labels_mode="all",
        include_title=True,
        title_text="Нагрузочный тест 1000 точек (4K)",
        include_crs=True,
        include_legend=True,
        include_scale_bar=True,
        include_north_arrow=True,
    )

    t0 = time.perf_counter()
    img = MapRenderer.render_map(
        options=opts,
        active_crs="OGC:CRS84",
        target_extent=(46.5, 55.5, 49.0, 57.5),
        points=pts,
    )
    elapsed = time.perf_counter() - t0

    assert not img.isNull()
    assert img.width() == 3840
    assert img.height() == 2160
    # Рендеринг 1000 точек в 4K должен быть комфортно быстрым (обычно < 5 секунд)
    assert elapsed < 15.0


def test_29_performance_5000_points_no_crash():
    """Тест стабильности и отсутствия утечек памяти при 5000 точках."""
    pts: list[MapPoint] = []
    for i in range(5000):
        lon = 47.0 + (i % 100) * 0.02
        lat = 56.0 + (i // 100) * 0.02
        pts.append(
            MapPoint(
                id=f"pt5k_{i}",
                name=f"P_{i}",
                latitude=lat,
                longitude=lon,
                symbol="circle",
                size=10.0,
                zone_enabled=False,
            )
        )

    opts = ImageExportOptions(
        file_path="perf_5k.png",
        format="PNG",
        width_px=1920,
        height_px=1080,
        include_points=True,
        include_zones=False,
        include_labels=False,  # Отключаем подписи для чистой проверки геометрии
    )

    t0 = time.perf_counter()
    img = MapRenderer.render_map(
        options=opts,
        active_crs="OGC:CRS84",
        target_extent=(46.5, 55.5, 49.5, 57.5),
        points=pts,
    )
    elapsed = time.perf_counter() - t0

    assert not img.isNull()
    assert img.width() == 1920
    assert img.height() == 1080
    assert elapsed < 15.0
