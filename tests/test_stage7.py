"""Тесты для Этапа 7 проекта RME-Mapper: географические зоны заданного радиуса."""

import os
import pytest
from PySide6.QtWidgets import QGraphicsItem
from shapely.geometry import Polygon

from rme_mapper.maps.map_canvas import MapCanvas
from rme_mapper.models.map_point import MapPoint
from rme_mapper.models.point_style import (
    PointStyle,
    PointZoneStyle,
    StyleValidator,
    validate_opacity,
    validate_radius,
)
from rme_mapper.services.geodesic_service import GeodesicService
from rme_mapper.services.point_service import PointService
from rme_mapper.ui.add_point_dialog import PointDialog
from rme_mapper.ui.main_window import MainWindow


@pytest.fixture(scope="session")
def qapp():
    """Фикстура для инициализации QApplication в headless-режиме."""
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    yield app


def test_1_pyproj_geod_polygon_valid():
    """1. Геодезический круг строится корректно через pyproj.Geod и является валидным полигоном."""
    poly = GeodesicService.create_geodesic_circle(lat=56.63, lon=47.89, radius_m=1000.0)
    assert isinstance(poly, Polygon)
    assert poly.is_valid
    assert not poly.is_empty
    assert poly.geom_type == "Polygon"
    assert poly.area > 0


def test_2_geodesic_polygon_is_closed():
    """2. Геодезический полигон замкнут (первая и последняя вершины совпадают)."""
    poly = GeodesicService.create_geodesic_circle(lat=56.63, lon=47.89, radius_m=1000.0)
    assert poly.exterior.is_closed
    coords = list(poly.exterior.coords)
    assert coords[0] == coords[-1]


def test_3_geodesic_circle_segment_count():
    """3. Число сегментов полигона не менее 128."""
    poly = GeodesicService.create_geodesic_circle(lat=56.63, lon=47.89, radius_m=1000.0, num_points=128)
    coords = list(poly.exterior.coords)
    # Замкнутое кольцо: 128 сегментов = 129 координат
    assert len(coords) >= 129


def test_4_radius_1000m_accuracy():
    """4. Точность радиуса 1 000 м: расстояние от центра до всех вершин равно 1 000 м ± 0.05%."""
    center_lat, center_lon = 56.63, 47.89
    target_radius = 1000.0
    poly = GeodesicService.create_geodesic_circle(lon=center_lon, lat=center_lat, radius_m=target_radius)

    for lon, lat in list(poly.exterior.coords)[:-1]:
        dist = GeodesicService.calculate_distance(center_lon, center_lat, lon, lat)
        assert dist == pytest.approx(target_radius, rel=0.0005)


def test_5_radius_10000m_accuracy():
    """5. Точность радиуса 10 000 м (10 км): расстояние от центра до вершин в пределах ± 0.05%."""
    center_lat, center_lon = 56.63, 47.89
    target_radius = 10000.0
    poly = GeodesicService.create_geodesic_circle(lon=center_lon, lat=center_lat, radius_m=target_radius)

    for lon, lat in list(poly.exterior.coords)[:-1]:
        dist = GeodesicService.calculate_distance(center_lon, center_lat, lon, lat)
        assert dist == pytest.approx(target_radius, rel=0.0005)


def test_6_radius_50000m_accuracy():
    """6. Точность радиуса 50 000 м (50 км): расстояние от центра до вершин в пределах ± 0.05%."""
    center_lat, center_lon = 56.63, 47.89
    target_radius = 50000.0
    poly = GeodesicService.create_geodesic_circle(lon=center_lon, lat=center_lat, radius_m=target_radius)

    for lon, lat in list(poly.exterior.coords)[:-1]:
        dist = GeodesicService.calculate_distance(center_lon, center_lat, lon, lat)
        assert dist == pytest.approx(target_radius, rel=0.0005)


def test_7_geodesic_accuracy_cardinal_directions():
    """7. Проверка расстояния по четырем сторонам света (Север, Восток, Юг, Запад) на 10 км."""
    center_lat, center_lon = 56.63, 47.89
    target_radius = 10000.0

    # Вычисляем напрямую через fwd
    from pyproj import Geod

    geod = Geod(ellps="WGS84")
    cardinal_azimuths = [0.0, 90.0, 180.0, 270.0]
    for az in cardinal_azimuths:
        p_lon, p_lat, _ = geod.fwd(center_lon, center_lat, az, target_radius)
        dist = GeodesicService.calculate_distance(center_lon, center_lat, p_lon, p_lat)
        assert dist == pytest.approx(target_radius, abs=0.01)


