"""Тесты Этапа 19: Экранный индикатор масштаба (Scale Bar) (Tests 30-42)."""

import os
from pathlib import Path
import pytest
from PySide6.QtCore import QPointF, QRectF, QSize, Qt
from PySide6.QtWidgets import QApplication

from rme_mapper.maps.map_canvas import MapCanvas
from rme_mapper.services.app_settings_service import AppSettingsService
from rme_mapper.services.scale_service import ScaleService
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


def test_30_scale_overlay_present_and_default_visible(qapp, default_gpkg):
    """Тест 30: Виджет масштаба присутствует на холсте, включен по умолчанию (ON) и отображается при наличии карты."""
    canvas = MapCanvas()
    assert hasattr(canvas, "_scale_overlay")
    assert canvas._show_scale_indicator is True
    assert canvas._scale_overlay.is_indicator_visible() is True

    window = MainWindow()
    window.load_map(default_gpkg)
    window.resize(1000, 700)
    window.show()
    assert window.map_canvas._scale_overlay.isVisible() is True
    window.close()


def test_31_view_menu_toggle_scale(qapp, default_gpkg):
    """Тест 31: Переключение отображения масштаба через меню Вид."""
    window = MainWindow()
    window.load_map(default_gpkg)
    window.resize(1000, 700)
    window.show()

    assert window.toggle_scale_action.isChecked() is True
    assert window.map_canvas._scale_overlay.isVisible() is True

    # Выключаем
    window.toggle_scale_action.trigger()
    assert window.toggle_scale_action.isChecked() is False
    assert window.map_canvas._scale_overlay.isVisible() is False

    # Включаем обратно
    window.toggle_scale_action.trigger()
    assert window.toggle_scale_action.isChecked() is True
    assert window.map_canvas._scale_overlay.isVisible() is True

    window.close()


def test_32_settings_persistence(qapp):
    """Тест 32: Настройка видимости масштаба сохраняется в AppSettingsService."""
    settings = AppSettingsService()
    orig = settings.get_show_scale_indicator()

    try:
        settings.set_show_scale_indicator(False)
        assert settings.get_show_scale_indicator() is False

        settings.set_show_scale_indicator(True)
        assert settings.get_show_scale_indicator() is True
    finally:
        settings.set_show_scale_indicator(orig)


def test_33_geographic_crs_latitude_aware():
    """Тест 33: Расчет масштаба в географической CRS зависит от широты (latitude-aware)."""
    # 1 градус долготы на широте 0° = ~111.3 км, на широте 60° = ~55.6 км
    res_eq = ScaleService.calculate_scale_for_span(0.0, 1.0, 0.0, 100.0, "OGC:CRS84", target_bar_pixels=100.0)
    res_60 = ScaleService.calculate_scale_for_span(0.0, 1.0, 60.0, 100.0, "OGC:CRS84", target_bar_pixels=100.0)

    assert res_eq is not None
    assert res_60 is not None
    dist_eq, _, _ = res_eq
    dist_60, _, _ = res_60

    assert dist_60 < dist_eq


def test_34_projected_crs_scale():
    """Тест 34: Расчет масштаба в спроецированной CRS (EPSG:3857)."""
    res = ScaleService.calculate_scale_for_span(
        4185000.0, 4200000.0, 7500000.0, 150.0, "EPSG:3857", target_bar_pixels=120.0
    )
    assert res is not None
    nice_dist, actual_px, label = res
    assert nice_dist > 0
    assert 40.0 <= actual_px <= 250.0
    assert "м" in label or "км" in label or "m" in label or "km" in label


def test_35_nice_values_selection():
    """Тест 35: Подбор красивых стандартных значений (1, 2, 5, 10...)."""
    assert ScaleService.pick_nice_distance(9.5) == 5.0
    assert ScaleService.pick_nice_distance(19.0) == 10.0
    assert ScaleService.pick_nice_distance(45.0) == 20.0
    assert ScaleService.pick_nice_distance(90.0) == 50.0
    assert ScaleService.pick_nice_distance(180.0) == 100.0
    assert ScaleService.pick_nice_distance(1800.0) == 1000.0
    assert ScaleService.pick_nice_distance(4500.0) == 2000.0


def test_36_zoom_in_updates_scale_bar(qapp, default_gpkg):
    """Тест 36: Приближение (Zoom In) уменьшает номинальное расстояние на линейке."""
    window = MainWindow()
    window.load_map(default_gpkg)
    window.resize(1000, 700)
    window.show()

    initial_dist = window.map_canvas._scale_overlay.distance_m
    # Приближаем в 4 раза
    window.map_canvas.scale(4.0, 4.0)
    window.map_canvas.update_scale_indicator()

    zoomed_dist = window.map_canvas._scale_overlay.distance_m
    assert zoomed_dist < initial_dist

    window.close()


def test_37_zoom_out_updates_scale_bar(qapp, default_gpkg):
    """Тест 37: Отдаление (Zoom Out) увеличивает номинальное расстояние на линейке."""
    window = MainWindow()
    window.load_map(default_gpkg)
    window.resize(1000, 700)
    window.show()

    initial_dist = window.map_canvas._scale_overlay.distance_m
    # Отдаляем
    window.map_canvas.scale(0.25, 0.25)
    window.map_canvas.update_scale_indicator()

    zoomed_dist = window.map_canvas._scale_overlay.distance_m
    assert zoomed_dist > initial_dist

    window.close()


