"""Тесты для Этапа 12.3 — Удобства работы с картой и точками.

Разделы тестирования (56 тестов):
- Section 49: Undo / Redo система (тесты 1–15)
- Section 50: Создание точки кликом по карте (тесты 16–22)
- Section 51: Мульти-выделение в таблице точек (тесты 23–28)
- Section 52: Множественное удаление точек (тесты 29–33)
- Section 53: Массовое изменение стиля (тесты 34–38)
- Section 54: Подписи точек на карте (тесты 39–44)
- Section 55: Быстрая навигация и центрирование (тесты 45–48)
- Section 56: Копирование координат нескольких точек TSV (тесты 49–51)
- Section 57: Глобальное переключение видимости и меню (тесты 52–56)
"""

import copy
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest

from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QColor, QKeyEvent, QMouseEvent
from PySide6.QtWidgets import QApplication, QDialog, QMessageBox

from rme_mapper.maps.map_config import get_default_geopackage_path
from rme_mapper.models.map_point import MapPoint
from rme_mapper.models.map_profile import MapProfile
from rme_mapper.services.app_settings_service import AppSettingsService
from rme_mapper.services.undo_manager import (
    AddPointCommand,
    BulkEditStyleCommand,
    DeleteMultiplePointsCommand,
    DeletePointCommand,
    EditPointCommand,
    UndoManager,
)
from rme_mapper.ui.bulk_point_style_dialog import BulkPointStyleDialog
from rme_mapper.ui.main_window import MainWindow
from rme_mapper.ui.point_dialog import PointDialog


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    yield app


@pytest.fixture
def default_gpkg():
    return get_default_geopackage_path()


@pytest.fixture
def clean_settings():
    """Изолированная фикстура для очистки пользовательских настроек до и после теста."""
    from rme_mapper.services.project_service import ProjectService
    ProjectService().clear_recovery_snapshot()
    settings = AppSettingsService()
    settings.clear()
    yield settings
    settings.clear()
    ProjectService().clear_recovery_snapshot()


@pytest.fixture(autouse=True)
def no_unsaved_prompts(monkeypatch):
    monkeypatch.setattr(
        "rme_mapper.ui.controllers.project_controller.ProjectController.maybe_save_prompt",
        lambda self, action_name=None: True,
    )


def create_sample_point(
    pid: str = "pt-1",
    name: str = "Test Point",
    lat: float = 56.63,
    lon: float = 47.88,
    symbol: str = "circle",
    size: float = 12.0,
    color: str = "#FF0000",
    zone_enabled: bool = True,
    radius_m: float = 1000.0,
    zone_color: str = "#FF0000",
    zone_opacity: float = 0.35,
) -> MapPoint:
    c = QColor(color)
    zc = QColor(zone_color)
    op = int(round(zone_opacity * 100)) if isinstance(zone_opacity, float) and zone_opacity <= 1.0 else int(zone_opacity)
    return MapPoint(
        id=pid,
        name=name,
        latitude=lat,
        longitude=lon,
        symbol=symbol,
        size=size,
        red=c.red(),
        green=c.green(),
        blue=c.blue(),
        zone_enabled=zone_enabled,
        radius_m=radius_m,
        zone_red=zc.red(),
        zone_green=zc.green(),
        zone_blue=zc.blue(),
        zone_opacity=op,
    )


# =============================================================================
# Section 49: Undo / Redo система (тесты 1–15)
# =============================================================================

def test_01_undo_add_point_removes_point():
    """1. Отмена добавления точки удаляет точку из модели."""
    points = {}
    pt = create_sample_point("pt-1", "Point 1")

    mgr = UndoManager()
    cmd = AddPointCommand(
        point=pt,
        add_fn=lambda p: points.__setitem__(p.id, p),
        remove_fn=lambda pid: points.pop(pid, None),
    )
    mgr.push(cmd, execute=True)
    assert "pt-1" in points
    assert mgr.can_undo

    mgr.undo()
    assert "pt-1" not in points
    assert not mgr.can_undo
    assert mgr.can_redo


def test_02_redo_add_point_restores_point():
    """2. Повтор добавления точки заново вставляет точку."""
    points = {}
    pt = create_sample_point("pt-1", "Point 1")

    mgr = UndoManager()
    cmd = AddPointCommand(
        point=pt,
        add_fn=lambda p: points.__setitem__(p.id, p),
        remove_fn=lambda pid: points.pop(pid, None),
    )
    mgr.push(cmd, execute=True)
    mgr.undo()
    assert "pt-1" not in points

    mgr.redo()
    assert "pt-1" in points
    assert points["pt-1"].name == "Point 1"


def test_03_undo_delete_point_restores_point():
    """3. Отмена удаления точки восстанавливает её в модели."""
    pt = create_sample_point("pt-1", "Deleted Point")
    points = {"pt-1": pt}

    mgr = UndoManager()
    cmd = DeletePointCommand(
        point=pt,
        row_index=0,
        remove_fn=lambda pid: points.pop(pid, None),
        restore_fn=lambda p, idx: points.__setitem__(p.id, p),
    )
    mgr.push(cmd, execute=True)
    assert "pt-1" not in points

    mgr.undo()
    assert "pt-1" in points
    assert points["pt-1"].name == "Deleted Point"


