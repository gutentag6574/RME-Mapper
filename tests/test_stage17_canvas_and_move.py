"""Тесты для Этапа 17: Интерактивное перемещение точек на холсте, подписи и видимость."""

import os
from pathlib import Path
import pytest
from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QKeyEvent, QMouseEvent
from PySide6.QtWidgets import QApplication

from rme_mapper.maps.map_canvas import MapCanvas, format_point_label
from rme_mapper.models.map_point import MapPoint
from rme_mapper.services.point_service import PointService
from rme_mapper.ui.controllers.point_controller import PointController
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


# =============================================================================
# 1. Форматирование подписей format_point_label
# =============================================================================


def test_01_format_point_label_modes():
    """Проверка формирования текста подписи во всех 3 режимах."""
    p = MapPoint(name="Скважина 42", latitude=56.0, longitude=47.0, object_number="СКВ-42")

    assert format_point_label(p, "name") == "Скважина 42"
    assert format_point_label(p, "number") == "СКВ-42"
    assert format_point_label(p, "number_name") == "СКВ-42 - Скважина 42"


def test_02_format_point_label_clean_fallbacks():
    """Проверка отсутствия висячих разделителей при пустых полях."""
    # Нет номера
    p_no_num = MapPoint(name="Главный корпус", latitude=56.0, longitude=47.0, object_number="")
    assert format_point_label(p_no_num, "name") == "Главный корпус"
    assert format_point_label(p_no_num, "number") == ""
    assert format_point_label(p_no_num, "number_name") == "Главный корпус"

    # Нет имени
    p_no_name = MapPoint(name="", latitude=56.0, longitude=47.0, object_number="№99")
    assert format_point_label(p_no_name, "name") == ""
    assert format_point_label(p_no_name, "number") == "№99"
    assert format_point_label(p_no_name, "number_name") == "№99"

    # Оба пусты
    p_empty = MapPoint(name="", latitude=56.0, longitude=47.0, object_number="")
    assert format_point_label(p_empty, "number_name") == ""


# =============================================================================
# 2. Интерактивное перемещение точки на MapCanvas
# =============================================================================


