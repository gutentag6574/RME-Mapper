"""Единый сервис локализации и переводов (TranslationService) для GeoPoint Mapper."""

import logging
from typing import Any, Callable

from rme_mapper.i18n.translations_en import TRANSLATIONS_EN
from rme_mapper.i18n.translations_ru import TRANSLATIONS_RU

logger = logging.getLogger("rme_mapper.i18n")

SUPPORTED_LANGUAGES = ("ru", "en")
DEFAULT_LANGUAGE = "ru"

# Попытка импортировать Qt Signal для UI уведомлений
try:
    from PySide6.QtCore import QObject, Signal

    class _SignalEmitter(QObject):
        language_changed = Signal(str)

except ImportError:
    _SignalEmitter = None  # type: ignore


class TranslationService:
    """Сервис управления переводами интерфейса.

    Поддерживает:
    - переключение активного языка ('ru', 'en');
    - форматирование с именованными параметрами;
    - безопасный fallback при отсутствии ключа;
    - уведомление подписчиков через сигналы Qt или прямые колбэки.
    """

    def __init__(self, default_language: str = DEFAULT_LANGUAGE) -> None:
        self._current_language: str = (
            default_language if default_language in SUPPORTED_LANGUAGES else DEFAULT_LANGUAGE
        )
        self._dictionaries: dict[str, dict[str, str]] = {
            "ru": TRANSLATIONS_RU,
            "en": TRANSLATIONS_EN,
        }
        self._callbacks: list[Callable[[str], None]] = []

        if _SignalEmitter is not None:
            self._emitter = _SignalEmitter()
        else:
            self._emitter = None

    @property
    def language_changed(self) -> Any:
        """Сигнал PySide6 для подключения UI-слоя (при наличии PySide6)."""
        if self._emitter is not None:
            return self._emitter.language_changed
        return None

    def get_supported_languages(self) -> list[str]:
        """Возвращает список поддерживаемых языковых кодов."""
        return list(SUPPORTED_LANGUAGES)

    def get_language(self) -> str:
        """Возвращает текущий активный код языка."""
        return self._current_language

    def set_language(self, language_code: str) -> None:
        """Устанавливает текущий активный язык.

        Параметры:
            language_code: код языка ('ru' или 'en').
        Исключения:
            ValueError: если передан неподдерживаемый язык.
        """
        code = (language_code or "").strip().lower()
        if code not in SUPPORTED_LANGUAGES:
            raise ValueError(
                f"Неподдерживаемый код языка: '{language_code}'. "
                f"Допустимы: {list(SUPPORTED_LANGUAGES)}"
            )

        if self._current_language == code:
            return

        self._current_language = code
        logger.info("Язык интерфейса переключен на: %s", code)

        # Оповещение через PySide6 сигнал
        if self._emitter is not None:
            self._emitter.language_changed.emit(code)

        # Оповещение через прямые колбэки
        for callback in list(self._callbacks):
            try:
                callback(code)
            except Exception as err:
                logger.error("Ошибка при вызове слушателя смены языка: %s", err)

    def register_listener(self, callback: Callable[[str], None]) -> None:
        """Регистрация функции обратного вызова при смене языка."""
        if callback not in self._callbacks:
            self._callbacks.append(callback)

    def unregister_listener(self, callback: Callable[[str], None]) -> None:
        """Удаление функции обратного вызова."""
        if callback in self._callbacks:
            self._callbacks.remove(callback)

    def has_translation(self, key: str, language_code: str | None = None) -> bool:
        """Проверяет наличие перевода для заданного ключа."""
        lang = language_code or self._current_language
        dict_for_lang = self._dictionaries.get(lang)
        if dict_for_lang and key in dict_for_lang:
            return True
        return False

    def translate_in_language(self, lang: str, key: str, **kwargs: Any) -> str:
        """Перевод ключа в конкретно указанном языке."""
        dict_for_lang = self._dictionaries.get(lang)
        if dict_for_lang and key in dict_for_lang:
            template = dict_for_lang[key]
        elif key in TRANSLATIONS_EN:
            template = TRANSLATIONS_EN[key]
        elif key in TRANSLATIONS_RU:
            template = TRANSLATIONS_RU[key]
        else:
            logger.warning("Отсутствует ключ перевода: '%s' (lang=%s)", key, lang)
            template = key

        if kwargs:
            try:
                return template.format(**kwargs)
            except Exception as err:
                logger.warning("Ошибка форматирования ключа '%s': %s", key, err)
                return template
        return template

    def translate(self, key: str, **kwargs: Any) -> str:
        """Переводит ключ на текущий активный язык.

        При отсутствии ключа логирует предупреждение и возвращает fallback
        (сначала английский вариант, затем сам ключ).
        """
        return self.translate_in_language(self._current_language, key, **kwargs)


# Глобальный экземпляр сервиса переводов (Singleton)
_translation_service_instance: TranslationService | None = None


def get_translation_service() -> TranslationService:
    """Возвращает глобальный экземпляр TranslationService."""
    global _translation_service_instance
    if _translation_service_instance is None:
        _translation_service_instance = TranslationService()
    return _translation_service_instance


def set_language(language_code: str) -> None:
    """Устанавливает текущий язык глобального TranslationService."""
    get_translation_service().set_language(language_code)


def get_language() -> str:
    """Возвращает текущий язык глобального TranslationService."""
    return get_translation_service().get_language()


def tr(key: str, **kwargs: Any) -> str:
    """Удобный короткий хелпер для перевода ключа на текущий язык."""
    return get_translation_service().translate(key, **kwargs)
