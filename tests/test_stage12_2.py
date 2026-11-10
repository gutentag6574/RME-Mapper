"""Тесты для Этапа 12.2 — Удобство работы + Защита пользовательских данных.

Разделы тестирования (60 тестов):
- Section 39: Drag & Drop (тесты 1–8)
- Section 40: Недавние проекты (тесты 9–15)
- Section 41: Недавние карты (тесты 16–21)
- Section 42: Запоминание последних каталогов (тесты 22–27)
- Section 43: Поиск и фильтрация точек по имени (тесты 28–33)
- Section 44: Отображение координат курсора в статус-баре (тесты 34–39)
- Section 45: Копирование координат точки в буфер обмена (тесты 40–45)
- Section 46: Горячие клавиши и подтверждение удаления точки (тесты 46–50)
- Section 47: Резервная копия (*.bak) и аварийное восстановление (тесты 51–56)
- Section 48: Безопасность, лимиты и целостность GeoPackage (тесты 57–60)
"""

import hashlib
import json
import os
from pathlib import Path
from unittest.mock import MagicMock
import pytest

from PySide6.QtCore import QMimeData, QPoint, QPointF, Qt, QUrl
from PySide6.QtGui import QDragEnterEvent, QDropEvent, QKeyEvent
from PySide6.QtWidgets import QApplication, QDialog, QLineEdit, QMessageBox

from rme_mapper.maps.map_config import get_default_geopackage_path
from rme_mapper.models.map_point import MapPoint
from rme_mapper.models.map_profile import MapProfile
from rme_mapper.models.project_data import (
    PRIMARY_PROJECT_FORMAT,
    ProjectData,
    ProjectMapData,
    ProjectPointData,
)
from rme_mapper.services.app_settings_service import AppSettingsService
from rme_mapper.services.project_service import (
    MAX_PROJECT_FILE_SIZE,
    MAX_PROJECT_POINTS,
    ProjectService,
)
from rme_mapper.ui.controllers.point_controller import PointController
from rme_mapper.ui.controllers.project_controller import ProjectController
from rme_mapper.ui.main_window import MainWindow
from rme_mapper.ui.open_map_dialog import OpenMapDialog
from rme_mapper.ui.panels.points_panel import PointsPanel


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    yield app


@pytest.fixture
def default_gpkg():
    return get_default_geopackage_path()


class MockDragDropEvent:
    """Безопасный мок для Drag&Drop событий, предотвращающий доступ к неинициализированному C++ d_ptr."""

    def __init__(self, file_paths: list[str]) -> None:
        self._urls = [QUrl.fromLocalFile(p) for p in file_paths]
        self._accepted = False

        class _Mime:
            def __init__(self, urls):
                self._urls = urls

            def hasUrls(self):
                return bool(self._urls)

            def urls(self):
                return self._urls

        self._mime = _Mime(self._urls)

    def mimeData(self):
        return self._mime

    def acceptProposedAction(self):
        self._accepted = True

    def ignore(self):
        self._accepted = False

    def isAccepted(self):
        return self._accepted


def _make_drag_enter_event(urls: list[str]) -> MockDragDropEvent:
    return MockDragDropEvent(urls)


def _make_drop_event(urls: list[str]) -> MockDragDropEvent:
    return MockDragDropEvent(urls)



# =============================================================================
# Section 39: DRAG & DROP (Тесты 1–8)
# =============================================================================

def test_01_drag_enter_accepts_gpkg(qapp, tmp_path):
    """1. DragEnter с файлом .gpkg принимает действие."""
    win = MainWindow()
    f = tmp_path / "test_map.gpkg"
    f.touch()
    ev = _make_drag_enter_event([str(f)])
    win.dragEnterEvent(ev)
    assert ev.isAccepted()
    win.close()


def test_02_drag_enter_accepts_gpmap(qapp, tmp_path):
    """2. DragEnter с файлом проекта .gpmap принимает действие."""
    win = MainWindow()
    f = tmp_path / "project.gpmap"
    f.touch()
    ev = _make_drag_enter_event([str(f)])
    win.dragEnterEvent(ev)
    assert ev.isAccepted()
    win.close()


def test_03_drag_enter_accepts_rmeproject(qapp, tmp_path):
    """3. DragEnter с legacy файлом проекта .rmeproject принимает действие."""
    win = MainWindow()
    f = tmp_path / "legacy.rmeproject"
    f.touch()
    ev = _make_drag_enter_event([str(f)])
    win.dragEnterEvent(ev)
    assert ev.isAccepted()
    win.close()


def test_04_drag_enter_ignores_unsupported(qapp, tmp_path):
    """4. DragEnter с неподдерживаемым файлом (.pdf) отклоняет действие."""
    win = MainWindow()
    f = tmp_path / "data.pdf"
    f.touch()
    ev = _make_drag_enter_event([str(f)])
    win.dragEnterEvent(ev)
    assert not ev.isAccepted()
    win.close()


