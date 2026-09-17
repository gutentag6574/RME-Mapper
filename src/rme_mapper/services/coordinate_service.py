"""Сервис универсальной работы с координатами, геометрическими проверками и трансформацией CRS."""

from functools import lru_cache
import logging
from typing import Any

import pyproj
from shapely.geometry import Point, Polygon

logger = logging.getLogger("rme_mapper.services.coordinate")


@lru_cache(maxsize=128)
def _get_transformer(source_crs: str, target_crs: str) -> pyproj.Transformer | None:
    """Кэшированное создание трансформера pyproj с always_xy=True."""
    s_clean = source_crs.strip()
    t_clean = target_crs.strip()

    # Быстрая проверка строкового совпадения
    if s_clean.upper() == t_clean.upper():
        return None

    try:
        s_obj = pyproj.CRS.from_user_input(s_clean)
        t_obj = pyproj.CRS.from_user_input(t_clean)
        if s_obj == t_obj:
            return None
        return pyproj.Transformer.from_crs(s_obj, t_obj, always_xy=True)
    except Exception as err:
        logger.exception("Не удалось создать трансформер из %s в %s: %s", source_crs, target_crs, err)
        raise


class CoordinateService:
    """Универсальный сервис координатных вычислений и преобразования между CRS."""

    @staticmethod
    def transform_xy(
        x: float,
        y: float,
        source_crs: str = "EPSG:4326",
        target_crs: str = "EPSG:4326",
    ) -> tuple[float, float]:
        """Преобразование координат (x, y) между произвольными CRS через pyproj.

        Всегда использует always_xy=True:
        - Для географических CRS: x = longitude, y = latitude.
        - Для спроецированных CRS: x = easting/X (м), y = northing/Y (м).
        """
        if not source_crs or not target_crs:
            return float(x), float(y)

        try:
            transformer = _get_transformer(source_crs, target_crs)
            if transformer is None:
                return float(x), float(y)

            tx, ty = transformer.transform(x, y)
            return float(tx), float(ty)
        except Exception as e:
            logger.exception("Ошибка трансформации координат (%s, %s) из %s в %s: %s", x, y, source_crs, target_crs, e)
            raise

    @staticmethod
    def transform_point(
        x: float,
        y: float,
        source_crs: str = "OGC:CRS84",
        target_crs: str = "OGC:CRS84",
    ) -> tuple[float, float]:
        """Алиас для обратной совместимости с вызовами transform_point."""
        return CoordinateService.transform_xy(x, y, source_crs=source_crs, target_crs=target_crs)

    @classmethod
    def transform_polygon(
        cls,
        polygon: Polygon,
        source_crs: str,
        target_crs: str,
    ) -> Polygon:
        """Трансформация всех вершин полигона (внешнего кольца и внутренних вырезов) в целевой CRS.

        Каждая вершина (x, y) трансформируется через pyproj с always_xy=True.
        """
        if polygon is None or polygon.is_empty:
            return polygon

        transformer = _get_transformer(source_crs, target_crs)
        if transformer is None:
            return polygon

        try:
            # Трансформируем внешнее кольцо
            exterior_coords = [
                transformer.transform(x, y)
                for x, y in polygon.exterior.coords
            ]

            # Трансформируем внутренние вырезы, если есть
            interiors_coords = []
            for interior in polygon.interiors:
                interiors_coords.append([
                    transformer.transform(x, y)
                    for x, y in interior.coords
                ])

            new_poly = Polygon(exterior_coords, interiors_coords)
            return new_poly
        except Exception as e:
            logger.exception("Ошибка трансформации полигона из %s в %s: %s", source_crs, target_crs, e)
            raise

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
    def is_point_inside_extent(
        x: float,
        y: float,
        extent: dict[str, float] | tuple[float, float, float, float] | list[float] | None,
    ) -> bool:
        """Проверка попадания координаты (x, y) в прямоугольный охват (extent).

        Принимает словарь с ключами xmin, ymin, xmax, ymax или кортеж (xmin, ymin, xmax, ymax).
        Если extent не задан, возвращает True.
        """
        if extent is None:
            return True

        try:
            if isinstance(extent, dict):
                xmin = float(extent["xmin"])
                ymin = float(extent["ymin"])
                xmax = float(extent["xmax"])
                ymax = float(extent["ymax"])
            elif isinstance(extent, (tuple, list)) and len(extent) >= 4:
                xmin, ymin, xmax, ymax = float(extent[0]), float(extent[1]), float(extent[2]), float(extent[3])
            else:
                return True

            return (xmin <= x <= xmax) and (ymin <= y <= ymax)
        except Exception as e:
            logger.warning("Ошибка при проверке охвата extent: %s", e)
            return True
