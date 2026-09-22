"""Автоматизированные тесты совместимости с устаревшими версиями Windows (Этап 24).

Проверяет:
1. Централизованный сервис возможностей RuntimeCapabilities (Modern, Win7, XP).
2. Отсутствие дублирования проверок возможностей (интеграция с BackendFactory).
3. Грациозную деградацию интерфейса (UI Feature Degradation) при недоступности функций.
4. Межплатформенную совместимость проектов *.gpmap (Modern -> Legacy -> Modern).
5. Сохранение метаданных неподдерживаемых источников карт при Round-Trip.
6. Корректную работу с путями (кириллица, пробелы, относительные пути, fallback APPDATA).
7. Аудит безопасности: отсутствие pickle/eval/exec, строгая валидация TLS без verify=False.
"""

import json
import os
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest

from rme_mapper.backends.factory import BackendFactory
from rme_mapper.models.map_point import MapPoint
from rme_mapper.models.object_group import ObjectGroup
from rme_mapper.models.project_data import PRIMARY_PROJECT_FORMAT, ProjectData, ProjectMapData
from rme_mapper.services.project_service import ProjectService
from rme_mapper.services.runtime_capabilities import RuntimeCapabilities


# =============================================================================
# 1. ТЕСТЫ ВОЗМОЖНОСТЕЙ (CAPABILITIES & PROFILES)
# =============================================================================

def test_01_runtime_capabilities_modern_profile():
    """Проверка полного набора возможностей на современной платформе Windows 10/11."""
    RuntimeCapabilities.reset_overrides()
    assert RuntimeCapabilities.get_profile_name() in ("modern", "win7", "xp")
    # В среде разработки должны быть доступны ключевые возможности
    assert RuntimeCapabilities.supports_geopackage() is True
    assert RuntimeCapabilities.supports_xlsx() is True
    assert RuntimeCapabilities.supports_secure_tls() is True
    assert RuntimeCapabilities.supports_online_maps() is True
    assert RuntimeCapabilities.supports_georeferencing() is True


def test_02_runtime_capabilities_win7_simulation():
    """Проверка симуляции профиля Windows 7."""
    RuntimeCapabilities.override_for_testing(
        profile="win7",
        supports_high_dpi=False,
    )
    try:
        assert RuntimeCapabilities.get_profile_name() == "win7"
        assert RuntimeCapabilities.supports_high_dpi() is False
        assert RuntimeCapabilities.supports_geopackage() is True
        summary = RuntimeCapabilities.get_capabilities_summary()
        assert summary["profile"] == "win7"
        assert summary["supports_high_dpi"] is False
    finally:
        RuntimeCapabilities.reset_overrides()


def test_03_runtime_capabilities_xp_simulation_and_unavailable():
    """Проверка симуляции Windows XP: блокировка TLS, онлайн-карт и растров."""
    RuntimeCapabilities.override_for_testing(
        profile="xp",
        supports_secure_tls=False,
        supports_online_maps=False,
        supports_geotiff=False,
        supports_high_dpi=False,
    )
    try:
        assert RuntimeCapabilities.get_profile_name() == "xp"
        assert RuntimeCapabilities.supports_secure_tls() is False
        assert RuntimeCapabilities.supports_online_maps() is False
        assert RuntimeCapabilities.supports_geotiff() is False

        unavailable = RuntimeCapabilities.get_unavailable_features()
        assert any("Online Maps" in item for item in unavailable)
        assert any("GeoTIFF" in item for item in unavailable)
    finally:
        RuntimeCapabilities.reset_overrides()


def test_04_no_duplicate_capability_systems():
    """Проверка отсутствия дублирующих систем проверки возможностей: BackendFactory делегирует в RuntimeCapabilities."""
    RuntimeCapabilities.override_for_testing(supports_geotiff=False, supports_geopackage=True)
    try:
        assert BackendFactory.supports_geotiff() is False
        assert BackendFactory.supports_source_type("geotiff") is False
        assert BackendFactory.supports_geopackage() is True
        assert BackendFactory.supports_source_type("geopackage") is True
        assert BackendFactory.supports_source_type("online_xyz") is True
    finally:
        RuntimeCapabilities.reset_overrides()