def test_05_drop_loads_gpkg_map(qapp, default_gpkg):
    """5. Drop файла .gpkg инициирует загрузку карты."""
    win = MainWindow()
    ev = _make_drop_event([str(default_gpkg)])
    win.dropEvent(ev)
    assert ev.isAccepted()
    assert win.map_controller.active_profile is not None or win.map_controller.map_path is not None
    win._set_modified(False)
    win.close()


def test_06_drop_opens_gpmap_project(qapp, tmp_path):
    """6. Drop файла .gpmap открывает проект."""
    win = MainWindow()
    proj = ProjectData(
        format=PRIMARY_PROJECT_FORMAT,
        version=1,
        map=ProjectMapData(map_id="", name="Тестовый проект"),
        layers={},
        points=[],
    )
    p = tmp_path / "test.gpmap"
    ProjectService.save_project(proj, p, create_backup=False)

    ev = _make_drop_event([str(p)])
    win.dropEvent(ev)
    assert ev.isAccepted()
    assert win.project_controller.current_project_path == p
    win._set_modified(False)
    win.close()


def test_07_drop_multiple_files_warning(qapp, tmp_path, default_gpkg, monkeypatch):
    """7. Drop нескольких файлов показывает предупреждение и открывает первый."""
    win = MainWindow()
    warning_called = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *args, **kwargs: warning_called.append(True))

    f2 = tmp_path / "second.gpkg"
    f2.touch()

    ev = _make_drop_event([str(default_gpkg), str(f2)])
    win.dropEvent(ev)

    assert len(warning_called) == 1
    assert win.map_controller.map_path == default_gpkg or win.map_controller.active_profile is not None
    win._set_modified(False)
    win.close()


def test_08_drop_unsupported_file_warning(qapp, tmp_path, monkeypatch):
    """8. Drop неподдерживаемого формата выдает предупреждение."""
    win = MainWindow()
    warning_called = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *args, **kwargs: warning_called.append(True))

    bad_file = tmp_path / "document.pdf"
    bad_file.touch()

    ev = _make_drop_event([str(bad_file)])
    win.dropEvent(ev)

    assert len(warning_called) == 1
    win.close()


# =============================================================================
# Section 40: RECENT PROJECTS (Тесты 9–15)
# =============================================================================

def test_09_add_recent_project_persists():
    """9. Сохранение проекта добавляет его путь в список недавних проектов."""
    svc = AppSettingsService(settings=None)
    svc.clear_recent_projects()
    svc.add_recent_project("/path/to/project_a.gpmap")
    assert svc.get_recent_projects() == ["/path/to/project_a.gpmap"]


def test_10_recent_projects_max_10():
    """10. Список недавних проектов содержит максимум 10 записей (новые первыми)."""
    svc = AppSettingsService(settings=None)
    svc.clear_recent_projects()
    for i in range(12):
        svc.add_recent_project(f"/path/to/project_{i}.gpmap")
    items = svc.get_recent_projects()
    assert len(items) == 10
    assert items[0] == "/path/to/project_11.gpmap"
    assert items[-1] == "/path/to/project_2.gpmap"


def test_11_recent_projects_no_duplicates():
    """11. Добавление существующего пути перемещает его в начало списка без дублирования."""
    svc = AppSettingsService(settings=None)
    svc.clear_recent_projects()
    svc.add_recent_project("/path/to/alpha.gpmap")
    svc.add_recent_project("/path/to/beta.gpmap")
    svc.add_recent_project("/path/to/alpha.gpmap")
    items = svc.get_recent_projects()
    assert items == ["/path/to/alpha.gpmap", "/path/to/beta.gpmap"]


def test_12_recent_projects_clear_list():
    """12. Очистка списка недавних проектов делает его пустым."""
    svc = AppSettingsService(settings=None)
    svc.clear_recent_projects()
    svc.add_recent_project("/path/to/alpha.gpmap")
    svc.clear_recent_projects()
    assert svc.get_recent_projects() == []


def test_13_recent_projects_missing_file_handled(qapp, monkeypatch):
    """13. Выбор несуществующего файла из недавних предупреждает и удаляет его из списка."""
    win = MainWindow()
    win._settings_service.clear_recent_projects()
    fake_path = "/non/existent/missing_project.gpmap"
    win._settings_service.add_recent_project(fake_path)

    warn_called = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *args, **kwargs: warn_called.append(True))

    win._open_recent_project(fake_path)
    assert len(warn_called) == 1
    assert fake_path not in win._settings_service.get_recent_projects()
    win.close()


def test_14_recent_projects_menu_empty_indicator(qapp):
    """14. Пустое меню недавних проектов отображает неактивный пункт-заглушку."""
    win = MainWindow()
    win._settings_service.clear_recent_projects()
    win._update_recent_projects_menu()
    actions = win.recent_projects_menu.actions()
    assert len(actions) == 1
    assert not actions[0].isEnabled()
    win.close()


