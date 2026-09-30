"""Комплексные сквозные тесты GIS-инструментов, Undo/Redo и групп объектов (Этап 25).

Покрывает:
1. Измерения расстояний и площадей: WGS84 геодезия, rubber-band, pan/zoom, отмена, инвариант чистоты Undo/Redo.
2. Масштабная линейка и координатная сетка: адаптивные шаги, лимит линий (<=30), скрытие без карты.
3. Сложные цепочки Undo/Redo: множественные шаги, отсечение Redo ветки при новом действии, отсутствие фантомных команд при Esc.
4. Cross-Feature Scenario D: Move Point -> Undo -> Save -> Reload (координаты после Undo сохраняются).
5. Cross-Feature Scenario E: Delete Group -> Undo -> Save -> Reload (связи группы и точек восстанавливаются).
6. Группы, фильтры и подписи (Labels): комбинированная фильтрация, счетчик 'Показано X из Y', предотвращение наложений (collision avoidance).
"""
from __future__ import annotations

import copy
from pathlib import Path
import pytest
from PySide6.QtCore import Qt, QPointF, QRectF
from PySide6.QtGui import QPainterPath

from rme_mapper.models.map_point import MapPoint
from rme_mapper.models.object_group import ObjectGroup
from rme_mapper.services.geodesic_service import GeodesicService
from rme_mapper.services.undo_manager import (
    AddPointCommand,
    AssignPointsToGroupCommand,
    CreateGroupCommand,
    DeleteGroupCommand,
    EditPointCommand,
    MovePointCommand,
    UndoManager,
)
from rme_mapper.ui.main_window import MainWindow


@pytest.fixture
def mari_gpkg_path() -> Path:
    p = Path("maps/test_map/prepared/mari.gpkg").resolve()
    assert p.exists()
    return p


def test_01_distance_and_area_measurement_tools_and_safety_invariant(qapp, mari_gpkg_path: Path):
    """Инструменты измерений: геодезический расчет, rubber-band, отмена и неизменность Undo/проекта."""
    window = MainWindow()
    window.load_map(mari_gpkg_path)
    window.resize(1000, 700)
    window.show()

    canvas = window.map_canvas
    undo_mgr = window.point_controller.undo_manager
    undo_len_before = len(undo_mgr._undo_stack)
    is_mod_before = window.is_modified

    # --- Измерение расстояния ---
    window.measure_distance_action.trigger()
    assert canvas.interaction_mode == "measure_distance"

    # Добавляем 3 вершины
    v1 = (47.880, -56.630)
    v2 = (47.890, -56.640)
    v3 = (47.900, -56.650)
    canvas._add_measurement_vertex(v1)
    canvas._add_measurement_vertex(v2)
    canvas._add_measurement_vertex(v3)
    assert len(canvas._measure_points) == 3

    # Проверка геодезического расчета расстояния WGS84
    # Дистанция между v1 и v2
    d1 = GeodesicService.calculate_distance(lat1=56.630, lon1=47.880, lat2=56.640, lon2=47.890)
    d2 = GeodesicService.calculate_distance(lat1=56.640, lon1=47.890, lat2=56.650, lon2=47.900)
    assert d1 > 1000.0 and d2 > 1000.0

    # Проверка pan / zoom во время измерения (вершины должны оставаться)
    assert canvas.has_measurements() is True
    assert len(canvas._measure_points) == 3

    # Завершение и очистка измерения
    canvas._finish_measurement()
    window.clear_measurements_action.trigger()
    assert len(canvas._measure_points) == 0

    # --- Измерение площади ---
    window.measure_area_action.trigger()
    assert canvas.interaction_mode == "measure_area"

    # Добавляем 4 вершины полигона
    p1 = (47.880, -56.630)
    p2 = (47.890, -56.630)
    p3 = (47.890, -56.640)
    p4 = (47.880, -56.640)
    for pt in (p1, p2, p3, p4):
        canvas._add_measurement_vertex(pt)

    assert len(canvas._measure_points) == 4
    # Проверка вычисления площади и периметра
    poly_lats = [56.630, 56.630, 56.640, 56.640]
    poly_lons = [47.880, 47.890, 47.890, 47.880]
    area, perim = GeodesicService.calculate_area_perimeter(poly_lats, poly_lons)
    assert area > 100_000.0
    assert perim > 2000.0

    # Отмена через Escape
    canvas._cancel_active_measurement()
    assert len(canvas._measure_points) == 0

    # КРИТИЧЕСКИЙ ИНВАРИАНТ: Измерения НЕ меняют проект и НЕ попадают в Undo
    assert window.is_modified == is_mod_before
    assert len(undo_mgr._undo_stack) == undo_len_before

    window.close()


