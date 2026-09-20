"""Модели данных и спецификации для экспорта объектов (Stage 22)."""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class ObjectExportFormat(str, Enum):
    """Поддерживаемые форматы экспорта объектов."""

    CSV = "csv"
    XLSX = "xlsx"
    TXT = "txt"
    GEOJSON = "geojson"


class ObjectExportScope(str, Enum):
    """Область экспортируемых объектов."""

    ALL = "all"
    SELECTED = "selected"
    VISIBLE = "visible"


class CsvDelimiter(str, Enum):
    """Разделители полей для CSV и текстовых форматов."""

    COMMA = ","
    SEMICOLON = ";"
    TAB = "\t"


@dataclass(frozen=True)
class ExportFieldDefinition:
    """Определение атрибутивного поля для экспорта."""

    key: str
    title_key: str
    category: str  # "general", "coordinates", "marker", "zone", "advanced"
    default_enabled: bool = False
    is_numeric: bool = False


# Полный реестр поддерживаемых полей экспорта
EXPORT_FIELDS: list[ExportFieldDefinition] = [
    # Общие атрибуты
    ExportFieldDefinition("object_number", "export_objects.field_object_number", "general", default_enabled=True),
    ExportFieldDefinition("name", "export_objects.field_name", "general", default_enabled=True),
    ExportFieldDefinition("category", "export_objects.field_category", "general", default_enabled=True),
    ExportFieldDefinition("group", "export_objects.field_group", "general", default_enabled=True),
    ExportFieldDefinition("description", "export_objects.field_description", "general", default_enabled=False),
    ExportFieldDefinition("visible", "export_objects.field_visible", "general", default_enabled=False),
    # Географические координаты (WGS84)
    ExportFieldDefinition("latitude", "export_objects.field_latitude", "coordinates", default_enabled=True, is_numeric=True),
    ExportFieldDefinition("longitude", "export_objects.field_longitude", "coordinates", default_enabled=True, is_numeric=True),
    ExportFieldDefinition("lat_dms", "export_objects.field_lat_dms", "coordinates", default_enabled=False),
    ExportFieldDefinition("lon_dms", "export_objects.field_lon_dms", "coordinates", default_enabled=False),
    # Спроецированные координаты в целевой CRS
    ExportFieldDefinition("x", "export_objects.field_x", "coordinates", default_enabled=False, is_numeric=True),
    ExportFieldDefinition("y", "export_objects.field_y", "coordinates", default_enabled=False, is_numeric=True),
    ExportFieldDefinition("crs", "export_objects.field_crs", "coordinates", default_enabled=False),
    # Стиль маркера точки
    ExportFieldDefinition("marker_shape", "export_objects.field_marker_shape", "marker", default_enabled=False),
    ExportFieldDefinition("marker_size", "export_objects.field_marker_size", "marker", default_enabled=False, is_numeric=True),
    ExportFieldDefinition("marker_fill_color", "export_objects.field_marker_fill_color", "marker", default_enabled=False),
    ExportFieldDefinition("marker_stroke_color", "export_objects.field_marker_stroke_color", "marker", default_enabled=False),
    ExportFieldDefinition("marker_stroke_width", "export_objects.field_marker_stroke_width", "marker", default_enabled=False, is_numeric=True),
    ExportFieldDefinition("marker_opacity_percent", "export_objects.field_marker_opacity", "marker", default_enabled=False, is_numeric=True),
    # Стиль географической зоны
    ExportFieldDefinition("zone_enabled", "export_objects.field_zone_enabled", "zone", default_enabled=False),
    ExportFieldDefinition("zone_radius_m", "export_objects.field_zone_radius_m", "zone", default_enabled=False, is_numeric=True),
    ExportFieldDefinition("zone_fill_color", "export_objects.field_zone_fill_color", "zone", default_enabled=False),
    ExportFieldDefinition("zone_opacity_percent", "export_objects.field_zone_opacity", "zone", default_enabled=False, is_numeric=True),
    ExportFieldDefinition("zone_border_color", "export_objects.field_zone_border_color", "zone", default_enabled=False),
    ExportFieldDefinition("zone_border_width", "export_objects.field_zone_border_width", "zone", default_enabled=False, is_numeric=True),
    ExportFieldDefinition("zone_border_style", "export_objects.field_zone_border_style", "zone", default_enabled=False),
    # Расширенные идентификаторы
    ExportFieldDefinition("internal_id", "export_objects.field_internal_id", "advanced", default_enabled=False),
]

EXPORT_FIELDS_BY_KEY: dict[str, ExportFieldDefinition] = {f.key: f for f in EXPORT_FIELDS}

DEFAULT_FIELD_KEYS: list[str] = [f.key for f in EXPORT_FIELDS if f.default_enabled]


@dataclass
class ObjectExportOptions:
    """Опции экспорта объектов."""

    format: ObjectExportFormat = ObjectExportFormat.CSV
    scope: ObjectExportScope = ObjectExportScope.ALL
    field_keys: list[str] = field(default_factory=lambda: list(DEFAULT_FIELD_KEYS))
    target_crs: str = "EPSG:3857"
    dd_precision: int = 6
    projected_precision: int = 3
    delimiter: CsvDelimiter = CsvDelimiter.COMMA
    utf8_bom: bool = True
    include_internal_id: bool = False
    include_headers: bool = True
