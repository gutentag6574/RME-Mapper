"""Тесты отображения онлайн-тайлов на MapCanvas, Z-order, кэша памяти и GIS-инструментов (Этап 20)."""

import os
from pathlib import Path
import pytest
from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QPixmap
from PySide6.QtWidgets import QGraphicsPixmapItem, QGraphicsRectItem, QGraphicsScene

from rme_mapper.maps.map_canvas import MapCanvas
from rme_mapper.maps.online_tile_manager import OnlineTileManager
from rme_mapper.models.map_point import MapPoint
from rme_mapper.models.online_provider import OnlineTileProvider, ProviderRegistry
from rme_mapper.services.tile_cache import TileDiskCache
from rme_mapper.services.tile_loader import TileLoader
from rme_mapper.services.tile_math import TileMath


def _make_dummy_tile_png() -> bytes:
    """Генерация валидного PNG 256x256 в памяти."""
    img = QImage(256, 256, QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(QColor(100, 150, 200))
    from PySide6.QtCore import QBuffer, QIODevice
    buf = QBuffer()
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    img.save(buf, "PNG")
    return bytes(buf.data())


@pytest.fixture
def temp_cache_dir(tmp_path: Path) -> Path:
    cache_dir = tmp_path / "test_tile_cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    return cache_dir


@pytest.fixture
def tile_cache(temp_cache_dir: Path) -> TileDiskCache:
    return TileDiskCache(cache_dir=temp_cache_dir, max_size_bytes=10 * 1024 * 1024)


def test_39_visible_tiles_calculated_on_viewport_change(qapp, tile_cache: TileDiskCache):
    """39. Корректный расчет видимых тайлов при смещении или масштабировании вьюпорта."""
    scene = QGraphicsScene()
    manager = OnlineTileManager(scene, tile_cache=tile_cache)
    provider = ProviderRegistry.get_provider("osm_standard")
    manager.set_provider(provider)

    assert manager.is_active is True

    # Экстент в центре Москвы (Web Mercator meters)
    # x ~ 4180000, y ~ 7500000. В сцене scene_y = -mercator_y
    center_x = 4180000.0
    center_y = -7500000.0
    half_span = 5000.0  # 5 км
    rect = QRectF(center_x - half_span, center_y - half_span, half_span * 2, half_span * 2)

    # meters_per_pixel = 10 м/пикс (~ zoom 14)
    manager.update_viewport(rect, meters_per_pixel=10.0)

    assert manager.current_zoom > 0
    assert len(manager._needed_tiles) > 0
    # Проверяем, что все нужные тайлы соответствуют текущему зуму
    for (z, tx, ty) in manager._needed_tiles:
        assert z == manager.current_zoom
        assert tx >= 0
        assert ty >= 0


def test_40_out_of_viewport_tiles_recycled(qapp, tile_cache: TileDiskCache):
    """40. Удаление из сцены тайлов, вышедших далеко за границы вьюпорта."""
    scene = QGraphicsScene()
    manager = OnlineTileManager(scene, tile_cache=tile_cache)
    provider = ProviderRegistry.get_provider("osm_standard")
    manager.set_provider(provider)

    # Предзаполняем кэш для 2 тайлов
    tile_data = _make_dummy_tile_png()
    tile_cache.put_tile(provider.id, 10, 100, 100, tile_data)
    tile_cache.put_tile(provider.id, 10, 200, 200, tile_data)

    # Вьюпорт 1: вокруг (100, 100) на зуме 10
    b1 = TileMath.tile_to_scene_rect(100, 100, 10)
    manager.update_viewport(b1, meters_per_pixel=150.0)

    keys_1 = set(manager._visible_tile_items.keys())
    assert any(k[1] == 100 for k in keys_1)

    # Перемещаем вьюпорт в совершенно другое место: вокруг (200, 200)
    b2 = TileMath.tile_to_scene_rect(200, 200, 10)
    manager.update_viewport(b2, meters_per_pixel=150.0)

    keys_2 = set(manager._visible_tile_items.keys())
    # Старый тайл 100 не должен присутствовать в новом видимом наборе
    assert not any(k[1] == 100 for k in keys_2)


def test_41_stale_requests_cancelled_on_rapid_pan(qapp, tile_cache: TileDiskCache):
    """41. Отмена устаревших сетевых запросов при быстром панорамировании."""
    scene = QGraphicsScene()
    loader = TileLoader()
    manager = OnlineTileManager(scene, tile_cache=tile_cache, tile_loader=loader)
    provider = ProviderRegistry.get_provider("osm_standard")
    manager.set_provider(provider)

    # Первый вьюпорт (порождает запросы)
    b1 = TileMath.tile_to_scene_rect(50, 50, 8)
    manager.update_viewport(b1, meters_per_pixel=600.0)

    # Быстрый сдвиг в другое место
    b2 = TileMath.tile_to_scene_rect(80, 80, 8)
    manager.update_viewport(b2, meters_per_pixel=600.0)

    # Старые запросы должны быть исключены из очереди
    visible_request_keys = {
        f"{provider.id}/{z}/{x}/{y}" for (z, x, y) in manager._needed_tiles
    }
    for req in loader._queue:
        pid, rz, rx, ry, _ = req
        req_key = f"{pid}/{rz}/{rx}/{ry}"
        assert req_key in visible_request_keys


def test_42_zoom_in_out_resolution_levels(qapp, tile_cache: TileDiskCache):
    """42-43. Приближение выбирает более подробный зум, отдаление — более мелкий."""
    scene = QGraphicsScene()
    manager = OnlineTileManager(scene, tile_cache=tile_cache)
    provider = ProviderRegistry.get_provider("osm_standard")
    manager.set_provider(provider)

    rect = QRectF(4180000.0, -7500000.0, 1000.0, 1000.0)

    # Мелкий масштаб (1000 м/пикс)
    manager.update_viewport(rect, meters_per_pixel=1000.0)
    zoom_out = manager.current_zoom

    # Крупный масштаб (2 м/пикс)
    manager.update_viewport(rect, meters_per_pixel=2.0)
    zoom_in = manager.current_zoom

    assert zoom_in > zoom_out
    assert zoom_in <= provider.max_zoom
    assert zoom_out >= provider.min_zoom


def test_44_memory_lru_cache_eviction(qapp, tile_cache: TileDiskCache):
    """44. LRU кэш памяти ограничивает число хранимых QPixmap и вытесняет старые."""
    scene = QGraphicsScene()
    manager = OnlineTileManager(scene, tile_cache=tile_cache)
    manager._mem_cache_capacity = 3  # маленький лимит для теста
    provider = ProviderRegistry.get_provider("osm_standard")

    pix = QPixmap(10, 10)
    manager._put_mem_cache(provider.id, 10, 1, 1, pix)
    manager._put_mem_cache(provider.id, 10, 2, 2, pix)
    manager._put_mem_cache(provider.id, 10, 3, 3, pix)

    assert len(manager._mem_cache) == 3
    assert (provider.id, 10, 1, 1) in manager._mem_cache

    # Добавляем 4-й элемент — 1-й должен быть вытеснен
    manager._put_mem_cache(provider.id, 10, 4, 4, pix)
    assert len(manager._mem_cache) == 3
    assert (provider.id, 10, 1, 1) not in manager._mem_cache
    assert (provider.id, 10, 4, 4) in manager._mem_cache


def test_45_neutral_placeholder_shown_for_missing_tiles(qapp, tile_cache: TileDiskCache):
    """45. Отображение нейтрального плейсхолдера для незагруженного тайла."""
    scene = QGraphicsScene()
    manager = OnlineTileManager(scene, tile_cache=tile_cache)
    provider = ProviderRegistry.get_provider("osm_standard")
    manager.set_provider(provider)

    b = TileMath.tile_to_scene_rect(10, 10, 5)
    manager.update_viewport(b, meters_per_pixel=4000.0)

    # Тайлов нет в кэше — должны быть созданы элементы-плейсхолдеры QGraphicsRectItem
    assert len(manager._visible_tile_items) > 0
    for item in manager._visible_tile_items.values():
        assert isinstance(item, QGraphicsRectItem)
        assert item.zValue() == 5.0


def test_46_z_order_hierarchy(qapp):
    """46. Иерархия Z-order: тайлы Z=5 < сетка Z=80 < зоны Z=90 < точки Z=100 < подписи Z=110."""
    canvas = MapCanvas()
    canvas.resize(800, 600)
    canvas.show()

    provider = ProviderRegistry.get_provider("osm_standard")
    canvas.set_online_basemap(provider)

    # Добавляем точку с зоной
    pt = MapPoint(
        id="pt1",
        name="Test Point",
        latitude=55.75,
        longitude=37.61,
        source_crs="OGC:CRS84",
        zone_enabled=True,
        radius_m=500.0,
    )
    canvas.add_user_point(pt)

    # Проверяем z-value элементов
    assert canvas.online_tile_manager().is_active is True
    if canvas.online_tile_manager()._tile_group is not None:
        assert canvas.online_tile_manager()._tile_group.zValue() == 5.0

    marker_item = canvas._user_point_items.get("pt1")
    assert marker_item is not None
    assert marker_item.zValue() >= 100.0

    zone_item = canvas._user_zone_items.get("pt1")
    assert zone_item is not None
    assert zone_item.zValue() == 90.0

    canvas.close()


def test_47_dynamic_scale_indicator_with_online_map(qapp):
    """48. Динамический индикатор масштаба корректно обновляется с онлайн-картой."""
    canvas = MapCanvas()
    canvas.resize(800, 600)
    canvas.show()

    provider = ProviderRegistry.get_provider("osm_standard")
    canvas.set_online_basemap(provider)

    assert canvas._scale_overlay is not None
    canvas.update_scale_indicator()

    assert canvas._scale_overlay.isVisible() is True
    assert len(canvas._scale_overlay.text()) > 0
    assert canvas._scale_overlay.distance_m > 0.0
    canvas.close()


def test_48_coordinate_grid_renders_over_online_tiles(qapp):
    """49. Линии и подписи координатной сетки корректно отображаются поверх онлайн-тайлов."""
    canvas = MapCanvas()
    canvas.resize(800, 600)
    canvas.show()

    provider = ProviderRegistry.get_provider("osm_standard")
    canvas.set_online_basemap(provider)
    canvas.set_coordinate_grid_visible(True)

    # Принудительно вызываем отрисовку сетки
    canvas._render_coordinate_grid()

    assert canvas._grid_item_group is not None
    assert canvas._grid_item_group.zValue() == 80.0
    assert len(canvas._grid_item_group.childItems()) > 0
    canvas.close()


def test_49_measurements_work_over_online_tiles(qapp):
    """50. Инструменты измерений (расстояние и площадь) корректно работают на онлайн-карте."""
    canvas = MapCanvas()
    canvas.resize(800, 600)
    canvas.show()

    provider = ProviderRegistry.get_provider("osm_standard")
    canvas.set_online_basemap(provider)

    # Включаем инструмент измерения расстояния
    canvas.start_measurement("measure_distance")
    assert canvas.interaction_mode == "measure_distance"

    # Добавляем две точки в координатах Web Mercator
    canvas._measure_points = [(4180000.0, 7500000.0), (4190000.0, 7510000.0)]
    canvas._finish_measurement()

    assert canvas.has_measurements() is True
    assert len(canvas._measure_completed_items) > 0
    # Z-order измерений должен быть выше тайлов (> 100)
    for it in canvas._measure_completed_items:
        assert it.zValue() >= 115.0
    canvas.close()