def test_03_canvas_move_point_mode_and_drag(qapp):
    """Проверка drag-and-drop перемещения точки в режиме move_point."""
    canvas = MapCanvas()
    canvas.resize(800, 600)
    canvas.show()

    p = MapPoint(id="test-p1", name="Точка 1", latitude=56.0, longitude=47.0, size=20.0)
    canvas.add_user_point(p, map_x=100.0, map_y=100.0)

    # Включаем режим перемещения
    canvas.set_interaction_mode("move_point")
    assert canvas._interaction_mode == "move_point"

    moved_events = []
    canvas.point_moved.connect(lambda pid, fx, fy, sx, sy: moved_events.append((pid, fx, fy, sx, sy)))

    # Эмулируем клик на маркере (в координатах сцены 100, -100)
    view_pos = canvas.mapFromScene(QPointF(100.0, -100.0))

    # MousePress
    press_ev = QMouseEvent(
        QMouseEvent.Type.MouseButtonPress,
        QPointF(view_pos),
        Qt.MouseButton.LeftButton,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    canvas.mousePressEvent(press_ev)
    assert canvas._drag_point_id == "test-p1"
    assert canvas._is_dragging_point is True

    # MouseMove
    move_view_pos = view_pos + QPoint(50, -50)
    move_ev = QMouseEvent(
        QMouseEvent.Type.MouseMove,
        QPointF(move_view_pos),
        Qt.MouseButton.LeftButton,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    canvas.mouseMoveEvent(move_ev)

    # MouseRelease
    release_ev = QMouseEvent(
        QMouseEvent.Type.MouseButtonRelease,
        QPointF(move_view_pos),
        Qt.MouseButton.LeftButton,
        Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.NoModifier,
    )
    canvas.mouseReleaseEvent(release_ev)

    assert len(moved_events) == 1
    pid, fx, fy, sx, sy = moved_events[0]
    assert pid == "test-p1"
    assert sx == 100.0
    assert sy == 100.0
    assert fx != sx or fy != sy


def test_04_canvas_move_point_cancel_with_escape(qapp):
    """Нажатие клавиши Escape отменяет перемещение и восстанавливает позицию маркера."""
    canvas = MapCanvas()
    canvas.resize(800, 600)
    canvas.show()

    p = MapPoint(id="test-p2", name="Точка 2", latitude=56.0, longitude=47.0, size=20.0)
    canvas.add_user_point(p, map_x=200.0, map_y=200.0)
    canvas.set_interaction_mode("move_point")

    cancel_events = []
    canvas.move_point_mode_cancelled.connect(lambda: cancel_events.append(True))

    view_pos = canvas.mapFromScene(QPointF(200.0, -200.0))

    # Начинаем перетаскивание
    press_ev = QMouseEvent(
        QMouseEvent.Type.MouseButtonPress,
        QPointF(view_pos),
        Qt.MouseButton.LeftButton,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    canvas.mousePressEvent(press_ev)
    assert canvas._is_dragging_point is True

    # Перемещаем
    move_ev = QMouseEvent(
        QMouseEvent.Type.MouseMove,
        QPointF(view_pos + QPoint(40, 40)),
        Qt.MouseButton.LeftButton,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    canvas.mouseMoveEvent(move_ev)

    # Нажимаем Escape
    esc_ev = QKeyEvent(QKeyEvent.Type.KeyPress, Qt.Key.Key_Escape, Qt.KeyboardModifier.NoModifier)
    canvas.keyPressEvent(esc_ev)

    assert canvas._is_dragging_point is False
    assert canvas._drag_point_id is None
    # Маркер возвращен на исходную позицию (200, -200)
    item = canvas._user_point_items["test-p2"]
    assert item.pos().x() == 200.0
    assert item.pos().y() == -200.0
    assert len(cancel_events) == 1


# =============================================================================
# 3. Undo/Redo перемещения точки через PointController
# =============================================================================


def test_05_point_controller_move_point_undo_redo(qapp, default_gpkg):
    """Проверка фиксации перемещения в стеке Undo/Redo."""
    win = MainWindow(map_path=default_gpkg)
    p = MapPoint(id="pt-move", name="Исходная", latitude=56.634, longitude=47.899)
    win.point_controller._cmd_add_point(p)

    orig_lat = p.latitude
    orig_lon = p.longitude

    # Симулируем событие point_moved от canvas
    new_scene_x = 47.95
    new_scene_y = 56.65
    win.point_controller.on_point_moved_on_canvas("pt-move", new_scene_x, new_scene_y, orig_lon, orig_lat)

    moved_p = win._point_service.get_point("pt-move")
    assert moved_p.longitude != orig_lon or moved_p.latitude != orig_lat

    # Undo
    assert win.point_controller.undo_manager.can_undo is True
    win.point_controller.undo()

    restored_p = win._point_service.get_point("pt-move")
    assert abs(restored_p.latitude - orig_lat) < 1e-5
    assert abs(restored_p.longitude - orig_lon) < 1e-5

    # Redo
    assert win.point_controller.undo_manager.can_redo is True
    win.point_controller.redo()

    redo_p = win._point_service.get_point("pt-move")
    assert abs(redo_p.latitude - moved_p.latitude) < 1e-5
    assert abs(redo_p.longitude - moved_p.longitude) < 1e-5


# =============================================================================
# 4. Видимость объектов и контекстное меню
# =============================================================================


def test_06_toggle_point_visibility(qapp, default_gpkg):
    """Скрытие и показ объекта через PointController с поддержкой Undo."""
    win = MainWindow(map_path=default_gpkg)
    p = MapPoint(id="pt-vis", name="Видимый", latitude=56.634, longitude=47.899, visible=True)
    win.point_controller._cmd_add_point(p)

    # Переключаем видимость (скрываем)
    win.point_controller.toggle_point_visibility("pt-vis")
    hidden_p = win._point_service.get_point("pt-vis")
    assert hidden_p.visible is False

    # Проверяем, что маркер на холсте скрыт
    marker_item = win.map_canvas._user_point_items.get("pt-vis")
    assert marker_item.isVisible() is False

    # Undo восстанавливает видимость
    win.point_controller.undo()
    restored_p = win._point_service.get_point("pt-vis")
    assert restored_p.visible is True
    assert marker_item.isVisible() is True
