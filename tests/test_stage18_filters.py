"""Тесты презентационной фильтрации (Group AND Category AND Search) в PointsPanel (Этап 18)."""

from rme_mapper.models.map_point import MapPoint
from rme_mapper.ui.panels.points_panel import PointsPanel


def test_combined_filters_in_points_panel(qapp):
    """Проверка одновременной работы фильтров группы, категории и поиска."""
    panel = PointsPanel()

    p1 = MapPoint(id="p1", name="Альфа", latitude=56.0, longitude=47.0, category="Склады", group_id="grp-1")
    p2 = MapPoint(id="p2", name="Бета", latitude=56.1, longitude=47.1, category="Офисы", group_id="grp-1")
    p3 = MapPoint(id="p3", name="Гамма", latitude=56.2, longitude=47.2, category="Склады", group_id="grp-2")
    p4 = MapPoint(id="p4", name="Дельта", latitude=56.3, longitude=47.3, category="Офисы", group_id=None)

    panel.add_point(p1)
    panel.add_point(p2)
    panel.add_point(p3)
    panel.add_point(p4)

    assert panel.total_count == 4
    assert panel.shown_count == 4
    assert "Всего: 4" in panel.count_label.text()

    # 1. Фильтр только по группе "grp-1"
    panel.set_group_filter("grp-1")
    assert panel.shown_count == 2
    assert "Показано 2 из 4" in panel.count_label.text()

    # 2. Фильтр: Группа "grp-1" AND Категория "Склады"
    panel.category_combo.setCurrentText("Склады")
    assert panel.shown_count == 1  # Только p1
    assert "Показано 1 из 4" in panel.count_label.text()

    # 3. Фильтр: Группа "grp-1" AND Категория "Склады" AND Поиск "Бета"
    panel.search_input.setText("Бета")
    assert panel.shown_count == 0  # Ничего не найдено
    assert "Показано 0 из 4" in panel.count_label.text()

    # 4. Поиск "Альфа"
    panel.search_input.setText("Альфа")
    assert panel.shown_count == 1
    assert "Показано 1 из 4" in panel.count_label.text()

    # 5. Сброс поиска и категории
    panel.search_input.clear()
    panel.category_combo.setCurrentIndex(0)  # "Все категории"
    assert panel.shown_count == 2

    # 6. Фильтр "Без группы" (__ungrouped__)
    panel.set_group_filter("__ungrouped__")
    assert panel.shown_count == 1  # Только p4 (group_id=None)
    assert "Показано 1 из 4" in panel.count_label.text()

    # 7. Сброс группы (Все объекты)
    panel.set_group_filter(None)
    assert panel.shown_count == 4
    assert "Всего: 4" in panel.count_label.text()


def test_all_seven_filter_combinations_and_counters(qapp):
    """Проверка всех 7 вариантов фильтрации (Point 9) и счетчика Shown X of Y."""
    panel = PointsPanel()

    p1 = MapPoint(id="p1", name="Север 1", latitude=56.0, longitude=47.0, category="Лес", group_id="g-north")
    p2 = MapPoint(id="p2", name="Север 2", latitude=56.1, longitude=47.1, category="Поле", group_id="g-north")
    p3 = MapPoint(id="p3", name="Юг 1", latitude=56.2, longitude=47.2, category="Лес", group_id="g-south")
    p4 = MapPoint(id="p4", name="Юг 2", latitude=56.3, longitude=47.3, category="Поле", group_id="g-south")
    p5 = MapPoint(id="p5", name="Центр", latitude=56.4, longitude=47.4, category="Вода", group_id=None)

    for p in (p1, p2, p3, p4, p5):
        panel.add_point(p)

    assert panel.total_count == 5
    assert panel.shown_count == 5
    assert "Всего: 5" in panel.count_label.text()

    # 1. Group only
    panel.set_group_filter("g-north")
    assert panel.shown_count == 2
    assert "Показано 2 из 5" in panel.count_label.text()
    panel.set_group_filter(None)

    # 2. Category only
    panel.category_combo.setCurrentText("Лес")
    assert panel.shown_count == 2  # p1, p3
    assert "Показано 2 из 5" in panel.count_label.text()
    panel.category_combo.setCurrentIndex(0)

    # 3. Search only
    panel.search_input.setText("Север")
    assert panel.shown_count == 2  # p1, p2
    assert "Показано 2 из 5" in panel.count_label.text()
    panel.search_input.clear()

    # 4. Group + Category
    panel.set_group_filter("g-north")
    panel.category_combo.setCurrentText("Лес")
    assert panel.shown_count == 1  # p1
    assert "Показано 1 из 5" in panel.count_label.text()
    panel.category_combo.setCurrentIndex(0)
    panel.set_group_filter(None)

    # 5. Group + Search
    panel.set_group_filter("g-south")
    panel.search_input.setText("Юг 1")
    assert panel.shown_count == 1  # p3
    assert "Показано 1 из 5" in panel.count_label.text()
    panel.search_input.clear()
    panel.set_group_filter(None)

    # 6. Category + Search
    panel.category_combo.setCurrentText("Поле")
    panel.search_input.setText("Юг")
    assert panel.shown_count == 1  # p4
    assert "Показано 1 из 5" in panel.count_label.text()
    panel.search_input.clear()
    panel.category_combo.setCurrentIndex(0)

    # 7. Group + Category + Search
    panel.set_group_filter("g-north")
    panel.category_combo.setCurrentText("Лес")
    panel.search_input.setText("Север 1")
    assert panel.shown_count == 1  # p1
    assert "Показано 1 из 5" in panel.count_label.text()


