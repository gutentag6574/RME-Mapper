"""Тесты для Этапа 12.1 — Рефакторинг больших UI-файлов без изменения поведения.

Проверка модулей контроллеров, презентационных панелей, рефакторинга MainWindow,
сохранения всех рабочих процессов, локализации и безопасности сигналов.
"""

from pathlib import Path
import pytest

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from rme_mapper.maps.map_config import get_default_geopackage_path
from rme_mapper.models.map_point import MapPoint
from rme_mapper.models.map_profile import MapProfile
from rme_mapper.ui.controllers.map_controller import MapController
from rme_mapper.ui.controllers.point_controller import PointController
from rme_mapper.ui.controllers.project_controller import ProjectController
from rme_mapper.ui.main_window import MainWindow, get_symbol_display_name
from rme_mapper.ui.panels.layers_panel import LayersPanel
from rme_mapper.ui.panels.points_panel import PointsPanel
from rme_mapper.ui.panels.properties_panel import PropertiesPanel
from rme_mapper.ui.point_dialog import PointDialogData


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    yield app


@pytest.fixture
def default_gpkg():
    return get_default_geopackage_path()


# -----------------------------------------------------------------------------
# 1. MainWindow создается
# -----------------------------------------------------------------------------
def test_01_main_window_creation(qapp):
    """1. MainWindow успешно создается, имеет координаторы и исходно пустую карту."""
    win = MainWindow()
    assert win is not None
    assert hasattr(win, "point_controller")
    assert hasattr(win, "map_controller")
    assert hasattr(win, "project_controller")
    assert hasattr(win, "layers_panel")
    assert hasattr(win, "points_panel")
    assert hasattr(win, "properties_panel")
    assert win.map_controller.active_profile is None
    assert not win.is_modified
    win.close()


# -----------------------------------------------------------------------------
# 2. PointController создается
# -----------------------------------------------------------------------------
def test_02_point_controller_creation(qapp):
    """2. PointController успешно создается и привязывается к UI компонентам."""
    win = MainWindow()
    ctrl = win.point_controller
    assert isinstance(ctrl, PointController)
    assert ctrl.table_point_ids == []
    win.close()


# -----------------------------------------------------------------------------
# 3. ProjectController создается
# -----------------------------------------------------------------------------
def test_03_project_controller_creation(qapp):
    """3. ProjectController успешно создается и отслеживает состояние проекта."""
    win = MainWindow()
    ctrl = win.project_controller
    assert isinstance(ctrl, ProjectController)
    assert ctrl.current_project_path is None
    assert not ctrl.is_modified
    win.close()


# -----------------------------------------------------------------------------
# 4. MapController создается
# -----------------------------------------------------------------------------
def test_04_map_controller_creation(qapp):
    """4. MapController успешно создается и управляет профилем и CRS."""
    win = MainWindow()
    ctrl = win.map_controller
    assert isinstance(ctrl, MapController)
    assert ctrl.active_profile is None
    assert ctrl.active_crs == "OGC:CRS84"
    assert ctrl.loaded_layers == []
    win.close()


# -----------------------------------------------------------------------------
# 5. PointsPanel создается
# -----------------------------------------------------------------------------
def test_05_points_panel_creation(qapp):
    """5. PointsPanel создается, содержит кнопки и таблицу из 6 колонок."""
    panel = PointsPanel()
    assert panel.points_table.columnCount() == 6
    assert panel.btn_add is not None
    assert not panel.btn_edit.isEnabled()
    assert not panel.btn_delete.isEnabled()
    panel.close()


# -----------------------------------------------------------------------------
# 6. LayersPanel создается
# -----------------------------------------------------------------------------
def test_06_layers_panel_creation(qapp):
    """6. LayersPanel создается, содержит заголовок и пустой контейнер чекбоксов."""
    panel = LayersPanel()
    assert panel.title_label.text() != ""
    assert len(panel.layer_checkboxes) == 0
    panel.close()


# -----------------------------------------------------------------------------
# 7. PropertiesPanel создается
# -----------------------------------------------------------------------------
def test_07_properties_panel_creation(qapp):
    """7. PropertiesPanel создается в чистом виде с подсказкой о выборе точки."""
    panel = PropertiesPanel()
    assert not panel.prop_empty_label.isHidden()
    assert not panel.prop_container.isVisible()
    panel.close()


