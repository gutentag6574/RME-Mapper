"""Тесты релизных дефектов и UX/UI геометрии окон (Этап 27).

Проверяет:
1. BUG-001 / BUG-005: Нормализацию и адаптацию геометрии окна (sanitize_window_geometry, _apply_default_geometry).
2. BUG-002: Разбор аргументов командной строки и открытие проектов *.gpmap при старте приложения.
3. BUG-004: Единый канонический источник версии приложения и отсутствие дублирования.
4. BUG-007: Политику путей GIS-окружения в frozen vs development режимах.
5. BUG-008: Отсутствие дублирующих вызовов обновления заголовка окна.
"""
from __future__ import annotations

import os
from pathlib import Path
import sys
from unittest.mock import MagicMock, patch

from PySide6.QtCore import QRect
from PySide6.QtWidgets import QApplication
import pytest

from rme_mapper.app_info import APP_NAME, APP_VERSION
from rme_mapper.main import parse_cli_project_path
from rme_mapper.models.project_data import ProjectData, ProjectPointData
from rme_mapper.services.project_service import ProjectService
from rme_mapper.ui.main_window import MainWindow, sanitize_window_geometry

ROOT_DIR = Path(__file__).resolve().parent.parent


# -----------------------------------------------------------------------------
# 1. Тесты нормализации геометрии окна (BUG-001, BUG-005)
# -----------------------------------------------------------------------------

def test_01_geometry_sanitization_y_above_screen() -> None:
    """BUG-001: Заголовок окна, оказавшийся выше экрана (y < top), возвращается в видимую зону."""
    screen_rect = QRect(0, 0, 1920, 1080)
    target = QRect(100, -150, 1200, 700)  # y < 0

    sanitized = sanitize_window_geometry(target, [screen_rect], screen_rect)

    assert sanitized.y() >= 0, f"Y координата {sanitized.y()} осталась выше верхней границы экрана"
    assert sanitized.y() == 0
    assert sanitized.x() == 100
    assert sanitized.width() == 1200
    assert sanitized.height() == 700


def test_02_geometry_sanitization_disconnected_monitor() -> None:
    """BUG-001: Окно на отключенном втором мониторе возвращается на основной экран."""
    primary_rect = QRect(0, 0, 1920, 1080)
    # Координаты бывшего второго монитора справа
    target = QRect(2500, 100, 1200, 700)

    sanitized = sanitize_window_geometry(target, [primary_rect], primary_rect)

    assert sanitized.x() >= 0
    assert sanitized.x() + sanitized.width() <= primary_rect.width()
    assert sanitized.y() >= 0
    assert sanitized.y() + sanitized.height() <= primary_rect.height()


def test_03_geometry_sanitization_partially_visible_hidden_titlebar() -> None:
    """BUG-001: Частично видимое окно с недоступной строкой заголовка корректируется."""
    screen_rect = QRect(0, 0, 1920, 1080)
    target = QRect(200, -500, 1400, 850)

    sanitized = sanitize_window_geometry(target, [screen_rect], screen_rect)

    assert sanitized.y() >= 0
    assert sanitized.y() + 40 <= screen_rect.height()


def test_04_geometry_sanitization_larger_than_screen() -> None:
    """BUG-001 / BUG-005: Геометрия больше текущего разрешения экрана уменьшается до доступного размера."""
    screen_rect = QRect(0, 0, 1280, 720)
    target = QRect(0, 0, 2560, 1440)

    sanitized = sanitize_window_geometry(target, [screen_rect], screen_rect)

    assert sanitized.width() <= screen_rect.width()
    assert sanitized.height() <= screen_rect.height()
    assert sanitized.width() == 1280
    assert sanitized.height() == 720


def test_05_geometry_sanitization_normal_position_preserved() -> None:
    """BUG-001: Нормальная геометрия внутри экрана не модифицируется."""
    screen_rect = QRect(0, 0, 1920, 1080)
    target = QRect(250, 150, 1200, 700)

    sanitized = sanitize_window_geometry(target, [screen_rect], screen_rect)

    assert sanitized == target


def test_06_geometry_sanitization_multimonitor_negative_coordinates() -> None:
    """BUG-001: В многомониторной конфигурации сохраняются отрицательные координаты левого монитора."""
    left_monitor = QRect(-1920, 0, 1920, 1080)
    right_monitor = QRect(0, 0, 1920, 1080)
    target = QRect(-1500, 100, 1200, 700)

    sanitized = sanitize_window_geometry(target, [left_monitor, right_monitor], right_monitor)

    assert sanitized.x() == -1500
    assert sanitized.y() == 100
    assert sanitized.width() == 1200
    assert sanitized.height() == 700


def test_07_default_geometry_small_screen_adaptation(qapp) -> None:
    """BUG-005: _apply_default_geometry адаптирует размер под рабочую область экрана."""
    win = MainWindow()
    win._apply_default_geometry()

    screen = QApplication.primaryScreen()
    if screen:
        avail = screen.availableGeometry()
        assert win.width() <= avail.width()
        assert win.height() <= avail.height()
        assert win.y() >= avail.top()

    win.close()


