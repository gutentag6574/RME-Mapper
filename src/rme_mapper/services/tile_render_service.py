"""Shared rendering of cached XYZ tiles, including export in a different CRS."""
from __future__ import annotations

import logging
import math
import pyproj
from pyproj.exceptions import ProjError
from PySide6.QtCore import QPointF, QRectF
from PySide6.QtGui import QPolygonF, QTransform, QPixmap

from rme_mapper.services.tile_math import (
    MAX_LATITUDE,
    MAX_MERCATOR_EXTENT,
    MIN_LATITUDE,
    extent_to_tile_range,
    meters_per_pixel_to_zoom,
    tile_to_mercator_bounds,
)

logger = logging.getLogger("rme_mapper.services.tile_render")


def _load_cached_pixmap(manager, cache, provider_id: str, zoom: int, tx: int, ty: int) -> QPixmap | None:
    pixmap = manager._get_mem_cache(provider_id, zoom, tx, ty)
    if pixmap is None and cache is not None:
        data = cache.get_tile(provider_id, zoom, tx, ty)
        if data:
            candidate = QPixmap()
            if candidate.loadFromData(data):
                pixmap = candidate
    if pixmap is None or pixmap.isNull():
        return None
    return pixmap


def _find_cached_tile_with_fallback(
    manager,
    cache,
    provider_id: str,
    zoom: int,
    tx: int,
    ty: int,
    min_zoom: int,
) -> tuple[QPixmap, QRectF] | None:
    """Находит точный тайл или ближайший родительский тайл более крупного охвата."""
    pixmap = _load_cached_pixmap(manager, cache, provider_id, zoom, tx, ty)
    if pixmap is not None:
        return pixmap, QRectF(0.0, 0.0, float(pixmap.width()), float(pixmap.height()))

    max_ancestor_steps = min(3, max(0, zoom - min_zoom))
    for depth in range(1, max_ancestor_steps + 1):
        az = zoom - depth
        factor = 1 << depth
        ax = tx >> depth
        ay = ty >> depth
        parent_pixmap = _load_cached_pixmap(manager, cache, provider_id, az, ax, ay)
        if parent_pixmap is not None and parent_pixmap.width() > 0 and parent_pixmap.height() > 0:
            sub_x = tx % factor
            sub_y = ty % factor
            tile_w = float(parent_pixmap.width()) / factor
            tile_h = float(parent_pixmap.height()) / factor
            src_rect = QRectF(sub_x * tile_w, sub_y * tile_h, tile_w, tile_h)
            return parent_pixmap, src_rect
    return None


def _clamp_mercator_bounds(xmin: float, ymin: float, xmax: float, ymax: float) -> tuple[float, float, float, float]:
    return (
        max(-MAX_MERCATOR_EXTENT, min(MAX_MERCATOR_EXTENT, xmin)),
        max(-MAX_MERCATOR_EXTENT, min(MAX_MERCATOR_EXTENT, ymin)),
        max(-MAX_MERCATOR_EXTENT, min(MAX_MERCATOR_EXTENT, xmax)),
        max(-MAX_MERCATOR_EXTENT, min(MAX_MERCATOR_EXTENT, ymax)),
    )