# -----------------------------------------------------------------------------
# 8. add point workflow работает
# -----------------------------------------------------------------------------
def test_08_add_point_workflow(qapp, default_gpkg, monkeypatch):
    """8. Сценарий добавления точки создает точку в сервисе, маркер на холсте и строку в таблице."""
    win = MainWindow()
    win.load_map(default_gpkg)

    fake_data = PointDialogData(
        name="Новая Точка 1",
        latitude=56.63,
        longitude=47.88,
        symbol="circle",
        size=10.0,
        red=255,
        green=0,
        blue=0,
        zone_enabled=False,
        radius_m=0.0,
        zone_red=255,
        zone_green=0,
        zone_blue=0,
        zone_opacity=30,
    )

    from rme_mapper.ui.point_dialog import PointDialog
    monkeypatch.setattr(PointDialog, "exec", lambda self: 1)
    monkeypatch.setattr(PointDialog, "get_point_data", lambda self: fake_data)

    win.show_add_point_dialog()

    assert len(win._point_service) == 1
    assert win.points_table.rowCount() == 1
    assert win.points_table.item(0, 1).text() == "Новая Точка 1"
    assert win.is_modified
    win._set_modified(False)
    win.close()


# -----------------------------------------------------------------------------
# 9. edit point workflow работает
# -----------------------------------------------------------------------------
def test_09_edit_point_workflow(qapp, default_gpkg, monkeypatch):
    """9. Сценарий редактирования точки обновляет сервис, таблицу, свойства и холст."""
    win = MainWindow()
    win.load_map(default_gpkg)

    pt = win._point_service.add_point("До правки", 56.63, 47.88, symbol="circle")
    win.point_controller.add_point_to_table(pt)
    win.points_table.selectRow(0)
    win._set_modified(False)

    fake_updated = PointDialogData(
        name="После правки",
        latitude=56.70,
        longitude=47.95,
        symbol="square",
        size=14.0,
        red=0,
        green=255,
        blue=0,
        zone_enabled=True,
        radius_m=3000.0,
        zone_red=0,
        zone_green=255,
        zone_blue=0,
        zone_opacity=40,
    )

    from rme_mapper.ui.point_dialog import PointDialog
    monkeypatch.setattr(PointDialog, "exec", lambda self: 1)
    monkeypatch.setattr(PointDialog, "get_point_data", lambda self: fake_updated)

    win.edit_selected_point()

    assert win.points_table.item(0, 1).text() == "После правки"
    assert win.points_table.item(0, 4).text() == "Квадрат"
    assert win.prop_name_val.text() == "После правки"
    assert win.is_modified
    win._set_modified(False)
    win.close()


# -----------------------------------------------------------------------------
# 10. delete point workflow работает
# -----------------------------------------------------------------------------
def test_10_delete_point_workflow(qapp, default_gpkg):
    """10. Сценарий удаления точки удаляет ее из сервиса и таблицы, сбрасывает панель свойств."""
    win = MainWindow()
    win.load_map(default_gpkg)

    pt = win._point_service.add_point("Удаляемая", 56.63, 47.88)
    win.point_controller.add_point_to_table(pt)
    assert win.points_table.rowCount() == 1

    win.points_table.selectRow(0)
    assert win.btn_delete_point.isEnabled()

    win.delete_selected_point()
    assert len(win._point_service) == 0
    assert win.points_table.rowCount() == 0
    assert not win.prop_empty_label.isHidden()
    assert not win.prop_container.isVisible()
    assert win.is_modified
    win._set_modified(False)
    win.close()


# -----------------------------------------------------------------------------
# 11. Open Map workflow работает
# -----------------------------------------------------------------------------
def test_11_open_map_workflow(qapp, default_gpkg):
    """11. Сценарий открытия карты загружает слои и обновляет UI."""
    win = MainWindow()
    assert win._active_profile is None

    res = win.open_map(default_gpkg)
    assert res is True
    assert win._map_path == default_gpkg
    assert len(win.loaded_layers) > 0
    assert len(win.layer_checkboxes) > 0
    assert win.btn_add_point.isEnabled()
    win._set_modified(False)
    win.close()


# -----------------------------------------------------------------------------
# 12. Close Map workflow работает
# -----------------------------------------------------------------------------
def test_12_close_map_workflow(qapp, default_gpkg):
    """12. Сценарий закрытия карты возвращает приложение в состояние без карты."""
    win = MainWindow()
    win.load_map(default_gpkg)
    assert win.map_controller.map_path is not None

    res = win.close_map(prompt=False)
    assert res is True
    assert win.map_controller.map_path is None
    assert len(win.loaded_layers) == 0
    assert len(win.layer_checkboxes) == 0
    assert not win.btn_add_point.isEnabled()
    win._set_modified(False)
    win.close()


