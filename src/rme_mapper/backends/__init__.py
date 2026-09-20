"""Пакет бэкендов доступа к ГИС-данным GeoPoint Mapper."""

from rme_mapper.backends.base import MapDataBackend
from rme_mapper.backends.modern import ModernGeoPackageBackend
from rme_mapper.backends.legacy_placeholder import LegacyGeoPackageBackend
from rme_mapper.backends.raster_backend import RasterDataBackend
from rme_mapper.backends.modern_raster import ModernGeoTiffBackend
from rme_mapper.backends.legacy_raster_placeholder import LegacyRasterBackend
from rme_mapper.backends.factory import BackendFactory, get_backend, get_raster_backend

__all__ = [
    "MapDataBackend",
    "ModernGeoPackageBackend",
    "LegacyGeoPackageBackend",
    "RasterDataBackend",
    "ModernGeoTiffBackend",
    "LegacyRasterBackend",
    "BackendFactory",
    "get_backend",
    "get_raster_backend",
]
