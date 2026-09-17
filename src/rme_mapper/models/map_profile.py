"""Универсальная модель профиля карты (MapProfile)."""

from dataclasses import asdict, dataclass, field
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger("rme_mapper.models.map_profile")

SUPPORTED_SOURCE_TYPES = {"geopackage", "geotiff"}


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

    metadata_version: int = 1

    def get_absolute_source_path(self, root_dir: Path | None = None) -> Path:
        """Получение абсолютного пути к исходному файлу данных карты.

        Разрешает относительные пути с учетом директории расположения metadata.json (base_dir)
        или корневой директории проекта.
        """
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
        data: dict[str, Any] = {
            "schema_version": self.metadata_version,
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "source": {
                "type": self.source_type,
                "path": self.source_path,
            },
            "crs": self.crs,
            "boundary": {
                "layer": self.boundary_layer,
                "required": self.boundary_required,
            },
            "layers": [dict(layer) for layer in self.layers],
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
        source_info = data.get("source")
        if isinstance(source_info, dict):
            source_type = str(source_info.get("type", "geopackage")).lower().strip()
            source_path = str(source_info.get("path") or "").strip()
        else:
            source_type = "geopackage"
            source_path = str(data.get("prepared_file") or data.get("source_path") or "").strip()

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
            metadata_version=version,
        )
