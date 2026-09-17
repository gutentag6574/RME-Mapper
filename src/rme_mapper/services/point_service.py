"""Менеджер хранения и управления пользовательскими точками в памяти."""

import logging
from typing import Iterator

from rme_mapper.models.map_point import MapPoint

logger = logging.getLogger("rme_mapper.services.point")


class PointService:
    """Сервис управления пользовательскими точками приложения."""

    def __init__(self) -> None:
        # Хранилище: point_id -> MapPoint
        self._points: dict[str, MapPoint] = {}
        self._auto_counter: int = 1

    def add_point(
        self,
        name: str | None,
        latitude: float,
        longitude: float,
        source_crs: str = "OGC:CRS84",
        point_id: str | None = None,
        symbol: str = "circle",
        size: float = 12.0,
        red: int = 220,
        green: int = 30,
        blue: int = 30,
        zone_enabled: bool = False,
        radius_m: float = 0.0,
        zone_red: int = 220,
        zone_green: int = 30,
        zone_blue: int = 30,
        zone_opacity: int = 30,
    ) -> MapPoint:
        """Создание и добавление новой пользовательской точки.

        Если имя не указано или пусто, генерируется автоматическое название:
        'Точка 1', 'Точка 2' и т.д.
        """
        final_name = (name or "").strip()
        if not final_name:
            final_name = f"Точка {self._auto_counter}"
            self._auto_counter += 1

        kwargs = {
            "name": final_name,
            "latitude": latitude,
            "longitude": longitude,
            "source_crs": source_crs,
            "symbol": symbol,
            "size": size,
            "red": red,
            "green": green,
            "blue": blue,
            "zone_enabled": zone_enabled,
            "radius_m": radius_m,
            "zone_red": zone_red,
            "zone_green": zone_green,
            "zone_blue": zone_blue,
            "zone_opacity": zone_opacity,
        }
        if point_id:
            kwargs["id"] = point_id

        point = MapPoint(**kwargs)
        self._points[point.id] = point

        logger.info(
            "Добавлена точка: id=%s, name='%s', lat=%s, lon=%s, zone_enabled=%s, radius_m=%s",
            point.id, point.name, point.latitude, point.longitude,
            point.zone_enabled, point.radius_m,
        )
        return point

    def update_point(
        self,
        point_id: str,
        name: str | None = None,
        latitude: float | None = None,
        longitude: float | None = None,
        symbol: str | None = None,
        size: float | None = None,
        red: int | None = None,
        green: int | None = None,
        blue: int | None = None,
        visible: bool | None = None,
        zone_enabled: bool | None = None,
        radius_m: float | None = None,
        zone_red: int | None = None,
        zone_green: int | None = None,
        zone_blue: int | None = None,
        zone_opacity: int | None = None,
    ) -> MapPoint:
        """Обновление существующей пользовательской точки по ее ID.

        Сохраняет исходный ID точки и обновляет только переданные поля.
        """
        point = self._points.get(point_id)
        if point is None:
            raise KeyError(f"Точка с ID '{point_id}' не найдена в хранилище.")

        if name is not None:
            point.name = name.strip() if name.strip() else point.name
        if latitude is not None:
            point.latitude = latitude
        if longitude is not None:
            point.longitude = longitude
        if symbol is not None:
            point.symbol = symbol
        if size is not None:
            point.size = size
        if red is not None:
            point.red = red
        if green is not None:
            point.green = green
        if blue is not None:
            point.blue = blue
        if visible is not None:
            point.visible = visible
        if zone_enabled is not None:
            point.zone_enabled = zone_enabled
        if radius_m is not None:
            point.radius_m = radius_m
        if zone_red is not None:
            point.zone_red = zone_red
        if zone_green is not None:
            point.zone_green = zone_green
        if zone_blue is not None:
            point.zone_blue = zone_blue
        if zone_opacity is not None:
            point.zone_opacity = zone_opacity

        logger.info(
            "Обновлена точка: id=%s, name='%s', lat=%s, lon=%s, zone_enabled=%s, radius_m=%s",
            point.id, point.name, point.latitude, point.longitude,
            point.zone_enabled, point.radius_m,
        )
        return point


    def update_point_object(self, point: MapPoint) -> MapPoint:
        """Обновление точки передачей готового экземпляра MapPoint (сохраняя point.id)."""
        if point.id not in self._points:
            raise KeyError(f"Точка с ID '{point.id}' не найдена в хранилище.")
        self._points[point.id] = point
        return point

    def get_points(self) -> list[MapPoint]:
        """Получение списка всех зарегистрированных точек."""
        return list(self._points.values())

    def get_point(self, point_id: str) -> MapPoint | None:
        """Получение точки по ее уникальному идентификатору."""
        return self._points.get(point_id)

    def remove_point(self, point_id: str) -> bool:
        """Удаление точки по ее идентификатору.

        Возвращает True, если точка была найдена и удалена, иначе False.
        """
        if point_id in self._points:
            removed = self._points.pop(point_id)
            logger.info("Удалена точка: id=%s, name='%s'", removed.id, removed.name)
            return True
        logger.warning("Попытка удаления несуществующей точки: %s", point_id)
        return False

    def clear(self) -> None:
        """Очистка всех точек."""
        self._points.clear()
        self._auto_counter = 1
        logger.info("Хранилище точек очищено")

    def __len__(self) -> int:
        return len(self._points)

    def __iter__(self) -> Iterator[MapPoint]:
        return iter(self._points.values())
