"""Модуль работы с картами.

Отвечает за:
- Чтение метаданных каталога карт (metadata.json);
- Интерактивный холст карты (MapCanvas);
- Пути к картографическим данным.
"""

from rme_mapper.maps.map_canvas import MapCanvas
from rme_mapper.maps.map_config import get_default_geopackage_path, get_project_root

__all__ = ["MapCanvas", "get_default_geopackage_path", "get_project_root"]
