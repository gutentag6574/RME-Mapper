"""Сервис сохранения и экспорта растрового изображения карты (ImageExportService)."""

import logging
import os
from pathlib import Path
from typing import Any
import uuid

from PySide6.QtGui import QImage, QPainterPath, QPen, QBrush

from rme_mapper.exporters.map_renderer import MapRenderer
from rme_mapper.exporters.models import ImageExportOptions
from rme_mapper.models.map_point import MapPoint

logger = logging.getLogger("rme_mapper.exporters.service")


class ImageExportService:
    """Сервис высокоуровневой генерации и атомарного сохранения карты в файл изображения."""

    @classmethod
    def export_image(
        cls,
        options: ImageExportOptions,
        active_crs: str,
        target_extent: tuple[float, float, float, float],
        loaded_layers_render_data: list[tuple[str, QPainterPath, QPen, QBrush, float, bool]] | None = None,
        points: list[MapPoint] | None = None,
        selected_point_ids: set[str] | None = None,
    ) -> Path:
        """Рендеринг и сохранение изображения в файл с гарантией атомарности.

        Возвращает:
            Path: Абсолютный путь к сохраненному файлу.

        Исключения:
            ValueError: При некорректных опциях или параметрах.
            PermissionError: При отсутствии прав на запись в целевой каталог.
            RuntimeError: При сбое рендеринга или сохранения в файл.
        """
        # 1. Валидация входных опций
        errors = options.validate()
        if errors:
            raise ValueError(f"Ошибки валидации: {'; '.join(errors)}")

        target_path = Path(options.file_path).resolve()
        parent_dir = target_path.parent

        if not parent_dir.exists():
            try:
                parent_dir.mkdir(parents=True, exist_ok=True)
            except Exception as e:
                raise PermissionError(f"Не удалось создать директорию для сохранения: {parent_dir}. Ошибка: {e}") from e

        # Проверка прав на запись в каталог
        if not os.access(parent_dir, os.W_OK):
            raise PermissionError(f"Каталог недоступен для записи: {parent_dir}")

        # 2. Рендеринг в QImage
        image: QImage = MapRenderer.render_map(
            options=options,
            active_crs=active_crs,
            target_extent=target_extent,
            loaded_layers_render_data=loaded_layers_render_data,
            points=points,
            selected_point_ids=selected_point_ids,
        )

        if image.isNull():
            raise RuntimeError("Не удалось сформировать растровое изображение (image is null).")

        # 3. Атомарное сохранение через временный файл
        norm_fmt = options.normalized_format()
        temp_name = f".tmp_{uuid.uuid4().hex}_{target_path.name}"
        temp_path = parent_dir / temp_name

        try:
            # Для JPEG принудительно конвертируем в RGB32, если был ARGB32
            save_image = image
            if norm_fmt == "JPEG":
                if image.hasAlphaChannel() or image.format() == QImage.Format.Format_ARGB32_Premultiplied:
                    save_image = image.convertToFormat(QImage.Format.Format_RGB32)
                quality = int(options.jpeg_quality)
                success = save_image.save(str(temp_path), "JPEG", quality=quality)
            else:
                success = save_image.save(str(temp_path), "PNG")

            if not success or not temp_path.exists() or temp_path.stat().st_size == 0:
                raise RuntimeError(f"Qt не смог сохранить изображение в формате {norm_fmt}: {target_path}")

            # Атомарная замена целевого файла
            os.replace(str(temp_path), str(target_path))
            logger.info("Карта успешно экспортирована: %s (%dx%d, %s)", target_path, options.width_px, options.height_px, norm_fmt)
            return target_path

        except Exception as e:
            # Очистка временного файла при ошибке
            if temp_path.exists():
                try:
                    temp_path.unlink()
                except Exception:
                    pass
            logger.exception("Ошибка экспорта карты в файл %s: %s", target_path, e)
            raise
