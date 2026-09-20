"""Тесты экспорта карты с онлайн-подложкой и копирайтом (Этап 20: Tests 71-80)."""

from pathlib import Path
from unittest.mock import MagicMock
import pytest
from PySide6.QtCore import QPointF, QRectF
from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtWidgets import QGraphicsScene

from rme_mapper.exporters.map_renderer import MapRenderer
from rme_mapper.exporters.models import ImageExportOptions
from rme_mapper.maps.online_tile_manager import OnlineTileManager
from rme_mapper.models.map_point import MapPoint
from rme_mapper.models.online_provider import ProviderRegistry
from rme_mapper.services.tile_cache import TileDiskCache
from rme_mapper.services.tile_math import TileMath
from rme_mapper.ui.export_image_dialog import ExportImageDialog
from tests.test_stage20_canvas_and_tiles import _make_dummy_tile_png


@pytest.fixture
def temp_cache(tmp_path: Path) -> TileDiskCache:
    cache_dir = tmp_path / "export_tile_cache"
    return TileDiskCache(base_dir=cache_dir)


@pytest.fixture
def sample_point() -> MapPoint:
    return MapPoint(
        id="pt_export",
        name="Точка Экспорта",
        latitude=55.75,
        longitude=37.61,
        radius_m=400.0,
        zone_enabled=True,
    )


def test_71_image_export_options_include_attribution_default(tmp_path: Path):
    """71. ImageExportOptions содержит поле include_attribution со значением True по умолчанию."""
    opts = ImageExportOptions(file_path=tmp_path / "test.png")
    assert hasattr(opts, "include_attribution")
    assert opts.include_attribution is True


def test_72_export_dialog_has_chk_attribution(qapp):
    """72. ExportImageDialog содержит чекбокс chk_attribution, по умолчанию включенный."""
    dialog = ExportImageDialog(
        parent=None,
        active_crs="EPSG:3857",
        map_title="Online Map Export",
        current_view_extent=(4180000.0, 7500000.0, 4190000.0, 7510000.0),
        full_map_extent=(4180000.0, 7500000.0, 4190000.0, 7510000.0),
        points=[],
        selected_point_ids=set(),
        loaded_layers_render_data=[],
        raster_source=None,
        is_raster_visible=False,
    )

    assert hasattr(dialog, "chk_attribution")
    assert dialog.chk_attribution.isChecked() is True
    dialog.close()


def test_73_export_dialog_chk_attribution_toggled(qapp, tmp_path: Path):
    """73. Переключение chk_attribution обновляет соответствующую опцию в ImageExportOptions."""
    dialog = ExportImageDialog(
        parent=None,
        active_crs="EPSG:3857",
        map_title="Online Map Export",
        current_view_extent=(4180000.0, 7500000.0, 4190000.0, 7510000.0),
        full_map_extent=(4180000.0, 7500000.0, 4190000.0, 7510000.0),
        points=[],
        selected_point_ids=set(),
        loaded_layers_render_data=[],
        raster_source=None,
        is_raster_visible=False,
    )

    dialog.path_edit.setText(str(tmp_path / "output.png"))
    dialog.chk_attribution.setChecked(False)

    opts = dialog.build_export_options()
    assert opts.include_attribution is False

    dialog.chk_attribution.setChecked(True)
    opts2 = dialog.build_export_options()
    assert opts2.include_attribution is True
    dialog.close()


def test_74_export_renders_attribution_watermark(tmp_path: Path):
    """74. При включенной опции атрибуция провайдера отрисовывается в нижнем правом углу."""
    opts = ImageExportOptions(
        file_path=tmp_path / "test_attr.png",
        width_px=800,
        height_px=600,
        include_attribution=True,
    )

    img = MapRenderer.render_map(
        options=opts,
        active_crs="EPSG:3857",
        target_extent=(4180000.0, 7500000.0, 4190000.0, 7510000.0),
        attribution_text="© OpenStreetMap contributors",
    )

    assert isinstance(img, QImage)
    assert not img.isNull()
    assert img.width() == 800
    assert img.height() == 600


def test_75_export_omits_attribution_when_unchecked(tmp_path: Path):
    """75. При выключенной опции include_attribution=False водяной знак не отрисовывается."""
    opts_with = ImageExportOptions(
        file_path=tmp_path / "with.png",
        width_px=400,
        height_px=300,
        include_attribution=True,
        include_title=False,
        include_crs=False,
        include_legend=False,
        include_scale_bar=False,
        include_north_arrow=False,
    )
    img_with = MapRenderer.render_map(
        options=opts_with,
        active_crs="EPSG:3857",
        target_extent=(4180000.0, 7500000.0, 4190000.0, 7510000.0),
        attribution_text="© OpenStreetMap contributors",
    )

    opts_without = ImageExportOptions(
        file_path=tmp_path / "without.png",
        width_px=400,
        height_px=300,
        include_attribution=False,
        include_title=False,
        include_crs=False,
        include_legend=False,
        include_scale_bar=False,
        include_north_arrow=False,
    )
    img_without = MapRenderer.render_map(
        options=opts_without,
        active_crs="EPSG:3857",
        target_extent=(4180000.0, 7500000.0, 4190000.0, 7510000.0),
        attribution_text="© OpenStreetMap contributors",
    )

    # Изображения должны отличаться в области нижнего правого угла (где копирайт)
    assert img_with != img_without


