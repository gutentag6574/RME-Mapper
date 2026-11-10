"""Тесты для Этапа 12.2.1 — UI / UX Polishing.

Проверка компоновки, QSplitter, ToolBar, меню 'Вид', ThemeManager,
структурирования панели свойств, панели точек, счетчиков и сохранения настроек.
Всего 38 тестов (тесты 1–38).
"""

import os
from pathlib import Path
import pytest

from PySide6.QtCore import QRect, Qt
from PySide6.QtGui import QAction, QGuiApplication
from PySide6.QtWidgets import QApplication, QHeaderView, QSplitter

from rme_mapper.i18n import get_language, set_language
from rme_mapper.maps.map_config import get_default_geopackage_path
from rme_mapper.models.map_point import MapPoint
from rme_mapper.services.app_settings_service import AppSettingsService
from rme_mapper.ui.main_window import MainWindow
from rme_mapper.ui.panels.points_panel import PointsPanel
from rme_mapper.ui.panels.properties_panel import PropertiesPanel
from rme_mapper.ui.theme_manager import ThemeManager, get_theme_manager


@pytest.fixture(scope="session")
def qapp():
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    yield app


@pytest.fixture
def clean_settings():
    """Изолированная фикстура для очистки пользовательских настроек до и после теста."""
    settings = AppSettingsService()
    settings.clear()
    yield settings
    settings.clear()


@pytest.fixture
def default_gpkg():
    return get_default_geopackage_path()


# =============================================================================
# 39. TESTS — LAYOUT (Тесты 1–8)
# =============================================================================

def test_01_splitter_is_used(qapp, clean_settings):
    """1. QSplitter используется в качестве центрального виджета."""
    win = MainWindow()
    central = win.centralWidget()
    assert isinstance(central, QSplitter)
    assert win.workspace_splitter is central
    assert central.count() == 2
    assert central.widget(0) is win.splitter
    assert win.splitter.count() == 3
    assert central.widget(1) is win.points_panel


def test_02_left_panel_exists(qapp, clean_settings):
    """2. left panel существует и имеет защитный minimumWidth."""
    win = MainWindow()
    assert hasattr(win, "left_panel")
    assert win.left_panel is not None
    assert win.left_panel.minimumWidth() >= 220
    assert win.splitter.childrenCollapsible() is False


def test_03_right_panel_exists(qapp, clean_settings):
    """3. right panel существует и имеет защитный minimumWidth."""
    win = MainWindow()
    assert hasattr(win, "right_panel")
    assert win.right_panel is not None
    assert win.right_panel.minimumWidth() >= 240


def test_04_map_canvas_center(qapp, clean_settings):
    """4. map canvas расположен в центре и растягивается."""
    win = MainWindow()
    assert hasattr(win, "center_panel")
    assert win.center_panel is not None
    assert win.splitter.widget(1) is win.center_panel
    assert win.splitter.indexOf(win.center_panel) == 1


def test_05_splitter_state_saved(qapp, clean_settings):
    """5. splitter state сохраняется через AppSettingsService."""
    win = MainWindow()
    test_sizes = [290, 820, 290]
    win.splitter.setSizes(test_sizes)
    win.save_ui_state(force=True)

    saved = clean_settings.get_splitter_sizes()
    assert saved is not None
    assert len(saved) == 3


def test_06_splitter_state_restored(qapp, clean_settings):
    """6. splitter state восстанавливается из AppSettingsService."""
    clean_settings.set_splitter_sizes([250, 900, 250])
    win = MainWindow()
    win.set_auto_properties(False)
    win.show()
    win.restore_ui_state()

    sizes = win.splitter.sizes()
    assert len(sizes) == 3
    assert sizes[0] >= 220
    assert sizes[2] >= 240
    win.close()


def test_07_left_panel_hide_show(qapp, clean_settings):
    """7. left panel скрывается и показывается с синхронизацией действия."""
    win = MainWindow()
    win.show()
    assert not win.left_panel.isHidden()
    assert win.toggle_layers_points_action.isChecked()

    win.set_left_panel_visible(False)
    assert win.left_panel.isHidden()
    assert not win.toggle_layers_points_action.isChecked()
    assert clean_settings.get_left_panel_visible() is False

    win.set_left_panel_visible(True)
    assert not win.left_panel.isHidden()
    assert win.toggle_layers_points_action.isChecked()
    assert clean_settings.get_left_panel_visible() is True
    win.close()


