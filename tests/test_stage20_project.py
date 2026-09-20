"""Тесты сохранения и загрузки проектов с онлайн-картами (Этап 20: Tests 61-70)."""

import json
from pathlib import Path
from unittest.mock import patch
import pytest

from rme_mapper.models.map_point import MapPoint
from rme_mapper.models.map_profile import MapProfile
from rme_mapper.models.object_group import ObjectGroup
from rme_mapper.models.online_provider import MapType, OnlineTileProvider, ProviderRegistry
from rme_mapper.models.project_data import ProjectData, ProjectMapData, ProjectPointData
from rme_mapper.services.app_settings_service import AppSettingsService
from rme_mapper.services.project_service import ProjectService
from rme_mapper.ui.main_window import MainWindow


@pytest.fixture
def clean_project_env(tmp_path: Path):
    proj_dir = tmp_path / "projects"
    proj_dir.mkdir(parents=True, exist_ok=True)
    return proj_dir


@pytest.fixture(autouse=True)
def clean_recovery_snapshot():
    ProjectService.clear_recovery_snapshot()
    yield
    ProjectService.clear_recovery_snapshot()


def test_61_project_data_serialization_with_online_map(tmp_path: Path):
    """61. Сериализация и десериализация ProjectData с онлайн-подложкой."""
    proj_service = ProjectService()
    profile = MapProfile(
        id="online_osm_profile",
        name="OpenStreetMap Standard",
        source_type="online_xyz",
        source_path="",
        crs="EPSG:3857",
        provider_id="osm_standard",
        map_type="standard",
    )

    pt = MapPoint(id="p1", name="Точка 1", latitude=55.75, longitude=37.61)
    data = proj_service.build_project_data(
        map_path=None,
        layers=[],
        points=[pt],
        groups=[],
        map_profile=profile,
    )

    assert data.map.source_type == "online_xyz"
    assert data.map.provider_id == "osm_standard"
    assert data.map.map_type == "standard"
    assert data.map.relative_path == ""

    # Сохраняем в файл
    save_file = tmp_path / "test_online.gpmap"
    proj_service.save_project(data, save_file)

    # Загружаем обратно
    loaded = proj_service.load_project(save_file)
    assert loaded.map.source_type == "online_xyz"
    assert loaded.map.provider_id == "osm_standard"
    assert loaded.map.map_type == "standard"
    assert len(loaded.points) == 1
    assert loaded.points[0].id == "p1"


def test_62_project_never_serializes_api_keys(tmp_path: Path):
    """62. Безопасность: API-ключи и токены НИКОГДА не сохраняются в *.gpmap."""
    secret_key = "pk.eyJ1_SECRET_TOKEN_DO_NOT_LEAK_9876543210"
    settings = AppSettingsService()
    settings.set_provider_api_key("mapbox_satellite", secret_key)

    proj_service = ProjectService()
    profile = MapProfile(
        id="online_mapbox_sat",
        name="Mapbox Satellite",
        source_type="online_xyz",
        source_path="",
        crs="EPSG:3857",
        provider_id="mapbox_satellite",
        map_type="satellite",
    )

    pt = MapPoint(id="p1", name="Точка с секретом", latitude=55.0, longitude=37.0)
    data = proj_service.build_project_data(
        map_path=None,
        layers=[],
        points=[pt],
        groups=[],
        map_profile=profile,
    )

    save_file = tmp_path / "secure_satellite.gpmap"
    proj_service.save_project(data, save_file)

    # Сканируем весь сохраненный файл как сырой текст
    content = save_file.read_text(encoding="utf-8")
    assert secret_key not in content
    assert "SECRET_TOKEN" not in content
    assert "api_key" not in content.lower() or '"api_key": null' in content.lower()
    assert "access_token" not in content.lower()


def test_63_project_load_without_file_on_disk(tmp_path: Path):
    """63. Загрузка проекта с online_xyz не требует локального файла карты на диске."""
    proj_service = ProjectService()
    data = ProjectData(
        format="GeoPoint Mapper Project",
        version=1,
        map=ProjectMapData(
            map_id="online_osm",
            relative_path="",
            name="OSM Map",
            source_type="online_xyz",
            crs="EPSG:3857",
            provider_id="osm_standard",
            map_type="standard",
        ),
        layers={},
        points=[],
        groups=[],
    )
    save_file = tmp_path / "pure_online.gpmap"
    proj_service.save_project(data, save_file)

    # Чтение не должно вызывать ошибок
    loaded = proj_service.load_project(save_file)
    assert loaded.map.source_type == "online_xyz"
    assert loaded.map.provider_id == "osm_standard"


