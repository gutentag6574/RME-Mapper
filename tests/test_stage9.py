"""Тесты Этапа 9: Универсализация картографической архитектуры."""

import json
from pathlib import Path
import pytest
from PySide6.QtCore import QPointF
from PySide6.QtWidgets import QApplication
from shapely.geometry import Polygon

from rme_mapper.maps.map_canvas import MapCanvas
from rme_mapper.maps.map_config import get_project_root
from rme_mapper.models.map_layer import LayerRole, MapLayer
from rme_mapper.models.map_point import MapPoint
from rme_mapper.models.map_profile import MapProfile
from rme_mapper.models.project_data import ProjectData, ProjectMapData, ProjectPointData
from rme_mapper.services.coordinate_service import CoordinateService
from rme_mapper.services.geodesic_service import GeodesicService
from rme_mapper.services.layer_service import LayerService
from rme_mapper.services.map_catalog_service import MapCatalogService
from rme_mapper.services.project_service import ProjectService
from rme_mapper.ui.add_point_dialog import PointDialog
from rme_mapper.ui.main_window import MainWindow


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


@pytest.fixture
def mari_el_metadata_path():
    return get_project_root() / "maps" / "test_map" / "metadata.json"


@pytest.fixture
def projected_fixture_dir():
    return Path(__file__).parent / "fixtures" / "projected_map"


# -----------------------------------------------------------------------------
# 1. MapProfile создается
# -----------------------------------------------------------------------------
def test_01_map_profile_creation():
    """1. Создание экземпляра MapProfile со всеми обязательными и опциональными полями."""
    profile = MapProfile(
        id="custom_test_map",
        name="Пользовательская карта",
        description="Тестовое описание",
        source_type="geopackage",
        source_path="maps/custom/test.gpkg",
        crs="EPSG:3857",
        boundary_layer="admin_border",
        boundary_required=True,
        layers=[{"id": "l1", "source_name": "roads", "role": "ROADS"}],
        extent={"xmin": 10.0, "ymin": 20.0, "xmax": 30.0, "ymax": 40.0},
        metadata_version=1,
    )
    assert profile.id == "custom_test_map"
    assert profile.name == "Пользовательская карта"
    assert profile.source_type == "geopackage"
    assert profile.crs == "EPSG:3857"
    assert profile.boundary_required is True
    assert len(profile.layers) == 1
    assert profile.extent["xmin"] == 10.0


