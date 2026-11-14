"""Reproject RGBA imagery for cross-CRS overlays without editing the source file."""
from __future__ import annotations
import numpy as np
from PySide6.QtGui import QImage


def warp_image(image, full_size, affine, source_crs, target_crs, extent=None, output_size=None):
    import rasterio.warp
    from rasterio.transform import Affine, from_bounds
    from rasterio.enums import Resampling

    if image is None or image.isNull() or image.width() <= 0 or image.height() <= 0:
        raise ValueError("Cannot warp an empty or invalid image")

    rgba = image.convertToFormat(QImage.Format.Format_RGBA8888)
    if rgba.isNull() or rgba.width() <= 0 or rgba.height() <= 0:
        raise ValueError("Failed to convert image to RGBA8888 for warping")

    source = (
        np.frombuffer(rgba.bits(), dtype=np.uint8)
        .reshape(rgba.height(), rgba.bytesPerLine())[:, : rgba.width() * 4]
        .reshape(rgba.height(), rgba.width(), 4)
        .copy()
    )
    transform = Affine(*affine) @ Affine.scale(full_size[0] / rgba.width(), full_size[1] / rgba.height())
    if extent is not None:
        if output_size is None:
            width = max(1, rgba.width())
            xmin, ymin, xmax, ymax = extent
            dx = abs(float(xmax) - float(xmin))
            dy = abs(float(ymax) - float(ymin))
            if dx > 0 and dy > 0:
                height = max(1, min(4096, round(width * (dy / dx))))
            else:
                height = max(1, rgba.height())
        else:
            width, height = int(output_size[0]), int(output_size[1])
            if width <= 0 or height <= 0:
                raise ValueError("output_size must contain positive dimensions")
        dest_transform = from_bounds(*extent, width, height)
    else:
        corners = [
            transform @ (x, y)
            for x, y in ((0, 0), (rgba.width(), 0), (0, rgba.height()), (rgba.width(), rgba.height()))
        ]
        xs, ys = zip(*corners)
        dest_transform, width, height = rasterio.warp.calculate_default_transform(
            source_crs,
            target_crs,
            rgba.width(),
            rgba.height(),
            min(xs),
            min(ys),
            max(xs),
            max(ys),
        )
        factor = max(1, max(width, height) / 4096)
        width, height = max(1, round(width / factor)), max(1, round(height / factor))
        dest_transform = dest_transform @ Affine.scale(factor)
    destination = np.zeros((4, height, width), dtype=np.uint8)
    rasterio.warp.reproject(
        source=np.moveaxis(source, 2, 0),
        destination=destination,
        src_transform=transform,
        src_crs=source_crs,
        dst_transform=dest_transform,
        dst_crs=target_crs,
        src_alpha=4,
        dst_alpha=4,
        resampling=Resampling.bilinear,
    )
    data = np.ascontiguousarray(np.moveaxis(destination, 0, 2))
    return QImage(data.data, width, height, width * 4, QImage.Format.Format_RGBA8888).copy(), tuple(dest_transform)[:6]
