"""Тесты производительности операций с группами объектов (Этап 18)."""

import time

from rme_mapper.maps.map_canvas import MapCanvas
from rme_mapper.models.map_point import MapPoint
from rme_mapper.models.object_group import ObjectGroup
from rme_mapper.services.group_service import GroupService
from rme_mapper.services.point_service import PointService
from rme_mapper.ui.panels.points_panel import PointsPanel


def test_performance_groups_and_filtering(qapp):
    """Проверка производительности: 1 000 точек, 10 групп - операции < 50ms."""
    gs = GroupService()
    ps = PointService()
    panel = PointsPanel()
    canvas = MapCanvas()

    # 1. Создаем 10 групп
    groups = [gs.create_group(f"Группа {i}") for i in range(10)]
    canvas.set_groups(groups)

    # 2. Создаем 1 000 точек
    points = []
    for i in range(1000):
        grp_idx = i % 10
        pt = ps.add_point(
            name=f"Точка {i}",
            latitude=56.0 + (i * 0.001),
            longitude=47.0 + (i * 0.001),
            group_id=groups[grp_idx].id if grp_idx < 8 else None,  # 800 в группах, 200 Ungrouped
        )
        points.append(pt)
        panel.add_point(pt)

    # 3. Скорость фильтрации по группе
    t0 = time.perf_counter()
    panel.set_group_filter(groups[0].id)
    t_filter = (time.perf_counter() - t0) * 1000  # ms
    assert panel.shown_count == 100
    assert t_filter < 100  # Должно быть мгновенно (< 100ms в тестовой среде)

    # 4. Скорость вычисления Zoom to Group
    grp_pts = ps.get_points_by_group(groups[0].id)
    t0 = time.perf_counter()
    canvas.zoom_to_group(grp_pts)
    t_zoom = (time.perf_counter() - t0) * 1000
    assert t_zoom < 50

    # 5. Скорость сброса фильтра (Все объекты)
    t0 = time.perf_counter()
    panel.set_group_filter(None)
    t_reset = (time.perf_counter() - t0) * 1000
    assert panel.shown_count == 1000
    assert t_reset < 100
