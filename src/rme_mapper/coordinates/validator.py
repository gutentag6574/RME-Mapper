"""Валидатор географических координат в формате десятичных градусов (DD)."""

import logging

logger = logging.getLogger("rme_mapper.coordinates.validator")


class CoordinateValidator:
    """Валидатор и парсер десятичных координат (Decimal Degrees)."""

    @classmethod
    def parse_dd(cls, value: str | float | int) -> float:
        """Парсинг значения координаты из строки или числа.

        Поддерживает как десятичную точку, так и запятую (например, 56.631 и 56,631).
        Исключает сбои при лишних пробелах.
        """
        if isinstance(value, (float, int)):
            return float(value)

        if not isinstance(value, str):
            raise ValueError(f"Ожидается строка или число, получено: {type(value).__name__}")

        cleaned = value.strip()
        if not cleaned:
            raise ValueError("Значение координаты не может быть пустым")

        # Заменяем запятую на точку для парсинга дробной части
        normalized = cleaned.replace(",", ".")

        try:
            return float(normalized)
        except ValueError:
            logger.debug("Не удалось преобразовать строку '%s' в число", value)
            raise ValueError(f"Некорректный формат числа: '{value}'")

    @classmethod
    def validate_latitude(cls, latitude: float) -> None:
        """Проверка допустимого диапазона широты [-90, 90]."""
        if not (-90.0 <= latitude <= 90.0):
            raise ValueError(
                f"Широта должна находиться в диапазоне от -90 до 90 градусов. Получено: {latitude}"
            )

    @classmethod
    def validate_longitude(cls, longitude: float) -> None:
        """Проверка допустимого диапазона долготы [-180, 180]."""
        if not (-180.0 <= longitude <= 180.0):
            raise ValueError(
                f"Долгота должна находиться в диапазоне от -180 до 180 градусов. Получено: {longitude}"
            )

    @classmethod
    def validate_dd_pair(
        cls,
        lat_input: str | float | int,
        lon_input: str | float | int,
    ) -> tuple[float, float]:
        """Комплексный парсинг и валидация пары координат (широта, долгота).

        Возвращает:
            tuple[float, float]: (latitude, longitude)
        """
        lat = cls.parse_dd(lat_input)
        lon = cls.parse_dd(lon_input)

        cls.validate_latitude(lat)
        cls.validate_longitude(lon)

        return lat, lon
