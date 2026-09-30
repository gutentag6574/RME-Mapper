"""Модель пользовательской географической точки."""
from __future__ import annotations


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
    object_number: str = ""
    description: str = ""
    category: str = ""
    stroke_red: int = 0
    stroke_green: int = 0
    stroke_blue: int = 0
    stroke_width: float = 1.0
    opacity: int = 100
    zone_border_red: int = 220
    zone_border_green: int = 30
    zone_border_blue: int = 30
    zone_border_width: float = 1.0
    zone_border_style: str = "solid"
    group_id: str | None = None

    @property
    def marker_opacity(self) -> int:
        """Псевдоним для прозрачности маркера (0..100)."""
        return self.opacity

    @marker_opacity.setter
    def marker_opacity(self, val: int) -> None:
        self.opacity = val

    @property
    def style(self) -> PointStyle:
        """Получение объекта визуального стиля точки."""
        return PointStyle(
            symbol=self.symbol,
            size=self.size,
            red=self.red,
            green=self.green,
            blue=self.blue,
            stroke_red=self.stroke_red,
            stroke_green=self.stroke_green,
            stroke_blue=self.stroke_blue,
            stroke_width=self.stroke_width,
            opacity=self.opacity,
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
            border_red=self.zone_border_red,
            border_green=self.zone_border_green,
            border_blue=self.zone_border_blue,
            border_width=self.zone_border_width,
            border_style=self.zone_border_style,
        )
