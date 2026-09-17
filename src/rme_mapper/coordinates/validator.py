"""Валидатор географических координат в формате десятичных градусов (DD) и DMS."""

from typing import Any
import logging

from rme_mapper.coordinates.converter import dms_to_decimal

logger = logging.getLogger("rme_mapper.coordinates.validator")


class ValidationError(ValueError):
    """Исключение валидации с поддержкой стабильного кода ошибки и двуязычного перевода."""

    def __init__(self, code: str, **params: Any) -> None:
        self.code = code
        self.params = params
        super().__init__(self._format())

    def _format(self) -> str:
        try:
            from rme_mapper.i18n import tr
            return tr(self.code, **self.params)
        except Exception:
            return self.code

    def localized_message(self, lang: str | None = None) -> str:
        """Получить локализованное сообщение на указанном или активном языке."""
        try:
            from rme_mapper.i18n import get_translation_service
            ts = get_translation_service()
            if lang:
                return ts.translate_in_language(lang, self.code, **self.params)
            return ts.translate(self.code, **self.params)
        except Exception:
            return self.code

    def __str__(self) -> str:
        return self._format()


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
            raise ValidationError("val.coord.expected_str_num", type=type(value).__name__)

        cleaned = value.strip()
        if not cleaned:
            raise ValidationError("val.coord.empty_coord")

        # Заменяем запятую на точку для парсинга дробной части
        normalized = cleaned.replace(",", ".")

        try:
            return float(normalized)
        except ValueError:
            logger.debug("Не удалось преобразовать строку '%s' в число", value)
            raise ValidationError("val.coord.invalid_number_format", value=value)

    @classmethod
    def validate_latitude(cls, latitude: float) -> None:
        """Проверка допустимого диапазона широты [-90, 90]."""
        if not (-90.0 <= latitude <= 90.0):
            raise ValidationError("val.coord.lat_range", value=latitude)

    @classmethod
    def validate_longitude(cls, longitude: float) -> None:
        """Проверка допустимого диапазона долготы [-180, 180]."""
        if not (-180.0 <= longitude <= 180.0):
            raise ValidationError("val.coord.lon_range", value=longitude)

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
            raise ValidationError("val.dms.enter_component", component=component_name, coord_label=coord_label)

        if isinstance(value, str):
            cleaned = value.strip().replace(",", ".")
            if not cleaned:
                raise ValidationError("val.dms.enter_component", component=component_name, coord_label=coord_label)
            try:
                num = float(cleaned)
            except ValueError:
                raise ValidationError("val.dms.component_must_be_int", component=component_name.capitalize(), coord_label=coord_label)
        elif isinstance(value, (int, float)):
            num = float(value)
        else:
            raise ValidationError("val.dms.enter_component", component=component_name, coord_label=coord_label)

        if not num.is_integer():
            raise ValidationError("val.dms.component_must_be_int", component=component_name.capitalize(), coord_label=coord_label)

        return int(num)

    @classmethod
    def _parse_dms_seconds(
        cls,
        value: str | int | float,
        coord_label: str,
    ) -> float:
        """Вспомогательный метод парсинга секунд DMS (поддерживает точку и запятую)."""
        if value is None:
            raise ValidationError("val.dms.enter_component", component="секунды", coord_label=coord_label)

        if isinstance(value, str):
            cleaned = value.strip().replace(",", ".")
            if not cleaned:
                raise ValidationError("val.dms.enter_component", component="секунды", coord_label=coord_label)
            try:
                sec = float(cleaned)
            except ValueError:
                raise ValidationError("val.dms.seconds_must_be_number", coord_label=coord_label)
        elif isinstance(value, (int, float)):
            sec = float(value)
        else:
            raise ValidationError("val.dms.enter_component", component="секунды", coord_label=coord_label)

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
            raise ValidationError("val.dms.lat_deg_range", value=deg)

        if not (0 <= mn < 60):
            raise ValidationError("val.dms.lat_min_range")

        if sec < 0:
            raise ValidationError("val.dms.lat_sec_negative")
        if sec >= 60.0:
            raise ValidationError("val.dms.lat_sec_less_60")

        if deg == 90 and (mn != 0 or sec != 0.0):
            raise ValidationError("val.dms.lat_90_zero")

        if not isinstance(direction, str):
            raise ValidationError("val.dms.lat_dir_str")

        dir_clean = direction.strip().upper()
        if dir_clean not in {"N", "S"}:
            raise ValidationError("val.dms.lat_dir_invalid", value=direction)

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
            raise ValidationError("val.dms.lon_deg_range", value=deg)

        if not (0 <= mn < 60):
            raise ValidationError("val.dms.lon_min_range")

        if sec < 0:
            raise ValidationError("val.dms.lon_sec_negative")
        if sec >= 60.0:
            raise ValidationError("val.dms.lon_sec_less_60")

        if deg == 180 and (mn != 0 or sec != 0.0):
            raise ValidationError("val.dms.lon_180_zero")

        if not isinstance(direction, str):
            raise ValidationError("val.dms.lon_dir_str")

        dir_clean = direction.strip().upper()
        if dir_clean not in {"E", "W"}:
            raise ValidationError("val.dms.lon_dir_invalid", value=direction)

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