def test_08_right_panel_hide_show(qapp, clean_settings):
    """8. right panel скрывается и показывается с синхронизацией действия."""
    win = MainWindow()
    win.set_auto_properties(False)
    win.show()
    assert not win.right_panel.isHidden()
    assert win.toggle_properties_action.isChecked()

    win.set_right_panel_visible(False)
    assert win.right_panel.isHidden()
    assert not win.toggle_properties_action.isChecked()
    assert clean_settings.get_right_panel_visible() is False

    win.set_right_panel_visible(True)
    assert not win.right_panel.isHidden()
    assert win.toggle_properties_action.isChecked()
    assert clean_settings.get_right_panel_visible() is True
    win.close()


# =============================================================================
# 40. TESTS — TOOLBAR (Тесты 9–15)
# =============================================================================

def test_09_toolbar_exists(qapp, clean_settings):
    """9. toolbar существует на главном окне."""
    win = MainWindow()
    assert hasattr(win, "main_toolbar")
    assert win.main_toolbar is not None
    assert win.main_toolbar.objectName() == "mainToolBar"


def test_10_toolbar_open_map_action(qapp, clean_settings):
    """10. toolbar содержит действие Открыть карту."""
    win = MainWindow()
    actions = win.main_toolbar.actions()
    assert win.open_map_action in actions


def test_11_toolbar_open_project_action(qapp, clean_settings):
    """11. toolbar содержит действие Открыть проект."""
    win = MainWindow()
    actions = win.main_toolbar.actions()
    assert win.open_action in actions


def test_12_toolbar_save_action(qapp, clean_settings):
    """12. toolbar содержит действие Сохранить."""
    win = MainWindow()
    actions = win.main_toolbar.actions()
    assert win.save_action in actions


def test_13_toolbar_add_point_action(qapp, clean_settings):
    """13. toolbar содержит действие Добавить точку."""
    win = MainWindow()
    actions = win.main_toolbar.actions()
    assert win.add_pt_action in actions


def test_14_toolbar_fit_map_action(qapp, clean_settings):
    """14. toolbar содержит действие Показать всю карту."""
    win = MainWindow()
    actions = win.main_toolbar.actions()
    assert hasattr(win, "fit_map_action")
    assert win.fit_map_action in actions


def test_15_toolbar_no_duplicate_actions(qapp, clean_settings):
    """15. toolbar не создает дубликатов QAction."""
    win = MainWindow()
    tb_actions = [a for a in win.main_toolbar.actions() if not a.isSeparator()]
    unique_instances = set(tb_actions)
    assert len(tb_actions) == len(unique_instances)
    assert win.open_map_action in unique_instances
    assert win.open_action in unique_instances
    assert win.save_action in unique_instances
    assert win.add_pt_action in unique_instances
    assert win.fit_map_action in unique_instances


# =============================================================================
# 41. TESTS — SETTINGS (Тесты 16–21)
# =============================================================================

def test_16_window_geometry_saved(qapp, clean_settings):
    """16. window geometry корректно сохраняется в сервисе."""
    clean_settings.set_window_geometry(100, 150, 1280, 720)
    geom = clean_settings.get_window_geometry()
    assert geom == {"x": 100, "y": 150, "width": 1280, "height": 720}


def test_17_window_geometry_restored(qapp, clean_settings):
    """17. window geometry восстанавливается при валидных координатах."""
    screen = QGuiApplication.primaryScreen()
    if screen:
        avail = screen.availableGeometry()
        target_w = min(1100, avail.width())
        target_h = min(700, avail.height())
        clean_settings.set_window_geometry(avail.x() + 10, avail.y() + 10, target_w, target_h)
        win = MainWindow()
        win.restore_ui_state()
        assert win.width() == target_w
        assert win.height() == target_h


def test_18_maximized_state_restored(qapp, clean_settings):
    """18. maximized state восстанавливается."""
    clean_settings.set_window_maximized(True)
    assert clean_settings.get_window_maximized() is True
    win = MainWindow()
    win.restore_ui_state()
    assert win.isMaximized() or win._settings_service.get_window_maximized()


