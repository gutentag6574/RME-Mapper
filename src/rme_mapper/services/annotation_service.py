"""Project-backed field tracks and saved measurements in longitude/latitude."""
from __future__ import annotations
import math
import pyproj
from PySide6.QtGui import QPainterPath


def annotation_path(record, target_crs, scene=True):
    coordinates=record.get("coordinates",[])
    if record.get("kind") not in ("line","polygon") or not 2<=len(coordinates)<=100000:
        raise ValueError("Invalid annotation geometry")
    if any(len(p)!=2 or not all(math.isfinite(float(v)) for v in p) or not -180<=p[0]<=180 or not -90<=p[1]<=90 for p in coordinates):
        raise ValueError("Invalid annotation coordinates")
    transform=pyproj.Transformer.from_crs("EPSG:4326",target_crs,always_xy=True)
    path=QPainterPath()
    for index,(lon,lat) in enumerate(coordinates):
        x,y=transform.transform(lon,lat,errcheck=True)
        if scene:
            y=-y
        if index==0:
            path.moveTo(x,y)
        else:
            path.lineTo(x,y)
    if record["kind"]=="polygon":
        path.closeSubpath()
    return path
