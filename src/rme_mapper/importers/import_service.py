"""Сервис импорта пользовательских точек из файлов XLSX, CSV и TXT.

Выполняет чтение, нормализацию заголовков, построчную валидацию координат (DD/DMS),
оформления и геозон без изменения состояния приложения во время парсинга.
"""

import logging
from pathlib import Path
import re
from typing import Any
import uuid

from rme_mapper.importers.base import BaseImporter
from rme_mapper.importers.delimited_importer import DelimitedImporter
from rme_mapper.importers.models import (
    CoordinateFormat,
    ImportOptions,
    ImportResult,
    ImportRow,
    ImportRowError,
    ImportRowWarning,
)
from rme_mapper.importers.xlsx_importer import XlsxImporter
from rme_mapper.models.map_point import MapPoint
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
    # Стиль маркера
    "symbol": "symbol",
    "форма": "symbol",
    "тип_маркера": "symbol",
    "shape": "symbol",
    "маркер": "symbol",
    "символ": "symbol",
    "size": "size",
    "размер": "size",
    "размер_маркера": "size",
    "red": "red",
    "r": "red",
    "красный": "red",
    "green": "green",
    "g": "green",
    "зеленый": "green",
    "зелёный": "green",
    "blue": "blue",
    "b": "blue",
    "синий": "blue",
    # Геодезическая зона
    "zone_enabled": "zone_enabled",
    "zone": "zone_enabled",
    "зона": "zone_enabled",
    "геозона": "zone_enabled",
    "включить_зону": "zone_enabled",
    "radius": "radius",
    "радиус": "radius",
    "zone_radius": "radius",
    "radius_unit": "radius_unit",
    "единица_радиуса": "radius_unit",
    "ед_изм": "radius_unit",
    "unit": "radius_unit",
    "zone_red": "zone_red",
    "zone_r": "zone_red",
    "цвет_зоны_r": "zone_red",
    "zone_green": "zone_green",
    "zone_g": "zone_green",
    "цвет_зоны_g": "zone_green",
    "zone_blue": "zone_blue",
    "zone_b": "zone_blue",
    "цвет_зоны_b": "zone_blue",
    "zone_opacity": "zone_opacity",
    "opacity": "zone_opacity",
    "прозрачность": "zone_opacity",
    "прозрачность_зоны": "zone_opacity",
}


