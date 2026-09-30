"""Пакет интернационализации и локализации (i18n) приложения GeoPoint Mapper."""
from __future__ import annotations


from rme_mapper.i18n.translation_service import (
    DEFAULT_LANGUAGE,
    SUPPORTED_LANGUAGES,
    TranslationService,
    get_language,
    get_translation_service,
    set_language,
    tr,
)

__all__ = [
    "DEFAULT_LANGUAGE",
    "SUPPORTED_LANGUAGES",
    "TranslationService",
    "get_language",
    "get_translation_service",
    "set_language",
    "tr",
]
