"""Менеджер хранения и управления пользовательскими точками в памяти."""
from __future__ import annotations


import logging
from typing import Any, Iterator

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
        visible: bool = True,
        object_number: str = "",
        description: str = "",
        category: str = "",
        stroke_red: int = 0,
        stroke_green: int = 0,
        stroke_blue: int = 0,
        stroke_width: float = 1.0,
        opacity: int = 100,
        zone_border_red: int = 220,
        zone_border_green: int = 30,
        zone_border_blue: int = 30,
        zone_border_width: float = 1.0,
        zone_border_style: str = "solid",
        group_id: str | None = None,
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
            "visible": visible,
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
            "object_number": object_number,
            "description": description,
            "category": category,
            "stroke_red": stroke_red,
            "stroke_green": stroke_green,
            "stroke_blue": stroke_blue,
            "stroke_width": stroke_width,
            "opacity": opacity,
            "zone_border_red": zone_border_red,
            "zone_border_green": zone_border_green,
            "zone_border_blue": zone_border_blue,
            "zone_border_width": zone_border_width,
            "zone_border_style": zone_border_style,
            "group_id": group_id,
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
        object_number: str | None = None,
        description: str | None = None,
        category: str | None = None,
        stroke_red: int | None = None,
        stroke_green: int | None = None,
        stroke_blue: int | None = None,
        stroke_width: float | None = None,
        opacity: int | None = None,
        zone_border_red: int | None = None,
        zone_border_green: int | None = None,
        zone_border_blue: int | None = None,
        zone_border_width: float | None = None,
        zone_border_style: str | None = None,
        group_id: Any = None,
        update_group: bool = False,
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
        if object_number is not None:
            point.object_number = object_number
        if description is not None:
            point.description = description
        if category is not None:
            point.category = category
        if stroke_red is not None:
            point.stroke_red = stroke_red
        if stroke_green is not None:
            point.stroke_green = stroke_green
        if stroke_blue is not None:
            point.stroke_blue = stroke_blue
        if stroke_width is not None:
            point.stroke_width = stroke_width
        if opacity is not None:
            point.opacity = opacity
        if zone_border_red is not None:
            point.zone_border_red = zone_border_red
        if zone_border_green is not None:
            point.zone_border_green = zone_border_green
        if zone_border_blue is not None:
            point.zone_border_blue = zone_border_blue
        if zone_border_width is not None:
            point.zone_border_width = zone_border_width
        if zone_border_style is not None:
            point.zone_border_style = zone_border_style
        if update_group:
            point.group_id = group_id

        logger.info(
            "Обновлена точка: id=%s, name='%s', lat=%s, lon=%s, zone_enabled=%s, radius_m=%s, group_id=%s",
            point.id, point.name, point.latitude, point.longitude,
            point.zone_enabled, point.radius_m, point.group_id,
        )
        return point

    def set_point_group(self, point_id: str, group_id: str | None) -> None:
        """Назначение группы для одной точки."""
        point = self.get_point(point_id)
        if point:
            point.group_id = group_id

    def set_points_group(self, point_ids: list[str], group_id: str | None) -> None:
        """Массовое назначение группы для набора точек."""
        for pid in point_ids:
            self.set_point_group(pid, group_id)

    def get_points_by_group(self, group_id: str | None) -> list[MapPoint]:
        """Получение списка точек, принадлежащих указанной группе (или Ungrouped при None)."""
        return [p for p in self._points.values() if p.group_id == group_id]

    def count_points_by_groups(self) -> dict[str | None, int]:
        """Подсчет количества точек во всех группах за один проход O(N)."""
        from collections import Counter
        return dict(Counter(p.group_id for p in self._points.values()))

    def add_points_bulk(self, points: list[MapPoint]) -> list[MapPoint]:
        """Массовое добавление готовых точек в хранилище за один проход."""
        for p in points:
            self._points[p.id] = p
        return points

    def get_used_categories(self) -> list[str]:
        """Получение списка уникальных непустых категорий всех точек проекта."""
        cats = {p.category.strip() for p in self._points.values() if p.category and p.category.strip()}
        return sorted(cats)


    def update_point_object(self, point: MapPoint) -> MapPoint:
        """Обновление точки передачей готового экземпляра MapPoint (сохраняя point.id)."""
        if point.id not in self._points:
            raise KeyError(f"Точка с ID '{point.id}' не найдена в хранилище.")
        self._points[point.id] = point
        return point

    def insert_point(self, point: MapPoint, index: int | None = None) -> MapPoint:
        """Вставка готового экземпляра MapPoint в хранилище с сохранением заданного индекса."""
        items = [(pid, pt) for pid, pt in self._points.items() if pid != point.id]
        if index is None or index >= len(items):
            items.append((point.id, point))
        else:
            target_idx = max(0, index)
            items.insert(target_idx, (point.id, point))
        self._points = dict(items)
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
