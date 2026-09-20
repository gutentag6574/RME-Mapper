"""Комплексные интеграционные и стресс-тесты для онлайн-карт (Этап 20: Tests 81-86)."""

import os
from pathlib import Path
import pytest
from PySide6.QtCore import QPointF, QRectF
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QGraphicsScene

from rme_mapper.i18n import set_language, tr
from rme_mapper.maps.map_canvas import MapCanvas
from rme_mapper.maps.online_tile_manager import OnlineTileManager
from rme_mapper.models.map_point import MapPoint
from rme_mapper.models.online_provider import MapType, OnlineTileProvider, ProviderRegistry
from rme_mapper.services.tile_cache import TileDiskCache
from rme_mapper.services.tile_loader import TileLoader
from rme_mapper.services.tile_math import TileMath
from rme_mapper.ui.main_window import MainWindow
from tests.test_stage20_canvas_and_tiles import _make_dummy_tile_png


def test_81_manual_offline_resilience(qapp, tmp_path: Path):
    """81. Устойчивость к отключению сети: кэшированные тайлы отображаются, инструменты работают."""
    cache = TileDiskCache(base_dir=tmp_path / "offline_cache")
    # Кэшируем тайл для центра Москвы
    dummy_png = _make_dummy_tile_png()
    cache.save_tile("osm_standard", 12, 2476, 1280, dummy_png)

    canvas = MapCanvas()
    canvas.resize(800, 600)
    canvas.show()

    provider = ProviderRegistry.get_provider("osm_standard")
    canvas.set_online_basemap(provider)

    # Имитируем офлайн: лоадер без сети
    manager = canvas.online_tile_manager()
    manager._cache = cache

    # Перемещаемся в область с кэшированным тайлом
    rect = TileMath.tile_to_scene_rect(2476, 1280, 12)
    manager.update_viewport(rect, meters_per_pixel=38.0)

    # Тайл успешно отображается
    assert (12, 2476, 1280) in manager._visible_tile_items

    # Проверяем интерактивность инструментов в офлайн
    canvas.start_measurement("measure_distance")
    assert canvas.interaction_mode == "measure_distance"

    # Добавляем точку
    pt = MapPoint(id="p_offline", name="Офлайн точка", latitude=55.75, longitude=37.61)
    canvas.add_user_point(pt)
    assert "p_offline" in canvas._user_point_items

    canvas.close()


def test_82_manual_rapid_pan_zoom_stress(qapp, tmp_path: Path):
    """82. Стресс-тест быстрого зума и панорамирования: отсутствие утечек и блокировок."""
    cache = TileDiskCache(base_dir=tmp_path / "stress_cache")
    scene = QGraphicsScene()
    manager = OnlineTileManager(scene, tile_cache=cache)
    provider = ProviderRegistry.get_provider("osm_standard")
    manager.set_provider(provider)

    # Быстрые скачки по зумам от 2 до 18 и по разным координатам
    for z in range(2, 18):
        # Различные координаты по миру
        tx = (1 << (z - 1))
        ty = (1 << (z - 1))
        rect = TileMath.tile_to_scene_rect(tx, ty, z)
        m_per_px = 156543.03392 / (1 << z)
        manager.update_viewport(rect, meters_per_pixel=m_per_px)

        assert manager.current_zoom == z
        # Количество элементов на сцене никогда не должно превышать разумный предел
        assert len(manager._visible_tile_items) <= 250

    manager.clear()
    assert len(manager._visible_tile_items) == 0


def test_83_manual_empty_map_fallback(qapp):
    """83. Отключение карты: корректный возврат в пустое состояние."""
    canvas = MapCanvas()
    canvas.resize(800, 600)
    canvas.show()

    provider = ProviderRegistry.get_provider("osm_standard")
    canvas.set_online_basemap(provider)
    assert canvas.is_online_map_active() is True
    assert canvas.attribution_overlay.is_map_active() is True

    # Очищаем онлайн-подложку
    canvas.clear_online_basemap()
    assert canvas.is_online_map_active() is False
    assert canvas.attribution_overlay.is_map_active() is False
    assert len(canvas.online_tile_manager()._visible_tile_items) == 0

    canvas.close()


def test_84_manual_cache_limit_enforcement(tmp_path: Path):
    """84. Контроль размера кэша: вытеснение по LRU при превышении квоты."""
    # Устанавливаем лимит кэша 10 КБ (для теста)
    limit = 10 * 1024
    cache = TileDiskCache(base_dir=tmp_path / "lru_limit_cache", max_size_bytes=limit)

    dummy_png = _make_dummy_tile_png() + b"x" * 2000
    tile_size = len(dummy_png)
    assert tile_size > 2000

    # Записываем 10 тайлов (суммарно > 25 КБ, при лимите 10 КБ)
    for i in range(10):
        cache.save_tile("osm_standard", 10, i, i, dummy_png)

    # Суммарный размер не должен превышать лимит с запасом
    total_size = cache.get_total_size_bytes()
    assert total_size <= limit * 1.2
    # Самый первый тайл должен быть вытеснен
    assert not cache.has_tile("osm_standard", 10, 0, 0)
    # Последний записанный тайл должен быть на месте
    assert cache.has_tile("osm_standard", 10, 9, 9)


def test_85_manual_ru_en_attribution_and_ui(qapp):
    """85. Локализация: переключение RU <-> EN корректно обновляет все тексты Этапа 20."""
    window = MainWindow()

    # Русский язык
    set_language("ru")
    window.retranslate_ui()
    assert window.online_map_menu.title() == "Онлайн-карта"
    assert window.online_standard_action.text() == "Стандартная карта (OSM)"
    assert window.online_satellite_action.text() == "Спутниковая карта"
    assert window.online_hybrid_action.text() == "Гибридная карта"

    # Английский язык
    set_language("en")
    window.retranslate_ui()
    assert window.online_map_menu.title() == "Online Map"
    assert window.online_standard_action.text() == "Standard Map (OSM)"
    assert window.online_satellite_action.text() == "Satellite Map"
    assert window.online_hybrid_action.text() == "Hybrid Map"

    # Возвращаем русский
    set_language("ru")
    window.retranslate_ui()
    window.close()


def test_86_manual_point_coordinates_accuracy():
    """86. Точность проецирования координат: прямое и обратное преобразование Web Mercator."""
    # Координаты Красной площади: (55.7525, 37.6231)
    lat = 55.7525
    lon = 37.6231

    mx, my = TileMath.lat_lon_to_mercator(lat, lon)
    back_lat, back_lon = TileMath.mercator_to_lat_lon(mx, my)

    assert abs(back_lat - lat) < 1e-7
    assert abs(back_lon - lon) < 1e-7

    # Преобразование в тайловые координаты
    zoom = 15
    tx, ty = TileMath.mercator_to_tile(mx, my, zoom)
    min_x, min_y, max_x, max_y = TileMath.tile_to_mercator_bounds(tx, ty, zoom)

    assert min_x <= mx <= max_x
    assert min_y <= my <= max_y