def test_04_redo_delete_point_removes_point():
    """4. Повтор удаления точки снова удаляет её."""
    pt = create_sample_point("pt-1", "Deleted Point")
    points = {"pt-1": pt}

    mgr = UndoManager()
    cmd = DeletePointCommand(
        point=pt,
        row_index=0,
        remove_fn=lambda pid: points.pop(pid, None),
        restore_fn=lambda p, idx: points.__setitem__(p.id, p),
    )
    mgr.push(cmd, execute=True)
    mgr.undo()
    assert "pt-1" in points

    mgr.redo()
    assert "pt-1" not in points


def test_05_undo_edit_point_restores_previous_state():
    """5. Отмена редактирования возвращает исходные свойства точки."""
    old_pt = create_sample_point("pt-1", "Old Name", lat=55.0)
    new_pt = create_sample_point("pt-1", "New Name", lat=56.0)
    current = {"pt-1": copy.deepcopy(new_pt)}

    mgr = UndoManager()
    cmd = EditPointCommand(
        before_point=old_pt,
        after_point=new_pt,
        apply_fn=lambda p: current.__setitem__(p.id, copy.deepcopy(p)),
    )
    mgr.push(cmd, execute=False)

    mgr.undo()
    assert current["pt-1"].name == "Old Name"
    assert current["pt-1"].latitude == 55.0


def test_06_redo_edit_point_reapplies_changes():
    """6. Повтор редактирования заново применяет измененные свойства."""
    old_pt = create_sample_point("pt-1", "Old Name")
    new_pt = create_sample_point("pt-1", "New Name")
    current = {"pt-1": copy.deepcopy(new_pt)}

    mgr = UndoManager()
    cmd = EditPointCommand(
        before_point=old_pt,
        after_point=new_pt,
        apply_fn=lambda p: current.__setitem__(p.id, copy.deepcopy(p)),
    )
    mgr.push(cmd, execute=False)
    mgr.undo()
    mgr.redo()
    assert current["pt-1"].name == "New Name"


def test_07_undo_multi_delete_atomic():
    """7. Отмена множественного удаления восстанавливает все точки атомарно."""
    pts = [create_sample_point(f"pt-{i}", f"Point {i}") for i in range(3)]
    points = {p.id: p for p in pts}

    mgr = UndoManager()
    cmd = DeleteMultiplePointsCommand(
        points_with_indices=[(p, i) for i, p in enumerate(pts)],
        remove_fn=lambda pid: points.pop(pid, None),
        restore_fn=lambda p, idx: points.__setitem__(p.id, p),
    )
    mgr.push(cmd, execute=True)
    assert len(points) == 0

    mgr.undo()
    assert len(points) == 3
    assert set(points.keys()) == {"pt-0", "pt-1", "pt-2"}


def test_08_redo_multi_delete_atomic():
    """8. Повтор множественного удаления удаляет все точки разом."""
    pts = [create_sample_point(f"pt-{i}", f"Point {i}") for i in range(3)]
    points = {p.id: p for p in pts}

    mgr = UndoManager()
    cmd = DeleteMultiplePointsCommand(
        points_with_indices=[(p, i) for i, p in enumerate(pts)],
        remove_fn=lambda pid: points.pop(pid, None),
        restore_fn=lambda p, idx: points.__setitem__(p.id, p),
    )
    mgr.push(cmd, execute=True)
    mgr.undo()
    assert len(points) == 3

    mgr.redo()
    assert len(points) == 0


def test_09_undo_bulk_style_atomic():
    """9. Отмена массового изменения стиля возвращает индивидуальные свойства."""
    p1 = create_sample_point("pt-1", "P1", color="#111111", radius_m=100.0)
    p2 = create_sample_point("pt-2", "P2", color="#222222", radius_m=200.0)
    current = {"pt-1": copy.deepcopy(p1), "pt-2": copy.deepcopy(p2)}

    p1_new = copy.deepcopy(p1)
    p1_new.red, p1_new.green, p1_new.blue = 255, 0, 0
    p2_new = copy.deepcopy(p2)
    p2_new.red, p2_new.green, p2_new.blue = 255, 0, 0

    mgr = UndoManager()
    cmd = BulkEditStyleCommand(
        before_points=[p1, p2],
        after_points=[p1_new, p2_new],
        apply_fn=lambda pts: [current.__setitem__(p.id, copy.deepcopy(p)) for p in pts],
    )
    mgr.push(cmd, execute=True)
    assert current["pt-1"].red == 255
    assert current["pt-2"].red == 255

    mgr.undo()
    assert current["pt-1"].red == p1.red
    assert current["pt-2"].red == p2.red
    assert current["pt-1"].radius_m == 100.0
    assert current["pt-2"].radius_m == 200.0


def test_10_redo_bulk_style_atomic():
    """10. Повтор массового изменения стиля заново накладывает стиль."""
    p1 = create_sample_point("pt-1", "P1", color="#111111")
    current = {"pt-1": copy.deepcopy(p1)}
    p1_new = copy.deepcopy(p1)
    p1_new.red, p1_new.green, p1_new.blue = 0, 255, 0

    mgr = UndoManager()
    cmd = BulkEditStyleCommand(
        before_points=[p1],
        after_points=[p1_new],
        apply_fn=lambda pts: [current.__setitem__(p.id, copy.deepcopy(p)) for p in pts],
    )
    mgr.push(cmd, execute=True)
    mgr.undo()
    assert current["pt-1"].red == p1.red

    mgr.redo()
    assert current["pt-1"].green == 255