def test_8_geodesic_not_euclidean_degrees():
    """8. Проверка, что буфер геодезический, а не плоский евклидов в градусах.

    На широте Йошкар-Олы (56.63° N) длина 1 градуса долготы существенно меньше
    длины 1 градуса широты (cos(56.63°) ≈ 0.55). Следовательно, размах по долготе
    в градусах для круглого геодезического буфера должен быть примерно в 1.8 раза
    больше, чем размах по широте.
    """
    poly = GeodesicService.create_geodesic_circle(lat=56.63, lon=47.89, radius_m=10000.0)
    min_lon, min_lat, max_lon, max_lat = poly.bounds

    d_lon = max_lon - min_lon
    d_lat = max_lat - min_lat

    # Если бы это был евклидов круг в градусах, d_lon было бы равно d_lat.
    assert d_lon > 1.5 * d_lat


def test_9_km_to_m_conversion():
    """9. Конвертация единиц: 'км' -> метры."""
    assert GeodesicService.parse_radius("1", "км") == 1000.0
    assert GeodesicService.parse_radius("10", "км") == 10000.0
    assert GeodesicService.parse_radius("0.5", "км") == 500.0
    assert GeodesicService.parse_radius("2,5", "км") == 2500.0


def test_10_m_unit_passed_directly():
    """10. Конвертация единиц: 'м' передается без масштабирования."""
    assert GeodesicService.parse_radius("500", "м") == 500.0
    assert GeodesicService.parse_radius("1500,5", "м") == 1500.5


def test_11_radius_min_valid():
    """11. Минимальный допустимый радиус (1.0 м) валиден."""
    assert validate_radius(1.0, zone_enabled=True) == 1.0
    assert StyleValidator.validate_radius(1.0, zone_enabled=True) == 1.0


def test_12_radius_max_valid():
    """12. Максимальный допустимый радиус (1 000 000.0 м / 1 000 км) валиден."""
    assert validate_radius(1000000.0, zone_enabled=True) == 1000000.0
    assert StyleValidator.validate_radius(1000000.0, zone_enabled=True) == 1000000.0


def test_13_radius_zero_with_zone_disabled():
    """13. Радиус 0.0 допустим, когда зона отключена."""
    assert validate_radius(0.0, zone_enabled=False) == 0.0
    assert StyleValidator.validate_radius(0.0, zone_enabled=False) == 0.0


def test_14_radius_zero_with_zone_enabled_rejected():
    """14. Радиус 0.0 отклоняется, когда зона включена."""
    with pytest.raises(ValueError):
        validate_radius(0.0, zone_enabled=True)
    with pytest.raises(ValueError):
        StyleValidator.validate_radius(0.0, zone_enabled=True)


def test_15_radius_negative_rejected():
    """15. Отрицательный радиус отклоняется в любом режиме."""
    with pytest.raises(ValueError):
        validate_radius(-10.0, zone_enabled=True)
    with pytest.raises(ValueError):
        validate_radius(-5.0, zone_enabled=False)


def test_16_radius_above_max_rejected():
    """16. Радиус выше максимального (> 1 000 000 м) отклоняется."""
    with pytest.raises(ValueError):
        validate_radius(1000001.0, zone_enabled=True)


def test_17_radius_non_numeric_rejected():
    """17. Нечисловой радиус отклоняется валидатором и парсером."""
    with pytest.raises(ValueError):
        GeodesicService.parse_radius("abc", "м")
    with pytest.raises(ValueError):
        validate_radius("not-a-number", zone_enabled=True)


def test_18_opacity_min_valid():
    """18. Минимальная прозрачность 0% валидна."""
    assert validate_opacity(0) == 0
    assert StyleValidator.validate_opacity(0) == 0


def test_19_opacity_max_valid():
    """19. Максимальная прозрачность 100% валидна."""
    assert validate_opacity(100) == 100
    assert StyleValidator.validate_opacity(100) == 100