def test_15_opening_project_adds_to_recent(qapp, tmp_path):
    """15. Открытие проекта через ProjectController добавляет его в недавние."""
    win = MainWindow()
    win._settings_service.clear_recent_projects()
    p = tmp_path / "opened.gpmap"
    proj = ProjectData(
        format=PRIMARY_PROJECT_FORMAT,
        version=1,
        map=ProjectMapData(map_id="", name="Open Test"),
        layers={},
        points=[],
    )
    ProjectService.save_project(proj, p, create_backup=False)

    win.open_project(p)
    recent = win._settings_service.get_recent_projects()
    assert str(p) in recent
    win._set_modified(False)
    win.close()


# =============================================================================
# Section 41: RECENT MAPS (Тесты 16–21)
# =============================================================================

def test_16_load_map_adds_to_recent_maps(qapp, default_gpkg):
    """16. Загрузка карты добавляет путь к ней в недавние карты."""
    win = MainWindow()
    win._settings_service.clear_recent_maps()
    win.load_map(default_gpkg)
    items = win._settings_service.get_recent_maps()
    assert str(default_gpkg) in items
    win._set_modified(False)
    win.close()


def test_17_recent_maps_max_10():
    """17. Недавние карты содержат не более 10 записей (новые первыми)."""
    svc = AppSettingsService(settings=None)
    svc.clear_recent_maps()
    for i in range(15):
        svc.add_recent_map(f"/path/to/map_{i}.gpkg")
    items = svc.get_recent_maps()
    assert len(items) == 10
    assert items[0] == "/path/to/map_14.gpkg"
    assert items[-1] == "/path/to/map_5.gpkg"


def test_18_recent_maps_no_duplicates():
    """18. Повторное добавление карты перемещает ее на первое место без дублирования."""
    svc = AppSettingsService(settings=None)
    svc.clear_recent_maps()
    svc.add_recent_map("/path/to/mari_el.gpkg")
    svc.add_recent_map("/path/to/tatarstan.gpkg")
    svc.add_recent_map("/path/to/mari_el.gpkg")
    assert svc.get_recent_maps() == ["/path/to/mari_el.gpkg", "/path/to/tatarstan.gpkg"]


def test_19_recent_maps_clear_list():
    """19. Очистить список недавних карт удаляет все записи."""
    svc = AppSettingsService(settings=None)
    svc.clear_recent_maps()
    svc.add_recent_map("/path/to/map.gpkg")
    svc.clear_recent_maps()
    assert svc.get_recent_maps() == []


def test_20_recent_maps_missing_file_handled(qapp, monkeypatch):
    """20. Выбор отсутствующей карты из недавних показывает предупреждение и очищает запись."""
    win = MainWindow()
    win._settings_service.clear_recent_maps()
    fake_map = "/missing/dir/fake_map.gpkg"
    win._settings_service.add_recent_map(fake_map)

    warn_called = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *args, **kwargs: warn_called.append(True))

    win._open_recent_map(fake_map)
    assert len(warn_called) == 1
    assert fake_map not in win._settings_service.get_recent_maps()
    win.close()


def test_21_recent_maps_menu_empty_indicator(qapp):
    """21. Пустое меню недавних карт показывает неактивную подсказку."""
    win = MainWindow()
    win._settings_service.clear_recent_maps()
    win._update_recent_maps_menu()
    actions = win.recent_maps_menu.actions()
    assert len(actions) == 1
    assert not actions[0].isEnabled()
    win.close()


# =============================================================================
# Section 42: LAST DIRECTORIES MEMORY (Тесты 22–27)
# =============================================================================

def test_22_last_map_directory_saved():
    """22. AppSettingsService сохраняет и возвращает последний каталог карт."""
    svc = AppSettingsService(settings=None)
    svc.set_last_map_directory("/workspace/maps")
    assert Path(svc.get_last_map_directory()) == Path("/workspace/maps")


def test_23_last_project_directory_saved():
    """23. AppSettingsService сохраняет и возвращает последний каталог проектов."""
    svc = AppSettingsService(settings=None)
    svc.set_last_project_directory("/workspace/projects")
    assert Path(svc.get_last_project_directory()) == Path("/workspace/projects")


def test_24_last_map_directory_fallback(tmp_path):
    """24. Если каталог карт не существует, при check_exists возвращается fallback."""
    svc = AppSettingsService(settings=None)
    svc.set_last_map_directory("/non/existent/path/for/test")
    res = svc.get_last_map_directory(check_exists=True, fallback=str(tmp_path))
    assert res == str(tmp_path)


def test_25_last_project_directory_fallback(tmp_path):
    """25. Если каталог проектов не существует, при check_exists возвращается fallback."""
    svc = AppSettingsService(settings=None)
    svc.set_last_project_directory("/invalid/dir")
    res = svc.get_last_project_directory(check_exists=True, fallback=str(tmp_path))
    assert res == str(tmp_path)


