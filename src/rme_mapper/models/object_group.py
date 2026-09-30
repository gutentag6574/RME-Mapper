"""Модель организационной группы объектов (ObjectGroup).

Группа — это исключительно организационная сущность проекта,
позволяющая структурировать и фильтровать точки на карте.
Не является геометрией GIS.
"""
from __future__ import annotations


from dataclasses import asdict, dataclass, field
import re
from typing import Any
from uuid import uuid4

MAX_GROUP_NAME_LENGTH = 200
MAX_GROUP_DESCRIPTION_LENGTH = 8192
_HTML_TAG_RE = re.compile(r"<[^>]+>")


def validate_group_name(name: str) -> str:
    """Валидация названия группы: обязательно, trim whitespace, 1..200 символов."""
    if not isinstance(name, str):
        raise ValueError("Название группы должно быть строкой.")
    cleaned = name.strip()
    if not cleaned:
        raise ValueError("Название группы не может быть пустым.")
    if len(cleaned) > MAX_GROUP_NAME_LENGTH:
        raise ValueError(
            f"Название группы не должно превышать {MAX_GROUP_NAME_LENGTH} символов (получено {len(cleaned)})."
        )
    return cleaned


def validate_group_description(description: str) -> str:
    """Валидация описания группы: plain text, до 8192 символов, без HTML."""
    if not description:
        return ""
    if not isinstance(description, str):
        raise ValueError("Описание группы должно быть строкой.")
    cleaned = description.strip()
    if _HTML_TAG_RE.search(cleaned):
        raise ValueError("Описание группы не должно содержать HTML-разметку.")
    if len(cleaned) > MAX_GROUP_DESCRIPTION_LENGTH:
        raise ValueError(
            f"Описание группы не должно превышать {MAX_GROUP_DESCRIPTION_LENGTH} символов (получено {len(cleaned)})."
        )
    return cleaned


@dataclass
class ObjectGroup:
    """Организационная группа объектов проекта."""

    name: str
    id: str = field(default_factory=lambda: uuid4().hex)
    description: str = ""
    visible: bool = True

    def __post_init__(self) -> None:
        self.name = validate_group_name(self.name)
        self.description = validate_group_description(self.description)
        self.visible = bool(self.visible)

    def to_dict(self) -> dict[str, Any]:
        """Преобразование в словарь для JSON-сериализации."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ObjectGroup":
        """Создание экземпляра из словаря с валидацией."""
        if not isinstance(data, dict):
            raise ValueError("Данные группы должны быть словарем.")
        raw_name = str(data.get("name") or "")
        group_id = str(data.get("id") or uuid4().hex)
        desc = str(data.get("description") or "")
        vis = bool(data.get("visible", True))
        return cls(
            name=raw_name,
            id=group_id,
            description=desc,
            visible=vis,
        )
