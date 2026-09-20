"""Общие фикстуры для тестирования приложения GeoPoint Mapper."""

import os
import pytest
from rme_mapper.services.project_service import ProjectService


@pytest.fixture(autouse=True)
def clean_recovery_snapshot():
    """Предотвращает влияние файлов аварийного восстановления и настроек на тесты."""
    from rme_mapper.services.app_settings_service import AppSettingsService
    ProjectService.clear_recovery_snapshot()
    AppSettingsService().clear()
    yield
    ProjectService.clear_recovery_snapshot()
    AppSettingsService().clear()


@pytest.fixture(scope="session")
def qapp():
    """Общий экземпляр QApplication для тестов интерфейса."""
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app