def test_11_undo_manager_clean_index_and_dirty_state():
    """11. Проверка отслеживания clean_index при сохранении и отмене."""
    mgr = UndoManager()
    assert mgr.is_clean

    pt = create_sample_point("pt-1")
    cmd = AddPointCommand(pt, lambda p: None, lambda pid: None)
    mgr.push(cmd)
    assert not mgr.is_clean

    mgr.mark_clean()
    assert mgr.is_clean

    cmd2 = AddPointCommand(create_sample_point("pt-2"), lambda p: None, lambda pid: None)
    mgr.push(cmd2)
    assert not mgr.is_clean

    mgr.undo()
    assert mgr.is_clean


def test_12_undo_manager_clears_redo_on_new_command():
    """12. Новая команда после отмены очищает стек Redo."""
    mgr = UndoManager()
    cmd1 = AddPointCommand(create_sample_point("pt-1"), lambda p: None, lambda pid: None)
    cmd2 = AddPointCommand(create_sample_point("pt-2"), lambda p: None, lambda pid: None)

    mgr.push(cmd1)
    mgr.undo()
    assert mgr.can_redo

    mgr.push(cmd2)
    assert not mgr.can_redo


def test_13_undo_manager_clear_resets_stacks():
    """13. Метод clear полностью очищает оба стека и clean_index."""
    mgr = UndoManager()
    cmd = AddPointCommand(create_sample_point("pt-1"), lambda p: None, lambda pid: None)
    mgr.push(cmd)
    mgr.mark_clean()
    mgr.push(cmd)

    mgr.clear()
    assert not mgr.can_undo
    assert not mgr.can_redo
    assert mgr.is_clean


def test_14_undo_redo_updates_recovery_snapshot(qapp, clean_settings):
    """14. Выполнение Undo/Redo через PointController синхронизирует dirty state проекта."""
    win = MainWindow()
    pt = create_sample_point("pt-1", "RecPoint")

    assert not win.is_modified

    cmd = AddPointCommand(
        pt,
        win.point_controller._cmd_add_point,
        win.point_controller._cmd_remove_point,
    )
    win.point_controller.undo_manager.push(cmd, execute=True)
    assert win.is_modified

    win.undo()
    assert not win.is_modified
    assert len(win.point_controller.table_point_ids) == 0

    win.redo()
    assert win.is_modified
    assert len(win.point_controller.table_point_ids) == 1

    win.close()


def test_15_undo_actions_enabled_disabled_sync(qapp, clean_settings):
    """15. Действия Меню/Тулбара Undo/Redo синхронизируются со стеком."""
    win = MainWindow()
    assert not win.undo_action.isEnabled()
    assert not win.redo_action.isEnabled()

    pt = create_sample_point("pt-1")
    cmd = AddPointCommand(
        pt,
        win.point_controller._cmd_add_point,
        win.point_controller._cmd_remove_point,
    )
    win.point_controller.undo_manager.push(cmd, execute=True)

    assert win.undo_action.isEnabled()
    assert not win.redo_action.isEnabled()

    win.undo()
    assert not win.undo_action.isEnabled()
    assert win.redo_action.isEnabled()

    win.redo()
    assert win.undo_action.isEnabled()
    assert not win.redo_action.isEnabled()
    win.close()


# =============================================================================
# Section 50: Создание точки кликом по карте (тесты 16–22)
# =============================================================================

def test_16_start_add_point_mode_sets_crosshair(qapp, clean_settings, default_gpkg):
    """16. Активация режима добавления точки меняет курсор на перекрестие."""
    win = MainWindow(map_path=default_gpkg)
    win.point_controller.start_add_point_on_map_mode()

    assert win.map_canvas.interaction_mode == "add_point"
    assert win.map_canvas.viewport().cursor().shape() == Qt.CursorShape.CrossCursor
    win.close()


def test_17_cancel_add_point_mode_restores_navigation(qapp, clean_settings, default_gpkg):
    """17. Отмена режима восстанавливает режим навигации."""
    win = MainWindow(map_path=default_gpkg)
    win.point_controller.start_add_point_on_map_mode()
    win.point_controller.cancel_add_point_on_map_mode()

    assert win.map_canvas.interaction_mode == "navigation"
    assert win.map_canvas.viewport().cursor().shape() == Qt.CursorShape.ArrowCursor
    win.close()


def test_18_esc_key_cancels_add_point_mode(qapp, clean_settings, default_gpkg):
    """18. Нажатие клавиши Escape на холсте отменяет режим добавления точки."""
    win = MainWindow(map_path=default_gpkg)
    win.point_controller.start_add_point_on_map_mode()
    win.add_pt_map_action.setChecked(True)

    event = QKeyEvent(QKeyEvent.Type.KeyPress, Qt.Key.Key_Escape, Qt.KeyboardModifier.NoModifier)
    win.map_canvas.keyPressEvent(event)

    assert win.map_canvas.interaction_mode == "navigation"
    assert not win.add_pt_map_action.isChecked()
    win.close()


