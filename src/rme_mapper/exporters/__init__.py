"""Модуль экспорта и сохранения карты и проектов.

Отвечает за:
- Экспорт отображаемой карты с точками и радиусами в форматы PNG и JPEG;
- Оформление экспортируемой карты (заголовок, легенда, масштабная линейка, стрелка севера);
- Сериализацию и сохранение файлов проектов.
"""

from rme_mapper.exporters.decorations import MapDecorationRenderer
from rme_mapper.exporters.image_export_service import ImageExportService
from rme_mapper.exporters.map_renderer import MapRenderer
from rme_mapper.exporters.models import (
    MAX_IMAGE_DIMENSION,
    MIN_IMAGE_DIMENSION,
    ImageExportOptions,
)

__all__ = [
    "ImageExportOptions",
    "ImageExportService",
    "MapRenderer",
    "MapDecorationRenderer",
    "MIN_IMAGE_DIMENSION",
    "MAX_IMAGE_DIMENSION",
]
