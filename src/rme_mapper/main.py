"""Точка входа приложения RME-Mapper."""
from __future__ import annotations


import logging
import sys
from pathlib import Path

# Обеспечиваем доступность пакета при прямом запуске скрипта
project_src = Path(__file__).resolve().parent.parent
if str(project_src) not in sys.path:
    sys.path.insert(0, str(project_src))

import rme_mapper  # noqa: F401 - инициализирует PROJ_DATA, GDAL_DATA и DLL каталоги
import rme_mapper.qt_compat  # noqa: F401 - подключает shim PySide6 для PySide2/PyQt5 на Win7

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from rme_mapper.app_info import APP_NAME
from rme_mapper.i18n import set_language
from rme_mapper.services.app_settings_service import AppSettingsService
from rme_mapper.services.license_service import LicenseCheckResult, LicenseService
from rme_mapper.ui.activation_dialog import show_blocking_activation
from rme_mapper.ui.license_controller import LicenseController
from rme_mapper.ui.main_window import MainWindow
from rme_mapper.ui.theme_manager import get_theme_manager


def setup_logging() -> None:
    """Настройка стандартного логирования приложения."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )


def parse_cli_project_path(argv: list[str]) -> Path | None:
    """Извлечение пути к файлу проекта из аргументов командной строки.

    Игнорирует системные флаги, проверяет расширения (.gpmap, .rmeproject),
    корректно обрабатывает кавычки, пробелы, кириллицу и Unicode.
    """
    logger = logging.getLogger("rme_mapper")
    for arg in argv[1:]:
        if arg.startswith("-"):
            continue
        cleaned = arg.strip().strip('"').strip("'")
        if not cleaned:
            continue
        p = Path(cleaned)
        if p.suffix.lower() in (".gpmap", ".rmeproject"):
            return p.resolve() if p.exists() else p
        else:
            logger.warning("Передан неподдерживаемый аргумент файла проекта: %s", arg)
    return None


def main() -> int:
    """Основная функция запуска приложения."""
    setup_logging()
    logger = logging.getLogger("rme_mapper")
    logger.info("Запуск приложения %s...", APP_NAME)

    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName(APP_NAME)

    def _cleanup_backends() -> None:
        try:
            from rme_mapper.backends.factory import BackendFactory
            BackendFactory.close_all()
        except Exception:
            pass

    app.aboutToQuit.connect(_cleanup_backends)

    try:
        from rme_mapper.services.runtime_capabilities import RuntimeCapabilities
        RuntimeCapabilities.log_runtime_environment()
    except Exception as e:
        logger.warning("Не удалось записать параметры окружения: %s", e)

    # Установка официальной иконки приложения
    try:
        from PySide6.QtGui import QIcon
        res_dir = Path(__file__).resolve().parent / "resources"
        icon_path = res_dir / "icon.png" if (res_dir / "icon.png").exists() else res_dir / "icon.ico"
        if icon_path.exists():
            app_icon = QIcon(str(icon_path))
            app.setWindowIcon(app_icon)
    except Exception as e:
        logger.debug("Не удалось загрузить иконку приложения: %s", e)

    # Специальный режим быстрой автономной валидации запуска (Smoke Test)
    if "--smoke-test" in sys.argv:
        logger.info("Режим --smoke-test: валидация инициализации ГИС-подсистемы и UI...")
        try:
            window = MainWindow()
            if 'app_icon' in locals() and not app_icon.isNull():
                window.setWindowIcon(app_icon)
            # 1. Валидация CoordinateService (WGS84, Web Mercator, UTM)
            from rme_mapper.services.coordinate_service import CoordinateService
            x, y = CoordinateService.transform_xy(37.6173, 55.7558, "EPSG:4326", "EPSG:3857")
            lon, lat = CoordinateService.transform_xy(x, y, "EPSG:3857", "EPSG:4326")
            if abs(lon - 37.6173) > 1e-4 or abs(lat - 55.7558) > 1e-4:
                raise RuntimeError(f"Сбой трансформации координат: ({lon}, {lat})")

            # 2. Валидация ProjectData и ProjectPointData
            from rme_mapper.models.project_data import ProjectData, ProjectPointData
            pt_data = ProjectPointData(id="smoke_1", name="Smoke Point", latitude=55.7558, longitude=37.6173)
            proj = ProjectData(points=[pt_data])
            d = proj.to_dict()
            restored = ProjectData.from_dict(d)
            if len(restored.points) != 1 or restored.points[0].name != "Smoke Point":
                raise RuntimeError("Сбой сериализации/десериализации проекта в smoke test")

            # 3. Валидация AppSettingsService
            settings = AppSettingsService()
            _ = settings.get_language()

            # 4. Валидация BackendFactory (GeoPackage и GeoTIFF)
            from rme_mapper.backends.factory import BackendFactory
            gpkg_backend = BackendFactory.get_backend()
            raster_backend = BackendFactory.get_raster_backend()
            if gpkg_backend is None or raster_backend is None:
                raise RuntimeError("Бэкенды GeoPackage/GeoTIFF не инициализированы")

            # 5. Валидация криптографии Ed25519 и службы лицензирования
            import tempfile
            from rme_mapper.services.credential_store import MemoryCredentialStore

            with tempfile.TemporaryDirectory() as tmp_dir:
                smoke_lic = LicenseService(
                    credential_store=MemoryCredentialStore(),
                    cache_path=Path(tmp_dir) / "license_cache.json",
                )
                smoke_res = smoke_lic.get_status_snapshot()
                if smoke_res.authorized:
                    raise RuntimeError("Пустое хранилище лицензий не должно проходить проверку")

            app.processEvents()
            window.show()
            app.processEvents()
            window.close()
            app.processEvents()
            _cleanup_backends()
            try:
                Path("smoke_success.txt").write_text("SMOKE-TEST SUCCESS", encoding="utf-8")
            except Exception:
                pass
            logger.info("[SMOKE-TEST] SUCCESS: Интерфейс и ГИС-модули успешно инициализированы.")
            print("[SMOKE-TEST] SUCCESS")
            return 0
        except Exception as e:
            _cleanup_backends()
            logger.error("[SMOKE-TEST] Ошибка при валидации: %s", e, exc_info=True)
            print(f"[SMOKE-TEST] FAILED: {e}", file=sys.stderr)
            return 1

    # Применяем язык и тему до возможного показа окна активации
    settings = AppSettingsService()
    set_language(settings.get_language())
    try:
        theme_mode = settings.get_str("ui/theme", "light")
        get_theme_manager().apply_theme(app, theme_mode)
    except Exception:
        pass

    license_service = LicenseService()
    ok, _initial_state = ensure_startup_license(license_service)
    if not ok:
        logger.info("Запуск отменён: лицензия не подтверждена.")
        return 0

    project_path = parse_cli_project_path(sys.argv)
    window = MainWindow(project_path=project_path, license_service=license_service)
    license_controller = LicenseController(license_service, main_window=window)
    window.set_license_controller(license_controller)
    if 'app_icon' in locals() and not app_icon.isNull():
        window.setWindowIcon(app_icon)

    window.show()
    QTimer.singleShot(300, license_controller.check_now_async)
    QTimer.singleShot(500, license_controller.start)

    exit_code = app.exec()
    license_controller.stop()
    logger.info("Завершение работы приложения с кодом %d", exit_code)
    return exit_code


def ensure_startup_license(
    license_service: LicenseService,
    *,
    interactive: bool = True,
) -> tuple[bool, LicenseCheckResult]:
    """Проверить лицензию перед созданием главного окна и при необходимости показать активацию."""
    res = license_service.check_startup_access()
    if res.authorized:
        return True, res
    if not interactive:
        return False, res
    accepted, new_res = show_blocking_activation(license_service, initial_result=res)
    if accepted and new_res is not None and new_res.authorized:
        return True, new_res
    return False, new_res or res


if __name__ == "__main__":
    sys.exit(main())
