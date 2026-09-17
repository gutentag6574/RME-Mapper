"""Сервисный слой приложения.

Отвечает за:
- Чтение векторных данных GeoPackage (GeoPackageService);
- Реестр, типизацию и кэширование картографических слоев (LayerService);
- Преобразование систем координат (CRS transformation) через pyproj;
- Расчет расстояний, смещений и проекций.
"""

from rme_mapper.services.geopackage_service import GeoPackageService
from rme_mapper.services.layer_service import LayerService

__all__ = ["GeoPackageService", "LayerService"]
