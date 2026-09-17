"""Модели структуры данных проекта RME-Mapper (*.rmeproject)."""

from dataclasses import asdict, dataclass, field
from typing import Any

from rme_mapper.models.map_point import MapPoint


@dataclass
class ProjectMapData:
    """Данные о подключенной карте проекта."""

    map_id: str = "mari_el"
    relative_path: str = "maps/test_map/prepared/mari.gpkg"

    def to_dict(self) -> dict[str, Any]:
        """Преобразование в словарь для JSON-сериализации."""
        res: dict[str, Any] = {
            "map_id": self.map_id,
        }
        if self.relative_path:
            res["relative_path"] = self.relative_path
        return res

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "ProjectMapData":
        """Создание экземпляра из словаря с поддержкой обратной совместимости."""
        if not data or not isinstance(data, dict):
            return cls()
        return cls(
            map_id=str(data.get("map_id") or "mari_el"),
            relative_path=str(data.get("relative_path") or data.get("path") or "maps/test_map/prepared/mari.gpkg"),
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

    def to_dict(self) -> dict[str, Any]:
        """Преобразование в словарь для JSON-сериализации."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ProjectPointData":
        """Создание экземпляра из словаря с безопасными значениями по умолчанию."""
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
        )


@dataclass
class ProjectData:
    """Корневая модель проекта RME-Mapper."""

    format: str = "RME-Mapper Project"
    version: int = 1
    map: ProjectMapData = field(default_factory=ProjectMapData)
    layers: dict[str, bool] = field(default_factory=dict)
    points: list[ProjectPointData] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Преобразование модели проекта в словарь верхнего уровня."""
        return {
            "format": self.format,
            "version": self.version,
            "map": self.map.to_dict(),
            "layers": dict(self.layers),
            "points": [p.to_dict() for p in self.points],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ProjectData":
        """Десериализация проекта из словаря."""
        if not isinstance(data, dict):
            raise ValueError("Данные проекта должны быть JSON-объектом (словарем).")

        fmt = data.get("format")
        if fmt != "RME-Mapper Project":
            raise ValueError(
                f"Неподдерживаемый формат проекта: '{fmt}'. Ожидается 'RME-Mapper Project'."
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
        )
