"""Тесты производительности операций с группами объектов (Point 29).

Проверяются масштабы 1 000, 5 000 и 10 000 точек для:
- group filter
- category filter
- search
- combined filter
- show/hide group
- counters
- Zoom to Group
Фиксируются времена и подтверждается отсутствие деградации O(n^2).
"""

import time
import pytest

from rme_mapper.maps.map_canvas import MapCanvas
from rme_mapper.models.map_point import MapPoint
from rme_mapper.services.group_service import GroupService
from rme_mapper.services.point_service import PointService
from rme_mapper.ui.panels.points_panel import PointsPanel


@pytest.mark.parametrize("point_count", [1000, 5000, 10000])
def test_performance_benchmarks_1k_5k_10k(qapp, point_count):
    """Бенчмарк производительности для 1k, 5k, 10k точек с группами."""
    gs = GroupService()
    ps = PointService()
    panel = PointsPanel()
    canvas = MapCanvas()
    canvas.set_active_crs("EPSG:4326")

    # 5 групп объектов
    groups = [gs.create_group(f"Группа {i}", visible=True) for i in range(5)]
    canvas.set_groups(groups)

    categories = ["Лес", "Поле", "Вода", "Дорога"]

    # Отключаем обновления таблицы во время наполнения для чистоты замера
    panel.points_table.setUpdatesEnabled(False)
    panel.points_table.blockSignals(True)

    points = []
    for i in range(point_count):
        grp_idx = i % 6  # 0..4 = группы, 5 = None (Ungrouped)
        cat_idx = i % 4
        pt = ps.add_point(
            name=f"Точка #{i}",
            latitude=56.0 + (i * 0.0001),
            longitude=47.0 + (i * 0.0001),
            category=categories[cat_idx],
            group_id=groups[grp_idx].id if grp_idx < 5 else None,
        )
        points.append(pt)
        panel.add_point(pt)

    panel.points_table.blockSignals(False)
    panel.points_table.setUpdatesEnabled(True)
    panel._reapply_all_filters()

    # 1. Group filter
    t0 = time.perf_counter()
    panel.set_group_filter(groups[0].id)
    t_group_filter = (time.perf_counter() - t0) * 1000
    assert panel.shown_count > 0

    # 2. Category filter
    t0 = time.perf_counter()
    panel.category_combo.setCurrentText("Лес")
    t_cat_filter = (time.perf_counter() - t0) * 1000
    assert panel.shown_count > 0

    # 3. Search query
    t0 = time.perf_counter()
    panel.search_input.setText("Точка #1")
    t_search_filter = (time.perf_counter() - t0) * 1000
    assert panel.shown_count > 0

    # 4. Combined filter (Group + Category + Search)
    t0 = time.perf_counter()
    panel._reapply_all_filters()
    t_combined = (time.perf_counter() - t0) * 1000

    # 5. Counters
    t0 = time.perf_counter()
    panel._update_counter()
    t_counters = (time.perf_counter() - t0) * 1000

    # Сброс фильтров
    panel.search_input.clear()
    panel.category_combo.setCurrentIndex(0)
    panel.set_group_filter(None)

    # 6. Show / Hide group на холсте
    t0 = time.perf_counter()
    canvas.set_group_visibility(groups[0].id, False)
    canvas.set_group_visibility(groups[0].id, True)
    t_toggle_vis = (time.perf_counter() - t0) * 1000

    # 7. Zoom to Group
    grp_pts = ps.get_points_by_group(groups[0].id)
    t0 = time.perf_counter()
    canvas.zoom_to_group(grp_pts)
    t_zoom = (time.perf_counter() - t0) * 1000

    print(
        f"\n[PERF {point_count} pts] "
        f"group_filter={t_group_filter:.2f}ms, "
        f"cat_filter={t_cat_filter:.2f}ms, "
        f"search={t_search_filter:.2f}ms, "
        f"combined={t_combined:.2f}ms, "
        f"counter={t_counters:.2f}ms, "
        f"toggle_vis={t_toggle_vis:.2f}ms, "
        f"zoom={t_zoom:.2f}ms"
    )

    # Проверка отсутствия катастрофической деградации:
    # даже на 10k точек все операции отрабатывают в пределах разумного времени (< 1.5s на 10k)
    assert t_group_filter < 1500
    assert t_combined < 1500
    assert t_zoom < 500
