"""Smoke-тесты для Этапа 1 RME-Mapper."""

import os
from pathlib import Path
import pytest


def test_required_libraries_imported():
    """Проверка доступности всех ключевых библиотек проекта."""
    import PySide6
    import pyproj
    import geopandas
    import shapely
    import pandas
    import openpyxl

    assert PySide6.__version__ is not None
    assert pyproj.__version__ is not None
    assert geopandas.__version__ is not None
    assert shapely.__version__ is not None
    assert pandas.__version__ is not None
    assert openpyxl.__version__ is not None


def test_internal_modules_imported():
    """Проверка доступности всех внутренних модулей пакета rme_mapper."""
    import rme_mapper
    import rme_mapper.coordinates
    import rme_mapper.exporters
    import rme_mapper.importers
    import rme_mapper.maps
    import rme_mapper.models
    import rme_mapper.points
    import rme_mapper.services
    import rme_mapper.ui
    from rme_mapper.ui.main_window import MainWindow

    assert rme_mapper.__version__ == rme_mapper.app_info.APP_VERSION
    assert MainWindow is not None


@pytest.fixture(scope="session")
def qapp():
    """Фикстура для инициализации QApplication в headless-режиме."""
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    yield app


def test_main_window_creation(qapp):
    """Проверка успешного создания и свойств главного окна."""
    from rme_mapper.ui.main_window import MainWindow

    window = MainWindow()
    assert window is not None
    assert "GeoPoint Mapper" in window.windowTitle()
    assert 0 < window.width() <= 1400
    assert 0 < window.height() <= 850


def test_main_window_menu_structure(qapp):
    """Проверка структуры верхнего меню: Файл, Карта, Координаты, Импорт, Экспорт, Настройки."""
    from rme_mapper.ui.main_window import MainWindow

    window = MainWindow()
    menu_bar = window.menuBar()
    actions = menu_bar.actions()
    menu_titles = [action.text() for action in actions]

    expected_menus = ["Файл", "Карта", "Координаты", "Импорт", "Экспорт", "Настройки"]
    for expected in expected_menus:
        assert expected in menu_titles, f"Меню '{expected}' не найдено в {menu_titles}"


def test_main_window_panels_and_placeholders(qapp):
    """Проверка наличия трех областей (левая панель, центр, правая панель) и статусбара."""
    from PySide6.QtWidgets import QLabel
    from rme_mapper.services.map_catalog_service import MapCatalogService
    from rme_mapper.ui.main_window import MainWindow

    window = MainWindow()
    prof = MapCatalogService().get_profile("mari_el")
    if prof:
        window.load_map(prof)

    # Левая панель: Точки
    assert hasattr(window, "left_panel")
    assert hasattr(window, "points_placeholder")
    point_labels = [lbl.text() for lbl in window.points_panel.findChildren(QLabel)]
    assert "Точки" in point_labels
    assert window.points_panel.parent() is window.workspace_splitter

    # Центральная панель: Карта Республики Марий Эл
    assert hasattr(window, "center_panel")
    assert hasattr(window, "map_placeholder")
    center_labels = [lbl.text() for lbl in window.center_panel.findChildren(QLabel)]
    assert any("Республика Марий Эл" in lbl for lbl in center_labels)

    # Правая панель: Свойства
    assert hasattr(window, "right_panel")
    assert hasattr(window, "properties_placeholder")
    right_labels = [lbl.text() for lbl in window.right_panel.findChildren(QLabel)]
    assert "Свойства" in right_labels

    # Строка состояния: Готово или статус загрузки карты
    status_bar = window.statusBar()
    assert status_bar is not None
    assert status_bar.currentMessage() == "Готово" or "Карта" in status_bar.currentMessage()



def test_mari_gpkg_intact():
    """Проверка сохранности эталонного файла mari.gpkg."""
    gpkg_path = Path(__file__).resolve().parent.parent / "maps" / "test_map" / "prepared" / "mari.gpkg"
    assert gpkg_path.exists(), f"Файл {gpkg_path} не существует!"
    assert gpkg_path.stat().st_size > 10_000_000, "Размер mari.gpkg меньше ожидаемого!"
