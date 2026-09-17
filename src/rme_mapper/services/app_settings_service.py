"""Сервис хранения пользовательских настроек приложения (AppSettingsService)."""

import logging
from typing import Any

try:
    from PySide6.QtCore import QSettings
except ImportError:
    QSettings = None  # type: ignore

from rme_mapper.i18n import DEFAULT_LANGUAGE, SUPPORTED_LANGUAGES

logger = logging.getLogger("rme_mapper.services.settings")


_AUTO = object()


class AppSettingsService:
    """Тонкая обертка над QSettings для централизованного управления настройками приложения.

    Изолирует остальной UI от прямых вызовов QSettings по проекту.
    """

    ORGANIZATION_NAME = "GeoPointMapper"
    APPLICATION_NAME = "GeoPointMapper"
    KEY_LANGUAGE = "ui/language"
    KEY_RECENT_PROJECTS = "history/recent_projects"
    KEY_RECENT_MAPS = "history/recent_maps"
    KEY_LAST_MAP_DIR = "paths/last_map_directory"
    KEY_LAST_PROJECT_DIR = "paths/last_project_directory"
    MAX_RECENT_ITEMS = 10

    def __init__(self, settings: Any = _AUTO) -> None:
        if settings is _AUTO:
            if QSettings is not None:
                self._settings = QSettings(self.ORGANIZATION_NAME, self.APPLICATION_NAME)
            else:
                self._settings = None
        else:
            self._settings = settings
        self._memory_fallback: dict[str, Any] = {}

    def get_language(self) -> str:
        """Получить сохраненный код языка приложения. По умолчанию 'ru'."""
        if self._settings is not None:
            val = self._settings.value(self.KEY_LANGUAGE, DEFAULT_LANGUAGE)
        else:
            val = self._memory_fallback.get(self.KEY_LANGUAGE, DEFAULT_LANGUAGE)

        if isinstance(val, str) and val.lower() in SUPPORTED_LANGUAGES:
            return val.lower()
        return DEFAULT_LANGUAGE

    def set_language(self, language_code: str) -> None:
        """Сохранить код языка приложения ('ru' или 'en')."""
        code = (language_code or "").strip().lower()
        if code in SUPPORTED_LANGUAGES:
            if self._settings is not None:
                self._settings.setValue(self.KEY_LANGUAGE, code)
                if hasattr(self._settings, "sync"):
                    self._settings.sync()
            self._memory_fallback[self.KEY_LANGUAGE] = code
            logger.debug("Настройка языка сохранена: %s", code)
        else:
            logger.warning("Попытка сохранить недопустимый язык: %s", language_code)

    def _get_string_list(self, key: str) -> list[str]:
        if self._settings is not None:
            val = self._settings.value(key, [])
        else:
            val = self._memory_fallback.get(key, [])

        if isinstance(val, list):
            return [str(item) for item in val if item]
        if isinstance(val, str) and val:
            return [val]
        return []

    def _set_string_list(self, key: str, items: list[str]) -> None:
        cleaned = [str(item).strip() for item in items if str(item).strip()]
        if self._settings is not None:
            self._settings.setValue(key, cleaned)
            if hasattr(self._settings, "sync"):
                self._settings.sync()
        self._memory_fallback[key] = cleaned

    def _get_str(self, key: str, default: str = "") -> str:
        if self._settings is not None:
            val = self._settings.value(key, default)
        else:
            val = self._memory_fallback.get(key, default)
        return str(val) if val is not None else default

    def _set_str(self, key: str, value: str) -> None:
        val = str(value) if value is not None else ""
        if self._settings is not None:
            self._settings.setValue(key, val)
            if hasattr(self._settings, "sync"):
                self._settings.sync()
        self._memory_fallback[key] = val

    # --- Recent Projects ---
    def get_recent_projects(self) -> list[str]:
        """Возвращает список путей к недавним проектам (до MAX_RECENT_ITEMS)."""
        return self._get_string_list(self.KEY_RECENT_PROJECTS)

    def add_recent_project(self, path: str) -> None:
        """Добавить проект в начало списка недавних проектов без дубликатов."""
        if not path:
            return
        norm_path = path.strip()
        items = self.get_recent_projects()
        # Remove if already exists (case-insensitive for Windows)
        items = [p for p in items if p.lower() != norm_path.lower()]
        items.insert(0, norm_path)
        items = items[: self.MAX_RECENT_ITEMS]
        self._set_string_list(self.KEY_RECENT_PROJECTS, items)

    def remove_recent_project(self, path: str) -> None:
        """Удалить проект из списка недавних."""
        if not path:
            return
        norm_path = path.strip()
        items = [p for p in self.get_recent_projects() if p.lower() != norm_path.lower()]
        self._set_string_list(self.KEY_RECENT_PROJECTS, items)

    def clear_recent_projects(self) -> None:
        """Очистить список недавних проектов."""
        self._set_string_list(self.KEY_RECENT_PROJECTS, [])

    # --- Recent Maps ---
    def get_recent_maps(self) -> list[str]:
        """Возвращает список путей к недавним картам (до MAX_RECENT_ITEMS)."""
        return self._get_string_list(self.KEY_RECENT_MAPS)

    def add_recent_map(self, path: str) -> None:
        """Добавить карту в начало списка недавних карт без дубликатов."""
        if not path:
            return
        norm_path = path.strip()
        items = self.get_recent_maps()
        items = [p for p in items if p.lower() != norm_path.lower()]
        items.insert(0, norm_path)
        items = items[: self.MAX_RECENT_ITEMS]
        self._set_string_list(self.KEY_RECENT_MAPS, items)

    def remove_recent_map(self, path: str) -> None:
        """Удалить карту из списка недавних."""
        if not path:
            return
        norm_path = path.strip()
        items = [p for p in self.get_recent_maps() if p.lower() != norm_path.lower()]
        self._set_string_list(self.KEY_RECENT_MAPS, items)

    def clear_recent_maps(self) -> None:
        """Очистить список недавних карт."""
        self._set_string_list(self.KEY_RECENT_MAPS, [])

    # --- Directories Memory ---
    def get_last_map_directory(self, check_exists: bool = False, fallback: str = "") -> str:
        """Получить последний каталог карт."""
        import os
        from pathlib import Path

        val = self._get_str(self.KEY_LAST_MAP_DIR, "")
        if val:
            if not check_exists or os.path.isdir(val):
                return val
        if fallback and (not check_exists or os.path.isdir(fallback)):
            return fallback
        return str(Path.home()) if check_exists else ""

    def set_last_map_directory(self, path: str) -> None:
        """Сохранить последний каталог карт."""
        import os
        from pathlib import Path

        if not path:
            return
        p = Path(path)
        if p.suffix or (os.path.exists(path) and not os.path.isdir(path)):
            d = str(p.parent)
        else:
            d = str(p)
        if d:
            self._set_str(self.KEY_LAST_MAP_DIR, d)

    def get_last_project_directory(self, check_exists: bool = False, fallback: str = "") -> str:
        """Получить последний каталог проектов."""
        import os
        from pathlib import Path

        val = self._get_str(self.KEY_LAST_PROJECT_DIR, "")
        if val:
            if not check_exists or os.path.isdir(val):
                return val
        if fallback and (not check_exists or os.path.isdir(fallback)):
            return fallback
        return str(Path.home()) if check_exists else ""

    def set_last_project_directory(self, path: str) -> None:
        """Сохранить последний каталог проектов."""
        import os
        from pathlib import Path

        if not path:
            return
        p = Path(path)
        if p.suffix or (os.path.exists(path) and not os.path.isdir(path)):
            d = str(p.parent)
        else:
            d = str(p)
        if d:
            self._set_str(self.KEY_LAST_PROJECT_DIR, d)


    def clear(self) -> None:
        """Очистить сохраненные настройки (для изолированного тестирования)."""
        if self._settings is not None:
            self._settings.clear()
            if hasattr(self._settings, "sync"):
                self._settings.sync()
        self._memory_fallback.clear()

