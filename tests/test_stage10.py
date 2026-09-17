"""Тесты для Этапа 10: пустой старт, загрузка карты, ребрендинг в GeoPoint Mapper,

OpenMapDialog, runtime MapProfile, закрытие карты и формат .gpmap.
"""

import json
from pathlib import Path
import pytest
from shapely.geometry import LineString, Point, Polygon
import geopandas as gpd

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QLabel, QMessageBox

from rme_mapper.maps.map_canvas import MapCanvas
from rme_mapper.maps.map_config import get_project_root
from rme_mapper.models.map_point import MapPoint
from rme_mapper.models.map_profile import MapProfile
from rme_mapper.models.project_data import (
    PRIMARY_PROJECT_FORMAT,
    LEGACY_PROJECT_FORMAT,
    SUPPORTED_PROJECT_FORMATS,
    ProjectData,
    ProjectMapData,
    ProjectPointData,
)
from rme_mapper.services.geodesic_service import GeodesicService
from rme_mapper.services.geopackage_service import GeoPackageService
from rme_mapper.services.map_catalog_service import MapCatalogService
from rme_mapper.services.point_service import PointService
from rme_mapper.services.project_service import (
    PRIMARY_EXTENSION,
    LEGACY_EXTENSION,
    ProjectService,
)
from rme_mapper.ui.main_window import MainWindow
from rme_mapper.ui.open_map_dialog import OpenMapDialog


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


@pytest.fixture
def mari_el_profile():
    catalog = MapCatalogService()
    prof = catalog.get_profile("mari_el")
    assert prof is not None
    return prof


@pytest.fixture
def multi_layer_gpkg(tmp_path):
    """Создание тестового GeoPackage с несколькими слоями без границы."""
    gpkg_path = tmp_path / "research_layers.gpkg"
    gdf_polys = gpd.GeoDataFrame(
        {"name": ["Zone A", "Zone B"], "geometry": [
            Polygon([(30.0, 50.0), (31.0, 50.0), (31.0, 51.0), (30.0, 51.0)]),
            Polygon([(32.0, 50.0), (33.0, 50.0), (33.0, 51.0), (32.0, 51.0)]),
        ]},
        crs="EPSG:4326",
    )
    gdf_lines = gpd.GeoDataFrame(
        {"name": ["Track 1"], "geometry": [
            LineString([(30.5, 50.5), (32.5, 50.5)]),
        ]},
        crs="EPSG:4326",
    )
    gdf_points = gpd.GeoDataFrame(
        {"name": ["Station 1"], "geometry": [
            Point(31.5, 50.5),
        ]},
        crs="EPSG:4326",
    )
    gdf_polys.to_file(gpkg_path, layer="study_areas", driver="GPKG")
    gdf_lines.to_file(gpkg_path, layer="survey_lines", driver="GPKG")
    gdf_points.to_file(gpkg_path, layer="survey_stations", driver="GPKG")
    return gpkg_path


# -----------------------------------------------------------------------------
# 1. Startup active_map is None
# -----------------------------------------------------------------------------
def test_01_startup_active_map_is_none(qapp):
    """1. При обычном запуске MainWindow активная карта отсутствует (None)."""
    window = MainWindow()
    assert window._active_profile is None
    assert window._map_path is None


# -----------------------------------------------------------------------------
# 2. Startup MapCanvas empty
# -----------------------------------------------------------------------------
def test_02_startup_map_canvas_empty(qapp):
    """2. При запуске MapCanvas пуст и отображает экран пустого состояния."""
    window = MainWindow()
    assert len(window.map_canvas._layer_items) == 0
    assert len(window.map_canvas._user_point_items) == 0
    assert not window.map_canvas.empty_overlay.isHidden()
    window.show()
    assert window.map_canvas.empty_overlay.isVisible()
    assert not window.map_canvas.btn_fit.isVisible()
    window.close()


# -----------------------------------------------------------------------------
# 3. Startup status = Карта не загружена
# -----------------------------------------------------------------------------
def test_03_startup_status_is_map_not_loaded(qapp):
    """3. При запуске статусная строка отображает 'Карта не загружена'."""
    window = MainWindow()
    msg = window.statusBar().currentMessage()
    assert msg == "Карта не загружена"


