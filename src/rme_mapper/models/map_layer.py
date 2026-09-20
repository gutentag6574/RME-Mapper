"""Модель картографического слоя приложения RME-Mapper."""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class LayerRole(str, Enum):
    """Роль картографического слоя в иерархии отображения."""

    WATER = "water"              # Водоемы (полигоны)
    BOUNDARY = "boundary"        # Административная граница (полигоны)
    WATERWAYS = "waterways"      # Реки и каналы (линии)
    ROADS = "roads"              # Сеть автодорог (линии)
    PLACES = "places"            # Населенные пункты (точки/полигоны)
    RASTER = "raster"            # Растровая подложка (GeoTIFF)
    UNKNOWN = "unknown"          # Неизвестный/неподдерживаемый слой


# Порядок отрисовки по умолчанию (меньший Z рисуется раньше, то есть ниже)
DEFAULT_Z_ORDERS: dict[LayerRole, int] = {
    LayerRole.RASTER: 5,
    LayerRole.WATER: 10,
    LayerRole.BOUNDARY: 20,
    LayerRole.WATERWAYS: 30,
    LayerRole.ROADS: 40,
    LayerRole.PLACES: 50,
    LayerRole.UNKNOWN: 0,
}


@dataclass
class MapLayer:
    """Описатель векторного картографического слоя."""

    id: str
    source_name: str
    display_name: str
    geometry_type: str
    crs: str
    visible: bool = True
    feature_count: int = 0
    role: LayerRole = LayerRole.UNKNOWN
    z_order: int = 0
    style: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.z_order == 0 and self.role in DEFAULT_Z_ORDERS:
            self.z_order = DEFAULT_Z_ORDERS[self.role]
