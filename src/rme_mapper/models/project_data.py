"""Модели структуры данных проекта GeoPoint Mapper (*.gpmap, *.rmeproject)."""

from dataclasses import asdict, dataclass, field
from typing import Any
from uuid import uuid4

from rme_mapper.models.map_point import MapPoint


@dataclass
class ProjectGroupData:
    """Сериализуемые данные организационной группы объектов."""

    id: str
    name: str
    description: str = ""
    visible: bool = True

    def to_dict(self) -> dict[str, Any]:
        """Преобразование в словарь для JSON-сериализации."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "ProjectGroupData":
        """Создание экземпляра из словаря."""
        if not data or not isinstance(data, dict):
            return cls(id=uuid4().hex, name="")
        return cls(
            id=str(data.get("id") or uuid4().hex),
            name=str(data.get("name") or ""),
            description=str(data.get("description") or ""),
            visible=bool(data.get("visible", True)),
        )


@dataclass
class ProjectMapData:
    """Данные о подключенной карте проекта."""

    map_id: str = ""
    relative_path: str = ""
    name: str = ""
    source_type: str = "geopackage"
    crs: str | None = None
    boundary_layer: str | None = None
    layers: list[dict[str, Any]] = field(default_factory=list)
    provider_id: str | None = None
    map_type: str | None = None
    affine_transform: list[float] | None = None
    control_points: list[dict[str, Any]] | None = None
    transformation_type: str = "affine"

    def to_dict(self) -> dict[str, Any]:
        """Преобразование в словарь для JSON-сериализации.

        Безопасность: API-ключи и учетные данные картографических провайдеров
        НИКОГДА не сохраняются в файл проекта (*.gpmap).
        """
        res: dict[str, Any] = {
            "map_id": self.map_id,
        }
        if self.relative_path:
            res["relative_path"] = self.relative_path
        if self.name:
            res["name"] = self.name
        if self.source_type:
            res["source_type"] = self.source_type
        if self.crs:
            res["crs"] = self.crs
        if self.boundary_layer:
            res["boundary_layer"] = self.boundary_layer
        if self.layers:
            res["layers"] = [dict(l) for l in self.layers]
        if self.provider_id:
            res["provider_id"] = self.provider_id
        if self.map_type:
            res["map_type"] = self.map_type
        if self.affine_transform is not None:
            res["affine_transform"] = list(self.affine_transform)
        if self.control_points is not None:
            res["control_points"] = [dict(cp) for cp in self.control_points]
        if self.transformation_type:
            res["transformation_type"] = self.transformation_type
        return res

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "ProjectMapData":
        """Создание экземпляра из словаря с поддержкой обратной совместимости."""
        if not data or not isinstance(data, dict):
            return cls()
        raw_layers = data.get("layers", [])
        layers_list = [dict(l) for l in raw_layers if isinstance(l, dict)]

        raw_affine = data.get("affine_transform")
        affine_list: list[float] | None = None
        if isinstance(raw_affine, (list, tuple)):
            affine_list = [float(x) for x in raw_affine]

        raw_cps = data.get("control_points")
        cps_list: list[dict[str, Any]] | None = None
        if isinstance(raw_cps, list):
            cps_list = [dict(cp) for cp in raw_cps if isinstance(cp, dict)]

        return cls(
            map_id=str(data.get("map_id") or ""),
            relative_path=str(data.get("relative_path") or data.get("path") or ""),
            name=str(data.get("name") or ""),
            source_type=str(data.get("source_type") or "geopackage"),
            crs=data.get("crs"),
            boundary_layer=data.get("boundary_layer"),
            layers=layers_list,
            provider_id=data.get("provider_id"),
            map_type=data.get("map_type"),
            affine_transform=affine_list,
            control_points=cps_list,
            transformation_type=str(data.get("transformation_type") or "affine"),
        )


@dataclass
class ProjectPointData:
    """Сериализуемые данные пользовательской точки."""

    id: str
    name: str
    latitude: float
    longitude: float
    source_crs: str = "OGC:CRS84"
    visible: bool = True
    symbol: str = "circle"
    size: float = 12.0
    red: int = 220
    green: int = 30
    blue: int = 30
    zone_enabled: bool = False
    radius_m: float = 0.0
    zone_red: int = 220
    zone_green: int = 30
    zone_blue: int = 30
    zone_opacity: int = 30
    object_number: str = ""
    description: str = ""
    category: str = ""
    stroke_red: int = 0
    stroke_green: int = 0
    stroke_blue: int = 0
    stroke_width: float = 1.0
    opacity: float = 100.0
    zone_border_red: int = 220
    zone_border_green: int = 30
    zone_border_blue: int = 30
    zone_border_width: float = 1.0
    zone_border_style: str = "solid"
    group_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Преобразование в словарь для JSON-сериализации."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ProjectPointData":
        """Создание экземпляра из словаря с безопасными значениями по умолчанию."""
        raw_gid = data.get("group_id")
        gid = str(raw_gid).strip() if raw_gid is not None and str(raw_gid).strip() else None

        return cls(
            id=str(data["id"]),
            name=str(data.get("name", "")),
            latitude=float(data["latitude"]),
            longitude=float(data["longitude"]),
            source_crs=str(data.get("source_crs", "OGC:CRS84")),
            visible=bool(data.get("visible", True)),
            symbol=str(data.get("symbol", "circle")),
            size=float(data.get("size", 12.0)),
            red=int(data.get("red", 220)),
            green=int(data.get("green", 30)),
            blue=int(data.get("blue", 30)),
            zone_enabled=bool(data.get("zone_enabled", False)),
            radius_m=float(data.get("radius_m", 0.0)),
            zone_red=int(data.get("zone_red", 220)),
            zone_green=int(data.get("zone_green", 30)),
            zone_blue=int(data.get("zone_blue", 30)),
            zone_opacity=int(data.get("zone_opacity", 30)),
            object_number=str(data.get("object_number", "")),
            description=str(data.get("description", "")),
            category=str(data.get("category", "")),
            stroke_red=int(data.get("stroke_red", 0)),
            stroke_green=int(data.get("stroke_green", 0)),
            stroke_blue=int(data.get("stroke_blue", 0)),
            stroke_width=float(data.get("stroke_width", 1.0)),
            opacity=float(data.get("opacity", data.get("marker_opacity", 100.0))),
            zone_border_red=int(data.get("zone_border_red", data.get("zone_red", 220))),
            zone_border_green=int(data.get("zone_border_green", data.get("zone_green", 30))),
            zone_border_blue=int(data.get("zone_border_blue", data.get("zone_blue", 30))),
            zone_border_width=float(data.get("zone_border_width", 1.0)),
            zone_border_style=str(data.get("zone_border_style", "solid")),
            group_id=gid,
        )

    def to_map_point(self) -> MapPoint:
        """Конвертация в модель рабочего пространства MapPoint."""
        return MapPoint(
            id=self.id,
            name=self.name,
            latitude=self.latitude,
            longitude=self.longitude,
            source_crs=self.source_crs,
            visible=self.visible,
            symbol=self.symbol,
            size=self.size,
            red=self.red,
            green=self.green,
            blue=self.blue,
            zone_enabled=self.zone_enabled,
            radius_m=self.radius_m,
            zone_red=self.zone_red,
            zone_green=self.zone_green,
            zone_blue=self.zone_blue,
            zone_opacity=self.zone_opacity,
            object_number=self.object_number,
            description=self.description,
            category=self.category,
            stroke_red=self.stroke_red,
            stroke_green=self.stroke_green,
            stroke_blue=self.stroke_blue,
            stroke_width=self.stroke_width,
            opacity=self.opacity,
            zone_border_red=self.zone_border_red,
            zone_border_green=self.zone_border_green,
            zone_border_blue=self.zone_border_blue,
            zone_border_width=self.zone_border_width,
            zone_border_style=self.zone_border_style,
            group_id=self.group_id,
        )

    @classmethod
    def from_map_point(cls, point: MapPoint) -> "ProjectPointData":
        """Создание ProjectPointData из экземпляра MapPoint."""
        return cls(
            id=point.id,
            name=point.name,
            latitude=point.latitude,
            longitude=point.longitude,
            source_crs=point.source_crs,
            visible=point.visible,
            symbol=point.symbol,
            size=point.size,
            red=point.red,
            green=point.green,
            blue=point.blue,
            zone_enabled=point.zone_enabled,
            radius_m=point.radius_m,
            zone_red=point.zone_red,
            zone_green=point.zone_green,
            zone_blue=point.zone_blue,
            zone_opacity=point.zone_opacity,
            object_number=point.object_number,
            description=point.description,
            category=point.category,
            stroke_red=point.stroke_red,
            stroke_green=point.stroke_green,
            stroke_blue=point.stroke_blue,
            stroke_width=point.stroke_width,
            opacity=point.opacity,
            zone_border_red=point.zone_border_red,
            zone_border_green=point.zone_border_green,
            zone_border_blue=point.zone_border_blue,
            zone_border_width=point.zone_border_width,
            zone_border_style=point.zone_border_style,
            group_id=point.group_id,
        )


PRIMARY_PROJECT_FORMAT = "GeoPoint Mapper Project"
LEGACY_PROJECT_FORMAT = "RME-Mapper Project"
SUPPORTED_PROJECT_FORMATS = {PRIMARY_PROJECT_FORMAT, LEGACY_PROJECT_FORMAT}


@dataclass
class ProjectData:
    """Корневая модель проекта GeoPoint Mapper."""

    format: str = PRIMARY_PROJECT_FORMAT
    version: int = 1
    map: ProjectMapData = field(default_factory=ProjectMapData)
    layers: dict[str, bool] = field(default_factory=dict)
    points: list[ProjectPointData] = field(default_factory=list)
    groups: list[ProjectGroupData] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Преобразование модели проекта в словарь верхнего уровня."""
        return {
            "format": self.format,
            "version": self.version,
            "map": self.map.to_dict(),
            "layers": dict(self.layers),
            "groups": [g.to_dict() for g in self.groups],
            "points": [p.to_dict() for p in self.points],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ProjectData":
        """Десериализация проекта из словаря."""
        if not isinstance(data, dict):
            raise ValueError("Данные проекта должны быть JSON-объектом (словарем).")

        fmt = data.get("format")
        if fmt not in SUPPORTED_PROJECT_FORMATS:
            raise ValueError(
                f"Неподдерживаемый формат проекта: '{fmt}'. "
                f"Ожидается '{PRIMARY_PROJECT_FORMAT}' или '{LEGACY_PROJECT_FORMAT}'."
            )

        ver = data.get("version")
        if ver is None:
            raise ValueError("В файле проекта отсутствует поле 'version'.")

        try:
            ver_int = int(ver)
        except (ValueError, TypeError):
            raise ValueError(f"Некорректная версия проекта: '{ver}'.")

        map_data = ProjectMapData.from_dict(data.get("map"))

        raw_layers = data.get("layers", {})
        layers: dict[str, bool] = {}
        if isinstance(raw_layers, dict):
            for k, v in raw_layers.items():
                layers[str(k)] = bool(v)

        # Десериализация групп с безопасной обработкой дубликатов ID
        raw_groups = data.get("groups", [])
        groups: list[ProjectGroupData] = []
        seen_group_ids: set[str] = set()
        if isinstance(raw_groups, list):
            for grp_item in raw_groups:
                if isinstance(grp_item, dict):
                    grp_data = ProjectGroupData.from_dict(grp_item)
                    if grp_data.id in seen_group_ids:
                        grp_data.id = uuid4().hex
                    seen_group_ids.add(grp_data.id)
                    groups.append(grp_data)

        raw_points = data.get("points", [])
        points: list[ProjectPointData] = []
        if isinstance(raw_points, list):
            for pt_item in raw_points:
                if isinstance(pt_item, dict) and "id" in pt_item and "latitude" in pt_item and "longitude" in pt_item:
                    points.append(ProjectPointData.from_dict(pt_item))

        return cls(
            format=fmt,
            version=ver_int,
            map=map_data,
            layers=layers,
            points=points,
            groups=groups,
        )
