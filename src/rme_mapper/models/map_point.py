"""Модель пользовательской географической точки."""

import uuid
from dataclasses import dataclass, field


from rme_mapper.models.point_style import PointStyle


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
    symbol: str = "circle"
    size: float = 12.0
    red: int = 220
    green: int = 30
    blue: int = 30

    @property
    def style(self) -> PointStyle:
        """Получение объекта визуального стиля точки."""
        return PointStyle(
            symbol=self.symbol,
            size=self.size,
            red=self.red,
            green=self.green,
            blue=self.blue,
        )
