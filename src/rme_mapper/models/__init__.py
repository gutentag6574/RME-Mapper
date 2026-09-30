"""Модели данных приложения RME-Mapper.

Содержит структуры данных для:
- Пользовательских точек (MapPoint);
- Картографических слоев (MapLayer, LayerRole);
- Проектов (Project, ProjectSettings).
"""
from __future__ import annotations


from rme_mapper.models.map_layer import DEFAULT_Z_ORDERS, LayerRole, MapLayer
from rme_mapper.models.map_point import MapPoint
from rme_mapper.models.map_profile import MapProfile
from rme_mapper.models.object_group import (
    ObjectGroup,
    validate_group_description,
    validate_group_name,
)
from rme_mapper.models.project_data import (
    ProjectData,
    ProjectGroupData,
    ProjectMapData,
    ProjectPointData,
)

__all__ = [
    "DEFAULT_Z_ORDERS",
    "LayerRole",
    "MapLayer",
    "MapPoint",
    "MapProfile",
    "ObjectGroup",
    "PointStyle",
    "PointZoneStyle",
    "ProjectData",
    "ProjectGroupData",
    "ProjectMapData",
    "ProjectPointData",
    "StyleValidator",
    "validate_group_description",
    "validate_group_name",
]