def test_19_map_click_opens_dialog_with_wgs84_coords(qapp, clean_settings, default_gpkg):
    """19. Клик по карте пересчитывает координаты в WGS84 и открывает диалог."""
    win = MainWindow(map_path=default_gpkg)
    win.point_controller.start_add_point_on_map_mode()

    with patch.object(PointDialog, "exec", return_value=QDialog.DialogCode.Rejected) as mock_dlg:
        win.map_canvas.map_point_clicked.emit(47.88, 56.63)
        assert mock_dlg.called
        assert win.map_canvas.interaction_mode == "navigation"

    win.close()


def test_20_map_click_with_projected_crs_converts_properly(qapp, clean_settings):
    """20. При проекционной CRS координаты преобразуются в широту/долготу."""
    win = MainWindow()
    win.map_controller.active_crs = "EPSG:3857"
    win.map_controller.map_path = Path("fake.gpkg")

    opened_lat = None
    opened_lon = None

    def mock_workflow(initial_lat=None, initial_lon=None):
        nonlocal opened_lat, opened_lon
        opened_lat = initial_lat
        opened_lon = initial_lon

    win.point_controller.add_point_workflow = mock_workflow
    win.point_controller.on_map_point_clicked(0.0, 0.0)

    assert opened_lat is not None
    assert abs(opened_lat) < 1e-4
    assert abs(opened_lon) < 1e-4
    win.close()


def test_21_add_point_on_map_dialog_confirmed_adds_undoable_point(qapp, clean_settings, default_gpkg):
    """21. Подтверждение в диалоге добавляет точку и регистрирует команду Undo."""
    from rme_mapper.ui.point_dialog import PointDialogData
    win = MainWindow(map_path=default_gpkg)
    created_data = PointDialogData(
        name="Map Clicked Point",
        latitude=56.63,
        longitude=47.88,
        symbol="circle",
        size=12.0,
        red=220,
        green=30,
        blue=30,
        zone_enabled=True,
        radius_m=1000.0,
        zone_red=220,
        zone_green=30,
        zone_blue=30,
        zone_opacity=35,
    )

    with patch.object(PointDialog, "exec", return_value=QDialog.DialogCode.Accepted):
        with patch.object(PointDialog, "get_point_data", return_value=created_data):
            win.point_controller.on_map_point_clicked(47.88, 56.63)

    assert len(win.point_controller.table_point_ids) == 1
    assert win.point_controller.undo_manager.can_undo

    win.undo()
    assert len(win.point_controller.table_point_ids) == 0
    win.close()


def test_22_add_point_on_map_dialog_cancelled_adds_nothing(qapp, clean_settings, default_gpkg):
    """22. Отмена в диалоге не добавляет точку и оставляет стек отмены пустым."""
    win = MainWindow(map_path=default_gpkg)

    with patch.object(PointDialog, "exec", return_value=QDialog.DialogCode.Rejected):
        win.point_controller.on_map_point_clicked(47.88, 56.63)

    assert len(win.point_controller.table_point_ids) == 0
    assert not win.point_controller.undo_manager.can_undo
    win.close()


# =============================================================================
# Section 51: Мульти-выделение в таблице точек (тесты 23–28)
# =============================================================================

def test_23_points_table_selection_mode_is_extended(qapp, clean_settings):
    """23. Таблица точек настроена на ExtendedSelection."""
    win = MainWindow()
    from PySide6.QtWidgets import QAbstractItemView
    assert win.points_panel.points_table.selectionMode() == QAbstractItemView.SelectionMode.ExtendedSelection
    win.close()


def test_24_selected_point_ids_returns_all_selected(qapp, clean_settings):
    """24. selected_point_ids возвращает идентификаторы всех выделенных точек."""
    win = MainWindow()
    p1 = create_sample_point("pt-1", "P1")
    p2 = create_sample_point("pt-2", "P2")
    p3 = create_sample_point("pt-3", "P3")
    win.point_controller._cmd_add_point(p1)
    win.point_controller._cmd_add_point(p2)
    win.point_controller._cmd_add_point(p3)

    win.points_panel.select_point_ids(["pt-1", "pt-3"])
    selected = win.points_panel.selected_point_ids()
    assert set(selected) == {"pt-1", "pt-3"}
    win.close()


def test_25_selected_point_ids_accurate_when_search_filtered(qapp, clean_settings):
    """25. selected_point_ids возвращает корректные ID при активной фильтрации поиска."""
    win = MainWindow()
    p1 = create_sample_point("pt-alpha", "Alpha Point")
    p2 = create_sample_point("pt-beta", "Beta Point")
    win.point_controller._cmd_add_point(p1)
    win.point_controller._cmd_add_point(p2)

    win.points_panel.search_input.setText("Beta")
    win.points_panel.select_point_ids(["pt-beta"])

    selected = win.points_panel.selected_point_ids()
    assert selected == ["pt-beta"]
    win.close()


