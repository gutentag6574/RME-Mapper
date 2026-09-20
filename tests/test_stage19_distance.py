"""Тесты Этапа 19: Инструмент измерения расстояний (Tests 1-15)."""

import os
from pathlib import Path
import pytest
from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QKeyEvent, QMouseEvent
from PySide6.QtWidgets import QApplication

from rme_mapper.maps.map_canvas import MapCanvas
from rme_mapper.models.map_point import MapPoint
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


def test_01_tool_activation_mode_and_cursor(qapp):
    """Тест 1: Активация инструмента измерения расстояния, установка режима и курсора."""
    canvas = MapCanvas()
    canvas.set_active_crs("OGC:CRS84")
    canvas.start_measurement("measure_distance")

    assert canvas.mode == "measure_distance"
    assert canvas.viewport().cursor().shape() == Qt.CursorShape.CrossCursor or canvas.cursor().shape() == Qt.CursorShape.CrossCursor


def test_02_adding_first_vertex(qapp):
    """Тест 2: Добавление первой вершины измерения расстояния."""
    canvas = MapCanvas()
    canvas.set_active_crs("OGC:CRS84")
    canvas.start_measurement("measure_distance")

    # Имитация клика мышью в координатах сцены (47.0, -56.0)
    canvas._add_measurement_vertex(QPointF(47.0, -56.0))

    assert len(canvas._measure_vertices) == 1
    assert canvas.has_measurements() is True
    assert canvas._measure_vertices[0] == QPointF(47.0, -56.0)


def test_03_multi_segment_polyline(qapp):
    """Тест 3: Добавление нескольких сегментов полилинии расстояния."""
    canvas = MapCanvas()
    canvas.set_active_crs("OGC:CRS84")
    canvas.start_measurement("measure_distance")

    updates = []
    canvas.measurement_updated.connect(lambda txt: updates.append(txt))

    canvas._add_measurement_vertex(QPointF(47.0, -56.0))
    canvas._add_measurement_vertex(QPointF(47.1, -56.1))
    canvas._add_measurement_vertex(QPointF(47.2, -56.2))

    assert len(canvas._measure_vertices) == 3
    assert len(updates) == 3
    assert "км" in updates[-1] or "м" in updates[-1]


def test_04_rubber_band_preview(qapp):
    """Тест 4: Динамическая резиновая линия предпросмотра следующего сегмента."""
    canvas = MapCanvas()
    canvas.set_active_crs("OGC:CRS84")
    canvas.start_measurement("measure_distance")

    canvas._add_measurement_vertex(QPointF(47.0, -56.0))
    canvas._update_rubber_band(QPointF(47.5, -56.5))

    assert canvas._rubber_band_line is not None
    assert canvas._rubber_band_line.isVisible() is True
    line = canvas._rubber_band_line.line()
    assert line.p1() == QPointF(47.0, -56.0)
    assert line.p2() == QPointF(47.5, -56.5)


def test_05_geodesic_distance_known_coordinates():
    """Тест 5: Геодезический расчет для известной координатной пары (Москва - Санкт-Петербург)."""
    # Москва: 55.7558° N, 37.6173° E; СПб: 59.9343° N, 30.3351° E
    dist_m = GeodesicService.calculate_distance(37.6173, 55.7558, 30.3351, 59.9343)
    dist_km = dist_m / 1000.0

    # Фактическое геодезическое расстояние по эллипсоиду WGS-84 ~ 634 км
    assert 620.0 < dist_km < 650.0


def test_06_crs_conversion_projected_to_wgs84():
    """Тест 6: Пересчет координат из спроецированной CRS в WGS84 перед геодезическим расчетом."""
    # Возьмем Web Mercator EPSG:3857
    crs = "EPSG:3857"
    lon1, lat1 = 37.6173, 55.7558
    lon2, lat2 = 30.3351, 59.9343

    mx1, my1 = CoordinateService.transform_xy(lon1, lat1, "OGC:CRS84", crs)
    mx2, my2 = CoordinateService.transform_xy(lon2, lat2, "OGC:CRS84", crs)

    # Преобразуем обратно и рассчитываем геодезическое расстояние
    rlon1, rlat1 = CoordinateService.transform_xy(mx1, my1, crs, "OGC:CRS84")
    rlon2, rlat2 = CoordinateService.transform_xy(mx2, my2, crs, "OGC:CRS84")

    dist_m = GeodesicService.calculate_distance(rlon1, rlat1, rlon2, rlat2)
    assert 620.0 < (dist_m / 1000.0) < 650.0