class ImportService:
    """Сервис для проверки и валидации файлов с точками перед их добавлением в проект."""

    def __init__(self) -> None:
        self._importers: list[BaseImporter] = [
            XlsxImporter(),
            DelimitedImporter(),
        ]

    def get_importer_for_file(self, file_path: Path) -> BaseImporter | None:
        """Поиск подходящего парсера по расширению файла."""
        for imp in self._importers:
            if imp.can_handle(file_path):
                return imp
        return None

    @staticmethod
    def normalize_header(header: str) -> str:
        """Нормализация строки заголовка в канонический ключ."""
        cleaned = re.sub(r"[\s_\-]+", "_", header.strip().lower())
        return CANONICAL_HEADERS.get(cleaned, cleaned)

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

        file_size = path.stat().st_size
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

        canonical_present = set(header_map.values())

        # 3. Определение схемы (DD vs DMS)
        has_dd = "latitude" in canonical_present and "longitude" in canonical_present
        dms_req = {"lat_deg", "lat_dir", "lon_deg", "lon_dir"}
        has_dms = dms_req.issubset(canonical_present)

        if opts.coordinate_format == CoordinateFormat.DD:
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
        auto_point_counter = current_project_points_count + 1

        for row_num, raw_dict in raw_rows:
            # Создаем словарь по каноническим ключам
            c_dict: dict[str, Any] = {}
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
                            params={"value": raw_size},
                            raw_value=raw_size,
                        )
                    )

            raw_r = c_dict.get("red")
            raw_g = c_dict.get("green")
            raw_b = c_dict.get("blue")
            has_any_rgb = any(x is not None and str(x).strip() != "" for x in (raw_r, raw_g, raw_b))
            if has_any_rgb:
                if not all(x is not None and str(x).strip() != "" for x in (raw_r, raw_g, raw_b)):
                    row_errors.append(
                        ImportRowError(row_number=row_num, field="rgb", code="import.err.incomplete_rgb")
                    )
                else:
                    try:
                        r, g, b = StyleValidator.validate_rgb(raw_r, raw_g, raw_b)
                    except Exception:
                        row_errors.append(
                            ImportRowError(row_number=row_num, field="rgb", code="import.err.invalid_rgb")
                        )

            # Г. Геодезическая зона (необязательное)
            zone_enabled = False
            radius_m = 0.0
            z_r, z_g, z_b = 220, 30, 30
            zone_opacity = 30

            raw_zone = c_dict.get("zone_enabled")
            if raw_zone is not None and str(raw_zone).strip() != "":
                clean_z = str(raw_zone).strip().lower()
                if clean_z in BOOL_TRUE_VALUES:
                    zone_enabled = True
                elif clean_z in BOOL_FALSE_VALUES:
                    zone_enabled = False
                else:
                    row_errors.append(
                        ImportRowError(
                            row_number=row_num,
                            field="zone_enabled",
                            code="import.err.invalid_boolean",
                            params={"value": raw_zone},
                            raw_value=raw_zone,
                        )
                    )

            raw_rad = c_dict.get("radius")
            raw_unit = str(c_dict.get("radius_unit", "")).strip().lower()

            if raw_rad is not None and str(raw_rad).strip() != "":
                # Если радиус указан, но zone_enabled не был явно выключен (None), включаем зону
                if raw_zone is None:
                    zone_enabled = True

                # Парсинг радиуса
                try:
                    num_rad = float(str(raw_rad).strip().replace(",", "."))
                    if raw_unit in UNIT_KM_VALUES:
                        num_rad *= 1000.0
                    elif raw_unit not in UNIT_M_VALUES:
                        row_errors.append(
                            ImportRowError(
                                row_number=row_num,
                                field="radius_unit",
                                code="import.err.invalid_radius_unit",
                                params={"value": raw_unit},
                            )
                        )
                    radius_m = StyleValidator.validate_radius(num_rad, enabled=zone_enabled)
                except Exception:
                    row_errors.append(
                        ImportRowError(
                            row_number=row_num,
                            field="radius",
                            code="import.err.invalid_radius",
                            params={"value": raw_rad},
                            raw_value=raw_rad,
                        )
                    )
            elif zone_enabled:
                # Зона включена, но радиус пуст
                row_errors.append(
                    ImportRowError(row_number=row_num, field="radius", code="import.err.radius_required_when_zone_enabled")
                )

            # Цвет зоны
            raw_zr = c_dict.get("zone_red")
            raw_zg = c_dict.get("zone_green")
            raw_zb = c_dict.get("zone_blue")
            has_any_zrgb = any(x is not None and str(x).strip() != "" for x in (raw_zr, raw_zg, raw_zb))
            if has_any_zrgb:
                if not all(x is not None and str(x).strip() != "" for x in (raw_zr, raw_zg, raw_zb)):
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

            # Д. Предупреждения (дубликаты координат и границы карты)
            if coords_valid and not row_errors:
                coord_pair = (round(lat, 6), round(lon, 6))
                if coord_pair in seen_coordinates:
                    row_warnings.append(
                        ImportRowWarning(
                            row_number=row_num,
                            field="coordinates",
                            code="import.warn.duplicate_coordinates",
                            params={"lat": f"{lat:.6f}", "lon": f"{lon:.6f}"},
                        )
                    )
                seen_coordinates.add(coord_pair)

                if opts.boundary_geometry is not None:
                    is_inside = CoordinateService.is_within_boundary(lon, lat, opts.boundary_geometry)
                    if not is_inside:
                        row_warnings.append(
                            ImportRowWarning(
                                row_number=row_num,
                                field="coordinates",
                                code="import.warn.outside_working_area",
                                params={"lat": f"{lat:.6f}", "lon": f"{lon:.6f}"},
                            )
                        )

            # Е. Итоговая сборка строки
            if row_errors:
                result.invalid_rows += 1
                result.errors.extend(row_errors)
                result.warnings.extend(row_warnings)
                result.rows.append(
                    ImportRow(
                        row_number=row_num,
                        raw_data=raw_dict,
                        point=None,
                        is_valid=False,
                        errors=row_errors,
                        warnings=row_warnings,
                    )
                )
            else:
                final_name = name_str if name_str else f"Точка {auto_point_counter}"
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
                )
                result.valid_rows += 1
                result.points.append(pt)
                result.warnings.extend(row_warnings)
                result.rows.append(
                    ImportRow(
                        row_number=row_num,
                        raw_data=raw_dict,
                        point=pt,
                        is_valid=True,
                        errors=[],
                        warnings=row_warnings,
                    )
                )

        # 5. Проверка общего лимита проекта
        if current_project_points_count + result.valid_rows > MAX_PROJECT_POINTS:
            result.errors.append(
                ImportRowError(
                    row_number=0,
                    field="points",
                    code="import.err.project_points_limit_exceeded",
                    params={
                        "current": current_project_points_count,
                        "importing": result.valid_rows,
                        "limit": MAX_PROJECT_POINTS,
                    },
                )
            )

        return result

    @staticmethod
    def _parse_dd_number(val: Any) -> float:
        """Парсинг числа десятичной координаты с поддержкой точки и запятой."""
        if isinstance(val, (int, float)):
            return float(val)
        if isinstance(val, str):
            cleaned = val.strip().replace(",", ".")
            return float(cleaned)
        raise ValueError(f"Некорректное значение числа: {val}")

    def _validate_dms_row(
        self,
        row_num: int,
        c_dict: dict[str, Any],
    ) -> tuple[float, float, list[ImportRowError]]:
        """Валидация строки в формате DMS и конвертация в (lat, lon)."""
        errors: list[ImportRowError] = []

        lat_d_raw = c_dict.get("lat_deg")
        lat_m_raw = c_dict.get("lat_min")
        lat_s_raw = c_dict.get("lat_sec")
        lat_dir_raw = c_dict.get("lat_dir")

        lon_d_raw = c_dict.get("lon_deg")
        lon_m_raw = c_dict.get("lon_min")
        lon_s_raw = c_dict.get("lon_sec")
        lon_dir_raw = c_dict.get("lon_dir")

        # Проверка наличия обязательных компонентов
        parts = [
            ("lat_deg", lat_d_raw), ("lat_min", lat_m_raw), ("lat_sec", lat_s_raw), ("lat_dir", lat_dir_raw),
            ("lon_deg", lon_d_raw), ("lon_min", lon_m_raw), ("lon_sec", lon_s_raw), ("lon_dir", lon_dir_raw),
        ]
        for name, val in parts:
            if val is None or str(val).strip() == "":
                errors.append(
                    ImportRowError(row_number=row_num, field=name, code="import.err.missing_dms_component", params={"component": name})
                )

        if errors:
            return 0.0, 0.0, errors

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
        if isinstance(val, int):
            return val
        if isinstance(val, float):
            if val.is_integer():
                return int(val)
            raise ValueError(f"Компонент {name} обязан быть целым числом: {val}")
        s = str(val).strip().replace(",", ".")
        f = float(s)
        if not f.is_integer():
            raise ValueError(f"Компонент {name} обязан быть целым числом: {val}")
        return int(f)

    @staticmethod
    def _parse_float_component(val: Any, name: str) -> float:
        """Парсинг вещественного компонента секунд DMS."""
        if isinstance(val, (int, float)):
            return float(val)
        s = str(val).strip().replace(",", ".")
        return float(s)