def test_64_project_load_restores_online_tile_manager(qapp, tmp_path: Path):
    """64. Загрузка проекта в MainWindow корректно настраивает OnlineTileManager."""
    window = MainWindow()
    window.show()

    proj_service = ProjectService()
    data = ProjectData(
        format="GeoPoint Mapper Project",
        version=1,
        map=ProjectMapData(
            map_id="online_osm_test",
            relative_path="",
            name="OSM Map",
            source_type="online_xyz",
            crs="EPSG:3857",
            provider_id="osm_standard",
            map_type="standard",
        ),
        layers={},
        points=[ProjectPointData(id="pt_test", name="Test Pt", latitude=56.0, longitude=47.0)],
        groups=[],
    )
    save_file = tmp_path / "test_load_canvas.gpmap"
    proj_service.save_project(data, save_file)

    # Открываем проект через контроллер проектов
    window.project_controller.open_project_from_path(save_file)

    manager = window.map_canvas.online_tile_manager()
    assert manager.is_active is True
    assert manager.provider is not None
    assert manager.provider.id == "osm_standard"
    assert window.map_canvas.attribution_overlay is not None
    assert "OpenStreetMap" in window.map_canvas.attribution_overlay.text()

    # Проверяем наличие точки на холсте
    assert "pt_test" in window.map_canvas._user_point_items
    window.close()


def test_65_project_load_restores_satellite_provider(qapp, tmp_path: Path):
    """65. Загрузка проекта восстанавливает спутникового провайдера (Mapbox Satellite)."""
    settings = AppSettingsService()
    settings.set_provider_api_key("mapbox_satellite", "pk.test_key_sat")

    window = MainWindow()
    window.show()

    proj_service = ProjectService()
    data = ProjectData(
        format="GeoPoint Mapper Project",
        version=1,
        map=ProjectMapData(
            map_id="online_mapbox_sat",
            relative_path="",
            name="Mapbox Satellite",
            source_type="online_xyz",
            crs="EPSG:3857",
            provider_id="mapbox_satellite",
            map_type="satellite",
        ),
        layers={},
        points=[],
        groups=[],
    )
    save_file = tmp_path / "test_satellite_load.gpmap"
    proj_service.save_project(data, save_file)

    window.project_controller.open_project_from_path(save_file)

    manager = window.map_canvas.online_tile_manager()
    assert manager.is_active is True
    assert manager.provider.id == "mapbox_satellite"
    assert manager.api_key == "pk.test_key_sat"
    window.close()


def test_66_project_load_restores_points_over_online_map(qapp, tmp_path: Path):
    """66. Точки и группы восстанавливаются поверх онлайн-карты с правильным Z-order."""
    window = MainWindow()
    window.show()

    proj_service = ProjectService()
    pt = ProjectPointData(
        id="pt_zorder",
        name="Точка Z",
        latitude=55.75,
        longitude=37.61,
        zone_enabled=True,
        radius_m=300.0,
    )
    data = ProjectData(
        format="GeoPoint Mapper Project",
        version=1,
        map=ProjectMapData(
            map_id="online_osm",
            relative_path="",
            name="OSM",
            source_type="online_xyz",
            crs="EPSG:3857",
            provider_id="osm_standard",
            map_type="standard",
        ),
        layers={},
        points=[pt],
        groups=[],
    )
    save_file = tmp_path / "test_points_zorder.gpmap"
    proj_service.save_project(data, save_file)

    window.project_controller.open_project_from_path(save_file)

    pt_item = window.map_canvas._user_point_items.get("pt_zorder")
    assert pt_item is not None
    assert pt_item.zValue() >= 100.0

    zone_item = window.map_canvas._user_zone_items.get("pt_zorder")
    assert zone_item is not None
    assert zone_item.zValue() == 90.0
    window.close()


def test_67_project_load_restores_coordinate_grid(qapp, tmp_path: Path):
    """67. Состояние координатной сетки сохраняется и отображается поверх онлайн-карты."""
    window = MainWindow()
    window.show()

    proj_service = ProjectService()
    data = ProjectData(
        format="GeoPoint Mapper Project",
        version=1,
        map=ProjectMapData(
            map_id="online_osm",
            relative_path="",
            name="OSM",
            source_type="online_xyz",
            crs="EPSG:3857",
            provider_id="osm_standard",
            map_type="standard",
        ),
        layers={},
        points=[],
        groups=[],
    )
    save_file = tmp_path / "test_grid_restore.gpmap"
    proj_service.save_project(data, save_file)

    window.map_canvas.set_coordinate_grid_visible(True)
    window.project_controller.open_project_from_path(save_file)

    assert window.map_canvas.show_coordinate_grid is True
    window.map_canvas._render_coordinate_grid()
    assert window.map_canvas._grid_item_group is not None
    assert window.map_canvas._grid_item_group.zValue() == 80.0
    window.close()


