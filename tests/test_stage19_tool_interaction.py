"""Тесты взаимодействия инструментов и неконфликтности режимов (Тесты 69–76).

Проверяет:
69: Взаимное исключение между инструментами измерения (расстояние и площадь).
70: Взаимное исключение между измерениями и режимами добавления/перемещения точки.
71: Панорамирование средней кнопкой мыши во время измерения не добавляет вершину.
72: Зум колесиком мыши во время измерения сохраняет активное измерение.
73: Клик по точке во время измерения не выделяет/не перемещает точку, а добавляет вершину.
74: Клавиша Esc отменяет незавершенное измерение; Очистить удаляет все измерения.
75: Переключение языка интерфейса (RU <-> EN) обновляет тексты и подсказки инструментов.
76: Измерения не меняют статус модификации проекта (is_modified=False) и не влияют на Undo/Redo.
"""

from pathlib import Path
import pytest
from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QMouseEvent, QWheelEvent

from rme_mapper.i18n import set_language, tr
from rme_mapper.models.map_point import MapPoint
from rme_mapper.ui.main_window import MainWindow


@pytest.fixture
def default_gpkg() -> Path:
    """Путь к тестовому GeoPackage."""
    return Path(__file__).resolve().parent.parent / "maps" / "test_map" / "prepared" / "mari.gpkg"


@pytest.fixture
def sample_point() -> MapPoint:
    return MapPoint(
        id="pt_interact_1",
        name="Точка Взаимодействия",
        latitude=56.63,
        longitude=47.89,
        radius_m=200.0,
        zone_enabled=True,
    )


def test_69_mutual_exclusivity_distance_and_area(qapp, default_gpkg):
    """Тест 69: Взаимное исключение между инструментами Расстояние и Площадь."""
    window = MainWindow()
    window.load_map(default_gpkg)
    window.resize(1000, 700)
    window.show()

    # Активируем измерение расстояния
    window.measure_distance_action.trigger()
    assert window.measure_distance_action.isChecked() is True
    assert window.measure_area_action.isChecked() is False
    assert window.map_canvas.interaction_mode == "measure_distance"

    # Активируем измерение площади -> расстояние должно выключиться
    window.measure_area_action.trigger()
    assert window.measure_distance_action.isChecked() is False
    assert window.measure_area_action.isChecked() is True
    assert window.map_canvas.interaction_mode == "measure_area"

    # Снова включаем расстояние -> площадь выключается
    window.measure_distance_action.trigger()
    assert window.measure_distance_action.isChecked() is True
    assert window.measure_area_action.isChecked() is False
    assert window.map_canvas.interaction_mode == "measure_distance"

    window.close()


def test_70_mutual_exclusivity_measurement_and_point_tools(qapp, default_gpkg):
    """Тест 70: Взаимное исключение между измерениями и режимами добавления/перемещения точки."""
    window = MainWindow()
    window.load_map(default_gpkg)
    window.resize(1000, 700)
    window.show()

    # 1. Включаем Добавление точки на карте -> затем измерение расстояния
    window.add_pt_map_action.setChecked(True)
    assert window.add_pt_map_action.isChecked() is True

    window.measure_distance_action.setChecked(True)
    assert window.measure_distance_action.isChecked() is True
    assert window.add_pt_map_action.isChecked() is False
    assert window.map_canvas.interaction_mode == "measure_distance"

    # 2. Находясь в измерении расстояния, включаем Добавление точки
    window.add_pt_map_action.setChecked(True)
    assert window.add_pt_map_action.isChecked() is True
    assert window.measure_distance_action.isChecked() is False
    assert window.map_canvas.interaction_mode == "add_point"

    # 3. Переход в режим перемещения точки отменяет измерение
    window.measure_area_action.setChecked(True)
    assert window.map_canvas.interaction_mode == "measure_area"
    window.point_controller.start_move_point_mode()
    assert window.map_canvas.interaction_mode == "move_point"
    assert window.measure_area_action.isChecked() is False

    window.close()


def test_71_middle_click_pan_does_not_add_vertex(qapp, default_gpkg):
    """Тест 71: Панорамирование средней кнопкой мыши не добавляет вершин к активному измерению."""
    window = MainWindow()
    window.load_map(default_gpkg)
    window.resize(1000, 700)
    window.show()

    canvas = window.map_canvas
    window.measure_distance_action.trigger()
    assert len(canvas._measure_points) == 0

    # Эмулируем клик средней кнопкой мыши
    mid_event = QMouseEvent(
        QMouseEvent.Type.MouseButtonPress,
        QPointF(200.0, 200.0),
        Qt.MouseButton.MiddleButton,
        Qt.MouseButton.MiddleButton,
        Qt.KeyboardModifier.NoModifier,
    )
    canvas.mousePressEvent(mid_event)
    assert canvas._is_middle_panning is True
    assert len(canvas._measure_points) == 0, "Клик средней кнопкой не должен добавлять вершину измерения"

    window.close()


