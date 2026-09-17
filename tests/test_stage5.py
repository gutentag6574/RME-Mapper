"""Тесты для Этапа 5 проекта RME-Mapper: ввод координат в формате DMS."""

import os
import pytest
from shapely.geometry import Polygon

from rme_mapper.coordinates.converter import dms_to_decimal
from rme_mapper.coordinates.validator import CoordinateValidator
from rme_mapper.maps.map_canvas import MapCanvas
from rme_mapper.models.map_point import MapPoint
from rme_mapper.services.coordinate_service import CoordinateService
from rme_mapper.services.point_service import PointService
from rme_mapper.ui.add_point_dialog import AddPointDialog


@pytest.fixture(scope="session")
def qapp():
    """Фикстура для инициализации QApplication в headless-режиме."""
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    yield app


def test_1_dms_latitude_north_valid():
    """1. 56° 0' 0" N корректно."""
    val = CoordinateValidator.validate_dms_latitude(56, 0, 0, "N")
    assert val == 56.0


def test_2_dms_latitude_south_valid():
    """2. 56° 0' 0" S корректно (-56.0)."""
    val = CoordinateValidator.validate_dms_latitude(56, 0, 0, "S")
    assert val == -56.0


def test_3_dms_longitude_east_valid():
    """3. 47° 0' 0" E корректно (47.0)."""
    val = CoordinateValidator.validate_dms_longitude(47, 0, 0, "E")
    assert val == 47.0


def test_4_dms_longitude_west_valid():
    """4. 47° 0' 0" W корректно (-47.0)."""
    val = CoordinateValidator.validate_dms_longitude(47, 0, 0, "W")
    assert val == -47.0


def test_5_dms_to_dd_conversion_accuracy():
    """5. 56° 38' 15" N правильно преобразуется в DD."""
    # 56 + 38/60 + 15/3600 = 56.6375
    val = CoordinateValidator.validate_dms_latitude(56, 38, 15, "N")
    assert val == pytest.approx(56.6375, abs=1e-6)


def test_6_dms_fractional_seconds_dot():
    """6. Дробные секунды с точкой работают (15.25)."""
    val = CoordinateValidator.validate_dms_latitude("56", "0", "15.25", "N")
    expected = 56.0 + 15.25 / 3600.0
    assert val == pytest.approx(expected, abs=1e-6)


def test_7_dms_fractional_seconds_comma():
    """7. Дробные секунды с запятой работают (15,25)."""
    val = CoordinateValidator.validate_dms_latitude("56", "0", "15,25", "N")
    expected = 56.0 + 15.25 / 3600.0
    assert val == pytest.approx(expected, abs=1e-6)


def test_8_minutes_zero_allowed():
    """8. minutes = 0 допустимо."""
    val = CoordinateValidator.validate_dms_latitude(56, 0, 10, "N")
    assert val == pytest.approx(56.0 + 10.0 / 3600.0, abs=1e-6)


def test_9_seconds_zero_allowed():
    """9. seconds = 0 допустимо."""
    val = CoordinateValidator.validate_dms_latitude(56, 10, 0, "N")
    assert val == pytest.approx(56.0 + 10.0 / 60.0, abs=1e-6)


def test_10_minutes_59_allowed():
    """10. minutes = 59 допустимо."""
    val = CoordinateValidator.validate_dms_latitude(56, 59, 10, "N")
    assert val == pytest.approx(56.0 + 59.0 / 60.0 + 10.0 / 3600.0, abs=1e-6)


def test_11_minutes_60_rejected():
    """11. minutes = 60 отклоняется."""
    with pytest.raises(ValueError, match="Минуты широты"):
        CoordinateValidator.validate_dms_latitude(56, 60, 0, "N")

    with pytest.raises(ValueError, match="Минуты долготы"):
        CoordinateValidator.validate_dms_longitude(47, 60, 0, "E")


def test_12_seconds_59_999_allowed():
    """12. seconds = 59.999 допустимо."""
    val = CoordinateValidator.validate_dms_latitude(56, 10, 59.999, "N")
    assert val == pytest.approx(56.0 + 10.0 / 60.0 + 59.999 / 3600.0, abs=1e-6)


def test_13_seconds_60_rejected():
    """13. seconds = 60 отклоняется."""
    with pytest.raises(ValueError, match="Секунды широты"):
        CoordinateValidator.validate_dms_latitude(56, 10, 60, "N")

    with pytest.raises(ValueError, match="Секунды долготы"):
        CoordinateValidator.validate_dms_longitude(47, 10, 60.0, "E")


def test_14_latitude_90_with_zero_min_sec_allowed():
    """14. latitude degrees = 90 допустимо при 0/0."""
    val = CoordinateValidator.validate_dms_latitude(90, 0, 0, "N")
    assert val == 90.0

    val_s = CoordinateValidator.validate_dms_latitude(90, 0, 0, "S")
    assert val_s == -90.0


def test_15_latitude_90_with_non_zero_rejected():
    """15. latitude 90° 1' 0" отклоняется."""
    with pytest.raises(ValueError, match="Для широты 90°"):
        CoordinateValidator.validate_dms_latitude(90, 1, 0, "N")

    with pytest.raises(ValueError, match="Для широты 90°"):
        CoordinateValidator.validate_dms_latitude(90, 0, 1, "N")