def test_68_project_dirty_state_on_basemap_switch(qapp, tmp_path: Path):
    """68. Переключение онлайн-подложки при активном проекте выставляет флаг модификации."""
    window = MainWindow()
    window.show()

    proj_service = ProjectService()
    data = ProjectData(
        format="GeoPoint Mapper Project",
        version=1,
        map=ProjectMapData(
            map_id="online_osm",
            relative_path="",
            name="OSM",
            source_type="online_xyz",
            crs="EPSG:3857",
            provider_id="osm_standard",
            map_type="standard",
        ),
        layers={},
        points=[],
        groups=[],
    )
    save_file = tmp_path / "test_dirty.gpmap"
    proj_service.save_project(data, save_file)

    window.project_controller.open_project_from_path(save_file)
    assert window.project_controller.is_modified is False

    # Переключаем подложку на спутник через map_controller
    sat_provider = ProviderRegistry.get_provider("mapbox_satellite")
    window.map_controller.load_online_map(provider=sat_provider, api_key="pk.test_key")

    assert window.project_controller.is_modified is True
    window.project_controller.set_modified(False)
    window.close()


def test_69_project_clean_switch_between_online_projects(qapp, tmp_path: Path):
    """69. Загрузка другого онлайн-проекта чисто заменяет подложку и данные предыдущего."""
    window = MainWindow()
    window.show()

    proj_service = ProjectService()

    # Проект 1: OSM
    p1_data = ProjectData(
        format="GeoPoint Mapper Project",
        version=1,
        map=ProjectMapData(
            map_id="online_osm",
            relative_path="",
            name="OSM",
            source_type="online_xyz",
            crs="EPSG:3857",
            provider_id="osm_standard",
            map_type="standard",
        ),
        layers={},
        points=[ProjectPointData(id="pt_one", name="Point 1", latitude=55.0, longitude=37.0)],
        groups=[],
    )
    p1_file = tmp_path / "p1.gpmap"
    proj_service.save_project(p1_data, p1_file)

    # Проект 2: Mapbox Hybrid
    settings = AppSettingsService()
    settings.set_provider_api_key("mapbox_hybrid", "pk.test_hybrid_key")
    p2_data = ProjectData(
        format="GeoPoint Mapper Project",
        version=1,
        map=ProjectMapData(
            map_id="online_mapbox_hybrid",
            relative_path="",
            name="Mapbox Hybrid",
            source_type="online_xyz",
            crs="EPSG:3857",
            provider_id="mapbox_hybrid",
            map_type="hybrid",
        ),
        layers={},
        points=[ProjectPointData(id="pt_two", name="Point 2", latitude=56.0, longitude=48.0)],
        groups=[],
    )
    p2_file = tmp_path / "p2.gpmap"
    proj_service.save_project(p2_data, p2_file)

    # Открываем Проект 1
    window.project_controller.open_project_from_path(p1_file)
    assert "pt_one" in window.map_canvas._user_point_items
    assert window.map_canvas.online_tile_manager().provider.id == "osm_standard"

    # Открываем Проект 2
    window.project_controller.open_project_from_path(p2_file)
    assert "pt_one" not in window.map_canvas._user_point_items
    assert "pt_two" in window.map_canvas._user_point_items
    assert window.map_canvas.online_tile_manager().provider.id == "mapbox_hybrid"
    window.close()


def test_70_backward_compatibility_load_old_project(tmp_path: Path):
    """70. Обратная совместимость: проекты без полей provider_id/map_type читаются штатно."""
    old_json = {
        "format": "GeoPoint Mapper Project",
        "version": 1,
        "map": {
            "id": "mari_el",
            "path": "maps/mari.gpkg",
            "name": "Марий Эл",
            "crs": "EPSG:32638",
            "layers": [],
        },
        "points": [],
        "groups": [],
    }
    old_file = tmp_path / "legacy.gpmap"
    old_file.write_text(json.dumps(old_json), encoding="utf-8")

    proj_service = ProjectService()
    loaded = proj_service.load_project(old_file)
    assert loaded.map.source_type == "geopackage"
    assert loaded.map.provider_id is None
    assert loaded.map.map_type is None
