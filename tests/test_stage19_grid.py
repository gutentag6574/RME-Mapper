"""Тесты Этапа 19: Координатная сетка (Coordinate Grid) (Tests 43-59)."""

import math
import os
from pathlib import Path
import numpy as np
import pytest
import rasterio
from rasterio.transform import Affine, from_origin
from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtWidgets import QApplication

from rme_mapper.maps.map_canvas import MapCanvas
from rme_mapper.services.app_settings_service import AppSettingsService
from rme_mapper.services.grid_calculator import (
    GEOGRAPHIC_STEPS,
    PROJECTED_STEPS,
    GridCalculator,
    MAX_GRID_LINES_SAFETY_LIMIT,
)
from rme_mapper.ui.main_window import MainWindow


@pytest.fixture(scope="session")
def qapp():
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    yield app


@pytest.fixture
def default_gpkg():
    return Path(__file__).resolve().parent.parent / "maps" / "test_map" / "prepared" / "mari.gpkg"


@pytest.fixture
def geotiff_utm(tmp_path: Path) -> Path:
    """Временный GeoTIFF в проекции UTM (EPSG:32637)."""
    file_path = tmp_path / "test_utm.tif"
    w, h = 100, 80
    data = np.full((h, w), 128, dtype=np.uint8)
    transform = from_origin(500000.0, 6000000.0, 10.0, 10.0)
    with rasterio.open(
        file_path, "w", driver="GTiff", height=h, width=w, count=1, dtype=np.uint8, crs="EPSG:32637", transform=transform
    ) as dst:
        dst.write(data, 1)
    return file_path


@pytest.fixture
def geotiff_rotated(tmp_path: Path) -> Path:
    """Повернутый GeoTIFF."""
    file_path = tmp_path / "test_rotated.tif"
    w, h = 60, 40
    data = np.full((h, w), 180, dtype=np.uint8)
    angle = math.radians(20)
    res = 5.0
    t = Affine(res * math.cos(angle), -res * math.sin(angle), 500000.0,
               res * math.sin(angle), res * math.cos(angle), 6000000.0)
    with rasterio.open(
        file_path, "w", driver="GTiff", height=h, width=w, count=1, dtype=np.uint8, crs="EPSG:32637", transform=t
    ) as dst:
        dst.write(data, 1)
    return file_path


def test_43_grid_group_z_value(qapp, default_gpkg):
    """Тест 43: Группа элементов сетки имеет фиксированный Z-index 80.0."""
    canvas = MapCanvas()
    canvas.set_coordinate_grid_visible(True)
    canvas._boundary_bounds = QRectF(46.0, -57.0, 3.0, 2.0)
    canvas.setSceneRect(QRectF(46.0, -57.0, 3.0, 2.0))
    canvas.resize(800, 600)
    canvas.show()

    canvas._render_coordinate_grid()
    assert canvas._grid_item_group is not None
    assert canvas._grid_item_group.zValue() == 80.0


def test_44_coordinate_grid_default_off(qapp):
    """Тест 44: Координатная сетка по умолчанию выключена (OFF)."""
    canvas = MapCanvas()
    assert canvas.show_coordinate_grid is False
    assert canvas._grid_item_group is None


def test_45_view_menu_toggle_grid(qapp, default_gpkg):
    """Тест 45: Переключение сетки через меню Вид."""
    AppSettingsService().set_show_coordinate_grid(False)
    window = MainWindow()
    window.load_map(default_gpkg)
    window.resize(1000, 700)
    window.show()

    assert window.toggle_grid_action.isChecked() is False
    assert window.map_canvas._grid_item_group is None

    # Включаем
    window.toggle_grid_action.trigger()
    assert window.toggle_grid_action.isChecked() is True
    assert window.map_canvas.show_coordinate_grid is True
    assert window.map_canvas._grid_item_group is not None

    # Выключаем
    window.toggle_grid_action.trigger()
    assert window.toggle_grid_action.isChecked() is False
    assert window.map_canvas._grid_item_group is None

    window.close()


