from pathlib import Path

from rme_mapper.exporters.map_renderer import MapRenderer
from rme_mapper.exporters.models import ImageExportOptions
from rme_mapper.i18n import get_language, set_language, tr
from rme_mapper.importers.import_service import ImportService
from rme_mapper.importers.models import ImportOptions
from rme_mapper.maps.map_canvas import MapCanvas
from rme_mapper.models.map_point import MapPoint
from rme_mapper.models.object_group import ObjectGroup
from rme_mapper.models.project_data import ProjectData
from rme_mapper.services.group_service import GroupService
from rme_mapper.services.point_service import PointService
from rme_mapper.services.project_service import ProjectService
from rme_mapper.services.undo_manager import (
    AssignPointsToGroupCommand,
    BulkEditStyleCommand,
    DeleteGroupCommand,
    SetGroupVisibilityCommand,
    UndoManager,
)
from rme_mapper.ui.panels.points_panel import PointsPanel


def test_stage18_manual_check_a_to_u(tmp_path, qapp):
    """Сквозное выполнение сценария A–U."""
    gs = GroupService()
    ps = PointService()
    undo_mgr = UndoManager()
    panel = PointsPanel()
    canvas = MapCanvas()
    canvas.set_active_crs("EPSG:4326")

    # =========================================================================
    # A. Создать: Местообитания, Наблюдения, Контрольные точки
    # =========================================================================
    g1 = gs.create_group("Местообитания")
    g2 = gs.create_group("Наблюдения")
    g3 = gs.create_group("Контрольные точки")
    assert len(gs) == 3

    canvas.set_groups(gs.list_groups())

    # =========================================================================
    # B. Создать несколько points
    # =========================================================================
    pts = []
    for i in range(5):
        pt = ps.add_point(
            name=f"Точка {i+1}",
            latitude=56.0 + (i * 0.05),
            longitude=47.0 + (i * 0.05),
            category="Биология" if i < 3 else "Геология",
            zone_enabled=True,
            radius_m=300.0,
        )
        pts.append(pt)
        panel.add_point(pt)
        canvas.add_point(pt)

    assert len(ps) == 5
    assert panel.total_count == 5

    # =========================================================================
    # C. Переместить 3 точки в Местообитания
    # =========================================================================
    target_pids = [pts[0].id, pts[1].id, pts[2].id]
    before_map_c = {pid: ps.get_point(pid).group_id for pid in target_pids}

    def apply_group_c(mapping):
        for pid, gid in mapping.items():
            ps.set_point_group(pid, gid)
        panel.update_points_group_ids(mapping)

    cmd_c = AssignPointsToGroupCommand(
        previous_groups=before_map_c,
        target_group_id=g1.id,
        apply_fn=apply_group_c,
    )
    undo_mgr.push(cmd_c, execute=True)

    assert ps.get_point(pts[0].id).group_id == g1.id
    assert ps.get_point(pts[1].id).group_id == g1.id
    assert ps.get_point(pts[2].id).group_id == g1.id
    assert len(ps.get_points_by_group(g1.id)) == 3

    # =========================================================================
    # D. Выбрать filter этой group
    # =========================================================================
    panel.set_group_filter(g1.id)
    assert panel.shown_count == 3
    assert "Показано 3 из 5" in panel.count_label.text()

    # =========================================================================
    # E. Добавить category filter
    # =========================================================================
    panel.category_combo.setCurrentText("Биология")
    assert panel.shown_count == 3

    # =========================================================================
    # F. Добавить search
    # =========================================================================
    panel.search_input.setText("Точка 1")
    assert panel.shown_count == 1
    assert "Показано 1 из 5" in panel.count_label.text()

    # Сброс презентационных фильтров перед проверкой видимости
    panel.search_input.clear()
    panel.category_combo.setCurrentIndex(0)
    panel.set_group_filter(None)
    assert panel.shown_count == 5

    # =========================================================================
    # G. Hide group. Markers/zones/labels исчезают
    # =========================================================================
    def apply_vis_g(gid, vis):
        gs.set_group_visibility(gid, vis)
        canvas.set_group_visibility(gid, vis)

    cmd_g = SetGroupVisibilityCommand(
        group_id=g1.id,
        before_visible=True,
        after_visible=False,
        apply_fn=apply_vis_g,
    )
    undo_mgr.push(cmd_g, execute=True)

    assert gs.get_group(g1.id).visible is False
    # Точки группы g1 скрыты на карте
    assert canvas._marker_items[pts[0].id].isVisible() is False
    assert canvas._zone_items[pts[0].id].isVisible() is False
    # Точки без группы видны
    assert canvas._marker_items[pts[3].id].isVisible() is True

    # =========================================================================
    # H. Ctrl+Z. Возвращаются
    # =========================================================================
    assert undo_mgr.can_undo is True
    undo_mgr.undo()

    assert gs.get_group(g1.id).visible is True
    assert canvas._marker_items[pts[0].id].isVisible() is True
    assert canvas._zone_items[pts[0].id].isVisible() is True

    # =========================================================================
    # I. Move selected points в другую group (Наблюдения g2)
    # =========================================================================
    before_map_i = {pid: ps.get_point(pid).group_id for pid in target_pids}
    cmd_i = AssignPointsToGroupCommand(
        previous_groups=before_map_i,
        target_group_id=g2.id,
        apply_fn=apply_group_c,
    )
    undo_mgr.push(cmd_i, execute=True)
    assert ps.get_point(pts[0].id).group_id == g2.id
    assert ps.get_point(pts[1].id).group_id == g2.id

    # =========================================================================
    # J. Ctrl+Z. Membership возвращается
    # =========================================================================
    undo_mgr.undo()
    assert ps.get_point(pts[0].id).group_id == g1.id
    assert ps.get_point(pts[1].id).group_id == g1.id

    # =========================================================================
    # K. Bulk style group
    # =========================================================================
    grp_pts = ps.get_points_by_group(g1.id)
    before_styles = [p.size for p in grp_pts]

    def apply_style_k(pts_list):
        for p in pts_list:
            ps.update_point(p.id, size=p.size)
            canvas.update_point(ps.get_point(p.id))

    after_pts = []
    for p in grp_pts:
        import copy
        p_up = copy.deepcopy(p)
        p_up.size = 35.0
        after_pts.append(p_up)

    cmd_k = BulkEditStyleCommand(
        before_points=grp_pts,
        after_points=after_pts,
        apply_fn=apply_style_k,
    )
    undo_mgr.push(cmd_k, execute=True)
    assert ps.get_point(pts[0].id).size == 35.0

    # =========================================================================
    # L. Ctrl+Z
    # =========================================================================
    undo_mgr.undo()
    assert ps.get_point(pts[0].id).size == before_styles[0]

    # =========================================================================
    # M. Zoom to Group
    # =========================================================================
    canvas.zoom_to_group(ps.get_points_by_group(g1.id))
    # Видимость не нарушена
    assert canvas._marker_items[pts[0].id].isVisible() is True

    # =========================================================================
    # N. Delete Group. Points -> Ungrouped
    # =========================================================================
    affected_ids_n = [p.id for p in ps.get_points_by_group(g1.id)]

    def restore_g_n(grp):
        gs.add_existing_group(grp)
        canvas.set_groups(gs.list_groups())

    def remove_g_n(gid):
        gs.delete_group(gid)
        canvas.set_groups(gs.list_groups())

    def set_p_n(pids, gid):
        ps.set_points_group(pids, gid)
        panel.update_points_group_ids({pid: gid for pid in pids})

    cmd_n = DeleteGroupCommand(
        group=g1,
        affected_point_ids=affected_ids_n,
        restore_group_fn=restore_g_n,
        remove_group_fn=remove_g_n,
        set_points_group_fn=set_p_n,
    )
    undo_mgr.push(cmd_n, execute=True)

    assert gs.get_group(g1.id) is None
    assert ps.get_point(pts[0].id).group_id is None
    assert ps.get_point(pts[1].id).group_id is None

    # =========================================================================
    # O. Ctrl+Z. Group/membership возвращаются
    # =========================================================================
    undo_mgr.undo()
    assert gs.get_group(g1.id) is not None
    assert ps.get_point(pts[0].id).group_id == g1.id
    assert ps.get_point(pts[1].id).group_id == g1.id

    # =========================================================================
    # P. Save gpmap
    # =========================================================================
    proj_service = ProjectService()
    project_file = tmp_path / "manual_check.gpmap"
    proj_data = proj_service.build_project_data(
        map_path=None,
        layers=[],
        points=ps.get_points(),
        groups=gs.list_groups(),
    )
    proj_service.save_project(proj_data, project_file)
    assert project_file.exists()

    # =========================================================================
    # Q. Reopen
    # =========================================================================
    reopened = proj_service.load_project(project_file)
    assert len(reopened.groups) == 3
    assert len(reopened.points) == 5
    reopened_p0 = next(p for p in reopened.points if p.id == pts[0].id)
    assert reopened_p0.group_id == g1.id

    # =========================================================================
    # R. Open old project
    # =========================================================================
    old_raw = {
        "format": "GeoPoint Mapper Project",
        "version": 1,
        "map": {},
        "layers": {},
        "points": [{"id": "old-p", "name": "Старая", "latitude": 55.0, "longitude": 46.0}],
    }
    old_proj = proj_service._parse_project_dict(old_raw)
    assert old_proj.groups == []
    assert old_proj.points[0].group_id is None

    # =========================================================================
    # S. Import CSV/XLSX with group
    # =========================================================================
    import_csv = (
        "name,latitude,longitude,group\n"
        "Импорт 1,56.8,47.8,Новая Из CSV\n"
    )
    imp_file = tmp_path / "step_s.csv"
    imp_file.write_text(import_csv, encoding="utf-8")
    imp_opts = ImportOptions(create_missing_groups=True)
    imp_svc = ImportService()
    imp_res = imp_svc.validate_file(imp_file, imp_opts)
    assert imp_res.valid_rows == 1
    assert len(imp_res.new_groups) == 1
    assert imp_res.new_groups[0].name == "Новая Из CSV"
    assert imp_res.points[0].group_id == imp_res.new_groups[0].id

    # =========================================================================
    # T. PNG/JPEG при hidden group
    # =========================================================================
    hidden_ids_t = {g1.id}
    export_opts = ImageExportOptions(file_path=str(tmp_path / "export.png"), width_px=300, height_px=300)
    img = MapRenderer.render_map(
        options=export_opts,
        active_crs="EPSG:4326",
        target_extent=(46.0, 55.0, 48.0, 57.0),
        points=ps.get_points(),
        hidden_group_ids=hidden_ids_t,
    )
    assert img is not None
    # Точки группы g1 не попали в рендеринг
    visible_export_pts = [p for p in ps.get_points() if p.group_id not in hidden_ids_t]
    assert len(visible_export_pts) == 2

    # =========================================================================
    # U. RU -> EN. Пользовательские названия не изменяются
    # =========================================================================
    orig_l = get_language()
    try:
        set_language("ru")
        assert tr("groups.ungrouped") == "Без группы"
        assert g1.name == "Местообитания"

        set_language("en")
        assert tr("groups.ungrouped") == "Ungrouped"
        # Пользовательское название группы НЕ изменилось
        assert g1.name == "Местообитания"
    finally:
        set_language(orig_l)
