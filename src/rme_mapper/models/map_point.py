"""Модель пользовательской географической точки."""

import uuid
from dataclasses import dataclass, field


@dataclass
class MapPoint:
    """Модель пользовательской точки на карте.

    Главный принцип:
    latitude и longitude являются первичным источником географических данных.
    Экранные координаты не хранятся в качестве основных данных.
    """

    name: str
    latitude: float
    longitude: float
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    source_crs: str = "OGC:CRS84"
    visible: bool = True
