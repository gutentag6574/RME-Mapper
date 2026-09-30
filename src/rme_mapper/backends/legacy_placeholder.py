"""Архитектурный плейсхолдер для будущего бэкенда устаревших платформ (LegacyGeoPackageBackend)."""
from __future__ import annotations


from pathlib import Path
from typing import Any

from rme_mapper.backends.base import MapDataBackend


class LegacyGeoPackageBackend(MapDataBackend):
    """Архитектурная заготовка для будущего бэкенда под Windows 7 и Windows XP.

    В будущих этапах проектной разработки данная реализация будет использовать:
    - Модуль стандартной библиотеки Python `sqlite3` для прямого чтения таблиц
      GeoPackage (`gpkg_contents`, `gpkg_geometry_columns`, данных слоя);
    - Парсер бинарных структур WKB / GPKG Geometry BLOB без тяжелых внешних C-библиотек;
    - Аналитические формулы Карни / Винсенти на чистом Python для геодезических расчетов.

    На текущем этапе кодовая база функционирует в режиме Modern Build. Попытка вызвать методы
    данного класса вызывает понятное исключение NotImplementedError.
    """

    _NOT_IMPLEMENTED_MSG = (
        "LegacyGeoPackageBackend запланирован для отдельных будущих этапов "
        "сборок под Windows 7 / Windows XP. В текущей версии используется ModernGeoPackageBackend."
    )

    def exists(self, path: Path | str) -> bool:
        """Проверка существования файла карты."""
        raise NotImplementedError(self._NOT_IMPLEMENTED_MSG)

    def list_layers(self, path: Path | str) -> list[tuple[str, str]]:
        """Получение списка слоев карты."""
        raise NotImplementedError(self._NOT_IMPLEMENTED_MSG)

    def get_layer_metadata(self, path: Path | str, layer_name: str) -> dict[str, Any]:
        """Получение метаданных слоя."""
        raise NotImplementedError(self._NOT_IMPLEMENTED_MSG)

    def read_layer(self, path: Path | str, layer_name: str) -> Any:
        """Чтение объектов слоя карты."""
        raise NotImplementedError(self._NOT_IMPLEMENTED_MSG)

    def get_crs(self, path: Path | str, layer_name: str | None = None) -> str | None:
        """Получение системы координат (CRS)."""
        raise NotImplementedError(self._NOT_IMPLEMENTED_MSG)

    def get_extent(self, path: Path | str, layer_name: str | None = None) -> dict[str, float] | None:
        """Получение географического охвата."""
        raise NotImplementedError(self._NOT_IMPLEMENTED_MSG)

    def find_boundary_layer(self, path: Path | str) -> str | None:
        """Поиск слоя административной границы."""
        raise NotImplementedError(self._NOT_IMPLEMENTED_MSG)
