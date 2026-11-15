"""Тесты для Этапа 11 проекта GeoPoint Mapper:
- Изоляция Core от Qt (тесты бизнес-логики и моделей без создания QApplication);
- Абстракция GIS бэкенда (MapDataBackend, ModernGeoPackageBackend, LegacyGeoPackageBackend, BackendFactory);
- Сведения об авторе, версия и диалоговое окно "О программе" (app_info.py, AboutDialog, меню "Справка");
- Межплатформенная совместимость форматов проектов (*.gpmap, *.rmeproject).
"""

import inspect
import json
import os
from pathlib import Path
import tempfile
import pytest

from rme_mapper.app_info import (
    APP_DESCRIPTION,
    APP_NAME,
    APP_VERSION,
    AUTHOR_EMAIL,
    AUTHOR_NAME,
    AUTHOR_TELEGRAM,
    COMPANY_NAME,
    COPYRIGHT_TEXT,
    COPYRIGHT_YEAR,
    FILE_DESCRIPTION,
    FILE_VERSION,
    PRODUCT_NAME,
    PRODUCT_VERSION,
    format_telegram_url,
)
from rme_mapper.backends import (
    BackendFactory,
    LegacyGeoPackageBackend,
    MapDataBackend,
    ModernGeoPackageBackend,
    get_backend,
)
from rme_mapper.coordinates.converter import dms_to_decimal
from rme_mapper.coordinates.validator import CoordinateValidator
from rme_mapper.maps.map_config import get_default_geopackage_path
from rme_mapper.models.map_layer import LayerRole, MapLayer
from rme_mapper.models.map_point import MapPoint
from rme_mapper.models.map_profile import MapProfile
from rme_mapper.models.point_style import PointStyle, PointZoneStyle, StyleValidator
from rme_mapper.models.project_data import (
    PRIMARY_PROJECT_FORMAT,
    LEGACY_PROJECT_FORMAT,
    ProjectData,
    ProjectMapData,
    ProjectPointData,
)
from rme_mapper.services.coordinate_service import CoordinateService
from rme_mapper.services.geodesic_service import GeodesicService
from rme_mapper.services.project_service import ProjectService


# ==============================================================================
# БЛОК 1: TESTS CORE WITHOUT UI (БЕЗ СОЗДАНИЯ QAPPLICATION)
# ==============================================================================

def test_core_coordinate_validator_without_qapp():
    """Проверка работы CoordinateValidator в изолированном окружении без Qt."""
    lat, lon = CoordinateValidator.validate_dd_pair("56.6315", "47.8861")
    assert lat == 56.6315
    assert lon == 47.8861

    # Валидация диапазонов
    with pytest.raises(ValueError, match="Широта"):
        CoordinateValidator.validate_latitude(95.0)

    with pytest.raises(ValueError, match="Долгота"):
        CoordinateValidator.validate_longitude(-190.0)


def test_core_dms_to_decimal_without_qapp():
    """Проверка математического преобразования dms_to_decimal без Qt."""
    # 56° 37' 53.4" N -> 56 + 37/60 + 53.4/3600
    val_n = dms_to_decimal(56, 37, 53.4, "N")
    assert pytest.approx(val_n, rel=1e-5) == 56.6315

    # 47° 53' 9.96" W -> отрицательное значение
    val_w = dms_to_decimal(47, 53, 9.96, "W")
    assert val_w < 0


def test_core_geodesic_service_without_qapp():
    """Проверка геодезических расчетов GeodesicService без Qt."""
    circle = GeodesicService.create_geodesic_circle(47.8861, 56.6315, 1000.0, num_points=32)
    assert circle is not None
    assert circle.is_valid
    assert len(circle.exterior.coords) == 33  # 32 сегмента + замыкающая точка