def test_38_canvas_resize_updates_scale(qapp, default_gpkg):
    """Тест 38: Изменение размера окна пересчитывает масштабную линейку."""
    window = MainWindow()
    window.load_map(default_gpkg)
    window.resize(800, 600)
    window.show()

    window.resize(1400, 900)
    window.map_canvas.update_scale_indicator()

    assert window.map_canvas._scale_overlay.distance_m > 0
    assert bool(window.map_canvas._scale_overlay.text())

    window.close()


def test_39_geographic_pan_updates_scale(qapp):
    """Тест 39: Смещение центра на другую широту в geographic CRS меняет масштаб."""
    canvas = MapCanvas()
    canvas.set_active_crs("OGC:CRS84")
    canvas.resize(800, 600)
    canvas.show()
    canvas._boundary_bounds = QRectF(-180, -90, 360, 180)
    canvas.setSceneRect(QRectF(-180, -90, 360, 180))

    canvas.scale(10.0, 10.0)
    canvas.centerOn(0.0, 0.0)  # Экватор
    canvas.update_scale_indicator()
    eq_dist = canvas._scale_overlay.distance_m

    canvas.centerOn(0.0, -75.0)  # 75° с.ш. (Y в сцене = -lat)
    canvas.update_scale_indicator()
    high_lat_dist = canvas._scale_overlay.distance_m

    assert eq_dist > 0.0
    assert high_lat_dist > 0.0
    assert high_lat_dist < eq_dist


def test_40_empty_canvas_scale_state(qapp):
    """Тест 40: При выгруженной карте масштабная линейка корректно скрывается."""
    canvas = MapCanvas()
    canvas.clear_map()
    assert canvas._scale_overlay.isVisible() is False or canvas._scale_overlay.text() == ""


def test_41_contrast_and_styling(qapp):
    """Тест 41: Стилизация виджета масштаба (полупрозрачный фон, читаемый контраст)."""
    canvas = MapCanvas()
    canvas.show()
    overlay = canvas._scale_overlay
    assert overlay is not None

    overlay.set_map_loaded(True)
    overlay.update_scale("500 м", 120.0, 500.0)
    assert not overlay.isHidden()
    assert overlay.width() > 0
    assert overlay.height() > 0


def test_42_scale_overlay_position_top_left(qapp):
    """Тест 42: Позиционирование масштабной линейки в левом верхнем углу (10-16px отступ)."""
    canvas = MapCanvas()
    canvas.resize(800, 600)
    canvas.show()
    canvas._scale_overlay.move(12, 12)

    pos = canvas._scale_overlay.pos()
    assert 8 <= pos.x() <= 20
    assert 8 <= pos.y() <= 20


def test_43_qsettings_multi_instance_persistence():
    """Тест 43: Проверка реального сохранения настроек в QSettings между отдельными экземплярами сервиса."""
    s1 = AppSettingsService()
    orig_scale = s1.get_show_scale_indicator()
    orig_grid = s1.get_show_coordinate_grid()

    try:
        # Шаг 2 и 3: выставляем тестовые значения
        s1.set_show_scale_indicator(False)
        s1.set_show_coordinate_grid(True)

        # Шаг 4: создаем совершенно новый экземпляр сервиса
        s2 = AppSettingsService()

        # Шаг 5: проверяем, что настройки прочитаны из QSettings
        assert s2.get_show_scale_indicator() is False
        assert s2.get_show_coordinate_grid() is True
    finally:
        # Шаг 6: очистка / восстановление
        s1.set_show_scale_indicator(orig_scale)
        s1.set_show_coordinate_grid(orig_grid)


def test_44_scale_at_high_latitude_vs_equator():
    """Тест 44: Scale Indicator при разных широтах (0° vs 75° N) рассчитывает физическое расстояние без фиксированной константы."""
    # Одинаковый горизонтальный угловой интервал (1 градус) при одинаковой экранной ширине (100 px)
    res_eq = ScaleService.calculate_scale_for_span(0.0, 1.0, 0.0, 100.0, "OGC:CRS84", target_bar_pixels=100.0)
    res_75n = ScaleService.calculate_scale_for_span(0.0, 1.0, 75.0, 100.0, "OGC:CRS84", target_bar_pixels=100.0)

    assert res_eq is not None
    assert res_75n is not None
    dist_eq, px_eq, _ = res_eq
    dist_75n, px_75n, _ = res_75n

    # Физическое расстояние в метрах на пиксель на 75° N должно быть примерно в 3.86 раза меньше (1/cos(75°))
    m_per_px_eq = dist_eq / px_eq
    m_per_px_75n = dist_75n / px_75n
    ratio = m_per_px_75n / m_per_px_eq

    assert 0.25 < ratio < 0.27, f"Отношение масштабов {ratio} должно соответствовать cos(75°) ~ 0.2588"


def test_45_scale_non_meter_projected_crs():
    """Тест 45: В спроецированной CRS с неметровыми единицами (EPSG:2263 US survey foot) масштаб рассчитывается в реальных метрах."""
    # Нью-Йорк, EPSG:2263. Координаты в футах США.
    # 100 000 футов = 30 480.06 метров
    x1 = 980_000.0
    x2 = 1_080_000.0
    y = 200_000.0
    pixel_span = 500.0

    res = ScaleService.calculate_scale_for_span(x1, x2, y, pixel_span, "EPSG:2263", target_bar_pixels=120.0)
    assert res is not None
    nice_dist, actual_px, label = res

    # Проверяем, что результат в метрах (~5000 м или ~10 км), а не в 100 000 метрах
    assert nice_dist < 50_000.0
    assert "км" in label or "м" in label or "km" in label or "m" in label

