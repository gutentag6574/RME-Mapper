"""Фабрика и реестр ГИС-бэкендов (BackendFactory / GISBackendRegistry)."""
from __future__ import annotations


import logging
from typing import Type

from rme_mapper.backends.base import MapDataBackend
from rme_mapper.backends.raster_backend import RasterDataBackend

logger = logging.getLogger("rme_mapper.backends.factory")


class BackendFactory:
    """Реестр и фабрика для получения экземпляров картографических бэкендов."""

    _registry: dict[str, Type[MapDataBackend]] = {}
    _default_backend: str = "modern"

    _raster_registry: dict[str, Type[RasterDataBackend]] = {}
    _default_raster_backend: str = "modern"
    _raster_instances: dict[str, RasterDataBackend] = {}

    @classmethod
    def _ensure_defaults(cls) -> None:
        """Ленивая регистрация векторных бэкендов по умолчанию."""
        if not cls._registry:
            from rme_mapper.backends.modern import ModernGeoPackageBackend
            from rme_mapper.backends.legacy_placeholder import LegacyGeoPackageBackend

            cls._registry["modern"] = ModernGeoPackageBackend
            cls._registry["legacy"] = LegacyGeoPackageBackend

    @classmethod
    def _ensure_raster_defaults(cls) -> None:
        """Ленивая регистрация растровых бэкендов по умолчанию."""
        if not cls._raster_registry:
            from rme_mapper.backends.modern_raster import ModernGeoTiffBackend
            from rme_mapper.backends.legacy_raster_placeholder import LegacyRasterBackend

            cls._raster_registry["modern"] = ModernGeoTiffBackend
            cls._raster_registry["legacy"] = LegacyRasterBackend

    @classmethod
    def register(cls, name: str, backend_cls: Type[MapDataBackend]) -> None:
        """Регистрация нового класса векторного бэкенда."""
        cls._ensure_defaults()
        key = name.strip().lower()
        cls._registry[key] = backend_cls
        logger.debug("Зарегистрирован векторный бэкенд: %s -> %s", key, backend_cls.__name__)

    @classmethod
    def register_raster(cls, name: str, backend_cls: Type[RasterDataBackend]) -> None:
        """Регистрация нового класса растрового бэкенда."""
        cls._ensure_raster_defaults()
        key = name.strip().lower()
        cls._raster_registry[key] = backend_cls
        logger.debug("Зарегистрирован растровый бэкенд: %s -> %s", key, backend_cls.__name__)

    @classmethod
    def get_backend(cls, name: str | None = None) -> MapDataBackend:
        """Получение экземпляра векторного бэкенда по имени."""
        cls._ensure_defaults()
        key = (name or cls._default_backend).strip().lower()
        if key not in cls._registry:
            raise KeyError(
                f"Неизвестный ГИС-бэкенд: '{name}'. "
                f"Доступные бэкенды: {', '.join(sorted(cls._registry.keys()))}"
            )
        backend_cls = cls._registry[key]
        return backend_cls()

    @classmethod
    def get_raster_backend(cls, name: str | None = None) -> RasterDataBackend:
        """Получение (или переиспользование) экземпляра растрового бэкенда по имени."""
        cls._ensure_raster_defaults()
        key = (name or cls._default_raster_backend).strip().lower()
        if key not in cls._raster_registry:
            raise KeyError(
                f"Неизвестный растровый бэкенд: '{name}'. "
                f"Доступные бэкенды: {', '.join(sorted(cls._raster_registry.keys()))}"
            )
        if key not in cls._raster_instances:
            backend_cls = cls._raster_registry[key]
            cls._raster_instances[key] = backend_cls()
        return cls._raster_instances[key]

    @classmethod
    def list_available(cls) -> list[str]:
        """Список зарегистрированных имен векторных бэкендов."""
        cls._ensure_defaults()
        return sorted(cls._registry.keys())

    @classmethod
    def list_available_raster(cls) -> list[str]:
        """Список зарегистрированных имен растровых бэкендов."""
        cls._ensure_raster_defaults()
        return sorted(cls._raster_registry.keys())

    @classmethod
    def set_default(cls, name: str) -> None:
        """Установка векторного бэкенда по умолчанию."""
        cls._ensure_defaults()
        key = name.strip().lower()
        if key not in cls._registry:
            raise KeyError(f"Невозможно установить неизвестный бэкенд по умолчанию: '{name}'")
        cls._default_backend = key

    @classmethod
    def set_default_raster(cls, name: str) -> None:
        """Установка растрового бэкенда по умолчанию."""
        cls._ensure_raster_defaults()
        key = name.strip().lower()
        if key not in cls._raster_registry:
            raise KeyError(f"Невозможно установить неизвестный растровый бэкенд по умолчанию: '{name}'")
        cls._default_raster_backend = key

    # --- Capability API (Этап 16 / Этап 24) ---

    @classmethod
    def supports_geopackage(cls) -> bool:
        """Проверка поддержки формата векторных карт GeoPackage в текущей среде."""
        from rme_mapper.services.runtime_capabilities import RuntimeCapabilities
        return RuntimeCapabilities.supports_geopackage()

    @classmethod
    def supports_geotiff(cls) -> bool:
        """Проверка поддержки растровых карт GeoTIFF в текущей среде."""
        from rme_mapper.services.runtime_capabilities import RuntimeCapabilities
        return RuntimeCapabilities.supports_geotiff()

    @classmethod
    def supports_source_type(cls, source_type: str) -> bool:
        """Проверка поддержки типа источника карты ('geopackage', 'geotiff', 'online_xyz', 'georeferenced_image')."""
        from rme_mapper.services.runtime_capabilities import RuntimeCapabilities
        return RuntimeCapabilities.supports_source_type(source_type)


def get_backend(name: str | None = None) -> MapDataBackend:
    """Модуль-уровневый хелпер для получения векторного ГИС-бэкенда."""
    return BackendFactory.get_backend(name)


def get_raster_backend(name: str | None = None) -> RasterDataBackend:
    """Модуль-уровневый хелпер для получения растрового ГИС-бэкенда."""
    return BackendFactory.get_raster_backend(name)
