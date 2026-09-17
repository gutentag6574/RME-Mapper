"""Сервисный слой приложения.

Отвечает за:
- Чтение векторных данных GeoPackage (GeoPackageService);
- Реестр, типизацию и кэширование картографических слоев (LayerService);
- Хранение и управление пользовательскими точками (PointService);
- Координатные вычисления и геометрические проверки (CoordinateService);
- Преобразование систем координат (CRS transformation) через pyproj.
"""

from rme_mapper.services.app_settings_service import AppSettingsService
from rme_mapper.services.coordinate_service import CoordinateService
from rme_mapper.services.geodesic_service import GeodesicService
from rme_mapper.services.geopackage_service import GeoPackageService
from rme_mapper.services.layer_service import LayerService
from rme_mapper.services.map_catalog_service import MapCatalogService
from rme_mapper.services.point_service import PointService
from rme_mapper.services.project_service import ProjectService

__all__ = [
    "AppSettingsService",
    "CoordinateService",
    "GeodesicService",
    "GeoPackageService",
    "LayerService",
    "MapCatalogService",
    "PointService",
    "ProjectService",
]

