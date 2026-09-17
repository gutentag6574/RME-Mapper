"""Тесты для Этапа 6 проекта RME-Mapper: стилизация, редактирование и свойства точек."""

import os
import pytest
from PySide6.QtGui import QColor
from shapely.geometry import Polygon

from rme_mapper.maps.map_canvas import MapCanvas
from rme_mapper.models.map_point import MapPoint
from rme_mapper.models.point_style import PointStyle, StyleValidator
from rme_mapper.services.coordinate_service import CoordinateService
from rme_mapper.services.point_service import PointService
from rme_mapper.ui.add_point_dialog import AddPointDialog, PointDialog
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


def test_1_map_point_has_style_fields():
    """1. MapPoint имеет style-поля с корректными значениями по умолчанию."""
    p = MapPoint(name="Тест", latitude=56.0, longitude=47.0)
    assert hasattr(p, "symbol")
    assert hasattr(p, "size")
    assert hasattr(p, "red")
    assert hasattr(p, "green")
    assert hasattr(p, "blue")
    assert p.symbol == "circle"
    assert p.size == 12.0
    assert p.red == 220
    assert p.green == 30
    assert p.blue == 30
    assert isinstance(p.style, PointStyle)


def test_2_circle_symbol_creation():
    """2. circle корректно создается и валидируется."""
    p = MapPoint("Круг", 56.0, 47.0, symbol="circle")
    assert p.symbol == "circle"
    assert StyleValidator.validate_symbol("circle") == "circle"
    assert StyleValidator.validate_symbol("CIRCLE") == "circle"


def test_3_square_symbol_creation():
    """3. square корректно создается и валидируется."""
    p = MapPoint("Квадрат", 56.0, 47.0, symbol="square")
    assert p.symbol == "square"
    assert StyleValidator.validate_symbol("square") == "square"


def test_4_triangle_symbol_creation():
    """4. triangle корректно создается и валидируется."""
    p = MapPoint("Треугольник", 56.0, 47.0, symbol="triangle")
    assert p.symbol == "triangle"
    assert StyleValidator.validate_symbol("triangle") == "triangle"


def test_5_rgb_min_boundary_valid():
    """5. RGB 0/0/0 корректен."""
    r, g, b = StyleValidator.validate_rgb(0, 0, 0)
    assert (r, g, b) == (0, 0, 0)

    r, g, b = StyleValidator.validate_rgb("0", "0", "0")
    assert (r, g, b) == (0, 0, 0)


def test_6_rgb_max_boundary_valid():
    """6. RGB 255/255/255 корректен."""
    r, g, b = StyleValidator.validate_rgb(255, 255, 255)
    assert (r, g, b) == (255, 255, 255)


def test_7_rgb_negative_rejected():
    """7. RGB -1 отклоняется."""
    with pytest.raises(ValueError, match="0 до 255"):
        StyleValidator.validate_rgb(-1, 100, 100)

    with pytest.raises(ValueError, match="0 до 255"):
        StyleValidator.validate_rgb_component("-1", "Red")


def test_8_rgb_overflow_rejected():
    """8. RGB 256 отклоняется."""
    with pytest.raises(ValueError, match="0 до 255"):
        StyleValidator.validate_rgb(256, 100, 100)

    with pytest.raises(ValueError, match="0 до 255"):
        StyleValidator.validate_rgb_component("300", "Blue")


def test_9_size_min_allowed():
    """9. размер 4.0 допустим."""
    assert StyleValidator.validate_size(4.0) == 4.0
    assert StyleValidator.validate_size("4") == 4.0


def test_10_size_max_allowed():
    """10. размер 50.0 допустим."""
    assert StyleValidator.validate_size(50.0) == 50.0
    assert StyleValidator.validate_size("50") == 50.0


def test_11_size_below_min_rejected():
    """11. размер меньше min отклоняется."""
    with pytest.raises(ValueError, match="от 4.0 до 50.0"):
        StyleValidator.validate_size(3.9)

    with pytest.raises(ValueError, match="от 4.0 до 50.0"):
        StyleValidator.validate_size("0")


def test_12_size_above_max_rejected():
    """12. размер больше max отклоняется."""
    with pytest.raises(ValueError, match="от 4.0 до 50.0"):
        StyleValidator.validate_size(50.1)

    with pytest.raises(ValueError, match="от 4.0 до 50.0"):
        StyleValidator.validate_size("100")


