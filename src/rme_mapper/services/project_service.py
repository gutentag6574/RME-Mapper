"""Сервис сохранения, загрузки и валидации проектов GeoPoint Mapper (*.gpmap, *.rmeproject)."""
from __future__ import annotations


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
from rme_mapper.models.object_group import ObjectGroup
from rme_mapper.models.point_style import StyleValidator
from rme_mapper.models.project_data import (
    PRIMARY_PROJECT_FORMAT,
    LEGACY_PROJECT_FORMAT,
    SUPPORTED_PROJECT_FORMATS,
    ProjectData,
    ProjectGroupData,
    ProjectMapData,
    ProjectPointData,
)

logger = logging.getLogger("rme_mapper.services.project")

PRIMARY_FORMAT = PRIMARY_PROJECT_FORMAT
LEGACY_FORMAT = LEGACY_PROJECT_FORMAT
SUPPORTED_FORMATS = SUPPORTED_PROJECT_FORMATS
CURRENT_VERSION = 1
MAX_SUPPORTED_VERSION = 2
SUPPORTED_VERSIONS = {1, 2}
PRIMARY_EXTENSION = ".gpmap"
LEGACY_EXTENSION = ".rmeproject"
SUPPORTED_EXTENSIONS = {PRIMARY_EXTENSION, LEGACY_EXTENSION}

# Для обратной совместимости
SUPPORTED_FORMAT = PRIMARY_FORMAT
PROJECT_EXTENSION = PRIMARY_EXTENSION


MAX_PROJECT_FILE_SIZE = 128 * 1024 * 1024  # 128 MB (supports up to 100,000 points JSON)
MAX_PROJECT_POINTS = 100_000