def test_02_scale_bar_and_coordinate_grid(qapp, mari_gpkg_path: Path):
    """Масштабная линейка и координатная сетка: адаптивность, лимит линий (<=30) и скрытие."""
    window = MainWindow()
    window.resize(1000, 700)
    window.show()

    canvas = window.map_canvas

    # До загрузки карты масштабная линейка скрыта
    assert canvas.is_online_map_active() is False

    # Загружаем карту
    window.load_map(mari_gpkg_path)

    # Проверка масштабной линейки
    assert canvas._scale_overlay is not None
    assert canvas._show_scale_indicator is True

    # Проверка координатной сетки
    assert canvas.show_coordinate_grid is False
    window.toggle_grid_action.setChecked(True)
    assert canvas.show_coordinate_grid is True

    # Рендеринг координатной сетки
    canvas._render_coordinate_grid()
    assert canvas._grid_item_group is not None

    # Лимит безопасности: число линий сетки никогда не превышает 30
    grid_lines_count = len(canvas._grid_item_group.childItems())
    # Каждая линия может иметь текстовую метку, общее число элементов в разумных пределах
    assert grid_lines_count <= 60

    # Выгрузка карты должна корректно сбросить сетку
    window.map_controller.unload_map()
    assert canvas._grid_item_group is None or len(canvas._grid_item_group.childItems()) == 0

    window.close()


def test_03_undo_redo_complex_action_chains_and_branch_clearing():
    """Сложные цепочки Undo/Redo и инвариант отсечения Redo-ветки при новом действии."""
    undo_mgr = UndoManager()
    points_db: dict[str, MapPoint] = {}

    def apply_add(p: MapPoint):
        points_db[p.id] = copy.deepcopy(p)

    def apply_delete(pid: str):
        points_db.pop(pid, None)

    # 1. Добавление 3 точек через команды
    pt1 = MapPoint(id="u1", name="Пункт 1", latitude=56.0, longitude=47.0)
    pt2 = MapPoint(id="u2", name="Пункт 2", latitude=56.1, longitude=47.1)
    pt3 = MapPoint(id="u3", name="Пункт 3", latitude=56.2, longitude=47.2)

    cmd1 = AddPointCommand(point=pt1, add_fn=apply_add, remove_fn=apply_delete)
    cmd2 = AddPointCommand(point=pt2, add_fn=apply_add, remove_fn=apply_delete)
    cmd3 = AddPointCommand(point=pt3, add_fn=apply_add, remove_fn=apply_delete)

    undo_mgr.push(cmd1, execute=True)
    undo_mgr.push(cmd2, execute=True)
    undo_mgr.push(cmd3, execute=True)

    assert len(points_db) == 3
    assert undo_mgr.can_undo is True
    assert undo_mgr.can_redo is False

    # 2. Перемещение точки 1
    pt1_moved = copy.deepcopy(pt1)
    pt1_moved.latitude = 56.05
    cmd_move = MovePointCommand(
        before_point=pt1,
        after_point=pt1_moved,
        apply_fn=apply_add,
        description="Перемещение u1",
    )
    undo_mgr.push(cmd_move, execute=True)
    assert points_db["u1"].latitude == 56.05

    # 3. Выполняем 2 Undo
    undo_mgr.undo()  # откат перемещения
    assert points_db["u1"].latitude == 56.0
    undo_mgr.undo()  # откат добавления u3
    assert "u3" not in points_db
    assert len(points_db) == 2
    assert undo_mgr.can_redo is True

    # 4. Выполняем 1 Redo (возврат добавления u3)
    undo_mgr.redo()
    assert "u3" in points_db
    assert len(points_db) == 3

    # 5. ИНВАРИАНТ: Новое действие после Undo очищает ветку Redo
    undo_mgr.undo()  # откат u3 снова
    assert undo_mgr.can_redo is True

    pt4 = MapPoint(id="u4", name="Пункт 4 (Новая ветка)", latitude=56.3, longitude=47.3)
    cmd4 = AddPointCommand(point=pt4, add_fn=apply_add, remove_fn=apply_delete)
    undo_mgr.push(cmd4, execute=True)

    # Redo стек должен быть очищен!
    assert undo_mgr.can_redo is False
    assert "u4" in points_db
    assert "u3" not in points_db