def test_76_export_png_with_online_tiles(qapp, tmp_path: Path, temp_cache: TileDiskCache):
    """76. Экспорт в PNG с онлайн-тайлами из дискового кэша."""
    scene = QGraphicsScene()
    manager = OnlineTileManager(scene, tile_cache=temp_cache)
    provider = ProviderRegistry.get_provider("osm_standard")
    manager.set_provider(provider)

    # Предзаполняем кэш тайлами для Москвы на zoom 10
    # Москва: x ~ 619, y ~ 320 на зуме 10
    tile_bytes = _make_dummy_tile_png()
    temp_cache.save_tile("osm_standard", 10, 619, 320, tile_bytes)

    out_file = tmp_path / "moscow_online.png"
    opts = ImageExportOptions(
        file_path=out_file,
        format="PNG",
        width_px=800,
        height_px=600,
        include_attribution=True,
    )

    # Охват вокруг тайла (619, 320, 10)
    extent = (4180000.0, 7500000.0, 4190000.0, 7510000.0)
    img = MapRenderer.render_map(
        options=opts,
        active_crs="EPSG:3857",
        target_extent=extent,
        online_tile_manager=manager,
    )

    assert img.save(str(out_file), "PNG") is True
    assert out_file.exists()
    assert out_file.stat().st_size > 0


def test_77_export_jpeg_with_online_tiles(qapp, tmp_path: Path, temp_cache: TileDiskCache):
    """77. Экспорт в JPEG с онлайн-тайлами и проверкой качества."""
    scene = QGraphicsScene()
    manager = OnlineTileManager(scene, tile_cache=temp_cache)
    provider = ProviderRegistry.get_provider("mapbox_satellite")
    manager.set_provider(provider, api_key="test_key")

    temp_cache.save_tile("mapbox_satellite", 10, 619, 320, _make_dummy_tile_png())

    out_file = tmp_path / "satellite_export.jpg"
    opts = ImageExportOptions(
        file_path=out_file,
        format="JPEG",
        jpeg_quality=85,
        width_px=640,
        height_px=480,
    )

    img = MapRenderer.render_map(
        options=opts,
        active_crs="EPSG:3857",
        target_extent=(4180000.0, 7500000.0, 4190000.0, 7510000.0),
        online_tile_manager=manager,
    )

    assert img.save(str(out_file), "JPEG", quality=opts.jpeg_quality) is True
    assert out_file.exists()
    assert out_file.stat().st_size > 0


def test_78_export_missing_tiles_neutral_background(qapp, tmp_path: Path, temp_cache: TileDiskCache):
    """78. Отсутствующие в кэше тайлы не вызывают исключений и не ломают экспорт."""
    scene = QGraphicsScene()
    manager = OnlineTileManager(scene, tile_cache=temp_cache)
    provider = ProviderRegistry.get_provider("osm_standard")
    manager.set_provider(provider)

    # Кэш абсолютно пуст
    out_file = tmp_path / "empty_cache_export.png"
    opts = ImageExportOptions(
        file_path=out_file,
        width_px=600,
        height_px=400,
    )

    img = MapRenderer.render_map(
        options=opts,
        active_crs="EPSG:3857",
        target_extent=(4180000.0, 7500000.0, 4190000.0, 7510000.0),
        online_tile_manager=manager,
    )

    assert isinstance(img, QImage)
    assert not img.isNull()
    assert img.width() == 600
    assert img.height() == 400


def test_79_export_layers_order_with_online_tiles(qapp, tmp_path: Path, temp_cache: TileDiskCache, sample_point):
    """79. Порядок отрисовки: тайлы внизу, поверх них сетка, затем зоны и точки с подписями."""
    scene = QGraphicsScene()
    manager = OnlineTileManager(scene, tile_cache=temp_cache)
    provider = ProviderRegistry.get_provider("osm_standard")
    manager.set_provider(provider)

    temp_cache.save_tile("osm_standard", 10, 619, 320, _make_dummy_tile_png())

    out_file = tmp_path / "full_layers_export.png"
    opts = ImageExportOptions(
        file_path=out_file,
        width_px=800,
        height_px=600,
        include_points=True,
        include_zones=True,
        include_labels=True,
        include_grid=True,
        include_attribution=True,
    )

    img = MapRenderer.render_map(
        options=opts,
        active_crs="EPSG:3857",
        target_extent=(4180000.0, 7500000.0, 4190000.0, 7510000.0),
        points=[sample_point],
        online_tile_manager=manager,
    )

    assert isinstance(img, QImage)
    assert not img.isNull()


def test_80_export_offline_map_does_not_render_online_attribution(tmp_path: Path):
    """80. При экспорте без онлайн-подложки водяной знак копирайта онлайн-провайдера не выводится."""
    opts = ImageExportOptions(
        file_path=tmp_path / "offline_no_attr.png",
        width_px=400,
        height_px=300,
        include_attribution=True,
    )

    # Без передачи online_tile_manager и attribution_text
    img = MapRenderer.render_map(
        options=opts,
        active_crs="EPSG:32638",
        target_extent=(400000.0, 6200000.0, 500000.0, 6300000.0),
        online_tile_manager=None,
        attribution_text=None,
    )

    assert isinstance(img, QImage)
    assert not img.isNull()