def test_filtered_table_stable_point_ids(qapp):
    """Проверка, что при активных фильтрах выборка и операции используют point ID, а не индекс строки (Point 10)."""
    panel = PointsPanel()

    p1 = MapPoint(id="p-first", name="ААА", latitude=56.0, longitude=47.0, group_id="g1")
    p2 = MapPoint(id="p-second", name="БББ", latitude=56.1, longitude=47.1, group_id="g2")
    p3 = MapPoint(id="p-third", name="ВВВ", latitude=56.2, longitude=47.2, group_id="g1")

    panel.add_point(p1)
    panel.add_point(p2)
    panel.add_point(p3)

    # Фильтруем по группе "g2": строка 0 (p1) скрыта, видна только строка 1 (p2)
    panel.set_group_filter("g2")
    assert panel.shown_count == 1
    assert panel.points_table.isRowHidden(0) is True
    assert panel.points_table.isRowHidden(1) is False
    assert panel.points_table.isRowHidden(2) is True

    # Выделяем видимую строку
    panel.points_table.selectRow(1)
    # selected_point_ids возвращает стабильный ID 'p-second', а не 0 или индекс
    assert panel.selected_point_ids() == ["p-second"]

    # Программное выделение по ID: select_point_ids
    panel.select_point_ids(["p-third"])
    assert panel.selected_point_ids() == ["p-third"]


def test_select_group_objects_rule_a(qapp):
    """Проверка Правила А (Point 11): 'Выбрать объекты группы' выбирает все реальные точки группы.

    Даже если поисковый фильтр скрывает часть строк группы в таблице.
    """
    from rme_mapper.services.group_service import GroupService
    from rme_mapper.services.point_service import PointService
    from rme_mapper.ui.controllers.group_controller import GroupController
    from rme_mapper.services.undo_manager import UndoManager
    from rme_mapper.maps.map_canvas import MapCanvas

    gs = GroupService()
    ps = PointService()
    panel = PointsPanel()
    canvas = MapCanvas()
    undo_mgr = UndoManager()

    g = gs.create_group("Участок №1")
    p1 = ps.add_point(name="Береза 1", latitude=56.0, longitude=47.0, group_id=g.id)
    p2 = ps.add_point(name="Дуб 2", latitude=56.1, longitude=47.1, group_id=g.id)

    panel.add_point(p1)
    panel.add_point(p2)

    from rme_mapper.ui.panels.groups_panel import GroupsPanel
    g_panel = GroupsPanel()

    ctrl = GroupController(
        parent=panel,
        group_service=gs,
        point_service=ps,
        undo_manager=undo_mgr,
        groups_panel=g_panel,
        points_panel=panel,
        map_canvas=canvas,
        point_controller=None,
    )

    # Фильтр поиска скрывает p2 ("Дуб")
    panel.search_input.setText("Береза")
    assert panel.shown_count == 1

    # Вызываем выборку всех объектов группы
    ctrl.select_group_points_workflow(g.id)

    # Правило А: выбраны ОБЕ реальные точки группы p1 и p2!
    selected = panel.selected_point_ids()
    assert set(selected) == {p1.id, p2.id}

