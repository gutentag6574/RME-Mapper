"""Сервис импорта пользовательских точек из файлов XLSX, CSV и TXT.

Выполняет чтение, нормализацию заголовков, построчную валидацию координат (DD/DMS/XY),
оформления и геозон без изменения состояния приложения во время парсинга.
"""
from __future__ import annotations


import logging
import math
from pathlib import Path
import re
from typing import Any
import uuid

import rme_mapper  # noqa: F401 - ensures PROJ_DATA environment variable is set
import pyproj

from rme_mapper.importers.base import BaseImporter
from rme_mapper.importers.delimited_importer import DelimitedImporter
from rme_mapper.importers.models import (
    CoordinateFormat,
    DuplicatePolicy,
    ImportOptions,
    ImportResult,
    ImportRow,
    ImportRowError,
    ImportRowWarning,
    OutsideAreaPolicy,
)
from rme_mapper.importers.xlsx_importer import XlsxImporter
from rme_mapper.models.map_point import MapPoint
from rme_mapper.models.object_group import ObjectGroup
from rme_mapper.models.point_style import ALLOWED_SYMBOLS, StyleValidator
from rme_mapper.services.coordinate_service import CoordinateService
from rme_mapper.services.project_service import MAX_PROJECT_POINTS

logger = logging.getLogger("rme_mapper.importers.service")

MAX_IMPORT_FILE_SIZE = 50 * 1024 * 1024  # 50 MB
MAX_NAME_LENGTH = 500

# Булевы синонимы
BOOL_TRUE_VALUES = {"true", "1", "yes", "да", "y", "д", "+", "t"}
BOOL_FALSE_VALUES = {"false", "0", "no", "нет", "n", "н", "-", "f"}

# Синонимы форм маркеров
SYMBOL_ALIASES = {
    "circle": "circle",
    "круг": "circle",
    "round": "circle",
    "square": "square",
    "квадрат": "square",
    "triangle": "triangle",
    "треугольник": "triangle",
}

# Синонимы единиц измерения радиуса
UNIT_KM_VALUES = {"km", "км", "километр", "километры", "километров", "kilometer", "kilometers"}
UNIT_M_VALUES = {"m", "м", "метр", "метры", "метров", "meter", "meters", ""}

# Синонимы сторон света для DMS
DIR_LAT_NORTH = {"n", "с", "north", "север"}
DIR_LAT_SOUTH = {"s", "ю", "south", "юг"}
DIR_LON_EAST = {"e", "в", "east", "восток"}
DIR_LON_WEST = {"w", "з", "west", "запад"}

