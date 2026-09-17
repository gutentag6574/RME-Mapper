"""Абстрактный базовый интерфейс бэкенда доступа к картографическим данным."""

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any


class MapDataBackend(ABC):
    """Абстрактный интерфейс доступа к картографическим данным.

    Служит точкой расширения для различных реализаций:
    - ModernGeoPackageBackend (GeoPandas / pyogrio / Shapely);
    - LegacyGeoPackageBackend (будущая реализация на базе sqlite3 / pure Python).
    """

    @abstractmethod
    def exists(self, path: Path | str) -> bool:
        """Проверка существования и доступности файла карты."""
        ...

    @abstractmethod
    def list_layers(self, path: Path | str) -> list[tuple[str, str]]:
        """Получение списка слоев карты.

        Возвращает:
            Список кортежей вида (имя_слоя, тип_геометрии).
        """
        ...

    @abstractmethod
    def get_layer_metadata(self, path: Path | str, layer_name: str) -> dict[str, Any]:
        """Получение метаданных слоя (количество объектов, CRS, охват и поля) без полной загрузки данных."""
        ...

    @abstractmethod
    def read_layer(self, path: Path | str, layer_name: str) -> Any:
        """Чтение объектов слоя карты в виде коллекции геометрий (GeoDataFrame или структуры объектов)."""
        ...

    @abstractmethod
    def get_crs(self, path: Path | str, layer_name: str | None = None) -> str | None:
        """Получение строки системы координат (CRS) карты или указанного слоя."""
        ...

    @abstractmethod
    def get_extent(self, path: Path | str, layer_name: str | None = None) -> dict[str, float] | None:
        """Получение географического охвата {'xmin', 'ymin', 'xmax', 'ymax'} карты или слоя."""
        ...

    @abstractmethod
    def find_boundary_layer(self, path: Path | str) -> str | None:
        """Автоматический поиск слоя административной границы."""
        ...
