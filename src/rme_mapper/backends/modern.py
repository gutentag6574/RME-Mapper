"""Современная реализация ГИС-бэкенда на базе GeoPandas, pyogrio и Shapely."""
from __future__ import annotations


import logging
from pathlib import Path
from typing import Any

from rme_mapper.backends.base import MapDataBackend
from rme_mapper.services.geopackage_service import GeoPackageService

logger = logging.getLogger("rme_mapper.backends.modern")


class ModernGeoPackageBackend(MapDataBackend):
    """Современный бэкенд доступа к данным векторных карт GeoPackage (*.gpkg).

    Использует возможности GeoPandas, pyogrio и Shapely для работы
    на платформах Windows 10/11 x64 с актуальными версиями Python.
    """

    def exists(self, path: Path | str) -> bool:
        """Проверка существования файла карты."""
        return GeoPackageService.exists(path)

    def list_layers(self, path: Path | str) -> list[tuple[str, str]]:
        """Получение списка доступных слоев в файле GeoPackage."""
        return GeoPackageService.list_layers(path)

    def get_layer_metadata(self, path: Path | str, layer_name: str) -> dict[str, Any]:
        """Получение метаданных слоя через pyogrio."""
        return GeoPackageService.get_layer_metadata(path, layer_name)

    def read_layer(self, path: Path | str, layer_name: str) -> Any:
        """Чтение объектов слоя в GeoDataFrame."""
        return GeoPackageService.read_layer(path, layer_name)

    def get_crs(self, path: Path | str, layer_name: str | None = None) -> str | None:
        """Получение строки CRS указанного слоя или первого найденного слоя в GeoPackage."""
        p = Path(path)
        if not p.is_file():
            return None

        if layer_name:
            try:
                meta = self.get_layer_metadata(p, layer_name)
                crs_val = meta.get("crs")
                if crs_val:
                    return crs_val.to_string() if hasattr(crs_val, "to_string") else str(crs_val)
            except Exception as e:
                logger.warning("Не удалось получить CRS для слоя %s: %s", layer_name, e)
                return None

        # Если имя слоя не задано, ищем первый слой с валидным CRS
        try:
            layers = self.list_layers(p)
            for name, _ in layers:
                try:
                    meta = self.get_layer_metadata(p, name)
                    crs_val = meta.get("crs")
                    if crs_val:
                        return crs_val.to_string() if hasattr(crs_val, "to_string") else str(crs_val)
                except Exception:
                    continue
        except Exception as e:
            logger.warning("Не удалось прочитать список слоев для получения CRS из %s: %s", p, e)

        return None

    def get_extent(self, path: Path | str, layer_name: str | None = None) -> dict[str, float] | None:
        """Получение географического охвата (xmin, ymin, xmax, ymax)."""
        p = Path(path)
        if not p.is_file():
            return None

        target_layer = layer_name
        if not target_layer:
            # Ищем граничный слой или первый доступный полигональный слой
            target_layer = self.find_boundary_layer(p)
            if not target_layer:
                layers = self.list_layers(p)
                if layers:
                    target_layer = layers[0][0]

        if not target_layer:
            return None

        try:
            meta = self.get_layer_metadata(p, target_layer)
            bounds = meta.get("total_bounds")
            if bounds is not None and len(bounds) >= 4:
                return {
                    "xmin": float(bounds[0]),
                    "ymin": float(bounds[1]),
                    "xmax": float(bounds[2]),
                    "ymax": float(bounds[3]),
                }
        except Exception as e:
            logger.warning("Не удалось получить total_bounds из метаданных слоя %s: %s", target_layer, e)

        # Резервный вариант: чтение слоя и определение границ
        try:
            gdf = self.read_layer(p, target_layer)
            if gdf is not None and hasattr(gdf, "total_bounds") and len(gdf.total_bounds) >= 4:
                bounds = gdf.total_bounds
                return {
                    "xmin": float(bounds[0]),
                    "ymin": float(bounds[1]),
                    "xmax": float(bounds[2]),
                    "ymax": float(bounds[3]),
                }
        except Exception as e:
            logger.warning("Не удалось вычислить охват при прямом чтении слоя %s: %s", target_layer, e)

        return None

    def find_boundary_layer(self, path: Path | str) -> str | None:
        """Автоматический поиск слоя административной границы."""
        return GeoPackageService.find_boundary_layer(path)
