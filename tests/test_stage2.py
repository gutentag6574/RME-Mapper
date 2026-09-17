"""Тесты для Этапа 2 проекта RME-Mapper."""

import os
from pathlib import Path
import pytest
from shapely.geometry import MultiPolygon, Polygon

from rme_mapper.maps.map_canvas import MapCanvas
from rme_mapper.maps.map_config import get_default_geopackage_path, get_project_root
from rme_mapper.services.geopackage_service import GeoPackageService
from rme_mapper.ui.main_window import MainWindow


@pytest.fixture(scope="session")
def qapp():
    """Фикстура для инициализации QApplication в headless-режиме."""
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    yield app


@pytest.fixture
def default_gpkg():
    """Путь к эталонному файлу GeoPackage."""
    return get_default_geopackage_path()


def test_geopackage_exists(default_gpkg):
    """1. Проверка существования GeoPackage."""
    assert GeoPackageService.exists(default_gpkg)
    assert default_gpkg.is_file()
    assert default_gpkg.stat().st_size > 0


def test_geopackage_layers_list(default_gpkg):
    """2. Проверка успешного чтения списка слоев."""
    layers = GeoPackageService.list_layers(default_gpkg)
    assert len(layers) >= 2
    layer_names = [name for name, _ in layers]
    assert "gis_osm_adminareas_a_free" in layer_names
    assert "_roads" in layer_names


def test_boundary_layer_found(default_gpkg):
    """3. Проверка обнаружения слоя границы Республики Марий Эл."""
    boundary_layer = GeoPackageService.find_boundary_layer(default_gpkg)
    assert boundary_layer is not None
    assert boundary_layer == "gis_osm_adminareas_a_free"


def test_boundary_geometry_type(default_gpkg):
    """4. Проверка типа геометрии слоя границы (Polygon или MultiPolygon)."""
    boundary_layer = GeoPackageService.find_boundary_layer(default_gpkg)
    gdf = GeoPackageService.read_layer(default_gpkg, boundary_layer)

    assert not gdf.empty
    geom_types = set(gdf.geometry.geom_type.unique())
    assert geom_types.issubset({"Polygon", "MultiPolygon"})


def test_boundary_crs(default_gpkg):
    """5. Проверка успешного определения CRS."""
    boundary_layer = GeoPackageService.find_boundary_layer(default_gpkg)
    meta = GeoPackageService.get_layer_metadata(default_gpkg, boundary_layer)

    crs = meta.get("crs")
    assert crs is not None
    crs_str = str(crs)
    assert "CRS84" in crs_str or "WGS 84" in crs_str or "4326" in crs_str


def test_boundary_geodataframe_not_empty(default_gpkg):
    """6. Проверка, что GeoDataFrame не пустой и содержит валидные данные."""
    boundary_layer = GeoPackageService.find_boundary_layer(default_gpkg)
    gdf = GeoPackageService.read_layer(default_gpkg, boundary_layer)

    assert len(gdf) == 1
    feature = gdf.iloc[0]
    assert feature["name"] == "Марий Эл"
    assert feature.geometry is not None
    assert feature.geometry.is_valid
    assert not feature.geometry.is_empty


def test_map_canvas_creation(qapp, default_gpkg):
    """7. Проверка создания MapCanvas и отрисовки геометрии."""
    canvas = MapCanvas()
    assert canvas is not None
    assert canvas.scene() is not None

    boundary_layer = GeoPackageService.find_boundary_layer(default_gpkg)
    gdf = GeoPackageService.read_layer(default_gpkg, boundary_layer)

    canvas.load_geodataframe(gdf)

    # Проверяем наличие элементов на сцене
    items = canvas.scene().items()
    assert len(items) >= 1

    # Проверяем охват сцены (долгота ~45.6..50.2, -широта ~ -57.3..-55.8)
    rect = canvas.scene().sceneRect()
    assert rect.isValid()
    assert 45.0 <= rect.left() <= 46.0
    assert 50.0 <= rect.right() <= 51.0
    # Ось Y инвертирована: -lat
    assert -58.0 <= rect.top() <= -57.0
    assert -56.0 <= rect.bottom() <= -55.0


def test_main_window_has_map_canvas(qapp, default_gpkg):
    """8. Проверка, что MainWindow содержит MapCanvas и отображает корректный статус."""
    window = MainWindow(map_path=default_gpkg)
    assert hasattr(window, "map_canvas")
    assert isinstance(window.map_canvas, MapCanvas)

    # Проверяем строку состояния
    status_text = window.statusBar().currentMessage()
    assert "Карта" in status_text
    assert "CRS84" in status_text or "WGS" in status_text


def test_missing_file_handling(qapp):
    """9. Проверка корректной обработки отсутствующего файла без падения."""
    fake_path = Path("maps/test_map/non_existent.gpkg")

    # Передаем несуществующий путь в MainWindow
    window = MainWindow(map_path=fake_path)
    assert window is not None

    # Окно не падает, на холсте отображается ошибка, статус сообщает об ошибке
    status_text = window.statusBar().currentMessage()
    assert "Ошибка" in status_text
