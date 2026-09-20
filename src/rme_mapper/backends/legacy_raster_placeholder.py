"""Архитектурный плейсхолдер для будущего бэкенда устаревших платформ (LegacyRasterBackend)."""

from pathlib import Path
from typing import Any
import numpy as np

from rme_mapper.backends.raster_backend import RasterDataBackend


class LegacyRasterBackend(RasterDataBackend):
    """Архитектурная заготовка для будущего растрового бэкенда под Windows 7 и Windows XP.

    В будущих этапах разработки данная реализация будет использовать легковесные
    механизмы чтения базовых TIFF/GeoTIFF без тяжелых зависимостей (GDAL/rasterio),
    адаптированные под ограничения 32-битной архитектуры памяти (до 2 ГБ RAM).

    В текущей версии Modern Build используется ModernGeoTiffBackend.
    Попытка вызвать методы данного класса вызывает исключение NotImplementedError.
    """

    _NOT_IMPLEMENTED_MSG = (
        "LegacyRasterBackend запланирован для отдельных будущих этапов "
        "сборок под Windows 7 / Windows XP. В текущей версии используется ModernGeoTiffBackend."
    )

    def inspect_raster(self, path: Path | str) -> dict[str, Any]:
        raise NotImplementedError(self._NOT_IMPLEMENTED_MSG)

    def get_crs(self, path: Path | str) -> str | None:
        raise NotImplementedError(self._NOT_IMPLEMENTED_MSG)

    def get_extent(self, path: Path | str) -> dict[str, float] | None:
        raise NotImplementedError(self._NOT_IMPLEMENTED_MSG)

    def get_size(self, path: Path | str) -> tuple[int, int] | None:
        raise NotImplementedError(self._NOT_IMPLEMENTED_MSG)

    def get_band_count(self, path: Path | str) -> int:
        raise NotImplementedError(self._NOT_IMPLEMENTED_MSG)

    def get_nodata(self, path: Path | str) -> float | None:
        raise NotImplementedError(self._NOT_IMPLEMENTED_MSG)

    def read_preview(
        self,
        path: Path | str,
        max_dimension: int = 4096,
        max_preview_dimension: int | None = None,
    ) -> tuple[np.ndarray, dict[str, Any]]:
        raise NotImplementedError(self._NOT_IMPLEMENTED_MSG)

    def read_window(
        self,
        path: Path | str,
        map_extent: tuple[float, float, float, float],
        target_width: int | None = None,
        target_height: int | None = None,
        out_width: int | None = None,
        out_height: int | None = None,
    ) -> tuple[np.ndarray, dict[str, Any]] | None:
        raise NotImplementedError(self._NOT_IMPLEMENTED_MSG)

    def close(self, path: Path | str | None = None) -> None:
        pass
