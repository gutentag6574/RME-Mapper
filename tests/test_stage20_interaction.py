"""Тесты UI-взаимодействия и диалогов для онлайн-карт (Этап 20: Tests 51-60)."""

from pathlib import Path
from unittest.mock import patch, MagicMock
import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QMessageBox

from rme_mapper.i18n import set_language, tr
from rme_mapper.models.online_provider import MapType, OnlineTileProvider, ProviderRegistry
from rme_mapper.services.app_settings_service import AppSettingsService
from rme_mapper.ui.main_window import MainWindow
from rme_mapper.ui.online_basemap_dialog import OnlineBasemapDialog


@pytest.fixture
def default_gpkg() -> Path:
    return Path(__file__).resolve().parent.parent / "maps" / "test_map" / "prepared" / "mari.gpkg"


@pytest.fixture
def clean_settings(tmp_path: Path):
    settings = AppSettingsService()
    # Сохраняем и сбрасываем ключи провайдеров для тестов
    old_satellite_key = settings.get_provider_api_key("mapbox_satellite")
    settings.set_provider_api_key("mapbox_satellite", "")
    yield settings
    if old_satellite_key:
        settings.set_provider_api_key("mapbox_satellite", old_satellite_key)


def test_51_online_map_menu_structure(qapp):
    """51. Меню 'Онлайн-карта' содержит все требуемые действия и подменю."""
    window = MainWindow()
    set_language("ru")

    assert hasattr(window, "online_map_menu")
    assert window.online_map_menu.title() == tr("menu.online_map")

    assert hasattr(window, "online_standard_action")
    assert window.online_standard_action.text() == tr("action.online_standard")

    assert hasattr(window, "online_satellite_action")
    assert window.online_satellite_action.text() == tr("action.online_satellite")

    assert hasattr(window, "online_hybrid_action")
    assert window.online_hybrid_action.text() == tr("action.online_hybrid")

    assert hasattr(window, "select_online_basemap_action")
    assert window.select_online_basemap_action.text() == tr("action.select_online_basemap")

    assert hasattr(window, "clear_tile_cache_action")
    window.close()


def test_52_switch_to_osm_standard(qapp):
    """52. Выбор 'Стандартная карта' переключает подложку на OpenStreetMap."""
    window = MainWindow()
    window.show()

    window.online_standard_action.trigger()

    manager = window.map_canvas.online_tile_manager()
    assert manager.is_active is True
    assert manager.provider is not None
    assert manager.provider.id == "osm_standard"
    assert manager.provider.map_type == MapType.STANDARD

    # Проверяем копирайт OpenStreetMap
    assert window.map_canvas.attribution_overlay is not None
    assert "OpenStreetMap" in window.map_canvas.attribution_overlay.text()
    window.close()


def test_53_satellite_without_api_key_prompts_dialog(qapp, clean_settings):
    """53. Выбор спутниковой карты без сохраненного API-ключа открывает диалог настройки."""
    window = MainWindow()
    window.show()

    # Мокаем OnlineBasemapDialog.exec чтобы не блокировать выполнение
    with patch.object(OnlineBasemapDialog, "exec", return_value=False) as mock_exec:
        window.online_satellite_action.trigger()
        assert mock_exec.called

    window.close()


def test_54_satellite_with_api_key_loads_provider(qapp, clean_settings):
    """54. Выбор спутниковой карты с сохраненным ключом загружает провайдера без диалога."""
    clean_settings.set_provider_api_key("mapbox_satellite", "pk.test_mapbox_key_12345")
    window = MainWindow()
    window.show()

    with patch.object(OnlineBasemapDialog, "exec") as mock_exec:
        window.online_satellite_action.trigger()
        assert not mock_exec.called

    manager = window.map_canvas.online_tile_manager()
    assert manager.is_active is True
    assert manager.provider.id == "mapbox_satellite"
    assert manager.api_key == "pk.test_mapbox_key_12345"
    window.close()


def test_55_hybrid_map_switch(qapp, clean_settings):
    """55. Переключение на гибридную карту с сохраненным ключом."""
    clean_settings.set_provider_api_key("mapbox_hybrid", "pk.test_mapbox_key_hybrid")
    window = MainWindow()
    window.show()

    window.load_online_hybrid_map()

    manager = window.map_canvas.online_tile_manager()
    assert manager.is_active is True
    assert manager.provider.id == "mapbox_hybrid"
    assert manager.provider.map_type == MapType.HYBRID
    window.close()