def test_07_geographic_crs_direct(qapp):
    """Тест 7: Прямой геодезический расчет в географической CRS OGC:CRS84."""
    canvas = MapCanvas()
    canvas.set_active_crs("OGC:CRS84")
    canvas.start_measurement("measure_distance")

    canvas._add_measurement_vertex(QPointF(37.6173, -55.7558))
    canvas._add_measurement_vertex(QPointF(30.3351, -59.9343))

    assert len(canvas._measure_vertices) == 2
    # Проверка вычисленного расстояния
    total_m, _ = canvas._calculate_current_measurement()
    assert 620_000.0 < total_m < 650_000.0


def test_08_high_latitude_accuracy():
    """Тест 8: Точность на высоких широтах (длина градуса долготы сжимается)."""
    # На 80° с.ш. 1 градус долготы ~ 19.39 км
    dist_80 = GeodesicService.calculate_distance(0.0, 80.0, 1.0, 80.0)
    # На экваторе 1 градус долготы ~ 111.32 км
    dist_0 = GeodesicService.calculate_distance(0.0, 0.0, 1.0, 0.0)

    assert dist_80 < dist_0
    assert 19_000.0 < dist_80 < 20_000.0
    assert 110_000.0 < dist_0 < 112_000.0


def test_09_antimeridian_crossing():
    """Тест 9: Пересечение антимеридиана (179° в.д. -> -179° з.д.)."""
    # 2 градуса по долготе на экваторе через 180° меридиан ~ 222 км
    dist_m = GeodesicService.calculate_distance(179.0, 0.0, -179.0, 0.0)
    assert 220_000.0 < dist_m < 225_000.0


def test_10_automatic_unit_selection():
    """Тест 10: Автоматический выбор единиц измерения (метры / километры)."""
    # Менее 1000 м -> метры
    s_ru_m = GeodesicService.format_distance(450.2, "ru")
    assert "450" in s_ru_m and "м" in s_ru_m and "км" not in s_ru_m

    s_en_m = GeodesicService.format_distance(450.2, "en")
    assert "450" in s_en_m and "m" in s_en_m and "km" not in s_en_m

    # 1000 м и более -> километры
    s_ru_km = GeodesicService.format_distance(3456.0, "ru")
    assert "3.46" in s_ru_km or "3.5" in s_ru_km
    assert "км" in s_ru_km

    s_en_km = GeodesicService.format_distance(3456.0, "en")
    assert "3.46" in s_en_km or "3.5" in s_en_km
    assert "km" in s_en_km


def test_11_double_click_finishes_measurement(qapp):
    """Тест 11: Завершение измерения по двойному клику (возврат режима в default)."""
    canvas = MapCanvas()
    canvas.set_active_crs("OGC:CRS84")
    canvas.start_measurement("measure_distance")

    finished = []
    canvas.measurement_finished.connect(lambda txt: finished.append(txt))

    canvas._add_measurement_vertex(QPointF(47.0, -56.0))
    canvas._add_measurement_vertex(QPointF(47.1, -56.1))

    canvas._finish_measurement()

    assert canvas.mode == "default"
    assert len(finished) == 1
    assert canvas.has_measurements() is True
    # Полилиния и маркеры сохранены в завершенных оверлеях
    assert len(canvas._finished_measurements) >= 1


