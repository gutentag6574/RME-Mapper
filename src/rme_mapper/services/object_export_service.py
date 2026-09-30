"""Сервис экспорта пространственных объектов проекта в табличные и GIS форматы (Stage 22).

Поддерживает форматы:
- CSV (с настраиваемым разделителем и UTF-8 BOM)
- XLSX (с отдельным листом 'Objects', стилями заголовков и защитой ведущих нулей)
- TXT (табуляция / разделители)
- GeoJSON (RFC 7946, WGS84, FeatureCollection, [lon, lat])

Гарантирует:
- Атомарность записи файлов (через временный файл и os.replace)
- Отсутствие побочных эффектов (не меняет project.is_modified, UndoManager, выборки)
- Корректный учет скоупов (All, Selected, Visible)
- Поддержку больших наборов данных (до 100 000 точек без утечек памяти)
"""
from __future__ import annotations


from collections.abc import Iterable
import csv
import json
import logging
import math
import os
from pathlib import Path
from typing import Any
import uuid

import openpyxl
from openpyxl.styles import Font

from rme_mapper.models.map_point import MapPoint
from rme_mapper.models.object_export import (
    EXPORT_FIELDS,
    EXPORT_FIELDS_BY_KEY,
    CsvDelimiter,
    ObjectExportFormat,
    ObjectExportOptions,
    ObjectExportScope,
)
from rme_mapper.services.coordinate_service import CoordinateService

logger = logging.getLogger("rme_mapper.services.object_export")


def format_lat_dms(lat: float) -> str:
    """Каноническое форматирование широты в градусы, минуты и секунды (DD°MM'SS.SSS" N/S)."""
    if lat is None or not isinstance(lat, (int, float)) or math.isnan(lat) or math.isinf(lat):
        return ""
    hemi = "N" if lat >= 0 else "S"
    abs_lat = abs(lat)
    deg = int(abs_lat)
    rem = (abs_lat - deg) * 60.0
    mn = int(rem)
    sec = round((rem - mn) * 60.0, 3)
    if sec >= 60.0:
        sec = 0.0
        mn += 1
    if mn >= 60:
        mn = 0
        deg += 1
    return f"{deg:02d}°{mn:02d}'{sec:06.3f}\" {hemi}"


def format_lon_dms(lon: float) -> str:
    """Каноническое форматирование долготы в градусы, минуты и секунды (DDD°MM'SS.SSS" E/W)."""
    if lon is None or not isinstance(lon, (int, float)) or math.isnan(lon) or math.isinf(lon):
        return ""
    hemi = "E" if lon >= 0 else "W"
    abs_lon = abs(lon)
    deg = int(abs_lon)
    rem = (abs_lon - deg) * 60.0
    mn = int(rem)
    sec = round((rem - mn) * 60.0, 3)
    if sec >= 60.0:
        sec = 0.0
        mn += 1
    if mn >= 60:
        mn = 0
        deg += 1
    return f"{deg:03d}°{mn:02d}'{sec:06.3f}\" {hemi}"


