"""Модель и валидатор визуального стиля пользовательской точки."""

import logging
from dataclasses import dataclass
from typing import Any

from rme_mapper.coordinates.validator import ValidationError

logger = logging.getLogger("rme_mapper.models.point_style")

ALLOWED_SYMBOLS: set[str] = {"circle", "square", "triangle"}
MIN_SIZE: float = 4.0
MAX_SIZE: float = 50.0
MIN_RGB: int = 0
MAX_RGB: int = 255


@dataclass
class PointStyle:
    """Визуальный стиль отображения пользовательской точки."""

    symbol: str = "circle"
    size: float = 12.0
    red: int = 220
    green: int = 30
    blue: int = 30


class StyleValidator:
    """Валидатор параметров визуального стиля маркера точки."""

    @classmethod
    def validate_symbol(cls, symbol: str) -> str:
        """Проверка допустимой формы маркера ('circle', 'square', 'triangle')."""
        if not isinstance(symbol, str):
            raise ValidationError("val.style.symbol_str", type=type(symbol).__name__)

        sym = symbol.strip().lower()
        if sym not in ALLOWED_SYMBOLS:
            raise ValidationError(
                "val.style.symbol_unknown",
                value=symbol,
                allowed=", ".join(sorted(ALLOWED_SYMBOLS)),
            )
        return sym

    @classmethod
    def validate_size(cls, size: Any) -> float:
        """Проверка допустимого размера маркера (от 4.0 до 50.0 px)."""
        if size is None:
            raise ValidationError("val.style.size_empty")

        if isinstance(size, str):
            cleaned = size.strip().replace(",", ".")
            if not cleaned:
                raise ValidationError("val.style.size_empty")
            try:
                val = float(cleaned)
            except ValueError:
                raise ValidationError("val.style.size_format", min=MIN_SIZE, max=MAX_SIZE)
        elif isinstance(size, (int, float)):
            val = float(size)
        else:
            raise ValidationError("val.style.size_number")

        if val < MIN_SIZE or val > MAX_SIZE:
            raise ValidationError("val.style.size_range", min=MIN_SIZE, max=MAX_SIZE, value=val)
        return val

    @classmethod
    def validate_rgb_component(cls, value: Any, component_name: str) -> int:
        """Проверка отдельной цветовой компоненты (0..255)."""
        if value is None:
            raise ValidationError("val.style.rgb_empty", component=component_name)

        if isinstance(value, str):
            cleaned = value.strip()
            if not cleaned:
                raise ValidationError("val.style.rgb_empty", component=component_name)
            try:
                val = float(cleaned.replace(",", "."))
            except ValueError:
                raise ValidationError("val.style.rgb_format", component=component_name)
            if not val.is_integer():
                raise ValidationError("val.style.rgb_int", component=component_name)
            int_val = int(val)
        elif isinstance(value, (int, float)):
            if isinstance(value, float) and not value.is_integer():
                raise ValidationError("val.style.rgb_int", component=component_name)
            int_val = int(value)
        else:
            raise ValidationError("val.style.rgb_format", component=component_name)

        if int_val < MIN_RGB or int_val > MAX_RGB:
            raise ValidationError(
                "val.style.rgb_range", component=component_name, value=int_val
            )
        return int_val

    @classmethod
    def validate_rgb(cls, red: Any, green: Any, blue: Any) -> tuple[int, int, int]:
        """Комплексная проверка трех компонент цвета RGB."""
        r = cls.validate_rgb_component(red, "Red (красный)")
        g = cls.validate_rgb_component(green, "Green (зеленый)")
        b = cls.validate_rgb_component(blue, "Blue (синий)")
        return r, g, b

    @classmethod
    def validate_style(
        cls,
        symbol: str,
        size: Any,
        red: Any,
        green: Any,
        blue: Any,
    ) -> PointStyle:
        """Комплексная валидация параметров стиля с возвратом проверенного объекта PointStyle."""
        valid_symbol = cls.validate_symbol(symbol)
        valid_size = cls.validate_size(size)
        r, g, b = cls.validate_rgb(red, green, blue)
        return PointStyle(
            symbol=valid_symbol,
            size=valid_size,
            red=r,
            green=g,
            blue=b,
        )

    @classmethod
    def validate_radius(cls, radius: Any, enabled: bool = True, zone_enabled: bool | None = None) -> float:
        """Валидация значения радиуса зоны в метрах (от 1 до 1 000 000 м)."""
        if zone_enabled is not None:
            enabled = zone_enabled

        if not enabled:
            if radius is None or radius == "" or radius == 0 or radius == 0.0:
                return 0.0

        if radius is None:
            raise ValidationError("val.zone.radius_empty")

        if isinstance(radius, str):
            cleaned = radius.strip().replace(",", ".")
            if not cleaned:
                if not enabled:
                    return 0.0
                raise ValidationError("val.zone.radius_empty")
            try:
                val = float(cleaned)
            except ValueError:
                raise ValidationError("val.zone.radius_format", value=radius)
        elif isinstance(radius, (int, float)):
            val = float(radius)
        else:
            raise ValidationError("val.zone.radius_type", type=type(radius).__name__)

        if not enabled and val == 0.0:
            return 0.0

        if val <= 0:
            raise ValidationError("val.zone.radius_positive", value=val)

        if val < 1.0 or val > 1_000_000.0:
            raise ValidationError("val.zone.radius_range", value=val)

        return val

    @classmethod
    def validate_opacity(cls, opacity: Any) -> int:
        """Валидация непрозрачности зоны (в процентах от 0 до 100)."""
        if opacity is None:
            raise ValidationError("val.zone.opacity_empty")

        if isinstance(opacity, str):
            cleaned = opacity.strip().replace(",", ".")
            if not cleaned:
                raise ValidationError("val.zone.opacity_empty")
            try:
                num = float(cleaned)
            except ValueError:
                raise ValidationError("val.zone.opacity_number")
        elif isinstance(opacity, (int, float)):
            num = float(opacity)
        else:
            raise ValidationError("val.zone.opacity_number")

        if not num.is_integer():
            num = round(num)

        int_val = int(num)
        if int_val < 0 or int_val > 100:
            raise ValidationError("val.zone.opacity_range", value=int_val)

        return int_val


def validate_radius(radius: Any, enabled: bool = True, zone_enabled: bool | None = None) -> float:
    """Модульная функция валидации радиуса зоны."""
    return StyleValidator.validate_radius(radius, enabled=enabled, zone_enabled=zone_enabled)


def validate_opacity(opacity: Any) -> int:
    """Модульная функция валидации прозрачности зоны."""
    return StyleValidator.validate_opacity(opacity)


@dataclass
class PointZoneStyle:
    """Параметры географической зоны вокруг точки."""

    enabled: bool = False
    radius_m: float = 0.0
    red: int = 220
    green: int = 30
    blue: int = 30
    opacity: int = 30
