"""Сервис управления организационными группами объектов проекта (GroupService).

Отвечает за:
- Создание, переименование, удаление групп;
- Поиск и получение списка групп;
- Управление видимостью групп;
- Валидацию уникальности имён групп (case-insensitive).
"""
from __future__ import annotations


import logging
from typing import Iterator

from rme_mapper.models.object_group import (
    ObjectGroup,
    validate_group_description,
    validate_group_name,
)

logger = logging.getLogger("rme_mapper.services.group")


class GroupService:
    """Сервис хранения и управления группами объектов в памяти."""

    def __init__(self) -> None:
        # group_id -> ObjectGroup
        self._groups: dict[str, ObjectGroup] = {}

    def create_group(
        self,
        name: str,
        description: str = "",
        visible: bool = True,
        group_id: str | None = None,
    ) -> ObjectGroup:
        """Создание новой группы объектов с проверкой уникальности имени."""
        cleaned_name = validate_group_name(name)
        cleaned_desc = validate_group_description(description)

        # Проверка уникальности имени без учёта регистра
        if self.find_group_by_name(cleaned_name) is not None:
            from rme_mapper.i18n import tr
            raise ValueError(tr("err.group.already_exists", name=cleaned_name))

        kwargs = {
            "name": cleaned_name,
            "description": cleaned_desc,
            "visible": visible,
        }
        if group_id:
            kwargs["id"] = group_id

        group = ObjectGroup(**kwargs)
        self._groups[group.id] = group
        logger.info("Создана группа: id=%s, name='%s', visible=%s", group.id, group.name, group.visible)
        return group

    def add_existing_group(self, group: ObjectGroup) -> None:
        """Добавление существующего объекта группы (например, при восстановлении в Undo или загрузке)."""
        self._groups[group.id] = group

    def rename_group(
        self,
        group_id: str,
        new_name: str,
        new_description: str | None = None,
    ) -> ObjectGroup:
        """Переименование группы и/или обновление её описания."""
        from rme_mapper.i18n import tr
        group = self.get_group(group_id)
        if not group:
            raise KeyError(tr("err.group.not_found", group_id=group_id))

        cleaned_name = validate_group_name(new_name)
        existing = self.find_group_by_name(cleaned_name)
        if existing and existing.id != group_id:
            raise ValueError(tr("err.group.already_exists", name=cleaned_name))

        group.name = cleaned_name
        if new_description is not None:
            group.description = validate_group_description(new_description)

        logger.info("Группа '%s' обновлена: name='%s'", group_id, group.name)
        return group

    def delete_group(self, group_id: str) -> ObjectGroup:
        """Удаление группы из реестра. Точки группы не удаляются (обрабатываются вызывающей стороной)."""
        if group_id not in self._groups:
            from rme_mapper.i18n import tr
            raise KeyError(tr("err.group.not_found", group_id=group_id))
        group = self._groups.pop(group_id)
        logger.info("Группа удалена: id=%s, name='%s'", group.id, group.name)
        return group

    def get_group(self, group_id: str) -> ObjectGroup | None:
        """Получение группы по идентификатору."""
        return self._groups.get(group_id)

    def find_group_by_name(self, name: str) -> ObjectGroup | None:
        """Поиск группы по названию (регистронезависимо)."""
        target = name.strip().casefold()
        for grp in self._groups.values():
            if grp.name.casefold() == target:
                return grp
        return None

    def list_groups(self) -> list[ObjectGroup]:
        """Возврат списка всех групп в порядке добавления."""
        return list(self._groups.values())

    def set_group_visibility(self, group_id: str, visible: bool) -> None:
        """Управление видимостью группы."""
        group = self.get_group(group_id)
        if not group:
            from rme_mapper.i18n import tr
            raise KeyError(tr("err.group.not_found", group_id=group_id))
        group.visible = bool(visible)
        logger.info("Видимость группы '%s' изменена на %s", group.name, group.visible)

    def is_group_visible(self, group_id: str | None) -> bool:
        """Проверка видимости группы. Для точек без группы (None) всегда возвращает True."""
        if group_id is None:
            return True
        group = self.get_group(group_id)
        if group is None:
            return True
        return group.visible

    def clear(self) -> None:
        """Полная очистка реестра групп."""
        self._groups.clear()
        logger.info("Реестр групп очищен")

    def __len__(self) -> int:
        return len(self._groups)

    def __iter__(self) -> Iterator[ObjectGroup]:
        return iter(self._groups.values())
