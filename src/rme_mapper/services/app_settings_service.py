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
    KEY_LAST_IMPORT_DIR = "paths/last_import_directory"
    KEY_LAST_EXPORT_DIR = "paths/last_export_directory"
    KEY_LAST_EXPORT_FORMAT = "export/last_format"
    KEY_LAST_EXPORT_WIDTH = "export/last_width"
    KEY_LAST_EXPORT_HEIGHT = "export/last_height"
    KEY_LAST_EXPORT_EXTENT_MODE = "export/last_extent_mode"
    KEY_LAST_EXPORT_JPEG_QUALITY = "export/last_jpeg_quality"
    KEY_LAST_EXPORT_LOCK_ASPECT = "export/last_lock_aspect"
    KEY_IMPORT_PRESETS = "import/mapping_presets"
    KEY_WINDOW_GEOMETRY = "ui/window_geometry"
    KEY_WINDOW_MAXIMIZED = "ui/window_maximized"
    KEY_SPLITTER_SIZES = "ui/splitter_sizes"
    KEY_LEFT_PANEL_VISIBLE = "ui/left_panel_visible"
    KEY_RIGHT_PANEL_VISIBLE = "ui/right_panel_visible"
    KEY_TOOLBAR_VISIBLE = "ui/toolbar_visible"
    KEY_STATUSBAR_VISIBLE = "ui/statusbar_visible"
    KEY_POINT_LABELS_MODE = "ui/point_labels_mode"
    KEY_POINT_LABEL_CONTENT = "ui/point_label_content"
    KEY_SHOW_POINTS_VISIBLE = "ui/show_points_visible"
    KEY_SHOW_ZONES_VISIBLE = "ui/show_zones_visible"
    KEY_SHOW_SCALE_INDICATOR = "ui/show_scale_indicator"
    KEY_SHOW_COORDINATE_GRID = "ui/show_coordinate_grid"
    KEY_ONLINE_CACHE_MAX_MB = "online_maps/cache_max_mb"
    KEY_LAST_ONLINE_PROVIDER = "online_maps/last_provider"
    KEY_ONLINE_API_KEYS = "online_maps/api_keys"
    KEY_CUSTOM_XYZ_PROVIDERS = "online_maps/custom_providers"
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

    def get_last_import_directory(self, check_exists: bool = False, fallback: str = "") -> str:
        """Получить последний каталог импорта."""
        import os
        from pathlib import Path

        val = self._get_str(self.KEY_LAST_IMPORT_DIR, "")
        if val:
            if not check_exists or os.path.isdir(val):
                return val
        if fallback and (not check_exists or os.path.isdir(fallback)):
            return fallback
        # В качестве резерва используем каталог проектов или домашнюю директорию
        proj_dir = self.get_last_project_directory(check_exists=check_exists)
        return proj_dir if proj_dir else (str(Path.home()) if check_exists else "")

    def set_last_import_directory(self, path: str) -> None:
        """Сохранить последний каталог импорта."""
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
            self._set_str(self.KEY_LAST_IMPORT_DIR, d)

    def get_last_export_directory(self, check_exists: bool = False, fallback: str = "") -> str:
        """Получить последний каталог экспорта."""
        import os
        from pathlib import Path

        val = self._get_str(self.KEY_LAST_EXPORT_DIR, "")
        if val:
            if not check_exists or os.path.isdir(val):
                return val
        if fallback and (not check_exists or os.path.isdir(fallback)):
            return fallback
        proj_dir = self.get_last_project_directory(check_exists=check_exists)
        return proj_dir if proj_dir else (str(Path.home()) if check_exists else "")

    def set_last_export_directory(self, path: str) -> None:
        """Сохранить последний каталог экспорта."""
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
            self._set_str(self.KEY_LAST_EXPORT_DIR, d)

    def get_export_format(self, default: str = "PNG") -> str:
        """Получить сохраненный формат экспорта ('PNG' или 'JPEG')."""
        val = self._get_str(self.KEY_LAST_EXPORT_FORMAT, default).upper()
        return val if val in ("PNG", "JPEG", "JPG") else default

    def set_export_format(self, fmt: str) -> None:
        """Сохранить формат экспорта."""
        clean = fmt.strip().upper()
        if clean in ("PNG", "JPEG", "JPG"):
            self._set_str(self.KEY_LAST_EXPORT_FORMAT, clean)

    def get_export_width(self, default: int = 1920) -> int:
        """Получить сохраненную ширину экспорта в пикселях."""
        raw = self._get_str(self.KEY_LAST_EXPORT_WIDTH, str(default))
        try:
            val = int(raw)
            return val if 256 <= val <= 16384 else default
        except (ValueError, TypeError):
            return default

    def set_export_width(self, width: int) -> None:
        """Сохранить ширину экспорта."""
        if 256 <= width <= 16384:
            self._set_str(self.KEY_LAST_EXPORT_WIDTH, str(width))

    def get_export_height(self, default: int = 1080) -> int:
        """Получить сохраненную высоту экспорта в пикселях."""
        raw = self._get_str(self.KEY_LAST_EXPORT_HEIGHT, str(default))
        try:
            val = int(raw)
            return val if 256 <= val <= 16384 else default
        except (ValueError, TypeError):
            return default

    def set_export_height(self, height: int) -> None:
        """Сохранить высоту экспорта."""
        if 256 <= height <= 16384:
            self._set_str(self.KEY_LAST_EXPORT_HEIGHT, str(height))

    def get_export_extent_mode(self, default: str = "current_view") -> str:
        """Получить сохраненный режим охвата экспорта."""
        val = self._get_str(self.KEY_LAST_EXPORT_EXTENT_MODE, default)
        valid = {"current_view", "full_map", "all_points", "selected_points"}
        return val if val in valid else default

    def set_export_extent_mode(self, mode: str) -> None:
        """Сохранить режим охвата экспорта."""
        if mode in {"current_view", "full_map", "all_points", "selected_points"}:
            self._set_str(self.KEY_LAST_EXPORT_EXTENT_MODE, mode)

    def get_export_jpeg_quality(self, default: int = 92) -> int:
        """Получить сохраненное качество JPEG (1-100)."""
        raw = self._get_str(self.KEY_LAST_EXPORT_JPEG_QUALITY, str(default))
        try:
            val = int(raw)
            return val if 1 <= val <= 100 else default
        except (ValueError, TypeError):
            return default

    def set_export_jpeg_quality(self, quality: int) -> None:
        """Сохранить качество JPEG."""
        if 1 <= quality <= 100:
            self._set_str(self.KEY_LAST_EXPORT_JPEG_QUALITY, str(quality))

    def get_export_lock_aspect(self, default: bool = True) -> bool:
        """Получить настройку фиксации пропорций области."""
        return self._get_bool(self.KEY_LAST_EXPORT_LOCK_ASPECT, default=default)

    def set_export_lock_aspect(self, locked: bool) -> None:
        """Сохранить настройку фиксации пропорций области."""
        self._set_bool(self.KEY_LAST_EXPORT_LOCK_ASPECT, locked)

    # --- UI State & Geometry ---
    def _get_bool(self, key: str, default: bool = True) -> bool:
        if self._settings is not None:
            val = self._settings.value(key, default)
        else:
            val = self._memory_fallback.get(key, default)
        if isinstance(val, bool):
            return val
        if isinstance(val, (int, float)):
            return bool(val)
        if isinstance(val, str):
            return val.strip().lower() in ("true", "1", "yes")
        return default

    def _set_bool(self, key: str, value: bool) -> None:
        val = bool(value)
        if self._settings is not None:
            self._settings.setValue(key, val)
            if hasattr(self._settings, "sync"):
                self._settings.sync()
        self._memory_fallback[key] = val

    def get_window_geometry(self) -> dict[str, int] | None:
        """Получить сохраненную геометрию окна {x, y, width, height}."""
        raw = self._get_str(self.KEY_WINDOW_GEOMETRY, "")
        if not raw:
            return None
        try:
            import json
            data = json.loads(raw)
            if isinstance(data, dict) and all(k in data for k in ("x", "y", "width", "height")):
                return {k: int(data[k]) for k in ("x", "y", "width", "height")}
        except Exception:
            pass
        return None

    def set_window_geometry(self, x: int, y: int, width: int, height: int) -> None:
        """Сохранить координаты и размеры главного окна."""
        import json
        payload = json.dumps({"x": int(x), "y": int(y), "width": int(width), "height": int(height)})
        self._set_str(self.KEY_WINDOW_GEOMETRY, payload)

    def get_window_maximized(self) -> bool:
        """Получить признак развернутого состояния окна (maximized)."""
        return self._get_bool(self.KEY_WINDOW_MAXIMIZED, default=False)

    def set_window_maximized(self, maximized: bool) -> None:
        """Сохранить признак развернутого состояния окна."""
        self._set_bool(self.KEY_WINDOW_MAXIMIZED, maximized)

    def get_splitter_sizes(self) -> list[int] | None:
        """Получить сохраненные размеры панелей сплиттера [left, center, right]."""
        raw = self._get_string_list(self.KEY_SPLITTER_SIZES)
        if not raw:
            return None
        try:
            sizes = [int(x) for x in raw]
            if len(sizes) == 3 and all(s > 0 for s in sizes):
                return sizes
        except (ValueError, TypeError):
            pass
        return None

    def set_splitter_sizes(self, sizes: list[int]) -> None:
        """Сохранить размеры панелей сплиттера."""
        str_list = [str(int(s)) for s in sizes]
        self._set_string_list(self.KEY_SPLITTER_SIZES, str_list)

    def get_left_panel_visible(self) -> bool:
        """Видимость левой панели (Слои и Точки)."""
        return self._get_bool(self.KEY_LEFT_PANEL_VISIBLE, default=True)

    def set_left_panel_visible(self, visible: bool) -> None:
        """Сохранить видимость левой панели."""
        self._set_bool(self.KEY_LEFT_PANEL_VISIBLE, visible)

    def get_right_panel_visible(self) -> bool:
        """Видимость правой панели (Свойства)."""
        return self._get_bool(self.KEY_RIGHT_PANEL_VISIBLE, default=True)

    def set_right_panel_visible(self, visible: bool) -> None:
        """Сохранить видимость правой панели."""
        self._set_bool(self.KEY_RIGHT_PANEL_VISIBLE, visible)

    def get_toolbar_visible(self) -> bool:
        """Видимость верхней панели инструментов."""
        return self._get_bool(self.KEY_TOOLBAR_VISIBLE, default=True)

    def set_toolbar_visible(self, visible: bool) -> None:
        """Сохранить видимость верхней панели инструментов."""
        self._set_bool(self.KEY_TOOLBAR_VISIBLE, visible)

    def get_statusbar_visible(self) -> bool:
        """Видимость нижней строки состояния."""
        return self._get_bool(self.KEY_STATUSBAR_VISIBLE, default=True)

    def set_statusbar_visible(self, visible: bool) -> None:
        """Сохранить видимость нижней строки состояния."""
        self._set_bool(self.KEY_STATUSBAR_VISIBLE, visible)

    def get_point_labels_mode(self) -> str:
        """Режим отображения подписей точек: 'hidden', 'selected', 'all'."""
        if self._settings is not None:
            val = self._settings.value(self.KEY_POINT_LABELS_MODE, "hidden")
        else:
            val = self._memory_fallback.get(self.KEY_POINT_LABELS_MODE, "hidden")
        if isinstance(val, str) and val.lower() in {"hidden", "selected", "all"}:
            return val.lower()
        return "hidden"

    def set_point_labels_mode(self, mode: str) -> None:
        """Сохранить режим отображения подписей точек."""
        val = mode.lower() if mode.lower() in {"hidden", "selected", "all"} else "hidden"
        if self._settings is not None:
            self._settings.setValue(self.KEY_POINT_LABELS_MODE, val)
            if hasattr(self._settings, "sync"):
                self._settings.sync()
        else:
            self._memory_fallback[self.KEY_POINT_LABELS_MODE] = val

    def get_point_label_content(self) -> str:
        """Режим содержимого подписей точек: 'name', 'number', 'number_name'."""
        if self._settings is not None:
            val = self._settings.value(self.KEY_POINT_LABEL_CONTENT, "name")
        else:
            val = self._memory_fallback.get(self.KEY_POINT_LABEL_CONTENT, "name")
        if isinstance(val, str) and val.lower() in {"name", "number", "number_name"}:
            return val.lower()
        return "name"

    def set_point_label_content(self, content: str) -> None:
        """Сохранить режим содержимого подписей точек."""
        val = content.lower() if content.lower() in {"name", "number", "number_name"} else "name"
        if self._settings is not None:
            self._settings.setValue(self.KEY_POINT_LABEL_CONTENT, val)
            if hasattr(self._settings, "sync"):
                self._settings.sync()
        else:
            self._memory_fallback[self.KEY_POINT_LABEL_CONTENT] = val

    def get_show_points_visible(self) -> bool:
        """Глобальная видимость точек на холсте."""
        return self._get_bool(self.KEY_SHOW_POINTS_VISIBLE, default=True)

    def set_show_points_visible(self, visible: bool) -> None:
        """Сохранить глобальную видимость точек на холсте."""
        self._set_bool(self.KEY_SHOW_POINTS_VISIBLE, visible)

    def get_show_zones_visible(self) -> bool:
        """Глобальная видимость геодезических зон на холсте."""
        return self._get_bool(self.KEY_SHOW_ZONES_VISIBLE, default=True)

    def set_show_zones_visible(self, visible: bool) -> None:
        """Сохранить глобальную видимость геодезических зон на холсте."""
        self._set_bool(self.KEY_SHOW_ZONES_VISIBLE, visible)

    def get_show_scale_indicator(self) -> bool:
        """Видимость экранного индикатора масштаба в левом верхнем углу (по умолчанию True)."""
        return self._get_bool(self.KEY_SHOW_SCALE_INDICATOR, default=True)

    def set_show_scale_indicator(self, visible: bool) -> None:
        """Сохранить видимость экранного индикатора масштаба."""
        self._set_bool(self.KEY_SHOW_SCALE_INDICATOR, visible)

    def get_show_coordinate_grid(self) -> bool:
        """Видимость экранной координатной сетки (по умолчанию False)."""
        return self._get_bool(self.KEY_SHOW_COORDINATE_GRID, default=False)

    def set_show_coordinate_grid(self, visible: bool) -> None:
        """Сохранить видимость экранной координатной сетки."""
        self._set_bool(self.KEY_SHOW_COORDINATE_GRID, visible)

    def get_import_presets(self) -> list[dict[str, Any]]:
        """Получить список сохраненных пресетов сопоставления колонок импорта."""
        if self._settings is not None:
            val = self._settings.value(self.KEY_IMPORT_PRESETS, "[]")
        else:
            val = self._memory_fallback.get(self.KEY_IMPORT_PRESETS, "[]")
        if isinstance(val, str):
            try:
                import json
                parsed = json.loads(val)
                return parsed if isinstance(parsed, list) else []
            except Exception:
                return []
        return val if isinstance(val, list) else []

    def save_import_preset(self, name: str, preset_data: dict[str, Any]) -> None:
        """Сохранить или обновить пресет сопоставления по имени."""
        import json
        presets = self.get_import_presets()
        presets = [p for p in presets if p.get("name") != name]
        presets.append(preset_data)
        val = json.dumps(presets, ensure_ascii=False)
        if self._settings is not None:
            self._settings.setValue(self.KEY_IMPORT_PRESETS, val)
            if hasattr(self._settings, "sync"):
                self._settings.sync()
        else:
            self._memory_fallback[self.KEY_IMPORT_PRESETS] = val

    def delete_import_preset(self, name: str) -> bool:
        """Удалить пресет сопоставления по имени."""
        import json
        presets = self.get_import_presets()
        initial_len = len(presets)
        presets = [p for p in presets if p.get("name") != name]
        if len(presets) < initial_len:
            val = json.dumps(presets, ensure_ascii=False)
            if self._settings is not None:
                self._settings.setValue(self.KEY_IMPORT_PRESETS, val)
                if hasattr(self._settings, "sync"):
                    self._settings.sync()
            else:
                self._memory_fallback[self.KEY_IMPORT_PRESETS] = val
            return True
        return False

    def clear(self) -> None:
        """Очистить сохраненные настройки (для изолированного тестирования)."""
        if self._settings is not None:
            self._settings.clear()
            if hasattr(self._settings, "sync"):
                self._settings.sync()
        self._memory_fallback.clear()

    # --- Online Maps Settings ---
    def get_online_cache_max_mb(self) -> int:
        """Получить максимальный размер дискового кэша тайлов в МБ (по умолчанию 256)."""
        val = self._get_str(self.KEY_ONLINE_CACHE_MAX_MB, "256")
        try:
            return max(16, int(val))
        except (ValueError, TypeError):
            return 256

    def set_online_cache_max_mb(self, mb: int) -> None:
        """Установить максимальный размер дискового кэша тайлов в МБ."""
        self._set_str(self.KEY_ONLINE_CACHE_MAX_MB, str(max(16, mb)))

    def get_last_online_provider(self) -> str:
        """Получить ID последнего выбранного онлайн-провайдера."""
        return self._get_str(self.KEY_LAST_ONLINE_PROVIDER, "osm_standard")

    def set_last_online_provider(self, provider_id: str) -> None:
        """Сохранить ID последнего выбранного онлайн-провайдера."""
        self._set_str(self.KEY_LAST_ONLINE_PROVIDER, provider_id)

    def get_provider_api_key(self, provider_id: str) -> str:
        """Получить локально сохраненный API-ключ для провайдера."""
        import json
        raw = self._get_str(self.KEY_ONLINE_API_KEYS, "{}")
        try:
            data = json.loads(raw)
            if isinstance(data, dict):
                return str(data.get(provider_id) or "")
        except Exception:
            pass
        return ""

    def set_provider_api_key(self, provider_id: str, key: str) -> None:
        """Сохранить локальный API-ключ для провайдера."""
        import json
        raw = self._get_str(self.KEY_ONLINE_API_KEYS, "{}")
        try:
            data = json.loads(raw)
            if not isinstance(data, dict):
                data = {}
        except Exception:
            data = {}
        if key.strip():
            data[provider_id] = key.strip()
        else:
            data.pop(provider_id, None)
        self._set_str(self.KEY_ONLINE_API_KEYS, json.dumps(data))

    def get_custom_providers(self) -> list[dict[str, Any]]:
        """Получить список пользовательских XYZ-провайдеров."""
        import json
        raw = self._get_str(self.KEY_CUSTOM_XYZ_PROVIDERS, "[]")
        try:
            data = json.loads(raw)
            return data if isinstance(data, list) else []
        except Exception:
            return []

    def save_custom_provider(self, provider_data: dict[str, Any]) -> None:
        """Сохранить или обновить конфигурацию пользовательского XYZ-провайдера."""
        import json
        providers = self.get_custom_providers()
        pid = provider_data.get("id")
        providers = [p for p in providers if p.get("id") != pid]
        providers.append(provider_data)
        self._set_str(self.KEY_CUSTOM_XYZ_PROVIDERS, json.dumps(providers, ensure_ascii=False))

    def delete_custom_provider(self, provider_id: str) -> bool:
        """Удалить пользовательского XYZ-провайдера."""
        import json
        providers = self.get_custom_providers()
        initial_len = len(providers)
        providers = [p for p in providers if p.get("id") != provider_id]
        if len(providers) < initial_len:
            self._set_str(self.KEY_CUSTOM_XYZ_PROVIDERS, json.dumps(providers, ensure_ascii=False))
            return True
        return False

