"""Сервис геодезических вычислений на эллипсоиде WGS84 через pyproj.Geod."""

import logging
from typing import Any

import pyproj
from shapely.geometry import Polygon

logger = logging.getLogger("rme_mapper.services.geodesic")


MAX_CIRCLE_CACHE_SIZE = 2048


class GeodesicService:
    """Сервис точных геодезических расчетов и построения окружностей на эллипсоиде WGS84."""

    _geod: pyproj.Geod | None = None
    _circle_cache: dict[tuple[float, float, float, int], Polygon] = {}
    MAX_CIRCLE_CACHE_SIZE: int = MAX_CIRCLE_CACHE_SIZE

    @classmethod
    def get_geod(cls) -> pyproj.Geod:
        """Получение синглтон-экземпляра pyproj.Geod с эллипсоидом WGS84."""
        if cls._geod is None:
            cls._geod = pyproj.Geod(ellps="WGS84")
        return cls._geod

    @classmethod
    def clear_circle_cache(cls) -> None:
        """Очистка кэша геодезических полигонов окружностей."""
        cls._circle_cache.clear()

    @classmethod
    def circle_cache_size(cls) -> int:
        """Количество закэшированных геодезических полигонов."""
        return len(cls._circle_cache)

    @classmethod
    def create_geodesic_circle(
        cls,
        longitude: float | None = None,
        latitude: float | None = None,
        radius_m: float = 0.0,
        segments: int = 128,
        *,
        lon: float | None = None,
        lat: float | None = None,
        num_points: int | None = None,
    ) -> Polygon:
        """Построение замкнутого геодезического полигона окружности заданного радиуса (в метрах).

        Использует прямую геодезическую задачу (Geod.fwd) на эллипсоиде WGS84.
        Координаты возвращаются в системе OGC:CRS84 (lon, lat).
        Результаты кэшируются в ограниченном LRU-кэше (до MAX_CIRCLE_CACHE_SIZE записей).
        """
        if longitude is None and lon is not None:
            longitude = lon
        if latitude is None and lat is not None:
            latitude = lat
        if num_points is not None:
            segments = num_points

        if longitude is None or latitude is None:
            raise ValueError("Необходимо указать долготу и широту центральной точки.")

        if radius_m <= 0:
            raise ValueError(f"Радиус должен быть положительным числом (> 0). Получено: {radius_m}")

        if segments < 16:
            raise ValueError(f"Количество сегментов должно быть не менее 16. Получено: {segments}")

        cache_key = (
            round(float(longitude), 6),
            round(float(latitude), 6),
            round(float(radius_m), 2),
            int(segments),
        )
        if cache_key in cls._circle_cache:
            return cls._circle_cache[cache_key]

        geod = cls.get_geod()
        coords: list[tuple[float, float]] = []

        step = 360.0 / segments
        for i in range(segments):
            azimuth = i * step
            lon_i, lat_i, _ = geod.fwd(longitude, latitude, azimuth, radius_m)
            coords.append((lon_i, lat_i))

        # Замыкаем полигон первой точкой
        coords.append(coords[0])

        polygon = Polygon(coords)

        # Вытеснение при превышении лимита кэша (FIFO/LRU)
        if len(cls._circle_cache) >= cls.MAX_CIRCLE_CACHE_SIZE:
            # Удаляем первую четверть записей
            keys_to_evict = list(cls._circle_cache.keys())[:cls.MAX_CIRCLE_CACHE_SIZE // 4]
            for k in keys_to_evict:
                cls._circle_cache.pop(k, None)

        cls._circle_cache[cache_key] = polygon
        return polygon

    @classmethod
    def calculate_distance(
        cls,
        lon1: float,
        lat1: float,
        lon2: float,
        lat2: float,
    ) -> float:
        """Вычисление расстояния между двумя точками на эллипсоиде WGS84 в метрах (Geod.inv)."""
        geod = cls.get_geod()
        _, _, distance = geod.inv(lon1, lat1, lon2, lat2)
        return float(distance)

    @classmethod
    def parse_radius(cls, value: Any, unit: str = "км") -> float:
        """Парсинг строки/числа радиуса с переводом в метры.

        Поддерживает:
            10, 10.5, '10,5'
            Единицы: 'м', 'm', 'км', 'km'.
        """
        if value is None:
            raise ValueError("Радиус не может быть пустым.")

        if isinstance(value, str):
            cleaned = value.strip().replace(",", ".")
            if not cleaned:
                raise ValueError("Радиус не может быть пустым.")
            try:
                num = float(cleaned)
            except ValueError:
                raise ValueError(f"Некорректное числовое значение радиуса: '{value}'")
        elif isinstance(value, (int, float)):
            num = float(value)
        else:
            raise ValueError(f"Некорректный тип значения радиуса: {type(value).__name__}")

        if num <= 0:
            raise ValueError(f"Радиус должен быть больше 0. Получено: {num}")

        unit_clean = unit.strip().lower()
        if unit_clean in {"км", "km"}:
            radius_m = num * 1000.0
        elif unit_clean in {"м", "m"}:
            radius_m = num
        else:
            raise ValueError(f"Неизвестная единица измерения: '{unit}'. Допустимы: 'м', 'км'.")

        return radius_m

    @classmethod
    def format_radius(cls, radius_m: float, zone_enabled: bool = True, lang: str | None = None) -> str:
        """Форматирование радиуса для отображения в интерфейсе (таблица, свойства)."""
        if not zone_enabled or radius_m <= 0:
            return "—"

        try:
            from rme_mapper.i18n import get_language
            active_lang = lang or get_language()
        except Exception:
            active_lang = "ru"

        unit_km = "km" if active_lang == "en" else "км"
        unit_m = "m" if active_lang == "en" else "м"

        if radius_m >= 1000.0:
            km = radius_m / 1000.0
            if km.is_integer():
                return f"{int(km)} {unit_km}"
            return f"{km:.2f}".rstrip("0").rstrip(".") + f" {unit_km}"
        else:
            if radius_m.is_integer():
                return f"{int(radius_m)} {unit_m}"
            return f"{radius_m:.1f}".rstrip("0").rstrip(".") + f" {unit_m}"

    @classmethod
    def calculate_area_perimeter(
        cls,
        lons: list[float],
        lats: list[float],
    ) -> tuple[float, float]:
        """Вычисление геодезической площади (м²) и периметра (м) замкнутого полигона на WGS84.

        Возвращает:
            tuple[float, float]: (abs(area_m2), perimeter_m).
        """
        if len(lons) < 3 or len(lats) < 3:
            return 0.0, 0.0

        geod = cls.get_geod()
        area, perimeter = geod.polygon_area_perimeter(lons, lats)
        return abs(float(area)), abs(float(perimeter))

    @classmethod
    def format_distance(cls, distance_m: float, lang: str | None = None) -> str:
        """Форматирование геодезического расстояния (м / км) для UI."""
        if distance_m < 0:
            distance_m = 0.0

        try:
            from rme_mapper.i18n import get_language
            active_lang = lang or get_language()
        except Exception:
            active_lang = "ru"

        unit_km = "km" if active_lang == "en" else "км"
        unit_m = "m" if active_lang == "en" else "м"

        if distance_m >= 1000.0:
            km = distance_m / 1000.0
            return f"{km:.2f} {unit_km}"
        else:
            if distance_m.is_integer():
                return f"{int(distance_m)} {unit_m}"
            return f"{distance_m:.1f} {unit_m}"

    @classmethod
    def format_area(cls, area_m2: float, lang: str | None = None) -> str:
        """Форматирование геодезической площади (м² / га / км²) для UI."""
        abs_area = abs(area_m2)

        try:
            from rme_mapper.i18n import get_language
            active_lang = lang or get_language()
        except Exception:
            active_lang = "ru"

        unit_m2 = "m²" if active_lang == "en" else "м²"
        unit_ha = "ha" if active_lang == "en" else "га"
        unit_km2 = "km²" if active_lang == "en" else "км²"

        if abs_area >= 1_000_000.0:
            km2 = abs_area / 1_000_000.0
            return f"{km2:.2f} {unit_km2}"
        elif abs_area >= 10_000.0:
            ha = abs_area / 10_000.0
            return f"{ha:.2f} {unit_ha}"
        else:
            if abs_area.is_integer():
                return f"{int(abs_area)} {unit_m2}"
            return f"{abs_area:.1f} {unit_m2}"

