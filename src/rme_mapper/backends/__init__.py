"""Пакет бэкендов доступа к ГИС-данным GeoPoint Mapper."""

from rme_mapper.backends.base import MapDataBackend
from rme_mapper.backends.modern import ModernGeoPackageBackend
from rme_mapper.backends.legacy_placeholder import LegacyGeoPackageBackend
from rme_mapper.backends.factory import BackendFactory, get_backend

__all__ = [
    "MapDataBackend",
    "ModernGeoPackageBackend",
    "LegacyGeoPackageBackend",
    "BackendFactory",
    "get_backend",
]