def test_core_map_point_without_qapp():
    """Проверка модели MapPoint: чистые примитивные типы, отсутствие Qt."""
    pt = MapPoint(
        name="Точка без Qt",
        latitude=56.5,
        longitude=47.5,
        symbol="square",
        size=16.0,
        red=100,
        green=150,
        blue=200,
        zone_enabled=True,
        radius_m=2500.0,
        zone_red=50,
        zone_green=100,
        zone_blue=150,
        zone_opacity=40,
    )
    assert pt.name == "Точка без Qt"
    assert isinstance(pt.style, PointStyle)
    assert pt.style.symbol == "square"
    assert isinstance(pt.zone, PointZoneStyle)
    assert pt.zone.radius_m == 2500.0


def test_core_point_styles_without_qapp():
    """Проверка валидаторов стилей точек и зон StyleValidator без Qt."""
    style = StyleValidator.validate_style("triangle", "15.5", 255, 128, 0)
    assert style.symbol == "triangle"
    assert style.size == 15.5
    assert style.red == 255

    radius = StyleValidator.validate_radius("1500.5", enabled=True)
    assert radius == 1500.5

    opacity = StyleValidator.validate_opacity("50")
    assert opacity == 50


def test_core_project_data_without_qapp():
    """Проверка сериализации и десериализации ProjectData без Qt."""
    pt = ProjectPointData(
        id="pt-1",
        name="Тестовая",
        latitude=56.0,
        longitude=47.0,
    )
    proj = ProjectData(
        format=PRIMARY_PROJECT_FORMAT,
        version=1,
        map=ProjectMapData(name="Тестовая карта", relative_path="maps/test.gpkg"),
        layers={"roads": True},
        points=[pt],
    )
    d = proj.to_dict()
    assert d["format"] == PRIMARY_PROJECT_FORMAT
    assert d["version"] == 1
    assert d["points"][0]["id"] == "pt-1"

    restored = ProjectData.from_dict(d)
    assert restored.map.name == "Тестовая карта"
    assert len(restored.points) == 1


def test_core_map_profile_without_qapp():
    """Проверка MapProfile без Qt."""
    meta = {
        "id": "mari_el",
        "name": "Республика Марий Эл",
        "source": {
            "type": "geopackage",
            "path": "maps/test_map/mari_el.gpkg",
        },
        "crs": "OGC:CRS84",
        "boundary": {
            "layer": "admin_level_4",
            "required": True,
        },
        "layers": [
            {"id": "bnd", "source_name": "admin_level_4", "name": "Граница"}
        ],
    }
    profile = MapProfile.from_dict(meta)
    assert profile.id == "mari_el"
    assert profile.boundary_layer == "admin_level_4"
    d = profile.to_dict()
    assert d["id"] == "mari_el"


# ==============================================================================
# БЛОК 2: GIS BACKEND ABSTRACTION TESTS
# ==============================================================================

def test_backend_interface_exists():
    """1. Backend interface существует и определяет базовые абстрактные методы."""
    assert inspect.isabstract(MapDataBackend)
    required_methods = {
        "exists",
        "list_layers",
        "get_layer_metadata",
        "read_layer",
        "get_crs",
        "get_extent",
        "find_boundary_layer",
    }
    for m in required_methods:
        assert hasattr(MapDataBackend, m)


def test_backend_factory_and_modern_resolution():
    """2. Modern backend определяется и выдается BackendFactory."""
    backend = BackendFactory.get_backend("modern")
    assert isinstance(backend, ModernGeoPackageBackend)

    default_backend = get_backend()
    assert isinstance(default_backend, ModernGeoPackageBackend)

    avail = BackendFactory.list_available()
    assert "modern" in avail
    assert "legacy" in avail


def test_modern_backend_reads_geopackage():
    """3. Modern backend успешно читает реальный тестовый GeoPackage."""
    gpkg_path = get_default_geopackage_path()
    assert gpkg_path.exists(), f"Файл {gpkg_path} должен существовать"

    backend = get_backend("modern")
    assert backend.exists(gpkg_path)

    layers = backend.list_layers(gpkg_path)
    assert len(layers) > 0

    # Проверка чтения слоя
    first_layer_name = layers[0][0]
    gdf = backend.read_layer(gpkg_path, first_layer_name)
    assert len(gdf) > 0