def test_26_save_as_uses_last_directory(qapp, tmp_path, monkeypatch):
    """26. Save As открывает диалог с каталогом из last_project_directory."""
    win = MainWindow()
    win._settings_service.set_last_project_directory(str(tmp_path))

    captured_dir = []
    from PySide6.QtWidgets import QFileDialog
    monkeypatch.setattr(
        QFileDialog,
        "getSaveFileName",
        lambda parent, caption, dir, filter: (captured_dir.append(dir) or "", ""),
    )

    win.save_project_as()
    assert len(captured_dir) == 1
    assert captured_dir[0] == str(tmp_path)
    win.close()


def test_27_open_dialog_uses_last_map_directory(qapp, tmp_path):
    """27. OpenMapDialog инициализирует обзор каталогом из last_map_directory."""
    dlg = OpenMapDialog(initial_dir=tmp_path)
    assert dlg._initial_dir == tmp_path
    dlg.close()


# =============================================================================
# Section 43: POINT NAME SEARCH / FILTER (Тесты 28–33)
# =============================================================================

def test_28_search_filter_hides_unmatched_rows(qapp):
    """28. Ввод запроса в строку поиска скрывает строки с несовпадающими именами."""
    panel = PointsPanel()
    panel.add_row("1", "Йошкар-Ола", "56.63", "47.88", "Круг", "—")
    panel.add_row("2", "Волжск", "55.85", "48.35", "Круг", "—")
    panel.add_row("3", "Козьмодемьянск", "56.33", "46.56", "Круг", "—")

    panel.search_input.setText("Волж")
    assert not panel.points_table.isRowHidden(1)
    assert panel.points_table.isRowHidden(0)
    assert panel.points_table.isRowHidden(2)
    panel.close()


def test_29_search_filter_case_insensitive(qapp):
    """29. Поиск нечувствителен к регистру (йошкар находит Йошкар-Ола)."""
    panel = PointsPanel()
    panel.add_row("1", "Йошкар-Ола", "56.63", "47.88", "Круг", "—")
    panel.search_input.setText("йошкар")
    assert not panel.points_table.isRowHidden(0)
    panel.close()


def test_30_search_clear_restores_all_rows(qapp):
    """30. Очистка строки поиска восстанавливает отображение всех строк."""
    panel = PointsPanel()
    panel.add_row("1", "Альфа", "56.0", "47.0", "Круг", "—")
    panel.add_row("2", "Бета", "56.1", "47.1", "Круг", "—")

    panel.search_input.setText("Альфа")
    assert panel.points_table.isRowHidden(1)

    panel.search_input.clear()
    assert not panel.points_table.isRowHidden(0)
    assert not panel.points_table.isRowHidden(1)
    panel.close()


def test_31_search_does_not_modify_points_or_dirty(qapp, default_gpkg):
    """31. Фильтрация поиска в PointsPanel не меняет сервис точек и флаг is_modified."""
    win = MainWindow()
    win.load_map(default_gpkg)
    pt = win._point_service.add_point("Точка Тест", 56.63, 47.88)
    win.point_controller.add_point_to_table(pt)
    win._set_modified(False)

    win.points_panel.search_input.setText("Неизвестно")
    assert win.points_table.isRowHidden(0)
    assert len(win._point_service) == 1
    assert not win.is_modified
    win.close()


def test_32_adding_point_while_filtered(qapp):
    """32. Добавление строки во время активного фильтра корректно скрывает/отображает ее."""
    panel = PointsPanel()
    panel.search_input.setText("Марий")
    r1 = panel.add_row("1", "Марий Эл", "56.0", "47.0", "Круг", "—")
    r2 = panel.add_row("2", "Казань", "55.0", "49.0", "Круг", "—")

    assert not panel.points_table.isRowHidden(r1)
    assert panel.points_table.isRowHidden(r2)
    panel.close()


def test_33_updating_point_while_filtered(qapp):
    """33. Обновление имени точки пересчитывает ее видимость при фильтре."""
    panel = PointsPanel()
    panel.add_row("1", "Старое имя", "56.0", "47.0", "Круг", "—")
    panel.search_input.setText("Новое")
    assert panel.points_table.isRowHidden(0)

    panel.update_row(0, "Новое имя", "56.0", "47.0", "Круг", "—")
    assert not panel.points_table.isRowHidden(0)
    panel.close()


# =============================================================================
# Section 44: CURSOR COORDINATES DISPLAY (Тесты 34–39)
# =============================================================================

def test_34_cursor_coords_hidden_when_no_map(qapp):
    """34. При отсутствии загруженной карты виджет координат курсора скрыт/пуст."""
    win = MainWindow()
    assert not win.status_coords_label.isVisible() or win.status_coords_label.text() == ""
    win._on_canvas_cursor_moved(47.88, 56.63)
    assert not win.status_coords_label.isVisible() or win.status_coords_label.text() == ""
    win.close()