def test_26_select_point_ids_programmatic_selection(qapp, clean_settings):
    """26. Программная установка выделения через select_point_ids."""
    win = MainWindow()
    p1 = create_sample_point("pt-1", "P1")
    p2 = create_sample_point("pt-2", "P2")
    win.point_controller._cmd_add_point(p1)
    win.point_controller._cmd_add_point(p2)

    win.points_panel.select_point_ids(["pt-2"])
    assert win.points_panel.selected_point_ids() == ["pt-2"]
    win.close()


def test_27_multi_selection_updates_buttons_state(qapp, clean_settings):
    """27. При выборе 2+ точек кнопка 'Редактировать' выключается, 'Удалить' включена."""
    win = MainWindow()
    p1 = create_sample_point("pt-1", "P1")
    p2 = create_sample_point("pt-2", "P2")
    win.point_controller._cmd_add_point(p1)
    win.point_controller._cmd_add_point(p2)

    win.points_panel.select_point_ids(["pt-1", "pt-2"])
    assert not win.btn_edit_point.isEnabled()
    assert win.btn_delete_point.isEnabled()
    win.close()


def test_28_multi_selection_clears_properties_panel(qapp, clean_settings):
    """28. При множественном выделении панель свойств очищается."""
    win = MainWindow()
    p1 = create_sample_point("pt-1", "P1")
    p2 = create_sample_point("pt-2", "P2")
    win.point_controller._cmd_add_point(p1)
    win.point_controller._cmd_add_point(p2)

    win.points_panel.select_point_ids(["pt-1"])
    assert win.properties_panel.prop_name_val.text() == "P1"

    win.points_panel.select_point_ids(["pt-1", "pt-2"])
    assert win.properties_panel.prop_container.isHidden()
    assert not win.properties_panel.prop_empty_label.isHidden()
    win.close()


# =============================================================================
# Section 52: Множественное удаление точек (тесты 29–33)
# =============================================================================

def test_29_delete_multiple_points_shows_confirmation_dialog(qapp, clean_settings):
    """29. Диалог подтверждения множественного удаления отображает количество точек."""
    win = MainWindow()
    p1 = create_sample_point("pt-1", "P1")
    p2 = create_sample_point("pt-2", "P2")
    win.point_controller._cmd_add_point(p1)
    win.point_controller._cmd_add_point(p2)
    win.points_panel.select_point_ids(["pt-1", "pt-2"])

    with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.No) as mock_q:
        win.delete_selected_point(confirm=True)
        assert mock_q.called
        text_arg = mock_q.call_args[0][2]
        assert "2" in text_arg

    win.close()


def test_30_delete_multiple_points_confirmed_deletes_all(qapp, clean_settings):
    """30. Подтверждение множественного удаления удаляет все выбранные точки."""
    win = MainWindow()
    p1 = create_sample_point("pt-1", "P1")
    p2 = create_sample_point("pt-2", "P2")
    win.point_controller._cmd_add_point(p1)
    win.point_controller._cmd_add_point(p2)
    win.points_panel.select_point_ids(["pt-1", "pt-2"])

    with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes):
        win.delete_selected_point(confirm=True)

    assert len(win.point_controller.table_point_ids) == 0
    assert win.point_controller.undo_manager.can_undo

    win.undo()
    assert len(win.point_controller.table_point_ids) == 2
    win.close()


def test_31_delete_multiple_points_cancelled_preserves_all(qapp, clean_settings):
    """31. Отказ в диалоге множественного удаления сохраняет все точки."""
    win = MainWindow()
    p1 = create_sample_point("pt-1", "P1")
    p2 = create_sample_point("pt-2", "P2")
    win.point_controller._cmd_add_point(p1)
    win.point_controller._cmd_add_point(p2)
    win.points_panel.select_point_ids(["pt-1", "pt-2"])

    with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.No):
        win.delete_selected_point(confirm=True)

    assert len(win.point_controller.table_point_ids) == 2
    win.close()


def test_32_delete_selected_points_menu_action(qapp, clean_settings):
    """32. Действие 'Удалить выбранные' в меню Правка доступно при выделении."""
    win = MainWindow()
    assert not win.delete_selected_action.isEnabled()

    p1 = create_sample_point("pt-1", "P1")
    win.point_controller._cmd_add_point(p1)
    win.points_panel.select_point_ids(["pt-1"])

    assert win.delete_selected_action.isEnabled()
    win.close()


def test_33_delete_single_point_confirmation_dialog(qapp, clean_settings):
    """33. Одиночное удаление также показывает диалог подтверждения."""
    win = MainWindow()
    p1 = create_sample_point("pt-1", "P1")
    win.point_controller._cmd_add_point(p1)
    win.points_panel.select_point_ids(["pt-1"])

    with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.No) as mock_q:
        win.delete_selected_point(confirm=True)
        assert mock_q.called

    assert len(win.point_controller.table_point_ids) == 1
    win.close()


# =============================================================================
# Section 53: Массовое изменение стиля (тесты 34–38)
# =============================================================================

def test_34_bulk_style_dialog_validation(qapp):
    """34. Валидация в BulkPointStyleDialog: радиус зоны должен быть > 0 при включении."""
    dlg = BulkPointStyleDialog(point_count=3)
    dlg.chk_zone.setChecked(True)
    dlg.rb_zone_on.setChecked(True)
    dlg.chk_radius.setChecked(True)
    dlg.edit_radius.setText("0.0")

    with patch.object(QMessageBox, "warning") as mock_warn:
        dlg._on_apply()
        assert mock_warn.called