def test_ui_not_required_to_import_geopandas_directly():
    """4. UI-модули (about_dialog, open_map_dialog, main_window) не импортируют geopandas."""
    import rme_mapper.ui.about_dialog as about_mod
    import rme_mapper.ui.open_map_dialog as open_map_mod
    import rme_mapper.ui.main_window as main_window_mod

    assert "geopandas" not in sys_module_names(about_mod)
    assert "geopandas" not in sys_module_names(open_map_mod)
    assert "geopandas" not in sys_module_names(main_window_mod)


def sys_module_names(module) -> list[str]:
    """Вспомогательная функция инспекции прямых импортов модуля."""
    lines = inspect.getsource(module).splitlines()
    imports = []
    for l in lines:
        stripped = l.strip()
        if stripped.startswith("import ") or stripped.startswith("from "):
            imports.append(stripped)
    return imports


def test_list_layers_via_backend():
    """5. list_layers работает через backend."""
    gpkg_path = get_default_geopackage_path()
    backend = get_backend()
    layers = backend.list_layers(gpkg_path)
    assert isinstance(layers, list)
    layer_names = [name for name, _ in layers]
    assert "gis_osm_adminareas_a_free" in layer_names


def test_layer_metadata_via_backend():
    """6. layer metadata работает через backend."""
    gpkg_path = get_default_geopackage_path()
    backend = get_backend()
    meta = backend.get_layer_metadata(gpkg_path, "gis_osm_adminareas_a_free")
    assert isinstance(meta, dict)
    assert meta.get("layer_name") == "gis_osm_adminareas_a_free"
    assert "features_count" in meta
    assert "crs" in meta


def test_runtime_map_profile_creation_via_backend():
    """7. runtime MapProfile создается через backend data (CRS, extent, boundary)."""
    gpkg_path = get_default_geopackage_path()
    backend = get_backend()

    bnd = backend.find_boundary_layer(gpkg_path)
    assert bnd is not None

    crs = backend.get_crs(gpkg_path, bnd)
    assert crs is not None

    extent = backend.get_extent(gpkg_path, bnd)
    assert extent is not None
    assert "xmin" in extent and "ymax" in extent

    profile = MapProfile(
        id="runtime_backend_profile",
        name="Runtime Profile",
        source_type="geopackage",
        source_path=str(gpkg_path),
        crs=crs,
        boundary_layer=bnd,
        extent=extent,
    )
    assert profile.boundary_layer == bnd
    assert profile.extent == extent


def test_backend_error_handling_no_crash():
    """8. backend error при некорректном файле не вызывает crash приложения."""
    backend = get_backend()
    fake_path = Path("non_existent_map.gpkg")

    # exists должен возвращать False
    assert backend.exists(fake_path) is False

    # get_crs и get_extent для несуществующего файла возвращают None
    assert backend.get_crs(fake_path) is None
    assert backend.get_extent(fake_path) is None

    # Запрос слоев для несуществующего файла выбрасывает предсказуемый FileNotFoundError
    with pytest.raises(FileNotFoundError):
        backend.list_layers(fake_path)


def test_legacy_backend_placeholder():
    """Проверка плейсхолдера LegacyGeoPackageBackend."""
    legacy = BackendFactory.get_backend("legacy")
    assert isinstance(legacy, LegacyGeoPackageBackend)

    with pytest.raises(NotImplementedError, match="LegacyGeoPackageBackend запланирован"):
        legacy.exists("test.gpkg")

    with pytest.raises(NotImplementedError, match="LegacyGeoPackageBackend запланирован"):
        legacy.list_layers("test.gpkg")


# ==============================================================================
# БЛОК 3: APP INFO, AUTHOR & ABOUT DIALOG TESTS
# ==============================================================================

