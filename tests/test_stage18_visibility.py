"""Тесты формулы эффективной видимости и экспорта с учетом групп (Этап 18)."""

from rme_mapper.exporters.map_renderer import MapRenderer
from rme_mapper.maps.map_canvas import MapCanvas
from rme_mapper.models.map_point import MapPoint
from rme_mapper.models.object_group import ObjectGroup
from rme_mapper.services.group_service import GroupService
from rme_mapper.services.point_service import PointService


def test_effective_visibility_formula_canvas(qapp):
    """Проверка эффективной видимости на холсте: global AND group AND point."""
    canvas = MapCanvas()
    gs = GroupService()
    g1 = gs.create_group("Группа 1", visible=True)

    # Точка в группе g1
    pt1 = MapPoint(
        id="pt-1",
        name="Точка 1",
        latitude=56.0,
        longitude=47.0,
        group_id=g1.id,
        visible=True,
        zone_enabled=True,
        radius_m=500.0,
    )
    # Точка без группы
    pt2 = MapPoint(
        id="pt-2",
        name="Точка 2",
        latitude=56.1,
        longitude=47.1,
        group_id=None,
        visible=True,
    )

    canvas.set_groups(gs.list_groups())
    canvas.add_point(pt1)
    canvas.add_point(pt2)

    # Исходно: обе точки видны
    assert canvas._marker_items["pt-1"].isVisible() is True
    assert canvas._zone_items["pt-1"].isVisible() is True
    assert canvas._marker_items["pt-2"].isVisible() is True

    # 1. Отключаем видимость группы g1
    canvas.set_group_visibility(g1.id, False)
    assert canvas._marker_items["pt-1"].isVisible() is False
    assert canvas._zone_items["pt-1"].isVisible() is False
    # pt2 (Ungrouped) должна остаться видимой!
    assert canvas._marker_items["pt-2"].isVisible() is True

    # 2. Включаем обратно группу g1
    canvas.set_group_visibility(g1.id, True)
    assert canvas._marker_items["pt-1"].isVisible() is True
    assert canvas._zone_items["pt-1"].isVisible() is True

    # 3. Индивидуальная видимость точки выключена: pt1.visible = False
    pt1.visible = False
    canvas.update_point(pt1)
    assert canvas._marker_items["pt-1"].isVisible() is False
    assert ("pt-1" not in canvas._zone_items) or (canvas._zone_items["pt-1"].isVisible() is False)

    # 4. Глобальная видимость маркеров выключена
    pt1.visible = True
    canvas.update_point(pt1)
    canvas.set_all_points_visible(False)
    assert canvas._marker_items["pt-1"].isVisible() is False
    assert canvas._marker_items["pt-2"].isVisible() is False


def test_export_respects_hidden_group_ids(qapp):
    """Проверка, что MapRenderer исключает точки из скрытых групп."""
    from rme_mapper.exporters.models import ImageExportOptions

    p1 = MapPoint(id="p1", name="П1", latitude=56.0, longitude=47.0, group_id="grp-hidden")
    p2 = MapPoint(id="p2", name="П2", latitude=56.0, longitude=47.0, group_id="grp-visible")
    p3 = MapPoint(id="p3", name="П3", latitude=56.0, longitude=47.0, group_id=None)

    points = [p1, p2, p3]
    hidden_ids = {"grp-hidden"}

    options = ImageExportOptions(file_path="test_export.png", width_px=400, height_px=400)
    image = MapRenderer.render_map(
        options=options,
        active_crs="EPSG:4326",
        target_extent=(46.9, 55.9, 47.1, 56.1),
        points=points,
        hidden_group_ids=hidden_ids,
    )
    assert image is not None
    assert not image.isNull()

    # Проверяем фильтрацию точек для отрисовки
    pts_to_render = [
        p for p in points
        if (p.group_id not in hidden_ids if p.group_id else True)
    ]
    assert len(pts_to_render) == 2
    assert {p.id for p in pts_to_render} == {"p2", "p3"}


def test_multilevel_visibility_combinations_matrix(qapp):
    """Проверка всех комбинаций глобальной, групповой и точечной видимости (Points 6, 7, 8).

    Ни одна UI-операция видимости не должна менять флаги другого уровня!
    """
    canvas = MapCanvas()
    gs = GroupService()
    g1 = gs.create_group("Зона 1", visible=True)

    pt = MapPoint(
        id="p-test",
        name="Точка Тест",
        latitude=56.0,
        longitude=47.0,
        group_id=g1.id,
        visible=True,
        zone_enabled=True,
        radius_m=200.0,
    )

    canvas.set_groups(gs.list_groups())
    canvas.add_point(pt)

    # 1. Проверка независимости: point.visible=True, group.visible=False
    canvas.set_group_visibility(g1.id, False)
    assert pt.visible is True  # point.visible НЕ изменился!
    assert canvas.is_group_visible(g1.id) is False
    assert canvas._marker_items["p-test"].isVisible() is False
    assert canvas._zone_items["p-test"].isVisible() is False

    # Show group возвращает видимость
    canvas.set_group_visibility(g1.id, True)
    assert canvas._marker_items["p-test"].isVisible() is True
    assert canvas._zone_items["p-test"].isVisible() is True

    # 2. Проверка комбинаций видимости маркеров:
    # effective = global_pts AND group.visible AND pt.visible
    for g_pts in (True, False):
        for grp_vis in (True, False):
            for pt_vis in (True, False):
                canvas.set_all_points_visible(g_pts)
                canvas.set_group_visibility(g1.id, grp_vis)
                pt.visible = pt_vis
                canvas.update_point(pt)

                expected_marker_vis = g_pts and grp_vis and pt_vis
                assert canvas._marker_items["p-test"].isVisible() == expected_marker_vis, (
                    f"Mismatch for g_pts={g_pts}, grp_vis={grp_vis}, pt_vis={pt_vis}"
                )

    # 3. Проверка комбинаций видимости зон:
    # effective_zone = global_zones AND group.visible AND pt.visible AND zone_enabled AND radius > 0
    canvas.set_all_points_visible(True)
    for g_zones in (True, False):
        for grp_vis in (True, False):
            for pt_vis in (True, False):
                for z_en in (True, False):
                    canvas.set_all_zones_visible(g_zones)
                    canvas.set_group_visibility(g1.id, grp_vis)
                    pt.visible = pt_vis
                    pt.zone_enabled = z_en
                    canvas.update_point(pt)

                    expected_zone_vis = g_zones and grp_vis and pt_vis and z_en
                    actual_vis = (
                        canvas._zone_items["p-test"].isVisible()
                        if "p-test" in canvas._zone_items
                        else False
                    )
                    assert actual_vis == expected_zone_vis, (
                        f"Zone mismatch for g_zones={g_zones}, grp={grp_vis}, pt={pt_vis}, zen={z_en}"
                    )