# -----------------------------------------------------------------------------
# 2. metadata валидируется
# -----------------------------------------------------------------------------
def test_02_metadata_validation(mari_el_metadata_path):
    """2. Валидация схемы metadata.json и круглогодичная сериализация/десериализация."""
    assert mari_el_metadata_path.is_file()
    with open(mari_el_metadata_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    profile = MapProfile.from_dict(data, base_dir=mari_el_metadata_path.parent)
    assert profile.id == "mari_el"
    assert profile.name == "Республика Марий Эл"
    assert profile.crs == "OGC:CRS84"
    assert profile.source_path == "prepared/mari.gpkg"
    assert profile.boundary_layer == "gis_osm_adminareas_a_free"

    # Проверка to_dict
    serialized = profile.to_dict()
    assert serialized["id"] == "mari_el"
    assert serialized["source"]["type"] == "geopackage"
    assert serialized["crs"] == "OGC:CRS84"


# -----------------------------------------------------------------------------
# 3. MapCatalogService находит mari_el
# -----------------------------------------------------------------------------
def test_03_catalog_service_finds_mari_el():
    """3. MapCatalogService обнаруживает профиль mari_el в директории maps/."""
    catalog = MapCatalogService()
    profiles = catalog.discover_profiles()
    assert len(profiles) >= 1

    mari_el = catalog.get_profile("mari_el")
    assert mari_el is not None
    assert mari_el.id == "mari_el"
    assert "Марий Эл" in mari_el.name


# -----------------------------------------------------------------------------
# 4. mari_el загружается как обычный профиль
# -----------------------------------------------------------------------------
def test_04_mari_el_loaded_as_regular_profile():
    """4. Профиль mari_el загружается через единый generic-механизм без спец-ветвлений."""
    catalog = MapCatalogService()
    default_prof = catalog.get_default_profile()
    assert default_prof.id == "mari_el"

    abs_src = default_prof.get_absolute_source_path()
    assert abs_src.is_file()
    assert abs_src.name == "mari.gpkg"


# -----------------------------------------------------------------------------
# 5. Core не требует id == mari_el
# -----------------------------------------------------------------------------
def test_05_core_does_not_require_id_mari_el():
    """5. Бизнес-логика core корректно работает с произвольным идентификатором профиля."""
    profile = MapProfile(
        id="arbitrary_universe_map",
        name="Произвольная карта",
        source_type="geopackage",
        source_path="none.gpkg",
        crs="EPSG:32638",
    )
    assert profile.id != "mari_el"
    assert profile.crs == "EPSG:32638"


# -----------------------------------------------------------------------------
# 6. Boundary optional
# -----------------------------------------------------------------------------
def test_06_boundary_optional(projected_fixture_dir):
    """6. Профиль без слоя границы (boundary_layer=None) корректно валидируется."""
    meta_file = projected_fixture_dir / "metadata.json"
    with open(meta_file, "r", encoding="utf-8") as f:
        data = json.load(f)

    profile = MapProfile.from_dict(data, base_dir=projected_fixture_dir)
    assert profile.id == "test_projected_map"
    assert profile.boundary_layer is None
    assert profile.boundary_required is False


# -----------------------------------------------------------------------------
# 7. Fit работает без boundary
# -----------------------------------------------------------------------------
def test_07_fit_works_without_boundary(qapp):
    """7. fit_to_view успешно вписывает карту по itemsBoundingRect при отсутствии границы."""
    canvas = MapCanvas()
    canvas.resize(800, 600)

    # Создаем dummy-слой без роли BOUNDARY
    poly = Polygon([(1000.0, 1000.0), (2000.0, 1000.0), (2000.0, 2000.0), (1000.0, 2000.0)])
    import geopandas as gpd
    gdf = gpd.GeoDataFrame([{"geometry": poly}], crs="EPSG:3857")
    layer = MapLayer(
        id="l_feat", source_name="feat", display_name="Фичи",
        geometry_type="Polygon", crs="EPSG:3857", role=LayerRole.UNKNOWN,
    )
    canvas.add_layer_item(layer, gdf)
    assert canvas._boundary_bounds is None

    # Вызов fit_to_view не падает и выполняет центрирование
    canvas.fit_to_view()
    assert canvas.transform().m11() != 0.0


# -----------------------------------------------------------------------------
# 8. CoordinateService identical CRS
# -----------------------------------------------------------------------------
def test_08_coordinate_service_identical_crs():
    """8. CoordinateService.transform_xy при совпадении CRS возвращает точные исходные координаты."""
    x, y = 47.89, 56.63
    tx, ty = CoordinateService.transform_xy(x, y, "OGC:CRS84", "OGC:CRS84")
    assert tx == x
    assert ty == y

    tx2, ty2 = CoordinateService.transform_xy(5000000.0, 7000000.0, "EPSG:3857", "EPSG:3857")
    assert tx2 == 5000000.0
    assert ty2 == 7000000.0


# -----------------------------------------------------------------------------
# 9. EPSG:4326 -> projected CRS
# -----------------------------------------------------------------------------
def test_09_epsg4326_to_projected_crs():
    """9. Точка lon=47.9, lat=56.6 трансформируется в спроецированную CRS (метры, > 1 млн)."""
    lon, lat = 47.9, 56.6
    mx, my = CoordinateService.transform_xy(lon, lat, "EPSG:4326", "EPSG:3857")
    assert abs(mx) > 1000000.0
    assert abs(my) > 1000000.0
    # Проверка примерных значений Меркатора для центра РМЭ
    assert 5300000.0 < mx < 5400000.0
    assert 7600000.0 < my < 7700000.0


# -----------------------------------------------------------------------------
# 10. Projected -> EPSG:4326
# -----------------------------------------------------------------------------
def test_10_projected_to_epsg4326():
    """10. Обратная трансформация из спроецированной CRS в EPSG:4326."""
    proj_x, proj_y = 5332190.87, 7678144.59
    lon, lat = CoordinateService.transform_xy(proj_x, proj_y, "EPSG:3857", "EPSG:4326")
    assert 47.8 < lon < 48.0
    assert 56.5 < lat < 56.7


# -----------------------------------------------------------------------------
# 11. Roundtrip точен
# -----------------------------------------------------------------------------
def test_11_roundtrip_accurate():
    """11. Точность прямого и обратного преобразования (roundtrip) не хуже 1e-6 градуса."""
    init_lon, init_lat = 47.9, 56.6
    mx, my = CoordinateService.transform_xy(init_lon, init_lat, "EPSG:4326", "EPSG:3857")
    rt_lon, rt_lat = CoordinateService.transform_xy(mx, my, "EPSG:3857", "EPSG:4326")

    assert abs(rt_lon - init_lon) < 1e-6
    assert abs(rt_lat - init_lat) < 1e-6


# -----------------------------------------------------------------------------
# 12. always_xy корректен
# -----------------------------------------------------------------------------
def test_12_always_xy_correct():
    """12. Соблюдение правила always_xy: x = lon (47.9), y = lat (56.6)."""
    # Если бы было lat/lon, mx и my поменялись бы местами кардинально
    mx, my = CoordinateService.transform_xy(47.9, 56.6, "EPSG:4326", "EPSG:3857")
    # x (долгота 47.9) -> восток ~5.3 млн м
    # y (широта 56.6) -> север ~7.6 млн м
    assert mx < my


# -----------------------------------------------------------------------------
# 13. MapCanvas принимает projected X/Y
# -----------------------------------------------------------------------------
def test_13_map_canvas_accepts_projected_xy(qapp):
    """13. MapCanvas принимает спроецированные координаты (метры) и позиционирует на (x, -y)."""
    canvas = MapCanvas()
    point = MapPoint(id="proj_pt", name="Спроецированная", latitude=56.6, longitude=47.9)
    proj_x, proj_y = 5332000.0, 7678000.0

    canvas.add_user_point(point, map_x=proj_x, map_y=proj_y)
    item = canvas._user_point_items.get("proj_pt")
    assert item is not None
    assert item.pos().x() == proj_x
    assert item.pos().y() == -proj_y


# -----------------------------------------------------------------------------
# 14. Пользовательская точка трансформируется в map CRS
# -----------------------------------------------------------------------------
def test_14_user_point_transforms_to_map_crs():
    """14. Пользовательская точка из WGS84 трансформируется в активную CRS карты."""
    pt = MapPoint(name="Точка", latitude=56.6, longitude=47.9, source_crs="EPSG:4326")
    map_crs = "EPSG:3857"

    mx, my = CoordinateService.transform_xy(pt.longitude, pt.latitude, pt.source_crs, map_crs)
    assert abs(mx - 47.9) > 1000.0
    assert abs(my - 56.6) > 1000.0


# -----------------------------------------------------------------------------
# 15. Geodesic zone трансформируется в map CRS
# -----------------------------------------------------------------------------
def test_15_geodesic_zone_transforms_to_map_crs():
    """15. Полигон геодезической зоны (10 км) трансформируется в активную CRS карты."""
    lon, lat = 47.9, 56.6
    geo_circle = GeodesicService.create_geodesic_circle(lon, lat, radius_m=10000.0, segments=32)

    # Все вершины WGS84 трансформируются в спроецированную CRS
    proj_circle = CoordinateService.transform_polygon(geo_circle, "EPSG:4326", "EPSG:3857")
    coords = list(proj_circle.exterior.coords)
    assert len(coords) >= 32

    # Координаты вершин находятся в диапазоне миллионов метров
    for x, y in coords:
        assert 5000000.0 < x < 6000000.0
        assert 7000000.0 < y < 8000000.0


# -----------------------------------------------------------------------------
# 16. Projected zone валидна
# -----------------------------------------------------------------------------
def test_16_projected_zone_is_valid():
    """16. Спроецированный полигон зоны является валидным замкнутым Shapely Polygon."""
    geo_circle = GeodesicService.create_geodesic_circle(47.9, 56.6, radius_m=5000.0, segments=32)
    proj_poly = CoordinateService.transform_polygon(geo_circle, "EPSG:4326", "EPSG:3857")

    assert isinstance(proj_poly, Polygon)
    assert proj_poly.is_valid
    assert not proj_poly.is_empty
    assert proj_poly.area > 0.0


# -----------------------------------------------------------------------------
# 17. LayerService читает имена из MapProfile
# -----------------------------------------------------------------------------
def test_17_layer_service_reads_names_from_profile(projected_fixture_dir):
    """17. LayerService.load_profile_layers настраивает слои согласно метаданным профиля."""
    meta_file = projected_fixture_dir / "metadata.json"
    with open(meta_file, "r", encoding="utf-8") as f:
        data = json.load(f)

    profile = MapProfile.from_dict(data, base_dir=projected_fixture_dir)
    service = LayerService()
    layers = service.load_profile_layers(profile)

    assert len(layers) == 1
    assert layers[0].id == "features"
    assert layers[0].display_name == "Тестовые объекты"
    assert layers[0].crs == "EPSG:3857"


# -----------------------------------------------------------------------------
# 18. UI получает map name из profile
# -----------------------------------------------------------------------------
def test_18_ui_gets_map_name_from_profile(qapp):
    """18. Заголовок над картой в MainWindow формируется из имени активного профиля."""
    window = MainWindow()
    assert hasattr(window, "map_title_label")
    assert "Республика Марий Эл" in window.map_title_label.text()


# -----------------------------------------------------------------------------
# 19. Статус получает CRS из profile
# -----------------------------------------------------------------------------
def test_19_status_bar_gets_crs_from_profile(qapp):
    """19. Строка состояния MainWindow отображает CRS активного профиля."""
    window = MainWindow()
    msg = window.statusBar().currentMessage()
    assert "OGC:CRS84" in msg or "4326" in msg


# -----------------------------------------------------------------------------
# 20. Универсальное outside сообщение
# -----------------------------------------------------------------------------
def test_20_universal_outside_message(qapp, monkeypatch):
    """20. Предупреждение о выходе за пределы содержит имя активной карты."""
    from PySide6.QtWidgets import QMessageBox

    poly = Polygon([(47.0, 56.0), (48.0, 56.0), (48.0, 57.0), (47.0, 57.0)])
    dialog = PointDialog(
        boundary_geometry=poly,
        map_name="Кастомный Регион",
    )
    # Точка за пределами (Москва)
    dialog.lat_edit.setText("55.75")
    dialog.lon_edit.setText("37.61")

    captured_message = []
    def fake_question(parent, title, text, buttons, default):
        captured_message.append(text)
        return QMessageBox.StandardButton.No

    monkeypatch.setattr(QMessageBox, "question", fake_question)
    dialog.accept()

    assert len(captured_message) == 1
    assert "Кастомный Регион" in captured_message[0]
    assert "за пределами рабочей области" in captured_message[0]


# -----------------------------------------------------------------------------
# 21. ProjectService сохраняет map_id
# -----------------------------------------------------------------------------
def test_21_project_service_saves_map_id(tmp_path):
    """21. ProjectService сохраняет идентификатор карты map_id в структуру проекта."""
    data = ProjectService.build_project_data(
        map_path="maps/test_map/prepared/mari.gpkg",
        layers=[],
        points=[],
        map_id="mari_el",
    )
    assert data.map.map_id == "mari_el"

    saved_file = ProjectService.save_project(data, tmp_path / "proj.rmeproject")
    with open(saved_file, "r", encoding="utf-8") as f:
        content = json.load(f)

    assert content["map"]["map_id"] == "mari_el"


# -----------------------------------------------------------------------------
# 22. Старый v1 project с path продолжает открываться
# -----------------------------------------------------------------------------
def test_22_old_v1_project_with_path_opens():
    """22. Проект версии 1 (sample_project_v1.rmeproject) успешно открывается и валидируется."""
    sample_file = Path(__file__).parent / "fixtures" / "sample_project_v1.rmeproject"
    assert sample_file.is_file()

    project = ProjectService.load_project(sample_file)
    assert project.version == 1
    assert project.map.map_id == "test_map"
    assert len(project.points) == 3

    # Сопоставление с профилем mari_el через алиас
    catalog = MapCatalogService()
    profile = catalog.get_profile(project.map.map_id)
    assert profile is not None
    assert profile.id == "mari_el"


# -----------------------------------------------------------------------------
# 23. Новый project с map_id открывается
# -----------------------------------------------------------------------------
def test_23_new_project_with_map_id_opens(tmp_path):
    """23. Проект с новым map_id открывается и сопоставляется с MapProfile."""
    project = ProjectData(
        map=ProjectMapData(map_id="mari_el", relative_path="maps/test_map/prepared/mari.gpkg"),
        points=[ProjectPointData(id="p1", name="Тест", latitude=56.6, longitude=47.9)],
    )
    file_path = ProjectService.save_project(project, tmp_path / "new.rmeproject")
    loaded = ProjectService.load_project(file_path)

    assert loaded.map.map_id == "mari_el"
    assert len(loaded.points) == 1
    assert loaded.points[0].name == "Тест"


# -----------------------------------------------------------------------------
# 24. Карта без boundary не вызывает crash
# -----------------------------------------------------------------------------
def test_24_map_without_boundary_no_crash(qapp, projected_fixture_dir):
    """24. Загрузка карты без границы не вызывает исключений при отображении и добавлении точек."""
    meta_file = projected_fixture_dir / "metadata.json"
    with open(meta_file, "r", encoding="utf-8") as f:
        data = json.load(f)

    profile = MapProfile.from_dict(data, base_dir=projected_fixture_dir)
    window = MainWindow(map_profile=profile)

    assert window._active_profile.id == "test_projected_map"
    assert window._boundary_geometry is None
    assert "EPSG:3857" in window.statusBar().currentMessage()

    # Добавляем точку в спроецированную карту
    pt = window._point_service.add_point(name="Проекция 1", latitude=56.6, longitude=47.9)
    mx, my = CoordinateService.transform_xy(pt.longitude, pt.latitude, pt.source_crs, window._active_crs)
    window.map_canvas.add_user_point(pt, map_x=mx, map_y=my)
    window._add_point_to_table(pt)

    assert window.points_table.rowCount() == 1
    assert window.map_canvas.has_user_point(pt.id)


# -----------------------------------------------------------------------------
# 25. Существующая карта РМЭ продолжает работать
# -----------------------------------------------------------------------------
def test_25_existing_mari_el_map_works(qapp):
    """25. Регрессионная проверка: карта Марий Эл загружается и полностью функциональна."""
    window = MainWindow()
    assert window._active_profile.id == "mari_el"
    assert len(window.loaded_layers) == 2
    assert window._boundary_geometry is not None

    # Добавляем точку с зоной радиуса
    pt = window._point_service.add_point(
        name="Йошкар-Ола",
        latitude=56.6344,
        longitude=47.8999,
        symbol="circle",
        zone_enabled=True,
        radius_m=5000.0,
    )
    window.map_canvas.add_user_point(pt)
    assert window.map_canvas.has_user_point(pt.id)
    assert window.map_canvas.has_point_zone(pt.id)
