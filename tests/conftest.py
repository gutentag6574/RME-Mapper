"""Общие фикстуры для тестирования приложения GeoPoint Mapper."""

import os
import pytest
from rme_mapper.services.project_service import ProjectService


@pytest.fixture(autouse=True)
def clean_recovery_snapshot():
    """Предотвращает влияние файлов аварийного восстановления на тесты."""
    ProjectService.clear_recovery_snapshot()
    yield
    ProjectService.clear_recovery_snapshot()
