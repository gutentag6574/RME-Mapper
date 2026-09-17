"""Модель и валидатор визуального стиля пользовательской точки."""

import logging
from dataclasses import dataclass
from typing import Any

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
            raise ValueError(f"Форма маркера должна быть строкой. Получено: {type(symbol).__name__}")

        sym = symbol.strip().lower()
        if sym not in ALLOWED_SYMBOLS:
            raise ValueError(
                f"Недопустимая форма маркера: '{symbol}'. "
                f"Разрешены: {', '.join(sorted(ALLOWED_SYMBOLS))}"
            )
        return sym

    @classmethod
    def validate_size(cls, size: Any) -> float:
        """Проверка допустимого размера маркера (от 4.0 до 50.0 px)."""
        if size is None:
            raise ValueError("Размер маркера не может быть пустым.")

        if isinstance(size, str):
            cleaned = size.strip().replace(",", ".")
            if not cleaned:
                raise ValueError("Размер маркера не может быть пустым.")
            try:
                val = float(cleaned)
            except ValueError:
                raise ValueError(f"Размер маркера должен быть числом от {MIN_SIZE} до {MAX_SIZE} px.")
        elif isinstance(size, (int, float)):
            val = float(size)
        else:
            raise ValueError("Размер маркера должен быть числом.")

        if val < MIN_SIZE or val > MAX_SIZE:
            raise ValueError(
                f"Размер маркера должен быть в диапазоне от {MIN_SIZE} до {MAX_SIZE} px. "
                f"Получено: {val}"
            )
        return val

    @classmethod
    def validate_rgb_component(cls, value: Any, component_name: str) -> int:
        """Проверка отдельной цветовой компоненты (0..255)."""
        if value is None:
            raise ValueError(f"Компонента цвета {component_name} не может быть пустой.")

        if isinstance(value, str):
            cleaned = value.strip()
            if not cleaned:
                raise ValueError(f"Компонента цвета {component_name} не может быть пустой.")
            try:
                val = float(cleaned.replace(",", "."))
            except ValueError:
                raise ValueError(f"Компонента цвета {component_name} должна быть целым числом от 0 до 255.")
            if not val.is_integer():
                raise ValueError(f"Компонента цвета {component_name} должна быть целым числом.")
            int_val = int(val)
        elif isinstance(value, (int, float)):
            if isinstance(value, float) and not value.is_integer():
                raise ValueError(f"Компонента цвета {component_name} должна быть целым числом.")
            int_val = int(value)
        else:
            raise ValueError(f"Компонента цвета {component_name} должна быть целым числом от 0 до 255.")

        if int_val < MIN_RGB or int_val > MAX_RGB:
            raise ValueError(
                f"Компонента цвета {component_name} должна быть в диапазоне от 0 до 255. "
                f"Получено: {int_val}"
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
