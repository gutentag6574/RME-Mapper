"""Модели данных приложения RME-Mapper.

Содержит структуры данных для:
- Пользовательских точек (MapPoint);
- Картографических слоев (MapLayer, LayerRole);
- Проектов (Project, ProjectSettings).
"""

from rme_mapper.models.map_layer import DEFAULT_Z_ORDERS, LayerRole, MapLayer
from rme_mapper.models.map_point import MapPoint
from rme_mapper.models.point_style import PointStyle, StyleValidator

__all__ = ["DEFAULT_Z_ORDERS", "LayerRole", "MapLayer", "MapPoint", "PointStyle", "StyleValidator"]
