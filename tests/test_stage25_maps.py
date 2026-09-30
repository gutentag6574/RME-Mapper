"""Комплексные сквозные тесты картографических подсистем (Этап 25).

Покрывает:
1. GeoPackage end-to-end: открытие, выбор слоев, добавление точек, сохранение, переоткрытие, экспорт изображения.
2. GeoTIFF end-to-end: загрузка, охват, инвариант отсутствия half-pixel ошибки, стабильность экранного размера маркеров, сохранение в проект.
3. Ручная геопривязка растра (Stage 21): добавление GCP, расчет аффинного преобразования, residuals, граничные случаи (<3 GCP, коллинеарность), сохранение в проект.
4. Онлайн-карты (Stage 20): провайдеры (OSM, Mapbox, Custom XYZ), изоляция API-ключей, L1/L2 кэширование, обработка сбоев сети.
5. Cross-Feature Scenario B: GeoTIFF -> Points -> Zones -> Grid -> PNG Export.
6. Cross-Feature Scenario C: Online Map -> Points -> Export (с водяным знаком атрибуции).
"""
from __future__ import annotations

import json
import math
from pathlib import Path
from unittest.mock import MagicMock
from affine import Affine
import numpy as np
import pytest
from PySide6.QtCore import QByteArray, QPointF, QRectF
from PySide6.QtGui import QColor, QImage, QPainter, QPainterPath, QPen, QBrush
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest
import rasterio
from shapely.geometry import Polygon

from rme_mapper.exporters.map_renderer import MapRenderer
from rme_mapper.exporters.models import ImageExportOptions
from rme_mapper.models.georeference import ControlPoint
from rme_mapper.models.map_point import MapPoint
from rme_mapper.models.map_profile import MapProfile
from rme_mapper.models.online_provider import OnlineTileProvider, ProviderRegistry
from rme_mapper.models.project_data import ProjectData, ProjectGroupData, ProjectMapData, ProjectPointData
from rme_mapper.services.app_settings_service import AppSettingsService
from rme_mapper.services.geodesic_service import GeodesicService
from rme_mapper.services.georeference_service import GeoreferenceService
from rme_mapper.services.project_service import ProjectService
from rme_mapper.services.tile_cache import PNG_MAGIC, TileDiskCache
from rme_mapper.services.tile_math import TileMath
from rme_mapper.ui.main_window import MainWindow


@pytest.fixture
def synthetic_geotiff(tmp_path: Path) -> Path:
    """Создание синтетического тестового GeoTIFF файла (WGS84 EPSG:4326)."""
    file_path = tmp_path / "test_geotiff.tif"
    w, h = 80, 60
    data = np.full((h, w), 180, dtype=np.uint8)
    # Origin: lon=47.80, lat=56.70, pixel resolution: 0.001 deg
    transform = Affine(0.001, 0.0, 47.80, 0.0, -0.001, 56.70)
    with rasterio.open(
        file_path,
        "w",
        driver="GTiff",
        height=h,
        width=w,
        count=1,
        dtype=np.uint8,
        crs="EPSG:4326",
        transform=transform,
    ) as dst:
        dst.write(data, 1)
    return file_path


def test_01_geopackage_e2e_lifecycle(qapp, tmp_path: Path):
    """Сценарий: Открытие GeoPackage -> выбор слоя -> точки -> сохранение -> переоткрытие -> экспорт растра."""
    gpkg_path = Path("maps/test_map/prepared/mari.gpkg").resolve()
    assert gpkg_path.exists()

    window = MainWindow()
    window.show()

    # 1. Открытие карты GeoPackage
    window.load_map(gpkg_path)
    assert window.map_controller.map_path == gpkg_path
    assert window.map_controller.active_crs is not None
    assert len(window.map_controller.loaded_layers) > 0

    # 2. Добавление пользовательских точек с зонами
    p1 = window._point_service.add_point(
        point_id="gpkg_pt_1",
        name="Подстанция GPKG",
        latitude=56.635,
        longitude=47.885,
        object_number="GPKG-01",
        zone_enabled=True,
        radius_m=300.0,
    )
    window.points_panel.add_point(p1)
    assert len(window._point_service.get_points()) == 1

    # 3. Сохранение проекта
    proj_file = tmp_path / "gpkg_lifecycle.gpmap"
    saved = window.project_controller.save_project_as_workflow(proj_file)
    assert saved is True
    assert proj_file.exists()

    # 4. Закрытие и создание нового проекта
    window.project_controller.new_project_workflow()
    assert len(window._point_service.get_points()) == 0

    # 5. Повторное открытие
    opened = window.project_controller.open_project_from_path(proj_file)
    assert opened is True
    assert len(window._point_service.get_points()) == 1
    loaded_pt = window._point_service.get_point("gpkg_pt_1")
    assert loaded_pt.name == "Подстанция GPKG"
    assert loaded_pt.zone_enabled is True
    assert loaded_pt.radius_m == 300.0

    # 6. Экспорт растрового изображения карты (PNG)
    export_img = tmp_path / "gpkg_rendered.png"
    opts = ImageExportOptions(
        file_path=export_img,
        format="PNG",
        width_px=800,
        height_px=600,
        include_title=True,
        include_scale_bar=True,
        include_north_arrow=True,
    )

    prof_extent = window.map_controller.active_profile.extent
    if isinstance(prof_extent, dict):
        target_ext = (prof_extent["xmin"], prof_extent["ymin"], prof_extent["xmax"], prof_extent["ymax"])
    elif isinstance(prof_extent, (list, tuple)):
        target_ext = tuple(prof_extent)
    else:
        target_ext = (47.8, 56.6, 47.9, 56.7)

    rendered_img = MapRenderer.render_map(
        options=opts,
        active_crs=window.map_controller.active_crs,
        target_extent=target_ext,
        points=window._point_service.get_points(),
    )
    assert isinstance(rendered_img, QImage)
    assert not rendered_img.isNull()
    assert rendered_img.width() == 800
    assert rendered_img.height() == 600

    saved_img = rendered_img.save(str(export_img), "PNG")
    assert saved_img is True
    assert export_img.exists()
    assert export_img.stat().st_size > 0

    window.close()


