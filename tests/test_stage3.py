"""Тесты для Этапа 3 проекта RME-Mapper."""

import os
from pathlib import Path
import geopandas as gpd
import pytest
from shapely.geometry import LineString, MultiLineString, Point, Polygon

from rme_mapper.maps.map_canvas import MapCanvas
from rme_mapper.maps.map_config import get_default_geopackage_path
from rme_mapper.models.map_layer import LayerRole, MapLayer
from rme_mapper.services.layer_service import LayerService
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


@pytest.fixture
def layer_service():
    """Инстанс LayerService."""
    return LayerService()


def test_layer_service_discovery(layer_service, default_gpkg):
    """1. Проверка обнаружения поддерживаемых слоев в mari.gpkg."""
    layers = layer_service.discover_layers(default_gpkg)
    assert len(layers) == 2

    roles = [layer.role for layer in layers]
    assert LayerRole.BOUNDARY in roles
    assert LayerRole.ROADS in roles


def test_boundary_role_detected(layer_service, default_gpkg):
    """2. Проверка правильного определения роли границы."""
    layers = layer_service.discover_layers(default_gpkg)
    boundary_layer = next(l for l in layers if l.role == LayerRole.BOUNDARY)

    assert boundary_layer.source_name == "gis_osm_adminareas_a_free"
    assert boundary_layer.display_name == "Граница РМЭ"
    assert boundary_layer.geometry_type == "MultiPolygon"
    assert boundary_layer.feature_count == 1
    assert boundary_layer.z_order == 20


def test_roads_role_detected(layer_service, default_gpkg):
    """3. Проверка правильного определения роли дорог."""
    layers = layer_service.discover_layers(default_gpkg)
    roads_layer = next(l for l in layers if l.role == LayerRole.ROADS)

    assert roads_layer.source_name == "_roads"
    assert roads_layer.display_name == "Дороги"
    assert roads_layer.geometry_type == "MultiLineString"
    assert roads_layer.feature_count == 56967
    assert roads_layer.z_order == 40


def test_unknown_layers_not_autoloaded(layer_service):
    """4. Проверка, что неизвестные слои не загружаются автоматически."""
    role1 = layer_service._determine_layer_role(Path("fake.gpkg"), "some_unknown_layer", "Point")
    assert role1 == LayerRole.UNKNOWN

    role2 = layer_service._determine_layer_role(Path("fake.gpkg"), "pois_and_buildings", "Polygon")
    assert role2 == LayerRole.UNKNOWN


def test_map_canvas_multilinestring(qapp):
    """5. Проверка добавления MultiLineString на MapCanvas."""
    canvas = MapCanvas()
    layer = MapLayer(
        id="test_roads",
        source_name="roads",
        display_name="Тестовые дороги",
        geometry_type="MultiLineString",
        crs="OGC:CRS84",
        role=LayerRole.ROADS,
    )
    mls = MultiLineString([
        [Point(47.0, 56.0), Point(48.0, 56.5)],
        [Point(48.0, 56.5), Point(49.0, 57.0)],
    ])
    gdf = gpd.GeoDataFrame({"geometry": [mls]}, crs="OGC:CRS84")

    canvas.add_layer_item(layer, gdf)

    assert canvas.is_layer_visible("test_roads")
    assert len(canvas.scene().items()) >= 1


def test_map_canvas_linestring(qapp):
    """6. Проверка добавления LineString на MapCanvas."""
    canvas = MapCanvas()
    layer = MapLayer(
        id="test_line",
        source_name="line",
        display_name="Линия",
        geometry_type="LineString",
        crs="OGC:CRS84",
        role=LayerRole.WATERWAYS,
    )
    ls = LineString([(46.5, 56.2), (47.5, 56.8)])
    gdf = gpd.GeoDataFrame({"geometry": [ls]}, crs="OGC:CRS84")

    canvas.add_layer_item(layer, gdf)

    assert canvas.is_layer_visible("test_line")


def test_layer_visibility_toggle(qapp, default_gpkg, layer_service):
    """7. Проверка скрытия слоя через set_layer_visibility."""
    canvas = MapCanvas()
    layers = layer_service.discover_layers(default_gpkg)
    roads_layer = next(l for l in layers if l.role == LayerRole.ROADS)

    # Небольшой срез геометрии для быстрого теста
    gdf = layer_service.load_layer_data(default_gpkg, roads_layer).iloc[:10]
    canvas.add_layer_item(roads_layer, gdf)

    assert canvas.is_layer_visible(roads_layer.id)

    # Скрываем слой
    canvas.set_layer_visibility(roads_layer.id, False)
    assert not canvas.is_layer_visible(roads_layer.id)