def test_20_opacity_out_of_range_rejected():
    """20. Прозрачность вне диапазона 0..100 отклоняется."""
    with pytest.raises(ValueError):
        validate_opacity(-1)
    with pytest.raises(ValueError):
        validate_opacity(101)
    with pytest.raises(ValueError):
        validate_opacity("abc")


def test_21_map_point_zone_defaults():
    """21. MapPoint имеет корректные значения по умолчанию для полей зоны."""
    p = MapPoint("Тестовая", 56.63, 47.88)
    assert p.zone_enabled is False
    assert p.radius_m == 0.0
    assert p.zone_red == 220
    assert p.zone_green == 30
    assert p.zone_blue == 30
    assert p.zone_opacity == 30
    assert isinstance(p.zone, PointZoneStyle)


def test_22_point_service_add_with_zone():
    """22. PointService.add_point сохраняет параметры зоны."""
    service = PointService()
    p = service.add_point(
        name="Точка с зоной",
        latitude=56.63,
        longitude=47.88,
        zone_enabled=True,
        radius_m=5000.0,
        zone_red=200,
        zone_green=100,
        zone_blue=50,
        zone_opacity=40,
    )
    assert p.zone_enabled is True
    assert p.radius_m == 5000.0
    assert p.zone_red == 200
    assert p.zone_green == 100
    assert p.zone_blue == 50
    assert p.zone_opacity == 40


def test_23_point_service_update_zone():
    """23. PointService.update_point обновляет параметры зоны точки."""
    service = PointService()
    p = service.add_point("Точка", 56.63, 47.88)
    assert p.zone_enabled is False

    upd = service.update_point(
        p.id,
        zone_enabled=True,
        radius_m=12000.0,
        zone_red=10,
        zone_green=20,
        zone_blue=30,
        zone_opacity=55,
    )
    assert upd.zone_enabled is True
    assert upd.radius_m == 12000.0
    assert upd.zone_red == 10
    assert upd.zone_green == 20
    assert upd.zone_blue == 30
    assert upd.zone_opacity == 55


def test_24_canvas_creates_zone_graphics_item(qapp):
    """24. MapCanvas создает графический элемент зоны при zone_enabled=True."""
    canvas = MapCanvas()
    p = MapPoint("Зона 5км", 56.63, 47.88, zone_enabled=True, radius_m=5000.0)
    canvas.add_user_point(p)

    assert canvas.has_point_zone(p.id)
    zone_item = canvas._user_zone_items[p.id]
    assert zone_item is not None
    assert zone_item.scene() == canvas.scene()


def test_25_canvas_zone_z_value(qapp):
    """25. Z-значение зоны (90.0) ниже маркера (100.0) и выше дорог (40.0)."""
    canvas = MapCanvas()
    p = MapPoint("Зона", 56.63, 47.88, zone_enabled=True, radius_m=5000.0)
    canvas.add_user_point(p)

    marker_item = canvas._user_point_items[p.id]
    zone_item = canvas._user_zone_items[p.id]

    assert zone_item.zValue() == 90.0
    assert marker_item.zValue() == 100.0
    assert zone_item.zValue() < marker_item.zValue()
    assert zone_item.zValue() > 40.0


def test_26_canvas_zone_scales_with_map(qapp):
    """26. Графический элемент зоны масштабируется вместе с картой (ItemIgnoresTransformations выключен)."""
    canvas = MapCanvas()
    p = MapPoint("Зона", 56.63, 47.88, zone_enabled=True, radius_m=5000.0)
    canvas.add_user_point(p)

    zone_item = canvas._user_zone_items[p.id]
    flags = zone_item.flags()
    assert not bool(flags & QGraphicsItem.GraphicsItemFlag.ItemIgnoresTransformations)


def test_27_canvas_marker_does_not_scale_with_map(qapp):
    """27. Графический элемент маркера сохраняет фиксированный экранный размер (ItemIgnoresTransformations включен)."""
    canvas = MapCanvas()
    p = MapPoint("Зона", 56.63, 47.88, zone_enabled=True, radius_m=5000.0)
    canvas.add_user_point(p)

    marker_item = canvas._user_point_items[p.id]
    flags = marker_item.flags()
    assert bool(flags & QGraphicsItem.GraphicsItemFlag.ItemIgnoresTransformations)