def test_05_runtime_environment_logging(caplog):
    """Проверка работы функции логирования среды и возможностей при старте."""
    with caplog.at_level("INFO"):
        RuntimeCapabilities.log_runtime_environment()
    assert any("Startup Environment" in record.message for record in caplog.records)
    assert any("Capabilities:" in record.message for record in caplog.records)


# =============================================================================
# 2. ТЕСТЫ СОВМЕСТИМОСТИ ПРОЕКТОВ И ROUND-TRIP МЕТАДАННЫХ
# =============================================================================

def test_06_project_schema_version_invariant():
    """Формат проекта сохраняет схему v1 независимо от платформы."""
    ps = ProjectService()
    pdata = ps.build_project_data(
        map_path=None,
        layers=[],
        points=[],
    )
    assert pdata.format == PRIMARY_PROJECT_FORMAT
    assert pdata.version == 1


def test_07_unsupported_online_map_loading_does_not_crash(qapp):
    """Открытие проекта с онлайн-картой на платформе без поддержки онлайн-карт открывается без падения."""
    from rme_mapper.services.point_service import PointService
    from rme_mapper.ui.controllers.project_controller import ProjectController
    from PySide6.QtWidgets import QWidget

    parent = QWidget()

    mock_map_ctrl = MagicMock()
    mock_map_ctrl.map_path = None
    mock_map_ctrl.loaded_layers = []
    mock_map_ctrl.active_profile = None

    point_service = PointService()
    mock_point_ctrl = MagicMock()
    mock_catalog = MagicMock()

    controller = ProjectController(
        parent_widget=parent,
        project_service=ProjectService(),
        point_service=point_service,
        map_controller=mock_map_ctrl,
        point_controller=mock_point_ctrl,
        map_catalog_service=mock_catalog,
        on_title_changed=MagicMock(),
    )

    # Проект, созданный в Modern с онлайн-картой OSM
    project = ProjectData(
        format=PRIMARY_PROJECT_FORMAT,
        version=1,
        map=ProjectMapData(
            map_id="online_osm",
            name="OpenStreetMap Standard",
            source_type="online_xyz",
            crs="EPSG:3857",
            provider_id="osm_standard",
        ),
        layers={},
        points=[],
        groups=[],
    )

    RuntimeCapabilities.override_for_testing(supports_online_maps=False)
    try:
        success = controller._resolve_and_apply_project(project, path=None)
        assert success is True
        # Карта выгружена, так как онлайн-карты не поддерживаются
        mock_map_ctrl.unload_map.assert_called_once()
        # Метаданные неподдерживаемой карты сохранены в контроллере
        assert controller._unsupported_map_data is not None
        assert controller._unsupported_map_data.source_type == "online_xyz"
        assert controller._unsupported_map_data.provider_id == "osm_standard"
    finally:
        RuntimeCapabilities.reset_overrides()


