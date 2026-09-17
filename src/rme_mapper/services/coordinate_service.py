"""Сервис работы с координатами и геометрическими проверками."""

import logging
from typing import Any

import pyproj
from shapely.geometry import Point

logger = logging.getLogger("rme_mapper.services.coordinate")


class CoordinateService:
    """Сервис координатных вычислений и проверки нахождения внутри геометрии."""

    @staticmethod
    def is_point_inside_boundary(
        longitude: float,
        latitude: float,
        boundary_geometry: Any,
    ) -> bool:
        """Геометрическая проверка попадания точки внутрь границы через Shapely.

        Не использует грубый bounding box, а выполняет точную проверку полигона.
        """
        if boundary_geometry is None:
            return True

        try:
            pt = Point(longitude, latitude)
            # Точка считается внутри, если она строго содержится или лежит на границе полигона
            is_inside = boundary_geometry.contains(pt) or boundary_geometry.touches(pt)
            logger.debug(
                "Проверка попадания точки (lon=%s, lat=%s) в границу: %s",
                longitude, latitude, is_inside,
            )
            return bool(is_inside)
        except Exception as e:
            logger.warning("Ошибка при геометрической проверке точки: %s", e)
            return True

    @staticmethod
    def transform_point(
        x: float,
        y: float,
        source_crs: str = "OGC:CRS84",
        target_crs: str = "OGC:CRS84",
    ) -> tuple[float, float]:
        """Преобразование координат между CRS через pyproj (подготовка к будущим этапам).

        Использует always_xy=True (первая координата = longitude/X, вторая = latitude/Y).
        """
        if source_crs == target_crs:
            return x, y

        try:
            transformer = pyproj.Transformer.from_crs(
                source_crs, target_crs, always_xy=True
            )
            tx, ty = transformer.transform(x, y)
            return float(tx), float(ty)
        except Exception as e:
            logger.exception("Ошибка трансформации координат (%s, %s): %s", x, y, e)
            raise
