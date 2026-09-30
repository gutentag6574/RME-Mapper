"""Математика тайлов XYZ, проекции Web Mercator (EPSG:3857) и преобразования координат сцены."""
from __future__ import annotations


import math
from PySide6.QtCore import QPointF, QRectF

# Международные константы эллипсоида WGS84 и проекции Web Mercator
WGS84_A: float = 6378137.0  # большая полуось (радиус сферы в Web Mercator), метры
MAX_MERCATOR_EXTENT: float = math.pi * WGS84_A  # ~ 20037508.342789244 метров
MAX_LATITUDE: float = 85.0511287798066  # предельная широта Web Mercator в градусах
MIN_LATITUDE: float = -85.0511287798066
TILE_SIZE_PX: int = 256


class TileMath:
    """Чистые статические методы расчета координат Web Mercator, индексов тайлов XYZ и границ сцены."""

    @staticmethod
    def clamp_latitude(lat: float) -> float:
        """Ограничение широты допустимым диапазоном проекции Web Mercator [-85.0511°, +85.0511°]."""
        return max(min(lat, MAX_LATITUDE), MIN_LATITUDE)

    @staticmethod
    def normalize_longitude(lon: float) -> float:
        """Нормализация долготы к диапазону [-180°, +180°]."""
        if -180.0 <= lon <= 180.0:
            return lon
        return ((lon + 180.0) % 360.0) - 180.0

    @classmethod
    def lonlat_to_mercator(cls, lon: float, lat: float) -> tuple[float, float]:
        """Преобразование географических координат (WGS84 lon, lat) в метры Web Mercator (EPSG:3857).

        Возвращает:
            tuple[float, float]: (x_meters, y_meters)
        """
        clamped_lat = cls.clamp_latitude(lat)
        norm_lon = cls.normalize_longitude(lon)

        x = norm_lon * MAX_MERCATOR_EXTENT / 180.0
        lat_rad = math.radians(clamped_lat)
        # y = R * ln(tan(pi/4 + lat/2))
        y = WGS84_A * math.log(math.tan(math.pi / 4.0 + lat_rad / 2.0))
        # Ограничиваем y максимальным полупериметром во избежание микровыходов из-за точности float
        y = max(min(y, MAX_MERCATOR_EXTENT), -MAX_MERCATOR_EXTENT)
        return x, y

    @classmethod
    def mercator_to_lonlat(cls, x: float, y: float) -> tuple[float, float]:
        """Преобразование метров Web Mercator (EPSG:3857) в географические координаты (WGS84 lon, lat).

        Возвращает:
            tuple[float, float]: (lon, lat)
        """
        clamped_x = max(min(x, MAX_MERCATOR_EXTENT), -MAX_MERCATOR_EXTENT)
        clamped_y = max(min(y, MAX_MERCATOR_EXTENT), -MAX_MERCATOR_EXTENT)

        lon = (clamped_x / MAX_MERCATOR_EXTENT) * 180.0
        # lat = 2 * atan(exp(y / R)) - pi/2 = radians_to_degrees(2 * atan(exp(y / R)) - pi/2)
        lat_rad = 2.0 * math.atan(math.exp(clamped_y / WGS84_A)) - (math.pi / 2.0)
        lat = math.degrees(lat_rad)
        return lon, cls.clamp_latitude(lat)

    @classmethod
    def lat_lon_to_mercator(cls, lat: float, lon: float) -> tuple[float, float]:
        """Псевдоним lonlat_to_mercator с порядком аргументов (lat, lon)."""
        return cls.lonlat_to_mercator(lon=lon, lat=lat)

    @classmethod
    def mercator_to_lat_lon(cls, x: float, y: float) -> tuple[float, float]:
        """Псевдоним mercator_to_lonlat, возвращающий (lat, lon)."""
        lon, lat = cls.mercator_to_lonlat(x=x, y=y)
        return lat, lon

    @classmethod
    def mercator_to_tile(cls, x: float, y: float, z: int) -> tuple[int, int]:
        """Определение целочисленных индексов тайла (tx, ty) для точки в метрах Web Mercator на зуме z."""
        if z < 0:
            z = 0
        n = 1 << z  # 2^z
        tile_span = (2.0 * MAX_MERCATOR_EXTENT) / n

        clamped_x = max(min(x, MAX_MERCATOR_EXTENT - 1e-9), -MAX_MERCATOR_EXTENT)
        clamped_y = max(min(y, MAX_MERCATOR_EXTENT), -MAX_MERCATOR_EXTENT + 1e-9)

        tx = int(math.floor((clamped_x + MAX_MERCATOR_EXTENT) / tile_span))
        ty = int(math.floor((MAX_MERCATOR_EXTENT - clamped_y) / tile_span))

        # Ограничение диапазоном [0, n - 1]
        tx = max(0, min(tx, n - 1))
        ty = max(0, min(ty, n - 1))
        return tx, ty

    @classmethod
    def lonlat_to_tile(cls, lon: float, lat: float, z: int) -> tuple[int, int]:
        """Определение индексов тайла (tx, ty) для географических координат (WGS84 lon, lat) на зуме z."""
        x, y = cls.lonlat_to_mercator(lon, lat)
        return cls.mercator_to_tile(x, y, z)

    @classmethod
    def tile_to_mercator_bounds(cls, tx: int, ty: int, z: int) -> tuple[float, float, float, float]:
        """Получение охвата тайла (min_x, min_y, max_x, max_y) в метрах Web Mercator.

        Возвращает:
            (min_x, min_y, max_x, max_y)
        """
        if z < 0:
            z = 0
        n = 1 << z
        tile_span = (2.0 * MAX_MERCATOR_EXTENT) / n

        min_x = -MAX_MERCATOR_EXTENT + tx * tile_span
        max_x = min_x + tile_span
        max_y = MAX_MERCATOR_EXTENT - ty * tile_span
        min_y = max_y - tile_span

        return min_x, min_y, max_x, max_y

    @classmethod
    def tile_to_scene_rect(cls, tx: int, ty: int, z: int) -> QRectF:
        """Получение прямоугольника тайла в координатах графической сцены MapCanvas (X, -Y).

        В MapCanvas ось Y направлена вниз (экранная система), поэтому сцена:
        scene_x = mercator_x
        scene_y = -mercator_y
        Левый верхний угол тайла: (min_x, -max_y).
        """
        min_x, min_y, max_x, max_y = cls.tile_to_mercator_bounds(tx, ty, z)
        width = max_x - min_x
        height = max_y - min_y
        return QRectF(min_x, -max_y, width, height)

    @classmethod
    def extent_to_tile_range(
        cls,
        min_x: float,
        min_y: float,
        max_x: float,
        max_y: float,
        z: int,
        margin: int = 1,
    ) -> tuple[int, int, int, int]:
        """Расчет диапазона тайлов (min_tx, min_ty, max_tx, max_ty), покрывающих заданный экстент Web Mercator.

        Параметр margin добавляет дополнительную кайму тайлов по краям для плавного панорамирования.
        """
        if z < 0:
            z = 0
        n = 1 << z

        min_tx, max_ty = cls.mercator_to_tile(min_x, min_y, z)
        max_tx, min_ty = cls.mercator_to_tile(max_x, max_y, z)

        # Добавляем margin и ограничиваем допустимыми пределами [0, n - 1]
        res_min_tx = max(0, min_tx - margin)
        res_max_tx = min(n - 1, max_tx + margin)
        res_min_ty = max(0, min_ty - margin)
        res_max_ty = min(n - 1, max_ty + margin)

        return res_min_tx, res_min_ty, res_max_tx, res_max_ty

    @classmethod
    def meters_per_pixel_to_zoom(cls, meters_per_px: float, min_zoom: int = 0, max_zoom: int = 19) -> int:
        """Определение ближайшего целочисленного уровня зума XYZ исходя из разрешения (метров на пиксель).

        На зуме 0 длина экватора (40 075 016.6856 м) делится на 256 пикселей, то есть
        базовое разрешение составляет ~ 156 543.0339 м/пикс.
        """
        if meters_per_px <= 0:
            return max_zoom

        initial_res = (2.0 * MAX_MERCATOR_EXTENT) / float(TILE_SIZE_PX)
        # meters_per_px = initial_res / (2^z) => 2^z = initial_res / meters_per_px
        z_raw = math.log2(initial_res / meters_per_px)
        z = int(round(z_raw))
        return max(min_zoom, min(z, max_zoom))

    @classmethod
    def tile_count(cls, min_tx: int, min_ty: int, max_tx: int, max_ty: int) -> int:
        """Количество тайлов в указанном диапазоне индексов."""
        if max_tx < min_tx or max_ty < min_ty:
            return 0
        return (max_tx - min_tx + 1) * (max_ty - min_ty + 1)


# Модульные псевдонимы для удобного импорта
clamp_latitude = TileMath.clamp_latitude
normalize_longitude = TileMath.normalize_longitude
lonlat_to_mercator = TileMath.lonlat_to_mercator
mercator_to_lonlat = TileMath.mercator_to_lonlat
mercator_to_tile = TileMath.mercator_to_tile
lonlat_to_tile = TileMath.lonlat_to_tile
tile_to_mercator_bounds = TileMath.tile_to_mercator_bounds
tile_to_scene_rect = TileMath.tile_to_scene_rect
extent_to_tile_range = TileMath.extent_to_tile_range
meters_per_pixel_to_zoom = TileMath.meters_per_pixel_to_zoom
tile_count = TileMath.tile_count

