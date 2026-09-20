"""Тесты Этапа 19: Инструмент измерения площади (Tests 16-29)."""

import os
from pathlib import Path
import pytest
from PySide6.QtCore import QPointF, Qt
from PySide6.QtWidgets import QApplication, QGraphicsPathItem

from rme_mapper.maps.map_canvas import MapCanvas
from rme_mapper.services.coordinate_service import CoordinateService
from rme_mapper.services.geodesic_service import GeodesicService
from rme_mapper.ui.main_window import MainWindow


@pytest.fixture(scope="session")
def qapp():
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    yield app


@pytest.fixture
def default_gpkg():
    return Path(__file__).resolve().parent.parent / "maps" / "test_map" / "prepared" / "mari.gpkg"


def test_16_tool_activation_mode_and_cursor(qapp):
    """Тест 16: Активация инструмента измерения площади, установка режима и курсора."""
    canvas = MapCanvas()
    canvas.set_active_crs("OGC:CRS84")
    canvas.start_measurement("measure_area")

    assert canvas.mode == "measure_area"
    assert canvas.viewport().cursor().shape() == Qt.CursorShape.CrossCursor or canvas.cursor().shape() == Qt.CursorShape.CrossCursor


def test_17_adding_vertices_and_rubber_band(qapp):
    """Тест 17: Добавление вершин и предпросмотр полигона измерения площади."""
    canvas = MapCanvas()
    canvas.set_active_crs("OGC:CRS84")
    canvas.start_measurement("measure_area")

    canvas._add_measurement_vertex(QPointF(47.0, -56.0))
    canvas._add_measurement_vertex(QPointF(47.5, -56.0))
    canvas._update_rubber_band(QPointF(47.5, -56.5))

    # Должен появиться предпросмотр полигона с полупрозрачной заливкой
    poly_items = [it for it in canvas._measure_active_items if isinstance(it, QGraphicsPathItem)]
    assert len(poly_items) == 1
    assert poly_items[0].brush().color().alpha() > 0


def test_18_geodesic_area_calculation_known_polygon():
    """Тест 18: Геодезический расчет площади известного полигона (квадрат 1°x1° на экваторе)."""
    # 1° на экваторе ~ 111.319 км, площадь ~ 12 364 км² = 1.236e10 м²
    lons = [0.0, 1.0, 1.0, 0.0, 0.0]
    lats = [0.0, 0.0, 1.0, 1.0, 0.0]

    area_m2, perim_m = GeodesicService.calculate_area_perimeter(lons, lats)
    assert 1.22e10 < area_m2 < 1.25e10


def test_19_geodesic_perimeter_calculation():
    """Тест 19: Расчет геодезического периметра полигона."""
    # Периметр квадрата 1°x1° на экваторе ~ 4 * 111.3 км ~ 445 км
    lons = [0.0, 1.0, 1.0, 0.0, 0.0]
    lats = [0.0, 0.0, 1.0, 1.0, 0.0]

    area_m2, perim_m = GeodesicService.calculate_area_perimeter(lons, lats)
    assert 440_000.0 < perim_m < 450_000.0


def test_20_translucent_fill_rendering(qapp):
    """Тест 20: Наличие полупрозрачной заливки полигона в завершенном оверлее."""
    canvas = MapCanvas()
    canvas.set_active_crs("OGC:CRS84")
    canvas.start_measurement("measure_area")

    canvas._add_measurement_vertex(QPointF(47.0, -56.0))
    canvas._add_measurement_vertex(QPointF(47.2, -56.0))
    canvas._add_measurement_vertex(QPointF(47.2, -56.2))
    canvas._finish_measurement()

    poly_items = [it for it in canvas._finished_measurements if isinstance(it, QGraphicsPathItem)]
    assert len(poly_items) == 1
    # Альфа-канал полупрозрачный
    assert 0 < poly_items[0].brush().color().alpha() < 255


