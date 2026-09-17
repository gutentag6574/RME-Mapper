"""Сервис сохранения, загрузки и валидации проектов GeoPoint Mapper (*.gpmap, *.rmeproject)."""

import json
import logging
import os
from pathlib import Path
from typing import Any
from uuid import uuid4

from rme_mapper.coordinates.validator import CoordinateValidator
from rme_mapper.maps.map_config import get_project_root
from rme_mapper.models.map_layer import MapLayer
from rme_mapper.models.map_point import MapPoint
from rme_mapper.models.point_style import StyleValidator
from rme_mapper.models.project_data import (
    PRIMARY_PROJECT_FORMAT,
    LEGACY_PROJECT_FORMAT,
    SUPPORTED_PROJECT_FORMATS,
    ProjectData,
    ProjectMapData,
    ProjectPointData,
)

logger = logging.getLogger("rme_mapper.services.project")

PRIMARY_FORMAT = PRIMARY_PROJECT_FORMAT
LEGACY_FORMAT = LEGACY_PROJECT_FORMAT
SUPPORTED_FORMATS = SUPPORTED_PROJECT_FORMATS
CURRENT_VERSION = 1
PRIMARY_EXTENSION = ".gpmap"
LEGACY_EXTENSION = ".rmeproject"
SUPPORTED_EXTENSIONS = {PRIMARY_EXTENSION, LEGACY_EXTENSION}

# Для обратной совместимости
SUPPORTED_FORMAT = PRIMARY_FORMAT
PROJECT_EXTENSION = PRIMARY_EXTENSION