class ObjectExportService:
    """Сервис экспорта объектов в форматы CSV, XLSX, TXT, GeoJSON."""

    @staticmethod
    def filter_points(
        points: Iterable[MapPoint],
        scope: ObjectExportScope,
        selected_ids: set[str] | list[str] | None = None,
        group_service: Any = None,
    ) -> list[MapPoint]:
        """Фильтрация точек согласно заданной области видимости (scope).

        - ALL: все точки проекта
        - SELECTED: только точки с id из selected_ids
        - VISIBLE: только точки с эффективной видимостью (point.visible AND group.visible)
        """
        all_pts = list(points)
        if scope == ObjectExportScope.ALL:
            return all_pts

        if scope == ObjectExportScope.SELECTED:
            sel_set = set(selected_ids or [])
            return [p for p in all_pts if p.id in sel_set]

        if scope == ObjectExportScope.VISIBLE:
            visible_pts: list[MapPoint] = []
            for p in all_pts:
                if not p.visible:
                    continue
                # Проверка видимости родительской группы
                if p.group_id and group_service:
                    grp = group_service.get_group(p.group_id)
                    if grp and not grp.visible:
                        continue
                visible_pts.append(p)
            return visible_pts

        return all_pts

    @classmethod
    def build_export_record(
        cls,
        point: MapPoint,
        options: ObjectExportOptions,
        group_service: Any = None,
    ) -> dict[str, Any]:
        """Построение словаря канонических значений атрибутов для одной точки."""
        # 1. Группа объекта
        group_name = ""
        if point.group_id and group_service:
            grp = group_service.get_group(point.group_id)
            if grp:
                group_name = grp.name

        # 2. Базовые координаты WGS84
        if point.latitude is None or math.isnan(point.latitude) or math.isinf(point.latitude):
            lat_dd = None
        else:
            lat_dd = round(point.latitude, options.dd_precision)

        if point.longitude is None or math.isnan(point.longitude) or math.isinf(point.longitude):
            lon_dd = None
        else:
            lon_dd = round(point.longitude, options.dd_precision)

        # 3. Спроецированные координаты (X/Y)
        x_val: float | None = None
        y_val: float | None = None
        target_crs_str = (options.target_crs or "").strip()
        needs_xy = any(k in options.field_keys for k in ("x", "y", "crs"))

        if target_crs_str:
            try:
                tx, ty = CoordinateService.transform_xy(
                    point.longitude,
                    point.latitude,
                    source_crs="EPSG:4326",
                    target_crs=target_crs_str,
                )
                x_val = round(tx, options.projected_precision)
                y_val = round(ty, options.projected_precision)
            except Exception as e:
                logger.error("Ошибка проецирования точки %s в %s: %s", point.id, target_crs_str, e)
                if any(k in options.field_keys for k in ("x", "y")):
                    raise ValueError(
                        f"Не удалось преобразовать координаты точки '{point.name or point.id}' в целевую CRS '{target_crs_str}': {e}"
                    ) from e
                x_val = None
                y_val = None

        # 4. Форматирование цветов (#RRGGBB)
        marker_fill = f"#{point.red:02X}{point.green:02X}{point.blue:02X}"
        marker_stroke = f"#{point.stroke_red:02X}{point.stroke_green:02X}{point.stroke_blue:02X}"
        zone_fill = f"#{point.zone_red:02X}{point.zone_green:02X}{point.zone_blue:02X}"
        zone_border = f"#{point.zone_border_red:02X}{point.zone_border_green:02X}{point.zone_border_blue:02X}"

        record: dict[str, Any] = {
            "object_number": point.object_number or "",
            "name": point.name or "",
            "category": point.category or "",
            "group": group_name,
            "description": point.description or "",
            "visible": point.visible,
            "latitude": lat_dd,
            "longitude": lon_dd,
            "lat_dms": format_lat_dms(point.latitude),
            "lon_dms": format_lon_dms(point.longitude),
            "x": x_val,
            "y": y_val,
            "crs": target_crs_str if (x_val is not None and y_val is not None) else "",
            "marker_shape": point.symbol,
            "marker_size": float(point.size),
            "marker_fill_color": marker_fill,
            "marker_stroke_color": marker_stroke,
            "marker_stroke_width": float(point.stroke_width),
            "marker_opacity_percent": int(point.opacity),
            "zone_enabled": bool(point.zone_enabled),
            "zone_radius_m": float(point.radius_m),
            "zone_fill_color": zone_fill,
            "zone_opacity_percent": int(point.zone_opacity),
            "zone_border_color": zone_border,
            "zone_border_width": float(point.zone_border_width),
            "zone_border_style": point.zone_border_style or "solid",
            "internal_id": point.id,
        }

        return record

    @classmethod
    def export_points(
        cls,
        points: Iterable[MapPoint],
        options: ObjectExportOptions,
        output_path: str | Path,
        selected_ids: set[str] | list[str] | None = None,
        group_service: Any = None,
    ) -> int:
        """Главный метод экспорта точек в целевой файл согласно опциям.

        Возвращает количество успешно экспортированных объектов.
        Гарантирует атомарную запись: при любой ошибке целевой файл не повреждается.
        """
        # Валидация Target CRS при запросе спроецированных координат (X/Y) или CRS
        needs_projected = any(k in options.field_keys for k in ("x", "y", "crs"))
        if needs_projected:
            target_crs_str = (options.target_crs or "").strip()
            if not target_crs_str:
                raise ValueError("Целевая система координат (Target CRS) не указана для экспорта координат X/Y.")
            try:
                import pyproj
                crs_obj = pyproj.CRS.from_user_input(target_crs_str)
                _ = pyproj.Transformer.from_crs("EPSG:4326", crs_obj, always_xy=True)
            except Exception as err:
                raise ValueError(
                    f"Недопустимая целевая система координат (Target CRS): '{target_crs_str}'. Ошибка: {err}"
                ) from err

        filtered_points = cls.filter_points(
            points,
            options.scope,
            selected_ids=selected_ids,
            group_service=group_service,
        )

        target_file = Path(output_path).resolve()
        target_file.parent.mkdir(parents=True, exist_ok=True)

        fmt = options.format
        if fmt == ObjectExportFormat.CSV:
            return cls._export_delimited(
                filtered_points,
                options,
                target_file,
                delimiter=options.delimiter.value,
                group_service=group_service,
            )
        elif fmt == ObjectExportFormat.TXT:
            # Для TXT поддерживаются табуляция (Tab) и точка с запятой (Semicolon)
            delimit = options.delimiter.value if options.delimiter in (CsvDelimiter.SEMICOLON, CsvDelimiter.TAB) else "\t"
            return cls._export_delimited(
                filtered_points,
                options,
                target_file,
                delimiter=delimit,
                group_service=group_service,
            )
        elif fmt == ObjectExportFormat.XLSX:
            return cls._export_xlsx(
                filtered_points,
                options,
                target_file,
                group_service=group_service,
            )
        elif fmt == ObjectExportFormat.GEOJSON:
            return cls._export_geojson(
                filtered_points,
                options,
                target_file,
                group_service=group_service,
            )
        else:
            raise ValueError(f"Неподдерживаемый формат экспорта: {fmt}")

    @classmethod
    def _export_delimited(
        cls,
        points: list[MapPoint],
        options: ObjectExportOptions,
        target_path: Path,
        delimiter: str,
        group_service: Any = None,
    ) -> int:
        """Потоковый экспорт в CSV / TXT с поддержкой BOM и экранирования."""
        fields = [k for k in options.field_keys if k in EXPORT_FIELDS_BY_KEY]
        if options.include_internal_id and "internal_id" not in fields:
            fields.append("internal_id")

        encoding = "utf-8-sig" if options.utf8_bom else "utf-8"
        tmp_path = target_path.with_name(f".{target_path.name}.tmp_{uuid.uuid4().hex[:8]}")

        try:
            with open(tmp_path, "w", newline="", encoding=encoding) as f:
                writer = csv.writer(f, delimiter=delimiter, quoting=csv.QUOTE_MINIMAL, lineterminator="\r\n")
                if options.include_headers:
                    writer.writerow(fields)

                for p in points:
                    rec = cls.build_export_record(p, options, group_service=group_service)
                    row: list[Any] = []
                    for k in fields:
                        val = rec.get(k)
                        if val is None:
                            row.append("")
                        elif isinstance(val, bool):
                            row.append("true" if val else "false")
                        else:
                            row.append(str(val))
                    writer.writerow(row)

            os.replace(tmp_path, target_path)
            return len(points)
        except Exception as e:
            if tmp_path.exists():
                tmp_path.unlink(missing_ok=True)
            logger.exception("Ошибка при экспорте в CSV/TXT: %s", e)
            raise

    @classmethod
    def _export_xlsx(
        cls,
        points: list[MapPoint],
        options: ObjectExportOptions,
        target_path: Path,
        group_service: Any = None,
    ) -> int:
        """Потоковый экспорт в XLSX (write_only=True) с листом 'Objects', стилями заголовков и защитой строк."""
        fields = [k for k in options.field_keys if k in EXPORT_FIELDS_BY_KEY]
        if options.include_internal_id and "internal_id" not in fields:
            fields.append("internal_id")

        wb = openpyxl.Workbook(write_only=True)
        ws = None
        tmp_path = target_path.with_name(f".{target_path.name}.tmp_{uuid.uuid4().hex[:8]}")
        try:
            ws = wb.create_sheet(title="Objects")
            header_font = Font(bold=True)

            if options.include_headers:
                header_cells: list[Any] = []
                for field_key in fields:
                    cell = openpyxl.cell.WriteOnlyCell(ws, value=field_key)
                    cell.font = header_font
                    header_cells.append(cell)
                ws.append(header_cells)

            for p in points:
                rec = cls.build_export_record(p, options, group_service=group_service)
                row: list[Any] = []
                for field_key in fields:
                    val = rec.get(field_key)
                    if field_key == "object_number":
                        # Защита ведущих нулей: строго строковая ячейка
                        c = openpyxl.cell.WriteOnlyCell(ws, value=str(val) if val is not None else "")
                        row.append(c)
                    elif val is None:
                        row.append("")
                    elif isinstance(val, bool):
                        row.append(val)
                    elif isinstance(val, (int, float)):
                        if math.isnan(val) or math.isinf(val):
                            row.append("")
                        else:
                            row.append(val)
                    else:
                        row.append(str(val))
                ws.append(row)

            wb.save(tmp_path)
            wb.close()
            os.replace(tmp_path, target_path)
            return len(points)
        except Exception as e:
            if ws is not None:
                try:
                    ws.close()
                except Exception:
                    pass
            try:
                wb.close()
            except Exception:
                pass
            if tmp_path.exists():
                tmp_path.unlink(missing_ok=True)
            logger.exception("Ошибка при экспорте в XLSX: %s", e)
            raise

    @classmethod
    def _export_geojson(
        cls,
        points: list[MapPoint],
        options: ObjectExportOptions,
        target_path: Path,
        group_service: Any = None,
    ) -> int:
        """Потоковый экспорт в GeoJSON согласно стандарту RFC 7946 (WGS84, [lon, lat]).

        Использует построчную потоковую сериализацию без удержания в оперативной
        памяти сотен тысяч Feature-объектов одновременно.
        """
        fields = [k for k in options.field_keys if k in EXPORT_FIELDS_BY_KEY]
        if options.include_internal_id and "internal_id" not in fields:
            fields.append("internal_id")

        tmp_path = target_path.with_name(f".{target_path.name}.tmp_{uuid.uuid4().hex[:8]}")
        try:
            exported_count = 0
            with open(tmp_path, "w", encoding="utf-8") as f:
                f.write('{\n  "type": "FeatureCollection",\n  "features": [\n')
                first = True

                for p in points:
                    lon = p.longitude
                    lat = p.latitude

                    # Проверка на NaN / Infinity перед сериализацией геометрии
                    if (
                        lon is None
                        or lat is None
                        or not isinstance(lon, (int, float))
                        or not isinstance(lat, (int, float))
                        or math.isnan(lon)
                        or math.isinf(lon)
                        or math.isnan(lat)
                        or math.isinf(lat)
                    ):
                        logger.warning("Пропуск точки с некорректными координатами (NaN/Inf): %s", p.id)
                        continue

                    rec = cls.build_export_record(p, options, group_service=group_service)

                    lon = round(lon, options.dd_precision)
                    lat = round(lat, options.dd_precision)

                    props: dict[str, Any] = {}
                    for k in fields:
                        val = rec.get(k)
                        if isinstance(val, float) and (math.isnan(val) or math.isinf(val)):
                            val = None
                        props[k] = val

                    feat: dict[str, Any] = {
                        "type": "Feature",
                        "geometry": {
                            "type": "Point",
                            "coordinates": [lon, lat],
                        },
                        "properties": props,
                    }
                    if options.include_internal_id or "internal_id" in fields:
                        feat["id"] = p.id

                    feat_json = json.dumps(feat, ensure_ascii=False, allow_nan=False)
                    if not first:
                        f.write(",\n")
                    f.write("    " + feat_json)
                    first = False
                    exported_count += 1

                f.write("\n  ]\n}\n")

            os.replace(tmp_path, target_path)
            return exported_count
        except Exception as e:
            if tmp_path.exists():
                tmp_path.unlink(missing_ok=True)
            logger.exception("Ошибка при экспорте в GeoJSON: %s", e)
            raise