def test_21_automatic_unit_selection_area():
    """Тест 21: Автоматический выбор единиц измерения площади (м², га, км²)."""
    # 1. Менее 10 000 м² -> м²
    s_m2_ru = GeodesicService.format_area(5400.0, "ru")
    assert "5" in s_m2_ru and "м²" in s_m2_ru and "га" not in s_m2_ru

    s_m2_en = GeodesicService.format_area(5400.0, "en")
    assert "5" in s_m2_en and "m²" in s_m2_en and "ha" not in s_m2_en

    # 2. От 10 000 м² до 1 000 000 м² -> гектары (га / ha)
    s_ha_ru = GeodesicService.format_area(250_000.0, "ru")
    assert "25" in s_ha_ru and "га" in s_ha_ru

    s_ha_en = GeodesicService.format_area(250_000.0, "en")
    assert "25" in s_ha_en and "ha" in s_ha_en

    # 3. От 1 000 000 м² и более -> км² (km²)
    s_km2_ru = GeodesicService.format_area(5_500_000.0, "ru")
    assert "5.5" in s_km2_ru and "км²" in s_km2_ru

    s_km2_en = GeodesicService.format_area(5_500_000.0, "en")
    assert "5.5" in s_km2_en and "km²" in s_km2_en


def test_22_clockwise_vertex_winding():
    """Тест 22: Расчет площади при обходе вершин по часовой стрелке."""
    # По часовой стрелке
    lons_cw = [0.0, 1.0, 1.0, 0.0]
    lats_cw = [1.0, 1.0, 0.0, 0.0]

    area_cw, _ = GeodesicService.calculate_area_perimeter(lons_cw, lats_cw)
    assert area_cw > 0.0
    assert 1.22e10 < area_cw < 1.25e10


def test_23_counter_clockwise_vertex_winding():
    """Тест 23: Расчет площади против часовой стрелки и равенство результатов."""
    lons_cw = [0.0, 1.0, 1.0, 0.0]
    lats_cw = [1.0, 1.0, 0.0, 0.0]

    lons_ccw = [0.0, 0.0, 1.0, 1.0]
    lats_ccw = [0.0, 1.0, 1.0, 0.0]

    area_cw, _ = GeodesicService.calculate_area_perimeter(lons_cw, lats_cw)
    area_ccw, _ = GeodesicService.calculate_area_perimeter(lons_ccw, lats_ccw)

    assert area_cw > 0.0
    assert area_ccw > 0.0
    assert abs(area_cw - area_ccw) < 1.0  # Полное совпадение


def test_24_self_intersecting_polygon_safety():
    """Тест 24: Безопасность при самопересекающемся полигоне (отсутствие краша)."""
    # "Песочные часы" / восьмерка
    lons = [0.0, 1.0, 0.0, 1.0]
    lats = [0.0, 1.0, 1.0, 0.0]

    area, perim = GeodesicService.calculate_area_perimeter(lons, lats)
    assert isinstance(area, float)
    assert isinstance(perim, float)
    assert not (area != area)  # not NaN


def test_25_double_click_finishes_polygon(qapp):
    """Тест 25: Завершение измерения полигона по двойному клику."""
    canvas = MapCanvas()
    canvas.set_active_crs("OGC:CRS84")
    canvas.start_measurement("measure_area")

    finished = []
    canvas.measurement_finished.connect(lambda txt: finished.append(txt))

    canvas._add_measurement_vertex(QPointF(47.0, -56.0))
    canvas._add_measurement_vertex(QPointF(47.2, -56.0))
    canvas._add_measurement_vertex(QPointF(47.2, -56.2))

    canvas._finish_measurement()

    assert canvas.mode == "default"
    assert len(finished) == 1
    assert "га" in finished[0] or "м²" in finished[0] or "км²" in finished[0]
    assert canvas.has_measurements() is True


def test_26_escape_cancels_active_area_measurement(qapp):
    """Тест 26: Отмена активного измерения площади по клавише Esc."""
    canvas = MapCanvas()
    canvas.set_active_crs("OGC:CRS84")
    canvas.start_measurement("measure_area")

    cancelled = []
    canvas.measurement_cancelled.connect(lambda: cancelled.append(True))

    canvas._add_measurement_vertex(QPointF(47.0, -56.0))
    canvas._add_measurement_vertex(QPointF(47.2, -56.0))
    canvas.cancel_measurement()

    assert canvas.mode == "default"
    assert len(cancelled) == 1
    assert len(canvas._measure_vertices) == 0


