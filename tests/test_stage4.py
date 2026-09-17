"""Тесты для Этапа 4 проекта RME-Mapper."""

import os
import pytest
from shapely.geometry import Point, Polygon

from rme_mapper.coordinates.validator import CoordinateValidator
from rme_mapper.maps.map_canvas import MapCanvas
from rme_mapper.models.map_point import MapPoint
from rme_mapper.services.coordinate_service import CoordinateService
from rme_mapper.services.point_service import PointService
from rme_mapper.ui.add_point_dialog import AddPointDialog
from rme_mapper.ui.main_window import MainWindow


@pytest.fixture(scope="session")
def qapp():
    """Фикстура для инициализации QApplication в headless-режиме."""
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    yield app


def test_map_point_creation():
    """1. Проверка создания объекта MapPoint."""
    p = MapPoint(name="Тест", latitude=56.63, longitude=47.88)
    assert p.name == "Тест"
    assert p.latitude == 56.63
    assert p.longitude == 47.88
    assert p.source_crs == "OGC:CRS84"
    assert p.visible is True
    assert len(p.id) > 0


def test_point_service_add():
    """2. Проверка добавления точки в PointService и автогенерации имени."""
    ps = PointService()
    p1 = ps.add_point(name=None, latitude=56.5, longitude=47.5)
    assert p1.name == "Точка 1"
    assert len(ps.get_points()) == 1

    p2 = ps.add_point(name="Моя точка", latitude=56.6, longitude=47.6)
    assert p2.name == "Моя точка"
    assert len(ps.get_points()) == 2


def test_point_service_remove():
    """3. Проверка удаления точки из PointService."""
    ps = PointService()
    p = ps.add_point("Точка", 56.0, 47.0)
    assert ps.get_point(p.id) is not None

    removed = ps.remove_point(p.id)
    assert removed is True
    assert ps.get_point(p.id) is None
    assert len(ps.get_points()) == 0


def test_validator_latitude_valid():
    """4. Проверка валидности широты 56.5."""
    CoordinateValidator.validate_latitude(56.5)


def test_validator_longitude_valid():
    """5. Проверка валидности долготы 47.5."""
    CoordinateValidator.validate_longitude(47.5)


def test_validator_comma_parsing():
    """6. Проверка корректного парсинга строки с запятой."""
    val = CoordinateValidator.parse_dd("56,5")
    assert val == 56.5

    lat, lon = CoordinateValidator.validate_dd_pair("56,631", "47,886")
    assert lat == 56.631
    assert lon == 47.886


def test_validator_latitude_out_of_range():
    """7 и 8. Отклонение широты > 90 и < -90."""
    with pytest.raises(ValueError, match="Широта"):
        CoordinateValidator.validate_latitude(90.1)

    with pytest.raises(ValueError, match="Широта"):
        CoordinateValidator.validate_latitude(-90.1)


def test_validator_longitude_out_of_range():
    """9. Отклонение долготы > 180 и < -180."""
    with pytest.raises(ValueError, match="Долгота"):
        CoordinateValidator.validate_longitude(180.1)

    with pytest.raises(ValueError, match="Долгота"):
        CoordinateValidator.validate_longitude(-180.1)


def test_validator_non_numeric():
    """10. Отклонение нечисловых значений."""
    with pytest.raises(ValueError):
        CoordinateValidator.parse_dd("abc")

    with pytest.raises(ValueError):
        CoordinateValidator.parse_dd("")


def test_add_point_dialog_creation(qapp):
    """11. Проверка создания диалога AddPointDialog."""
    dialog = AddPointDialog(default_name="Точка 1")
    assert dialog is not None
    assert dialog.windowTitle() == "Добавить точку"
    assert dialog.name_edit is not None
    assert dialog.lat_edit is not None
    assert dialog.lon_edit is not None


def test_main_window_has_add_button(qapp):
    """12. Проверка наличия кнопки добавления точки в MainWindow."""
    window = MainWindow()
    assert hasattr(window, "btn_add_point")
    assert hasattr(window, "btn_delete_point")
    assert hasattr(window, "points_table")
    assert window.btn_add_point.text() == "+ Добавить точку"


def test_point_added_to_table_and_canvas(qapp):
    """13 и 14. Проверка добавления точки в таблицу и на холст."""
    window = MainWindow()
    initial_rows = window.points_table.rowCount()

    point = window._point_service.add_point("Тестовая точка", 56.637, 47.886)
    window.map_canvas.add_user_point(point)
    window._add_point_to_table(point)

    assert window.points_table.rowCount() == initial_rows + 1
    assert window.map_canvas.has_user_point(point.id)

    # Проверяем отображение в ячейках таблицы
    row = window.points_table.rowCount() - 1
    assert window.points_table.item(row, 1).text() == "Тестовая точка"
    assert "56.637" in window.points_table.item(row, 2).text()
    assert "47.886" in window.points_table.item(row, 3).text()


def test_point_removal_updates_canvas_and_table(qapp):
    """15. Проверка удаления точки из таблицы и со сцены."""
    window = MainWindow()
    point = window._point_service.add_point("Удаляемая точка", 56.5, 47.5)
    window.map_canvas.add_user_point(point)
    window._add_point_to_table(point)

    row = window.points_table.rowCount() - 1
    window.points_table.selectRow(row)
    assert window.btn_delete_point.isEnabled()

    window.delete_selected_point()

    assert not window.map_canvas.has_user_point(point.id)
    assert window._point_service.get_point(point.id) is None


def test_coordinate_service_inside_boundary():
    """16. Проверка геометрического попадания точки внутрь полигона границы."""
    poly = Polygon([(45.0, 55.0), (51.0, 55.0), (51.0, 58.0), (45.0, 58.0)])

    # Внутри (Йошкар-Ола)
    assert CoordinateService.is_point_inside_boundary(47.886, 56.637, poly) is True

    # Снаружи (Москва)
    assert CoordinateService.is_point_inside_boundary(37.617, 55.755, poly) is False


def test_point_outside_boundary_handling(qapp):
    """17. Проверка обработки точки за границей без аварийного завершения."""
    poly = Polygon([(45.0, 55.0), (51.0, 55.0), (51.0, 58.0), (45.0, 58.0)])
    dialog = AddPointDialog(boundary_geometry=poly)

    dialog.name_edit.setText("Москва")
    dialog.lat_edit.setText("55.755")
    dialog.lon_edit.setText("37.617")

    # Валидация координат проходит корректно
    lat, lon = CoordinateValidator.validate_dd_pair(dialog.lat_edit.text(), dialog.lon_edit.text())
    assert lat == 55.755
    assert lon == 37.617

    # Геометрическая проверка фиксирует нахождение за границей
    assert CoordinateService.is_point_inside_boundary(lon, lat, poly) is False
