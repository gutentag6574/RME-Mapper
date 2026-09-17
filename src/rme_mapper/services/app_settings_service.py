"""Сервис хранения пользовательских настроек приложения (AppSettingsService)."""

import logging
from typing import Any

try:
    from PySide6.QtCore import QSettings
except ImportError:
    QSettings = None  # type: ignore

from rme_mapper.i18n import DEFAULT_LANGUAGE, SUPPORTED_LANGUAGES

logger = logging.getLogger("rme_mapper.services.settings")


class AppSettingsService:
    """Тонкая обертка над QSettings для централизованного управления настройками приложения.

    Изолирует остальной UI от прямых вызовов QSettings по проекту.
    """

    ORGANIZATION_NAME = "GeoPointMapper"
    APPLICATION_NAME = "GeoPointMapper"
    KEY_LANGUAGE = "ui/language"

    def __init__(self, settings: Any = None) -> None:
        if settings is not None:
            self._settings = settings
        elif QSettings is not None:
            self._settings = QSettings(self.ORGANIZATION_NAME, self.APPLICATION_NAME)
        else:
            self._settings = None
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

    def clear(self) -> None:
        """Очистить сохраненные настройки (для изолированного тестирования)."""
        if self._settings is not None:
            self._settings.clear()
            if hasattr(self._settings, "sync"):
                self._settings.sync()
        self._memory_fallback.clear()