def test_72_wheel_zoom_preserves_active_measurement(qapp, default_gpkg):
    """Тест 72: Зум колесиком мыши сохраняет зафиксированные точки активного измерения."""
    window = MainWindow()
    window.load_map(default_gpkg)
    window.resize(1000, 700)
    window.show()

    canvas = window.map_canvas
    window.measure_distance_action.trigger()

    # Добавляем две вершины
    canvas._add_measurement_vertex((47.5, -56.5))
    canvas._add_measurement_vertex((47.7, -56.7))
    assert len(canvas._measure_points) == 2

    # Эмулируем вращение колеса мыши (зум вперед)
    wheel_event = QWheelEvent(
        QPointF(300.0, 300.0),
        QPointF(300.0, 300.0),
        QPoint(0, 0),
        QPoint(0, 120),
        Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.NoModifier,
        Qt.ScrollPhase.NoScrollPhase,
        False,
    )
    canvas.wheelEvent(wheel_event)

    # Вершины должны сохраниться
    assert len(canvas._measure_points) == 2
    assert canvas.has_measurements() is True
    assert canvas.interaction_mode == "measure_distance"

    window.close()


def test_73_clicking_on_point_during_measurement_adds_vertex(qapp, default_gpkg, sample_point):
    """Тест 73: Клик по точке во время измерения не выделяет точку, а добавляет вершину."""
    window = MainWindow()
    window.load_map(default_gpkg)
    window.resize(1000, 700)
    window.show()

    # Добавляем точку на карту
    window.map_canvas.add_user_point(sample_point)
    window.map_canvas._selected_point_ids.clear()

    # Включаем измерение расстояния
    window.measure_distance_action.trigger()
    canvas = window.map_canvas

    # Координаты сцены точки
    pt_scene_pos = QPointF(sample_point.longitude, -sample_point.latitude)
    view_pos = canvas.mapFromScene(pt_scene_pos)

    # Кликаем левой кнопкой мыши ровно по точке
    click_event = QMouseEvent(
        QMouseEvent.Type.MouseButtonPress,
        QPointF(view_pos.x(), view_pos.y()),
        Qt.MouseButton.LeftButton,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    canvas.mousePressEvent(click_event)

    # Добавилась вершина измерения
    assert len(canvas._measure_points) == 1
    # Точка НЕ выделилась
    assert sample_point.id not in window.map_canvas._selected_point_ids

    window.close()


def test_74_esc_and_clear_measurements(qapp, default_gpkg):
    """Тест 74: Клавиша Esc отменяет активное измерение; кнопка Очистить удаляет всё."""
    window = MainWindow()
    window.load_map(default_gpkg)
    window.resize(1000, 700)
    window.show()

    canvas = window.map_canvas
    window.measure_distance_action.trigger()

    # Добавляем 2 вершины
    canvas._add_measurement_vertex((47.5, -56.5))
    canvas._add_measurement_vertex((47.7, -56.7))
    assert canvas.has_measurements() is True

    # Завершаем первое измерение
    canvas._finish_measurement()
    assert len(canvas._measure_completed_items) > 0

    # Начинаем второе измерение и отменяем по Esc
    window.measure_area_action.trigger()
    canvas._add_measurement_vertex((47.5, -56.5))
    assert len(canvas._measure_points) == 1

    from PySide6.QtGui import QKeyEvent
    esc_event = QKeyEvent(QKeyEvent.Type.KeyPress, Qt.Key.Key_Escape, Qt.KeyboardModifier.NoModifier)
    canvas.keyPressEvent(esc_event)

    assert len(canvas._measure_points) == 0
    assert canvas.interaction_mode == "navigation"
    # Завершенное измерение всё еще на холсте
    assert len(canvas._measure_completed_items) > 0

    # Очищаем всё через действие Очистить измерения
    window.clear_measurements_action.trigger()
    assert canvas.has_measurements() is False
    assert len(canvas._measure_completed_items) == 0

    window.close()


def test_75_language_switch_updates_measurement_ui(qapp, default_gpkg):
    """Тест 75: Переключение языка интерфейса динамически обновляет тексты инструментов."""
    window = MainWindow()
    window.load_map(default_gpkg)
    window.resize(1000, 700)
    window.show()

    # Переключаем на русский
    set_language("ru")
    window.retranslate_ui()
    assert window.tools_menu.title() == "Инструменты"
    assert "расстояние" in window.measure_distance_action.text().lower()
    assert "площадь" in window.measure_area_action.text().lower()

    # Переключаем на английский
    set_language("en")
    window.retranslate_ui()
    assert window.tools_menu.title() == "Tools"
    assert "distance" in window.measure_distance_action.text().lower()
    assert "area" in window.measure_area_action.text().lower()

    # Возвращаем на русский
    set_language("ru")
    window.retranslate_ui()
    window.close()


def test_76_measurements_never_modify_project_or_undo(qapp, default_gpkg):
    """Тест 76: Измерения являются временным UI-состоянием и не затрагивают проект и Undo."""
    window = MainWindow()
    window.load_map(default_gpkg)
    window.resize(1000, 700)
    window.show()

    undo_stack = window.point_controller.undo_manager
    undo_count_before = len(undo_stack._undo_stack)
    is_modified_before = window.is_modified

    # 1. Запуск и добавление вершин
    window.measure_distance_action.trigger()
    canvas = window.map_canvas
    canvas._add_measurement_vertex((47.5, -56.5))
    canvas._add_measurement_vertex((47.7, -56.7))

    assert window.is_modified == is_modified_before
    assert len(undo_stack._undo_stack) == undo_count_before

    # 2. Завершение измерения
    canvas._finish_measurement()
    assert window.is_modified == is_modified_before
    assert len(undo_stack._undo_stack) == undo_count_before

    # 3. Очистка измерений
    window.clear_measurements_action.trigger()
    assert window.is_modified == is_modified_before
    assert len(undo_stack._undo_stack) == undo_count_before

    window.close()
