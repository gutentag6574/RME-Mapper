"""Shared rendering of cached XYZ tiles, including export in a different CRS."""
from __future__ import annotations
import math
import pyproj
from PySide6.QtCore import QPointF, QRectF
from PySide6.QtGui import QPolygonF, QTransform, QPixmap

from rme_mapper.services.tile_math import extent_to_tile_range, meters_per_pixel_to_zoom, tile_to_mercator_bounds


def render_cached_tiles(painter, manager, extent, width, height, active_crs="EPSG:3857"):
    provider = manager.provider
    if provider is None:
        return
    crs = pyproj.CRS(active_crs)
    mercator = pyproj.CRS("EPSG:3857")
    same = crs.equals(mercator)
    to_merc = pyproj.Transformer.from_crs(crs, mercator, always_xy=True)
    bounds = extent if same else to_merc.transform_bounds(*extent, densify_pts=21)
    if not all(math.isfinite(v) for v in bounds):
        raise ValueError("Export extent cannot be transformed to Web Mercator")
    zoom = meters_per_pixel_to_zoom((bounds[2]-bounds[0])/max(width, 1), min_zoom=provider.min_zoom, max_zoom=provider.max_zoom)
    tiles = extent_to_tile_range(*bounds, zoom)
    if tiles is None:
        return
    # Limit work for unusually distorted or very large extents.
    while (tiles[2]-tiles[0]+1)*(tiles[3]-tiles[1]+1)>1024 and zoom>provider.min_zoom:
        zoom -= 1
        tiles = extent_to_tile_range(*bounds, zoom)
    if (tiles[2]-tiles[0]+1)*(tiles[3]-tiles[1]+1)>1024:
        raise ValueError("Too many tiles in export extent")
    xmin,ymin,xmax,ymax = extent
    sx,sy = width/(xmax-xmin), height/(ymax-ymin)
    transform = pyproj.Transformer.from_crs(mercator, crs, always_xy=True)
    def target(x, y):
        if not same:
            x,y = transform.transform(x,y)
        return QPointF((x-xmin)*sx,(ymax-y)*sy)
    for tx in range(tiles[0],tiles[2]+1):
        for ty in range(tiles[1],tiles[3]+1):
            pixmap = manager._get_mem_cache(provider.id,zoom,tx,ty)
            cache = getattr(manager,"_cache",None)
            if pixmap is None and cache is not None:
                data = cache.get_tile(provider.id,zoom,tx,ty)
                if data:
                    pixmap = QPixmap()
                    if not pixmap.loadFromData(data):
                        pixmap = None
            if pixmap is None or pixmap.isNull():
                continue
            left,bottom,right,top = tile_to_mercator_bounds(tx,ty,zoom)
            if same:
                a,b = target(left,top),target(right,bottom)
                painter.drawPixmap(QRectF(a,b).toRect(),pixmap)
                continue
            # Subdivide a tile into projected quads: a bounding rectangle alone
            # would stretch UTM/geographic exports and misplace the imagery.
            steps = 8
            for row in range(steps):
                for col in range(steps):
                    x0,x1 = left+(right-left)*col/steps,left+(right-left)*(col+1)/steps
                    y0,y1 = top-(top-bottom)*row/steps,top-(top-bottom)*(row+1)/steps
                    quad = QPolygonF([target(x0,y0),target(x1,y0),target(x1,y1),target(x0,y1)])
                    if not all(math.isfinite(p.x()) and math.isfinite(p.y()) for p in quad):
                        continue
                    source = QRectF(col*pixmap.width()/steps,row*pixmap.height()/steps,pixmap.width()/steps,pixmap.height()/steps)
                    src = QPolygonF([source.topLeft(),source.topRight(),source.bottomRight(),source.bottomLeft()])
                    matrix = QTransform.quadToQuad(src,quad)
                    if matrix is None:
                        continue
                    painter.save()
                    painter.setWorldTransform(matrix,True)
                    painter.drawPixmap(source,pixmap,source)
                    painter.restore()