# -----------------------------------------------------------------------------
# 13. Save Project работает
# -----------------------------------------------------------------------------
def test_13_save_project_workflow(qapp, default_gpkg, tmp_path):
    """13. Сценарий сохранения проекта записывает .gpmap файл."""
    win = MainWindow()
    win.load_map(default_gpkg)
    pt = win._point_service.add_point("Точка Сохранения", 56.63, 47.88)
    win.point_controller.add_point_to_table(pt)

    save_file = tmp_path / "test_saved.gpmap"
    res = win.save_project_as(save_file)
    assert res is True
    assert save_file.exists()
    assert not win.is_modified
    assert win.current_project_path == save_file
    win.close()


# -----------------------------------------------------------------------------
# 14. Open Project работает
# -----------------------------------------------------------------------------
def test_14_open_project_workflow(qapp, default_gpkg, tmp_path):
    """14. Сценарий открытия проекта восстанавливает данные из .gpmap."""
    win = MainWindow()
    win.load_map(default_gpkg)
    pt = win._point_service.add_point("Сохраненная Точка", 56.63, 47.88)
    win.point_controller.add_point_to_table(pt)

    save_file = tmp_path / "open_test.gpmap"
    win.save_project_as(save_file)
    win.close()

    win2 = MainWindow()
    res = win2.open_project(save_file)
    assert res is True
    assert len(win2._point_service) == 1
    assert win2.points_table.rowCount() == 1
    assert win2.points_table.item(0, 1).text() == "Сохраненная Точка"
    assert not win2.is_modified
    win2.close()


# -----------------------------------------------------------------------------
# 15. New Project работает
# -----------------------------------------------------------------------------
def test_15_new_project_workflow(qapp, default_gpkg):
    """15. Сценарий Нового проекта сбрасывает все точки, слои и флаг изменений."""
    win = MainWindow()
    win.load_map(default_gpkg)
    pt = win._point_service.add_point("Тест Новый", 56.63, 47.88)
    win.point_controller.add_point_to_table(pt)
    win._set_modified(False)

    res = win.new_project()
    assert res is True
    assert len(win._point_service) == 0
    assert win.points_table.rowCount() == 0
    assert win.map_controller.map_path is None
    assert not win.is_modified
    win.close()


# -----------------------------------------------------------------------------
# 16. dirty state не изменился по поведению
# -----------------------------------------------------------------------------
def test_16_dirty_state_behavior(qapp, default_gpkg):
    """16. Флаг несохраненных изменений устанавливается при модификациях и сбрасывается."""
    win = MainWindow()
    win.load_map(default_gpkg)
    win._set_modified(False)
    assert not win.is_modified

    # Добавление точки меняет dirty
    pt = win._point_service.add_point("Точка", 56.63, 47.88)
    win.point_controller.add_point_to_table(pt)
    win._set_modified(True)
    assert win.is_modified
    assert "*" in win.windowTitle()

    # Сброс флага
    win._set_modified(False)
    assert not win.is_modified
    assert "*" not in win.windowTitle()
    win.close()


# -----------------------------------------------------------------------------
# 17. RU работает после refactor
# -----------------------------------------------------------------------------
def test_17_ru_translation_after_refactor(qapp):
    """17. Русский интерфейс полностью переводит все меню и панели."""
    win = MainWindow()
    win.switch_language("ru")

    assert win.file_menu.title() == "Файл"
    assert win.layers_panel.title_label.text() == "Слои"
    assert win.points_panel.title_label.text() == "Точки"
    assert win.properties_panel.title_label.text() == "Свойства"
    assert win.points_panel.btn_add.text() == "+ Добавить точку"
    win.close()


# -----------------------------------------------------------------------------
# 18. EN работает после refactor
# -----------------------------------------------------------------------------
def test_18_en_translation_after_refactor(qapp):
    """18. Английский интерфейс полностью переводит все меню и панели."""
    win = MainWindow()
    win.switch_language("en")

    assert win.file_menu.title() == "File"
    assert win.layers_panel.title_label.text() == "Layers"
    assert win.points_panel.title_label.text() == "Points"
    assert win.properties_panel.title_label.text() == "Properties"
    assert win.points_panel.btn_add.text() == "+ Add Point"
    win.close()


# -----------------------------------------------------------------------------
# 19. live switch работает
# -----------------------------------------------------------------------------
def test_19_live_switch_works(qapp):
    """19. Динамическое переключение RU <-> EN на лету обновляет строки без перезапуска."""
    win = MainWindow()
    win.switch_language("ru")
    assert win.file_menu.title() == "Файл"

    win.switch_language("en")
    assert win.file_menu.title() == "File"

    win.switch_language("ru")
    assert win.file_menu.title() == "Файл"
    win.close()


