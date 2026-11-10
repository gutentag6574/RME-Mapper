"""Универсальная модель профиля карты (MapProfile)."""
from __future__ import annotations


from dataclasses import asdict, dataclass, field
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger("rme_mapper.models.map_profile")

SUPPORTED_SOURCE_TYPES = {"geopackage", "geotiff", "online_xyz", "georeferenced_image"}


@dataclass
class MapProfile:
    """Универсальный профиль карты, описывающий источник данных, CRS, слои и границу."""

    id: str
    name: str
    description: str | None = None

    source_type: str = "geopackage"
    source_path: str = ""
    base_dir: Path | None = None

    crs: str | None = None

    boundary_layer: str | None = None
    boundary_required: bool = False

    layers: list[dict[str, Any]] = field(default_factory=list)
    extent: dict[str, float] | None = None

    provider_id: str | None = None
    map_type: str | None = None

    # Поля для ручной геопривязки изображений (Stage 21: georeferenced_image)
    affine_transform: tuple[float, float, float, float, float, float] | list[float] | None = None
    control_points: list[dict[str, Any]] | None = None
    transformation_type: str = "affine"

    raster_overlays: list[dict[str, Any]] = field(default_factory=list)
    annotations: list[dict[str, Any]] = field(default_factory=list)

    metadata_version: int = 1

    def get_absolute_source_path(self, root_dir: Path | None = None) -> Path:
        """Получение абсолютного пути к исходному файлу данных карты.

        Разрешает относительные пути с учетом директории расположения metadata.json (base_dir)
        или корневой директории проекта.
        """
        if self.source_type == "online_xyz":
            return Path(self.source_path or "")

        p = Path(self.source_path)
        if p.is_absolute() and p.exists():
            return p

        # 1. Проверяем относительно base_dir (директории профиля карты)
        if self.base_dir is not None:
            resolved = (self.base_dir / p).resolve()
            if resolved.exists():
                return resolved

        # 2. Проверяем относительно root_dir (корня проекта)
        if root_dir is not None:
            resolved = (root_dir / p).resolve()
            if resolved.exists():
                return resolved

        # Резервный вариант: возврат пути относительно base_dir (если есть) или p
        if self.base_dir is not None:
            return (self.base_dir / p).resolve()
        return p.resolve()

    def to_dict(self) -> dict[str, Any]:
        """Преобразование профиля в словарь метаданных metadata.json."""
        source_dict: dict[str, Any] = {
            "type": self.source_type,
            "path": self.source_path,
        }
        if self.provider_id:
            source_dict["provider_id"] = self.provider_id
        if self.map_type:
            source_dict["map_type"] = self.map_type
        if self.affine_transform is not None:
            source_dict["affine_transform"] = list(self.affine_transform)
        if self.control_points is not None:
            source_dict["control_points"] = [
                cp.to_dict() if hasattr(cp, "to_dict") else dict(cp) for cp in self.control_points
            ]
        if self.transformation_type:
            source_dict["transformation_type"] = self.transformation_type

        data: dict[str, Any] = {
            "schema_version": self.metadata_version,
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "source": source_dict,
            "crs": self.crs,
            "boundary": {
                "layer": self.boundary_layer,
                "required": self.boundary_required,
            },
            "layers": [dict(layer) for layer in self.layers],
            "raster_overlays": [dict(item) for item in self.raster_overlays],
            "annotations": [dict(item) for item in self.annotations],
        }
        if self.extent is not None:
            data["extent"] = dict(self.extent)
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any], base_dir: Path | None = None) -> "MapProfile":
        """Создание экземпляра MapProfile из словаря метаданных metadata.json."""
        if not isinstance(data, dict):
            raise ValueError("Метаданные карты должны быть словарем (JSON-объектом).")

        profile_id = str(data.get("id") or data.get("map_id") or "").strip()
        if not profile_id:
            raise ValueError("В метаданных профиля карты отсутствует обязательное поле 'id'.")

        name = str(data.get("name") or profile_id).strip()
        description = data.get("description")
        if description is not None:
            description = str(description).strip()

        # Источник данных
        provider_id: str | None = None
        map_type: str | None = None
        affine_transform: tuple[float, ...] | list[float] | None = None
        control_points: list[dict[str, Any]] | None = None
        transformation_type: str = "affine"

        source_info = data.get("source")
        if isinstance(source_info, dict):
            source_type = str(source_info.get("type", "geopackage")).lower().strip()
            source_path = str(source_info.get("path") or "").strip()
            provider_id = source_info.get("provider_id")
            map_type = source_info.get("map_type")
            if "affine_transform" in source_info and isinstance(source_info["affine_transform"], (list, tuple)):
                affine_transform = tuple(float(x) for x in source_info["affine_transform"])
            if "control_points" in source_info and isinstance(source_info["control_points"], list):
                from rme_mapper.models.georeference import ControlPoint

                control_points = [
                    ControlPoint.from_dict(cp) if isinstance(cp, dict) else cp
                    for cp in source_info["control_points"]
                ]
            if "transformation_type" in source_info:
                transformation_type = str(source_info["transformation_type"])
        else:
            source_type = "geopackage"
            source_path = str(data.get("prepared_file") or data.get("source_path") or "").strip()

        if affine_transform is None and "affine_transform" in data and isinstance(data["affine_transform"], (list, tuple)):
            affine_transform = tuple(float(x) for x in data["affine_transform"])
        if control_points is None and "control_points" in data and isinstance(data["control_points"], list):
            control_points = [dict(cp) for cp in data["control_points"] if isinstance(cp, dict)]
        if "transformation_type" in data:
            transformation_type = str(data["transformation_type"])

        # Валидация поддерживаемых типов источника
        if source_type not in SUPPORTED_SOURCE_TYPES:
            logger.warning(
                "Профиль '%s' использует тип источника '%s', поддерживаются: %s",
                profile_id, source_type, SUPPORTED_SOURCE_TYPES,
            )

        # CRS
        raw_crs = data.get("crs")
        crs_str: str | None = None
        if isinstance(raw_crs, dict):
            crs_str = raw_crs.get("proj") or raw_crs.get("wkt") or raw_crs.get("layer_crs_name")
        elif raw_crs is not None:
            crs_str = str(raw_crs).strip()

        # Граница
        boundary_info = data.get("boundary")
        boundary_layer: str | None = None
        boundary_required = False
        if isinstance(boundary_info, dict):
            boundary_layer = boundary_info.get("layer")
            boundary_required = bool(boundary_info.get("required", False))
        elif boundary_info is not None:
            boundary_layer = str(boundary_info)

        # Слои
        raw_layers = data.get("layers", [])
        layers: list[dict[str, Any]] = []
        if isinstance(raw_layers, list):
            for item in raw_layers:
                if isinstance(item, dict):
                    layers.append(dict(item))

        # Охват (extent)
        raw_extent = data.get("extent")
        extent: dict[str, float] | None = None
        if isinstance(raw_extent, dict):
            try:
                extent = {
                    "xmin": float(raw_extent["xmin"]),
                    "ymin": float(raw_extent["ymin"]),
                    "xmax": float(raw_extent["xmax"]),
                    "ymax": float(raw_extent["ymax"]),
                }
            except (KeyError, ValueError, TypeError) as extent_err:
                logger.debug("Охват профиля '%s' не содержит полных координат xmin/ymin/xmax/ymax: %s", profile_id, extent_err)
                extent = None
        elif isinstance(raw_extent, (list, tuple)) and len(raw_extent) >= 4:
            extent = {
                "xmin": float(raw_extent[0]),
                "ymin": float(raw_extent[1]),
                "xmax": float(raw_extent[2]),
                "ymax": float(raw_extent[3]),
            }

        version = int(data.get("schema_version") or data.get("metadata_version") or 1)

        return cls(
            id=profile_id,
            name=name,
            description=description,
            source_type=source_type,
            source_path=source_path,
            base_dir=base_dir,
            crs=crs_str,
            boundary_layer=boundary_layer,
            boundary_required=boundary_required,
            layers=layers,
            extent=extent,
            provider_id=provider_id,
            map_type=map_type,
            affine_transform=affine_transform,
            control_points=control_points,
            transformation_type=transformation_type,
            raster_overlays=[dict(item) for item in data.get("raster_overlays", []) if isinstance(item, dict)],
            annotations=[dict(item) for item in data.get("annotations",[]) if isinstance(item,dict)],
            metadata_version=version,
        )
