"""Модель и валидатор визуального стиля пользовательской точки."""
from __future__ import annotations


import logging
import math
from dataclasses import dataclass
from typing import Any

from rme_mapper.coordinates.validator import ValidationError

logger = logging.getLogger("rme_mapper.models.point_style")

ALLOWED_SYMBOLS: set[str] = {"circle", "square", "triangle"}
ALLOWED_BORDER_STYLES: set[str] = {"solid", "dash", "dot"}
MIN_SIZE: float = 4.0
MAX_SIZE: float = 50.0
MIN_RGB: int = 0
MAX_RGB: int = 255
MIN_STROKE_WIDTH: float = 0.0
MAX_STROKE_WIDTH: float = 10.0
MIN_BORDER_WIDTH: float = 0.0
MAX_BORDER_WIDTH: float = 10.0
MAX_OBJECT_NUMBER_LEN: int = 100
MAX_CATEGORY_LEN: int = 200
MAX_DESCRIPTION_LEN: int = 8192


@dataclass
class PointStyle:
    """Визуальный стиль отображения пользовательской точки."""

    symbol: str = "circle"
    size: float = 12.0
    red: int = 220
    green: int = 30
    blue: int = 30
    stroke_red: int = 0
    stroke_green: int = 0
    stroke_blue: int = 0
    stroke_width: float = 1.0
    opacity: int = 100


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

        if not math.isfinite(val) or val < MIN_SIZE or val > MAX_SIZE:
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
        from rme_mapper.i18n import tr
        r = cls.validate_rgb_component(red, tr("val.style.rgb_red"))
        g = cls.validate_rgb_component(green, tr("val.style.rgb_green"))
        b = cls.validate_rgb_component(blue, tr("val.style.rgb_blue"))
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

        if not math.isfinite(num):
            raise ValidationError("val.zone.opacity_number")

        if not num.is_integer():
            num = round(num)

        int_val = int(num)
        if int_val < 0 or int_val > 100:
            raise ValidationError("val.zone.opacity_range", value=int_val)

        return int_val

    @classmethod
    def validate_stroke_width(cls, width: Any) -> float:
        """Проверка допустимой толщины обводки маркера (0.0 .. 10.0 px)."""
        if width is None or width == "":
            return 1.0
        if isinstance(width, str):
            cleaned = width.strip().replace(",", ".")
            try:
                val = float(cleaned)
            except ValueError:
                raise ValidationError("val.style.stroke_width_format", min=MIN_STROKE_WIDTH, max=MAX_STROKE_WIDTH)
        elif isinstance(width, (int, float)):
            val = float(width)
        else:
            raise ValidationError("val.style.stroke_width_number")

        if not math.isfinite(val) or val < MIN_STROKE_WIDTH or val > MAX_STROKE_WIDTH:
            raise ValidationError("val.style.stroke_width_range", min=MIN_STROKE_WIDTH, max=MAX_STROKE_WIDTH, value=val)
        return val

    @classmethod
    def validate_border_width(cls, width: Any) -> float:
        """Проверка допустимой толщины границы зоны (0.0 .. 10.0 px)."""
        if width is None or width == "":
            return 1.0
        if isinstance(width, str):
            cleaned = width.strip().replace(",", ".")
            try:
                val = float(cleaned)
            except ValueError:
                raise ValidationError("val.zone.border_width_format", min=MIN_BORDER_WIDTH, max=MAX_BORDER_WIDTH)
        elif isinstance(width, (int, float)):
            val = float(width)
        else:
            raise ValidationError("val.zone.border_width_number")

        if not math.isfinite(val) or val < MIN_BORDER_WIDTH or val > MAX_BORDER_WIDTH:
            raise ValidationError("val.zone.border_width_range", min=MIN_BORDER_WIDTH, max=MAX_BORDER_WIDTH, value=val)
        return val

    @classmethod
    def validate_border_style(cls, style: Any) -> str:
        """Проверка стиля границы зоны ('solid', 'dash', 'dot')."""
        if not style:
            return "solid"
        if not isinstance(style, str):
            raise ValidationError("val.zone.border_style_str")
        s = style.strip().lower()
        # Aliases
        if s in ("dashed", "штриховая"):
            s = "dash"
        elif s in ("dotted", "точечная"):
            s = "dot"
        elif s in ("сплошная",):
            s = "solid"

        if s not in ALLOWED_BORDER_STYLES:
            raise ValidationError("val.zone.border_style_unknown", value=style, allowed=", ".join(sorted(ALLOWED_BORDER_STYLES)))
        return s

    @classmethod
    def validate_object_number(cls, num: Any) -> str:
        """Валидация пользовательского номера объекта (длина <= 100)."""
        if num is None:
            return ""
        s = str(num).strip()
        if len(s) > MAX_OBJECT_NUMBER_LEN:
            raise ValidationError("val.object.number_length", max=MAX_OBJECT_NUMBER_LEN, value=len(s))
        return s

    @classmethod
    def validate_category(cls, category: Any) -> str:
        """Валидация категории объекта (длина <= 200)."""
        if category is None:
            return ""
        s = str(category).strip()
        if len(s) > MAX_CATEGORY_LEN:
            raise ValidationError("val.object.category_length", max=MAX_CATEGORY_LEN, value=len(s))
        return s

    @classmethod
    def validate_description(cls, description: Any) -> str:
        """Валидация многострочного описания (длина <= 8192)."""
        if description is None:
            return ""
        s = str(description)
        if len(s) > MAX_DESCRIPTION_LEN:
            raise ValidationError("val.object.description_length", max=MAX_DESCRIPTION_LEN, value=len(s))
        return s


def validate_radius(radius: Any, enabled: bool = True, zone_enabled: bool | None = None) -> float:
    """Модульная функция валидации радиуса зоны."""
    return StyleValidator.validate_radius(radius, enabled=enabled, zone_enabled=zone_enabled)


def validate_opacity(opacity: Any) -> int:
    """Модульная функция валидации прозрачности зоны."""
    return StyleValidator.validate_opacity(opacity)


def validate_stroke_width(width: Any) -> float:
    """Модульная функция валидации толщины обводки."""
    return StyleValidator.validate_stroke_width(width)


def validate_border_width(width: Any) -> float:
    """Модульная функция валидации толщины границы зоны."""
    return StyleValidator.validate_border_width(width)


def validate_border_style(style: Any) -> str:
    """Модульная функция валидации стиля границы зоны."""
    return StyleValidator.validate_border_style(style)


def validate_object_number(number: Any) -> str:
    """Модульная функция валидации номера объекта."""
    return StyleValidator.validate_object_number(number)


def validate_category(category: Any) -> str:
    """Модульная функция валидации категории."""
    return StyleValidator.validate_category(category)


def validate_description(description: Any) -> str:
    """Модульная функция валидации описания."""
    return StyleValidator.validate_description(description)


@dataclass
class PointZoneStyle:
    """Параметры географической зоны вокруг точки."""

    enabled: bool = False
    radius_m: float = 0.0
    red: int = 220
    green: int = 30
    blue: int = 30
    opacity: int = 30
    border_red: int = 220
    border_green: int = 30
    border_blue: int = 30
    border_width: float = 1.0
    border_style: str = "solid"
