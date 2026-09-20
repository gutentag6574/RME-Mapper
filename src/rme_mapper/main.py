"""Точка входа приложения RME-Mapper."""

import logging
import sys
from pathlib import Path

# Обеспечиваем доступность пакета при прямом запуске скрипта
project_src = Path(__file__).resolve().parent.parent
if str(project_src) not in sys.path:
    sys.path.insert(0, str(project_src))

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


def main() -> int:
    """Основная функция запуска приложения."""
    setup_logging()
    logger = logging.getLogger("rme_mapper")
    logger.info("Запуск приложения %s...", APP_NAME)

    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationDisplayName(APP_NAME)

    window = MainWindow()
    window.show()

    exit_code = app.exec()
    logger.info("Завершение работы приложения с кодом %d", exit_code)
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
