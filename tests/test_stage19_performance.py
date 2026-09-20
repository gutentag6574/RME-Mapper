"""Тесты производительности для Stage 19 (GIS-инструменты).

Проверяет:
1. Быстродействие расчета координатной сетки GridCalculator (< 5 мс).
2. Быстродействие расчета масштабной линейки ScaleService (< 1 мс).
3. Быстродействие расчета геодезической длины полилинии на 1000 вершин (< 10 мс).
4. Быстродействие расчета геодезической площади полигона на 1000 вершин (< 15 мс).
5. 100x цикл создания и очистки измерений без утечек и накопления элементов на сцене.
"""

import time
import math
import pytest
from pathlib import Path
from PySide6.QtCore import QPointF
from PySide6.QtWidgets import QApplication

from rme_mapper.services.geodesic_service import GeodesicService
from rme_mapper.services.scale_service import ScaleService
from rme_mapper.services.grid_calculator import GridCalculator
from rme_mapper.maps.map_canvas import MapCanvas


@pytest.fixture
def default_gpkg() -> Path:
    """Путь к тестовому GeoPackage."""
    return Path(__file__).resolve().parent.parent / "maps" / "test_map" / "prepared" / "mari.gpkg"


def test_perf_grid_calculation():
    """Тест производительности: расчет координатной сетки GridCalculator занимает < 5 мс."""
    extent = (47.0, 56.0, 49.0, 57.5)
    # Прогрев
    GridCalculator.calculate_grid(extent, "OGC:CRS84")

    iterations = 50
    t0 = time.perf_counter()
    for _ in range(iterations):
        res = GridCalculator.calculate_grid(extent, "OGC:CRS84")
        assert res is not None
    avg_ms = ((time.perf_counter() - t0) / iterations) * 1000.0

    assert avg_ms < 5.0, f"Расчет сетки слишком медленный: {avg_ms:.2f} мс (лимит 5 мс)"


def test_perf_scale_calculation():
    """Тест производительности: расчет параметров масштабной линейки ScaleService занимает < 1 мс."""
    # Прогрев
    ScaleService.calculate_scale_for_span(
        x1=47.0,
        x2=48.0,
        y=56.63,
        pixel_span=400.0,
        active_crs="OGC:CRS84",
    )

    iterations = 200
    t0 = time.perf_counter()
    for _ in range(iterations):
        res = ScaleService.calculate_scale_for_span(
            x1=47.0,
            x2=48.0,
            y=56.63,
            pixel_span=400.0,
            active_crs="OGC:CRS84",
        )
        assert res is not None
    avg_ms = ((time.perf_counter() - t0) / iterations) * 1000.0

    assert avg_ms < 1.0, f"Расчет масштаба слишком медленный: {avg_ms:.3f} мс (лимит 1 мс)"


def test_perf_geodesic_distance_1000_vertices():
    """Тест производительности: геодезический расчет длины полилинии из 1000 вершин < 10 мс."""
    # Генерируем 1000 точек
    points = [(47.0 + 0.001 * i, 56.0 + 0.001 * (i % 10)) for i in range(1000)]

    # Прогрев
    GeodesicService.calculate_distance(points[0][0], points[0][1], points[1][0], points[1][1])

    t0 = time.perf_counter()
    total_m = 0.0
    for i in range(len(points) - 1):
        total_m += GeodesicService.calculate_distance(
            points[i][0], points[i][1], points[i + 1][0], points[i + 1][1]
        )
    elapsed_ms = (time.perf_counter() - t0) * 1000.0

    assert total_m > 0.0
    assert elapsed_ms < 10.0, f"Расчет 1000 сегментов расстояния слишком медленный: {elapsed_ms:.2f} мс"


def test_perf_geodesic_area_1000_vertices():
    """Тест производительности: расчет геодезической площади полигона из 1000 вершин < 15 мс."""
    # Регулярный 1000-угольник
    center_lon, center_lat = 47.89, 56.63
    radius_deg = 0.05
    n = 1000
    lons = [center_lon + radius_deg * math.cos(2 * math.pi * i / n) for i in range(n)]
    lats = [center_lat + radius_deg * math.sin(2 * math.pi * i / n) for i in range(n)]

    t0 = time.perf_counter()
    area_m2, perim_m = GeodesicService.calculate_area_perimeter(lons, lats)
    elapsed_ms = (time.perf_counter() - t0) * 1000.0

    assert area_m2 > 0.0
    assert perim_m > 0.0
    assert elapsed_ms < 15.0, f"Расчет площади полигона на 1000 вершин слишком медленный: {elapsed_ms:.2f} мс"


def test_perf_100x_measurement_create_clear_lifecycle(qapp):
    """Тест надежности и памяти: 100 циклов создания и очистки измерений не накапливают элементы."""
    canvas = MapCanvas()
    canvas.resize(800, 600)

    initial_items_count = len(canvas._scene.items())

    for i in range(100):
        canvas.start_measurement("measure_distance")
        canvas._add_measurement_vertex((47.0 + i * 0.001, -56.0))
        canvas._add_measurement_vertex((47.1 + i * 0.001, -56.1))
        canvas._finish_measurement()
        assert len(canvas._measure_completed_items) > 0

        # Очищаем
        canvas.clear_measurements()
        assert len(canvas._measure_completed_items) == 0
        assert len(canvas._measure_active_items) == 0
        assert len(canvas._measure_points) == 0

    final_items_count = len(canvas._scene.items())
    assert final_items_count == initial_items_count, "Элементы измерений должны полностью удаляться со сцены"
