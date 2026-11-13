"""Сервис обнаружения, загрузки и управления каталогом профилей карт (MapCatalogService)."""
from __future__ import annotations


import copy
import json
import logging
from pathlib import Path

from rme_mapper.maps.map_config import get_project_root
from rme_mapper.models.map_profile import MapProfile

logger = logging.getLogger("rme_mapper.services.catalog")

DEFAULT_PROFILE_ID = "mari_el"
LEGACY_ALIASES: dict[str, str] = {
    "test_map": "mari_el",
}


class MapCatalogService:
    """Сервис обнаружения, загрузки и поиска профилей карт в файловой системе."""

    def __init__(self, maps_dir: Path | str | None = None) -> None:
        if maps_dir is not None:
            self._maps_dir = Path(maps_dir).resolve()
        else:
            self._maps_dir = (get_project_root() / "maps").resolve()

        # Кэш профилей: profile_id -> MapProfile
        self._profiles: dict[str, MapProfile] = {}
        self._discovered = False

    @property
    def maps_dir(self) -> Path:
        """Корневая директория каталога карт."""
        return self._maps_dir

    def discover_profiles(self) -> list[MapProfile]:
        """Сканирование директорий каталога карт и загрузка всех валидных профилей."""
        self._profiles.clear()

        if not self._maps_dir.exists() or not self._maps_dir.is_dir():
            logger.warning("Каталог карт не существует: %s", self._maps_dir)
            self._discovered = True
            return []

        logger.info("Сканирование каталога карт в: %s", self._maps_dir)

        # 1. Поиск metadata.json в поддиректориях каталога карт
        for item in sorted(self._maps_dir.iterdir()):
            if item.is_dir():
                meta_file = item / "metadata.json"
                if meta_file.is_file():
                    profile = self._load_profile_from_file(meta_file, base_dir=item)
                    if profile:
                        self._profiles[profile.id] = profile

        # 2. Также проверяем саму корневую папку maps_dir на случай если в ней есть metadata.json
        root_meta = self._maps_dir / "metadata.json"
        if root_meta.is_file() and root_meta not in [item / "metadata.json" for item in self._maps_dir.iterdir() if item.is_dir()]:
            profile = self._load_profile_from_file(root_meta, base_dir=self._maps_dir)
            if profile and profile.id not in self._profiles:
                self._profiles[profile.id] = profile

        self._discovered = True
        logger.info("Обнаружено профилей карт: %d (%s)", len(self._profiles), list(self._profiles.keys()))
        return [copy.deepcopy(p) for p in self._profiles.values()]

    def _load_profile_from_file(self, file_path: Path, base_dir: Path) -> MapProfile | None:
        """Чтение и валидация файла metadata.json."""
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                data = json.load(f)

            if not isinstance(data, dict):
                logger.warning("Файл %s не содержит JSON-объект, пропущен", file_path)
                return None

            profile = MapProfile.from_dict(data, base_dir=base_dir)
            logger.info("Загружен профиль карты '%s' (%s) из %s", profile.name, profile.id, file_path)
            return profile
        except Exception as e:
            logger.exception("Ошибка при загрузке профиля карты из %s: %s", file_path, e)
            return None

    def get_profile(self, profile_id: str) -> MapProfile | None:
        """Получение профиля карты по его идентификатору.

        Поддерживает обратную совместимость с legacy-идентификаторами (например, test_map -> mari_el).
        """
        if not self._discovered:
            self.discover_profiles()

        if profile_id in self._profiles:
            return copy.deepcopy(self._profiles[profile_id])

        # Проверка известных алиасов для обратной совместимости
        alias_target = LEGACY_ALIASES.get(profile_id)
        if alias_target and alias_target in self._profiles:
            logger.info("Профиль '%s' сопоставлен с '%s' через legacy-алиас", profile_id, alias_target)
            return copy.deepcopy(self._profiles[alias_target])

        return None

    def get_profile_by_path(self, path: Path | str) -> MapProfile | None:
        """Поиск профиля карты по пути к GIS-файлу (относительному или абсолютному)."""
        if not self._discovered:
            self.discover_profiles()

        target_path = Path(path)
        target_posix = target_path.as_posix().lower()

        # 1. Точное совпадение абсолютных путей
        try:
            target_resolved = target_path.resolve()
            for profile in self._profiles.values():
                src_resolved = profile.get_absolute_source_path(root_dir=get_project_root()).resolve()
                if src_resolved == target_resolved:
                    return copy.deepcopy(profile)
        except Exception:
            pass

        # 2. Сопоставление по относительному пути / подстроке
        for profile in self._profiles.values():
            prof_src_posix = Path(profile.source_path).as_posix().lower()
            if prof_src_posix and (target_posix.endswith(prof_src_posix) or prof_src_posix.endswith(target_posix)):
                return copy.deepcopy(profile)

        # 3. Специальный fallback для эталонного файла mari.gpkg
        if "mari.gpkg" in target_posix:
            return self.get_profile(DEFAULT_PROFILE_ID)

        return None

    def get_default_profile(self) -> MapProfile:
        """Получение профиля по умолчанию (mari_el или первого доступного)."""
        if not self._discovered:
            self.discover_profiles()

        if DEFAULT_PROFILE_ID in self._profiles:
            return copy.deepcopy(self._profiles[DEFAULT_PROFILE_ID])

        if self._profiles:
            first_profile = next(iter(self._profiles.values()))
            return copy.deepcopy(first_profile)

        # Fallback: создание синтетического профиля для mari.gpkg, если каталог пуст
        root = get_project_root()
        mari_gpkg = root / "maps" / "test_map" / "prepared" / "mari.gpkg"
        logger.warning("Профили карт не найдены на диске, сформирован резервный профиль mari_el")
        return MapProfile(
            id=DEFAULT_PROFILE_ID,
            name="Республика Марий Эл",
            description="Резервный профиль Республики Марий Эл",
            source_type="geopackage",
            source_path=str(mari_gpkg),
            base_dir=mari_gpkg.parent.parent,
            crs="OGC:CRS84",
            boundary_layer="gis_osm_adminareas_a_free",
            boundary_required=True,
        )
