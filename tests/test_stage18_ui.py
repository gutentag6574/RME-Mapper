"""Тесты пользовательского интерфейса групп (GroupsPanel, PointDialog, PropertiesPanel) (Этап 18)."""

from PySide6.QtCore import Qt

from rme_mapper.i18n import set_language, tr
from rme_mapper.models.map_point import MapPoint
from rme_mapper.models.object_group import ObjectGroup
from rme_mapper.services.group_service import GroupService
from rme_mapper.ui.panels.groups_panel import (
    ITEM_ROLE_GROUP_ID,
    ITEM_ROLE_IS_SYSTEM,
    GroupsPanel,
)
from rme_mapper.ui.panels.properties_panel import PropertiesPanel
from rme_mapper.ui.point_dialog import PointDialog


def test_groups_panel_tree_structure(qapp):
    """Проверка структуры дерева GroupsPanel (Все объекты, Без группы, пользовательские группы)."""
    panel = GroupsPanel()

    g1 = ObjectGroup(id="g1", name="Север", visible=True)
    g2 = ObjectGroup(id="g2", name="Юг", visible=False)

    counts = {
        "g1": 5,
        "g2": 2,
        None: 3,
    }
    total_pts = 10

    panel.set_groups_and_counts([g1, g2], counts, total_pts)

    tree = panel.groups_tree
    assert tree.topLevelItemCount() == 4

    # 1. Все объекты
    it_all = tree.topLevelItem(0)
    assert it_all.data(0, ITEM_ROLE_GROUP_ID) is None
    assert bool(it_all.data(0, ITEM_ROLE_IS_SYSTEM)) is True
    assert "Все объекты" in it_all.text(0)
    assert "(10)" in it_all.text(0)

    # 2. Без группы
    it_ungrouped = tree.topLevelItem(1)
    assert it_ungrouped.data(0, ITEM_ROLE_GROUP_ID) == "__ungrouped__"
    assert bool(it_ungrouped.data(0, ITEM_ROLE_IS_SYSTEM)) is True
    assert "Без группы" in it_ungrouped.text(0)
    assert "(3)" in it_ungrouped.text(0)

    # 3. Пользовательские группы
    it_g1 = tree.topLevelItem(2)
    assert it_g1.data(0, ITEM_ROLE_GROUP_ID) == "g1"
    assert "Север" in it_g1.text(0)
    assert "(5)" in it_g1.text(0)
    assert it_g1.checkState(0) == Qt.CheckState.Checked

    it_g2 = tree.topLevelItem(3)
    assert it_g2.data(0, ITEM_ROLE_GROUP_ID) == "g2"
    assert "Юг" in it_g2.text(0)
    assert "(2)" in it_g2.text(0)
    assert it_g2.checkState(0) == Qt.CheckState.Unchecked


def test_properties_panel_group_resolver(qapp):
    """Проверка отображения названия группы в PropertiesPanel."""
    panel = PropertiesPanel()
    gs = GroupService()
    g1 = gs.create_group("Разведка")

    panel.set_group_name_resolver(
        lambda gid: gs.get_group(gid).name if gid and gs.get_group(gid) else "Без группы"
    )

    p1 = MapPoint(name="Точка А", latitude=56.0, longitude=47.0, group_id=g1.id)
    panel.update_properties(p1)
    assert panel.prop_group_val.text() == "Разведка"

    p2 = MapPoint(name="Точка Б", latitude=56.0, longitude=47.0, group_id=None)
    panel.update_properties(p2)
    assert panel.prop_group_val.text() == "Без группы"


def test_point_dialog_group_combo(qapp):
    """Проверка наличия и заполнения выпадающего списка групп в PointDialog."""
    gs = GroupService()
    g1 = gs.create_group("Группа 1")
    g2 = gs.create_group("Группа 2")

    groups = gs.list_groups()

    dlg = PointDialog(groups=groups)
    assert hasattr(dlg, "group_combo")
    assert dlg.group_combo.count() == 3  # Без группы + Группа 1 + Группа 2
    assert dlg.group_combo.itemData(0) is None
    assert dlg.group_combo.itemData(1) == g1.id
    assert dlg.group_combo.itemData(2) == g2.id

    # Проверка предустановки существующего group_id
    dlg_edit = PointDialog(groups=groups, group_id=g2.id)
    assert dlg_edit.group_id_result == g2.id


def test_point_dialog_no_automatic_group_creation(qapp):
    """Проверка, что диалог точки не создает новые группы автоматически (Point 15)."""
    gs = GroupService()
    g1 = gs.create_group("Существующая")
    groups_before = len(gs)

    # Открываем диалог для точки без группы
    pt = MapPoint(name="Новая", latitude=56.0, longitude=47.0)
    dlg = PointDialog(groups=gs.list_groups(), point=pt, mode="EDIT")

    # Переключаем комбобокс на "Существующая"
    dlg.group_combo.setCurrentIndex(1)
    assert dlg.group_id_result == g1.id

    # Переключаем обратно на "Без группы"
    dlg.group_combo.setCurrentIndex(0)
    assert dlg.group_id_result is None

    # Количество групп в GroupService не изменилось
    assert len(gs) == groups_before


def test_properties_panel_group_label_never_shows_uuid(qapp):
    """Проверка, что PropertiesPanel показывает человекочитаемое имя или 'Без группы', никогда не UUID (Point 16)."""
    panel = PropertiesPanel()
    gs = GroupService()
    g = gs.create_group("Лесной сектор")

    # С резолвером
    panel.set_group_name_resolver(
        lambda gid: gs.get_group(gid).name if gid and gs.get_group(gid) else "Без группы"
    )

    pt = MapPoint(name="П1", latitude=56.0, longitude=47.0, group_id=g.id)
    panel.update_properties(pt)
    assert panel.prop_group_val.text() == "Лесной сектор"
    assert g.id not in panel.prop_group_val.text()

    # Для точки без группы
    pt_no_grp = MapPoint(name="П2", latitude=56.0, longitude=47.0, group_id=None)
    panel.update_properties(pt_no_grp)
    assert panel.prop_group_val.text() == "Без группы"
    assert "uuid" not in panel.prop_group_val.text().lower()

