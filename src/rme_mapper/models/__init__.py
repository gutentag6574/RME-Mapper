"""Модели данных приложения RME-Mapper.

Содержит структуры данных для:
- Картографических слоев (MapLayer, LayerRole);
- Точек и коллекций координат;
- Проектов (Project, ProjectSettings).
"""

from rme_mapper.models.map_layer import DEFAULT_Z_ORDERS, LayerRole, MapLayer

__all__ = ["DEFAULT_Z_ORDERS", "LayerRole", "MapLayer"]