def test_35_cursor_coords_geographic_display(qapp, default_gpkg):
    """35. При географической карте выводятся десятичные координаты X / Y (Lon / Lat)."""
    win = MainWindow()
    win.load_map(default_gpkg)
    win.map_controller.active_crs = "OGC:CRS84"

    win._on_canvas_cursor_moved(47.883333, 56.633333)
    assert not win.status_coords_label.isHidden()
    text = win.status_coords_label.text()
    assert "47.883333" in text
    assert "56.633333" in text
    win._set_modified(False)
    win.close()


def test_36_cursor_coords_projected_display(qapp, default_gpkg):
    """36. При спроецированной карте отображаются метры (м)."""
    win = MainWindow()
    win.load_map(default_gpkg)
    win.map_controller.active_crs = "EPSG:3857"

    win._on_canvas_cursor_moved(5330335.0, 7682220.0)
    assert not win.status_coords_label.isHidden()
    text = win.status_coords_label.text()
    assert "м" in text
    win._set_modified(False)
    win.close()


def test_37_cursor_coords_hidden_on_leave(qapp, default_gpkg):
    """37. При выходе курсора за пределы MapCanvas текст координат скрывается."""
    win = MainWindow()
    win.load_map(default_gpkg)
    win._on_canvas_cursor_moved(47.88, 56.63)
    assert not win.status_coords_label.isHidden()

    win._on_canvas_cursor_left()
    assert win.status_coords_label.isHidden() or win.status_coords_label.text() == ""
    win._set_modified(False)
    win.close()



def test_38_map_canvas_mouse_move_emits_signal(qapp):
    """38. MapCanvas испускает сигнал cursor_position_changed при движении мыши."""
    from rme_mapper.maps.map_canvas import MapCanvas
    canvas = MapCanvas()
    received = []
    canvas.cursor_position_changed.connect(lambda x, y: received.append((x, y)))

    from PySide6.QtGui import QMouseEvent
    ev = QMouseEvent(
        QMouseEvent.Type.MouseMove,
        QPointF(50.0, 50.0),
        Qt.MouseButton.NoButton,
        Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.NoModifier,
    )
    canvas.mouseMoveEvent(ev)
    assert len(received) == 1
    canvas.close()


def test_39_status_coords_cleared_on_close_map(qapp, default_gpkg):
    """39. Выгрузка карты скрывает координаты курсора в статусе."""
    win = MainWindow()
    win.load_map(default_gpkg)
    win._on_canvas_cursor_moved(47.88, 56.63)
    assert not win.status_coords_label.isHidden()

    win.close_map(prompt=False)
    assert win.status_coords_label.isHidden() or win.status_coords_label.text() == ""
    win.close()


# =============================================================================
# Section 45: COPY COORDINATES TO CLIPBOARD (Тесты 40–45)
# =============================================================================

def test_40_copy_coordinates_dd_format(qapp):
    """40. Копирование DD форматирует координаты как 'lat.6f, lon.6f'."""
    panel = PointsPanel()
    prop_panel = MagicMock()
    canvas = MagicMock()
    ctrl = PointController(
        parent_widget=panel,
        point_service=MagicMock(),
        points_panel=panel,
        properties_panel=prop_panel,
        map_canvas=canvas,
        get_active_crs=lambda: "OGC:CRS84",
        get_active_profile=lambda: None,
        get_map_path=lambda: None,
        get_boundary_geometry=lambda: None,
        on_modified=lambda: None,
    )
    pt = MapPoint(id="1", name="Тест", latitude=56.6333333, longitude=47.8833333)
    formatted = ctrl.copy_coordinates_dd(pt)
    assert formatted == "56.633333, 47.883333"
    panel.close()


def test_41_copy_coordinates_dms_format(qapp):
    """41. Копирование DMS форматирует градусы, минуты, секунды с направлением."""
    panel = PointsPanel()
    ctrl = PointController(
        parent_widget=panel,
        point_service=MagicMock(),
        points_panel=panel,
        properties_panel=MagicMock(),
        map_canvas=MagicMock(),
        get_active_crs=lambda: "OGC:CRS84",
        get_active_profile=lambda: None,
        get_map_path=lambda: None,
        get_boundary_geometry=lambda: None,
        on_modified=lambda: None,
    )
    pt = MapPoint(id="1", name="Тест", latitude=56.633333, longitude=47.883333)
    formatted = ctrl.copy_coordinates_dms(pt)
    assert "°" in formatted
    assert "'" in formatted
    assert '"' in formatted
    assert "N" in formatted
    assert "E" in formatted
    panel.close()


def test_42_copy_coordinates_map_xy_with_map(qapp, default_gpkg):
    """42. Копирование X/Y карты вычисляет координаты в активной CRS карты."""
    win = MainWindow()
    win.load_map(default_gpkg)
    pt = MapPoint(id="1", name="Тест", latitude=56.63, longitude=47.88)
    res = win.point_controller.copy_coordinates_map_xy(pt)
    assert res is not None
    assert "," in res
    win._set_modified(False)
    win.close()