class ProjectService:
    """Сервис сериализации, десериализации и атомарной записи проектов."""

    MAX_FILE_SIZE = MAX_PROJECT_FILE_SIZE
    MAX_POINTS = MAX_PROJECT_POINTS

    @staticmethod
    def get_recovery_snapshot_path() -> Path:
        """Путь к файлу аварийного восстановления."""
        base = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA")
        if base:
            return Path(base) / "GeoPointMapper" / "recovery_snapshot.json"
        return Path.home() / ".geopoint_mapper" / "recovery_snapshot.json"

    @classmethod
    def has_recovery_snapshot(cls, snapshot_path: Path | str | None = None) -> bool:
        """Проверить наличие файла аварийного восстановления."""
        p = Path(snapshot_path) if snapshot_path else cls.get_recovery_snapshot_path()
        return p.is_file() and p.stat().st_size > 0

    @classmethod
    def save_recovery_snapshot(
        cls,
        project: ProjectData,
        current_project_path: str | None = None,
        snapshot_path: Path | str | None = None,
    ) -> Path:
        """Сохранить снимок текущего проекта в файл аварийного восстановления."""
        import time

        p = Path(snapshot_path) if snapshot_path else cls.get_recovery_snapshot_path()
        p.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": 1,
            "timestamp": time.time(),
            "current_project_path": current_project_path,
            "project": project.to_dict(),
        }
        tmp_p = p.with_name(f"{p.name}.tmp_{uuid4().hex[:8]}")
        content = json.dumps(payload, ensure_ascii=False, indent=2)
        try:
            with open(tmp_p, "w", encoding="utf-8") as f:
                f.write(content)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_p, p)
            logger.debug("Аварийный снимок успешно сохранен: %s", p)
            return p
        except Exception as e:
            logger.warning("Ошибка при записи аварийного снимка %s: %s", p, e)
            if tmp_p.exists():
                try:
                    tmp_p.unlink()
                except OSError:
                    pass
            raise

    @classmethod
    def load_recovery_snapshot(
        cls,
        snapshot_path: Path | str | None = None,
    ) -> tuple[ProjectData, str | None]:
        """Загрузить проект и путь из аварийного снимка."""
        p = Path(snapshot_path) if snapshot_path else cls.get_recovery_snapshot_path()
        if not p.exists():
            raise FileNotFoundError(f"Файл аварийного восстановления не найден: {p}")

        if p.stat().st_size > cls.MAX_FILE_SIZE:
            raise ValueError("Размер аварийного снимка превышает допустимый предел.")

        try:
            with open(p, "r", encoding="utf-8") as f:
                data = json.load(f)
        except json.JSONDecodeError as json_err:
            logger.error("Ошибка парсинга JSON аварийного снимка %s: %s", p, json_err)
            raise ValueError(f"Снимок аварийного восстановления поврежден:\n{json_err}") from json_err

        if not isinstance(data, dict):
            raise ValueError("Некорректная структура аварийного снимка (ожидается dict).")

        raw_proj = data.get("project")
        if not isinstance(raw_proj, dict):
            raise ValueError("Аварийный снимок не содержит данных проекта.")

        project = cls._parse_project_dict(raw_proj)
        proj_path = data.get("current_project_path")
        return project, str(proj_path) if proj_path else None

    @classmethod
    def clear_recovery_snapshot(cls, snapshot_path: Path | str | None = None) -> None:
        """Удалить файл аварийного восстановления."""
        p = Path(snapshot_path) if snapshot_path else cls.get_recovery_snapshot_path()
        if p.exists():
            try:
                p.unlink()
                logger.debug("Аварийный снимок удален: %s", p)
            except OSError as e:
                logger.warning("Не удалось удалить аварийный снимок %s: %s", p, e)

    @staticmethod
    def save_project(
        project: ProjectData,
        file_path: Path | str,
        create_backup: bool = True,
    ) -> Path:
        """Атомарное сохранение данных проекта в файл *.gpmap или *.rmeproject.

        Если целевой файл уже существует и create_backup=True, создается копия *.bak.
        Запись сначала ведется во временный файл в том же каталоге,
        после чего выполняется атомарное замещение целевого файла (os.replace).
        Это предотвращает повреждение старого файла проекта при сбоях записи.
        """
        import shutil

        target = Path(file_path)
        if target.suffix.lower() not in SUPPORTED_EXTENSIONS:
            target = target.with_suffix(PRIMARY_EXTENSION)

        target.parent.mkdir(parents=True, exist_ok=True)

        # Создание резервной копии перед перезаписью существующего файла
        if target.exists() and create_backup:
            bak_path = target.with_name(f"{target.name}.bak")
            try:
                shutil.copy2(target, bak_path)
                logger.info("Создана резервная копия проекта: %s", bak_path)
            except Exception as bak_err:
                logger.warning("Не удалось создать резервную копию %s: %s", target, bak_err)

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

    @classmethod
    def load_project(cls, file_path: Path | str) -> ProjectData:
        """Загрузка, проверка формата и валидация проекта из файла *.gpmap / *.rmeproject."""
        target = Path(file_path)
        if not target.exists():
            raise FileNotFoundError(f"Файл проекта не найден: {target}")

        if not target.is_file():
            raise ValueError(f"Указанный путь не является файлом: {target}")

        if target.stat().st_size > cls.MAX_FILE_SIZE:
            raise ValueError(
                f"Размер файла проекта превышает допустимый предел ({cls.MAX_FILE_SIZE // (1024*1024)} МБ, базовый лимит 50 МБ): {target}"
            )

        logger.info("Чтение проекта из: %s", target)
        try:
            with open(target, "r", encoding="utf-8") as f:
                raw_data = json.load(f)
        except json.JSONDecodeError as json_err:
            logger.error("Ошибка парсинга JSON в файле проекта %s: %s", target, json_err)
            raise ValueError(f"Файл проекта поврежден (некорректный JSON):\n{json_err}") from json_err

        return cls._parse_project_dict(raw_data)

    @classmethod
    def _parse_project_dict(cls, raw_data: dict) -> ProjectData:
        """Внутренняя валидация и сборка ProjectData из словаря."""
        if not isinstance(raw_data, dict):
            raise ValueError("Корневой элемент данных проекта должен быть JSON-объектом.")

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

        if ver_int > MAX_SUPPORTED_VERSION:
            raise ValueError(
                f"Проект создан более новой версией программы (версия {ver_int}, поддерживается {MAX_SUPPORTED_VERSION})."
            )

        # Валидация и парсинг точек
        validated_points: list[ProjectPointData] = []
        raw_points = raw_data.get("points", [])
        # Парсинг групп проекта
        raw_groups = raw_data.get("groups", [])
        validated_groups: list[ProjectGroupData] = []
        seen_group_ids: set[str] = set()
        if isinstance(raw_groups, list):
            for g_idx, grp_item in enumerate(raw_groups):
                if not isinstance(grp_item, dict):
                    logger.warning("Группа №%d имеет неверный формат (не словарь), пропущена", g_idx + 1)
                    continue
                gid = str(grp_item.get("id") or uuid4().hex)
                gname = str(grp_item.get("name") or "").strip()
                if not gname:
                    logger.warning("Группа №%d имеет пустое название, пропущена", g_idx + 1)
                    continue
                if gid in seen_group_ids:
                    # Детерминированная безопасность: первая группа сохраняет оригинальный ID;
                    # последующим дубликатам генерируется новый UUID, чтобы они не перехватывали чужие точки.
                    logger.warning("duplicate_group_id: группа '%s' имеет дублирующийся ID '%s', сгенерирован новый", gname, gid)
                    gid = uuid4().hex
                seen_group_ids.add(gid)
                gdesc = str(grp_item.get("description") or "")
                gvis = bool(grp_item.get("visible", True))
                validated_groups.append(ProjectGroupData(
                    id=gid,
                    name=gname,
                    description=gdesc,
                    visible=gvis,
                ))

        valid_group_ids = {g.id for g in validated_groups}

        if not isinstance(raw_points, list):
            raw_points = []

        if len(raw_points) > cls.MAX_POINTS:
            raise ValueError(
                f"Количество точек в проекте превышает допустимый предел ({cls.MAX_POINTS})."
            )

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

                obj_num = StyleValidator.validate_object_number(pt_dict.get("object_number", ""))
                desc = StyleValidator.validate_description(pt_dict.get("description", ""))
                cat = StyleValidator.validate_category(pt_dict.get("category", ""))
                sr, sg, sb = StyleValidator.validate_rgb(
                    pt_dict.get("stroke_red", 0),
                    pt_dict.get("stroke_green", 0),
                    pt_dict.get("stroke_blue", 0),
                )
                sw = StyleValidator.validate_stroke_width(pt_dict.get("stroke_width", 1.0))
                m_op = StyleValidator.validate_opacity(pt_dict.get("opacity", pt_dict.get("marker_opacity", 100.0)))
                zbr, zbg, zbb = StyleValidator.validate_rgb(
                    pt_dict.get("zone_border_red", pt_dict.get("zone_red", 220)),
                    pt_dict.get("zone_border_green", pt_dict.get("zone_green", 30)),
                    pt_dict.get("zone_border_blue", pt_dict.get("zone_blue", 30)),
                )
                zbw = StyleValidator.validate_border_width(pt_dict.get("zone_border_width", 1.0))
                zbs = StyleValidator.validate_border_style(pt_dict.get("zone_border_style", "solid"))

                raw_gid = pt_dict.get("group_id")
                gid = str(raw_gid).strip() if raw_gid is not None and str(raw_gid).strip() else None
                if gid is not None and gid not in valid_group_ids:
                    logger.warning(
                        "orphan_group_reference: точка '%s' ссылается на несуществующую группу '%s', сброшена в Ungrouped",
                        pt_dict.get("name", ""),
                        gid,
                    )
                    gid = None

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
                    object_number=obj_num,
                    description=desc,
                    category=cat,
                    stroke_red=sr,
                    stroke_green=sg,
                    stroke_blue=sb,
                    stroke_width=sw,
                    opacity=m_op,
                    zone_border_red=zbr,
                    zone_border_green=zbg,
                    zone_border_blue=zbb,
                    zone_border_width=zbw,
                    zone_border_style=zbs,
                    group_id=gid,
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
            groups=validated_groups,
        )
        logger.info(
            "Проект успешно загружен: %d валидных точек, групп: %d, слоев: %s",
            len(project.points),
            len(project.groups),
            list(project.layers.keys()),
        )
        return project


    @staticmethod
    def build_project_data(
        map_path: Path | str | None = None,
        layers: list[MapLayer] | None = None,
        points: list[MapPoint] | None = None,
        groups: list[ObjectGroup] | None = None,
        map_id: str = "",
        map_name: str = "",
        source_type: str = "geopackage",
        crs: str | None = None,
        boundary_layer: str | None = None,
        map_profile: Any = None,
        preserve_map_data: ProjectMapData | None = None,
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
            if source_type != "online_xyz" and not map_path:
                map_path = map_profile.get_absolute_source_path()

        rel_path = ""
        if map_path and source_type != "online_xyz":
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

        provider_id = getattr(map_profile, "provider_id", None) if map_profile else None
        map_type = getattr(map_profile, "map_type", None) if map_profile else None
        affine_transform = getattr(map_profile, "affine_transform", None) if map_profile else None
        control_points = getattr(map_profile, "control_points", None) if map_profile else None
        transformation_type = getattr(map_profile, "transformation_type", "affine") if map_profile else "affine"

        if map_profile is None and not map_path and not map_id and preserve_map_data is not None:
            map_data = preserve_map_data
        else:
            map_data = ProjectMapData(
                map_id=map_id,
                relative_path=rel_path,
                name=map_name,
                source_type=source_type,
                crs=crs,
                boundary_layer=boundary_layer,
                layers=profile_layers_meta,
                provider_id=provider_id,
                map_type=map_type,
                affine_transform=list(affine_transform) if affine_transform is not None else None,
                control_points=[
                    cp.to_dict() if hasattr(cp, "to_dict") else dict(cp) for cp in control_points
                ] if control_points is not None else None,
                transformation_type=transformation_type,
            )

        layers_state = {layer.id: layer.visible for layer in (layers or [])}
        points_data = [ProjectPointData.from_map_point(p) for p in (points or [])]
        groups_data = [
            ProjectGroupData(
                id=g.id,
                name=g.name,
                description=g.description,
                visible=g.visible,
            )
            for g in (groups or [])
        ]

        return ProjectData(
            format=PRIMARY_FORMAT,
            version=CURRENT_VERSION,
            map=map_data,
            layers=layers_state,
            points=points_data,
            groups=groups_data,
        )