def test_35_bulk_style_modifies_only_checked_properties(qapp):
    """35. BulkPointStyleDialog возвращает только включенные свойства."""
    dlg = BulkPointStyleDialog(point_count=2)
    dlg.chk_color.setChecked(True)
    dlg._marker_color = QColor(0, 255, 0)
    dlg.chk_size.setChecked(False)

    changes = dlg.get_style_changes()
    assert changes.get("red") == 0
    assert changes.get("green") == 255
    assert changes.get("blue") == 0
    assert "size" not in changes
    assert "symbol" not in changes


def test_36_bulk_style_applies_to_all_selected_points(qapp, clean_settings):
    """36. Применение изменений стиля обновляет все выделенные точки."""
    win = MainWindow()
    p1 = create_sample_point("pt-1", "P1", size=10, color="#111111")
    p2 = create_sample_point("pt-2", "P2", size=10, color="#222222")
    win.point_controller._cmd_add_point(p1)
    win.point_controller._cmd_add_point(p2)
    win.points_panel.select_point_ids(["pt-1", "pt-2"])

    with patch.object(BulkPointStyleDialog, "exec", return_value=QDialog.DialogCode.Accepted):
        with patch.object(BulkPointStyleDialog, "get_style_changes", return_value={"size": 24.0, "red": 0, "green": 0, "blue": 255}):
            win.point_controller.bulk_edit_style_workflow()

    pt1 = win._point_service.get_point("pt-1")
    pt2 = win._point_service.get_point("pt-2")
    assert pt1.size == 24.0 and pt1.blue == 255
    assert pt2.size == 24.0 and pt2.blue == 255
    win.close()


def test_37_bulk_style_radius_km_conversion(qapp):
    """37. Пересчет радиуса из км в метры при установке единицы км."""
    dlg = BulkPointStyleDialog(point_count=2)
    dlg.chk_radius.setChecked(True)
    dlg.edit_radius.setText("2.5")
    dlg.combo_radius_unit.setCurrentIndex(1)

    changes = dlg.get_style_changes()
    assert changes["radius_m"] == 2500.0


def test_38_bulk_style_atomic_undo_redo(qapp, clean_settings):
    """38. Атомарная отмена и повтор массового изменения стиля через MainWindow."""
    win = MainWindow()
    p1 = create_sample_point("pt-1", "P1", color="#111111")
    p2 = create_sample_point("pt-2", "P2", color="#222222")
    win.point_controller._cmd_add_point(p1)
    win.point_controller._cmd_add_point(p2)
    win.points_panel.select_point_ids(["pt-1", "pt-2"])

    orig_r1 = p1.red
    orig_r2 = p2.red

    with patch.object(BulkPointStyleDialog, "exec", return_value=QDialog.DialogCode.Accepted):
        with patch.object(BulkPointStyleDialog, "get_style_changes", return_value={"red": 255, "green": 255, "blue": 255}):
            win.point_controller.bulk_edit_style_workflow()

    assert win._point_service.get_point("pt-1").red == 255
    assert win._point_service.get_point("pt-2").red == 255

    win.undo()
    assert win._point_service.get_point("pt-1").red == orig_r1
    assert win._point_service.get_point("pt-2").red == orig_r2

    win.redo()
    assert win._point_service.get_point("pt-1").red == 255
    assert win._point_service.get_point("pt-2").red == 255
    win.close()


# =============================================================================
# Section 54: Подписи точек на карте (тесты 39–44)
# =============================================================================

def test_39_labels_mode_hidden_shows_no_labels(qapp, clean_settings, default_gpkg):
    """39. В режиме 'hidden' подписи на карте не отображаются."""
    win = MainWindow(map_path=default_gpkg)
    p1 = create_sample_point("pt-1", "LabelTest")
    win.point_controller._cmd_add_point(p1)

    win._set_labels_mode("hidden")
    lbl_item = win.map_canvas._user_label_items.get("pt-1")
    assert lbl_item is not None
    assert not lbl_item.isVisible()
    win.close()


def test_40_labels_mode_all_shows_all_labels(qapp, clean_settings, default_gpkg):
    """40. В режиме 'all' отображаются подписи всех точек."""
    win = MainWindow(map_path=default_gpkg)
    p1 = create_sample_point("pt-1", "Label 1")
    p2 = create_sample_point("pt-2", "Label 2")
    win.point_controller._cmd_add_point(p1)
    win.point_controller._cmd_add_point(p2)

    win._set_labels_mode("all")
    assert win.map_canvas._user_label_items["pt-1"].isVisible()
    assert win.map_canvas._user_label_items["pt-2"].isVisible()
    win.close()


