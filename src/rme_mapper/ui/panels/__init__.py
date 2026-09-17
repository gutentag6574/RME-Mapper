"""Пакет UI-панелей приложения GeoPoint Mapper."""

from rme_mapper.ui.panels.layers_panel import LayersPanel
from rme_mapper.ui.panels.points_panel import PointsPanel
from rme_mapper.ui.panels.properties_panel import (
    PropertiesPanel,
    SYMBOL_DISPLAY_NAMES,
    get_symbol_display_name,
)

__all__ = [
    "LayersPanel",
    "PointsPanel",
    "PropertiesPanel",
    "SYMBOL_DISPLAY_NAMES",
    "get_symbol_display_name",
]