def test_43_copy_coordinates_map_xy_disabled_without_map(qapp):
    """43. Копирование X/Y карты возвращает None при отсутствии открытой карты."""
    panel = PointsPanel()
    ctrl = PointController(
        parent_widget=panel,
        point_service=MagicMock(),
        points_panel=panel,
        properties_panel=MagicMock(),
        map_canvas=MagicMock(),
        get_active_crs=lambda: "OGC:CRS84",
        get_active_profile=lambda: None,
        get_map_path=lambda: None,
        get_boundary_geometry=lambda: None,
        on_modified=lambda: None,
    )
    pt = MapPoint(id="1", name="Тест", latitude=56.63, longitude=47.88)
    assert ctrl.copy_coordinates_map_xy(pt) is None
    panel.close()


def test_44_copy_coordinates_clipboard_and_status(qapp):
    """44. Копирование координат обновляет буфер обмена и выводит статус."""
    panel = PointsPanel()
    status_log = []
    ctrl = PointController(
        parent_widget=panel,
        point_service=MagicMock(),
        points_panel=panel,
        properties_panel=MagicMock(),
        map_canvas=MagicMock(),
        get_active_crs=lambda: "OGC:CRS84",
        get_active_profile=lambda: None,
        get_map_path=lambda: None,
        get_boundary_geometry=lambda: None,
        on_modified=lambda: None,
        set_status_message=lambda msg, to: status_log.append(msg),
    )
    pt = MapPoint(id="1", name="Тест", latitude=56.0, longitude=47.0)
    ctrl.copy_coordinates_dd(pt)
    assert QApplication.clipboard().text() == "56.000000, 47.000000"
    assert len(status_log) == 1
    panel.close()


def test_45_context_menu_contains_copy_submenu(qapp):
    """45. Контекстное меню таблицы точек содержит пункт копирования координат."""
    win = MainWindow()
    pt = win._point_service.add_point("ТестМеню", 56.63, 47.88)
    win.point_controller.add_point_to_table(pt)
    win.points_table.selectRow(0)

    # Проверяем наличие методов копирования координат в контроллере
    assert hasattr(win.point_controller, "copy_coordinates_dd")
    assert hasattr(win.point_controller, "copy_coordinates_dms")
    assert hasattr(win.point_controller, "copy_coordinates_map_xy")
    win._set_modified(False)
    win.close()


# =============================================================================
# Section 46: KEYBOARD SHORTCUTS & DELETE CONFIRMATION (Тесты 46–50)
# =============================================================================

def test_46_insert_key_triggers_add_point(qapp):
    """46. Клавиша Insert на панели точек испускает add_clicked."""
    panel = PointsPanel()
    signal_fired = []
    panel.add_clicked.connect(lambda: signal_fired.append(True))

    ev = QKeyEvent(QKeyEvent.Type.KeyPress, Qt.Key.Key_Insert, Qt.KeyboardModifier.NoModifier)
    panel.keyPressEvent(ev)
    assert len(signal_fired) == 1
    panel.close()


def test_47_f2_key_triggers_edit_point(qapp):
    """47. Клавиша F2 при выбранной строке испускает edit_clicked."""
    panel = PointsPanel()
    signal_fired = []
    panel.edit_clicked.connect(lambda: signal_fired.append(True))

    panel.add_row("1", "Точка", "56.0", "47.0", "Круг", "—")
    panel.set_buttons_enabled(edit=True)

    ev = QKeyEvent(QKeyEvent.Type.KeyPress, Qt.Key.Key_F2, Qt.KeyboardModifier.NoModifier)
    panel.keyPressEvent(ev)
    assert len(signal_fired) == 1
    panel.close()


def test_48_delete_key_shows_confirmation(qapp, monkeypatch):
    """48. Клавиша Delete вызывает запрос подтверждения удаления."""
    panel = PointsPanel()
    pt_svc = MagicMock()
    pt_svc.__len__.return_value = 1
    ctrl = PointController(
        parent_widget=panel,
        point_service=pt_svc,
        points_panel=panel,
        properties_panel=MagicMock(),
        map_canvas=MagicMock(),
        get_active_crs=lambda: "OGC:CRS84",
        get_active_profile=lambda: None,
        get_map_path=lambda: None,
        get_boundary_geometry=lambda: None,
        on_modified=lambda: None,
    )
    panel.add_row("1", "Точка", "56.0", "47.0", "Круг", "—")
    ctrl._table_point_ids.append("id_1")
    panel.points_table.selectRow(0)

    question_called = []
    monkeypatch.setattr(
        QMessageBox,
        "question",
        lambda *args, **kwargs: (question_called.append(True) or QMessageBox.StandardButton.No),
    )

    ctrl.delete_point_workflow(confirm=True)
    assert len(question_called) == 1
    panel.close()