def test_41_labels_mode_selected_shows_only_selected(qapp, clean_settings, default_gpkg):
    """41. В режиме 'selected' отображаются только подписи выбранных точек."""
    win = MainWindow(map_path=default_gpkg)
    p1 = create_sample_point("pt-1", "L1")
    p2 = create_sample_point("pt-2", "L2")
    win.point_controller._cmd_add_point(p1)
    win.point_controller._cmd_add_point(p2)

    win._set_labels_mode("selected")
    win.points_panel.select_point_ids(["pt-1"])

    assert win.map_canvas._user_label_items["pt-1"].isVisible()
    assert not win.map_canvas._user_label_items["pt-2"].isVisible()
    win.close()


def test_42_labels_have_item_ignores_transformations(qapp, clean_settings, default_gpkg):
    """42. Элементы подписей имеют флаг ItemIgnoresTransformations."""
    win = MainWindow(map_path=default_gpkg)
    p1 = create_sample_point("pt-1", "ScaleTest")
    win.point_controller._cmd_add_point(p1)

    lbl_item = win.map_canvas._user_label_items["pt-1"]
    from PySide6.QtWidgets import QGraphicsItem
    assert bool(lbl_item.flags() & QGraphicsItem.GraphicsItemFlag.ItemIgnoresTransformations)
    win.close()


def test_43_labels_z_value_above_markers_and_zones(qapp, clean_settings, default_gpkg):
    """43. Z-значение подписей равно 110.0 (выше маркеров 100 и зон 50)."""
    win = MainWindow(map_path=default_gpkg)
    p1 = create_sample_point("pt-1", "ZTest")
    win.point_controller._cmd_add_point(p1)

    lbl_item = win.map_canvas._user_label_items["pt-1"]
    assert lbl_item.zValue() == 110.0
    win.close()


def test_44_labels_mode_persists_in_app_settings(qapp, clean_settings):
    """44. Режим подписей сохраняется в AppSettingsService."""
    win = MainWindow()
    win._set_labels_mode("all")
    assert win._settings_service.get_point_labels_mode() == "all"
    win.close()


# =============================================================================
# Section 55: Быстрая навигация и центрирование (тесты 45–48)
# =============================================================================

def test_45_show_all_points_calculates_correct_extent(qapp, clean_settings, default_gpkg):
    """45. Метод show_all_points масштабирует холст ко всем точкам."""
    win = MainWindow(map_path=default_gpkg)
    p1 = create_sample_point("pt-1", "P1", lat=56.0, lon=47.0)
    p2 = create_sample_point("pt-2", "P2", lat=57.0, lon=48.0)
    win.point_controller._cmd_add_point(p1)
    win.point_controller._cmd_add_point(p2)

    with patch.object(win.map_canvas, "zoom_to_points") as mock_zoom:
        win.point_controller.show_all_points()
        assert mock_zoom.called
        coords = mock_zoom.call_args[0][0]
        assert len(coords) == 2

    win.close()


def test_46_zoom_to_selected_single_point(qapp, clean_settings, default_gpkg):
    """46. Приближение к одной выделенной точке."""
    win = MainWindow(map_path=default_gpkg)
    p1 = create_sample_point("pt-1", "P1", lat=56.5, lon=47.5)
    win.point_controller._cmd_add_point(p1)
    win.points_panel.select_point_ids(["pt-1"])

    with patch.object(win.map_canvas, "zoom_to_points") as mock_zoom:
        win.point_controller.zoom_to_selected()
        assert mock_zoom.called

    win.close()


def test_47_zoom_to_selected_multiple_points(qapp, clean_settings, default_gpkg):
    """47. Приближение ко всем выделенным точкам."""
    win = MainWindow(map_path=default_gpkg)
    p1 = create_sample_point("pt-1", "P1", lat=56.0, lon=47.0)
    p2 = create_sample_point("pt-2", "P2", lat=57.0, lon=48.0)
    win.point_controller._cmd_add_point(p1)
    win.point_controller._cmd_add_point(p2)
    win.points_panel.select_point_ids(["pt-1", "pt-2"])

    with patch.object(win.map_canvas, "zoom_to_points") as mock_zoom:
        win.point_controller.zoom_to_selected()
        assert mock_zoom.called
        assert len(mock_zoom.call_args[0][0]) == 2

    win.close()


def test_48_navigation_actions_disabled_without_map_or_points(qapp, clean_settings):
    """48. Действия быстрой навигации отключены при отсутствии карты или точек."""
    win = MainWindow()
    assert not win.show_all_points_action.isEnabled()
    assert not win.zoom_to_selected_action.isEnabled()
    win.close()


# =============================================================================
# Section 56: Копирование координат нескольких точек TSV (тесты 49–51)
# =============================================================================

def test_49_copy_selected_coordinates_tsv_format(qapp, clean_settings):
    """49. Форматирование координат нескольких точек в буфер обмена (TSV)."""
    win = MainWindow()
    p1 = create_sample_point("pt-1", "Alpha", lat=56.123456, lon=47.654321)
    p2 = create_sample_point("pt-2", "Beta", lat=56.222222, lon=47.333333)
    win.point_controller._cmd_add_point(p1)
    win.point_controller._cmd_add_point(p2)
    win.points_panel.select_point_ids(["pt-1", "pt-2"])

    text = win.point_controller.copy_selected_coordinates()
    expected = "Alpha\t56.123456\t47.654321\nBeta\t56.222222\t47.333333"
    assert text == expected
    assert QApplication.clipboard().text() == expected
    win.close()


