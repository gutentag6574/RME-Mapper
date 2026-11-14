"""Project-backed field tracks and saved measurements in longitude/latitude."""
from __future__ import annotations

from functools import lru_cache
import math
import pyproj
from pyproj.exceptions import ProjError
from PySide6.QtGui import QPainterPath


@lru_cache(maxsize=32)
def _get_annotation_transformer(target_crs: str) -> pyproj.Transformer:
    return pyproj.Transformer.from_crs("EPSG:4326", target_crs, always_xy=True)


def annotation_path(record, target_crs, scene=True):
    coordinates = record.get("coordinates", [])
    if record.get("kind") not in ("line", "polygon") or not 2 <= len(coordinates) <= 100000:
        raise ValueError("Invalid annotation geometry")
    if any(len(p) != 2 or not all(math.isfinite(float(v)) for v in p) or not -180 <= p[0] <= 180 or not -90 <= p[1] <= 90 for p in coordinates):
        raise ValueError("Invalid annotation coordinates")
    try:
        transform = _get_annotation_transformer(str(target_crs))
    except ProjError as err:
        raise ValueError(f"Unsupported target CRS '{target_crs}': {err}") from err
    path = QPainterPath()
    for index, (lon, lat) in enumerate(coordinates):
        try:
            x, y = transform.transform(lon, lat, errcheck=True)
        except ProjError as err:
            raise ValueError(f"Annotation projection failed: {err}") from err
        if not (math.isfinite(x) and math.isfinite(y)):
            raise ValueError("Non-finite projected annotation coordinates")
        if scene:
            y = -y
        if index == 0:
            path.moveTo(x, y)
        else:
            path.lineTo(x, y)
    if record["kind"] == "polygon":
        path.closeSubpath()
    return path