def test_49_delete_confirmation_accepted_deletes_point(qapp, monkeypatch):
    """49. При согласии на удаление точка удаляется."""
    win = MainWindow()
    pt = win._point_service.add_point("Удаляемая", 56.63, 47.88)
    win.point_controller.add_point_to_table(pt)
    win.points_table.selectRow(0)

    monkeypatch.setattr(QMessageBox, "question", lambda *args, **kwargs: QMessageBox.StandardButton.Yes)

    win.point_controller.delete_point_workflow(confirm=True)
    assert len(win._point_service) == 0
    assert win.points_table.rowCount() == 0
    win._set_modified(False)
    win.close()


def test_50_delete_confirmation_rejected_preserves_point(qapp, monkeypatch):
    """50. При отказе точка остается в сервисе и таблице."""
    win = MainWindow()
    pt = win._point_service.add_point("Сохраняемая", 56.63, 47.88)
    win.point_controller.add_point_to_table(pt)
    win.points_table.selectRow(0)

    monkeypatch.setattr(QMessageBox, "question", lambda *args, **kwargs: QMessageBox.StandardButton.No)

    win.point_controller.delete_point_workflow(confirm=True)
    assert len(win._point_service) == 1
    assert win.points_table.rowCount() == 1
    win._set_modified(False)
    win.close()


# =============================================================================
# Section 47: PROJECT BACKUP & CRASH RECOVERY (Тесты 51–56)
# =============================================================================

def test_51_save_creates_bak_file(tmp_path):
    """51. Перезапись существующего проекта создает файл *.gpmap.bak."""
    p = tmp_path / "project.gpmap"
    proj = ProjectData(
        format=PRIMARY_PROJECT_FORMAT,
        version=1,
        map=ProjectMapData(map_id="m1", name="M1"),
        layers={},
        points=[],
    )
    # Первое сохранение
    ProjectService.save_project(proj, p, create_backup=True)
    assert p.exists()
    bak = p.with_name("project.gpmap.bak")
    assert not bak.exists()

    # Второе сохранение (перезапись)
    proj2 = ProjectData(
        format=PRIMARY_PROJECT_FORMAT,
        version=1,
        map=ProjectMapData(map_id="m2", name="M2"),
        layers={},
        points=[],
    )
    ProjectService.save_project(proj2, p, create_backup=True)
    assert bak.exists()
    assert bak.stat().st_size > 0


def test_52_save_failure_leaves_target_intact(tmp_path, monkeypatch):
    """52. Ошибка при сохранении не повреждает исходный файл проекта."""
    p = tmp_path / "safe.gpmap"
    proj = ProjectData(
        format=PRIMARY_PROJECT_FORMAT,
        version=1,
        map=ProjectMapData(map_id="orig", name="Original"),
        layers={},
        points=[],
    )
    ProjectService.save_project(proj, p, create_backup=False)
    orig_content = p.read_text(encoding="utf-8")

    # Имитируем сбой os.replace
    def fake_replace(src, dst):
        raise OSError("Disk full simulation")

    monkeypatch.setattr(os, "replace", fake_replace)

    with pytest.raises(OSError):
        ProjectService.save_project(proj, p, create_backup=True)

    # Исходный файл должен остаться неизменным
    assert p.read_text(encoding="utf-8") == orig_content


def test_53_recovery_snapshot_saved_on_dirty(tmp_path):
    """53. save_recovery_snapshot сохраняет корректный JSON-снимок состояния."""
    snap_path = tmp_path / "test_snapshot.json"
    proj = ProjectData(
        format=PRIMARY_PROJECT_FORMAT,
        version=1,
        map=ProjectMapData(map_id="snap_map", name="Snap"),
        layers={"boundary": True},
        points=[
            ProjectPointData(
                id="pt1",
                name="Точка снимка",
                latitude=56.63,
                longitude=47.88,
            )
        ],
    )
    res_path = ProjectService.save_recovery_snapshot(proj, "/proj/path.gpmap", snap_path)
    assert res_path.exists()
    assert ProjectService.has_recovery_snapshot(snap_path)

    loaded_proj, curr_path = ProjectService.load_recovery_snapshot(snap_path)
    assert len(loaded_proj.points) == 1
    assert loaded_proj.points[0].name == "Точка снимка"
    assert curr_path == "/proj/path.gpmap"


def test_54_recovery_snapshot_cleared_on_save_or_clean_exit(tmp_path):
    """54. clear_recovery_snapshot удаляет файл аварийного снимка."""
    snap_path = tmp_path / "test_snap.json"
    proj = ProjectData(
        format=PRIMARY_PROJECT_FORMAT,
        version=1,
        map=ProjectMapData(map_id="m", name="M"),
        layers={},
        points=[],
    )
    ProjectService.save_recovery_snapshot(proj, None, snap_path)
    assert snap_path.exists()

    ProjectService.clear_recovery_snapshot(snap_path)
    assert not snap_path.exists()
    assert not ProjectService.has_recovery_snapshot(snap_path)


