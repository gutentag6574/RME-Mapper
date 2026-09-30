"""Абстрактный базовый интерфейс бэкенда доступа к растровым геоданным."""
from __future__ import annotations


from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any
import numpy as np


class RasterDataBackend(ABC):
    """Абстрактный интерфейс доступа к растровым картографическим данным (GeoTIFF).

    Точка расширения для:
    - ModernGeoTiffBackend (на базе rasterio / GDAL для Windows 10/11 x64);
    - LegacyRasterBackend (архитектурный плейсхолдер для будущих сборок Windows XP / Windows 7).
    """

    @abstractmethod
    def inspect_raster(self, path: Path | str) -> dict[str, Any]:
        """Инспекция метаданных растрового файла без чтения массива пикселей в память.

        Возвращает словарь с ключами:
        - width: int
        - height: int
        - count / band_count: int
        - crs: str | None
        - bounds: tuple[float, float, float, float] (left, bottom, right, top)
        - extent: dict[str, float] (xmin, ymin, xmax, ymax)
        - transform: tuple[float, ...] (a, b, c, d, e, f)
        - dtype: str
        - nodata: float | int | None
        - has_alpha: bool
        - has_mask: bool
        - overviews: list[int]
        - is_valid_georef: bool
        """
        ...

    @abstractmethod
    def get_crs(self, path: Path | str) -> str | None:
        """Получение строки системы координат (CRS) растра."""
        ...

    @abstractmethod
    def get_extent(self, path: Path | str) -> dict[str, float] | None:
        """Получение географического охвата {'xmin', 'ymin', 'xmax', 'ymax'} в единицах CRS."""
        ...

    @abstractmethod
    def get_size(self, path: Path | str) -> tuple[int, int] | None:
        """Получение размеров растра (ширина, высота) в пикселях."""
        ...

    @abstractmethod
    def get_band_count(self, path: Path | str) -> int:
        """Получение количества каналов (bands) растра."""
        ...

    @abstractmethod
    def get_nodata(self, path: Path | str) -> float | None:
        """Получение значения NoData, если оно определено."""
        ...

    @abstractmethod
    def read_preview(
        self,
        path: Path | str,
        max_dimension: int = 4096,
        max_preview_dimension: int | None = None,
    ) -> tuple[np.ndarray, dict[str, Any]]:
        """Чтение обзорного уменьшенного представления растра (preview).

        Использует внутренние overviews файла или субдискретизацию (out_shape)
        для предотвращения избыточного расхода памяти.

        Возвращает:
            (rgba_array, meta): массив формата (H, W, 4) uint8 (RGBA) и словарь с актуальным
            transform и масштабом.
        """
        ...

    @abstractmethod
    def read_window(
        self,
        path: Path | str,
        map_extent: tuple[float, float, float, float],
        target_width: int | None = None,
        target_height: int | None = None,
        out_width: int | None = None,
        out_height: int | None = None,
    ) -> tuple[np.ndarray, dict[str, Any]] | None:
        """Чтение заданного географического окна растра с приведением к целевому экранному разрешению.

        Аргументы:
            map_extent: (min_x, min_y, max_x, max_y) в координатах CRS растра.
            target_width: целевая ширина результирующего массива в пикселях.
            target_height: целевая высота результирующего массива в пикселях.

        Возвращает:
            (rgba_array, meta): RGBA-массив uint8 и словарь метаданных (bounds, transform),
            или None, если окно не пересекается с растром.
        """
        ...

    @abstractmethod
    def close(self, path: Path | str | None = None) -> None:
        """Освобождение файловых дескрипторов и очистка кэша."""
        ...