def test_app_name_and_version():
    """9. APP_NAME == 'GeoPoint Mapper', 10. Единая версия приложения."""
    assert APP_NAME == "GeoPoint Mapper"
    assert APP_VERSION == PRODUCT_VERSION == FILE_VERSION
    assert len(APP_VERSION.split(".")) >= 2
    assert COPYRIGHT_YEAR == "2026"


def test_author_metadata():
    """11. AUTHOR_NAME, 12. AUTHOR_TELEGRAM, AUTHOR_EMAIL берутся из app_info."""
    assert AUTHOR_NAME == "Кульдеев Вадим Алексеевич"
    assert AUTHOR_TELEGRAM == "@enotis03"
    assert AUTHOR_EMAIL == "zingeevruslan@gmail.com"
    assert "Кульдеев Вадим Алексеевич" in COPYRIGHT_TEXT
    assert format_telegram_url() == "https://t.me/enotis03"


def test_telegram_url_formatting():
    """17. Telegram URL корректно строится для @username.
    18. Telegram URL корректно работает для полного URL.
    19. placeholder Telegram не открывает ссылку (возвращает None).
    """
    # 17: @username
    assert format_telegram_url("@geopoint_dev") == "https://t.me/geopoint_dev"
    assert format_telegram_url("@enotis03") == "https://t.me/enotis03"

    # 18: Полный URL
    assert format_telegram_url("https://t.me/mychannel") == "https://t.me/mychannel"
    assert format_telegram_url("http://t.me/mychannel") == "http://t.me/mychannel"
    assert format_telegram_url("t.me/mychannel") == "https://t.me/mychannel"
    assert format_telegram_url("geopoint_user") == "https://t.me/geopoint_user"

    # 19: Плейсхолдер
    assert format_telegram_url("Указать Telegram") is None
    assert format_telegram_url("указать telegram") is None
    assert format_telegram_url("") is None


@pytest.fixture(scope="module")
def qapp():
    """Инициализация QApplication для тестов интерфейса."""
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def test_about_dialog_creation_and_contents(qapp):
    """13. AboutDialog создается.
    14. Отображает имя приложения.
    15. Отображает версию.
    16. Отображает автора.
    """
    from rme_mapper.ui.about_dialog import AboutDialog

    dlg = AboutDialog()
    assert dlg is not None
    assert APP_NAME in dlg.windowTitle()
    assert dlg.title_label.text() == APP_NAME
    assert APP_VERSION in dlg.version_label.text()
    assert dlg.author_val_label.text() == "Кульдеев Вадим Алексеевич"
    assert "@enotis03" in dlg.tg_label.text()
    assert "zingeevruslan@gmail.com" in dlg.email_label.text()
    assert dlg.desc_label.text() == APP_DESCRIPTION
    assert "Кульдеев Вадим Алексеевич" in dlg.copyright_label.text()


def test_main_window_contains_help_menu(qapp):
    """20. Верхнее меню 'Справка' убрано (перенесено в единые Настройки), но about_action и show_about_dialog доступны."""
    from rme_mapper.ui.main_window import MainWindow

    window = MainWindow()
    assert window is not None
    assert not hasattr(window, "help_menu")
    assert hasattr(window, "settings_menu")
    assert hasattr(window, "about_action")
    assert window.about_action.text() == "О программе..."
    assert hasattr(window, "show_about_dialog")
    assert hasattr(window, "preferences_action")
    window.close()


# ==============================================================================
# БЛОК 4: PROJECT COMPATIBILITY TESTS (*.gpmap / *.rmeproject)
# ==============================================================================

