"""Модуль математических преобразований географических координат."""
from __future__ import annotations


import logging

logger = logging.getLogger("rme_mapper.coordinates.converter")


def dms_to_decimal(
    degrees: int | float,
    minutes: int | float,
    seconds: int | float,
    direction: str,
) -> float:
    """Преобразование координат из формата DMS (градусы, минуты, секунды) в десятичные градусы (DD).

    Параметры:
        degrees: Градусы (неотрицательное число).
        minutes: Минуты (неотрицательное число, 0 <= minutes < 60).
        seconds: Секунды (неотрицательное число, 0.0 <= seconds < 60.0).
        direction: Направление ('N', 'S', 'E', 'W').

    Возвращает:
        float: Координата в десятичных градусах (положительная для N/E, отрицательная для S/W).

    Исключения:
        ValueError: Если направление некорректно или компоненты отрицательны.
    """
    deg = float(degrees)
    mn = float(minutes)
    sec = float(seconds)

    if deg < 0 or mn < 0 or sec < 0:
        raise ValueError("Градусы, минуты и секунды не могут быть отрицательными.")

    dir_clean = direction.strip().upper()
    if dir_clean not in {"N", "S", "E", "W"}:
        raise ValueError(
            f"Недопустимое направление '{direction}'. Разрешены только N, S, E, W."
        )

    abs_value = deg + (mn / 60.0) + (sec / 3600.0)

    if dir_clean in {"S", "W"}:
        return -abs_value
    return abs_value
