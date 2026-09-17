"""Сервис для работы с векторными данными GeoPackage."""

import logging
from pathlib import Path
from typing import Any

import geopandas as gpd
import pyogrio

logger = logging.getLogger("rme_mapper.services.geopackage")


class GeoPackageService:
    """Сервис чтения и извлечения метаданных из файлов GeoPackage."""

    @staticmethod
    def exists(path: Path | str) -> bool:
        """Проверка существования файла GeoPackage."""
        p = Path(path)
        exists = p.is_file()
        logger.debug("Проверка существования файла %s: %s", p, exists)
        return exists

    @staticmethod
    def list_layers(path: Path | str) -> list[tuple[str, str]]:
        """Получение списка слоев в GeoPackage.

        Возвращает:
            Список кортежей (имя_слоя, тип_геометрии).
        """
        p = Path(path)
        if not p.is_file():
            logger.error("Файл GeoPackage не найден по пути: %s", p)
            raise FileNotFoundError(f"Файл GeoPackage не найден: {p}")

        try:
            layers = pyogrio.list_layers(str(p))
            result = [(str(name), str(geom_type)) for name, geom_type in layers]
            logger.info("В GeoPackage %s обнаружено слоев: %d -> %s", p.name, len(result), result)
            return result
        except Exception as e:
            logger.exception("Ошибка чтения списка слоев из %s: %s", p, e)
            raise

    @staticmethod
    def get_layer_metadata(path: Path | str, layer_name: str) -> dict[str, Any]:
        """Получение метаданных конкретного слоя без загрузки всех данных в память."""
        p = Path(path)
        if not p.is_file():
            logger.error("Файл GeoPackage не найден: %s", p)
            raise FileNotFoundError(f"Файл GeoPackage не найден: {p}")

        try:
            info = pyogrio.read_info(str(p), layer=layer_name)
            meta = {
                "layer_name": layer_name,
                "geometry_type": info.get("geometry_type"),
                "features_count": info.get("features_count"),
                "crs": info.get("crs"),
                "total_bounds": info.get("total_bounds"),
                "fields": info.get("fields"),
            }
            logger.info("Метаданные слоя '%s': объекты=%s, geom=%s, crs=%s",
                        layer_name, meta["features_count"], meta["geometry_type"], meta["crs"])
            return meta
        except Exception as e:
            logger.exception("Ошибка получения метаданных слоя '%s': %s", layer_name, e)
            raise

    @staticmethod
    def read_layer(path: Path | str, layer_name: str) -> gpd.GeoDataFrame:
        """Чтение указанного слоя в виде GeoDataFrame."""
        p = Path(path)
        if not p.is_file():
            logger.error("Файл GeoPackage не найден: %s", p)
            raise FileNotFoundError(f"Файл GeoPackage не найден: {p}")

        try:
            logger.info("Чтение слоя '%s' из %s...", layer_name, p)
            gdf = gpd.read_file(str(p), layer=layer_name)
            crs_str = gdf.crs.to_string() if gdf.crs else "None"
            logger.info("Слой '%s' успешно прочитан: объектов=%d, CRS=%s, bounds=%s",
                        layer_name, len(gdf), crs_str, gdf.total_bounds)
            return gdf
        except Exception as e:
            logger.exception("Ошибка чтения слоя '%s' из %s: %s", layer_name, p, e)
            raise

    @classmethod
    def find_boundary_layer(cls, path: Path | str) -> str | None:
        """Автоматический поиск слоя административной границы Республики Марий Эл.

        Критерии поиска:
        1. Слой должен иметь полигональную геометрию (Polygon или MultiPolygon).
        2. Приоритет отдается слою, содержащему в названии 'admin'/'boundary'/'border',
           либо содержащему объект с именем 'Марий Эл'.
        """
        p = Path(path)
        layers = cls.list_layers(p)

        polygon_layers = [
            name for name, geom_type in layers
            if geom_type in ("Polygon", "MultiPolygon", "Unknown")
        ]

        logger.debug("Полигональные слои-кандидаты: %s", polygon_layers)

        if not polygon_layers:
            logger.warning("В GeoPackage %s не найдено полигональных слоев", p)
            return None

        # 1. Проверяем слои с ключевыми словами в имени
        for layer in polygon_layers:
            lower = layer.lower()
            if any(key in lower for key in ("admin", "boundary", "border", "mari")):
                logger.info("Выбран слой границы по имени: '%s'", layer)
                return layer

        # 2. Если имя не подошло, читаем кратко данные и проверяем атрибут name
        for layer in polygon_layers:
            try:
                gdf = cls.read_layer(p, layer)
                if "name" in gdf.columns:
                    names = gdf["name"].dropna().astype(str).str.lower()
                    if names.str.contains("марий").any() or names.str.contains("mari").any():
                        logger.info("Выбран слой границы по атрибуту name: '%s'", layer)
                        return layer
            except Exception as e:
                logger.warning("Не удалось проверить атрибуты слоя '%s': %s", layer, e)

        # 3. Если есть ровно один полигональный слой — берем его
        chosen = polygon_layers[0]
        logger.info("Выбран единственный полигональный слой: '%s'", chosen)
        return chosen
