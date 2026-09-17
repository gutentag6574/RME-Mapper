"""Сервис сохранения, загрузки и валидации проектов RME-Mapper (*.rmeproject)."""

import json
import logging
import os
from pathlib import Path
from typing import Any
from uuid import uuid4

from rme_mapper.coordinates.validator import CoordinateValidator
from rme_mapper.models.map_layer import MapLayer
from rme_mapper.models.map_point import MapPoint
from rme_mapper.models.point_style import StyleValidator
from rme_mapper.models.project_data import (
    ProjectData,
    ProjectMapData,
    ProjectPointData,
)

logger = logging.getLogger("rme_mapper.services.project")

SUPPORTED_FORMAT = "RME-Mapper Project"
CURRENT_VERSION = 1
PROJECT_EXTENSION = ".rmeproject"


class ProjectService:
    """Сервис сериализации, десериализации и атомарной записи проектов."""

    @staticmethod
    def save_project(project: ProjectData, file_path: Path | str) -> Path:
        """Атомарное сохранение данных проекта в файл *.rmeproject.

        Запись сначала ведется во временный файл в том же каталоге,
        после чего выполняется атомарное замещение целевого файла (os.replace).
        Это предотвращает повреждение старого файла проекта при сбоях записи.
        """
        target = Path(file_path)
        if target.suffix.lower() != PROJECT_EXTENSION:
            target = target.with_suffix(PROJECT_EXTENSION)

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
        if fmt != SUPPORTED_FORMAT:
            raise ValueError(
                f"Неподдерживаемый формат проекта: '{fmt}'. "
                f"Ожидается '{SUPPORTED_FORMAT}'."
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
                f"Проект создан более новой версией RME-Mapper (версия {ver_int}, поддерживается {CURRENT_VERSION})."
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
        map_path: Path | str,
        layers: list[MapLayer],
        points: list[MapPoint],
        map_id: str = "mari_el",
    ) -> ProjectData:
        """Сборка модели ProjectData из текущего состояния приложения."""
        # Относительный путь к карте
        path_obj = Path(map_path)
        try:
            rel_path = path_obj.as_posix()
            # Если путь абсолютный, пытаемся сделать относительным
            if "maps/" in rel_path:
                rel_path = "maps/" + rel_path.split("maps/", 1)[1]
        except Exception:
            rel_path = "maps/test_map/prepared/mari.gpkg"

        map_data = ProjectMapData(
            map_id=map_id,
            relative_path=rel_path,
        )

        layers_state = {layer.id: layer.visible for layer in layers}
        points_data = [ProjectPointData.from_map_point(p) for p in points]

        return ProjectData(
            format=SUPPORTED_FORMAT,
            version=CURRENT_VERSION,
            map=map_data,
            layers=layers_state,
            points=points_data,
        )