def test_layer_visibility_re_enable(qapp, default_gpkg, layer_service):
    """8. Проверка повторного включения видимости слоя."""
    canvas = MapCanvas()
    layers = layer_service.discover_layers(default_gpkg)
    boundary_layer = next(l for l in layers if l.role == LayerRole.BOUNDARY)

    gdf = layer_service.load_layer_data(default_gpkg, boundary_layer)
    canvas.add_layer_item(boundary_layer, gdf)

    canvas.set_layer_visibility(boundary_layer.id, False)
    assert not canvas.is_layer_visible(boundary_layer.id)

    canvas.set_layer_visibility(boundary_layer.id, True)
    assert canvas.is_layer_visible(boundary_layer.id)


def test_fit_to_view_anchored_to_boundary(qapp):
    """9. Проверка, что fit_to_view ориентируется на границу, а не на выступающие дороги."""
    canvas = MapCanvas()

    # Граница 47..48, 56..57
    boundary_poly = Polygon([(47.0, 56.0), (48.0, 56.0), (48.0, 57.0), (47.0, 57.0)])
    boundary_layer = MapLayer(
        id="bnd",
        source_name="bnd",
        display_name="Граница",
        geometry_type="Polygon",
        crs="OGC:CRS84",
        role=LayerRole.BOUNDARY,
    )
    canvas.add_layer_item(boundary_layer, gpd.GeoDataFrame({"geometry": [boundary_poly]}, crs="OGC:CRS84"))

    # Дорога, выступающая далеко за пределы границы: 40..60
    far_road = LineString([(40.0, 50.0), (60.0, 65.0)])
    road_layer = MapLayer(
        id="road",
        source_name="road",
        display_name="Дорога",
        geometry_type="LineString",
        crs="OGC:CRS84",
        role=LayerRole.ROADS,
    )
    canvas.add_layer_item(road_layer, gpd.GeoDataFrame({"geometry": [far_road]}, crs="OGC:CRS84"))

    # Вызываем fit_to_view
    canvas.resize(800, 600)
    canvas.fit_to_view()

    # Охват границы должен оставаться эталонным
    assert canvas._boundary_bounds is not None
    assert canvas._boundary_bounds.width() == pytest.approx(1.0, abs=0.01)


def test_missing_optional_layer_graceful(layer_service, default_gpkg):
    """10. Проверка, что отсутствие optional-слоев не вызывает исключений."""
    layers = layer_service.discover_layers(default_gpkg)
    roles = {l.role for l in layers}

    # В mari.gpkg нет слоев water, waterways, places
    assert LayerRole.WATER not in roles
    assert LayerRole.WATERWAYS not in roles
    assert LayerRole.PLACES not in roles


def test_main_window_layers_panel(qapp, default_gpkg):
    """11. Проверка, что в MainWindow отображаются чекбоксы только реально найденных слоев."""
    window = MainWindow(map_path=default_gpkg)

    assert hasattr(window, "layer_checkboxes")
    assert len(window.layer_checkboxes) == 2

    checkbox_names = [chk.text() for chk in window.layer_checkboxes.values()]
    assert "Граница РМЭ" in checkbox_names
    assert "Дороги" in checkbox_names
    assert "Водоемы" not in checkbox_names
    assert "Населенные пункты" not in checkbox_names

    # Проверка статусной строки
    status = window.statusBar().currentMessage()
    assert "Слоёв: 2" in status


def test_layer_cache(layer_service, default_gpkg):
    """12. Проверка, что кэш сохраняет загруженные данные слоя."""
    layers = layer_service.discover_layers(default_gpkg)
    bnd_layer = next(l for l in layers if l.role == LayerRole.BOUNDARY)

    gdf1 = layer_service.load_layer_data(default_gpkg, bnd_layer)
    gdf2 = layer_service.load_layer_data(default_gpkg, bnd_layer)

    # Должен возвращаться тот же самый объект из кэша
    assert gdf1 is gdf2
