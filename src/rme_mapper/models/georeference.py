"""Модели данных для ручной геопривязки изображений по контрольным точкам (Stage 21)."""

from dataclasses import asdict, dataclass, field
import math
from typing import Any
from uuid import uuid4

MAX_CONTROL_POINTS = 500


@dataclass
class ControlPoint:
    """Контрольная точка геопривязки (Ground Control Point / GCP).

    Связывает пиксельные координаты растра (pixel_x, pixel_y)
    с целевыми географическими или прямоугольными координатами (target_x, target_y) в выбранной CRS.

    Система координат растра:
    - Origin (0, 0): верхний левый угол растра.
    - pixel_x: направлен вправо (колонки / width), непрерывное значение.
    - pixel_y: направлен вниз (строки / height), непрерывное значение.

    Целевые координаты (target_x, target_y):
    - Для географических CRS (EPSG:4326, OGC:CRS84): target_x = долгота (Lon), target_y = широта (Lat).
    - Для спроецированных CRS (UTM, EPSG:3857): target_x = Easting / X (м), target_y = Northing / Y (м).
    Всегда соблюдается принцип always_xy=True.
    """

    id: str = field(default_factory=lambda: uuid4().hex)
    name: str = ""
    pixel_x: float = 0.0
    pixel_y: float = 0.0
    target_x: float = 0.0
    target_y: float = 0.0
    enabled: bool = True

    # Расчетные невязки (residuals)
    residual_x: float | None = None
    residual_y: float | None = None
    residual_total: float | None = None

    def to_dict(self) -> dict[str, Any]:
        """Сериализация контрольной точки в словарь."""
        res: dict[str, Any] = {
            "id": self.id,
            "name": self.name,
            "pixel_x": float(self.pixel_x),
            "pixel_y": float(self.pixel_y),
            "target_x": float(self.target_x),
            "target_y": float(self.target_y),
            "enabled": bool(self.enabled),
        }
        if self.residual_x is not None:
            res["residual_x"] = float(self.residual_x)
        if self.residual_y is not None:
            res["residual_y"] = float(self.residual_y)
        if self.residual_total is not None:
            res["residual_total"] = float(self.residual_total)
        return res

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ControlPoint":
        """Десериализация контрольной точки из словаря."""
        if not isinstance(data, dict):
            raise ValueError("Данные контрольной точки должны быть словарем")

        res_x = data.get("residual_x")
        res_y = data.get("residual_y")
        res_tot = data.get("residual_total")

        return cls(
            id=str(data.get("id") or uuid4().hex),
            name=str(data.get("name") or ""),
            pixel_x=float(data.get("pixel_x", 0.0)),
            pixel_y=float(data.get("pixel_y", 0.0)),
            target_x=float(data.get("target_x", 0.0)),
            target_y=float(data.get("target_y", 0.0)),
            enabled=bool(data.get("enabled", True)),
            residual_x=float(res_x) if res_x is not None else None,
            residual_y=float(res_y) if res_y is not None else None,
            residual_total=float(res_tot) if res_tot is not None else None,
        )