class ProjectService:
    """Сервис сериализации, десериализации и атомарной записи проектов."""

    @staticmethod
    def save_project(project: ProjectData, file_path: Path | str) -> Path:
        """Атомарное сохранение данных проекта в файл *.gpmap или *.rmeproject.

        Запись сначала ведется во временный файл в том же каталоге,
        после чего выполняется атомарное замещение целевого файла (os.replace).
        Это предотвращает повреждение старого файла проекта при сбоях записи.
        """
        target = Path(file_path)
        if target.suffix.lower() not in SUPPORTED_EXTENSIONS:
            target = target.with_suffix(PRIMARY_EXTENSION)

        target.parent.mkdir(parents=True, exist_ok=True)

        # Подготовка читаемого JSON в кодировке UTF-8
        data_dict = project.to_dict()
        json_content = json.dumps(data_dict, ensure_ascii=False, indent=2)

        tmp_path = target.with_name(f"{target.name}.tmp_{uuid4().hex[:8]}")
        try:
            with open(tmp_path, "w", encoding="utf-8") as f:
                f.write(json_content)
                f.flush()
                os.fsync(f.fileno())

            # Атомарное перемещение
            os.replace(tmp_path, target)
            logger.info("Проект успешно сохранен в: %s (%d точек)", target, len(project.points))
            return target
        except Exception as e:
            logger.exception("Ошибка при сохранении проекта в %s: %s", target, e)
            if tmp_path.exists():
                try:
                    tmp_path.unlink()
                except OSError:
                    pass
            raise

    @staticmethod
    def load_project(file_path: Path | str) -> ProjectData:
        """Загрузка, проверка формата и валидация проекта из файла *.rmeproject."""
        target = Path(file_path)
        if not target.exists():
            raise FileNotFoundError(f"Файл проекта не найден: {target}")

        if not target.is_file():
            raise ValueError(f"Указанный путь не является файлом: {target}")

        logger.info("Чтение проекта из: %s", target)
        try:
            with open(target, "r", encoding="utf-8") as f:
                raw_data = json.load(f)
        except json.JSONDecodeError as json_err:
            logger.error("Ошибка парсинга JSON в файле проекта %s: %s", target, json_err)
            raise ValueError(f"Файл проекта поврежден (некорректный JSON):\n{json_err}") from json_err

        if not isinstance(raw_data, dict):
            raise ValueError("Корневой элемент файла проекта должен быть JSON-объектом.")

        fmt = raw_data.get("format")
        if fmt not in SUPPORTED_FORMATS:
            raise ValueError(
                f"Неподдерживаемый формат проекта: '{fmt}'. "
                f"Ожидается '{PRIMARY_FORMAT}' или '{LEGACY_FORMAT}'."
            )

        ver = raw_data.get("version")
        if ver is None:
            raise ValueError("В файле проекта отсутствует обязательное поле 'version'.")

        try:
            ver_int = int(ver)
        except (ValueError, TypeError):
            raise ValueError(f"Некорректная версия проекта: '{ver}'. Ожидается целое число.")

        if ver_int > CURRENT_VERSION:
            raise ValueError(
                f"Проект создан более новой версией программы (версия {ver_int}, поддерживается {CURRENT_VERSION})."
            )

        # Валидация и парсинг точек
        validated_points: list[ProjectPointData] = []
        raw_points = raw_data.get("points", [])
        if isinstance(raw_points, list):
            for idx, pt_dict in enumerate(raw_points):
                if not isinstance(pt_dict, dict):
                    logger.warning("Точка №%d имеет неверный формат (не словарь), пропущена", idx + 1)
                    continue

                try:
                    # Валидация обязательных координат
                    lat = float(pt_dict["latitude"])
                    lon = float(pt_dict["longitude"])
                    CoordinateValidator.validate_latitude(lat)
                    CoordinateValidator.validate_longitude(lon)

                    # Валидация стиля
                    sym = StyleValidator.validate_symbol(str(pt_dict.get("symbol", "circle")))
                    size = StyleValidator.validate_size(pt_dict.get("size", 12.0))
                    r, g, b = StyleValidator.validate_rgb(
                        pt_dict.get("red", 220),
                        pt_dict.get("green", 30),
                        pt_dict.get("blue", 30),
                    )

                    # Валидация параметров зоны
                    zone_en = bool(pt_dict.get("zone_enabled", False))
                    rad_m = StyleValidator.validate_radius(
                        pt_dict.get("radius_m", 0.0),
                        enabled=zone_en,
                    )
                    zr, zg, zb = StyleValidator.validate_rgb(
                        pt_dict.get("zone_red", 220),
                        pt_dict.get("zone_green", 30),
                        pt_dict.get("zone_blue", 30),
                    )
                    opacity = StyleValidator.validate_opacity(pt_dict.get("zone_opacity", 30))

                    pt_data = ProjectPointData(
                        id=str(pt_dict.get("id", uuid4().hex)),
                        name=str(pt_dict.get("name", "")),
                        latitude=lat,
                        longitude=lon,
                        source_crs=str(pt_dict.get("source_crs", "OGC:CRS84")),
                        visible=bool(pt_dict.get("visible", True)),
                        symbol=sym,
                        size=size,
                        red=r,
                        green=g,
                        blue=b,
                        zone_enabled=zone_en,
                        radius_m=rad_m,
                        zone_red=zr,
                        zone_green=zg,
                        zone_blue=zb,
                        zone_opacity=opacity,
                    )
                    validated_points.append(pt_data)
                except Exception as pt_err:
                    logger.warning("Ошибка валидации точки №%d в проекте: %s (пропущена)", idx + 1, pt_err)
                    continue

        map_dict = raw_data.get("map")
        map_data = ProjectMapData.from_dict(map_dict)

        layers_dict: dict[str, bool] = {}
        raw_layers = raw_data.get("layers", {})
        if isinstance(raw_layers, dict):
            for k, v in raw_layers.items():
                layers_dict[str(k)] = bool(v)

        project = ProjectData(
            format=fmt,
            version=ver_int,
            map=map_data,
            layers=layers_dict,
            points=validated_points,
        )
        logger.info(
            "Проект успешно загружен: %d валидных точек, слоев: %s",
            len(project.points),
            list(project.layers.keys()),
        )
        return project

    @staticmethod
    def build_project_data(
        map_path: Path | str | None = None,
        layers: list[MapLayer] | None = None,
        points: list[MapPoint] | None = None,
        map_id: str = "",
        map_name: str = "",
        source_type: str = "geopackage",
        crs: str | None = None,
        boundary_layer: str | None = None,
        map_profile: Any = None,
    ) -> ProjectData:
        """Сборка модели ProjectData из текущего состояния приложения."""
        if map_profile is not None:
            if not map_id:
                map_id = getattr(map_profile, "id", "")
            if not map_name:
                map_name = getattr(map_profile, "name", "")
            if not crs:
                crs = getattr(map_profile, "crs", None)
            if not boundary_layer:
                boundary_layer = getattr(map_profile, "boundary_layer", None)
            source_type = getattr(map_profile, "source_type", "geopackage")
            if not map_path:
                map_path = map_profile.get_absolute_source_path()

        rel_path = ""
        if map_path:
            path_obj = Path(map_path)
            posix_str = path_obj.as_posix()
            if "maps/" in posix_str:
                rel_path = "maps/" + posix_str.split("maps/", 1)[1]
            else:
                try:
                    root = get_project_root().resolve()
                    resolved = path_obj.resolve()
                    try:
                        rel_path = resolved.relative_to(root).as_posix()
                    except ValueError:
                        rel_path = resolved.as_posix()
                except Exception:
                    rel_path = str(map_path)

        profile_layers_meta: list[dict[str, Any]] = []
        if map_profile and getattr(map_profile, "layers", None):
            profile_layers_meta = [dict(l) for l in map_profile.layers]

        map_data = ProjectMapData(
            map_id=map_id,
            relative_path=rel_path,
            name=map_name,
            source_type=source_type,
            crs=crs,
            boundary_layer=boundary_layer,
            layers=profile_layers_meta,
        )

        layers_state = {layer.id: layer.visible for layer in (layers or [])}
        points_data = [ProjectPointData.from_map_point(p) for p in (points or [])]

        return ProjectData(
            format=PRIMARY_FORMAT,
            version=CURRENT_VERSION,
            map=map_data,
            layers=layers_state,
            points=points_data,
        )