def test_46_grid_settings_persistence(qapp):
    """Тест 46: Настройка видимости сетки сохраняется в AppSettingsService."""
    settings = AppSettingsService()
    orig = settings.get_show_coordinate_grid()

    try:
        settings.set_show_coordinate_grid(True)
        assert settings.get_show_coordinate_grid() is True

        settings.set_show_coordinate_grid(False)
        assert settings.get_show_coordinate_grid() is False
    finally:
        settings.set_show_coordinate_grid(orig)


def test_47_geographic_crs_grid_calculation():
    """Тест 47: Расчет линий сетки для географической CRS (OGC:CRS84 / EPSG:4326)."""
    extent = (47.0, 56.0, 48.0, 57.0)
    res = GridCalculator.calculate_grid(extent, "OGC:CRS84")
    assert res is not None
    assert res.is_geographic is True
    assert len(res.vertical_lines) >= 4
    assert len(res.horizontal_lines) >= 4
    for vl in res.vertical_lines:
        assert 47.0 - 1e-5 <= vl.coord <= 48.0 + 1e-5
        assert "° E" in vl.label or "°" in vl.label


def test_48_geographic_dd_labels_formatting():
    """Тест 48: Форматирование подписей географических координат в формате DD с полусферой."""
    lbl_lat_n = GridCalculator.format_geographic_label(56.5, is_lon=False, step=0.5)
    assert lbl_lat_n == "56.5° N"

    lbl_lat_s = GridCalculator.format_geographic_label(-23.45, is_lon=False, step=0.01)
    assert lbl_lat_s == "23.45° S"

    lbl_lon_e = GridCalculator.format_geographic_label(47.0, is_lon=True, step=1.0)
    assert lbl_lon_e == "47° E"

    lbl_lon_w = GridCalculator.format_geographic_label(-122.33, is_lon=True, step=0.01)
    assert lbl_lon_w == "122.33° W"


def test_49_projected_crs_grid_calculation():
    """Тест 49: Расчет сетки для спроецированной CRS в метрах (EPSG:32637)."""
    extent = (500000.0, 6000000.0, 510000.0, 6010000.0)
    res = GridCalculator.calculate_grid(extent, "EPSG:32637")
    assert res is not None
    assert res.is_geographic is False
    assert len(res.vertical_lines) >= 4
    assert len(res.horizontal_lines) >= 4
    for vl in res.vertical_lines:
        assert 500000.0 <= vl.coord <= 510000.0


def test_50_projected_meter_labels_formatting():
    """Тест 50: Форматирование подписей координат спроецированной сетки в метрах."""
    assert GridCalculator.format_projected_label(500000.0, 1000.0) == "500000"
    assert GridCalculator.format_projected_label(6000500.0, 500.0) == "6000500"
    assert GridCalculator.format_projected_label(12.5, 0.5) == "12.5"


def test_51_adaptive_step_selection():
    """Тест 51: Адаптивный подбор шага дает от 4 до 12 линий на охват."""
    # Охват 10 градусов
    step_geo = GridCalculator.choose_step(10.0, GEOGRAPHIC_STEPS)
    lines_geo = 10.0 / step_geo
    assert 4 <= lines_geo <= 12

    # Охват 50 000 метров
    step_proj = GridCalculator.choose_step(50000.0, PROJECTED_STEPS)
    lines_proj = 50000.0 / step_proj
    assert 4 <= lines_proj <= 12


def test_52_safety_limit_lines_count():
    """Тест 52: Предохранитель ограничивает количество линий сетки не более 30."""
    res = GridCalculator.calculate_grid((0.0, 0.0, 180.0, 90.0), "OGC:CRS84")
    assert res is not None
    assert len(res.vertical_lines) <= MAX_GRID_LINES_SAFETY_LIMIT
    assert len(res.horizontal_lines) <= MAX_GRID_LINES_SAFETY_LIMIT