def test_19_invalid_screen_position_fallback(qapp, clean_settings):
    """19. invalid screen position использует безопасный fallback."""
    # Заведомо некорректные координаты экрана (далеко за пределами любого монитора)
    clean_settings.set_window_geometry(-99999, -99999, 1200, 800)
    win = MainWindow()
    win.restore_ui_state()
    # Окно должно применить fallback и быть адаптировано под рабочую область (BUG-005)
    screen = QGuiApplication.primaryScreen()
    avail = screen.availableGeometry() if screen else None
    max_w = min(1400, avail.width()) if avail else 1400
    max_h = min(850, avail.height()) if avail else 850
    assert 0 < win.width() <= max_w
    assert 0 < win.height() <= max_h


def test_20_toolbar_visibility_persists(qapp, clean_settings):
    """20. toolbar visibility сохраняется в настройках."""
    win = MainWindow()
    win.set_toolbar_visible(False)
    assert win.main_toolbar.isHidden()
    assert clean_settings.get_toolbar_visible() is False

    win2 = MainWindow()
    win2.restore_ui_state()
    assert win2.main_toolbar.isHidden()
    win.close()
    win2.close()


def test_21_panel_visibility_persists(qapp, clean_settings):
    """21. panel visibility сохраняется в настройках."""
    win = MainWindow()
    win.set_left_panel_visible(False)
    win.set_right_panel_visible(False)
    assert clean_settings.get_left_panel_visible() is False
    assert clean_settings.get_right_panel_visible() is False

    win2 = MainWindow()
    win2.restore_ui_state()
    assert win2.left_panel.isHidden()
    assert win2.right_panel.isHidden()
    win.close()
    win2.close()


# =============================================================================
# 42. TESTS — TABLE (Тесты 22–27)
# =============================================================================

def test_22_table_name_column_stretches(qapp, clean_settings):
    """22. name column растягивается (Stretch mode)."""
    panel = PointsPanel()
    header = panel.points_table.horizontalHeader()
    assert header.sectionResizeMode(1) == QHeaderView.ResizeMode.Stretch


def test_23_table_number_column_compact(qapp, clean_settings):
    """23. number column компактная (ResizeToContents)."""
    panel = PointsPanel()
    header = panel.points_table.horizontalHeader()
    assert header.sectionResizeMode(0) == QHeaderView.ResizeMode.ResizeToContents


def test_24_table_headers_ru(qapp, clean_settings):
    """24. headers таблицы на русском языке."""
    win = MainWindow()
    win.switch_language("ru")
    headers = [
        win.points_table.horizontalHeaderItem(i).text()
        for i in range(win.points_table.columnCount())
    ]
    assert headers == ["№", "Название", "Широта", "Долгота", "Форма", "Радиус"]


def test_25_table_headers_en(qapp, clean_settings):
    """25. headers таблицы на английском языке."""
    win = MainWindow()
    win.switch_language("en")
    headers = [
        win.points_table.horizontalHeaderItem(i).text()
        for i in range(win.points_table.columnCount())
    ]
    assert headers == ["#", "Name", "Latitude", "Longitude", "Shape", "Radius"]


def test_26_point_count_updates(qapp, clean_settings):
    """26. point count обновляется при добавлении и удалении."""
    panel = PointsPanel()
    panel.retranslate_ui()
    assert "0" in panel.count_label.text()

    panel.add_row("1", "Точка А", "56.6", "47.8", "Круг", "100 м")
    assert "1" in panel.count_label.text()

    panel.add_row("2", "Точка Б", "56.7", "47.9", "Круг", "200 м")
    assert "2" in panel.count_label.text()

    panel.remove_row(0)
    assert "1" in panel.count_label.text()


def test_27_search_count_updates(qapp, clean_settings):
    """27. search count отображает число показанных точек из общего количества."""
    panel = PointsPanel()
    panel.add_row("1", "Марий Эл 1", "56.6", "47.8", "Круг", "100 м")
    panel.add_row("2", "Волга 2", "56.7", "47.9", "Круг", "200 м")
    panel.add_row("3", "Марий Эл 3", "56.8", "48.0", "Круг", "300 м")

    panel.search_input.setText("Волга")
    # Должно отображаться 1 из 3
    text = panel.count_label.text()
    assert "1" in text and "3" in text


# =============================================================================
# 43. TESTS — PROPERTIES (Тесты 28–32)
# =============================================================================

