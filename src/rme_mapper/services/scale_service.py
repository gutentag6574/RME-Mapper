"""Сервис вычисления красивых масштабов и расстояний для экранной и экспортной масштабных линеек."""
from __future__ import annotations


import logging

from rme_mapper.services.coordinate_service import CoordinateService
from rme_mapper.services.geodesic_service import GeodesicService

logger = logging.getLogger("rme_mapper.services.scale")

# Набор стандартных "красивых" расстояний для масштабной линейки (в метрах)
NICE_SCALE_DISTANCES: list[float] = [
    1.0,
    2.0,
    5.0,
    10.0,
    20.0,
    50.0,
    100.0,
    200.0,
    500.0,
    1_000.0,
    2_000.0,
    5_000.0,
    10_000.0,
    20_000.0,
    50_000.0,
    100_000.0,
    200_000.0,
    500_000.0,
    1_000_000.0,
]


class ScaleService:
    """Унифицированный сервис подбора делений и параметров масштабной линейки."""

    @staticmethod
    def pick_nice_distance(target_distance_m: float) -> float:
        """Подбор ближайшего стандартного 'красивого' расстояния (1, 2, 5...), меньшего или равного целевому."""
        if target_distance_m <= NICE_SCALE_DISTANCES[0]:
            return NICE_SCALE_DISTANCES[0]

        best_val = NICE_SCALE_DISTANCES[0]
        for val in NICE_SCALE_DISTANCES:
            if val <= target_distance_m:
                best_val = val
            else:
                break

        # Если масштаб еще крупнее последнего значения в таблице, масштабируем порядками
        if target_distance_m > NICE_SCALE_DISTANCES[-1]:
            cur = NICE_SCALE_DISTANCES[-1]
            while cur * 2 <= target_distance_m:
                cur *= 2
            return cur

        return best_val

    @staticmethod
    def format_scale_label(distance_m: float, lang: str | None = None) -> str:
        """Форматирование подписи масштабной линейки (например: '500 м' или '2 км')."""
        try:
            from rme_mapper.i18n import get_language, tr
            active_lang = lang or get_language()
        except Exception:
            active_lang = "ru"

        unit_km = "km" if active_lang == "en" else "км"
        unit_m = "m" if active_lang == "en" else "м"

        if distance_m >= 1000.0:
            km_val = distance_m / 1000.0
            km_str = f"{int(km_val)}" if km_val.is_integer() else f"{km_val:.1f}"
            return f"{km_str} {unit_km}"
        else:
            m_str = f"{int(distance_m)}" if distance_m.is_integer() else f"{distance_m:.1f}"
            return f"{m_str} {unit_m}"

    @classmethod
    def calculate_scale_for_span(
        cls,
        x1: float,
        x2: float,
        y: float,
        pixel_span: float,
        active_crs: str,
        target_bar_pixels: float = 120.0,
        lang: str | None = None,
    ) -> tuple[float, float, str] | None:
        """Расчет параметров линейки масштаба: (nice_dist_m, actual_bar_pixels, label_text).

        Параметры:
            x1, x2, y: координаты двух точек в активной CRS карты на одной горизонтали.
            pixel_span: расстояние между ними на экране/изображении в пикселях.
            active_crs: система координат карты.
            target_bar_pixels: желаемая базовая длина линейки в пикселях.
            lang: язык отображения ('ru' или 'en').
        """
        if pixel_span <= 0:
            return None

        try:
            lon1, lat1 = CoordinateService.transform_xy(x1, y, active_crs, "OGC:CRS84")
            lon2, lat2 = CoordinateService.transform_xy(x2, y, active_crs, "OGC:CRS84")
            dist_m = GeodesicService.calculate_distance(lon1, lat1, lon2, lat2)
        except Exception as err:
            logger.warning("Ошибка геодезического расчета масштаба: %s", err)
            return None

        if dist_m <= 0:
            return None

        meters_per_pixel = dist_m / pixel_span
        target_dist_m = target_bar_pixels * meters_per_pixel
        nice_dist_m = cls.pick_nice_distance(target_dist_m)
        actual_bar_px = nice_dist_m / meters_per_pixel
        label = cls.format_scale_label(nice_dist_m, lang=lang)

        return nice_dist_m, actual_bar_px, label
