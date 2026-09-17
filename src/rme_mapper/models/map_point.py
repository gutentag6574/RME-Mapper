"""Модель пользовательской географической точки."""

import uuid
from dataclasses import dataclass, field


from rme_mapper.models.point_style import PointStyle, PointZoneStyle


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
    zone_enabled: bool = False
    radius_m: float = 0.0
    zone_red: int = 220
    zone_green: int = 30
    zone_blue: int = 30
    zone_opacity: int = 30

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

    @property
    def zone(self) -> PointZoneStyle:
        """Получение объекта стиля географической зоны точки."""
        return PointZoneStyle(
            enabled=self.zone_enabled,
            radius_m=self.radius_m,
            red=self.zone_red,
            green=self.zone_green,
            blue=self.zone_blue,
            opacity=self.zone_opacity,
        )
