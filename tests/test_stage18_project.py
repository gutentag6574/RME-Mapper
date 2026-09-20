"""Тесты сохранения и загрузки проектов с группами объектов (Этап 18)."""

import json
from pathlib import Path

from rme_mapper.models.map_point import MapPoint
from rme_mapper.models.object_group import ObjectGroup
from rme_mapper.models.project_data import ProjectData, ProjectGroupData, ProjectPointData
from rme_mapper.services.group_service import GroupService
from rme_mapper.services.point_service import PointService
from rme_mapper.services.project_service import ProjectService


def test_project_data_serialization_with_groups(tmp_path: Path):
    """Проверка сериализации и десериализации групп в ProjectData."""
    proj_service = ProjectService()

    g1 = ObjectGroup(id="g1", name="Группа 1", description="Опис 1", visible=True)
    g2 = ObjectGroup(id="g2", name="Группа 2", description="Опис 2", visible=False)

    p1 = MapPoint(id="p1", name="П1", latitude=56.0, longitude=47.0, group_id="g1")
    p2 = MapPoint(id="p2", name="П2", latitude=56.1, longitude=47.1, group_id="g2")
    p3 = MapPoint(id="p3", name="П3", latitude=56.2, longitude=47.2, group_id=None)

    data = proj_service.build_project_data(
        map_path=None,
        layers=[],
        points=[p1, p2, p3],
        groups=[g1, g2],
    )

    assert len(data.groups) == 2
    assert data.groups[0].name == "Группа 1"
    assert data.groups[1].visible is False
    assert data.points[0].group_id == "g1"
    assert data.points[2].group_id is None

    # Сохраняем в файл
    file_path = tmp_path / "test_proj.gpmap"
    proj_service.save_project(data, file_path)

    # Читаем обратно
    loaded = proj_service.load_project(file_path)
    assert len(loaded.groups) == 2
    assert loaded.groups[0].id == "g1"
    assert loaded.groups[0].name == "Группа 1"
    assert loaded.groups[1].id == "g2"
    assert loaded.groups[1].visible is False

    assert len(loaded.points) == 3
    assert loaded.points[0].group_id == "g1"
    assert loaded.points[1].group_id == "g2"
    assert loaded.points[2].group_id is None


def test_backward_compatibility_old_project_without_groups():
    """Проверка загрузки старого файла проекта без секции 'groups'."""
    old_json = {
        "format": "GeoPoint Mapper Project",
        "version": 1,
        "map": {"name": "test"},
        "layers": {},
        "points": [
            {
                "id": "p1",
                "name": "Старая точка",
                "latitude": 56.0,
                "longitude": 47.0,
            }
        ],
    }

    data = ProjectData.from_dict(old_json)
    assert data.groups == []
    assert len(data.points) == 1
    assert data.points[0].group_id is None

    # Конвертация в MapPoint
    pt = data.points[0].to_map_point()
    assert pt.group_id is None


def test_orphan_group_reference_fallback():
    """Проверка, что ссылка на несуществующую группу безопасно сбрасывается в None."""
    proj_service = ProjectService()

    bad_json = {
        "format": "GeoPoint Mapper Project",
        "version": 1,
        "map": {},
        "layers": {},
        "groups": [
            {"id": "valid-group", "name": "Существующая"}
        ],
        "points": [
            {"id": "p1", "name": "Точка 1", "latitude": 56.0, "longitude": 47.0, "group_id": "valid-group"},
            {"id": "p2", "name": "Точка 2", "latitude": 56.0, "longitude": 47.0, "group_id": "non-existent-group"},
        ],
    }

    data = proj_service._parse_project_dict(bad_json)
    assert len(data.groups) == 1
    assert data.points[0].group_id == "valid-group"
    # Точка p2 ссылалась на отсутствующую группу - должна сброситься в None
    assert data.points[1].group_id is None


def test_duplicate_group_id_handling():
    """Проверка безопасной дедупликации групп с одинаковыми ID."""
    proj_service = ProjectService()

    dup_json = {
        "format": "GeoPoint Mapper Project",
        "version": 1,
        "map": {},
        "layers": {},
        "groups": [
            {"id": "duplicate-id", "name": "Группа 1"},
            {"id": "duplicate-id", "name": "Группа 2"},
        ],
        "points": [],
    }

    data = proj_service._parse_project_dict(dup_json)
    assert len(data.groups) == 2
    # ID первой остался прежним, у второй сгенерирован новый
    assert data.groups[0].id == "duplicate-id"
    assert data.groups[1].id != "duplicate-id"
    assert len(data.groups[1].id) > 0