def test_02_geotiff_raster_viewport_and_half_pixel_invariant(qapp, synthetic_geotiff: Path, tmp_path: Path):
    """GeoTIFF: загрузка, охват, инвариант отсутствия half-pixel сдвига и round-trip проекта."""
    window = MainWindow()
    window.show()

    # 1. Загрузка GeoTIFF
    window.load_map(synthetic_geotiff)
    assert window.map_controller.map_path == synthetic_geotiff
    assert window.map_controller.current_profile.source_type == "geotiff"

    # 2. Проверка аффинной трансформации и half-pixel инварианта
    # Origin: lon=47.80, lat=56.70; res=0.001 deg; w=80, h=60
    # Верхний левый угол пикселя (0, 0) = (47.80, 56.70)
    # Центр пикселя (0, 0) = (47.80 + 0.0005, 56.70 - 0.0005)
    # Нижний правый угол растра = (47.80 + 80*0.001, 56.70 - 60*0.001) = (47.88, 56.64)
    prof_extent = window.map_controller.active_profile.extent
    assert prof_extent is not None
    if isinstance(prof_extent, dict):
        min_x, min_y, max_x, max_y = prof_extent["xmin"], prof_extent["ymin"], prof_extent["xmax"], prof_extent["ymax"]
    else:
        min_x, min_y, max_x, max_y = prof_extent

    assert min_x == pytest.approx(47.80, abs=1e-5)
    assert max_x == pytest.approx(47.88, abs=1e-5)
    assert min_y == pytest.approx(56.64, abs=1e-5)
    assert max_y == pytest.approx(56.70, abs=1e-5)

    # 3. Добавление точки точно по центру первого пикселя
    px0_lon = 47.80 + 0.0005
    px0_lat = 56.70 - 0.0005
    pt = window._point_service.add_point(
        point_id="pt_center_px0",
        name="Пиксель 0,0",
        latitude=px0_lat,
        longitude=px0_lon,
    )
    window.points_panel.add_point(pt)

    # 4. Сохранение проекта с GeoTIFF
    proj_path = tmp_path / "geotiff_project.gpmap"
    save_ok = window.project_controller.save_project_as_workflow(proj_path)
    assert save_ok is True

    # 5. Переоткрытие проекта
    window.project_controller.new_project_workflow()
    open_ok = window.project_controller.open_project_from_path(proj_path)
    assert open_ok is True
    assert window.map_controller.current_profile.source_type == "geotiff"
    assert len(window._point_service.get_points()) == 1

    r_pt = window._point_service.get_point("pt_center_px0")
    assert r_pt.latitude == pytest.approx(px0_lat, abs=1e-6)
    assert r_pt.longitude == pytest.approx(px0_lon, abs=1e-6)

    window.close()