# -----------------------------------------------------------------------------
# 4. Startup point add disabled
# -----------------------------------------------------------------------------
def test_04_startup_point_add_disabled(qapp):
    """4. В пустом состоянии кнопка добавления точки отключена."""
    window = MainWindow()
    assert not window.btn_add_point.isEnabled()
    assert not window.btn_edit_point.isEnabled()
    assert not window.btn_delete_point.isEnabled()


# -----------------------------------------------------------------------------
# 5. New Project возвращает empty map
# -----------------------------------------------------------------------------
def test_05_new_project_returns_empty_map(qapp, mari_el_profile):
    """5. Файл -> Новый проект переводит приложение в чистое состояние без карты."""
    window = MainWindow(map_profile=mari_el_profile)
    assert window._active_profile is not None

    res = window.new_project()
    assert res is True
    assert window._active_profile is None
    assert window._map_path is None
    assert len(window.loaded_layers) == 0
    assert len(window.layer_checkboxes) == 0
    assert window.statusBar().currentMessage() == "Карта не загружена"
    assert not window.btn_add_point.isEnabled()


# -----------------------------------------------------------------------------
# 6. mari_el не загружается автоматически
# -----------------------------------------------------------------------------
def test_06_mari_el_not_loaded_automatically(qapp):
    """6. Профиль mari_el больше не загружается автоматически на startup."""
    window = MainWindow()
    assert window._active_profile is None
    labels = [lbl.text() for lbl in window.findChildren(QLabel)]
    assert not any("Республика Марий Эл" in lbl for lbl in labels)


# -----------------------------------------------------------------------------
# 7. MapCatalog продолжает находить mari_el
# -----------------------------------------------------------------------------
def test_07_map_catalog_continues_to_find_mari_el():
    """7. MapCatalogService сохраняет обнаружение профиля mari_el."""
    catalog = MapCatalogService()
    prof = catalog.get_profile("mari_el")
    assert prof is not None
    assert prof.id == "mari_el"
    assert "Марий Эл" in prof.name


# -----------------------------------------------------------------------------
# 8. Можно явно открыть mari_el profile
# -----------------------------------------------------------------------------
def test_08_can_explicitly_open_mari_el_profile(qapp, mari_el_profile):
    """8. Профиль mari_el можно явно загрузить через open_map."""
    window = MainWindow()
    window.open_map(mari_el_profile)
    assert window._active_profile is not None
    assert window._active_profile.id == "mari_el"
    assert len(window.loaded_layers) == 2
    assert window.btn_add_point.isEnabled()
    assert "Карта:" in window.statusBar().currentMessage()


# -----------------------------------------------------------------------------
# 9. Открытие GeoPackage создает runtime MapProfile
# -----------------------------------------------------------------------------
def test_09_open_geopackage_creates_runtime_profile(qapp, multi_layer_gpkg):
    """9. Прямое открытие файла через OpenMapDialog создает runtime MapProfile."""
    dlg = OpenMapDialog(initial_file_path=multi_layer_gpkg)
    dlg._on_accept_clicked()
    prof = dlg.get_map_profile()
    assert prof is not None
    assert prof.id.startswith("runtime_")
    assert prof.name == multi_layer_gpkg.stem
    assert prof.source_type == "geopackage"


# -----------------------------------------------------------------------------
# 10. Runtime MapProfile имеет правильный CRS
# -----------------------------------------------------------------------------
def test_10_runtime_map_profile_has_correct_crs(qapp, multi_layer_gpkg):
    """10. Runtime-профиль корректно извлекает CRS из GeoPackage."""
    dlg = OpenMapDialog(initial_file_path=multi_layer_gpkg)
    dlg._on_accept_clicked()
    prof = dlg.get_map_profile()
    assert prof.crs is not None
    assert "4326" in prof.crs or "CRS84" in prof.crs or "WGS" in prof.crs


# -----------------------------------------------------------------------------
# 11. Runtime profile получает layers
# -----------------------------------------------------------------------------
def test_11_runtime_profile_receives_layers(qapp, multi_layer_gpkg):
    """11. Runtime-профиль получает список выбранных слоев с настройками."""
    dlg = OpenMapDialog(initial_file_path=multi_layer_gpkg)
    dlg._on_accept_clicked()
    prof = dlg.get_map_profile()
    assert len(prof.layers) == 3
    layer_names = [l["name"] for l in prof.layers]
    assert "study_areas" in layer_names
    assert "survey_lines" in layer_names
    assert "survey_stations" in layer_names


