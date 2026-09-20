"""Модели данных и опции экспорта карты в растровое изображение."""

from dataclasses import dataclass
import math
from pathlib import Path


SUPPORTED_IMAGE_FORMATS = {"PNG", "JPEG", "JPG"}
SUPPORTED_EXTENT_MODES = {"current_view", "full_map", "all_points", "selected_points", "custom"}
SUPPORTED_LEGEND_POSITIONS = {"bottom_right", "bottom_left", "top_right", "top_left"}
SUPPORTED_LABELS_MODES = {"all", "selected", "none"}

MIN_IMAGE_DIMENSION = 256
MAX_IMAGE_DIMENSION = 16384
MAX_SAFE_MEMORY_BYTES = 1024 * 1024 * 1024  # 1 GB


@dataclass
class ImageExportOptions:
    """Параметры и настройки экспорта карты в растровое изображение."""

    file_path: Path | str
    format: str = "PNG"
    width_px: int = 1920
    height_px: int = 1080
    extent_mode: str = "current_view"
    custom_extent: tuple[float, float, float, float] | None = None

    # Содержимое
    include_points: bool = True
    include_zones: bool = True
    include_labels: bool = True
    labels_mode: str = "all"  # 'all', 'selected', 'none'
    label_content_mode: str = "name"  # 'name', 'number', 'number_name'

    # Оформление
    include_title: bool = True
    title_text: str = ""
    include_crs: bool = True
    include_legend: bool = True
    legend_position: str = "bottom_right"  # 'bottom_right', 'bottom_left', 'top_right', 'top_left'
    include_scale_bar: bool = True
    include_north_arrow: bool = True

    # Фон и качество
    background_color: str = "#FFFFFF"
    transparent_background: bool = False
    jpeg_quality: int = 92
    margin_px: int = 24

    def normalized_format(self) -> str:
        """Нормализованное имя формата ('PNG' или 'JPEG')."""
        fmt = (self.format or "PNG").strip().upper()
        if fmt == "JPG":
            return "JPEG"
        if fmt in ("PNG", "JPEG"):
            return fmt
        return "PNG"

    def estimated_memory_bytes(self) -> int:
        """Примерный объем оперативной памяти в байтах для QImage (RGBA 32-bit)."""
        return int(self.width_px) * int(self.height_px) * 4

    def scale_factor(self) -> float:
        """Коэффициент масштабирования элементов оформления относительно базового разрешения 1920x1080."""
        base_diag = math.hypot(1920.0, 1080.0)
        curr_diag = math.hypot(float(self.width_px), float(self.height_px))
        factor = curr_diag / base_diag
        return min(max(factor, 0.5), 5.0)

    def validate(self) -> list[str]:
        """Валидация опций экспорта. Возвращает список ошибок (пустой при успехе)."""
        errors: list[str] = []

        if not self.file_path or not str(self.file_path).strip():
            errors.append("Не указан путь для сохранения файла.")

        norm_fmt = self.normalized_format()
        if norm_fmt not in ("PNG", "JPEG"):
            errors.append(f"Неподдерживаемый формат: {self.format}. Поддерживаются: PNG, JPEG.")

        if not (MIN_IMAGE_DIMENSION <= self.width_px <= MAX_IMAGE_DIMENSION):
            errors.append(
                f"Ширина изображения должна быть от {MIN_IMAGE_DIMENSION} до {MAX_IMAGE_DIMENSION} px. Получено: {self.width_px}."
            )

        if not (MIN_IMAGE_DIMENSION <= self.height_px <= MAX_IMAGE_DIMENSION):
            errors.append(
                f"Высота изображения должна быть от {MIN_IMAGE_DIMENSION} до {MAX_IMAGE_DIMENSION} px. Получено: {self.height_px}."
            )

        if self.estimated_memory_bytes() >= MAX_SAFE_MEMORY_BYTES:
            errors.append(
                f"Превышен допустимый объем памяти: ~{self.estimated_memory_bytes() // (1024 * 1024)} МБ (максимум {MAX_SAFE_MEMORY_BYTES // (1024 * 1024)} МБ)."
            )

        if self.extent_mode not in SUPPORTED_EXTENT_MODES:
            errors.append(f"Неподдерживаемый режим охвата: {self.extent_mode}.")

        if self.extent_mode == "custom":
            if not self.custom_extent or len(self.custom_extent) != 4:
                errors.append("Для режима 'custom' необходимо передать 4 координаты охвата (min_x, min_y, max_x, max_y).")
            else:
                x1, y1, x2, y2 = self.custom_extent
                if x1 >= x2 or y1 >= y2:
                    errors.append(f"Некорректный пользовательский охват: ({x1}, {y1}, {x2}, {y2}).")

        if not (1 <= self.jpeg_quality <= 100):
            errors.append(f"Качество JPEG должно быть от 1 до 100. Получено: {self.jpeg_quality}.")

        if self.legend_position not in SUPPORTED_LEGEND_POSITIONS:
            errors.append(f"Неподдерживаемая позиция легенды: {self.legend_position}.")

        if self.labels_mode not in SUPPORTED_LABELS_MODES:
            errors.append(f"Неподдерживаемый режим подписей: {self.labels_mode}.")

        return errors
