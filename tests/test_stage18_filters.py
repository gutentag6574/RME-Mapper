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
