"""Централизованный слой обнаружения возможностей среды (RuntimeCapabilities).

Предоставляет единый интерфейс запроса рантайм-возможностей приложения
(наличие GIS-библиотек, растровых бэкендов, безопасного TLS, поддержки форматов)
без размазывания платформенных проверок по кодовой базе.
"""

import logging
import platform
import sys
from typing import Any

from rme_mapper.app_info import APP_NAME, APP_VERSION

logger = logging.getLogger("rme_mapper.capabilities")


class RuntimeCapabilities:
    """Единый сервис диагностики и проверки доступности функций в текущей среде."""

    _overrides: dict[str, bool] = {}
    _profile_override: str | None = None

    # -------------------------------------------------------------------------
    # Тестовые оверрайды (для симуляции Legacy / Limited профилей)
    # -------------------------------------------------------------------------

    @classmethod
    def override_for_testing(
        cls,
        profile: str | None = None,
        **kwargs: bool,
    ) -> None:
        """Временная подмена возможностей для изолированных автоматических тестов."""
        if profile is not None:
            cls._profile_override = profile.lower()
        for k, v in kwargs.items():
            cls._overrides[k] = bool(v)

    @classmethod
    def reset_overrides(cls) -> None:
        """Сброс всех тестовых оверрайдов к реальным возможностям среды."""
        cls._overrides.clear()
        cls._profile_override = None

    # -------------------------------------------------------------------------
    # Профиль среды
    # -------------------------------------------------------------------------

    @classmethod
    def get_profile_name(cls) -> str:
        """Определение имени активного профиля окружения ('modern', 'win7', 'xp', 'custom')."""
        if cls._profile_override:
            return cls._profile_override

        system = platform.system()
        if system != "Windows":
            return "modern"

        release = platform.release()
        try:
            ver_major = sys.getwindowsversion().major
            ver_minor = sys.getwindowsversion().minor
        except Exception:
            ver_major = 10
            ver_minor = 0

        if ver_major >= 10:
            return "modern"
        elif ver_major == 6 and ver_minor <= 1:
            return "win7"
        elif ver_major <= 5:
            return "xp"
        return "modern"

    # -------------------------------------------------------------------------
    # Базовые возможности (Capabilities)
    # -------------------------------------------------------------------------

    @classmethod
    def supports_secure_tls(cls) -> bool:
        """Проверка поддержки криптографически безопасного TLS (TLS 1.2/1.3)."""
        if "supports_secure_tls" in cls._overrides:
            return cls._overrides["supports_secure_tls"]

        profile = cls.get_profile_name()
        if profile == "xp":
            # На Windows XP безопасный TLS недоступен (устаревший Schannel / OpenSSL 1.0.1)
            return False

        try:
            import ssl
            # Проверяем наличие TLS 1.2+ в OpenSSL
            protocols = getattr(ssl, "HAS_TLSv1_2", False)
            if not protocols:
                return False
            # Проверяем поддержку SSL в QtNetwork
            try:
                from PySide6.QtNetwork import QSslSocket
                return QSslSocket.supportsSsl()
            except ImportError:
                return True
        except Exception:
            return False

    @classmethod
    def supports_online_maps(cls) -> bool:
        """Проверка доступности онлайн-карт (требует безопасный TLS и QtNetwork)."""
        if "supports_online_maps" in cls._overrides:
            return cls._overrides["supports_online_maps"]

        # Правило 7: Если безопасный TLS невозможен — онлайн-карты отключены
        if not cls.supports_secure_tls():
            return False

        try:
            from PySide6.QtNetwork import QNetworkAccessManager
            return True
        except ImportError:
            return False

    @classmethod
    def supports_geopackage(cls) -> bool:
        """Проверка поддержки формата векторных карт GeoPackage."""
        if "supports_geopackage" in cls._overrides:
            return cls._overrides["supports_geopackage"]

        try:
            from rme_mapper.backends.modern import ModernGeoPackageBackend
            return True
        except Exception:
            # Fallback на чтение через sqlite3
            try:
                import sqlite3
                return True
            except ImportError:
                return False

    @classmethod
    def supports_geotiff(cls) -> bool:
        """Проверка поддержки растровых карт GeoTIFF."""
        if "supports_geotiff" in cls._overrides:
            return cls._overrides["supports_geotiff"]

        try:
            from rme_mapper.backends.modern_raster import ModernGeoTiffBackend
            return ModernGeoTiffBackend.is_available()
        except Exception:
            return False

    @classmethod
    def supports_georeferencing(cls) -> bool:
        """Проверка поддержки ручной геопривязки растровых изображений."""
        if "supports_georeferencing" in cls._overrides:
            return cls._overrides["supports_georeferencing"]
        return True

    @classmethod
    def supports_xlsx(cls) -> bool:
        """Проверка доступности импорта/экспорта таблиц Excel (openpyxl)."""
        if "supports_xlsx" in cls._overrides:
            return cls._overrides["supports_xlsx"]
        try:
            import openpyxl
            return True
        except ImportError:
            return False

    @classmethod
    def supports_webp(cls) -> bool:
        """Проверка поддержки формата WebP для растров."""
        if "supports_webp" in cls._overrides:
            return cls._overrides["supports_webp"]
        try:
            from PySide6.QtGui import QImageReader
            supported = QImageReader.supportedImageFormats()
            return b"webp" in supported or b"WEBP" in supported
        except Exception:
            return False

    @classmethod
    def supports_high_dpi(cls) -> bool:
        """Проверка аппаратной поддержки High DPI масштабирования."""
        if "supports_high_dpi" in cls._overrides:
            return cls._overrides["supports_high_dpi"]
        profile = cls.get_profile_name()
        return profile not in ("xp", "win7")

    @classmethod
    def supports_source_type(cls, source_type: str) -> bool:
        """Проверка поддержки типа источника карты ('geopackage', 'geotiff', 'online_xyz', 'georeferenced_image')."""
        st = (source_type or "").strip().lower()
        if st == "geopackage":
            return cls.supports_geopackage()
        elif st == "geotiff":
            return cls.supports_geotiff()
        elif st == "online_xyz":
            return cls.supports_online_maps()
        elif st in ("georeferenced_image", "image"):
            return cls.supports_georeferencing()
        return False

    # -------------------------------------------------------------------------
    # Диагностика и сводка
    # -------------------------------------------------------------------------

    @classmethod
    def get_capabilities_summary(cls) -> dict[str, Any]:
        """Формирование сводного словаря текущих возможностей."""
        return {
            "profile": cls.get_profile_name(),
            "supports_geopackage": cls.supports_geopackage(),
            "supports_geotiff": cls.supports_geotiff(),
            "supports_online_maps": cls.supports_online_maps(),
            "supports_georeferencing": cls.supports_georeferencing(),
            "supports_xlsx": cls.supports_xlsx(),
            "supports_webp": cls.supports_webp(),
            "supports_high_dpi": cls.supports_high_dpi(),
            "supports_secure_tls": cls.supports_secure_tls(),
        }

    @classmethod
    def get_unavailable_features(cls) -> list[str]:
        """Список недоступных в текущей конфигурации функций с пояснениями."""
        unavailable: list[str] = []
        if not cls.supports_geotiff():
            unavailable.append("GeoTIFF (rasterio/GDAL backend unavailable)")
        if not cls.supports_online_maps():
            if not cls.supports_secure_tls():
                unavailable.append("Online Maps (secure TLS 1.2+ unavailable on legacy platform)")
            else:
                unavailable.append("Online Maps (network manager unavailable)")
        if not cls.supports_xlsx():
            unavailable.append("XLSX Import/Export (openpyxl library not installed)")
        if not cls.supports_webp():
            unavailable.append("WebP Image Format (Qt WebP image plugin not found)")
        return unavailable

    @classmethod
    def log_runtime_environment(cls) -> None:
        """Запись параметров среды, архитектуры и возможностей в стартовый лог (Правило 33)."""
        system = platform.system()
        release = platform.release()
        version = platform.version()
        machine = platform.machine()
        py_ver = sys.version.split()[0]
        arch = "64-bit" if sys.maxsize > 2**32 else "32-bit"

        qt_ver = "Unknown"
        try:
            from PySide6.QtCore import qVersion
            qt_ver = f"PySide6 (Qt {qVersion()})"
        except ImportError:
            try:
                from PyQt5.QtCore import qVersion
                qt_ver = f"PyQt5 (Qt {qVersion()})"
            except ImportError:
                pass

        logger.info(
            "=== %s v%s Startup Environment ===",
            APP_NAME,
            APP_VERSION,
        )
        logger.info("OS: %s %s (v%s) [%s, %s]", system, release, version, machine, arch)
        logger.info("Python: %s | GUI: %s | Profile: %s", py_ver, qt_ver, cls.get_profile_name())

        caps = cls.get_capabilities_summary()
        logger.info(
            "Capabilities: GPKG=%s, GeoTIFF=%s, OnlineMaps=%s, Georef=%s, XLSX=%s, TLS=%s",
            caps["supports_geopackage"],
            caps["supports_geotiff"],
            caps["supports_online_maps"],
            caps["supports_georeferencing"],
            caps["supports_xlsx"],
            caps["supports_secure_tls"],
        )

        unavailable = cls.get_unavailable_features()
        if unavailable:
            logger.warning("Unavailable optional features: %s", ", ".join(unavailable))
        else:
            logger.info("All optional features are fully supported.")