# -----------------------------------------------------------------------------
# 12. GeoPackage без boundary открывается
# -----------------------------------------------------------------------------
def test_12_geopackage_without_boundary_opens(qapp, multi_layer_gpkg):
    """12. GeoPackage без назначенной границы открывается и отображается."""
    dlg = OpenMapDialog(initial_file_path=multi_layer_gpkg)
    # Явно сбрасываем границу на None
    dlg.boundary_combo.setCurrentIndex(0)
    dlg._on_accept_clicked()
    prof = dlg.get_map_profile()
    assert prof.boundary_layer is None

    window = MainWindow()
    window.load_map(prof)
    assert window._active_profile is not None
    assert window._boundary_geometry is None
    assert len(window.loaded_layers) == 3
    assert window.btn_add_point.isEnabled()


# -----------------------------------------------------------------------------
# 13. GeoPackage с несколькими слоями поддерживается
# -----------------------------------------------------------------------------
def test_13_geopackage_with_multiple_layers_supported(qapp, multi_layer_gpkg):
    """13. Поддерживается отображение нескольких слоев произвольных типов."""
    window = MainWindow()
    dlg = OpenMapDialog(initial_file_path=multi_layer_gpkg)
    dlg._on_accept_clicked()
    prof = dlg.get_map_profile()
    window.load_map(prof)

    assert len(window.layer_checkboxes) == 3
    assert "study_areas" in [chk.text() for chk in window.layer_checkboxes.values()]
    assert "survey_lines" in [chk.text() for chk in window.layer_checkboxes.values()]
    assert "survey_stations" in [chk.text() for chk in window.layer_checkboxes.values()]


# -----------------------------------------------------------------------------
# 14. Закрытие карты возвращает empty state
# -----------------------------------------------------------------------------
def test_14_close_map_returns_empty_state(qapp, mari_el_profile):
    """14. Карта -> Закрыть карту выгружает карту и возвращает оверлей."""
    window = MainWindow(map_profile=mari_el_profile)
    assert window._active_profile is not None
    window.show()

    res = window.close_map(prompt=False)
    assert res is True
    assert window._active_profile is None
    assert len(window.loaded_layers) == 0
    assert window.statusBar().currentMessage() == "Карта не загружена"
    assert not window.btn_add_point.isEnabled()
    assert not window.map_canvas.empty_overlay.isHidden()
    assert window.map_canvas.empty_overlay.isVisible()
    window.close()


# -----------------------------------------------------------------------------
# 15. После загрузки point add становится enabled
# -----------------------------------------------------------------------------
def test_15_point_add_becomes_enabled_after_map_loaded(qapp, multi_layer_gpkg):
    """15. После открытия карты кнопка добавления точки становится активной."""
    window = MainWindow()
    assert not window.btn_add_point.isEnabled()

    dlg = OpenMapDialog(initial_file_path=multi_layer_gpkg)
    dlg._on_accept_clicked()
    window.load_map(dlg.get_map_profile())
    assert window.btn_add_point.isEnabled()


# -----------------------------------------------------------------------------
# 16. DD работает после ручной загрузки карты
# -----------------------------------------------------------------------------
def test_16_dd_works_after_manual_map_load(qapp, mari_el_profile):
    """16. Добавление точки в формате DD работает после ручного открытия карты."""
    window = MainWindow()
    window.load_map(mari_el_profile)

    pt = window._point_service.add_point(
        name="DD Точка",
        latitude=56.634,
        longitude=47.900,
        symbol="circle",
        size=14.0,
        red=200, green=50, blue=50,
    )
    window.map_canvas.add_user_point(pt)
    assert window.map_canvas.has_user_point(pt.id)


# -----------------------------------------------------------------------------
# 17. DMS работает после ручной загрузки карты
# -----------------------------------------------------------------------------
def test_17_dms_works_after_manual_map_load(qapp, mari_el_profile):
    """17. Добавление точки DMS работает после ручной загрузки карты."""
    window = MainWindow()
    window.load_map(mari_el_profile)

    from rme_mapper.coordinates.validator import CoordinateValidator
    lat, lon = CoordinateValidator.validate_dms_pair(
        ("56", "38", "12", "N"),
        ("47", "53", "45", "E"),
    )
    pt = window._point_service.add_point(
        name="DMS Точка",
        latitude=lat,
        longitude=lon,
        symbol="triangle",
    )
    window.map_canvas.add_user_point(pt)
    assert window.map_canvas.has_user_point(pt.id)