def test_08_unsupported_map_source_roundtrip_preservation(tmp_path: Path):
    """Критический Round-Trip тест: Modern -> Legacy (без онлайн карт) -> Modern.

    1. В Modern создается проект с онлайн-картой OpenStreetMap и 2 точками.
    2. Проект открывается в Legacy-режиме (без онлайн-карт).
    3. В Legacy добавляется 3-я точка, и проект сохраняется.
    4. Проект повторно открывается в Modern:
       - Все 3 точки на месте;
       - Метаданные онлайн-карты (online_xyz, osm_standard) ПОЛНОСТЬЮ СОХРАНЕНЫ!
    """
    proj_path = tmp_path / "modern_project.gpmap"
    ps = ProjectService()

    # 1. Создание проекта Modern
    orig_map = ProjectMapData(
        map_id="online_osm_standard",
        name="OpenStreetMap Standard",
        source_type="online_xyz",
        crs="EPSG:3857",
        provider_id="osm_standard",
    )
    pts = [
        MapPoint(id="pt_1", object_number="1", name="Точка 1", latitude=55.75, longitude=37.61),
        MapPoint(id="pt_2", object_number="2", name="Точка 2", latitude=55.76, longitude=37.62),
    ]
    groups = [ObjectGroup(id="grp_1", name="Группа Альфа", description="Основная")]

    project_modern = ps.build_project_data(
        map_path=None,
        layers=[],
        points=pts,
        groups=groups,
        preserve_map_data=orig_map,
    )
    ps.save_project(project_modern, proj_path)

    # 2. Симуляция Legacy Build (онлайн-карты недоступны)
    RuntimeCapabilities.override_for_testing(supports_online_maps=False)
    try:
        loaded_legacy = ps.load_project(proj_path)
        assert len(loaded_legacy.points) == 2
        assert loaded_legacy.map.source_type == "online_xyz"

        # Добавляем 3-ю точку в проект
        loaded_points = [p.to_map_point() for p in loaded_legacy.points]
        loaded_points.append(
            MapPoint(id="pt_3", object_number="3", name="Точка 3 (Legacy)", latitude=55.77, longitude=37.63)
        )

        # Сохраняем в Legacy без активной подложки (active_profile=None), но с preserve_map_data
        saved_legacy = ps.build_project_data(
            map_path=None,
            layers=[],
            points=loaded_points,
            groups=groups,
            preserve_map_data=loaded_legacy.map,
        )
        ps.save_project(saved_legacy, proj_path)
    finally:
        RuntimeCapabilities.reset_overrides()

    # 3. Повторное открытие в Modern Build
    reopened_modern = ps.load_project(proj_path)
    assert len(reopened_modern.points) == 3
    assert reopened_modern.points[2].name == "Точка 3 (Legacy)"
    assert len(reopened_modern.groups) == 1
    assert reopened_modern.groups[0].name == "Группа Альфа"

    # Проверка целостности метаданных карты
    assert reopened_modern.map.source_type == "online_xyz"
    assert reopened_modern.map.provider_id == "osm_standard"
    assert reopened_modern.map.map_id == "online_osm_standard"
    assert reopened_modern.map.crs == "EPSG:3857"


def test_09_unsupported_geotiff_source_roundtrip(tmp_path: Path):
    """Round-trip сохранение метаданных GeoTIFF при отсутствии бэкенда rasterio."""
    proj_path = tmp_path / "geotiff_project.gpmap"
    ps = ProjectService()

    geotiff_map = ProjectMapData(
        map_id="raster_map_01",
        relative_path="maps/satellite_view.tif",
        name="Satellite View",
        source_type="geotiff",
        crs="EPSG:32637",
        affine_transform=[10.0, 0.0, 500000.0, 0.0, -10.0, 6000000.0],
    )
    pdata = ps.build_project_data(
        map_path=None,
        layers=[],
        points=[MapPoint(id="p1", object_number="1", name="Радар", latitude=55.0, longitude=37.0)],
        preserve_map_data=geotiff_map,
    )
    ps.save_project(pdata, proj_path)

    # Загрузка и пересохранение
    reloaded = ps.load_project(proj_path)
    re_saved = ps.build_project_data(
        map_path=None,
        layers=[],
        points=[p.to_map_point() for p in reloaded.points],
        preserve_map_data=reloaded.map,
    )
    ps.save_project(re_saved, proj_path)

    final_proj = ps.load_project(proj_path)
    assert final_proj.map.source_type == "geotiff"
    assert final_proj.map.relative_path == "maps/satellite_view.tif"
    assert final_proj.map.affine_transform == [10.0, 0.0, 500000.0, 0.0, -10.0, 6000000.0]
    assert final_proj.map.crs == "EPSG:32637"


# =============================================================================
# 3. ТЕСТЫ ПУТЕЙ, КИРИЛЛИЦЫ И УСТАРЕВШИХ ПЕРЕМЕННЫХ ОКРУЖЕНИЯ
# =============================================================================

