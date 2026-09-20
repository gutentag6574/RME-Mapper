"""Сервис обнаружения, типизации и кэширования картографических слоев."""

import json
import logging
from pathlib import Path
from typing import Any

import geopandas as gpd

from rme_mapper.backends.base import MapDataBackend
from rme_mapper.models.map_layer import LayerRole, MapLayer
from rme_mapper.models.map_profile import MapProfile
from rme_mapper.services.geopackage_service import GeoPackageService

logger = logging.getLogger("rme_mapper.services.layer")

# Стандартные нейтральные отображаемые имена для ролей слоев
ROLE_DISPLAY_NAMES: dict[LayerRole, str] = {
    LayerRole.BOUNDARY: "Граница",
    LayerRole.ROADS: "Дороги",
    LayerRole.WATER: "Водоемы",
    LayerRole.WATERWAYS: "Реки",
    LayerRole.PLACES: "Населенные пункты",
    LayerRole.RASTER: "Растр",
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
    LayerRole.RASTER: {
        "border_color": "#000000",
        "fill_color": None,
        "border_width": 0.0,
    },
}


class LayerService:
    """Сервис управления реестром и данными картографических слоев."""

    def __init__(self, backend: MapDataBackend | None = None) -> None:
        if backend is None:
            from rme_mapper.backends.factory import get_backend
            backend = get_backend()
        self._backend: MapDataBackend = backend
        # Кэш в памяти: "путь_к_файлу:имя_слоя" -> GeoDataFrame
        self._cache: dict[str, gpd.GeoDataFrame] = {}

    def load_profile_layers(self, profile: MapProfile, base_dir: Path | None = None) -> list[MapLayer]:
        """Загрузка слоев, описанных в MapProfile.

        Если в профиле явно задан список слоев (profile.layers), слои настраиваются
        согласно метаданным профиля. Иначе выполняется автоматическое обнаружение (discovery).
        """
        source_path = profile.get_absolute_source_path(root_dir=base_dir)
        if not source_path.exists():
            logger.error("Файл данных карты не существует: %s", source_path)
            return []

        # Специальная обработка растровой карты GeoTIFF
        if profile.source_type == "geotiff" or source_path.suffix.lower() in (".tif", ".tiff"):
            display_name = "Растр"
            layer_id = "raster_base"
            visible = True
            if profile.layers:
                first_cfg = profile.layers[0]
                display_name = str(first_cfg.get("display_name") or first_cfg.get("name") or "Растр")
                layer_id = str(first_cfg.get("id") or "raster_base")
                visible = bool(first_cfg.get("visible", True))

            raster_layer = MapLayer(
                id=layer_id,
                source_name="raster",
                display_name=display_name,
                geometry_type="raster",
                crs=profile.crs or "OGC:CRS84",
                visible=visible,
                feature_count=1,
                role=LayerRole.RASTER,
                z_order=5,
                style={"border_color": "#000000", "fill_color": None, "border_width": 0.0},
            )
            return [raster_layer]

        if not profile.layers:
            return self.discover_layers(source_path)

        logger.info("Загрузка %d слоев из профиля '%s'", len(profile.layers), profile.name)
        discovered: list[MapLayer] = []
        raw_layers_info = {name: geom for name, geom in self._backend.list_layers(source_path)}

        for layer_cfg in profile.layers:
            source_name = str(layer_cfg.get("source_name") or layer_cfg.get("name") or "")
            if not source_name or source_name not in raw_layers_info:
                logger.warning("Слой профиля '%s' не найден в источнике %s", source_name, source_path.name)
                continue

            geom_type = raw_layers_info[source_name]
            role_val = str(layer_cfg.get("role", "UNKNOWN")).upper()
            try:
                role = LayerRole[role_val]
            except KeyError:
                role = LayerRole.UNKNOWN

            # Если слой указан как граничный в профиле
            if profile.boundary_layer and (source_name == profile.boundary_layer or layer_cfg.get("id") == "boundary"):
                role = LayerRole.BOUNDARY

            try:
                meta = self._backend.get_layer_metadata(source_path, source_name)
                crs_val = meta.get("crs")
                crs_str = crs_val.to_string() if hasattr(crs_val, "to_string") else str(crs_val)
                feature_count = meta.get("features_count") or 0
            except Exception as err:
                logger.warning("Не удалось получить метаданные слоя '%s': %s", source_name, err)
                crs_str = profile.crs or "OGC:CRS84"
                feature_count = 0

            display_name = str(layer_cfg.get("display_name") or ROLE_DISPLAY_NAMES.get(role, source_name))
            layer_id = str(layer_cfg.get("id") or f"layer_{role.value}_{source_name}")
            visible = bool(layer_cfg.get("visible", True))

            style = layer_cfg.get("style")
            if not style or not isinstance(style, dict):
                style = ROLE_STYLES.get(role, {}).copy()

            layer = MapLayer(
                id=layer_id,
                source_name=source_name,
                display_name=display_name,
                geometry_type=geom_type,
                crs=crs_str,
                visible=visible,
                feature_count=feature_count,
                role=role,
                style=style,
            )
            discovered.append(layer)

        discovered.sort(key=lambda x: x.z_order)
        return discovered

    def discover_layers(self, gpkg_path: Path | str) -> list[MapLayer]:
        """Обнаружение и классификация поддерживаемых слоев в файле карты.

        Возвращает список поддерживаемых слоев, отсортированных по z_order.
        """
        p = Path(gpkg_path)
        if p.suffix.lower() in (".tif", ".tiff"):
            from rme_mapper.backends.factory import get_raster_backend
            rb = get_raster_backend()
            crs_str = rb.get_crs(p) or "OGC:CRS84"
            raster_layer = MapLayer(
                id="raster_base",
                source_name="raster",
                display_name="Растр",
                geometry_type="raster",
                crs=crs_str,
                visible=True,
                feature_count=1,
                role=LayerRole.RASTER,
                z_order=5,
                style={"border_color": "#000000", "fill_color": None, "border_width": 0.0},
            )
            return [raster_layer]

        raw_layers = self._backend.list_layers(p)
        logger.info("Анализ слоев в %s: %s", p.name, raw_layers)

        # Пытаемся найти metadata.json рядом для извлечения настроенных имен слоев
        meta_layers: dict[str, dict[str, Any]] = {}
        for candidate_dir in [p.parent, p.parent.parent]:
            meta_json = candidate_dir / "metadata.json"
            if meta_json.is_file():
                try:
                    with open(meta_json, "r", encoding="utf-8") as f:
                        meta_data = json.load(f)
                    for item in meta_data.get("layers", []):
                        if isinstance(item, dict) and "source_name" in item:
                            meta_layers[item["source_name"]] = item
                    break
                except Exception:
                    pass

        discovered: list[MapLayer] = []

        for name, geom_type in raw_layers:
            role = self._determine_layer_role(p, name, geom_type)

            if role == LayerRole.UNKNOWN:
                logger.info("Слой '%s' (%s) определен как UNKNOWN и пропущен", name, geom_type)
                continue

            try:
                meta = self._backend.get_layer_metadata(p, name)
                crs_val = meta.get("crs")
                crs_str = crs_val.to_string() if hasattr(crs_val, "to_string") else str(crs_val)
                feature_count = meta.get("features_count") or 0
            except Exception as e:
                logger.warning("Не удалось получить полные метаданные слоя '%s': %s", name, e)
                crs_str = "OGC:CRS84"
                feature_count = 0

            # Имя отображения: берем из metadata.json если есть, иначе из ROLE_DISPLAY_NAMES
            layer_meta = meta_layers.get(name, {})
            custom_name = layer_meta.get("display_name")
            display_name = custom_name if custom_name else ROLE_DISPLAY_NAMES.get(role, name)

            layer = MapLayer(
                id=layer_meta.get("id", f"layer_{role.value}_{name}"),
                source_name=name,
                display_name=display_name,
                geometry_type=geom_type,
                crs=crs_str,
                visible=bool(layer_meta.get("visible", True)),
                feature_count=feature_count,
                role=role,
                style=layer_meta.get("style") or ROLE_STYLES.get(role, {}).copy(),
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
        """Определение роли слоя по имени и типу геометрии без привязки к конкретным регионам."""
        lower = layer_name.lower()
        geom = geom_type.lower()

        # 1. Административная граница
        if any(k in lower for k in ("admin", "boundary", "border")):
            if "polygon" in geom:
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
        """Загрузка данных слоя с использованием кэша в памяти."""
        if layer.role == LayerRole.RASTER:
            return gpd.GeoDataFrame()

        p = Path(gpkg_path)
        cache_key = f"{p.resolve()}:{layer.source_name}"

        if cache_key in self._cache:
            logger.debug("Слой '%s' возвращен из кэша памяти", layer.display_name)
            return self._cache[cache_key]

        logger.info("Чтение слоя '%s' (%s) с диска...", layer.display_name, layer.source_name)
        gdf = self._backend.read_layer(p, layer.source_name)
        self._cache[cache_key] = gdf
        return gdf

    def clear_cache(self) -> None:
        """Очистка кэша загруженных слоев."""
        self._cache.clear()
        logger.info("Кэш слоев очищен")
