"""Валидатор географических координат в формате десятичных градусов (DD)."""

import logging

from rme_mapper.coordinates.converter import dms_to_decimal

logger = logging.getLogger("rme_mapper.coordinates.validator")


class CoordinateValidator:
    """Валидатор и парсер десятичных координат (DD) и координат градусов/минут/секунд (DMS)."""

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
        """Комплексный парсинг и валидация пары координат (широта, долгота) в формате DD.

        Возвращает:
            tuple[float, float]: (latitude, longitude)
        """
        lat = cls.parse_dd(lat_input)
        lon = cls.parse_dd(lon_input)

        cls.validate_latitude(lat)
        cls.validate_longitude(lon)

        return lat, lon

    @classmethod
    def _parse_dms_int(
        cls,
        value: str | int | float,
        component_name: str,
        coord_label: str,
    ) -> int:
        """Вспомогательный метод парсинга целых компонентов DMS (градусы, минуты)."""
        if value is None:
            raise ValueError(f"Введите {component_name} {coord_label}. Для нулевого значения укажите 0.")

        if isinstance(value, str):
            cleaned = value.strip().replace(",", ".")
            if not cleaned:
                raise ValueError(f"Введите {component_name} {coord_label}. Для нулевого значения укажите 0.")
            try:
                num = float(cleaned)
            except ValueError:
                raise ValueError(f"{component_name.capitalize()} {coord_label} должны быть целым числом.")
        elif isinstance(value, (int, float)):
            num = float(value)
        else:
            raise ValueError(f"Введите {component_name} {coord_label}. Для нулевого значения укажите 0.")

        if not num.is_integer():
            raise ValueError(f"{component_name.capitalize()} {coord_label} должны быть целым числом.")

        return int(num)

    @classmethod
    def _parse_dms_seconds(
        cls,
        value: str | int | float,
        coord_label: str,
    ) -> float:
        """Вспомогательный метод парсинга секунд DMS (поддерживает точку и запятую)."""
        if value is None:
            raise ValueError(f"Введите секунды {coord_label}. Для нулевого значения укажите 0.")

        if isinstance(value, str):
            cleaned = value.strip().replace(",", ".")
            if not cleaned:
                raise ValueError(f"Введите секунды {coord_label}. Для нулевого значения укажите 0.")
            try:
                sec = float(cleaned)
            except ValueError:
                raise ValueError(f"Секунды {coord_label} должны быть числом.")
        elif isinstance(value, (int, float)):
            sec = float(value)
        else:
            raise ValueError(f"Введите секунды {coord_label}. Для нулевого значения укажите 0.")

        return sec

    @classmethod
    def validate_dms_latitude(
        cls,
        degrees: str | int | float,
        minutes: str | int | float,
        seconds: str | int | float,
        direction: str,
    ) -> float:
        """Валидация компонентов широты в формате DMS и конвертация в десятичные градусы.

        Правила:
            - Градусы: целое число [0..90]
            - Минуты: целое число [0..59]
            - Секунды: число [0.0..60.0)
            - Направление: 'N' или 'S'
            - При широте 90° минуты и секунды обязаны быть 0.
        """
        deg = cls._parse_dms_int(degrees, "градусы", "широты")
        mn = cls._parse_dms_int(minutes, "минуты", "широты")
        sec = cls._parse_dms_seconds(seconds, "широты")

        if deg < 0 or deg > 90:
            raise ValueError(f"Градусы широты должны быть от 0 до 90. Получено: {deg}")

        if not (0 <= mn < 60):
            raise ValueError("Минуты широты должны быть от 0 до 59.")

        if sec < 0:
            raise ValueError("Секунды широты не могут быть отрицательными.")
        if sec >= 60.0:
            raise ValueError("Секунды широты должны быть меньше 60.")

        if deg == 90 and (mn != 0 or sec != 0.0):
            raise ValueError("Для широты 90° минуты и секунды должны быть равны 0.")

        if not isinstance(direction, str):
            raise ValueError("Направление широты должно быть строкой (N или S).")

        dir_clean = direction.strip().upper()
        if dir_clean not in {"N", "S"}:
            raise ValueError(f"Для широты допустимы только направления N и S. Получено: '{direction}'")

        return dms_to_decimal(deg, mn, sec, dir_clean)

    @classmethod
    def validate_dms_longitude(
        cls,
        degrees: str | int | float,
        minutes: str | int | float,
        seconds: str | int | float,
        direction: str,
    ) -> float:
        """Валидация компонентов долготы в формате DMS и конвертация в десятичные градусы.

        Правила:
            - Градусы: целое число [0..180]
            - Минуты: целое число [0..59]
            - Секунды: число [0.0..60.0)
            - Направление: 'E' или 'W'
            - При долготе 180° минуты и секунды обязаны быть 0.
        """
        deg = cls._parse_dms_int(degrees, "градусы", "долготы")
        mn = cls._parse_dms_int(minutes, "минуты", "долготы")
        sec = cls._parse_dms_seconds(seconds, "долготы")

        if deg < 0 or deg > 180:
            raise ValueError(f"Градусы долготы должны быть от 0 до 180. Получено: {deg}")

        if not (0 <= mn < 60):
            raise ValueError("Минуты долготы должны быть от 0 до 59.")

        if sec < 0:
            raise ValueError("Секунды долготы не могут быть отрицательными.")
        if sec >= 60.0:
            raise ValueError("Секунды долготы должны быть меньше 60.")

        if deg == 180 and (mn != 0 or sec != 0.0):
            raise ValueError("Для долготы 180° минуты и секунды должны быть равны 0.")

        if not isinstance(direction, str):
            raise ValueError("Направление долготы должно быть строкой (E или W).")

        dir_clean = direction.strip().upper()
        if dir_clean not in {"E", "W"}:
            raise ValueError(f"Для долготы допустимы только направления E и W. Получено: '{direction}'")

        return dms_to_decimal(deg, mn, sec, dir_clean)

    @classmethod
    def validate_dms_pair(
        cls,
        lat_parts: tuple[str | int | float, str | int | float, str | int | float, str],
        lon_parts: tuple[str | int | float, str | int | float, str | int | float, str],
    ) -> tuple[float, float]:
        """Валидация пары координат в формате DMS и конвертация в нормализованные (lat, lon).

        Параметры:
            lat_parts: (degrees, minutes, seconds, direction)
            lon_parts: (degrees, minutes, seconds, direction)

        Возвращает:
            tuple[float, float]: (latitude, longitude) в десятичных градусах.
        """
        lat = cls.validate_dms_latitude(*lat_parts)
        lon = cls.validate_dms_longitude(*lon_parts)
        return lat, lon