def test_50_copy_selected_coordinates_preserves_precision(qapp, clean_settings):
    """50. Координаты копируются с точностью ровно 6 знаков после запятой."""
    win = MainWindow()
    p1 = create_sample_point("pt-1", "Exact", lat=55.1, lon=37.2)
    win.point_controller._cmd_add_point(p1)
    win.points_panel.select_point_ids(["pt-1"])

    text = win.point_controller.copy_selected_coordinates()
    assert text == "Exact\t55.100000\t37.200000"
    win.close()


def test_51_copy_selected_coordinates_empty_selection(qapp, clean_settings):
    """51. При пустом выборе возвращается пустая строка."""
    win = MainWindow()
    text = win.point_controller.copy_selected_coordinates()
    assert text == ""
    win.close()


# =============================================================================
# Section 57: Глобальное переключение видимости и меню (тесты 52–56)
# =============================================================================

def test_52_toggle_show_points_hides_all_markers(qapp, clean_settings, default_gpkg):
    """52. Глобальное скрытие маркеров точек на карте."""
    win = MainWindow(map_path=default_gpkg)
    p1 = create_sample_point("pt-1", "P1")
    win.point_controller._cmd_add_point(p1)

    win._toggle_show_points(False)
    assert not win.map_canvas._user_point_items["pt-1"].isVisible()

    win._toggle_show_points(True)
    assert win.map_canvas._user_point_items["pt-1"].isVisible()
    win.close()


def test_53_toggle_show_zones_hides_all_zones(qapp, clean_settings, default_gpkg):
    """53. Глобальное скрытие геодезических зон на карте."""
    win = MainWindow(map_path=default_gpkg)
    p1 = create_sample_point("pt-1", "P1", zone_enabled=True, radius_m=1000.0)
    win.point_controller._cmd_add_point(p1)

    win._toggle_show_zones(False)
    assert not win.map_canvas._user_zone_items["pt-1"].isVisible()

    win._toggle_show_zones(True)
    assert win.map_canvas._user_zone_items["pt-1"].isVisible()
    win.close()


def test_54_global_visibility_does_not_mutate_point_model(qapp, clean_settings, default_gpkg):
    """54. Глобальные переключатели видимости не изменяют свойства модели MapPoint."""
    win = MainWindow(map_path=default_gpkg)
    p1 = create_sample_point("pt-1", "P1", zone_enabled=True)
    win.point_controller._cmd_add_point(p1)

    win._toggle_show_points(False)
    win._toggle_show_zones(False)

    pt = win._point_service.get_point("pt-1")
    assert pt.visible is True
    assert pt.zone_enabled is True
    win.close()


def test_55_edit_menu_actions_state_sync(qapp, clean_settings):
    """55. Действия меню Правка синхронизируют доступность при смене выбора."""
    win = MainWindow()
    p1 = create_sample_point("pt-1", "P1")
    p2 = create_sample_point("pt-2", "P2")
    win.point_controller._cmd_add_point(p1)
    win.point_controller._cmd_add_point(p2)

    win.points_panel.clear_selection()
    assert not win.delete_selected_action.isEnabled()
    assert not win.bulk_edit_style_action.isEnabled()

    win.points_panel.select_point_ids(["pt-1"])
    assert win.delete_selected_action.isEnabled()
    assert not win.bulk_edit_style_action.isEnabled()

    win.points_panel.select_point_ids(["pt-1", "pt-2"])
    assert win.delete_selected_action.isEnabled()
    assert win.bulk_edit_style_action.isEnabled()
    win.close()


def test_56_menu_and_actions_symmetry_ru_en(qapp, clean_settings):
    """56. Полная симметрия RU/EN для всех новых действий и пунктов меню."""
    from rme_mapper.i18n.translations_en import TRANSLATIONS_EN
    from rme_mapper.i18n.translations_ru import TRANSLATIONS_RU

    required_keys = [
        "menu.edit",
        "menu.point_labels",
        "action.undo",
        "action.redo",
        "action.add_point_on_map",
        "action.delete_selected",
        "action.bulk_edit_style",
        "action.show_all_points",
        "action.zoom_to_selected",
        "action.copy_selected_coords",
        "action.labels_hidden",
        "action.labels_selected",
        "action.labels_all",
        "action.show_points",
        "action.show_zones",
        "tooltip.undo",
        "tooltip.redo",
        "tooltip.add_point_on_map",
        "tooltip.show_all_points",
        "tooltip.zoom_to_selected",
        "dialog.confirm_delete_multiple_title",
        "dialog.confirm_delete_multiple_text",
        "dialog.bulk_style.title",
        "dialog.bulk_style.apply",
        "dialog.labels_limit_title",
        "dialog.labels_limit_text",
        "status.selection_count",
        "status.bulk_styled",
        "status.coords_selected_copied",
        "status.add_point_on_map_hint",
        "status.undo_done",
        "status.redo_done",
    ]

    for k in required_keys:
        assert k in TRANSLATIONS_RU, f"Key missing in RU: {k}"
        assert k in TRANSLATIONS_EN, f"Key missing in EN: {k}"

    assert set(TRANSLATIONS_RU.keys()) == set(TRANSLATIONS_EN.keys())