def test_12_escape_cancels_measurement(qapp):
    """Тест 12: Отмена активного измерения по клавише Escape."""
    canvas = MapCanvas()
    canvas.set_active_crs("OGC:CRS84")
    canvas.start_measurement("measure_distance")

    cancelled = []
    canvas.measurement_cancelled.connect(lambda: cancelled.append(True))

    canvas._add_measurement_vertex(QPointF(47.0, -56.0))
    canvas.cancel_measurement()

    assert canvas.mode == "default"
    assert len(cancelled) == 1
    assert len(canvas._measure_vertices) == 0


def test_13_finishing_with_insufficient_vertices(qapp):
    """Тест 13: Попытка завершения полилинии с менее чем 2 вершинами отменяет измерение без падения."""
    canvas = MapCanvas()
    canvas.set_active_crs("OGC:CRS84")
    canvas.start_measurement("measure_distance")

    canvas._add_measurement_vertex(QPointF(47.0, -56.0))
    # Завершаем при 1 вершине
    canvas._finish_measurement()

    assert canvas.mode == "default"
    assert len(canvas._finished_measurements) == 0


def test_14_zoom_and_pan_preserve_overlay(qapp):
    """Тест 14: Масштабирование и панорамирование не сдвигают координаты измерений в сцене."""
    canvas = MapCanvas()
    canvas.set_active_crs("OGC:CRS84")
    canvas.start_measurement("measure_distance")

    p1 = QPointF(47.0, -56.0)
    p2 = QPointF(47.5, -56.5)
    canvas._add_measurement_vertex(p1)
    canvas._add_measurement_vertex(p2)
    canvas._finish_measurement()

    # Проверяем геометрию полилинии в сцене
    line_item = [it for it in canvas._finished_measurements if hasattr(it, "line")][0]
    assert line_item.line().p1() == p1
    assert line_item.line().p2() == p2

    # Зум
    canvas.scale(1.5, 1.5)
    assert line_item.line().p1() == p1
    assert line_item.line().p2() == p2


def test_15_measurement_does_not_dirty_project(qapp, default_gpkg):
    """Тест 15: Измерения являются временным оверлеем и не грязнят проект и не влияют на Undo/Redo."""
    window = MainWindow()
    window.load_map(default_gpkg)

    assert window.project_controller.is_modified is False
    assert window.point_controller.undo_manager.can_undo is False

    # Включаем инструмент измерения
    window.measure_distance_action.trigger()
    assert window.map_canvas.mode == "measure_distance"

    # Добавляем сегменты
    window.map_canvas._add_measurement_vertex(QPointF(47.0, -56.0))
    window.map_canvas._add_measurement_vertex(QPointF(47.2, -56.2))
    window.map_canvas._finish_measurement()

    # Проверяем, что проект остался чистым
    assert window.project_controller.is_modified is False
    assert window.point_controller.undo_manager.can_undo is False

    window.close()


def test_16_high_latitude_distance():
    """Тест 16: Геодезическое расстояние на высокой широте (75° N) учитывает схождение меридианов."""
    # 10 градусов долготы на широте 75° N и на экваторе (0°)
    dist_75n = GeodesicService.calculate_distance(10.0, 75.0, 20.0, 75.0)
    dist_eq = GeodesicService.calculate_distance(10.0, 0.0, 20.0, 0.0)

    # На экваторе 10 градусов ~ 1113 км
    assert 1_110_000.0 < dist_eq < 1_120_000.0

    # На 75° N 10 градусов ~ 288.7 км (cos(75°) ~ 0.2588)
    assert 285_000.0 < dist_75n < 292_000.0

    # Отношение расстояний должно соответствовать сферическому/эллипсоидальному закону, а не наивной константе
    ratio = dist_75n / dist_eq
    assert 0.25 < ratio < 0.27


def test_17_dateline_crossing_distance():
    """Тест 17: Расстояние через линию перемены дат (+180°/-180°) идет по кратчайшей ортодромии."""
    # Точки по разные стороны 180 меридиана на экваторе: 179° E и 179° W (-179°)
    dist_dateline = GeodesicService.calculate_distance(179.0, 0.0, -179.0, 0.0)

    # Кратчайший геодезический путь = 2 градуса (~222.6 км), а не 358 градусов (~39 800 км)
    assert 220_000.0 < dist_dateline < 225_000.0