# -----------------------------------------------------------------------------
# 18. Zones работают после ручной загрузки
# -----------------------------------------------------------------------------
def test_18_zones_work_after_manual_map_load(qapp, mari_el_profile):
    """18. Геодезические зоны отображаются после ручной загрузки карты."""
    window = MainWindow()
    window.load_map(mari_el_profile)

    pt = window._point_service.add_point(
        name="Точка с зоной",
        latitude=56.634,
        longitude=47.900,
        zone_enabled=True,
        radius_m=3500.0,
    )
    window.map_canvas.add_user_point(pt)
    assert window.map_canvas.has_point_zone(pt.id)


# -----------------------------------------------------------------------------
# 19. Save Project сохраняет runtime map
# -----------------------------------------------------------------------------
def test_19_save_project_saves_runtime_map(qapp, multi_layer_gpkg, tmp_path):
    """19. Сохранение проекта корректно записывает метаданные runtime-карты."""
    window = MainWindow()
    dlg = OpenMapDialog(initial_file_path=multi_layer_gpkg)
    dlg._on_accept_clicked()
    window.load_map(dlg.get_map_profile())

    pt = window._point_service.add_point(name="Test Point", latitude=50.5, longitude=31.0)
    out_proj = tmp_path / "runtime_project.gpmap"
    window.save_project_as(out_proj)

    assert out_proj.exists()
    with open(out_proj, "r", encoding="utf-8") as f:
        data = json.load(f)

    assert data["format"] == PRIMARY_PROJECT_FORMAT
    assert data["map"]["source_type"] == "geopackage"
    assert len(data["map"]["layers"]) == 3
    assert len(data["points"]) == 1


# -----------------------------------------------------------------------------
# 20. Open Project восстанавливает runtime map
# -----------------------------------------------------------------------------
def test_20_open_project_restores_runtime_map(qapp, multi_layer_gpkg, tmp_path):
    """20. Открытие проекта с runtime-картой восстанавливает слои и точки."""
    window1 = MainWindow()
    dlg = OpenMapDialog(initial_file_path=multi_layer_gpkg)
    dlg._on_accept_clicked()
    window1.load_map(dlg.get_map_profile())
    pt = window1._point_service.add_point(name="Persisted Point", latitude=50.5, longitude=31.0)
    out_proj = tmp_path / "restore_test.gpmap"
    window1.save_project_as(out_proj)

    # Открываем в новом окне
    window2 = MainWindow()
    assert window2._active_profile is None
    window2.open_project(out_proj)

    assert window2._active_profile is not None
    assert len(window2.loaded_layers) == 3
    assert len(window2._point_service) == 1
    assert window2.points_table.rowCount() == 1


# -----------------------------------------------------------------------------
# 21. Missing external map обрабатывается без crash
# -----------------------------------------------------------------------------
def test_21_missing_external_map_handled_without_crash(qapp, tmp_path, monkeypatch):
    """21. Если файл карты отсутствует, окно не падает и позволяет открыть без карты."""
    fake_map_proj = tmp_path / "missing_map.gpmap"
    project_data = ProjectData(
        format=PRIMARY_PROJECT_FORMAT,
        version=1,
        map=ProjectMapData(
            map_id="runtime_nonexistent",
            relative_path="C:/non_existent_folder/missing.gpkg",
            name="Missing Map",
        ),
        points=[
            ProjectPointData(
                id="p1", name="Orphan Point", latitude=56.0, longitude=47.0
            )
        ],
    )
    ProjectService.save_project(project_data, fake_map_proj)

    # Имитируем нажатие "Открыть проект без карты"
    def mock_exec(self):
        # Находим кнопку btn_no_map среди добавленных
        for btn in self.buttons():
            if "без карты" in btn.text().lower():
                self.clicked_button = btn
                break
        return 0

    monkeypatch.setattr(QMessageBox, "exec", mock_exec)
    monkeypatch.setattr(QMessageBox, "clickedButton", lambda self: getattr(self, "clicked_button", None))

    window = MainWindow()
    res = window.open_project(fake_map_proj)
    assert res is True
    assert window._active_profile is None
    assert len(window._point_service) == 1
    assert window.points_table.rowCount() == 1