def test_16_longitude_180_with_zero_min_sec_allowed():
    """16. longitude degrees = 180 допустимо при 0/0."""
    val = CoordinateValidator.validate_dms_longitude(180, 0, 0, "E")
    assert val == 180.0

    val_w = CoordinateValidator.validate_dms_longitude(180, 0, 0, "W")
    assert val_w == -180.0


def test_17_longitude_180_with_non_zero_rejected():
    """17. longitude 180° 0' 1" отклоняется."""
    with pytest.raises(ValueError, match="Для долготы 180°"):
        CoordinateValidator.validate_dms_longitude(180, 0, 1, "E")

    with pytest.raises(ValueError, match="Для долготы 180°"):
        CoordinateValidator.validate_dms_longitude(180, 1, 0, "E")


def test_18_empty_minutes_rejected():
    """18. пустые минуты отклоняются."""
    with pytest.raises(ValueError, match="Введите минуты"):
        CoordinateValidator.validate_dms_latitude("56", "", "0", "N")

    with pytest.raises(ValueError, match="Введите минуты"):
        CoordinateValidator.validate_dms_longitude("47", "   ", "0", "E")


def test_19_empty_seconds_rejected():
    """19. пустые секунды отклоняются."""
    with pytest.raises(ValueError, match="Введите секунды"):
        CoordinateValidator.validate_dms_latitude("56", "0", "", "N")

    with pytest.raises(ValueError, match="Введите секунды"):
        CoordinateValidator.validate_dms_longitude("47", "0", "  ", "E")


def test_20_dms_to_dd_south_is_negative():
    """20. DMS -> DD для S дает отрицательное число."""
    val = dms_to_decimal(56, 30, 0, "S")
    assert val == -56.5


def test_21_dms_to_dd_west_is_negative():
    """21. DMS -> DD для W дает отрицательное число."""
    val = dms_to_decimal(47, 30, 0, "W")
    assert val == -47.5


def test_22_add_point_dialog_format_switching(qapp):
    """22. AddPointDialog переключается DD/DMS."""
    dialog = AddPointDialog()
    assert dialog.rb_dd.isChecked()
    assert dialog.stack_widget.currentIndex() == 0

    # Переключаем на DMS
    dialog.rb_dms.setChecked(True)
    assert dialog.rb_dms.isChecked()
    assert dialog.stack_widget.currentIndex() == 1

    # Переключаем обратно на DD
    dialog.rb_dd.setChecked(True)
    assert dialog.rb_dd.isChecked()
    assert dialog.stack_widget.currentIndex() == 0


def test_23_dms_point_added_to_point_service():
    """23. DMS-точка успешно добавляется в PointService."""
    lat, lon = CoordinateValidator.validate_dms_pair(
        ("56", "38", "0", "N"),
        ("47", "53", "0", "E"),
    )
    service = PointService()
    point = service.add_point("DMS Точка", latitude=lat, longitude=lon)

    assert point is not None
    assert point.name == "DMS Точка"
    assert point.latitude == pytest.approx(56.633333, abs=1e-4)
    assert point.longitude == pytest.approx(47.883333, abs=1e-4)
    assert len(service.get_points()) == 1


def test_24_dms_point_appears_on_map_canvas(qapp):
    """24. DMS-точка появляется на MapCanvas."""
    lat, lon = CoordinateValidator.validate_dms_pair(
        ("56", "38", "15", "N"),
        ("47", "53", "10", "E"),
    )
    point = MapPoint(name="Йошкар-Ола DMS", latitude=lat, longitude=lon)

    canvas = MapCanvas()
    canvas.add_user_point(point)

    assert canvas.has_user_point(point.id)
    # Проверяем позицию элемента на сцене: x = lon, y = -lat
    item = canvas._user_point_items[point.id]
    pos = item.pos()
    assert pos.x() == pytest.approx(lon)
    assert pos.y() == pytest.approx(-lat)


def test_25_boundary_check_works_with_dms():
    """25. Проверка границы РМЭ работает после DMS-преобразования."""
    # Полигон Марий Эл (упрощенный охват)
    boundary_poly = Polygon([(45.0, 55.0), (51.0, 55.0), (51.0, 58.0), (45.0, 58.0)])

    # Точка в Марий Эл (Йошкар-Ола в DMS: 56° 38' 0" N, 47° 53' 0" E)
    lat_in, lon_in = CoordinateValidator.validate_dms_pair(
        (56, 38, 0, "N"),
        (47, 53, 0, "E"),
    )
    assert CoordinateService.is_point_inside_boundary(lon_in, lat_in, boundary_poly) is True

    # Точка вне Марий Эл (Москва в DMS: 55° 45' 0" N, 37° 37' 0" E)
    lat_out, lon_out = CoordinateValidator.validate_dms_pair(
        (55, 45, 0, "N"),
        (37, 37, 0, "E"),
    )
    assert CoordinateService.is_point_inside_boundary(lon_out, lat_out, boundary_poly) is False