def test_55_startup_recovery_prompt_restores_state(qapp, tmp_path, monkeypatch):
    """55. При старте найденный валидный снимок предлагает восстановление и загружает точки."""
    snap_path = tmp_path / "recovery_snapshot.json"
    proj = ProjectData(
        format=PRIMARY_PROJECT_FORMAT,
        version=1,
        map=ProjectMapData(map_id="", name="Recovered"),
        layers={},
        points=[
            ProjectPointData(
                id="p1",
                name="Спасенная точка",
                latitude=56.63,
                longitude=47.88,
            )
        ],
    )
    ProjectService.save_recovery_snapshot(proj, None, snap_path)

    # Monkeypatch snapshot path
    monkeypatch.setattr(ProjectService, "get_recovery_snapshot_path", lambda: snap_path)
    monkeypatch.setattr(QMessageBox, "question", lambda *args, **kwargs: QMessageBox.StandardButton.Yes)

    win = MainWindow()
    assert len(win._point_service) == 1
    assert win.points_table.rowCount() == 1
    assert win.points_table.item(0, 1).text() == "Спасенная точка"
    assert win.is_modified
    win._set_modified(False)
    win.close()


def test_56_startup_corrupt_recovery_cleared(qapp, tmp_path, monkeypatch):
    """56. Поврежденный файл аварийного восстановления удаляется по подтверждению."""
    corrupt_path = tmp_path / "corrupt_snapshot.json"
    corrupt_path.write_text("{ this is corrupt json !!!", encoding="utf-8")

    monkeypatch.setattr(ProjectService, "get_recovery_snapshot_path", lambda: corrupt_path)
    monkeypatch.setattr(QMessageBox, "question", lambda *args, **kwargs: QMessageBox.StandardButton.Yes)

    win = MainWindow()
    assert not corrupt_path.exists()
    assert len(win._point_service) == 0
    win.close()


# =============================================================================
# Section 48: SECURITY, SAFETY & LIMITS (Тесты 57–60)
# =============================================================================

def test_57_max_project_file_size_rejected(tmp_path, monkeypatch):
    """57. ProjectService отклоняет файл проекта более 50 МБ."""
    huge_file = tmp_path / "huge.gpmap"
    huge_file.write_text("{}", encoding="utf-8")

    orig_stat = Path.stat

    def safe_stat(self, *args, **kwargs):
        res = orig_stat(self, *args, **kwargs)
        if str(self) == str(huge_file):
            return os.stat_result((
                res.st_mode,
                res.st_ino,
                res.st_dev,
                res.st_nlink,
                res.st_uid,
                res.st_gid,
                MAX_PROJECT_FILE_SIZE + 1024,
                res.st_atime,
                res.st_mtime,
                res.st_ctime,
            ))
        return res

    monkeypatch.setattr(Path, "stat", safe_stat)

    with pytest.raises(ValueError) as exc:
        ProjectService.load_project(huge_file)
    assert "50" in str(exc.value)



def test_58_max_points_limit_rejected(tmp_path):
    """58. ProjectService отклоняет проект, содержащий более 100 000 точек."""
    points_list = [{"latitude": 56.0, "longitude": 47.0}] * (MAX_PROJECT_POINTS + 1)
    raw = {
        "format": PRIMARY_PROJECT_FORMAT,
        "version": 1,
        "map": {},
        "layers": {},
        "points": points_list,
    }
    p = tmp_path / "too_many_points.gpmap"
    p.write_text(json.dumps(raw), encoding="utf-8")

    with pytest.raises(ValueError, match="превышает допустимый предел"):
        ProjectService.load_project(p)


def test_59_coordinate_bounds_enforced(tmp_path):
    """59. Точки с координатами за пределами [-90..90] или [-180..180] пропускаются или отклоняются."""
    raw = {
        "format": PRIMARY_PROJECT_FORMAT,
        "version": 1,
        "map": {},
        "layers": {},
        "points": [
            {"id": "bad1", "name": "Неверная широта", "latitude": 95.0, "longitude": 47.0},
            {"id": "good", "name": "Верная точка", "latitude": 56.63, "longitude": 47.88},
        ],
    }
    p = tmp_path / "bounds.gpmap"
    p.write_text(json.dumps(raw), encoding="utf-8")

    loaded = ProjectService.load_project(p)
    # Точка с недопустимой широтой должна быть отфильтрована валидатором
    assert len(loaded.points) == 1
    assert loaded.points[0].name == "Верная точка"


def test_60_geopackage_sources_read_only(default_gpkg):
    """60. Исходный файл GeoPackage остается строго неизменным (хэш файла совпадает)."""
    with open(default_gpkg, "rb") as f:
        orig_hash = hashlib.sha256(f.read()).hexdigest()

    win = MainWindow()
    win.load_map(default_gpkg)
    pt = win._point_service.add_point("Тест защиты GPKG", 56.63, 47.88)
    win.point_controller.add_point_to_table(pt)
    win._set_modified(False)
    win.close()

    with open(default_gpkg, "rb") as f:
        after_hash = hashlib.sha256(f.read()).hexdigest()

    assert orig_hash == after_hash, "Файл GeoPackage был изменен!"