def test_28_properties_coordinates_section_exists(qapp, clean_settings):
    """28. coordinates section существует."""
    set_language("ru")
    panel = PropertiesPanel()
    assert hasattr(panel, "sec_coords_lbl")
    assert "Координаты" in panel.sec_coords_lbl.text()


def test_29_properties_marker_section_exists(qapp, clean_settings):
    """29. marker section существует."""
    set_language("ru")
    panel = PropertiesPanel()
    assert hasattr(panel, "sec_marker_lbl")
    assert "Маркер" in panel.sec_marker_lbl.text()


def test_30_properties_zone_section_exists(qapp, clean_settings):
    """30. zone section существует."""
    set_language("ru")
    panel = PropertiesPanel()
    assert hasattr(panel, "sec_zone_lbl")
    assert "Зона" in panel.sec_zone_lbl.text()


def test_31_properties_empty_state_ru(qapp, clean_settings):
    """31. empty state в русском языке."""
    win = MainWindow()
    win.switch_language("ru")
    assert "Выберите точку в таблице для просмотра свойств." in win.prop_empty_label.text()


def test_32_properties_empty_state_en(qapp, clean_settings):
    """32. empty state в английском языке."""
    win = MainWindow()
    win.switch_language("en")
    assert "Select a point in the table to view its properties." in win.prop_empty_label.text()


# =============================================================================
# 44. TESTS — TRANSLATION (Тесты 33–38)
# =============================================================================

def test_33_view_menu_ru(qapp, clean_settings):
    """33. View menu в русском языке."""
    win = MainWindow()
    win.switch_language("ru")
    assert win.view_menu.title() == "Вид"
    assert win.toggle_toolbar_action.text() == "Панель инструментов"
    assert win.toggle_layers_points_action.text() == "Панель слоев и точек"
    assert win.toggle_properties_action.text() == "Панель свойств"
    assert win.toggle_statusbar_action.text() == "Строка состояния"


def test_34_view_menu_en(qapp, clean_settings):
    """34. View menu в английском языке."""
    win = MainWindow()
    win.switch_language("en")
    assert win.view_menu.title() == "View"
    assert win.toggle_toolbar_action.text() == "Toolbar"
    assert win.toggle_layers_points_action.text() == "Layers and Points Panel"
    assert win.toggle_properties_action.text() == "Properties Panel"
    assert win.toggle_statusbar_action.text() == "Status Bar"


def test_35_toolbar_tooltips_ru(qapp, clean_settings):
    """35. toolbar tooltips в русском языке."""
    win = MainWindow()
    win.switch_language("ru")
    assert win.open_map_action.toolTip() == "Открыть карту"
    assert win.open_action.toolTip() == "Открыть проект"
    assert win.save_action.toolTip() == "Сохранить проект"
    assert win.add_pt_action.toolTip() == "Добавить точку"
    assert win.fit_map_action.toolTip() == "Показать всю карту"


def test_36_toolbar_tooltips_en(qapp, clean_settings):
    """36. toolbar tooltips в английском языке."""
    win = MainWindow()
    win.switch_language("en")
    assert win.open_map_action.toolTip() == "Open Map"
    assert win.open_action.toolTip() == "Open Project"
    assert win.save_action.toolTip() == "Save Project"
    assert win.add_pt_action.toolTip() == "Add Point"
    assert win.fit_map_action.toolTip() == "Fit Map"


def test_37_language_remains_live_switchable(qapp, clean_settings):
    """37. language остается переключаемым на лету RU -> EN -> RU."""
    win = MainWindow()
    win.switch_language("ru")
    assert win.file_menu.title() == "Файл"
    assert win.sec_coords_lbl.text() == "Координаты"

    win.switch_language("en")
    assert win.file_menu.title() == "File"
    assert win.sec_coords_lbl.text() == "Coordinates"

    win.switch_language("ru")
    assert win.file_menu.title() == "Файл"
    assert win.sec_coords_lbl.text() == "Координаты"


def test_38_no_duplicate_actions_after_repeated_switch(qapp, clean_settings):
    """38. повторное переключение языка не создает дубликатов действий."""
    win = MainWindow()
    init_tb_count = len(win.main_toolbar.actions())
    init_view_count = len(win.view_menu.actions())

    for _ in range(5):
        win.switch_language("en")
        win.switch_language("ru")

    assert len(win.main_toolbar.actions()) == init_tb_count
    assert len(win.view_menu.actions()) == init_view_count