# Словарь синонимов заголовков колонок -> каноническое имя поля
CANONICAL_HEADERS: dict[str, str] = {
    # Имя точки
    "name": "name",
    "название": "name",
    "имя": "name",
    "point_name": "name",
    "point": "name",
    "точка": "name",
    "метка": "name",
    "label": "name",
    "title": "name",
    "объект": "name",
    "имя_объекта": "name",
    "название_объекта": "name",
    "имя_точки": "name",
    "название_точки": "name",
    "наименование": "name",
    "наименование_объекта": "name",
    # Десятичные координаты (DD)
    "latitude": "latitude",
    "lat": "latitude",
    "широта": "latitude",
    "ш": "latitude",
    "y": "latitude",
    "longitude": "longitude",
    "lon": "longitude",
    "lng": "longitude",
    "долгота": "longitude",
    "д": "longitude",
    "x": "longitude",
    # DMS - широта
    "lat_deg": "lat_deg",
    "lat_degrees": "lat_deg",
    "градусы_широты": "lat_deg",
    "град_шир": "lat_deg",
    "lat_d": "lat_deg",
    "широта_град": "lat_deg",
    "lat_min": "lat_min",
    "lat_minutes": "lat_min",
    "минуты_широты": "lat_min",
    "мин_шир": "lat_min",
    "lat_m": "lat_min",
    "широта_мин": "lat_min",
    "lat_sec": "lat_sec",
    "lat_seconds": "lat_sec",
    "секунды_широты": "lat_sec",
    "сек_шир": "lat_sec",
    "lat_s": "lat_sec",
    "широта_сек": "lat_sec",
    "lat_dir": "lat_dir",
    "lat_direction": "lat_dir",
    "направление_широты": "lat_dir",
    "полушарие_широты": "lat_dir",
    "lat_hemisphere": "lat_dir",
    "полушарие_шир": "lat_dir",
    # DMS - долгота
    "lon_deg": "lon_deg",
    "lon_degrees": "lon_deg",
    "градусы_долготы": "lon_deg",
    "град_долг": "lon_deg",
    "lon_d": "lon_deg",
    "долгота_град": "lon_deg",
    "lon_min": "lon_min",
    "lon_minutes": "lon_min",
    "минуты_долготы": "lon_min",
    "мин_долг": "lon_min",
    "lon_m": "lon_min",
    "долгота_мин": "lon_min",
    "lon_sec": "lon_sec",
    "lon_seconds": "lon_sec",
    "секунды_долготы": "lon_sec",
    "сек_долг": "lon_sec",
    "lon_s": "lon_sec",
    "долгота_сек": "lon_sec",
    "lon_dir": "lon_dir",
    "lon_direction": "lon_dir",
    "направление_долготы": "lon_dir",
    "полушарие_долготы": "lon_dir",
    "lon_hemisphere": "lon_dir",
    "полушарие_долг": "lon_dir",
    # Координаты X/Y (проекции)
    "x_coord": "x",
    "x_coordinate": "x",
    "coord_x": "x",
    "easting": "x",
    "координата_х": "x",
    "координата_x": "x",
    "х_коорд": "x",
    "x_коорд": "x",
    "восток": "x",
    "y_coord": "y",
    "y_coordinate": "y",
    "coord_y": "y",
    "northing": "y",
    "координата_у": "y",
    "координата_y": "y",
    "у_коорд": "y",
    "y_коорд": "y",
    "север": "y",
    # Оформление маркера
    "symbol": "symbol",
    "форма": "symbol",
    "символ": "symbol",
    "маркер": "symbol",
    "shape": "symbol",
    "type": "symbol",
    "size": "size",
    "размер": "size",
    "red": "red",
    "r": "red",
    "красный": "red",
    "к": "red",
    "green": "green",
    "g": "green",
    "зеленый": "green",
    "з": "green",
    "blue": "blue",
    "b": "blue",
    "синий": "blue",
    "с_цвет": "blue",
    # Геодезические зоны
    "zone_enabled": "zone_enabled",
    "zone": "zone_enabled",
    "зона": "zone_enabled",
    "геозона": "zone_enabled",
    "has_zone": "zone_enabled",
    "radius": "radius",
    "радиус": "radius",
    "rad": "radius",
    "radius_unit": "radius_unit",
    "unit": "radius_unit",
    "единицы": "radius_unit",
    "ед_изм": "radius_unit",
    "zone_red": "zone_red",
    "zr": "zone_red",
    "зона_к": "zone_red",
    "zone_r": "zone_red",
    "зона_красный": "zone_red",
    "zone_green": "zone_green",
    "zg": "zone_green",
    "зона_з": "zone_green",
    "zone_g": "zone_green",
    "зона_зеленый": "zone_green",
    "zone_blue": "zone_blue",
    "zb": "zone_blue",
    "зона_с": "zone_blue",
    "zone_b": "zone_blue",
    "зона_синий": "zone_blue",
    "zone_opacity": "zone_opacity",
    "opacity": "zone_opacity",
    "прозрачность": "zone_opacity",
    # Этап 17: Новые поля объекта и стили
    "object_number": "object_number",
    "number": "object_number",
    "номер": "object_number",
    "номер_объекта": "object_number",
    "код": "object_number",
    "№": "object_number",
    "no": "object_number",
    "description": "description",
    "описание": "description",
    "примечание": "description",
    "комментарий": "description",
    "desc": "description",
    "notes": "description",
    "category": "category",
    "категория": "category",
    "тип": "category",
    "класс": "category",
    "cat": "category",
    # Этап 18: Группы объектов
    "group": "group",
    "group_name": "group",
    "группа": "group",
    "имя_группы": "group",
    "название_группы": "group",
    "visible": "visible",
    "видимость": "visible",
    "видимый": "visible",
    "отображать": "visible",
    # Обводка маркера
    "stroke_red": "stroke_red",
    "обводка_красный": "stroke_red",
    "stroke_r": "stroke_red",
    "обводка_к": "stroke_red",
    "stroke_green": "stroke_green",
    "обводка_зеленый": "stroke_green",
    "stroke_g": "stroke_green",
    "обводка_з": "stroke_green",
    "stroke_blue": "stroke_blue",
    "обводка_синий": "stroke_blue",
    "stroke_b": "stroke_blue",
    "обводка_с": "stroke_blue",
    "stroke_width": "stroke_width",
    "толщина_обводки": "stroke_width",
    "ширина_обводки": "stroke_width",
    "marker_opacity": "marker_opacity",
    "прозрачность_маркера": "marker_opacity",
    # Граница геозоны
    "zone_border_red": "zone_border_red",
    "граница_зоны_красный": "zone_border_red",
    "border_red": "zone_border_red",
    "zone_border_r": "zone_border_red",
    "zone_border_green": "zone_border_green",
    "граница_зоны_зеленый": "zone_border_green",
    "border_green": "zone_border_green",
    "zone_border_g": "zone_border_green",
    "zone_border_blue": "zone_border_blue",
    "граница_зоны_синий": "zone_border_blue",
    "border_blue": "zone_border_blue",
    "zone_border_b": "zone_border_blue",
    "zone_border_width": "zone_border_width",
    "толщина_границы_зоны": "zone_border_width",
    "border_width": "zone_border_width",
    "толщина_границы": "zone_border_width",
    "zone_border_style": "zone_border_style",
    "стиль_границы_зоны": "zone_border_style",
    "border_style": "zone_border_style",
    "стиль_границы": "zone_border_style",
}