def test_13_point_service_updates_name():
    """13. PointService обновляет имя точки."""
    ps = PointService()
    p = ps.add_point("Старое имя", 56.0, 47.0)
    updated = ps.update_point(p.id, name="Новое имя")
    assert updated.name == "Новое имя"
    assert ps.get_point(p.id).name == "Новое имя"


def test_14_point_service_updates_coordinates():
    """14. PointService обновляет координаты точки."""
    ps = PointService()
    p = ps.add_point("Точка", 56.0, 47.0)
    updated = ps.update_point(p.id, latitude=56.63, longitude=47.88)
    assert updated.latitude == 56.63
    assert updated.longitude == 47.88


def test_15_point_service_updates_symbol():
    """15. PointService обновляет symbol."""
    ps = PointService()
    p = ps.add_point("Точка", 56.0, 47.0, symbol="circle")
    updated = ps.update_point(p.id, symbol="square")
    assert updated.symbol == "square"
    assert ps.get_point(p.id).symbol == "square"


def test_16_point_service_updates_rgb():
    """16. PointService обновляет RGB."""
    ps = PointService()
    p = ps.add_point("Точка", 56.0, 47.0)
    updated = ps.update_point(p.id, red=10, green=20, blue=30)
    assert (updated.red, updated.green, updated.blue) == (10, 20, 30)


def test_17_point_service_updates_size():
    """17. PointService обновляет size."""
    ps = PointService()
    p = ps.add_point("Точка", 56.0, 47.0, size=12.0)
    updated = ps.update_point(p.id, size=24.0)
    assert updated.size == 24.0


def test_18_point_id_preserved_after_edit():
    """18. id после редактирования сохраняется."""
    ps = PointService()
    p = ps.add_point("Точка ID", 56.0, 47.0)
    original_id = p.id
    updated = ps.update_point(original_id, name="Измененное имя", size=18.0)
    assert updated.id == original_id
    assert ps.get_point(original_id).id == original_id


def test_19_map_canvas_updates_marker_without_duplicate(qapp):
    """19. MapCanvas обновляет маркер без создания дубликата."""
    canvas = MapCanvas()
    point = MapPoint(name="Маркер", latitude=56.0, longitude=47.0)
    canvas.add_user_point(point)
    assert len(canvas._user_point_items) == 1

    point.name = "Обновленный маркер"
    canvas.update_user_point(point)
    assert len(canvas._user_point_items) == 1
    assert canvas.has_user_point(point.id)


def test_20_changing_coordinates_moves_marker(qapp):
    """20. Изменение координат перемещает маркер."""
    canvas = MapCanvas()
    point = MapPoint(name="Маркер", latitude=56.0, longitude=47.0)
    canvas.add_user_point(point)

    point.latitude = 57.5
    point.longitude = 48.5
    canvas.update_user_point(point)

    item = canvas._user_point_items[point.id]
    pos = item.pos()
    assert pos.x() == pytest.approx(48.5)
    assert pos.y() == pytest.approx(-57.5)


def test_21_changing_color_updates_marker(qapp):
    """21. Изменение цвета обновляет маркер."""
    canvas = MapCanvas()
    point = MapPoint(name="Маркер", latitude=56.0, longitude=47.0, red=220, green=30, blue=30)
    canvas.add_user_point(point)

    point.red = 0
    point.green = 180
    point.blue = 0
    canvas.update_user_point(point)

    item = canvas._user_point_items[point.id]
    color = item.brush().color()
    assert color.red() == 0
    assert color.green() == 180
    assert color.blue() == 0


def test_22_changing_shape_updates_marker(qapp):
    """22. Изменение формы обновляет маркер."""
    canvas = MapCanvas()
    point = MapPoint(name="Маркер", latitude=56.0, longitude=47.0, symbol="circle")
    canvas.add_user_point(point)

    point.symbol = "triangle"
    canvas.update_user_point(point)

    item = canvas._user_point_items[point.id]
    path = item.path()
    assert not path.isEmpty()
    assert path.elementCount() >= 3


def test_23_changing_size_updates_marker(qapp):
    """23. Изменение размера обновляет маркер."""
    canvas = MapCanvas()
    point = MapPoint(name="Маркер", latitude=56.0, longitude=47.0, symbol="square", size=12.0)
    canvas.add_user_point(point)

    point.size = 28.0
    canvas.update_user_point(point)

    item = canvas._user_point_items[point.id]
    bounds = item.path().boundingRect()
    assert bounds.width() == pytest.approx(28.0, abs=0.5)
    assert bounds.height() == pytest.approx(28.0, abs=0.5)


