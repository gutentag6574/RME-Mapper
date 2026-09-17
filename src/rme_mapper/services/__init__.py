"""Сервисный слой приложения.

Отвечает за:
- Чтение векторных данных GeoPackage (GeoPackageService);
- Преобразование систем координат (CRS transformation) через pyproj;
- Расчет расстояний, смещений и проекций без жесткого зашивания CRS в UI.
"""

from rme_mapper.services.geopackage_service import GeoPackageService

__all__ = ["GeoPackageService"]