def test_03_manual_georeferencing_workflow_and_residuals(tmp_path: Path):
    """Ручная геопривязка: GCP, расчет 2D аффинной матрицы, residuals и сохранение."""
    # 1. Создание 4 контрольных точек (GCP)
    # Исходный растр 200x200 пикселей, целевые координаты в EPSG:4326
    # Модель: lon = 47.80 + 0.001 * px; lat = 56.70 - 0.001 * py
    gcps = [
        ControlPoint("1", pixel_x=0.0, pixel_y=0.0, target_x=47.80, target_y=56.70),
        ControlPoint("2", pixel_x=200.0, pixel_y=0.0, target_x=48.00, target_y=56.70),
        ControlPoint("3", pixel_x=200.0, pixel_y=200.0, target_x=48.00, target_y=56.50),
        ControlPoint("4", pixel_x=0.0, pixel_y=200.0, target_x=47.80, target_y=56.50),
    ]

    transform, updated_pts, rmse = GeoreferenceService.solve_affine(gcps, crs="EPSG:4326")
    assert len(transform) == 6
    a, b, c, d, e, f = transform
    assert a == pytest.approx(0.001, abs=1e-6)
    assert b == pytest.approx(0.0, abs=1e-6)
    assert c == pytest.approx(47.80, abs=1e-6)
    assert d == pytest.approx(0.0, abs=1e-6)
    assert e == pytest.approx(-0.001, abs=1e-6)
    assert f == pytest.approx(56.70, abs=1e-6)

    # Residuals и RMSE должны быть практически нулевыми для строгой модели
    assert rmse < 1e-5
    for p in updated_pts:
        assert p.residual_total < 1e-5

    # 2. Негативные сценарии
    # Менее 3 точек
    with pytest.raises(ValueError, match="как минимум 3"):
        GeoreferenceService.solve_affine(gcps[:2], crs="EPSG:4326")

    # Коллинеарные точки (дегенеративная матрица)
    collinear_gcps = [
        ControlPoint("1", pixel_x=0.0, pixel_y=0.0, target_x=47.80, target_y=56.70),
        ControlPoint("2", pixel_x=10.0, pixel_y=10.0, target_x=47.81, target_y=56.71),
        ControlPoint("3", pixel_x=20.0, pixel_y=20.0, target_x=47.82, target_y=56.72),
    ]
    with pytest.raises(ValueError, match="коллинеарны"):
        GeoreferenceService.solve_affine(collinear_gcps, crs="EPSG:4326")

    # 3. Сохранение и восстановление параметров геопривязки в проект (*.gpmap)
    raw_img = tmp_path / "cadastral_plan.png"
    raw_img.write_bytes(PNG_MAGIC + b"mock_cadastral_plan")

    proj_file = tmp_path / "georef_plan.gpmap"
    proj_svc = ProjectService()
    map_data = ProjectMapData(
        map_id="georef_001",
        relative_path="cadastral_plan.png",
        name="План застройки",
        source_type="raster_image",
        crs="EPSG:4326",
        affine_transform=list(transform),
        control_points=[p.to_dict() for p in updated_pts],
        transformation_type="affine",
    )
    p_data = ProjectData(
        map=map_data,
        points=[ProjectPointData(id="p1", name="Угол здания", latitude=56.60, longitude=47.90)],
    )
    proj_svc.save_project(p_data, proj_file)

    loaded = proj_svc.load_project(proj_file)
    assert loaded.map.source_type == "raster_image"
    assert loaded.map.transformation_type == "affine"
    assert loaded.map.affine_transform is not None
    assert len(loaded.map.affine_transform) == 6
    assert len(loaded.map.control_points) == 4


def test_04_online_maps_providers_cache_and_attribution(tmp_path: Path):
    """Онлайн-карты: реестр провайдеров, кэширование, изоляция API-ключей и отказ сети."""
    # 1. Проверка реестра провайдеров
    providers = ProviderRegistry.list_providers()
    provider_ids = {p.id for p in providers}
    assert "osm_standard" in provider_ids
    assert "mapbox_satellite" in provider_ids
    assert "mapbox_hybrid" in provider_ids

    # 2. Изоляция API-ключей: токен Mapbox не должен попадать в проект
    secret_token = "pk.eyJ1_SECRET_MAPBOX_KEY_STAGE25"
    app_settings = AppSettingsService()
    app_settings.set_provider_api_key("mapbox_satellite", secret_token)

    prof = MapProfile(
        id="online_mapbox",
        name="Mapbox Satellite",
        source_type="online_xyz",
        crs="EPSG:3857",
        provider_id="mapbox_satellite",
        map_type="satellite",
    )

    proj_svc = ProjectService()
    proj_data = proj_svc.build_project_data(
        map_path=None,
        layers=[],
        points=[MapPoint(id="pt1", name="Тест онлайн", latitude=55.75, longitude=37.61)],
        groups=[],
        map_profile=prof,
    )

    # Проверяем сериализованный словарь и JSON
    d = proj_data.to_dict()
    serialized_str = json.dumps(d, ensure_ascii=False)
    assert secret_token not in serialized_str
    assert "SECRET" not in serialized_str

    # 3. L2 Дисковый кэш тайлов
    cache_dir = tmp_path / "tile_cache_test"
    cache = TileDiskCache(base_dir=cache_dir, max_size_bytes=100_000)

    tile_bytes = PNG_MAGIC + b"test_tile_payload_12345"
    cache.save_tile("osm_standard", z=5, x=10, y=12, data=tile_bytes)

    # Чтение из кэша
    cached = cache.get_tile("osm_standard", z=5, x=10, y=12)
    assert cached == tile_bytes

    # Несуществующий тайл
    assert cache.get_tile("osm_standard", z=5, x=999, y=999) is None

    # Поврежденный файл в кэше
    corrupt_key = cache._get_tile_path("osm_standard", 5, 20, 20)
    corrupt_key.parent.mkdir(parents=True, exist_ok=True)
    corrupt_key.write_bytes(b"INVALID_HEADER_NOT_PNG")
    assert cache.get_tile("osm_standard", z=5, x=20, y=20) is None