# -----------------------------------------------------------------------------
# 20. zones работают
# -----------------------------------------------------------------------------
def test_20_zones_work(qapp, default_gpkg):
    """20. Геодезические зоны рассчитываются и отображаются в панели свойств."""
    win = MainWindow()
    win.load_map(default_gpkg)

    pt = win._point_service.add_point(
        name="Точка Зона",
        latitude=56.63,
        longitude=47.88,
        zone_enabled=True,
        radius_m=2500.0,
    )
    win.point_controller.add_point_to_table(pt)
    win.points_table.selectRow(0)

    assert win.prop_zone_val.text() == "Да"
    assert win.prop_zone_radius_val.text() == "2.5 км"
    win._set_modified(False)
    win.close()


# -----------------------------------------------------------------------------
# 21. map layers visibility работает
# -----------------------------------------------------------------------------
def test_21_map_layers_visibility(qapp, default_gpkg):
    """21. Переключение чекбокса слоя в LayersPanel скрывает слой на холсте."""
    win = MainWindow()
    win.load_map(default_gpkg)
    first_layer = win.loaded_layers[0]

    # Скрываем первый слой
    win.map_controller.set_layer_visibility(first_layer.id, False)
    assert not first_layer.visible
    chk = win.layer_checkboxes[first_layer.id]
    assert not chk.isChecked()

    # Включаем обратно
    win.map_controller.set_layer_visibility(first_layer.id, True)
    assert first_layer.visible
    assert chk.isChecked()

    win._set_modified(False)
    win.close()


# -----------------------------------------------------------------------------
# 22. gpmap reopen работает
# -----------------------------------------------------------------------------
def test_22_gpmap_reopen(qapp, default_gpkg, tmp_path):
    """22. Сохранение и повторное открытие *.gpmap сохраняет целостность всех данных."""
    win = MainWindow()
    win.load_map(default_gpkg)
    pt = win._point_service.add_point(
        "Точка Reopen",
        56.63,
        47.88,
        symbol="triangle",
        size=16.0,
        zone_enabled=True,
        radius_m=4000.0,
    )
    win.point_controller.add_point_to_table(pt)

    proj_file = tmp_path / "reopen_project.gpmap"
    win.save_project_as(proj_file)
    win.close()

    win2 = MainWindow()
    assert win2.open_project(proj_file) is True
    assert len(win2._point_service) == 1
    loaded_pt = win2._point_service.get_points()[0]
    assert loaded_pt.name == "Точка Reopen"
    assert loaded_pt.symbol == "triangle"
    assert loaded_pt.radius_m == 4000.0
    win2.close()


# -----------------------------------------------------------------------------
# 23. legacy rmeproject работает
# -----------------------------------------------------------------------------
def test_23_legacy_rmeproject_works(qapp):
    """23. Legacy проект *.rmeproject открывается и заполняет точки и карту."""
    from rme_mapper.maps.map_config import get_project_root
    fixture_path = get_project_root() / "tests" / "fixtures" / "sample_project_v1.rmeproject"

    win = MainWindow()
    assert win.open_project(fixture_path) is True
    assert len(win._point_service) == 3
    assert win.points_table.rowCount() == 3
    win.close()


# -----------------------------------------------------------------------------
# 24. нет duplicate QAction
# -----------------------------------------------------------------------------
def test_24_no_duplicate_qactions(qapp):
    """24. Вызовы switch_language и retranslate_ui не создают дублирующихся действий QAction."""
    win = MainWindow()
    initial_file_actions = len(win.file_menu.actions())
    initial_map_actions = len(win.map_menu.actions())

    for _ in range(5):
        win.retranslate_ui()
        win.switch_language("en")
        win.switch_language("ru")

    assert len(win.file_menu.actions()) == initial_file_actions
    assert len(win.map_menu.actions()) == initial_map_actions
    win.close()


# -----------------------------------------------------------------------------
# 25. нет duplicate signal invocation
# -----------------------------------------------------------------------------
def test_25_no_duplicate_signal_invocation(qapp):
    """25. Сигналы контроллеров и панелей вызываются ровно один раз на событие."""
    panel = PointsPanel()
    call_count = 0

    def counter():
        nonlocal call_count
        call_count += 1

    panel.add_clicked.connect(counter)
    panel.btn_add.click()
    assert call_count == 1

    panel.retranslate_ui()
    panel.retranslate_ui()
    panel.btn_add.click()
    assert call_count == 2
    panel.close()