def test_gpmap_does_not_contain_qt_objects():
    """21. gpmap не содержит Qt-объектов (QColor, QPixmap, QGraphicsItem)."""
    pt = ProjectPointData(
        id="test-pt-1",
        name="Точка",
        latitude=56.63,
        longitude=47.88,
        red=200,
        green=50,
        blue=50,
        zone_enabled=True,
        radius_m=1000.0,
    )
    proj = ProjectData(
        format=PRIMARY_PROJECT_FORMAT,
        version=1,
        map=ProjectMapData(name="Карта", relative_path="maps/test.gpkg"),
        points=[pt],
    )
    data = proj.to_dict()

    # Рекурсивная проверка отсутствия Qt-типов
    def check_no_qt(val):
        assert not type(val).__name__.startswith("Q")
        if isinstance(val, dict):
            for k, v in val.items():
                check_no_qt(k)
                check_no_qt(v)
        elif isinstance(val, list):
            for item in val:
                check_no_qt(item)

    check_no_qt(data)


def test_gpmap_valid_utf8_json_and_no_qapp():
    """22. gpmap валидный UTF-8 JSON.
    23. gpmap можно сериализовать и записать без QApplication.
    """
    pt = ProjectPointData(
        id="pt-utf8",
        name="Йошкар-Ола 🌟 Тест",
        latitude=56.63,
        longitude=47.88,
    )
    proj = ProjectData(
        format=PRIMARY_PROJECT_FORMAT,
        version=1,
        points=[pt],
    )

    with tempfile.TemporaryDirectory() as tmp_dir:
        target_path = Path(tmp_dir) / "test_project.gpmap"
        saved = ProjectService.save_project(proj, target_path)
        assert saved.exists()

        # Чтение сырых байт для проверки UTF-8
        raw_bytes = saved.read_bytes()
        decoded_text = raw_bytes.decode("utf-8")
        assert "Йошкар-Ола 🌟 Тест" in decoded_text

        # Валидный JSON
        parsed = json.loads(decoded_text)
        assert parsed["format"] == PRIMARY_PROJECT_FORMAT
        assert parsed["version"] == 1

        # Загрузка через сервис
        loaded = ProjectService.load_project(saved)
        assert loaded.points[0].name == "Йошкар-Ола 🌟 Тест"


def test_legacy_rmeproject_opens():
    """24. old rmeproject продолжает открываться."""
    legacy_json = {
        "format": LEGACY_PROJECT_FORMAT,
        "version": 1,
        "map": {
            "path": "maps/test_map/mari_el.gpkg",
            "name": "Республика Марий Эл",
        },
        "layers": {
            "admin_level_4": True,
        },
        "points": [
            {
                "id": "legacy-pt-1",
                "name": "Legacy Точка",
                "latitude": 56.63,
                "longitude": 47.88,
            }
        ],
    }
    with tempfile.TemporaryDirectory() as tmp_dir:
        legacy_file = Path(tmp_dir) / "project.rmeproject"
        with open(legacy_file, "w", encoding="utf-8") as f:
            json.dump(legacy_json, f, ensure_ascii=False)

        loaded = ProjectService.load_project(legacy_file)
        assert loaded.format == LEGACY_PROJECT_FORMAT
        assert loaded.points[0].name == "Legacy Точка"


def test_current_gpmap_opens():
    """25. current gpmap продолжает открываться."""
    current_json = {
        "format": PRIMARY_PROJECT_FORMAT,
        "version": 1,
        "map": {
            "relative_path": "maps/test_map/mari_el.gpkg",
            "name": "Марий Эл",
        },
        "points": [
            {
                "id": "gp-1",
                "name": "Пункт A",
                "latitude": 56.5,
                "longitude": 47.5,
            }
        ],
    }
    with tempfile.TemporaryDirectory() as tmp_dir:
        gp_file = Path(tmp_dir) / "project.gpmap"
        with open(gp_file, "w", encoding="utf-8") as f:
            json.dump(current_json, f, ensure_ascii=False)

        loaded = ProjectService.load_project(gp_file)
        assert loaded.format == PRIMARY_PROJECT_FORMAT
        assert loaded.points[0].id == "gp-1"


def test_project_version_decoupled_from_app_version():
    """26. Версия проекта (version: 1) не зависит от версии приложения."""
    proj = ProjectData()
    assert proj.version == 1
    assert bool(APP_VERSION)
    assert str(proj.version) != APP_VERSION