def test_10_cyrillic_paths_and_unicode_names(tmp_path: Path):
    """Корректная обработка кириллических путей к директориям, файлам и точкам."""
    cyrillic_dir = tmp_path / "Географические Карты 2026 №1"
    cyrillic_dir.mkdir()
    project_file = cyrillic_dir / "Проект_Центральный_Округ.gpmap"

    ps = ProjectService()
    pts = [
        MapPoint(
            id="pt_ru_1",
            object_number="1",
            name="Геодезический знак «Северный»",
            latitude=55.75,
            longitude=37.61,
            description="Пункт государственной геодезической сети (ГГС)",
        )
    ]
    groups = [ObjectGroup(id="g1", name="Особо охраняемые зоны", description="Зоны с ограничениями")]

    pdata = ps.build_project_data(map_path=None, layers=[], points=pts, groups=groups)
    saved = ps.save_project(pdata, project_file)
    assert saved.exists()

    loaded = ps.load_project(project_file)
    assert loaded.points[0].name == "Геодезический знак «Северный»"
    assert loaded.points[0].description == "Пункт государственной геодезической сети (ГГС)"
    assert loaded.groups[0].name == "Особо охраняемые зоны"


def test_11_legacy_recovery_paths_fallback():
    """Проверка вычисления пути аварийного восстановления на Windows XP (отсутствие LOCALAPPDATA, наличие APPDATA)."""
    # 1. При отсутствии LOCALAPPDATA, но наличии APPDATA (стандартное поведение Windows XP)
    with patch.dict(os.environ, {"LOCALAPPDATA": "", "APPDATA": "C:\\Documents and Settings\\User\\Application Data"}):
        p = ProjectService.get_recovery_snapshot_path()
        assert "Application Data" in str(p) or ".geopoint_mapper" in str(p)

    # 2. При полном отсутствии обеих переменных
    with patch.dict(os.environ, {"LOCALAPPDATA": "", "APPDATA": ""}):
        p = ProjectService.get_recovery_snapshot_path()
        assert ".geopoint_mapper" in str(p)


# =============================================================================
# 4. ТЕСТЫ ДЕГРАДАЦИИ ИНТЕРФЕЙСА (UI FEATURE DEGRADATION)
# =============================================================================

def test_12_ui_action_degradation_when_online_maps_disabled(qapp):
    """Деактивация действий онлайн-карт и установка поясняющего tooltip при отключении сетевого TLS."""
    from rme_mapper.ui.main_window import MainWindow

    RuntimeCapabilities.override_for_testing(supports_online_maps=False, supports_secure_tls=False)
    try:
        window = MainWindow()

        assert window.online_map_menu.isEnabled() is False
        assert "TLS 1.2+" in window.online_map_menu.toolTip()
        assert window.online_standard_action.isEnabled() is False
        assert window.online_satellite_action.isEnabled() is False
        assert window.online_hybrid_action.isEnabled() is False
        assert window.clear_tile_cache_action.isEnabled() is False

        # Попытка вызова действия не вызывает падений
        with patch("PySide6.QtWidgets.QMessageBox.warning") as mock_warn:
            window.load_online_standard_map()
            mock_warn.assert_called_once()
        window.close()
    finally:
        RuntimeCapabilities.reset_overrides()


# =============================================================================
# 5. АУДИТ БЕЗОПАСНОСТИ (SECURITY AUDIT)
# =============================================================================

def test_13_security_audit_no_pickle_or_eval():
    """Верификация отсутствия небезопасных механизмов сериализации (pickle, eval, exec)."""
    import inspect
    from rme_mapper.services import project_service

    source = inspect.getsource(project_service)
    assert "import pickle" not in source
    assert "pickle.loads" not in source
    assert "pickle.dump" not in source
    assert "eval(" not in source
    assert "exec(" not in source


def test_14_security_audit_strict_tls_no_verify_false():
    """Верификация строгого соблюдения TLS: отсутствие verify=False и игнорирования SSL-ошибок."""
    import inspect
    from rme_mapper.services import tile_loader

    source = inspect.getsource(tile_loader)
    assert "verify=False" not in source
    assert "ignoreSslErrors" not in source
    assert "SSL_VERIFY_NONE" not in source
