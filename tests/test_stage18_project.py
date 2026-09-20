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


def test_duplicate_group_id_with_points_deterministic_assignment(caplog):
    """Критическая проверка (Point 20): при одинаковых ID групп в файле проекта:

    - Программа не падает;
    - Точки не теряются;
    - Первая группа детерминированно сохраняет оригинальный ID;
    - Точка с этим group_id остается закрепленной за первой группой;
    - Вторая группа получает новый уникальный ID и НЕ перехватывает чужие точки;
    - Событие регистрируется в журнале с уровнем warning.
    """
    import logging
    proj_service = ProjectService()

    corrupt_json = {
        "format": "GeoPoint Mapper Project",
        "version": 1,
        "map": {},
        "layers": {},
        "groups": [
            {"id": "shared-uuid-123", "name": "Первая группа А"},
            {"id": "shared-uuid-123", "name": "Вторая группа Б"},
        ],
        "points": [
            {
                "id": "pt-1",
                "name": "Точка 1",
                "latitude": 56.0,
                "longitude": 47.0,
                "group_id": "shared-uuid-123",
            }
        ],
    }

    with caplog.at_level(logging.WARNING):
        data = proj_service._parse_project_dict(corrupt_json)

    assert len(data.groups) == 2
    first_grp = data.groups[0]
    second_grp = data.groups[1]

    # Первая сохраняет исходный ID
    assert first_grp.id == "shared-uuid-123"
    assert first_grp.name == "Первая группа А"

    # Вторая получает новый уникальный ID
    assert second_grp.id != "shared-uuid-123"
    assert second_grp.name == "Вторая группа Б"
    assert len(second_grp.id) > 0

    # Точка детерминированно осталась за первой группой
    assert len(data.points) == 1
    pt = data.points[0]
    assert pt.group_id == "shared-uuid-123"
    assert pt.group_id == first_grp.id
    assert pt.group_id != second_grp.id

    # Предупреждение зафиксировано в журнале
    assert any("duplicate_group_id" in rec.message for rec in caplog.records)


def test_legacy_rmeproject_backward_compatibility():
    """Проверка открытия старого формата .rmeproject без групп (Point 18)."""
    proj_service = ProjectService()
    legacy_json = {
        "format": "RME-Mapper Project",
        "version": 1,
        "map": {"name": "legacy_map"},
        "layers": {},
        "points": [
            {
                "id": "legacy-pt",
                "name": "Старая точка RME",
                "latitude": 55.75,
                "longitude": 37.61,
            }
        ],
    }

    data = proj_service._parse_project_dict(legacy_json)
    assert data.groups == []
    assert len(data.points) == 1
    assert data.points[0].group_id is None
    map_pt = data.points[0].to_map_point()
    assert map_pt.group_id is None