def test_56_online_basemap_dialog_custom_xyz(qapp):
    """56. Диалог 'Выбрать подложку': выбор провайдера, валидация и кастомные XYZ."""
    dialog = OnlineBasemapDialog()

    # 1. Проверяем переключение по типам карт
    dialog._rb_standard.setChecked(True)
    assert dialog.combo_provider.count() >= 1
    assert dialog.combo_provider.currentData() == "osm_standard"

    dialog._rb_satellite.setChecked(True)
    assert dialog.combo_provider.count() >= 1
    assert dialog.combo_provider.currentData() == "mapbox_satellite"

    dialog._rb_hybrid.setChecked(True)
    assert dialog.combo_provider.count() >= 1
    assert dialog.combo_provider.currentData() == "mapbox_hybrid"

    # 2. Проверяем пользовательский XYZ
    dialog._rb_custom.setChecked(True)
    assert dialog._url_edit.isEnabled() is True
    dialog._url_edit.setText("https://tile.example.com/{z}/{x}/{y}.png")
    dialog._attr_edit.setText("© Example Maps")

    # Принимаем диалог
    dialog._on_accept()
    custom_prov = dialog.get_selected_provider()
    assert custom_prov is not None
    assert custom_prov.map_type == MapType.CUSTOM
    assert custom_prov.url_template == "https://tile.example.com/{z}/{x}/{y}.png"
    assert custom_prov.attribution == "© Example Maps"
    dialog.close()


def test_57_clear_tile_cache_menu_action(qapp):
    """57. Очистка дискового кэша тайлов через интерфейс меню."""
    window = MainWindow()
    cache = window.map_canvas.online_tile_manager().cache
    # Кладем фиктивный тайл
    cache.save_tile("osm_standard", 1, 1, 1, b"\x89PNG\r\n\x1a\n" + b"dummy")
    assert cache.get_total_size_bytes() > 0

    # Мокаем подтверждение пользователя в QMessageBox.question -> Yes
    with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes):
        window.clear_online_tile_cache()

    assert cache.get_total_size_bytes() == 0
    window.close()


def test_58_offline_mode_cached_tiles_render(qapp):
    """58. В офлайн-режиме загруженные ранее тайлы корректно отображаются из кэша."""
    window = MainWindow()
    manager = window.map_canvas.online_tile_manager()
    provider = ProviderRegistry.get_provider("osm_standard")
    manager.set_provider(provider)

    from tests.test_stage20_canvas_and_tiles import _make_dummy_tile_png
    dummy_png = _make_dummy_tile_png()
    manager.cache.save_tile("osm_standard", 10, 50, 50, dummy_png)

    # Принудительно запрашиваем вьюпорт с этим тайлом
    from rme_mapper.services.tile_math import TileMath
    rect = TileMath.tile_to_scene_rect(50, 50, 10)
    manager.update_viewport(rect, meters_per_pixel=150.0)

    # Тайл должен отображаться как QGraphicsPixmapItem, а не placeholder RectItem
    item = manager._visible_tile_items.get((10, 50, 50))
    assert item is not None
    from PySide6.QtWidgets import QGraphicsPixmapItem
    assert isinstance(item, QGraphicsPixmapItem)
    window.close()


def test_59_auth_error_notification(qapp):
    """59. Ошибка авторизации (401/403) вызывает предупреждающее уведомление в строке состояния."""
    window = MainWindow()
    window.show()

    window._on_online_tiles_auth_error("Mapbox Satellite")
    status_text = window.statusBar().currentMessage()
    assert len(status_text) > 0
    assert "Mapbox Satellite" in status_text
    window.close()


def test_60_switch_between_offline_raster_and_online_map(qapp, default_gpkg):
    """60. Корректное переключение между офлайн-растром (GeoPackage) и онлайн-подложкой."""
    window = MainWindow()
    window.show()

    # 1. Загружаем офлайн растр
    window.load_map(default_gpkg)
    assert window.map_controller.has_map is True
    assert window.map_controller.current_profile.source_type in ("geopackage", "geotiff")
    assert window.map_canvas.online_tile_manager().is_active is False

    # 2. Переключаемся на онлайн-карту
    window.online_standard_action.trigger()
    assert window.map_controller.has_map is True
    assert window.map_controller.current_profile.source_type == "online_xyz"
    assert window.map_canvas.online_tile_manager().is_active is True

    # 3. Переключаемся обратно на офлайн растр
    window.load_map(default_gpkg)
    assert window.map_controller.current_profile.source_type in ("geopackage", "geotiff")
    assert window.map_canvas.online_tile_manager().is_active is False
    window.close()
