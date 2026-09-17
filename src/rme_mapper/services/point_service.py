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
        }
        if point_id:
            kwargs["id"] = point_id

        point = MapPoint(**kwargs)
        self._points[point.id] = point

        logger.info(
            "Добавлена точка: id=%s, name='%s', lat=%s, lon=%s",
            point.id, point.name, point.latitude, point.longitude,
        )
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