class ImportService:
    """Сервис импорта точек из табличных файлов различных форматов."""

    def __init__(self) -> None:
        self._importers: list[BaseImporter] = [
            XlsxImporter(),
            DelimitedImporter(),
        ]

    def get_importer_for_file(self, file_path: Path) -> BaseImporter | None:
        """Поиск подходящего парсера для указанного файла."""
        for importer in self._importers:
            if importer.can_handle(file_path):
                return importer
        return None

    def get_sheet_names(self, file_path: Path) -> list[str]:
        """Получение списка рабочих листов книги XLSX."""
        importer = self.get_importer_for_file(file_path)
        if importer:
            return importer.get_sheet_names(file_path)
        return []

    def read_preview_rows(
        self,
        file_path: Path,
        options: ImportOptions,
        max_rows: int = 100,
    ) -> tuple[list[list[str]], int, str | None, str | None]:
        """Чтение сырых строк для предпросмотра."""
        importer = self.get_importer_for_file(file_path)
        if importer:
            return importer.read_preview_rows(file_path, options, max_rows)
        return [], 0, None, None

    def normalize_header(self, header: str) -> str:
        """Нормализация строки заголовка в канонический ключ."""
        cleaned = re.sub(r"[\s_\-]+", "_", header.strip().lower())
        return CANONICAL_HEADERS.get(cleaned, cleaned)

    def suggest_column_mapping(
        self,
        headers: list[str],
        coord_format: CoordinateFormat = CoordinateFormat.AUTO,
    ) -> dict[str, str]:
        """Автоматическое предварительное сопоставление колонок файла на основе синонимов."""
        mapping: dict[str, str] = {}
        assigned_headers: set[str] = set()

        for orig_h in headers:
            if not orig_h:
                continue
            clean = orig_h.strip()
            canon = self.normalize_header(clean)

            if coord_format == CoordinateFormat.XY:
                if clean.lower() in ("x", "x_coord", "easting", "восток", "coord_x") or canon in ("x", "longitude"):
                    if "x" not in mapping and clean not in assigned_headers:
                        mapping["x"] = clean
                        assigned_headers.add(clean)
                        continue
                if clean.lower() in ("y", "y_coord", "northing", "север", "coord_y") or canon in ("y", "latitude"):
                    if "y" not in mapping and clean not in assigned_headers:
                        mapping["y"] = clean
                        assigned_headers.add(clean)
                        continue

            if canon and canon not in mapping and clean not in assigned_headers:
                mapping[canon] = clean
                assigned_headers.add(clean)

        return mapping

    def validate_file(
        self,
        file_path: Path | str,
        options: ImportOptions | None = None,
        current_project_points_count: int = 0,
    ) -> ImportResult:
        """Комплексная построчная валидация файла с формированием ImportResult."""
        path = Path(file_path)
        opts = options or ImportOptions()
        result = ImportResult(file_path=path)

        if not path.exists():
            result.errors.append(
                ImportRowError(row_number=0, field="file", code="import.err.file_not_found", params={"path": str(path)})
            )
            return result

        if not path.is_file():
            result.errors.append(
                ImportRowError(row_number=0, field="file", code="import.err.not_a_file", params={"path": str(path)})
            )
            return result

        result.file_mtime = path.stat().st_mtime
        file_size = path.stat().st_size
        result.file_size = file_size

        if file_size > MAX_IMPORT_FILE_SIZE:
            result.errors.append(
                ImportRowError(
                    row_number=0,
                    field="file",
                    code="import.err.file_too_large",
                    params={"size_mb": round(file_size / (1024 * 1024), 1), "max_mb": 50},
                )
            )
            return result

        importer = self.get_importer_for_file(path)
        if not importer:
            result.errors.append(
                ImportRowError(
                    row_number=0,
                    field="file",
                    code="import.err.unsupported_file_format",
                    params={"ext": path.suffix},
                )
            )
            return result

        # 1. Чтение строк через соответствующий импортер
        try:
            raw_rows, enc, delim, sheet = importer.read_rows(path, opts)
            result.detected_encoding = enc
            result.detected_delimiter = delim
            result.sheet_name = sheet
        except Exception as e:
            logger.error("Ошибка при чтении файла %s: %s", path, e)
            result.errors.append(
                ImportRowError(row_number=0, field="file", code="import.err.read_error", params={"error": str(e)})
            )
            return result

        if not raw_rows:
            result.errors.append(
                ImportRowError(row_number=0, field="file", code="import.err.file_empty")
            )
            return result

        # 2. Построение сопоставления заголовков
        sample_row = raw_rows[0][1]
        header_map: dict[str, str] = {}  # original_header -> canonical_key
        for orig_h in sample_row.keys():
            canon = self.normalize_header(orig_h)
            header_map[orig_h] = canon

        if opts.column_mapping:
            canonical_present = set(opts.column_mapping.keys())
        else:
            canonical_present = set(header_map.values())

        # 3. Определение схемы (DD vs DMS vs XY)
        has_dd = "latitude" in canonical_present and "longitude" in canonical_present
        dms_req = {"lat_deg", "lat_dir", "lon_deg", "lon_dir"}
        has_dms = dms_req.issubset(canonical_present)
        has_xy = "x" in canonical_present and "y" in canonical_present

        transformer = None

        if opts.coordinate_format == CoordinateFormat.XY:
            if not has_xy:
                result.errors.append(
                    ImportRowError(row_number=1, field="header", code="import.err.missing_xy_headers")
                )
                return result
            target_format = CoordinateFormat.XY
            source_crs = opts.source_crs or "EPSG:4326"
            try:
                pyproj.CRS.from_user_input(source_crs)
                transformer = pyproj.Transformer.from_crs(source_crs, "EPSG:4326", always_xy=True)
            except Exception as e:
                result.errors.append(
                    ImportRowError(row_number=1, field="source_crs", code="import.err.invalid_crs", params={"crs": source_crs, "error": str(e)})
                )
                return result

        elif opts.coordinate_format == CoordinateFormat.DD:
            if not has_dd:
                result.errors.append(
                    ImportRowError(row_number=1, field="header", code="import.err.missing_dd_headers")
                )
                return result
            target_format = CoordinateFormat.DD

        elif opts.coordinate_format == CoordinateFormat.DMS:
            if not has_dms:
                result.errors.append(
                    ImportRowError(row_number=1, field="header", code="import.err.missing_dms_headers")
                )
                return result
            target_format = CoordinateFormat.DMS

        else:  # AUTO
            if opts.column_mapping:
                if has_xy:
                    target_format = CoordinateFormat.XY
                    source_crs = opts.source_crs or "EPSG:4326"
                    try:
                        pyproj.CRS.from_user_input(source_crs)
                        transformer = pyproj.Transformer.from_crs(source_crs, "EPSG:4326", always_xy=True)
                    except Exception as e:
                        result.errors.append(
                            ImportRowError(row_number=1, field="source_crs", code="import.err.invalid_crs", params={"crs": source_crs, "error": str(e)})
                        )
                        return result
                elif has_dd:
                    target_format = CoordinateFormat.DD
                elif has_dms:
                    target_format = CoordinateFormat.DMS
                else:
                    result.errors.append(
                        ImportRowError(row_number=1, field="header", code="import.err.no_coordinate_headers")
                    )
                    return result
            else:
                if has_dd and has_dms:
                    result.errors.append(
                        ImportRowError(row_number=1, field="header", code="import.err.ambiguous_format")
                    )
                    return result
                elif has_dd:
                    target_format = CoordinateFormat.DD
                elif has_dms:
                    target_format = CoordinateFormat.DMS
                else:
                    result.errors.append(
                        ImportRowError(row_number=1, field="header", code="import.err.no_coordinate_headers")
                    )
                    return result

        result.detected_format = target_format
        result.total_rows = len(raw_rows)

        # 4. Построчная валидация
        seen_coordinates: set[tuple[float, float]] = set()
        existing_coords: set[tuple[float, float]] = {
            (round(p.latitude, 6), round(p.longitude, 6))
            for p in opts.existing_points
        }
        auto_point_counter = current_project_points_count + 1
        dynamic_group_map: dict[str, str] = {}
        new_group_names_map: dict[str, str] = {}
        importing_count = 0
        limit_exceeded = False

        for row_num, raw_dict in raw_rows:
            # Создаем словарь по каноническим ключам
            c_dict: dict[str, Any] = {}
            if opts.column_mapping:
                for tgt_field, src_col in opts.column_mapping.items():
                    if src_col and src_col != "__ignore__":
                        c_dict[tgt_field] = raw_dict.get(src_col, "")
            else:
                for orig_k, orig_val in raw_dict.items():
                    c_key = header_map.get(orig_k, orig_k)
                    c_dict[c_key] = orig_val

            row_errors: list[ImportRowError] = []
            row_warnings: list[ImportRowWarning] = []

            # А. Имя точки
            raw_name = c_dict.get("name")
            name_str = str(raw_name).strip() if raw_name is not None else ""
            if len(name_str) > MAX_NAME_LENGTH:
                name_str = name_str[:MAX_NAME_LENGTH]
                row_warnings.append(
                    ImportRowWarning(
                        row_number=row_num,
                        field="name",
                        code="import.warn.name_truncated",
                        params={"max": MAX_NAME_LENGTH},
                    )
                )

            # Б. Координаты
            lat: float = 0.0
            lon: float = 0.0
            coords_valid = False

            if target_format == CoordinateFormat.DD:
                lat_val = c_dict.get("latitude")
                lon_val = c_dict.get("longitude")

                if lat_val is None or str(lat_val).strip() == "":
                    row_errors.append(
                        ImportRowError(row_number=row_num, field="latitude", code="import.err.missing_latitude")
                    )
                if lon_val is None or str(lon_val).strip() == "":
                    row_errors.append(
                        ImportRowError(row_number=row_num, field="longitude", code="import.err.missing_longitude")
                    )

                if not row_errors:
                    # Парсинг широты
                    try:
                        lat = self._parse_dd_number(lat_val)
                        if not (-90.0 <= lat <= 90.0):
                            row_errors.append(
                                ImportRowError(
                                    row_number=row_num,
                                    field="latitude",
                                    code="import.err.lat_out_of_range",
                                    params={"value": lat_val},
                                    raw_value=lat_val,
                                )
                            )
                    except ValueError:
                        row_errors.append(
                            ImportRowError(
                                row_number=row_num,
                                field="latitude",
                                code="import.err.invalid_coordinate_number",
                                params={"value": lat_val},
                                raw_value=lat_val,
                            )
                        )

                    # Парсинг долготы
                    try:
                        lon = self._parse_dd_number(lon_val)
                        if not (-180.0 <= lon <= 180.0):
                            row_errors.append(
                                ImportRowError(
                                    row_number=row_num,
                                    field="longitude",
                                    code="import.err.lon_out_of_range",
                                    params={"value": lon_val},
                                    raw_value=lon_val,
                                )
                            )
                    except ValueError:
                        row_errors.append(
                            ImportRowError(
                                row_number=row_num,
                                field="longitude",
                                code="import.err.invalid_coordinate_number",
                                params={"value": lon_val},
                                raw_value=lon_val,
                            )
                        )

                    if not row_errors:
                        coords_valid = True

            elif target_format == CoordinateFormat.DMS:
                dms_lat, dms_lon, errs = self._validate_dms_row(row_num, c_dict)
                if errs:
                    row_errors.extend(errs)
                else:
                    lat, lon = dms_lat, dms_lon
                    coords_valid = True

            elif target_format == CoordinateFormat.XY:
                x_val = c_dict.get("x")
                y_val = c_dict.get("y")

                if x_val is None or str(x_val).strip() == "":
                    row_errors.append(
                        ImportRowError(row_number=row_num, field="x", code="import.err.missing_x")
                    )
                if y_val is None or str(y_val).strip() == "":
                    row_errors.append(
                        ImportRowError(row_number=row_num, field="y", code="import.err.missing_y")
                    )

                if not row_errors and transformer is not None:
                    try:
                        x_num = self._parse_dd_number(x_val)
                    except ValueError:
                        row_errors.append(
                            ImportRowError(row_number=row_num, field="x", code="import.err.invalid_coordinate_number", params={"value": x_val}, raw_value=x_val)
                        )
                    try:
                        y_num = self._parse_dd_number(y_val)
                    except ValueError:
                        row_errors.append(
                            ImportRowError(row_number=row_num, field="y", code="import.err.invalid_coordinate_number", params={"value": y_val}, raw_value=y_val)
                        )

                    if not row_errors:
                        if math.isnan(x_num) or math.isinf(x_num):
                            row_errors.append(ImportRowError(row_number=row_num, field="x", code="import.err.invalid_coordinate_number", params={"value": x_val}, raw_value=x_val))
                        if math.isnan(y_num) or math.isinf(y_num):
                            row_errors.append(ImportRowError(row_number=row_num, field="y", code="import.err.invalid_coordinate_number", params={"value": y_val}, raw_value=y_val))

                    if not row_errors:
                        try:
                            calc_lon, calc_lat = transformer.transform(x_num, y_num, errcheck=True)
                            if math.isnan(calc_lat) or math.isnan(calc_lon) or math.isinf(calc_lat) or math.isinf(calc_lon):
                                row_errors.append(ImportRowError(row_number=row_num, field="coordinates", code="import.err.transform_failed", params={"x": x_val, "y": y_val}))
                            elif not (-90.0 <= calc_lat <= 90.0):
                                row_errors.append(ImportRowError(row_number=row_num, field="latitude", code="import.err.lat_out_of_range", params={"value": f"{calc_lat:.6f}"}))
                            elif not (-180.0 <= calc_lon <= 180.0):
                                row_errors.append(ImportRowError(row_number=row_num, field="longitude", code="import.err.lon_out_of_range", params={"value": f"{calc_lon:.6f}"}))
                            else:
                                lat = calc_lat
                                lon = calc_lon
                                coords_valid = True
                        except Exception as e:
                            row_errors.append(ImportRowError(row_number=row_num, field="coordinates", code="import.err.transform_failed", params={"x": x_val, "y": y_val, "error": str(e)}))

            # В. Оформление маркера (необязательное)
            symbol = "circle"
            size = 12.0
            r, g, b = 220, 30, 30

            raw_sym = c_dict.get("symbol")
            if raw_sym is not None and str(raw_sym).strip() != "":
                sym_clean = str(raw_sym).strip().lower()
                matched_sym = SYMBOL_ALIASES.get(sym_clean)
                if matched_sym:
                    symbol = matched_sym
                else:
                    row_errors.append(
                        ImportRowError(
                            row_number=row_num,
                            field="symbol",
                            code="import.err.invalid_symbol",
                            params={"value": raw_sym, "allowed": ", ".join(sorted(ALLOWED_SYMBOLS))},
                            raw_value=raw_sym,
                        )
                    )

            raw_size = c_dict.get("size")
            if raw_size is not None and str(raw_size).strip() != "":
                try:
                    size = StyleValidator.validate_size(raw_size)
                except Exception:
                    row_errors.append(
                        ImportRowError(
                            row_number=row_num,
                            field="size",
                            code="import.err.invalid_size",
                            params={"value": raw_size, "min": 4, "max": 50},
                            raw_value=raw_size,
                        )
                    )

            raw_r = c_dict.get("red")
            raw_g = c_dict.get("green")
            raw_b = c_dict.get("blue")
            has_any_color = any(c is not None and str(c).strip() != "" for c in (raw_r, raw_g, raw_b))
            if has_any_color:
                if any(c is None or str(c).strip() == "" for c in (raw_r, raw_g, raw_b)):
                    row_errors.append(
                        ImportRowError(row_number=row_num, field="color", code="import.err.incomplete_rgb")
                    )
                else:
                    try:
                        r, g, b = StyleValidator.validate_rgb(raw_r, raw_g, raw_b)
                    except Exception:
                        row_errors.append(
                            ImportRowError(row_number=row_num, field="color", code="import.err.invalid_rgb")
                        )

            # Г. Геодезические зоны (необязательные)
            zone_enabled = False
            radius_m = 1000.0
            z_r, z_g, z_b = r, g, b
            zone_opacity = 30

            raw_zone_en = c_dict.get("zone_enabled")
            raw_rad = c_dict.get("radius")
            raw_unit = c_dict.get("radius_unit")

            if raw_zone_en is not None and str(raw_zone_en).strip() != "":
                z_clean = str(raw_zone_en).strip().lower()
                if z_clean in BOOL_TRUE_VALUES:
                    zone_enabled = True
                elif z_clean in BOOL_FALSE_VALUES:
                    zone_enabled = False
                else:
                    row_errors.append(
                        ImportRowError(
                            row_number=row_num,
                            field="zone_enabled",
                            code="import.err.invalid_boolean",
                            params={"value": raw_zone_en},
                            raw_value=raw_zone_en,
                        )
                    )

            if raw_rad is not None and str(raw_rad).strip() != "":
                try:
                    r_val = self._parse_dd_number(raw_rad)
                    if (r_val < 0 or r_val > 1_000_000) or (r_val == 0 and zone_enabled):
                        row_errors.append(
                            ImportRowError(
                                row_number=row_num,
                                field="radius",
                                code="import.err.invalid_radius",
                                params={"value": raw_rad, "min": 0, "max": 1000000},
                                raw_value=raw_rad,
                            )
                        )
                    elif r_val == 0 and not zone_enabled:
                        radius_m = 0.0
                    else:
                        unit_str = str(raw_unit).strip().lower() if raw_unit is not None else ""
                        if unit_str in UNIT_KM_VALUES:
                            radius_m = r_val * 1000.0
                        elif unit_str in UNIT_M_VALUES:
                            radius_m = r_val
                        else:
                            row_errors.append(
                                ImportRowError(
                                    row_number=row_num,
                                    field="radius_unit",
                                    code="import.err.invalid_radius_unit",
                                    params={"value": raw_unit},
                                    raw_value=raw_unit,
                                )
                            )
                        if raw_zone_en is None:
                            zone_enabled = True
                except ValueError:
                    row_errors.append(
                        ImportRowError(
                            row_number=row_num,
                            field="radius",
                            code="import.err.invalid_radius",
                            params={"value": raw_rad, "min": 0, "max": 1000000},
                            raw_value=raw_rad,
                        )
                    )

            # Цвет зоны
            raw_zr = c_dict.get("zone_red")
            raw_zg = c_dict.get("zone_green")
            raw_zb = c_dict.get("zone_blue")
            has_any_zcolor = any(c is not None and str(c).strip() != "" for c in (raw_zr, raw_zg, raw_zb))
            if has_any_zcolor:
                if any(c is None or str(c).strip() == "" for c in (raw_zr, raw_zg, raw_zb)):
                    row_errors.append(
                        ImportRowError(row_number=row_num, field="zone_rgb", code="import.err.incomplete_zone_rgb")
                    )
                else:
                    try:
                        z_r, z_g, z_b = StyleValidator.validate_rgb(raw_zr, raw_zg, raw_zb)
                    except Exception:
                        row_errors.append(
                            ImportRowError(row_number=row_num, field="zone_rgb", code="import.err.invalid_zone_rgb")
                        )

            # Прозрачность зоны
            raw_op = c_dict.get("zone_opacity")
            if raw_op is not None and str(raw_op).strip() != "":
                try:
                    zone_opacity = StyleValidator.validate_opacity(raw_op)
                except Exception:
                    row_errors.append(
                        ImportRowError(
                            row_number=row_num,
                            field="zone_opacity",
                            code="import.err.invalid_opacity",
                            params={"value": raw_op},
                            raw_value=raw_op,
                        )
                    )

            # Этап 17: Новые поля объекта и оформление
            raw_num = c_dict.get("object_number")
            object_number = str(raw_num).strip() if raw_num is not None and str(raw_num).strip() != "" else ""
            if len(object_number) > 100:
                object_number = object_number[:100]

            raw_cat = c_dict.get("category")
            category = str(raw_cat).strip() if raw_cat is not None and str(raw_cat).strip() != "" else ""
            if len(category) > 200:
                category = category[:200]

            # Этап 18: Группа объекта
            raw_group = c_dict.get("group")
            group_id = None
            if raw_group is not None and str(raw_group).strip() != "":
                group_name_str = str(raw_group).strip()
                if len(group_name_str) > 100:
                    group_name_str = group_name_str[:100]
                g_key = group_name_str.casefold()
                if g_key in opts.group_name_to_id:
                    group_id = opts.group_name_to_id[g_key]
                elif opts.create_missing_groups:
                    if g_key not in dynamic_group_map:
                        dynamic_group_map[g_key] = str(uuid.uuid4())
                        new_group_names_map[g_key] = group_name_str
                    group_id = dynamic_group_map[g_key]

            raw_desc = c_dict.get("description")
            description = str(raw_desc).strip() if raw_desc is not None and str(raw_desc).strip() != "" else ""
            if len(description) > 8192:
                description = description[:8192]

            visible = True
            raw_vis = c_dict.get("visible")
            if raw_vis is not None and str(raw_vis).strip() != "":
                v_clean = str(raw_vis).strip().lower()
                if v_clean in BOOL_TRUE_VALUES:
                    visible = True
                elif v_clean in BOOL_FALSE_VALUES:
                    visible = False
                else:
                    row_warnings.append(
                        ImportRowWarning(
                            row_number=row_num,
                            field="visible",
                            code="import.err.invalid_boolean",
                            params={"value": raw_vis},
                            raw_value=raw_vis,
                        )
                    )

            stroke_red = 255
            stroke_green = 255
            stroke_blue = 255
            raw_sr = c_dict.get("stroke_red")
            raw_sg = c_dict.get("stroke_green")
            raw_sb = c_dict.get("stroke_blue")
            has_stroke_color = any(c is not None and str(c).strip() != "" for c in (raw_sr, raw_sg, raw_sb))
            if has_stroke_color:
                if not all(c is not None and str(c).strip() != "" for c in (raw_sr, raw_sg, raw_sb)):
                    row_warnings.append(
                        ImportRowWarning(row_number=row_num, field="stroke_rgb", code="import.err.incomplete_rgb")
                    )
                else:
                    try:
                        stroke_red, stroke_green, stroke_blue = StyleValidator.validate_rgb(raw_sr, raw_sg, raw_sb)
                    except Exception:
                        row_warnings.append(
                            ImportRowWarning(row_number=row_num, field="stroke_rgb", code="import.err.invalid_rgb")
                        )

            stroke_width = 1
            raw_sw = c_dict.get("stroke_width")
            if raw_sw is not None and str(raw_sw).strip() != "":
                try:
                    stroke_width = StyleValidator.validate_stroke_width(raw_sw)
                except Exception:
                    row_warnings.append(
                        ImportRowWarning(
                            row_number=row_num,
                            field="stroke_width",
                            code="import.warn.invalid_stroke_width",
                            params={"value": raw_sw},
                            raw_value=raw_sw,
                        )
                    )

            marker_opacity = 100
            raw_mop = c_dict.get("marker_opacity")
            if raw_mop is not None and str(raw_mop).strip() != "":
                try:
                    marker_opacity = StyleValidator.validate_opacity(raw_mop)
                except Exception:
                    row_warnings.append(
                        ImportRowWarning(
                            row_number=row_num,
                            field="marker_opacity",
                            code="import.err.invalid_opacity",
                            params={"value": raw_mop},
                            raw_value=raw_mop,
                        )
                    )

            zone_border_red, zone_border_green, zone_border_blue = z_r, z_g, z_b
            raw_zbr = c_dict.get("zone_border_red")
            raw_zbg = c_dict.get("zone_border_green")
            raw_zbb = c_dict.get("zone_border_blue")
            has_zborder_color = any(c is not None and str(c).strip() != "" for c in (raw_zbr, raw_zbg, raw_zbb))
            if has_zborder_color:
                if not all(c is not None and str(c).strip() != "" for c in (raw_zbr, raw_zbg, raw_zbb)):
                    row_warnings.append(
                        ImportRowWarning(row_number=row_num, field="zone_border_rgb", code="import.err.incomplete_zone_rgb")
                    )
                else:
                    try:
                        zone_border_red, zone_border_green, zone_border_blue = StyleValidator.validate_rgb(raw_zbr, raw_zbg, raw_zbb)
                    except Exception:
                        row_warnings.append(
                            ImportRowWarning(row_number=row_num, field="zone_border_rgb", code="import.err.invalid_zone_rgb")
                        )

            zone_border_width = 2
            raw_zbw = c_dict.get("zone_border_width")
            if raw_zbw is not None and str(raw_zbw).strip() != "":
                try:
                    zone_border_width = StyleValidator.validate_border_width(raw_zbw)
                except Exception:
                    row_warnings.append(
                        ImportRowWarning(
                            row_number=row_num,
                            field="zone_border_width",
                            code="import.warn.invalid_border_width",
                            params={"value": raw_zbw},
                            raw_value=raw_zbw,
                        )
                    )

            zone_border_style = "solid"
            raw_zbs = c_dict.get("zone_border_style")
            if raw_zbs is not None and str(raw_zbs).strip() != "":
                try:
                    zone_border_style = StyleValidator.validate_border_style(raw_zbs)
                except Exception:
                    row_warnings.append(
                        ImportRowWarning(
                            row_number=row_num,
                            field="zone_border_style",
                            code="import.warn.invalid_border_style",
                            params={"value": raw_zbs},
                            raw_value=raw_zbs,
                        )
                    )

            # Д. Предупреждения (дубликаты координат и границы карты)
            is_duplicate = False
            is_outside = False
            is_excluded = False

            if coords_valid and not row_errors:
                coord_pair = (round(lat, 6), round(lon, 6))
                if coord_pair in seen_coordinates:
                    is_duplicate = True
                    row_warnings.append(
                        ImportRowWarning(
                            row_number=row_num,
                            field="coordinates",
                            code="import.warn.duplicate_coordinates",
                            params={"lat": f"{lat:.6f}", "lon": f"{lon:.6f}"},
                        )
                    )
                seen_coordinates.add(coord_pair)

                if coord_pair in existing_coords:
                    is_duplicate = True
                    row_warnings.append(
                        ImportRowWarning(
                            row_number=row_num,
                            field="coordinates",
                            code="import.warn.duplicate_with_project",
                            params={"lat": f"{lat:.6f}", "lon": f"{lon:.6f}"},
                        )
                    )

                if opts.boundary_geometry is not None:
                    is_inside = CoordinateService.is_point_inside_boundary(
                        longitude=lon,
                        latitude=lat,
                        boundary_geometry=opts.boundary_geometry,
                    )
                    if not is_inside:
                        is_outside = True
                        row_warnings.append(
                            ImportRowWarning(
                                row_number=row_num,
                                field="coordinates",
                                code="import.warn.outside_working_area",
                                params={"lat": f"{lat:.6f}", "lon": f"{lon:.6f}"},
                            )
                        )

                if is_duplicate and opts.duplicate_policy == DuplicatePolicy.SKIP_DUPLICATES:
                    is_excluded = True
                if is_outside and opts.outside_policy == OutsideAreaPolicy.SKIP_OUTSIDE:
                    is_excluded = True

            # Е. Итоговая сборка строки
            if row_errors:
                result.invalid_rows += 1
                result.errors.extend(row_errors)
                result.warnings.extend(row_warnings)
                row_item = ImportRow(
                    row_number=row_num,
                    raw_data=raw_dict,
                    point=None,
                    is_valid=False,
                    is_excluded=False,
                    status="error",
                    formatted_coords="",
                    errors=row_errors,
                    warnings=row_warnings,
                )
                result.rows.append(row_item)
            else:
                from rme_mapper.i18n import tr
                final_name = name_str if name_str else tr("ux.default_point_name", index=auto_point_counter)
                auto_point_counter += 1

                pt = MapPoint(
                    id=str(uuid.uuid4()),
                    name=final_name,
                    latitude=lat,
                    longitude=lon,
                    source_crs="EPSG:4326",
                    symbol=symbol,
                    size=size,
                    red=r,
                    green=g,
                    blue=b,
                    zone_enabled=zone_enabled,
                    radius_m=radius_m,
                    zone_red=z_r,
                    zone_green=z_g,
                    zone_blue=z_b,
                    zone_opacity=zone_opacity,
                    object_number=object_number,
                    description=description,
                    category=category,
                    visible=visible,
                    stroke_red=stroke_red,
                    stroke_green=stroke_green,
                    stroke_blue=stroke_blue,
                    stroke_width=stroke_width,
                    opacity=marker_opacity,
                    zone_border_red=zone_border_red,
                    zone_border_green=zone_border_green,
                    zone_border_blue=zone_border_blue,
                    zone_border_width=zone_border_width,
                    zone_border_style=zone_border_style,
                    group_id=group_id,
                )
                result.valid_rows += 1
                result.warnings.extend(row_warnings)

                status = "ok"
                if is_excluded:
                    status = "skipped"
                    result.excluded_rows += 1
                elif row_warnings:
                    status = "warning"

                if not is_excluded:
                    importing_count += 1
                    if current_project_points_count + importing_count > MAX_PROJECT_POINTS:
                        limit_exceeded = True
                        result.points.clear()
                        pt = None
                    elif not limit_exceeded:
                        result.points.append(pt)

                coords_str = f"{lat:.6f}, {lon:.6f}" if coords_valid else ""
                row_item = ImportRow(
                    row_number=row_num,
                    raw_data=raw_dict,
                    point=pt if (not is_excluded and not limit_exceeded) else None,
                    is_valid=True,
                    is_excluded=is_excluded,
                    status=status,
                    formatted_coords=coords_str,
                    errors=[],
                    warnings=row_warnings,
                )
                result.rows.append(row_item)

        # 5. Проверка глобального лимита точек проекта
        if limit_exceeded or (current_project_points_count + len(result.points) > MAX_PROJECT_POINTS):
            result.points.clear()
            result.errors.append(
                ImportRowError(
                    row_number=0,
                    field="project",
                    code="import.err.max_project_points_exceeded",
                    params={"current": current_project_points_count, "importing": importing_count or len(result.points), "max": MAX_PROJECT_POINTS},
                )
            )

        result.new_groups = [
            ObjectGroup(id=dynamic_group_map[k], name=new_group_names_map[k], visible=True)
            for k in dynamic_group_map
        ]
        result.new_group_names = [g.name for g in result.new_groups]
        return result

    @staticmethod
    def _parse_dd_number(val: Any) -> float:
        """Парсинг вещественного числа с поддержкой точки и запятой."""
        from rme_mapper.i18n import tr
        if isinstance(val, bool):
            raise ValueError(tr("import.err.bool_not_allowed", value=val))
        if isinstance(val, (int, float)):
            num = float(val)
        else:
            s = str(val).strip().replace(",", ".")
            num = float(s)
        if not math.isfinite(num):
            raise ValueError(tr("import.err.non_finite_number", value=val))
        return num

    def _validate_dms_row(
        self,
        row_num: int,
        c_dict: dict[str, Any],
    ) -> tuple[float, float, list[ImportRowError]]:
        """Валидация строки в формате DMS (градусы, минуты, секунды, полушарие)."""
        errors: list[ImportRowError] = []

        lat_d_raw = c_dict.get("lat_deg")
        lat_m_raw = c_dict.get("lat_min", 0)
        lat_s_raw = c_dict.get("lat_sec", 0.0)
        lat_dir_raw = c_dict.get("lat_dir")

        lon_d_raw = c_dict.get("lon_deg")
        lon_m_raw = c_dict.get("lon_min", 0)
        lon_s_raw = c_dict.get("lon_sec", 0.0)
        lon_dir_raw = c_dict.get("lon_dir")

        # Проверка наличия обязательных полей
        if lat_d_raw is None or str(lat_d_raw).strip() == "":
            errors.append(ImportRowError(row_number=row_num, field="lat_deg", code="import.err.missing_lat_deg"))
        if lat_dir_raw is None or str(lat_dir_raw).strip() == "":
            errors.append(ImportRowError(row_number=row_num, field="lat_dir", code="import.err.missing_lat_dir"))
        if lon_d_raw is None or str(lon_d_raw).strip() == "":
            errors.append(ImportRowError(row_number=row_num, field="lon_deg", code="import.err.missing_lon_deg"))
        if lon_dir_raw is None or str(lon_dir_raw).strip() == "":
            errors.append(ImportRowError(row_number=row_num, field="lon_dir", code="import.err.missing_lon_dir"))

        if errors:
            return 0.0, 0.0, errors

        # Если минуты или секунды опущены или пустые, принимаем за 0
        if lat_m_raw is None or str(lat_m_raw).strip() == "":
            lat_m_raw = 0
        if lat_s_raw is None or str(lat_s_raw).strip() == "":
            lat_s_raw = 0.0
        if lon_m_raw is None or str(lon_m_raw).strip() == "":
            lon_m_raw = 0
        if lon_s_raw is None or str(lon_s_raw).strip() == "":
            lon_s_raw = 0.0

        # Валидация широты DMS
        lat = 0.0
        try:
            lat_d = self._parse_int_component(lat_d_raw, "lat_deg")
            lat_m = self._parse_int_component(lat_m_raw, "lat_min")
            lat_s = self._parse_float_component(lat_s_raw, "lat_sec")
            lat_dir = str(lat_dir_raw).strip().lower()

            if lat_d < 0 or lat_d > 90:
                errors.append(ImportRowError(row_number=row_num, field="lat_deg", code="import.err.lat_deg_range", params={"value": lat_d}))
            if not (0 <= lat_m < 60):
                errors.append(ImportRowError(row_number=row_num, field="lat_min", code="import.err.lat_min_range", params={"value": lat_m}))
            if not (0.0 <= lat_s < 60.0):
                errors.append(ImportRowError(row_number=row_num, field="lat_sec", code="import.err.lat_sec_range", params={"value": lat_s}))

            if lat_d == 90 and (lat_m != 0 or lat_s != 0.0):
                errors.append(ImportRowError(row_number=row_num, field="lat_deg", code="import.err.lat_90_nonzero"))

            norm_lat_dir = None
            if lat_dir in DIR_LAT_NORTH:
                norm_lat_dir = "N"
            elif lat_dir in DIR_LAT_SOUTH:
                norm_lat_dir = "S"
            else:
                errors.append(ImportRowError(row_number=row_num, field="lat_dir", code="import.err.invalid_lat_dir", params={"value": lat_dir_raw}))

            if not errors and norm_lat_dir:
                lat_sign = -1.0 if norm_lat_dir == "S" else 1.0
                lat = lat_sign * (lat_d + lat_m / 60.0 + lat_s / 3600.0)
        except ValueError as e:
            errors.append(ImportRowError(row_number=row_num, field="latitude_dms", code="import.err.dms_parse_error", params={"error": str(e)}))

        # Валидация долготы DMS
        lon = 0.0
        try:
            lon_d = self._parse_int_component(lon_d_raw, "lon_deg")
            lon_m = self._parse_int_component(lon_m_raw, "lon_min")
            lon_s = self._parse_float_component(lon_s_raw, "lon_sec")
            lon_dir = str(lon_dir_raw).strip().lower()

            if lon_d < 0 or lon_d > 180:
                errors.append(ImportRowError(row_number=row_num, field="lon_deg", code="import.err.lon_deg_range", params={"value": lon_d}))
            if not (0 <= lon_m < 60):
                errors.append(ImportRowError(row_number=row_num, field="lon_min", code="import.err.lon_min_range", params={"value": lon_m}))
            if not (0.0 <= lon_s < 60.0):
                errors.append(ImportRowError(row_number=row_num, field="lon_sec", code="import.err.lon_sec_range", params={"value": lon_s}))

            if lon_d == 180 and (lon_m != 0 or lon_s != 0.0):
                errors.append(ImportRowError(row_number=row_num, field="lon_deg", code="import.err.lon_180_nonzero"))

            norm_lon_dir = None
            if lon_dir in DIR_LON_EAST:
                norm_lon_dir = "E"
            elif lon_dir in DIR_LON_WEST:
                norm_lon_dir = "W"
            else:
                errors.append(ImportRowError(row_number=row_num, field="lon_dir", code="import.err.invalid_lon_dir", params={"value": lon_dir_raw}))

            if not errors and norm_lon_dir:
                lon_sign = -1.0 if norm_lon_dir == "W" else 1.0
                lon = lon_sign * (lon_d + lon_m / 60.0 + lon_s / 3600.0)
        except ValueError as e:
            errors.append(ImportRowError(row_number=row_num, field="longitude_dms", code="import.err.dms_parse_error", params={"error": str(e)}))

        return lat, lon, errors

    @staticmethod
    def _parse_int_component(val: Any, name: str) -> int:
        """Парсинг целого компонента DMS."""
        from rme_mapper.i18n import tr
        if isinstance(val, bool):
            raise ValueError(tr("import.err.dms_comp_int", name=name, value=val))
        if isinstance(val, int):
            return val
        if isinstance(val, float):
            if math.isfinite(val) and val.is_integer():
                return int(val)
            raise ValueError(tr("import.err.dms_comp_int", name=name, value=val))
        s = str(val).strip().replace(",", ".")
        f = float(s)
        if not (math.isfinite(f) and f.is_integer()):
            raise ValueError(tr("import.err.dms_comp_int", name=name, value=val))
        return int(f)

    @staticmethod
    def _parse_float_component(val: Any, name: str) -> float:
        """Парсинг вещественного компонента секунд DMS."""
        from rme_mapper.i18n import tr
        if isinstance(val, bool):
            raise ValueError(tr("import.err.dms_comp_num", name=name, value=val))
        if isinstance(val, (int, float)):
            num = float(val)
        else:
            s = str(val).strip().replace(",", ".")
            num = float(s)
        if not math.isfinite(num):
            raise ValueError(tr("import.err.dms_comp_finite", name=name, value=val))
        return num
