"""Чистый калькулятор координатной сетки (GridCalculator) для экранного отображения и экспорта."""

from dataclasses import dataclass
import logging
import math

import pyproj

logger = logging.getLogger("rme_mapper.services.grid")

# Стандартные адаптивные шаги для географической сетки (в десятичных градусах)
GEOGRAPHIC_STEPS: list[float] = [
    0.00005,
    0.0001,
    0.0002,
    0.0005,
    0.001,
    0.002,
    0.005,
    0.01,
    0.02,
    0.05,
    0.1,
    0.2,
    0.25,
    0.5,
    1.0,
    2.0,
    5.0,
    10.0,
    15.0,
    20.0,
    30.0,
    45.0,
    60.0,
]

# Стандартные адаптивные шаги для спроецированной сетки (в метрах)
PROJECTED_STEPS: list[float] = [
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

MAX_GRID_LINES_SAFETY_LIMIT = 30
TARGET_LINES_MIN = 4
TARGET_LINES_MAX = 12


@dataclass(frozen=True)
class GridLine:
    """Представление одной линии координатной сетки."""

    coord: float
    label: str
    is_vertical: bool  # True: вертикальная (X / lon), False: горизонтальная (Y / lat)


@dataclass(frozen=True)
class GridResult:
    """Результат расчета координатной сетки."""

    step_x: float
    step_y: float
    vertical_lines: list[GridLine]
    horizontal_lines: list[GridLine]
    is_geographic: bool
    units: str


class GridCalculator:
    """Сервис чистых вычислений линий и подписей координатной сетки."""

    @staticmethod
    def get_crs_info(crs_str: str) -> tuple[bool, str]:
        """Определение типа CRS и единиц измерения: (is_geographic, units_name)."""
        clean_crs = (crs_str or "").strip()
        if not clean_crs:
            return True, "degree"

        try:
            crs = pyproj.CRS.from_user_input(clean_crs)
            if crs.is_geographic:
                return True, "degree"

            unit_name = "metre"
            if crs.axis_info:
                unit_name = (crs.axis_info[0].unit_name or "metre").lower()
            return False, unit_name
        except Exception as e:
            logger.warning("Ошибка определения свойств CRS '%s': %s", crs_str, e)
            return False, "unknown"

    @classmethod
    def choose_step(cls, span: float, steps: list[float]) -> float:
        """Подбор шага сетки для попадания в диапазон 4..12 линий с предохранителем."""
        if span <= 0:
            return steps[0]

        # Ищем шаг, при котором span / step в диапазоне [TARGET_LINES_MIN, TARGET_LINES_MAX]
        target = span / 7.0  # идеальное ориентировочное число линий ~ 7
        best_step = steps[-1]
        for s in steps:
            if s >= target:
                best_step = s
                break

        # Предохранитель: не более MAX_GRID_LINES_SAFETY_LIMIT линий
        idx = steps.index(best_step)
        while span / best_step > MAX_GRID_LINES_SAFETY_LIMIT and idx < len(steps) - 1:
            idx += 1
            best_step = steps[idx]

        return best_step

    @staticmethod
    def format_geographic_label(val: float, is_lon: bool, step: float) -> str:
        """Форматирование координаты географической сетки в компактном DD формате (напр. 56.5° N, 47.0° E)."""
        # Число знаков после запятой определяем по шагу
        if step >= 1.0:
            decimals = 0
        elif step >= 0.1:
            decimals = 1
        elif step >= 0.01:
            decimals = 2
        elif step >= 0.001:
            decimals = 3
        else:
            decimals = 4

        abs_val = abs(val)
        if abs_val < 1e-9:
            return "0°"

        if is_lon:
            hemisphere = "E" if val > 0 else "W"
        else:
            hemisphere = "N" if val > 0 else "S"

        if decimals == 0:
            return f"{round(abs_val)}° {hemisphere}"
        return f"{abs_val:.{decimals}f}° {hemisphere}"

    @staticmethod
    def format_projected_label(val: float, step: float) -> str:
        """Форматирование координаты спроецированной сетки (без scientific notation)."""
        if step >= 1.0 or val.is_integer():
            return f"{int(round(val))}"
        return f"{val:.1f}"

    @classmethod
    def calculate_grid(
        cls,
        extent: tuple[float, float, float, float],
        crs_str: str,
    ) -> GridResult | None:
        """Расчет координатной сетки для заданного охвата (min_x, min_y, max_x, max_y) и CRS."""
        min_x, min_y, max_x, max_y = extent
        dx = max_x - min_x
        dy = max_y - min_y

        if dx <= 0 or dy <= 0:
            return None

        is_geo, units = cls.get_crs_info(crs_str)

        # Проверка неметровых спроецированных CRS (футы и т.д.)
        if not is_geo and units not in ("metre", "meter", "m", "unknown"):
            logger.info("Проекция использует единицы '%s', отличные от метров; сетка отключена", units)
            return None

        if is_geo:
            step_x = cls.choose_step(dx, GEOGRAPHIC_STEPS)
            step_y = cls.choose_step(dy, GEOGRAPHIC_STEPS)
        else:
            step_x = cls.choose_step(dx, PROJECTED_STEPS)
            step_y = cls.choose_step(dy, PROJECTED_STEPS)

        # Вычисление координат вертикальных линий
        v_lines: list[GridLine] = []
        start_x = math.ceil(min_x / step_x) * step_x
        cur_x = start_x
        count_x = 0
        while cur_x <= max_x + 1e-9 and count_x < MAX_GRID_LINES_SAFETY_LIMIT:
            if is_geo:
                lbl = cls.format_geographic_label(cur_x, is_lon=True, step=step_x)
            else:
                lbl = cls.format_projected_label(cur_x, step=step_x)
            v_lines.append(GridLine(coord=cur_x, label=lbl, is_vertical=True))
            cur_x += step_x
            count_x += 1

        # Вычисление координат горизонтальных линий
        h_lines: list[GridLine] = []
        start_y = math.ceil(min_y / step_y) * step_y
        cur_y = start_y
        count_y = 0
        while cur_y <= max_y + 1e-9 and count_y < MAX_GRID_LINES_SAFETY_LIMIT:
            if is_geo:
                lbl = cls.format_geographic_label(cur_y, is_lon=False, step=step_y)
            else:
                lbl = cls.format_projected_label(cur_y, step=step_y)
            h_lines.append(GridLine(coord=cur_y, label=lbl, is_vertical=False))
            cur_y += step_y
            count_y += 1

        return GridResult(
            step_x=step_x,
            step_y=step_y,
            vertical_lines=v_lines,
            horizontal_lines=h_lines,
            is_geographic=is_geo,
            units=units,
        )
