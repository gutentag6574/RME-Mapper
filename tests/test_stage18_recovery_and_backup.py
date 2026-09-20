"""Тесты аварийного восстановления (Crash Recovery) и резервного копирования (*.bak) для групп (Этап 18)."""

import json
from pathlib import Path

from rme_mapper.models.map_point import MapPoint
from rme_mapper.models.object_group import ObjectGroup
from rme_mapper.services.group_service import GroupService
from rme_mapper.services.point_service import PointService
from rme_mapper.services.project_service import ProjectService


def test_crash_recovery_snapshot_preserves_and_restores_groups(tmp_path):
    """Проверка аварийного восстановления (Point 24):

    Recovery сохраняет groups, names, descriptions, visibility, membership.
    """
    proj_service = ProjectService()
    proj_service._recovery_dir = tmp_path

    # Исходные данные
    g1 = ObjectGroup(id="g-alpha", name="Альфа", description="Первая группа", visible=True)
    g2 = ObjectGroup(id="g-beta", name="Бета", description="Скрытая группа", visible=False)

    p1 = MapPoint(id="p1", name="Точка 1", latitude=56.0, longitude=47.0, group_id="g-alpha")
    p2 = MapPoint(id="p2", name="Точка 2", latitude=56.1, longitude=47.1, group_id="g-beta")
    p3 = MapPoint(id="p3", name="Точка 3", latitude=56.2, longitude=47.2, group_id=None)

    project_data = proj_service.build_project_data(
        map_path=None,
        layers=[],
        points=[p1, p2, p3],
        groups=[g1, g2],
    )

    # Сохраняем recovery снимок
    snap_path = proj_service.save_recovery_snapshot(project_data, str(tmp_path / "test.gpmap"))
    assert snap_path.exists()

    # Загружаем recovery снимок
    restored_data, restored_path = proj_service.load_recovery_snapshot()
    assert restored_data is not None
    assert len(restored_data.groups) == 2

    rg1 = next(g for g in restored_data.groups if g.id == "g-alpha")
    assert rg1.name == "Альфа"
    assert rg1.description == "Первая группа"
    assert rg1.visible is True

    rg2 = next(g for g in restored_data.groups if g.id == "g-beta")
    assert rg2.name == "Бета"
    assert rg2.description == "Скрытая группа"
    assert rg2.visible is False

    # Проверка членства точек
    pts_by_id = {p.id: p for p in restored_data.points}
    assert pts_by_id["p1"].group_id == "g-alpha"
    assert pts_by_id["p2"].group_id == "g-beta"
    assert pts_by_id["p3"].group_id is None


def test_backup_preserves_groups_and_membership(tmp_path):
    """Проверка резервного копирования *.bak при перезаписи (Point 25)."""
    proj_service = ProjectService()
    project_file = tmp_path / "project.gpmap"
    bak_file = tmp_path / "project.gpmap.bak"

    g1 = ObjectGroup(id="g1", name="Исходная группа", visible=True)
    p1 = MapPoint(id="p1", name="П1", latitude=56.0, longitude=47.0, group_id="g1")

    proj1 = proj_service.build_project_data(
        map_path=None,
        layers=[],
        points=[p1],
        groups=[g1],
    )

    # Первое сохранение
    proj_service.save_project(proj1, project_file, create_backup=True)
    assert project_file.exists()
    assert not bak_file.exists()

    # Второе сохранение (с модификацией группы)
    g2 = ObjectGroup(id="g2", name="Вторая группа", visible=False)
    p2 = MapPoint(id="p2", name="П2", latitude=56.5, longitude=47.5, group_id="g2")
    proj2 = proj_service.build_project_data(
        map_path=None,
        layers=[],
        points=[p2],
        groups=[g2],
    )

    proj_service.save_project(proj2, project_file, create_backup=True)
    assert project_file.exists()
    assert bak_file.exists()

    # Восстановление из .bak файла
    bak_data = proj_service.load_project(bak_file)
    assert len(bak_data.groups) == 1
    assert bak_data.groups[0].id == "g1"
    assert bak_data.groups[0].name == "Исходная группа"
    assert bak_data.points[0].group_id == "g1"
