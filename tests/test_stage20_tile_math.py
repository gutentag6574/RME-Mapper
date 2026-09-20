"""Тесты математики Web Mercator и тайлов XYZ (Этап 20: Tests 1-8)."""

import math
import pytest
from PySide6.QtCore import QRectF

from rme_mapper.services.tile_math import (
    TileMath,
    MAX_MERCATOR_EXTENT,
    MAX_LATITUDE,
    MIN_LATITUDE,
)


def test_01_greenwich_equator_coordinates():
    """Тест 1: Координаты (0, 0) в Web Mercator строго равны (0, 0)."""
    mx, my = TileMath.lonlat_to_mercator(0.0, 0.0)
    assert abs(mx) < 1e-6
    assert abs(my) < 1e-6

    lon, lat = TileMath.mercator_to_lonlat(0.0, 0.0)
    assert abs(lon) < 1e-6
    assert abs(lat) < 1e-6


def test_02_zoom_zero_world_bounds():
    """Тест 2: На зуме 0 существует единственный тайл (0, 0), покрывающий весь мир."""
    tx, ty = TileMath.mercator_to_tile(0.0, 0.0, 0)
    assert tx == 0 and ty == 0

    bounds = TileMath.tile_to_mercator_bounds(0, 0, 0)
    assert abs(bounds[0] - (-MAX_MERCATOR_EXTENT)) < 1e-3
    assert abs(bounds[1] - (-MAX_MERCATOR_EXTENT)) < 1e-3
    assert abs(bounds[2] - MAX_MERCATOR_EXTENT) < 1e-3
    assert abs(bounds[3] - MAX_MERCATOR_EXTENT) < 1e-3

    rect = TileMath.tile_to_scene_rect(0, 0, 0)
    assert isinstance(rect, QRectF)
    assert rect.x() == bounds[0]
    assert rect.y() == -bounds[3]
    assert rect.width() == (bounds[2] - bounds[0])
    assert rect.height() == (bounds[3] - bounds[1])


def test_03_latitude_clamping_limits():
    """Тест 3: Широты за пределами ±85.0511° безопасно ограничиваются без math error."""
    # Положительный полюс
    mx, my = TileMath.lonlat_to_mercator(0.0, 90.0)
    assert abs(my - MAX_MERCATOR_EXTENT) < 1.0

    # Отрицательный полюс
    mx_s, my_s = TileMath.lonlat_to_mercator(0.0, -90.0)
    assert abs(my_s - (-MAX_MERCATOR_EXTENT)) < 1.0

    # Обратное преобразование
    _, lat_n = TileMath.mercator_to_lonlat(0.0, MAX_MERCATOR_EXTENT)
    assert abs(lat_n - MAX_LATITUDE) < 1e-4

    _, lat_s = TileMath.mercator_to_lonlat(0.0, -MAX_MERCATOR_EXTENT)
    assert abs(lat_s - MIN_LATITUDE) < 1e-4


def test_04_antimeridian_180_degrees():
    """Тест 4: Координаты на антимеридиане (±180°) корректно переводятся в максимальный охват."""
    mx_e, _ = TileMath.lonlat_to_mercator(180.0, 0.0)
    assert abs(mx_e - MAX_MERCATOR_EXTENT) < 1e-3

    mx_w, _ = TileMath.lonlat_to_mercator(-180.0, 0.0)
    assert abs(mx_w - (-MAX_MERCATOR_EXTENT)) < 1e-3

    # Нормализация экстремальных долгот
    assert abs(TileMath.normalize_longitude(190.0) - (-170.0)) < 1e-6
    assert abs(TileMath.normalize_longitude(-190.0) - 170.0) < 1e-6


def test_05_roundtrip_coordinate_precision():
    """Тест 5: Прямое и обратное преобразование сохраняет точность до долей миллиметра."""
    test_points = [
        (37.6173, 55.7558),   # Москва
        (30.3351, 59.9343),   # СПб
        (47.8900, 56.6300),   # Йошкар-Ола
        (-74.0060, 40.7128),  # Нью-Йорк
        (139.6917, 35.6895),  # Токио
        (151.2093, -33.8688), # Сидней
    ]
    for lon, lat in test_points:
        mx, my = TileMath.lonlat_to_mercator(lon, lat)
        rlon, rlat = TileMath.mercator_to_lonlat(mx, my)
        assert abs(rlon - lon) < 1e-7, f"Lon mismatch for {lon}, {lat}"
        assert abs(rlat - lat) < 1e-7, f"Lat mismatch for {lon}, {lat}"


def test_06_tile_indices_at_zoom_levels():
    """Тест 6: Вычисление индексов тайлов на разных уровнях зума."""
    # Москва: 37.6173° E, 55.7558° N
    # На зуме 1 (2x2) Москва в квадранте (1, 0)
    tx, ty = TileMath.lonlat_to_tile(37.6173, 55.7558, 1)
    assert tx == 1 and ty == 0

    # На зуме 10:
    tx_10, ty_10 = TileMath.lonlat_to_tile(37.6173, 55.7558, 10)
    assert 610 <= tx_10 <= 630
    assert 310 <= ty_10 <= 330


def test_07_extent_to_tile_range_with_margins():
    """Тест 7: Расчет охвата тайлов для заданного экстента с добавлением полей (margin)."""
    # Экстент Марий Эл: ~ 46°..50° E, 56°..57° N
    x1, y1 = TileMath.lonlat_to_mercator(46.0, 56.0)
    x2, y2 = TileMath.lonlat_to_mercator(50.0, 57.0)

    min_tx, min_ty, max_tx, max_ty = TileMath.extent_to_tile_range(x1, y1, x2, y2, z=8, margin=1)
    assert min_tx <= max_tx
    assert min_ty <= max_ty

    count = TileMath.tile_count(min_tx, min_ty, max_tx, max_ty)
    assert count > 0
    # На зуме 8 Марий Эл с каймой в 1 тайл должна укладываться в разумное число (менее 50 тайлов)
    assert count < 50


def test_08_meters_per_pixel_to_zoom():
    """Тест 8: Расчет зума по экранному разрешению."""
    # Весь мир (зум 0): ~156543 м/пикс
    assert TileMath.meters_per_pixel_to_zoom(156543.0) == 0
    # Зум 1: ~78271 м/пикс
    assert TileMath.meters_per_pixel_to_zoom(78271.0) == 1
    # Городской масштаб (1-5 м/пикс) ~ 15-18 зум
    z_city = TileMath.meters_per_pixel_to_zoom(2.0)
    assert 15 <= z_city <= 18
    # Ограничения min_zoom и max_zoom
    assert TileMath.meters_per_pixel_to_zoom(0.01, max_zoom=19) == 19
    assert TileMath.meters_per_pixel_to_zoom(1e9, min_zoom=0) == 0