def render_cached_tiles(painter, manager, extent, width, height, active_crs="EPSG:3857"):
    provider = manager.provider
    if provider is None or width <= 0 or height <= 0:
        return

    xmin, ymin, xmax, ymax = map(float, extent)
    span_x = xmax - xmin
    span_y = ymax - ymin
    if not (math.isfinite(span_x) and math.isfinite(span_y)) or span_x <= 0.0 or span_y <= 0.0:
        return

    try:
        crs = pyproj.CRS(active_crs)
        mercator = pyproj.CRS("EPSG:3857")
        same = crs.equals(mercator)
    except ProjError as err:
        logger.warning("Некорректная CRS при экспорте тайлов '%s': %s", active_crs, err)
        return

    if same:
        bounds = _clamp_mercator_bounds(xmin, ymin, xmax, ymax)
    else:
        src_bounds = (xmin, ymin, xmax, ymax)
        if crs.is_geographic:
            clamped_ymin = max(MIN_LATITUDE, min(MAX_LATITUDE, ymin))
            clamped_ymax = max(MIN_LATITUDE, min(MAX_LATITUDE, ymax))
            if clamped_ymax <= clamped_ymin:
                return
            src_bounds = (max(-180.0, xmin), clamped_ymin, min(180.0, xmax), clamped_ymax)
        try:
            to_merc = pyproj.Transformer.from_crs(crs, mercator, always_xy=True)
            raw_bounds = to_merc.transform_bounds(*src_bounds, densify_pts=21)
        except ProjError as err:
            logger.warning("Ошибка перепроецирования охвата в EPSG:3857: %s", err)
            return
        if not all(math.isfinite(v) for v in raw_bounds):
            return
        bounds = _clamp_mercator_bounds(*raw_bounds)

    if bounds[2] <= bounds[0] or bounds[3] <= bounds[1]:
        return

    zoom = meters_per_pixel_to_zoom(
        (bounds[2] - bounds[0]) / max(width, 1),
        min_zoom=provider.min_zoom,
        max_zoom=provider.max_zoom,
    )
    tiles = extent_to_tile_range(*bounds, zoom)
    if tiles is None:
        return
    # Limit work for unusually distorted or very large extents.
    while (tiles[2] - tiles[0] + 1) * (tiles[3] - tiles[1] + 1) > 1024 and zoom > provider.min_zoom:
        zoom -= 1
        tiles = extent_to_tile_range(*bounds, zoom)
        if tiles is None:
            return
    if (tiles[2] - tiles[0] + 1) * (tiles[3] - tiles[1] + 1) > 1024:
        raise ValueError("Too many tiles in export extent")

    sx, sy = width / span_x, height / span_y
    transform = None if same else pyproj.Transformer.from_crs(mercator, crs, always_xy=True)
    cache = getattr(manager, "_cache", None)

    def target(x, y):
        if transform is not None:
            x, y = transform.transform(x, y)
        return QPointF((x - xmin) * sx, (ymax - y) * sy)

    for tx in range(tiles[0], tiles[2] + 1):
        for ty in range(tiles[1], tiles[3] + 1):
            found = _find_cached_tile_with_fallback(manager, cache, provider.id, zoom, tx, ty, provider.min_zoom)
            if found is None:
                continue
            pixmap, tile_src_rect = found
            left, bottom, right, top = tile_to_mercator_bounds(tx, ty, zoom)
            if same:
                a, b = target(left, top), target(right, bottom)
                painter.drawPixmap(QRectF(a, b), pixmap, tile_src_rect)
                continue
            # Subdivide a tile into projected quads: a bounding rectangle alone
            # would stretch UTM/geographic exports and misplace the imagery.
            steps = 8
            for row in range(steps):
                for col in range(steps):
                    x0 = left + (right - left) * col / steps
                    x1 = left + (right - left) * (col + 1) / steps
                    y0 = top - (top - bottom) * row / steps
                    y1 = top - (top - bottom) * (row + 1) / steps
                    try:
                        quad = QPolygonF([target(x0, y0), target(x1, y0), target(x1, y1), target(x0, y1)])
                    except ProjError:
                        continue
                    if not all(math.isfinite(p.x()) and math.isfinite(p.y()) for p in quad):
                        continue
                    source = QRectF(
                        tile_src_rect.left() + col * tile_src_rect.width() / steps,
                        tile_src_rect.top() + row * tile_src_rect.height() / steps,
                        tile_src_rect.width() / steps,
                        tile_src_rect.height() / steps,
                    )
                    src = QPolygonF([source.topLeft(), source.topRight(), source.bottomRight(), source.bottomLeft()])
                    matrix = QTransform.quadToQuad(src, quad)
                    if matrix is None:
                        continue
                    painter.save()
                    painter.setWorldTransform(matrix, True)
                    painter.drawPixmap(source, pixmap, source)
                    painter.restore()