def test_53_grid_updates_on_zoom(qapp, default_gpkg):
    """Тест 53: При приближении карты шаг сетки автоматически мельчает."""
    canvas = MapCanvas()
    canvas.load_geodataframe = lambda *args: None
    canvas._boundary_bounds = QRectF(46.0, -57.0, 3.0, 2.0)
    canvas.set_active_crs("OGC:CRS84")
    canvas.set_coordinate_grid_visible(True)
    canvas.resize(800, 600)
    canvas.show()

    canvas._render_coordinate_grid()
    assert canvas._grid_item_group is not None

    initial_lines_count = len(canvas._grid_item_group.childItems())

    # Масштабируем холст в 10 раз
    canvas.scale(10.0, 10.0)
    canvas._render_coordinate_grid()

    # Сетка перерисовалась с новым адаптивным шагом
    assert canvas._grid_item_group is not None
    assert len(canvas._grid_item_group.childItems()) > 0


def test_54_grid_updates_on_pan(qapp, default_gpkg):
    """Тест 54: При панорамировании карты линии сетки сдвигаются в соответствии с новым окном."""
    canvas = MapCanvas()
    canvas._boundary_bounds = QRectF(46.0, -57.0, 5.0, 5.0)
    canvas.setSceneRect(QRectF(46.0, -57.0, 5.0, 5.0))
    canvas.set_active_crs("OGC:CRS84")
    canvas.set_coordinate_grid_visible(True)
    canvas.resize(800, 600)
    canvas.show()

    canvas.centerOn(47.0, -55.0)
    canvas._render_coordinate_grid()
    assert canvas._grid_item_group is not None
    count1 = len(canvas._grid_item_group.childItems())

    canvas.centerOn(49.0, -56.0)
    canvas._render_coordinate_grid()
    assert canvas._grid_item_group is not None
    assert len(canvas._grid_item_group.childItems()) > 0


def test_55_grid_rendering_on_geopackage(qapp, default_gpkg):
    """Тест 55: Отрисовка сетки поверх векторной карты GeoPackage."""
    window = MainWindow()
    window.load_map(default_gpkg)
    window.resize(1000, 700)
    window.show()

    window.toggle_grid_action.setChecked(True)
    assert window.map_canvas._grid_item_group is not None
    assert window.map_canvas._grid_item_group.zValue() == 80.0

    window.close()


def test_56_grid_rendering_on_geotiff(qapp, geotiff_utm):
    """Тест 56: Отрисовка сетки поверх растровой подложки GeoTIFF."""
    window = MainWindow()
    window.load_map(geotiff_utm)
    window.resize(1000, 700)
    window.show()

    window.toggle_grid_action.setChecked(True)
    assert window.map_canvas._grid_item_group is not None
    assert window.map_canvas._grid_item_group.zValue() == 80.0

    window.close()


def test_57_grid_rendering_on_rotated_geotiff(qapp, geotiff_rotated):
    """Тест 57: Отрисовка координатной сетки поверх повернутого GeoTIFF."""
    window = MainWindow()
    window.load_map(geotiff_rotated)
    window.resize(1000, 700)
    window.show()

    window.toggle_grid_action.setChecked(True)
    assert window.map_canvas._grid_item_group is not None
    assert len(window.map_canvas._grid_item_group.childItems()) > 0

    window.close()


def test_58_non_meter_projected_crs_handled_safely():
    """Тест 58: Проекция с неметровыми единицами (футы) безопасно отключает сетку."""
    # US Survey Feet (EPSG:2227 и EPSG:2263)
    res_2227 = GridCalculator.calculate_grid((100000.0, 100000.0, 200000.0, 200000.0), "EPSG:2227")
    res_2263 = GridCalculator.calculate_grid((900000.0, 100000.0, 1000000.0, 200000.0), "EPSG:2263")
    res_unknown = GridCalculator.calculate_grid((100.0, 100.0, 200.0, 200.0), "EPSG:999999")

    # Сетка должна быть безопасно отключена (None) без притворства метрами
    assert res_2227 is None
    assert res_2263 is None
    assert res_unknown is None


def test_59_map_unload_clears_grid(qapp, default_gpkg):
    """Тест 59: При выгрузке карты элементы координатной сетки удаляются со сцены."""
    window = MainWindow()
    window.load_map(default_gpkg)
    window.resize(1000, 700)
    window.show()

    window.toggle_grid_action.setChecked(True)
    assert window.map_canvas._grid_item_group is not None

    # Закрываем карту
    window.close_map(prompt=False)
    assert window.map_canvas._grid_item_group is None

    window.close()