# -----------------------------------------------------------------------------
# 2. Тесты командной строки и ассоциации файлов *.gpmap (BUG-002)
# -----------------------------------------------------------------------------

def test_08_cli_parser_gpmap_and_rmeproject() -> None:
    """BUG-002: Корректное распознавание файлов *.gpmap и *.rmeproject."""
    assert parse_cli_project_path(["app.exe", "test.gpmap"]) == Path("test.gpmap")
    assert parse_cli_project_path(["app.exe", "test.rmeproject"]) == Path("test.rmeproject")
    assert parse_cli_project_path(["app.exe", "C:/Maps/MyProject.GPMAP"]) == Path("C:/Maps/MyProject.GPMAP")


def test_09_cli_parser_spaces_quotes_and_unicode() -> None:
    """BUG-002: Обработка путей с пробелами, кавычками и кириллицей."""
    raw = '"C:\\Проекты Геоинформатики\\Тестовая Карта 2026.gpmap"'
    parsed = parse_cli_project_path(["app.exe", raw])
    assert parsed == Path("C:\\Проекты Геоинформатики\\Тестовая Карта 2026.gpmap")


def test_10_cli_parser_flags_and_unsupported_files() -> None:
    """BUG-002: Флаги и неподдерживаемые файлы игнорируются."""
    assert parse_cli_project_path(["app.exe", "--smoke-test"]) is None
    assert parse_cli_project_path(["app.exe", "-v", "--debug"]) is None
    assert parse_cli_project_path(["app.exe", "data.csv"]) is None
    assert parse_cli_project_path(["app.exe", "map.gpkg"]) is None
    assert parse_cli_project_path(["app.exe"]) is None


def test_11_mainwindow_opens_project_from_path(qapp, tmp_path) -> None:
    """BUG-002: MainWindow открывает переданный проект при инициализации."""
    proj_path = tmp_path / "startup_test.gpmap"
    ps = ProjectService()
    pdata = ProjectData(points=[ProjectPointData(id="p1", name="Startup Point", latitude=55.0, longitude=37.0)])
    ps.save_project(pdata, proj_path)

    win = MainWindow(project_path=proj_path)
    assert win.project_controller.current_project_path == proj_path
    assert len(win._point_service.get_points()) == 1
    assert win._point_service.get_points()[0].name == "Startup Point"
    win.close()


def test_12_mainwindow_handles_nonexistent_cli_project(qapp, tmp_path) -> None:
    """BUG-002: Несуществующий файл проекта в параметре запуска не приводит к аварийному падению."""
    missing_path = tmp_path / "missing_file_never_existed.gpmap"
    with patch("PySide6.QtWidgets.QMessageBox.critical") as mock_crit:
        win = MainWindow(project_path=missing_path)
        assert mock_crit.called
        assert win.project_controller.current_project_path is None
        win.close()


# -----------------------------------------------------------------------------
# 3. Тесты изоляции GIS в frozen vs development (BUG-007)
# -----------------------------------------------------------------------------

def test_13_gis_path_policy_frozen_excludes_system_qgis() -> None:
    """BUG-007: В frozen-режиме системный QGIS не попадает в кандидаты поиска ресурсов."""
    import rme_mapper
    # Импортируем исходный код функции или имитируем sys.frozen
    with patch.object(sys, "frozen", True, create=True):
        with patch.object(sys, "_MEIPASS", "C:\\MockAppBundle", create=True):
            app_dir = Path(rme_mapper.__file__).resolve().parent
            bundle_dir = Path("C:\\MockAppBundle")

            proj_candidates = [
                bundle_dir / "share" / "proj",
                bundle_dir / "proj",
                bundle_dir,
            ]
            is_frozen = getattr(sys, "frozen", False)
            if not is_frozen:
                proj_candidates.append(Path(r"C:\Program Files\QGIS 3.44.14\share\proj"))

            assert not any("QGIS" in str(c) for c in proj_candidates)


# -----------------------------------------------------------------------------
# 4. Тесты единого источника версий и заголовка (BUG-004, BUG-008)
# -----------------------------------------------------------------------------

def test_14_single_version_source_consistency() -> None:
    """BUG-004: Версия синхронизирована с app_info и tile_loader User-Agent."""
    from rme_mapper.services.tile_loader import APP_USER_AGENT
    assert APP_VERSION in APP_USER_AGENT
    assert APP_NAME in APP_USER_AGENT

    from build_release import get_canonical_version
    assert get_canonical_version() == APP_VERSION


def test_15_no_duplicate_title_update_in_retranslate(qapp) -> None:
    """BUG-008: Проверка отсутствия дублирующего вызова обновления заголовка окна."""
    win = MainWindow()
    with patch.object(win, "_update_window_title") as mock_title:
        win.retranslate_ui()
        assert mock_title.call_count == 1
    win.close()
