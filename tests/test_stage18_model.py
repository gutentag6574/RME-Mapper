"""Тесты для модели ObjectGroup, валидаторов и GroupService (Этап 18)."""

import pytest

from rme_mapper.models.map_point import MapPoint
from rme_mapper.models.object_group import (
    MAX_GROUP_DESCRIPTION_LENGTH,
    MAX_GROUP_NAME_LENGTH,
    ObjectGroup,
    validate_group_description,
    validate_group_name,
)
from rme_mapper.services.group_service import GroupService


def test_object_group_defaults():
    """Проверка значений по умолчанию и инициализации ObjectGroup."""
    grp = ObjectGroup(name="Группа 1")
    assert grp.id is not None
    assert len(grp.id) > 0
    assert grp.name == "Группа 1"
    assert grp.description == ""
    assert grp.visible is True


def test_object_group_serialization():
    """Проверка сериализации в словарь и восстановления из словаря."""
    grp = ObjectGroup(
        id="test-grp-1",
        name="Транспорт",
        description="Транспортные узлы",
        visible=False,
    )
    d = grp.to_dict()
    assert d == {
        "id": "test-grp-1",
        "name": "Транспорт",
        "description": "Транспортные узлы",
        "visible": False,
    }

    restored = ObjectGroup.from_dict(d)
    assert restored.id == "test-grp-1"
    assert restored.name == "Транспорт"
    assert restored.description == "Транспортные узлы"
    assert restored.visible is False


def test_validate_group_name():
    """Проверка валидации названия группы."""
    assert validate_group_name("  Склад 1  ") == "Склад 1"

    with pytest.raises(ValueError, match="не может быть пустым"):
        validate_group_name("")

    with pytest.raises(ValueError, match="не может быть пустым"):
        validate_group_name("   ")

    with pytest.raises(ValueError, match="не должно превышать"):
        validate_group_name("a" * (MAX_GROUP_NAME_LENGTH + 1))


def test_validate_group_description():
    """Проверка валидации описания группы."""
    assert validate_group_description(None) == ""
    assert validate_group_description("  Описание  ") == "Описание"
    assert validate_group_description("a" * MAX_GROUP_DESCRIPTION_LENGTH) == "a" * MAX_GROUP_DESCRIPTION_LENGTH

    with pytest.raises(ValueError, match="не должно превышать"):
        validate_group_description("a" * (MAX_GROUP_DESCRIPTION_LENGTH + 1))


def test_group_service_crud():
    """Проверка CRUD операций в GroupService."""
    service = GroupService()
    assert len(service) == 0

    # Создание
    g1 = service.create_group("Группа А", "Первая группа")
    assert len(service) == 1
    assert service.get_group(g1.id) == g1

    # Поиск по имени (case-insensitive)
    assert service.find_group_by_name("группа а") == g1
    assert service.find_group_by_name("ГРУППА А") == g1
    assert service.find_group_by_name("Несуществующая") is None

    # Попытка создать дубликат имени (case-insensitive)
    with pytest.raises(ValueError, match="уже существует"):
        service.create_group("группа а")

    # Переименование
    service.rename_group(g1.id, "Новая Группа", "Обновленное описание")
    assert g1.name == "Новая Группа"
    assert g1.description == "Обновленное описание"

    # Удаление
    deleted = service.delete_group(g1.id)
    assert deleted == g1
    assert len(service) == 0
    assert service.get_group(g1.id) is None


def test_group_service_visibility():
    """Проверка управления видимостью в GroupService."""
    service = GroupService()
    g1 = service.create_group("Группа 1", visible=True)
    assert service.is_group_visible(g1.id) is True
    assert service.is_group_visible(None) is True  # Ungrouped всегда видима со стороны группы

    service.set_group_visibility(g1.id, False)
    assert service.is_group_visible(g1.id) is False
    assert g1.visible is False


def test_map_point_group_id_default():
    """Проверка, что MapPoint имеет group_id по умолчанию None."""
    pt = MapPoint(name="Точка 1", latitude=56.0, longitude=47.0)
    assert pt.group_id is None

    pt2 = MapPoint(name="Точка 2", latitude=56.0, longitude=47.0, group_id="grp-123")
    assert pt2.group_id == "grp-123"
