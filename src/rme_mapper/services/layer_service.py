"""Сервис обнаружения, типизации и кэширования картографических слоев."""

import logging
from pathlib import Path
from typing import Any

import geopandas as gpd

from rme_mapper.models.map_layer import LayerRole, MapLayer
from rme_mapper.services.geopackage_service import GeoPackageService

logger = logging.getLogger("rme_mapper.services.layer")

# Стандартные отображаемые имена для ролей слоев
ROLE_DISPLAY_NAMES: dict[LayerRole, str] = {
    LayerRole.BOUNDARY: "Граница РМЭ",
    LayerRole.ROADS: "Дороги",
    LayerRole.WATER: "Водоемы",
    LayerRole.WATERWAYS: "Реки",
    LayerRole.PLACES: "Населенные пункты",
}

# Стили оформления по умолчанию для слоев
ROLE_STYLES: dict[LayerRole, dict[str, Any]] = {
    LayerRole.BOUNDARY: {
        "border_color": "#2A5B84",
        "fill_color": "#DCEEF8",
        "border_width": 0.0,
    },
    LayerRole.ROADS: {
        "border_color": "#C2593F",
        "fill_color": None,
        "border_width": 0.0,
    },
    LayerRole.WATER: {
        "border_color": "#72A1E5",
        "fill_color": "#A0C4FF",
        "border_width": 0.0,
    },
    LayerRole.WATERWAYS: {
        "border_color": "#4A90E2",
        "fill_color": None,
        "border_width": 0.0,
    },
    LayerRole.PLACES: {
        "border_color": "#1D3557",
        "fill_color": "#E63946",
        "border_width": 0.0,
        "point_radius": 3.0,
    },
}


class LayerService:
    """Сервис управления реестром и данными картографических слоев."""

    def __init__(self) -> None:
        # Кэш в памяти: "путь_к_файлу:имя_слоя" -> GeoDataFrame
        self._cache: dict[str, gpd.GeoDataFrame] = {}

    def discover_layers(self, gpkg_path: Path | str) -> list[MapLayer]:
        """Обнаружение и классификация поддерживаемых слоев в GeoPackage.

        Возвращает список поддерживаемых слоев, отсортированных по z_order.
        Неизвестные/неподдерживаемые слои исключаются из автоматической загрузки.
        """
        p = Path(gpkg_path)
        raw_layers = GeoPackageService.list_layers(p)
        logger.info("Анализ слоев в %s: %s", p.name, raw_layers)

        discovered: list[MapLayer] = []

        for name, geom_type in raw_layers:
            role = self._determine_layer_role(p, name, geom_type)

            if role == LayerRole.UNKNOWN:
                logger.info("Слой '%s' (%s) определен как UNKNOWN и пропущен", name, geom_type)
                continue

            try:
                meta = GeoPackageService.get_layer_metadata(p, name)
                crs_val = meta.get("crs")
                crs_str = crs_val.to_string() if hasattr(crs_val, "to_string") else str(crs_val)
                feature_count = meta.get("features_count") or 0
            except Exception as e:
                logger.warning("Не удалось получить полные метаданные слоя '%s': %s", name, e)
                crs_str = "OGC:CRS84"
                feature_count = 0

            layer = MapLayer(
                id=f"layer_{role.value}_{name}",
                source_name=name,
                display_name=ROLE_DISPLAY_NAMES.get(role, name),
                geometry_type=geom_type,
                crs=crs_str,
                visible=True,
                feature_count=feature_count,
                role=role,
                style=ROLE_STYLES.get(role, {}).copy(),
            )
            discovered.append(layer)
            logger.info("Зарегистрирован слой: %s (роль=%s, объектов=%d, z=%d)",
                        layer.display_name, layer.role.value, layer.feature_count, layer.z_order)

        # Сортируем слои по z_order (нижние слои рендерятся первыми)
        discovered.sort(key=lambda x: x.z_order)
        return discovered

    def _determine_layer_role(
        self,
        gpkg_path: Path,
        layer_name: str,
        geom_type: str,
    ) -> LayerRole:
        """Определение роли слоя по имени и типу геометрии."""
        lower = layer_name.lower()
        geom = geom_type.lower()

        # 1. Административная граница
        if any(k in lower for k in ("admin", "boundary", "border")):
            if "polygon" in geom:
                return LayerRole.BOUNDARY
        # Дополнительная проверка на случай имени вроде mari_el
        if "mari" in lower and "polygon" in geom:
            return LayerRole.BOUNDARY

        # 2. Дороги
        if any(k in lower for k in ("road", "roads", "highway", "street")):
            if "line" in geom:
                return LayerRole.ROADS

        # 3. Водоемы
        if any(k in lower for k in ("water", "lake", "reservoir")) and "waterway" not in lower:
            if "polygon" in geom:
                return LayerRole.WATER

        # 4. Реки / водотоки
        if any(k in lower for k in ("waterway", "river", "stream", "canal")):
            if "line" in geom:
                return LayerRole.WATERWAYS

        # 5. Населенные пункты
        if any(k in lower for k in ("place", "places", "settlement", "city", "town")):
            if "point" in geom or "polygon" in geom:
                return LayerRole.PLACES

        # Неизвестный слой
        return LayerRole.UNKNOWN

    def load_layer_data(self, gpkg_path: Path | str, layer: MapLayer) -> gpd.GeoDataFrame:
        """Загрузка данных слоя с использованием кэша в памяти.

        При повторном запросе данные возвращаются из оперативной памяти
        без повторного обращения к диску.
        """
        p = Path(gpkg_path)
        cache_key = f"{p.resolve()}:{layer.source_name}"

        if cache_key in self._cache:
            logger.debug("Слой '%s' возвращен из кэша памяти", layer.display_name)
            return self._cache[cache_key]

        logger.info("Чтение слоя '%s' (%s) с диска...", layer.display_name, layer.source_name)
        gdf = GeoPackageService.read_layer(p, layer.source_name)
        self._cache[cache_key] = gdf
        return gdf

    def clear_cache(self) -> None:
        """Очистка кэша загруженных слоев."""
        self._cache.clear()
        logger.info("Кэш слоев очищен")