# -----------------------------------------------------------------------------
# 22. Новый format = GeoPoint Mapper Project
# -----------------------------------------------------------------------------
def test_22_new_project_format_is_geopoint_mapper():
    """22. Новые проекты используют format='GeoPoint Mapper Project'."""
    proj = ProjectData()
    assert proj.format == "GeoPoint Mapper Project"
    data = proj.to_dict()
    assert data["format"] == "GeoPoint Mapper Project"


# -----------------------------------------------------------------------------
# 23. Legacy RME-Mapper Project открывается
# -----------------------------------------------------------------------------
def test_23_legacy_rme_mapper_project_opens(tmp_path):
    """23. Проекты формата 'RME-Mapper Project' v1 открываются сервисом."""
    legacy_file = tmp_path / "legacy.rmeproject"
    raw_json = {
        "format": "RME-Mapper Project",
        "version": 1,
        "map": {
            "map_id": "mari_el",
            "relative_path": "maps/test_map/prepared/mari.gpkg",
        },
        "layers": {"boundary": True, "roads": True},
        "points": [
            {
                "id": "leg-1",
                "name": "Legacy Pt",
                "latitude": 56.6344,
                "longitude": 47.8999,
            }
        ],
    }
    with open(legacy_file, "w", encoding="utf-8") as f:
        json.dump(raw_json, f)

    proj = ProjectService.load_project(legacy_file)
    assert proj.format == "RME-Mapper Project"
    assert len(proj.points) == 1
    assert proj.points[0].name == "Legacy Pt"


# -----------------------------------------------------------------------------
# 24. .gpmap сохраняется
# -----------------------------------------------------------------------------
def test_24_gpmap_extension_saved(tmp_path):
    """24. ProjectService сохраняет расширение .gpmap по умолчанию."""
    proj = ProjectData()
    out = ProjectService.save_project(proj, tmp_path / "test_project")
    assert out.suffix == ".gpmap"
    assert out.is_file()


# -----------------------------------------------------------------------------
# 25. .rmeproject продолжает открываться
# -----------------------------------------------------------------------------
def test_25_rmeproject_continues_to_open(tmp_path):
    """25. Файлы с расширением .rmeproject успешно загружаются."""
    proj = ProjectData(format="RME-Mapper Project")
    out = ProjectService.save_project(proj, tmp_path / "project.rmeproject")
    assert out.suffix == ".rmeproject"

    loaded = ProjectService.load_project(out)
    assert loaded is not None


# -----------------------------------------------------------------------------
# 26. Заголовок содержит GeoPoint Mapper
# -----------------------------------------------------------------------------
def test_26_window_title_contains_geopoint_mapper(qapp):
    """26. Заголовок окна приложения всегда начинается с 'GeoPoint Mapper'."""
    window = MainWindow()
    assert window.windowTitle().startswith("GeoPoint Mapper")
    assert "GeoPoint Mapper — Без имени" in window.windowTitle()


# -----------------------------------------------------------------------------
# 27. UI не содержит обязательного Республика Марий Эл
# -----------------------------------------------------------------------------
def test_27_ui_does_not_contain_mandatory_mari_el(qapp):
    """27. При обычном старте интерфейс не содержит принудительной надписи 'Марий Эл'."""
    window = MainWindow()
    labels = [lbl.text() for lbl in window.findChildren(QLabel)]
    assert not any("Марий Эл" in lbl for lbl in labels)
    assert window.map_title_label.text() == "Карта не загружена"


# -----------------------------------------------------------------------------
# 28. Existing mari_el regression tests pass
# -----------------------------------------------------------------------------
def test_28_existing_mari_el_regression_tests_pass(qapp, mari_el_profile):
    """28. Регрессионная проверка: профиль mari_el полноценно работает при явном вызове."""
    window = MainWindow(map_profile=mari_el_profile)
    assert window._active_profile.id == "mari_el"
    assert len(window.loaded_layers) == 2
    assert window._boundary_geometry is not None

    # Проверяем геодезический расчет зоны в WGS84
    circle = GeodesicService.create_geodesic_circle(47.8999, 56.6344, 10000.0)
    assert circle is not None
    assert not circle.is_empty
    assert circle.is_valid
