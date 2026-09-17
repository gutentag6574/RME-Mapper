"""Фабрика и реестр ГИС-бэкендов (BackendFactory / GISBackendRegistry)."""

import logging
from typing import Type

from rme_mapper.backends.base import MapDataBackend

logger = logging.getLogger("rme_mapper.backends.factory")


class BackendFactory:
    """Реестр и фабрика для получения экземпляров картографических бэкендов."""

    _registry: dict[str, Type[MapDataBackend]] = {}
    _default_backend: str = "modern"

    @classmethod
    def _ensure_defaults(cls) -> None:
        """Ленивая регистрация бэкендов по умолчанию для предотвращения циклических импортов."""
        if not cls._registry:
            from rme_mapper.backends.modern import ModernGeoPackageBackend
            from rme_mapper.backends.legacy_placeholder import LegacyGeoPackageBackend

            cls._registry["modern"] = ModernGeoPackageBackend
            cls._registry["legacy"] = LegacyGeoPackageBackend

    @classmethod
    def register(cls, name: str, backend_cls: Type[MapDataBackend]) -> None:
        """Регистрация нового класса бэкенда."""
        cls._ensure_defaults()
        key = name.strip().lower()
        cls._registry[key] = backend_cls
        logger.debug("Зарегистрирован бэкенд: %s -> %s", key, backend_cls.__name__)

    @classmethod
    def get_backend(cls, name: str | None = None) -> MapDataBackend:
        """Получение экземпляра бэкенда по имени.

        По умолчанию (name=None) возвращает ModernGeoPackageBackend.
        """
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
    def list_available(cls) -> list[str]:
        """Список зарегистрированных имен бэкендов."""
        cls._ensure_defaults()
        return sorted(cls._registry.keys())

    @classmethod
    def set_default(cls, name: str) -> None:
        """Установка бэкенда по умолчанию."""
        cls._ensure_defaults()
        key = name.strip().lower()
        if key not in cls._registry:
            raise KeyError(f"Невозможно установить неизвестный бэкенд по умолчанию: '{name}'")
        cls._default_backend = key


def get_backend(name: str | None = None) -> MapDataBackend:
    """Удобный модуль-уровневый хелпер для получения активного ГИС-бэкенда."""
    return BackendFactory.get_backend(name)