def test_28_canvas_zone_disabled_no_item(qapp):
    """28. При zone_enabled=False графический элемент зоны не создается на холсте."""
    canvas = MapCanvas()
    p = MapPoint("Без зоны", 56.63, 47.88, zone_enabled=False, radius_m=0.0)
    canvas.add_user_point(p)

    assert not canvas.has_point_zone(p.id)
    assert p.id not in canvas._user_zone_items


def test_29_canvas_update_zone(qapp):
    """29. Обновление параметров зоны обновляет элемент на холсте без дублирования."""
    canvas = MapCanvas()
    p = MapPoint("Точка", 56.63, 47.88, zone_enabled=True, radius_m=1000.0)
    canvas.add_user_point(p)

    old_item = canvas._user_zone_items[p.id]
    old_width = old_item.path().boundingRect().width()

    p.radius_m = 10000.0
    canvas.update_user_point(p)

    new_item = canvas._user_zone_items[p.id]
    new_width = new_item.path().boundingRect().width()

    assert new_width > old_width
    assert len(canvas._user_zone_items) == 1


def test_30_canvas_remove_point_removes_zone(qapp):
    """30. Удаление точки с холста удаляет и связанную геодезическую зону."""
    canvas = MapCanvas()
    p = MapPoint("Точка", 56.63, 47.88, zone_enabled=True, radius_m=5000.0)
    canvas.add_user_point(p)
    assert canvas.has_point_zone(p.id)

    canvas.remove_user_point(p.id)
    assert not canvas.has_point_zone(p.id)
    assert not canvas.has_user_point(p.id)


def test_31_table_shows_radius(qapp):
    """31. В таблице отображается колонка 'Радиус' со значением или дефисом."""
    window = MainWindow()
    p1 = window._point_service.add_point("С зоной км", 56.63, 47.88, zone_enabled=True, radius_m=10000.0)
    p2 = window._point_service.add_point("С зоной м", 56.63, 47.88, zone_enabled=True, radius_m=500.0)
    p3 = window._point_service.add_point("Без зоны", 56.63, 47.88, zone_enabled=False)

    window._add_point_to_table(p1)
    window._add_point_to_table(p2)
    window._add_point_to_table(p3)

    assert window.points_table.columnCount() == 6
    assert window.points_table.horizontalHeaderItem(5).text() == "Радиус"
    assert window.points_table.item(0, 5).text() == "10 км"
    assert window.points_table.item(1, 5).text() == "500 м"
    assert window.points_table.item(2, 5).text() == "—"


def test_32_properties_panel_shows_zone(qapp):
    """32. Панель 'Свойства' отображает статус зоны, радиус, цвет и прозрачность."""
    window = MainWindow()
    p = window._point_service.add_point(
        "Точка свойств",
        56.63,
        47.88,
        zone_enabled=True,
        radius_m=15000.0,
        zone_red=255,
        zone_green=100,
        zone_blue=50,
        zone_opacity=40,
    )
    window._add_point_to_table(p)
    window.points_table.selectRow(0)

    assert window.prop_zone_val.text() == "Да"
    assert window.prop_zone_radius_val.text() == "15 км"
    assert "255, 100, 50" in window.prop_zone_color_val.text()
    assert window.prop_zone_opacity_val.text() == "40%"


def test_33_dialog_zone_ui_elements(qapp):
    """33. В диалоге добавления/редактирования присутствуют элементы управления зоной."""
    dialog = PointDialog(mode="CREATE")
    assert hasattr(dialog, "zone_group")
    assert hasattr(dialog, "zone_enabled_chk")
    assert hasattr(dialog, "radius_edit")
    assert hasattr(dialog, "unit_combo")
    assert hasattr(dialog, "btn_pick_zone_color")
    assert hasattr(dialog, "opacity_slider")
    assert hasattr(dialog, "opacity_spin")

    # Исходно флажок снят, поля ввода отключены
    assert not dialog.zone_enabled_chk.isChecked()
    assert not dialog.radius_edit.isEnabled()

    # Включение флажка активирует элементы управления зоной
    dialog.zone_enabled_chk.setChecked(True)
    assert dialog.radius_edit.isEnabled()
    assert dialog.unit_combo.isEnabled()
    assert dialog.opacity_slider.isEnabled()
    assert dialog.opacity_spin.isEnabled()