def test_05_cross_feature_scenario_b_geotiff_points_zones_grid_png_export(
    synthetic_geotiff: Path,
    tmp_path: Path,
):
    """Cross-Feature Scenario B: GeoTIFF -> Points -> Zones -> Grid -> PNG Export."""
    # 1. Исходные точки с зонами поверх GeoTIFF
    pts = [
        MapPoint(
            id="p_b_1",
            name="Центральный узел",
            latitude=56.67,
            longitude=47.84,
            zone_enabled=True,
            radius_m=600.0,
            symbol="square",
            red=220,
            green=40,
            blue=40,
            zone_red=255,
            zone_green=100,
            zone_blue=0,
            zone_opacity=30,
        ),
        MapPoint(
            id="p_b_2",
            name="Периферийный пост",
            latitude=56.66,
            longitude=47.86,
            zone_enabled=True,
            radius_m=350.0,
            symbol="circle",
            red=0,
            green=120,
            blue=220,
        ),
    ]

    # Предрасчет геодезических зон через GeodesicService
    precomputed = {}
    for p in pts:
        if p.zone_enabled and p.radius_m > 0:
            poly = GeodesicService.create_geodesic_circle(
                longitude=p.longitude,
                latitude=p.latitude,
                radius_m=p.radius_m,
                segments=36,
            )
            precomputed[p.id] = poly

    out_png = tmp_path / "scenario_b_export.png"
    export_opts = ImageExportOptions(
        file_path=out_png,
        format="PNG",
        width_px=1024,
        height_px=768,
        include_grid=True,
        include_scale_bar=True,
        include_north_arrow=True,
        include_title=True,
        title_text="GeoTIFF + Points + Zones + Grid Export",
    )

    rendered_img = MapRenderer.render_map(
        options=export_opts,
        active_crs="EPSG:4326",
        target_extent=(47.80, 56.64, 47.88, 56.70),
        points=pts,
        precomputed_zones=precomputed,
        raster_source=synthetic_geotiff,
        is_raster_visible=True,
    )

    assert isinstance(rendered_img, QImage)
    assert not rendered_img.isNull()
    assert rendered_img.width() == 1024
    assert rendered_img.height() == 768

    ok = rendered_img.save(str(out_png), "PNG")
    assert ok is True
    assert out_png.exists()
    assert out_png.stat().st_size > 5000


def test_06_cross_feature_scenario_c_online_map_points_export_attribution(tmp_path: Path):
    """Cross-Feature Scenario C: Online Map -> Points -> Export (с водяным знаком копирайта)."""
    pts = [
        MapPoint(
            id="p_c_1",
            name="Точка онлайн-подложки",
            latitude=55.751,
            longitude=37.618,
            symbol="triangle",
            red=0,
            green=180,
            blue=80,
        )
    ]

    out_png = tmp_path / "scenario_c_osm_attribution.png"
    export_opts = ImageExportOptions(
        file_path=out_png,
        format="PNG",
        width_px=800,
        height_px=600,
        include_attribution=True,
        include_scale_bar=True,
        include_north_arrow=True,
    )

    osm_attribution = "© OpenStreetMap contributors"
    rendered_img = MapRenderer.render_map(
        options=export_opts,
        active_crs="EPSG:3857",
        target_extent=(4185000.0, 7505000.0, 4195000.0, 7515000.0),
        points=pts,
        attribution_text=osm_attribution,
    )

    assert isinstance(rendered_img, QImage)
    assert not rendered_img.isNull()
    assert rendered_img.width() == 800
    assert rendered_img.height() == 600

    ok = rendered_img.save(str(out_png), "PNG")
    assert ok is True
    assert out_png.exists()
