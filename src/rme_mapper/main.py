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

from PySide6.QtWidgets import QApplication

from rme_mapper.app_info import APP_NAME
from rme_mapper.ui.main_window import MainWindow


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

    app = QApplication(sys.argv)
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
            from rme_mapper.services.app_settings_service import AppSettingsService
            settings = AppSettingsService()
            _ = settings.get_language()

            # 4. Валидация BackendFactory (GeoPackage и GeoTIFF)
            from rme_mapper.backends.factory import BackendFactory
            gpkg_backend = BackendFactory.get_backend()
            raster_backend = BackendFactory.get_raster_backend()
            if gpkg_backend is None or raster_backend is None:
                raise RuntimeError("Бэкенды GeoPackage/GeoTIFF не инициализированы")

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

    project_path = parse_cli_project_path(sys.argv)
    window = MainWindow(project_path=project_path)
    if 'app_icon' in locals() and not app_icon.isNull():
        window.setWindowIcon(app_icon)

    window.show()

    exit_code = app.exec()
    logger.info("Завершение работы приложения с кодом %d", exit_code)
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