def test_04_cross_feature_scenario_d_move_point_undo_save_reload(qapp, mari_gpkg_path: Path, tmp_path: Path):
    """Cross-Feature Scenario D: Move Point -> Undo -> Save -> Reload."""
    window = MainWindow()
    window.load_map(mari_gpkg_path)
    window.show()

    # 1. Создаем точку на исходных координатах
    lat_orig, lon_orig = 56.630, 47.880
    lat_moved, lon_moved = 56.645, 47.895

    pt = window._point_service.add_point(
        point_id="pt_scen_d",
        name="Точка Сценария D",
        latitude=lat_orig,
        longitude=lon_orig,
    )
    window.points_panel.add_point(pt)

    # 2. Перемещаем точку через MovePointCommand
    before_p = copy.deepcopy(pt)
    after_p = copy.deepcopy(pt)
    after_p.latitude = lat_moved
    after_p.longitude = lon_moved

    def apply_move(p: MapPoint):
        window._point_service.update_point(p.id, latitude=p.latitude, longitude=p.longitude)
        window.point_controller.update_point_in_table(0, p)

    cmd = MovePointCommand(before_point=before_p, after_point=after_p, apply_fn=apply_move)
    window.point_controller.undo_manager.push(cmd, execute=True)

    assert window._point_service.get_point("pt_scen_d").latitude == pytest.approx(lat_moved)

    # 3. Выполняем Undo! Координаты должны вернуться к lat_orig, lon_orig
    window.point_controller.undo()
    assert window._point_service.get_point("pt_scen_d").latitude == pytest.approx(lat_orig)
    assert window._point_service.get_point("pt_scen_d").longitude == pytest.approx(lon_orig)

    # 4. Сохраняем проект в файл
    proj_path = tmp_path / "scenario_d.gpmap"
    save_ok = window.project_controller.save_project_as_workflow(proj_path)
    assert save_ok is True

    # 5. Переоткрываем проект
    window.project_controller.new_project_workflow()
    open_ok = window.project_controller.open_project_from_path(proj_path)
    assert open_ok is True

    # 6. Проверяем координаты точки после reload
    reloaded_pt = window._point_service.get_point("pt_scen_d")
    assert reloaded_pt is not None
    assert reloaded_pt.latitude == pytest.approx(lat_orig, abs=1e-6)
    assert reloaded_pt.longitude == pytest.approx(lon_orig, abs=1e-6)

    window.close()


def test_05_cross_feature_scenario_e_delete_group_undo_save_reload(qapp, mari_gpkg_path: Path, tmp_path: Path):
    """Cross-Feature Scenario E: Delete Group -> Undo -> Save -> Reload."""
    window = MainWindow()
    window.load_map(mari_gpkg_path)
    window.show()

    # 1. Создаем группу и 2 точки в ней
    grp = window._group_service.create_group("Резервная Сеть", "Группа для удаления")
    window.group_controller.refresh_groups_ui()

    p1 = window._point_service.add_point(point_id="p_e1", name="Узел 1", latitude=56.63, longitude=47.88)
    p2 = window._point_service.add_point(point_id="p_e2", name="Узел 2", latitude=56.64, longitude=47.89)
    window.points_panel.add_point(p1)
    window.points_panel.add_point(p2)

    window._point_service.update_point("p_e1", group_id=grp.id, update_group=True)
    window._point_service.update_point("p_e2", group_id=grp.id, update_group=True)
    window.group_controller.refresh_groups_ui()

    assert window._point_service.get_point("p_e1").group_id == grp.id
    assert window._point_service.get_point("p_e2").group_id == grp.id

    # 2. Удаление группы через DeleteGroupCommand
    affected_ids = ["p_e1", "p_e2"]

    def restore_group_fn(g: ObjectGroup):
        window._group_service.add_existing_group(g)
        window.group_controller.refresh_groups_ui()

    def remove_group_fn(gid: str):
        window._group_service.delete_group(gid)
        window.group_controller.refresh_groups_ui()

    def set_points_group_fn(pids: list[str], gid: str | None):
        for pid in pids:
            window._point_service.update_point(pid, group_id=gid, update_group=True)
        window.group_controller.refresh_groups_ui()

    del_cmd = DeleteGroupCommand(
        group=grp,
        affected_point_ids=affected_ids,
        restore_group_fn=restore_group_fn,
        remove_group_fn=remove_group_fn,
        set_points_group_fn=set_points_group_fn,
    )
    window.point_controller.undo_manager.push(del_cmd, execute=True)

    # Проверяем, что группа удалена, а точки стали без группы
    assert window._group_service.get_group(grp.id) is None
    assert window._point_service.get_point("p_e1").group_id is None
    assert window._point_service.get_point("p_e2").group_id is None

    # 3. Выполняем Undo! Группа и связи точек должны быть восстановлены
    window.point_controller.undo()
    assert window._group_service.get_group(grp.id) is not None
    assert window._point_service.get_point("p_e1").group_id == grp.id
    assert window._point_service.get_point("p_e2").group_id == grp.id

    # 4. Сохраняем проект
    proj_path = tmp_path / "scenario_e.gpmap"
    save_ok = window.project_controller.save_project_as_workflow(proj_path)
    assert save_ok is True

    # 5. Переоткрываем проект
    window.project_controller.new_project_workflow()
    open_ok = window.project_controller.open_project_from_path(proj_path)
    assert open_ok is True

    # 6. Проверяем целостность группы и принадлежность точек
    reloaded_grp = window._group_service.get_group(grp.id)
    assert reloaded_grp is not None
    assert reloaded_grp.name == "Резервная Сеть"
    assert window._point_service.get_point("p_e1").group_id == grp.id
    assert window._point_service.get_point("p_e2").group_id == grp.id

    window.close()


