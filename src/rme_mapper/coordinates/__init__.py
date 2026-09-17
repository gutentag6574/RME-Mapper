"""Модуль работы с координатами.

Отвечает за:
- Парсинг строковых представлений координат DD и DMS;
- Валидацию диапазонов широты (-90..90) и долготы (-180..180);
- Нормализацию форматов и направлений.
"""

from rme_mapper.coordinates.converter import dms_to_decimal
from rme_mapper.coordinates.validator import CoordinateValidator

__all__ = ["CoordinateValidator", "dms_to_decimal"]