def test_27_finishing_with_insufficient_vertices(qapp):
    """Тест 27: Завершение площади с < 3 вершинами отменяет измерение без падения."""
    canvas = MapCanvas()
    canvas.set_active_crs("OGC:CRS84")
    canvas.start_measurement("measure_area")

    canvas._add_measurement_vertex(QPointF(47.0, -56.0))
    canvas._add_measurement_vertex(QPointF(47.2, -56.0))
    canvas._finish_measurement()

    assert canvas.mode == "default"
    assert len(canvas._finished_measurements) == 0


def test_28_projected_crs_reprojected_for_area(qapp):
    """Тест 28: Координаты спроецированной CRS пересчитываются в WGS84 перед расчетом площади."""
    canvas = MapCanvas()
    canvas.set_active_crs("EPSG:3857")
    canvas.start_measurement("measure_area")

    # Координаты в Web Mercator вокруг Москвы
    mx1, my1 = CoordinateService.transform_xy(37.5, 55.7, "OGC:CRS84", "EPSG:3857")
    mx2, my2 = CoordinateService.transform_xy(37.7, 55.7, "OGC:CRS84", "EPSG:3857")
    mx3, my3 = CoordinateService.transform_xy(37.7, 55.8, "OGC:CRS84", "EPSG:3857")

    canvas._add_measurement_vertex(QPointF(mx1, -my1))
    canvas._add_measurement_vertex(QPointF(mx2, -my2))
    canvas._add_measurement_vertex(QPointF(mx3, -my3))

    area_m2, perim_m = canvas._calculate_current_measurement()
    assert area_m2 > 10_000_000.0  # ~ 70 км²
    assert perim_m > 10_000.0


def test_29_measurement_does_not_dirty_project(qapp, default_gpkg):
    """Тест 29: Измерение площади не грязнят проект и не влияют на Undo/Redo."""
    window = MainWindow()
    window.load_map(default_gpkg)

    assert window.project_controller.is_modified is False
    assert window.point_controller.undo_manager.can_undo is False

    # Включаем измерение площади
    window.measure_area_action.trigger()
    assert window.map_canvas.mode == "measure_area"

    window.map_canvas._add_measurement_vertex(QPointF(47.0, -56.0))
    window.map_canvas._add_measurement_vertex(QPointF(47.2, -56.0))
    window.map_canvas._add_measurement_vertex(QPointF(47.2, -56.2))
    window.map_canvas._finish_measurement()

    # Проверяем чистоту проекта
    assert window.project_controller.is_modified is False
    assert window.point_controller.undo_manager.can_undo is False

    window.close()


def test_30_cw_and_ccw_area_orientation_identical():
    """Тест 30: Обход вершин полигона по часовой (CW) и против часовой (CCW) стрелки дает одинаковую положительную площадь."""
    # Вершины квадрата
    cw_lons = [37.0, 38.0, 38.0, 37.0, 37.0]
    cw_lats = [55.0, 55.0, 56.0, 56.0, 55.0]

    ccw_lons = [37.0, 37.0, 38.0, 38.0, 37.0]
    ccw_lats = [55.0, 56.0, 56.0, 55.0, 55.0]

    area_cw, perim_cw = GeodesicService.calculate_area_perimeter(cw_lons, cw_lats)
    area_ccw, perim_ccw = GeodesicService.calculate_area_perimeter(ccw_lons, ccw_lats)

    assert area_cw > 0
    assert area_ccw > 0
    assert abs(area_cw - area_ccw) < 1e-6, f"Площади CW ({area_cw}) и CCW ({area_ccw}) должны быть строго равны"
    assert abs(perim_cw - perim_ccw) < 1e-6, f"Периметры CW ({perim_cw}) и CCW ({perim_ccw}) должны быть равны"