def test_24_point_dialog_create_mode(qapp):
    """24. PointDialog работает в режиме CREATE."""
    dialog = PointDialog(default_name="Новая точка", mode="CREATE")
    assert dialog.mode == "CREATE"
    assert dialog.windowTitle() == "Добавить точку"
    assert dialog.btn_add.text() == "Добавить"
    assert dialog.name_edit.placeholderText() == "Новая точка"
    assert dialog.size_spin.value() == 12.0


def test_25_point_dialog_edit_mode(qapp):
    """25. PointDialog работает в режиме EDIT с предзаполнением полей."""
    point = MapPoint(
        name="Йошкар-Ола",
        latitude=56.63,
        longitude=47.88,
        symbol="square",
        size=20.0,
        red=15,
        green=25,
        blue=35,
    )
    dialog = PointDialog(point=point)
    assert dialog.mode == "EDIT"
    assert dialog.windowTitle() == "Редактировать точку"
    assert dialog.btn_add.text() == "Сохранить"
    assert dialog.name_edit.text() == "Йошкар-Ола"
    assert "56.63" in dialog.lat_edit.text()
    assert "47.88" in dialog.lon_edit.text()
    assert dialog.symbol_combo.currentData() == "square"
    assert dialog.size_spin.value() == 20.0
    assert dialog.r_edit.text() == "15"
    assert dialog.g_edit.text() == "25"
    assert dialog.b_edit.text() == "35"


def test_26_color_dialog_integration(qapp):
    """26. QColorDialog интеграция присутствует и не ломает диалог."""
    dialog = PointDialog(mode="CREATE")
    assert hasattr(dialog, "btn_pick_color")
    assert hasattr(dialog, "_open_color_dialog")
    assert dialog.btn_pick_color.text() == "Выбрать цвет..."


def test_27_invalid_rgb_rejected():
    """27. Некорректный RGB отклоняется валидатором."""
    with pytest.raises(ValueError):
        StyleValidator.validate_rgb("abc", 100, 100)

    with pytest.raises(ValueError):
        StyleValidator.validate_rgb("", 100, 100)


def test_28_editing_coords_outside_boundary_detected():
    """28. Редактирование координат за пределами РМЭ фиксируется проверкой границы."""
    poly = Polygon([(45.0, 55.0), (51.0, 55.0), (51.0, 58.0), (45.0, 58.0)])

    # Внутри
    assert CoordinateService.is_point_inside_boundary(47.88, 56.63, poly) is True
    # Снаружи (Казань или Москва)
    assert CoordinateService.is_point_inside_boundary(37.61, 55.75, poly) is False


def test_29_table_updates_after_editing(qapp):
    """29. Таблица обновляется после редактирования точки."""
    window = MainWindow()
    point = window._point_service.add_point("Точка ДО", 56.0, 47.0, symbol="circle")
    window.map_canvas.add_user_point(point)
    window._add_point_to_table(point)

    assert window.points_table.item(0, 1).text() == "Точка ДО"
    assert window.points_table.item(0, 4).text() == "Круг"

    updated = window._point_service.update_point(
        point.id,
        name="Точка ПОСЛЕ",
        symbol="triangle",
        size=18.0,
    )
    window.map_canvas.update_user_point(updated)
    window._update_point_in_table(0, updated)

    assert window.points_table.item(0, 1).text() == "Точка ПОСЛЕ"
    assert window.points_table.item(0, 4).text() == "Треугольник"


def test_30_deletion_after_editing_continues_to_work(qapp):
    """30. Удаление после редактирования продолжает работать."""
    window = MainWindow()
    point = window._point_service.add_point("Точка для удаления", 56.0, 47.0)
    window.map_canvas.add_user_point(point)
    window._add_point_to_table(point)

    window._point_service.update_point(point.id, name="Отредактированная")
    window._update_point_in_table(0, point)

    window.points_table.selectRow(0)
    assert window.btn_delete_point.isEnabled()
    assert window.btn_edit_point.isEnabled()

    window.delete_selected_point()

    assert window.points_table.rowCount() == 0
    assert not window.map_canvas.has_user_point(point.id)
    assert window._point_service.get_point(point.id) is None
    assert not window.btn_delete_point.isEnabled()
    assert not window.btn_edit_point.isEnabled()