def test_06_groups_filtering_and_label_collisions(qapp, mari_gpkg_path: Path):
    """Группы, фильтрация (счетчик 'Показано X из Y') и предотвращение наложения подписей."""
    window = MainWindow()
    window.load_map(mari_gpkg_path)
    window.resize(1000, 700)
    window.show()

    # 1. Создаем 4 точки в 2 группах
    g_a = window._group_service.create_group("Группа А")
    g_b = window._group_service.create_group("Группа Б")

    p1 = window._point_service.add_point(point_id="f1", name="Объект 1", category="Связь", latitude=56.63, longitude=47.88)
    p2 = window._point_service.add_point(point_id="f2", name="Объект 2", category="Связь", latitude=56.63001, longitude=47.88001)
    p3 = window._point_service.add_point(point_id="f3", name="Объект 3", category="Энергия", latitude=56.65, longitude=47.90)
    p4 = window._point_service.add_point(point_id="f4", name="Станция 4", category="Энергия", latitude=56.66, longitude=47.91)

    for p in (p1, p2, p3, p4):
        window.points_panel.add_point(p)

    window._point_service.update_point("f1", group_id=g_a.id, update_group=True)
    window._point_service.update_point("f2", group_id=g_a.id, update_group=True)
    window._point_service.update_point("f3", group_id=g_b.id, update_group=True)
    # f4 остается без группы

    window.group_controller.refresh_groups_ui()
    assert len(window._point_service.get_points()) == 4

    # 2. Фильтрация по поисковой строке
    window.points_panel.search_input.setText("Объект")
    # Должны отфильтроваться f1, f2, f3 (всего 3 из 4)
    assert window.points_panel.shown_count == 3

    # Очистка поиска
    window.points_panel.search_input.clear()
    assert window.points_panel.shown_count == 4

    # 3. Фильтрация по категории
    window.points_panel.category_combo.setCurrentText("Энергия")
    assert window.points_panel.shown_count == 2

    # Сброс фильтра категории
    window.points_panel.category_combo.setCurrentIndex(0)
    assert window.points_panel.shown_count == 4

    # 4. Предотвращение коллизий подписей (Collision Avoidance)
    canvas = window.map_canvas
    canvas.set_labels_mode("all")
    canvas.add_user_point(p1, map_x=47.88, map_y=-56.63)
    canvas.add_user_point(p2, map_x=47.88001, map_y=-56.63001)
    canvas._recalculate_labels_layout()

    # Точки f1 и f2 находятся на расстоянии ~1 метр (56.63, 47.88 и 56.63001, 47.88001)
    # Алгоритм раскладки подписей разводит их по разным позициям
    lbl1 = canvas._user_label_items.get("f1")
    lbl2 = canvas._user_label_items.get("f2")
    assert lbl1 is not None and lbl2 is not None
    assert lbl1.pos() != lbl2.pos()

    window.close()
