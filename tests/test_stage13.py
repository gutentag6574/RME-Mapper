"""Тесты для Этапа 13 — Массовый импорт XLSX / CSV / TXT.

Разделы тестирования (75 тестов):
- Section 55: Типы файлов и кодировки (тесты 1–9)
- Section 56: Координаты DD (тесты 10–20)
- Section 57: Координаты DMS (тесты 21–31)
- Section 58: Оформление маркера (тесты 32–40)
- Section 59: Геодезические зоны (тесты 41–49)
- Section 60: Построчная валидация и ImportResult (тесты 50–58)
- Section 61: Атомарное Undo / Redo (тесты 59–65)
- Section 62: Интерфейс и Drag & Drop (тесты 66–74)
- Section 63: Тест производительности (тест 75)
"""

import os
from pathlib import Path
import time
from unittest.mock import MagicMock
import openpyxl
import pytest

from PySide6.QtCore import QPoint, QPointF, Qt, QUrl
from PySide6.QtGui import QDragEnterEvent, QDropEvent
from PySide6.QtWidgets import QApplication, QMessageBox, QGroupBox

from rme_mapper.i18n import set_language
from rme_mapper.importers.import_service import ImportService
from rme_mapper.importers.models import (
    CoordinateFormat,
    ImportOptions,
    ImportResult,
)
from rme_mapper.maps.map_config import get_default_geopackage_path
from rme_mapper.models.map_point import MapPoint
from rme_mapper.services.app_settings_service import AppSettingsService
from rme_mapper.services.undo_manager import ImportPointsCommand, UndoManager
from rme_mapper.ui.import_dialog import ImportDialog
from rme_mapper.ui.main_window import MainWindow


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    yield app


@pytest.fixture
def clean_settings():
    settings = AppSettingsService()
    settings.clear()
    yield settings
    settings.clear()


@pytest.fixture(autouse=True)
def no_unsaved_prompts(monkeypatch):
    from rme_mapper.ui.controllers.project_controller import ProjectController
    monkeypatch.setattr(ProjectController, "maybe_save_prompt", lambda self, *args, **kwargs: True)


class MockDragDropEvent:
    def __init__(self, file_paths: list[str]) -> None:
        self._urls = [QUrl.fromLocalFile(p) for p in file_paths]
        self._accepted = False

        class _Mime:
            def __init__(self, urls):
                self._urls = urls

            def hasUrls(self):
                return bool(self._urls)

            def urls(self):
                return self._urls

        self._mime = _Mime(self._urls)

    def mimeData(self):
        return self._mime

    def acceptProposedAction(self):
        self._accepted = True

    def ignore(self):
        self._accepted = False

    def isAccepted(self):
        return self._accepted


# =============================================================================
# Section 55: Типы файлов и кодировки (тесты 1–9)
# =============================================================================

def test_01_xlsx_read(tmp_path):
    """1. Чтение файла формата .xlsx через openpyxl."""
    file = tmp_path / "test.xlsx"
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Points"
    ws.append(["name", "latitude", "longitude"])
    ws.append(["Точка 1", 56.63, 47.88])
    wb.save(str(file))
    wb.close()

    service = ImportService()
    res = service.validate_file(file)
    assert res.total_rows == 1
    assert res.valid_rows == 1
    assert res.invalid_rows == 0
    assert len(res.points) == 1
    assert res.points[0].name == "Точка 1"
    assert res.points[0].latitude == 56.63
    assert res.points[0].longitude == 47.88


def test_02_csv_comma_delimiter(tmp_path):
    """2. CSV файл с разделителем запятая."""
    file = tmp_path / "test.csv"
    file.write_text("name,latitude,longitude\nP1,56.63,47.88\n", encoding="utf-8")

    service = ImportService()
    res = service.validate_file(file)
    assert res.valid_rows == 1
    assert res.detected_delimiter == ","
    assert res.points[0].name == "P1"


def test_03_csv_semicolon_delimiter(tmp_path):
    """3. CSV файл с разделителем точка с запятой."""
    file = tmp_path / "test.csv"
    file.write_text("name;latitude;longitude\nP1;56.63;47.88\n", encoding="utf-8")

    service = ImportService()
    res = service.validate_file(file)
    assert res.valid_rows == 1
    assert res.detected_delimiter == ";"
    assert res.points[0].name == "P1"


def test_04_txt_tab_delimiter(tmp_path):
    """4. TXT файл с разделителем табуляция."""
    file = tmp_path / "test.txt"
    file.write_text("name\tlatitude\tlongitude\nP1\t56.63\t47.88\n", encoding="utf-8")

    service = ImportService()
    res = service.validate_file(file)
    assert res.valid_rows == 1
    assert res.detected_delimiter == "\t"
    assert res.points[0].name == "P1"


def test_05_utf8_encoding(tmp_path):
    """5. Корректное чтение кодировки UTF-8 с русскими символами."""
    file = tmp_path / "test_utf8.csv"
    file.write_text("name;latitude;longitude\nЙошкар-Ола;56.63;47.88\n", encoding="utf-8")

    service = ImportService()
    res = service.validate_file(file)
    assert res.valid_rows == 1
    assert res.detected_encoding == "utf-8"
    assert res.points[0].name == "Йошкар-Ола"


def test_06_utf8_bom_encoding(tmp_path):
    """6. Корректное чтение кодировки UTF-8 с BOM (сигнатура EF BB BF)."""
    file = tmp_path / "test_bom.csv"
    content = "name;latitude;longitude\nМосква;55.75;37.61\n"
    file.write_bytes(b"\xef\xbb\xbf" + content.encode("utf-8"))

    service = ImportService()
    res = service.validate_file(file)
    assert res.valid_rows == 1
    assert res.detected_encoding == "utf-8-sig"
    assert res.points[0].name == "Москва"


def test_07_cp1251_fallback(tmp_path):
    """7. Fallback на кодировку Windows-1251 (CP1251)."""
    file = tmp_path / "test_1251.csv"
    content = "name;latitude;longitude\nКазань;55.79;49.12\n"
    file.write_bytes(content.encode("cp1251"))

    service = ImportService()
    res = service.validate_file(file)
    assert res.valid_rows == 1
    assert res.detected_encoding == "cp1251"
    assert res.points[0].name == "Казань"


def test_08_unsupported_file_rejected(tmp_path):
    """8. Неподдерживаемое расширение файла отвергается с ошибкой."""
    file = tmp_path / "data.kml"
    file.write_text("<kml></kml>", encoding="utf-8")

    service = ImportService()
    res = service.validate_file(file)
    assert res.total_rows == 0
    assert len(res.errors) == 1
    assert res.errors[0].code == "import.err.unsupported_file_format"


def test_09_nonexistent_file_rejected(tmp_path):
    """9. Несуществующий файл отвергается с ошибкой."""
    file = tmp_path / "missing.csv"
    service = ImportService()
    res = service.validate_file(file)
    assert len(res.errors) == 1
    assert res.errors[0].code == "import.err.file_not_found"


# =============================================================================
# Section 56: Координаты DD (тесты 10–20)
# =============================================================================

def test_10_valid_dd(tmp_path):
    """10. Корректные десятичные координаты DD."""
    file = tmp_path / "test.csv"
    file.write_text("latitude;longitude\n56.63;47.88\n", encoding="utf-8")

    service = ImportService()
    res = service.validate_file(file)
    assert res.valid_rows == 1
    assert res.points[0].latitude == 56.63
    assert res.points[0].longitude == 47.88


def test_11_decimal_dot(tmp_path):
    """11. Десятичные координаты с точкой."""
    file = tmp_path / "test.csv"
    file.write_text("lat;lon\n56.123456;47.654321\n", encoding="utf-8")

    service = ImportService()
    res = service.validate_file(file)
    assert res.valid_rows == 1
    assert abs(res.points[0].latitude - 56.123456) < 1e-6


def test_12_decimal_comma_where_unambiguous(tmp_path):
    """12. Десятичные координаты с запятой в файле с точкой с запятой."""
    file = tmp_path / "test.csv"
    file.write_text("lat;lon\n56,6328;47,8844\n", encoding="utf-8")

    service = ImportService()
    res = service.validate_file(file)
    assert res.valid_rows == 1
    assert abs(res.points[0].latitude - 56.6328) < 1e-6
    assert abs(res.points[0].longitude - 47.8844) < 1e-6


def test_13_lat_90_valid(tmp_path):
    """13. Широта ровно 90 допустима."""
    file = tmp_path / "test.csv"
    file.write_text("lat;lon\n90.0;45.0\n", encoding="utf-8")

    service = ImportService()
    res = service.validate_file(file)
    assert res.valid_rows == 1
    assert res.points[0].latitude == 90.0


def test_14_lat_minus_90_valid(tmp_path):
    """14. Широта ровно -90 допустима."""
    file = tmp_path / "test.csv"
    file.write_text("lat;lon\n-90.0;45.0\n", encoding="utf-8")

    service = ImportService()
    res = service.validate_file(file)
    assert res.valid_rows == 1
    assert res.points[0].latitude == -90.0


def test_15_lon_180_valid(tmp_path):
    """15. Долгота ровно 180 допустима."""
    file = tmp_path / "test.csv"
    file.write_text("lat;lon\n45.0;180.0\n", encoding="utf-8")

    service = ImportService()
    res = service.validate_file(file)
    assert res.valid_rows == 1
    assert res.points[0].longitude == 180.0


def test_16_lon_minus_180_valid(tmp_path):
    """16. Долгота ровно -180 допустима."""
    file = tmp_path / "test.csv"
    file.write_text("lat;lon\n45.0;-180.0\n", encoding="utf-8")

    service = ImportService()
    res = service.validate_file(file)
    assert res.valid_rows == 1
    assert res.points[0].longitude == -180.0


def test_17_lat_91_rejected(tmp_path):
    """17. Широта 91 отвергается как выходящая за диапазон [-90..90]."""
    file = tmp_path / "test.csv"
    file.write_text("lat;lon\n91.0;45.0\n", encoding="utf-8")

    service = ImportService()
    res = service.validate_file(file)
    assert res.valid_rows == 0
    assert res.invalid_rows == 1
    assert res.errors[0].code == "import.err.lat_out_of_range"


def test_18_lon_181_rejected(tmp_path):
    """18. Долгота 181 отвергается как выходящая за диапазон [-180..180]."""
    file = tmp_path / "test.csv"
    file.write_text("lat;lon\n45.0;181.0\n", encoding="utf-8")

    service = ImportService()
    res = service.validate_file(file)
    assert res.valid_rows == 0
    assert res.invalid_rows == 1
    assert res.errors[0].code == "import.err.lon_out_of_range"


def test_19_empty_latitude_rejected(tmp_path):
    """19. Пустая широта вызывает ошибку строки."""
    file = tmp_path / "test.csv"
    file.write_text("name;lat;lon\nТочка;;47.88\n", encoding="utf-8")

    service = ImportService()
    res = service.validate_file(file)
    assert res.valid_rows == 0
    assert res.invalid_rows == 1
    assert res.errors[0].field == "latitude"


def test_20_empty_longitude_rejected(tmp_path):
    """20. Пустая долгота вызывает ошибку строки."""
    file = tmp_path / "test.csv"
    file.write_text("name;lat;lon\nТочка;56.63;\n", encoding="utf-8")

    service = ImportService()
    res = service.validate_file(file)
    assert res.valid_rows == 0
    assert res.invalid_rows == 1
    assert res.errors[0].field == "longitude"


# =============================================================================
# Section 57: Координаты DMS (тесты 21–31)
# =============================================================================

def test_21_valid_dms(tmp_path):
    """21. Корректные координаты в формате DMS."""
    file = tmp_path / "test.csv"
    file.write_text(
        "name;lat_deg;lat_min;lat_sec;lat_dir;lon_deg;lon_min;lon_sec;lon_dir\n"
        "P1;56;37;58.08;N;47;53;3.84;E\n",
        encoding="utf-8",
    )

    service = ImportService()
    res = service.validate_file(file)
    assert res.valid_rows == 1
    assert res.detected_format == CoordinateFormat.DMS
    assert abs(res.points[0].latitude - 56.6328) < 1e-4
    assert abs(res.points[0].longitude - 47.8844) < 1e-4


def test_22_zero_minutes_allowed(tmp_path):
    """22. Ноль минут в DMS допустим."""
    file = tmp_path / "test.csv"
    file.write_text(
        "lat_deg;lat_min;lat_sec;lat_dir;lon_deg;lon_min;lon_sec;lon_dir\n"
        "56;0;30;N;47;0;30;E\n",
        encoding="utf-8",
    )

    service = ImportService()
    res = service.validate_file(file)
    assert res.valid_rows == 1


def test_23_zero_seconds_allowed(tmp_path):
    """23. Ноль секунд в DMS допустим."""
    file = tmp_path / "test.csv"
    file.write_text(
        "lat_deg;lat_min;lat_sec;lat_dir;lon_deg;lon_min;lon_sec;lon_dir\n"
        "56;30;0;N;47;30;0;E\n",
        encoding="utf-8",
    )

    service = ImportService()
    res = service.validate_file(file)
    assert res.valid_rows == 1


def test_24_fractional_seconds_dot(tmp_path):
    """24. Дробные секунды с точкой."""
    file = tmp_path / "test.csv"
    file.write_text(
        "lat_deg;lat_min;lat_sec;lat_dir;lon_deg;lon_min;lon_sec;lon_dir\n"
        "56;30;15.75;N;47;30;45.25;E\n",
        encoding="utf-8",
    )

    service = ImportService()
    res = service.validate_file(file)
    assert res.valid_rows == 1


def test_25_fractional_seconds_comma(tmp_path):
    """25. Дробные секунды с запятой."""
    file = tmp_path / "test.csv"
    file.write_text(
        "lat_deg;lat_min;lat_sec;lat_dir;lon_deg;lon_min;lon_sec;lon_dir\n"
        "56;30;15,75;N;47;30;45,25;E\n",
        encoding="utf-8",
    )

    service = ImportService()
    res = service.validate_file(file)
    assert res.valid_rows == 1


def test_26_minutes_60_rejected(tmp_path):
    """26. Минуты равные 60 отвергаются."""
    file = tmp_path / "test.csv"
    file.write_text(
        "lat_deg;lat_min;lat_sec;lat_dir;lon_deg;lon_min;lon_sec;lon_dir\n"
        "56;60;0;N;47;30;0;E\n",
        encoding="utf-8",
    )

    service = ImportService()
    res = service.validate_file(file)
    assert res.valid_rows == 0
    assert res.errors[0].code == "import.err.lat_min_range"


def test_27_seconds_60_rejected(tmp_path):
    """27. Секунды равные 60 отвергаются."""
    file = tmp_path / "test.csv"
    file.write_text(
        "lat_deg;lat_min;lat_sec;lat_dir;lon_deg;lon_min;lon_sec;lon_dir\n"
        "56;30;60.0;N;47;30;0;E\n",
        encoding="utf-8",
    )

    service = ImportService()
    res = service.validate_file(file)
    assert res.valid_rows == 0
    assert res.errors[0].code == "import.err.lat_sec_range"


def test_28_lat_90_with_nonzero_min_sec_rejected(tmp_path):
    """28. При широте 90° ненулевые минуты или секунды отвергаются."""
    file = tmp_path / "test.csv"
    file.write_text(
        "lat_deg;lat_min;lat_sec;lat_dir;lon_deg;lon_min;lon_sec;lon_dir\n"
        "90;1;0;N;47;30;0;E\n",
        encoding="utf-8",
    )

    service = ImportService()
    res = service.validate_file(file)
    assert res.valid_rows == 0
    assert res.errors[0].code == "import.err.lat_90_nonzero"


def test_29_lon_180_with_nonzero_min_sec_rejected(tmp_path):
    """29. При долготе 180° ненулевые минуты или секунды отвергаются."""
    file = tmp_path / "test.csv"
    file.write_text(
        "lat_deg;lat_min;lat_sec;lat_dir;lon_deg;lon_min;lon_sec;lon_dir\n"
        "56;30;0;N;180;0;1;E\n",
        encoding="utf-8",
    )

    service = ImportService()
    res = service.validate_file(file)
    assert res.valid_rows == 0
    assert res.errors[0].code == "import.err.lon_180_nonzero"


def test_30_s_direction_becomes_negative(tmp_path):
    """30. Направление 'S' (Юг) делает широту отрицательной."""
    file = tmp_path / "test.csv"
    file.write_text(
        "lat_deg;lat_min;lat_sec;lat_dir;lon_deg;lon_min;lon_sec;lon_dir\n"
        "25;30;0;S;47;30;0;E\n",
        encoding="utf-8",
    )

    service = ImportService()
    res = service.validate_file(file)
    assert res.valid_rows == 1
    assert res.points[0].latitude == -25.5


def test_31_w_direction_becomes_negative(tmp_path):
    """31. Направление 'W' (Запад) делает долготу отрицательной."""
    file = tmp_path / "test.csv"
    file.write_text(
        "lat_deg;lat_min;lat_sec;lat_dir;lon_deg;lon_min;lon_sec;lon_dir\n"
        "25;30;0;N;47;30;0;W\n",
        encoding="utf-8",
    )

    service = ImportService()
    res = service.validate_file(file)
    assert res.valid_rows == 1
    assert res.points[0].longitude == -47.5


# =============================================================================
# Section 58: Оформление маркера (тесты 32–40)
# =============================================================================

def test_32_default_style_when_omitted(tmp_path):
    """32. Стандартный стиль маркера при отсутствии параметров оформления."""
    file = tmp_path / "test.csv"
    file.write_text("lat;lon\n56.0;47.0\n", encoding="utf-8")

    service = ImportService()
    res = service.validate_file(file)
    p = res.points[0]
    assert p.symbol == "circle"
    assert p.size == 12.0
    assert (p.red, p.green, p.blue) == (220, 30, 30)


def test_33_symbol_circle(tmp_path):
    """33. Форма маркера circle (и псевдоним 'круг')."""
    file = tmp_path / "test.csv"
    file.write_text("lat;lon;symbol\n56.0;47.0;круг\n", encoding="utf-8")

    service = ImportService()
    res = service.validate_file(file)
    assert res.points[0].symbol == "circle"


def test_34_symbol_square(tmp_path):
    """34. Форма маркера square (и псевдоним 'квадрат')."""
    file = tmp_path / "test.csv"
    file.write_text("lat;lon;symbol\n56.0;47.0;квадрат\n", encoding="utf-8")

    service = ImportService()
    res = service.validate_file(file)
    assert res.points[0].symbol == "square"


def test_35_symbol_triangle(tmp_path):
    """35. Форма маркера triangle (и псевдоним 'треугольник')."""
    file = tmp_path / "test.csv"
    file.write_text("lat;lon;symbol\n56.0;47.0;треугольник\n", encoding="utf-8")

    service = ImportService()
    res = service.validate_file(file)
    assert res.points[0].symbol == "triangle"


def test_36_rgb_0_valid(tmp_path):
    """36. Цвет RGB со значениями 0 допустим."""
    file = tmp_path / "test.csv"
    file.write_text("lat;lon;red;green;blue\n56.0;47.0;0;0;0\n", encoding="utf-8")

    service = ImportService()
    res = service.validate_file(file)
    assert (res.points[0].red, res.points[0].green, res.points[0].blue) == (0, 0, 0)


def test_37_rgb_255_valid(tmp_path):
    """37. Цвет RGB со значениями 255 допустим."""
    file = tmp_path / "test.csv"
    file.write_text("lat;lon;red;green;blue\n56.0;47.0;255;255;255\n", encoding="utf-8")

    service = ImportService()
    res = service.validate_file(file)
    assert (res.points[0].red, res.points[0].green, res.points[0].blue) == (255, 255, 255)


def test_38_invalid_or_incomplete_rgb_rejected(tmp_path):
    """38. Неполный RGB (только R и G) считается ошибкой строки."""
    file = tmp_path / "test.csv"
    file.write_text("lat;lon;red;green\n56.0;47.0;200;100\n", encoding="utf-8")

    service = ImportService()
    res = service.validate_file(file)
    assert res.valid_rows == 0
    assert res.errors[0].code == "import.err.incomplete_rgb"


def test_39_valid_size(tmp_path):
    """39. Допустимый размер маркера (например 24.5 px)."""
    file = tmp_path / "test.csv"
    file.write_text("lat;lon;size\n56.0;47.0;24.5\n", encoding="utf-8")

    service = ImportService()
    res = service.validate_file(file)
    assert res.points[0].size == 24.5


def test_40_invalid_size_rejected(tmp_path):
    """40. Недопустимый размер маркера (<4 или >50) отвергается."""
    file = tmp_path / "test.csv"
    file.write_text("lat;lon;size\n56.0;47.0;100\n", encoding="utf-8")

    service = ImportService()
    res = service.validate_file(file)
    assert res.valid_rows == 0
    assert res.errors[0].code == "import.err.invalid_size"


# =============================================================================
# Section 59: Геодезические зоны (тесты 41–49)
# =============================================================================

def test_41_zone_disabled(tmp_path):
    """41. Отключенная геозона."""
    file = tmp_path / "test.csv"
    file.write_text("lat;lon;zone_enabled;radius\n56.0;47.0;false;0\n", encoding="utf-8")

    service = ImportService()
    res = service.validate_file(file)
    assert res.valid_rows == 1
    assert not res.points[0].zone_enabled
    assert res.points[0].radius_m == 0.0


def test_42_zone_enabled_m(tmp_path):
    """42. Включенная геозона в метрах."""
    file = tmp_path / "test.csv"
    file.write_text("lat;lon;zone_enabled;radius;radius_unit\n56.0;47.0;true;500;m\n", encoding="utf-8")

    service = ImportService()
    res = service.validate_file(file)
    assert res.valid_rows == 1
    assert res.points[0].zone_enabled
    assert res.points[0].radius_m == 500.0


def test_43_zone_enabled_km(tmp_path):
    """43. Включенная геозона в километрах (автоматически умножается на 1000)."""
    file = tmp_path / "test.csv"
    file.write_text("lat;lon;zone_enabled;radius;radius_unit\n56.0;47.0;true;5;km\n", encoding="utf-8")

    service = ImportService()
    res = service.validate_file(file)
    assert res.valid_rows == 1
    assert res.points[0].zone_enabled
    assert res.points[0].radius_m == 5000.0


def test_44_russian_units(tmp_path):
    """44. Русские единицы измерения ('км', 'м')."""
    file = tmp_path / "test.csv"
    file.write_text("lat;lon;radius;radius_unit\n56.0;47.0;12;км\n", encoding="utf-8")

    service = ImportService()
    res = service.validate_file(file)
    assert res.valid_rows == 1
    assert res.points[0].zone_enabled
    assert res.points[0].radius_m == 12000.0


def test_45_english_units(tmp_path):
    """45. Английские единицы измерения ('km', 'm')."""
    file = tmp_path / "test.csv"
    file.write_text("lat;lon;radius;radius_unit\n56.0;47.0;2.5;km\n", encoding="utf-8")

    service = ImportService()
    res = service.validate_file(file)
    assert res.valid_rows == 1
    assert res.points[0].radius_m == 2500.0


def test_46_invalid_radius_rejected(tmp_path):
    """46. Недопустимый радиус (>1 000 000 м или <=0) отвергается."""
    file = tmp_path / "test.csv"
    file.write_text("lat;lon;zone_enabled;radius\n56.0;47.0;true;-5\n", encoding="utf-8")

    service = ImportService()
    res = service.validate_file(file)
    assert res.valid_rows == 0
    assert res.errors[0].code == "import.err.invalid_radius"


def test_47_zone_rgb(tmp_path):
    """47. Настраиваемый цвет зоны."""
    file = tmp_path / "test.csv"
    file.write_text("lat;lon;radius;zone_red;zone_green;zone_blue\n56.0;47.0;100;10;20;30\n", encoding="utf-8")

    service = ImportService()
    res = service.validate_file(file)
    assert (res.points[0].zone_red, res.points[0].zone_green, res.points[0].zone_blue) == (10, 20, 30)


def test_48_zone_opacity(tmp_path):
    """48. Прозрачность зоны (0..100%)."""
    file = tmp_path / "test.csv"
    file.write_text("lat;lon;radius;zone_opacity\n56.0;47.0;100;65\n", encoding="utf-8")

    service = ImportService()
    res = service.validate_file(file)
    assert res.points[0].zone_opacity == 65


def test_49_boolean_aliases(tmp_path):
    """49. Поддержка различных булевых синонимов (1/0, да/нет, yes/no)."""
    file = tmp_path / "test.csv"
    file.write_text(
        "lat;lon;zone;radius\n"
        "56.1;47.1;да;100\n"
        "56.2;47.2;нет;0\n"
        "56.3;47.3;1;200\n"
        "56.4;47.4;0;0\n",
        encoding="utf-8",
    )

    service = ImportService()
    res = service.validate_file(file)
    assert res.valid_rows == 4
    assert res.points[0].zone_enabled is True
    assert res.points[1].zone_enabled is False
    assert res.points[2].zone_enabled is True
    assert res.points[3].zone_enabled is False


# =============================================================================
# Section 60: Построчная валидация и ImportResult (тесты 50–58)
# =============================================================================

def test_50_empty_rows_skipped(tmp_path):
    """50. Полностью пустые строки пропускаются без добавления ошибок."""
    file = tmp_path / "test.csv"
    file.write_text(
        "lat;lon\n\n56.0;47.0\n   \n\n56.5;47.5\n\n",
        encoding="utf-8",
    )

    service = ImportService()
    res = service.validate_file(file)
    assert res.total_rows == 2
    assert res.valid_rows == 2
    assert res.invalid_rows == 0


def test_51_partial_row_invalid(tmp_path):
    """51. Частично пустая строка (есть имя, нет координат) — невалидна."""
    file = tmp_path / "test.csv"
    file.write_text("name;lat;lon\nP1;56.0;47.0\nP2;;\n", encoding="utf-8")

    service = ImportService()
    res = service.validate_file(file)
    assert res.total_rows == 2
    assert res.valid_rows == 1
    assert res.invalid_rows == 1


def test_52_error_contains_row_number(tmp_path):
    """52. Ошибка содержит точный 1-индексированный номер строки файла."""
    file = tmp_path / "test.csv"
    file.write_text("name;lat;lon\nP1;56.0;47.0\nP2;invalid_lat;47.0\n", encoding="utf-8")

    service = ImportService()
    res = service.validate_file(file)
    assert res.invalid_rows == 1
    assert res.errors[0].row_number == 3


def test_53_error_contains_field(tmp_path):
    """53. Ошибка содержит точное название проблемного поля."""
    file = tmp_path / "test.csv"
    file.write_text("lat;lon\n56.0;invalid_lon\n", encoding="utf-8")

    service = ImportService()
    res = service.validate_file(file)
    assert res.errors[0].field == "longitude"


def test_54_valid_and_invalid_rows_coexist(tmp_path):
    """54. Корректные и некорректные строки сосуществуют в отчете."""
    file = tmp_path / "test.csv"
    file.write_text(
        "lat;lon\n"
        "56.0;47.0\n"
        "200.0;47.0\n"
        "56.5;47.5\n",
        encoding="utf-8",
    )

    service = ImportService()
    res = service.validate_file(file)
    assert res.total_rows == 3
    assert res.valid_rows == 2
    assert res.invalid_rows == 1
    assert len(res.points) == 2


def test_55_import_result_counts_correct(tmp_path):
    """55. Подсчет общего количества, валидных и невалидных строк точен."""
    file = tmp_path / "test.csv"
    file.write_text(
        "lat;lon\n"
        "56.1;47.1\n"
        "56.2;47.2\n"
        "bad;bad\n"
        "56.4;47.4\n",
        encoding="utf-8",
    )

    service = ImportService()
    res = service.validate_file(file)
    assert res.total_rows == 4
    assert res.valid_rows == 3
    assert res.invalid_rows == 1


def test_56_user_names_preserved(tmp_path):
    """56. Пользовательские имена точек сохраняются без изменений."""
    file = tmp_path / "test.csv"
    file.write_text("name;lat;lon\nМой Пункт №42;56.0;47.0\n", encoding="utf-8")

    service = ImportService()
    res = service.validate_file(file)
    assert res.points[0].name == "Мой Пункт №42"


def test_57_whitespace_trimmed(tmp_path):
    """57. Краевые пробелы в именах и ячейках аккуратно обрезаются."""
    file = tmp_path / "test.csv"
    file.write_text("name;lat;lon\n   Центр   ;  56.0  ;  47.0  \n", encoding="utf-8")

    service = ImportService()
    res = service.validate_file(file)
    assert res.points[0].name == "Центр"


def test_58_exact_duplicates_warning(tmp_path):
    """58. Повторяющиеся координаты генерируют предупреждение, но не отбрасываются."""
    file = tmp_path / "test.csv"
    file.write_text(
        "name;lat;lon\n"
        "Точка 1;56.0;47.0\n"
        "Точка 2;56.0;47.0\n",
        encoding="utf-8",
    )

    service = ImportService()
    res = service.validate_file(file)
    assert res.valid_rows == 2
    assert len(res.warnings) == 1
    assert res.warnings[0].code == "import.warn.duplicate_coordinates"


# =============================================================================
# Section 61: Атомарное Undo / Redo (тесты 59–65)
# =============================================================================

def test_59_import_adds_all_valid_points(qapp, clean_settings):
    """59. Импорт добавляет все валидные точки в сервис и таблицу."""
    win = MainWindow()
    gpkg = get_default_geopackage_path()
    if gpkg and gpkg.exists():
        win.load_map(gpkg)

    p1 = MapPoint(id="p1", name="P1", latitude=56.1, longitude=47.1)
    p2 = MapPoint(id="p2", name="P2", latitude=56.2, longitude=47.2)

    cmd = ImportPointsCommand(
        points=[p1, p2],
        add_fn=win.point_controller._cmd_add_points,
        remove_fn=win.point_controller._cmd_remove_points,
        description="Импорт 2 точек",
    )
    win.point_controller.undo_manager.push(cmd, execute=True)

    assert len(win._point_service) == 2
    assert win.points_table.rowCount() == 2
    win.close()


def test_60_one_undo_removes_entire_import(qapp, clean_settings):
    """60. Одно нажатие Ctrl+Z удаляет весь импортированный пакет точек."""
    win = MainWindow()
    gpkg = get_default_geopackage_path()
    if gpkg and gpkg.exists():
        win.load_map(gpkg)

    p1 = MapPoint(id="p1", name="P1", latitude=56.1, longitude=47.1)
    p2 = MapPoint(id="p2", name="P2", latitude=56.2, longitude=47.2)

    cmd = ImportPointsCommand(
        points=[p1, p2],
        add_fn=win.point_controller._cmd_add_points,
        remove_fn=win.point_controller._cmd_remove_points,
    )
    win.point_controller.undo_manager.push(cmd, execute=True)
    assert len(win._point_service) == 2

    win.undo()
    assert len(win._point_service) == 0
    assert win.points_table.rowCount() == 0
    win.close()


def test_61_redo_restores_entire_import(qapp, clean_settings):
    """61. Нажатие Ctrl+Y возвращает весь импортированный пакет точек."""
    win = MainWindow()
    gpkg = get_default_geopackage_path()
    if gpkg and gpkg.exists():
        win.load_map(gpkg)

    p1 = MapPoint(id="p1", name="P1", latitude=56.1, longitude=47.1)
    p2 = MapPoint(id="p2", name="P2", latitude=56.2, longitude=47.2)

    cmd = ImportPointsCommand(
        points=[p1, p2],
        add_fn=win.point_controller._cmd_add_points,
        remove_fn=win.point_controller._cmd_remove_points,
    )
    win.point_controller.undo_manager.push(cmd, execute=True)
    win.undo()
    assert len(win._point_service) == 0

    win.redo()
    assert len(win._point_service) == 2
    assert win.points_table.rowCount() == 2
    win.close()


def test_62_ids_stable_across_undo_redo(qapp, clean_settings):
    """62. Идентификаторы точек сохраняются стабильными при Undo / Redo."""
    win = MainWindow()
    gpkg = get_default_geopackage_path()
    if gpkg and gpkg.exists():
        win.load_map(gpkg)

    p1 = MapPoint(id="id-stable-1", name="P1", latitude=56.1, longitude=47.1)
    cmd = ImportPointsCommand(
        points=[p1],
        add_fn=win.point_controller._cmd_add_points,
        remove_fn=win.point_controller._cmd_remove_points,
    )
    win.point_controller.undo_manager.push(cmd, execute=True)
    win.undo()
    win.redo()

    pts = win._point_service.get_points()
    assert len(pts) == 1
    assert pts[0].id == "id-stable-1"
    win.close()


def test_63_zones_restored_on_redo(qapp, clean_settings):
    """63. Геодезические зоны корректно восстанавливаются при Redo."""
    win = MainWindow()
    gpkg = get_default_geopackage_path()
    if gpkg and gpkg.exists():
        win.load_map(gpkg)

    p1 = MapPoint(id="p1", name="P1", latitude=56.1, longitude=47.1, zone_enabled=True, radius_m=1000)
    cmd = ImportPointsCommand(
        points=[p1],
        add_fn=win.point_controller._cmd_add_points,
        remove_fn=win.point_controller._cmd_remove_points,
    )
    win.point_controller.undo_manager.push(cmd, execute=True)
    win.undo()
    win.redo()

    pts = win._point_service.get_points()
    assert pts[0].zone_enabled is True
    assert pts[0].radius_m == 1000.0
    win.close()


def test_64_styles_restored_on_redo(qapp, clean_settings):
    """64. Стили маркеров корректно восстанавливаются при Redo."""
    win = MainWindow()
    gpkg = get_default_geopackage_path()
    if gpkg and gpkg.exists():
        win.load_map(gpkg)

    p1 = MapPoint(id="p1", name="P1", latitude=56.1, longitude=47.1, symbol="square", size=20.0, red=50, green=150, blue=250)
    cmd = ImportPointsCommand(
        points=[p1],
        add_fn=win.point_controller._cmd_add_points,
        remove_fn=win.point_controller._cmd_remove_points,
    )
    win.point_controller.undo_manager.push(cmd, execute=True)
    win.undo()
    win.redo()

    pts = win._point_service.get_points()
    assert pts[0].symbol == "square"
    assert pts[0].size == 20.0
    assert (pts[0].red, pts[0].green, pts[0].blue) == (50, 150, 250)
    win.close()


def test_65_dirty_state_correct_with_undo_redo(qapp, clean_settings):
    """65. Dirty state проекта синхронизируется с Undo / Redo импорта."""
    win = MainWindow()
    assert not win.is_modified

    p1 = MapPoint(id="p1", name="P1", latitude=56.1, longitude=47.1)
    cmd = ImportPointsCommand(
        points=[p1],
        add_fn=win.point_controller._cmd_add_points,
        remove_fn=win.point_controller._cmd_remove_points,
    )
    win.point_controller.undo_manager.push(cmd, execute=True)
    assert win.is_modified

    win.undo()
    assert not win.is_modified

    win.redo()
    assert win.is_modified
    win.close()


# =============================================================================
# Section 62: Интерфейс и Drag & Drop (тесты 66–74)
# =============================================================================

def test_66_import_points_action_exists(qapp):
    """66. Меню 'Импорт' содержит действие 'Импортировать точки...'."""
    win = MainWindow()
    assert hasattr(win, "import_points_action")
    assert win.import_points_action in win.import_menu.actions()
    win.close()


def test_67_basic_dialog_ru(qapp):
    """67. Базовый диалог импорта в русской локализации."""
    set_language("ru")
    dlg = ImportDialog()
    assert dlg.windowTitle() == "Импорт точек"
    assert "Файл" in dlg.findChild(QGroupBox).title()
    dlg.close()


def test_68_basic_dialog_en(qapp):
    """68. Базовый диалог импорта в английской локализации."""
    set_language("en")
    dlg = ImportDialog()
    assert dlg.windowTitle() == "Import Points"
    assert "File" in dlg.findChild(QGroupBox).title()
    set_language("ru")
    dlg.close()


def test_69_last_import_directory_persists(clean_settings):
    """69. Последний использованный каталог импорта сохраняется в AppSettingsService."""
    settings = AppSettingsService()
    settings.set_last_import_directory("/some/import/dir/file.csv")
    assert Path(settings.get_last_import_directory()) == Path("/some/import/dir")


def test_70_drag_drop_xlsx_opens_importer(qapp, tmp_path, monkeypatch):
    """70. Drag & Drop файла .xlsx открывает диалог импорта."""
    win = MainWindow()
    f = tmp_path / "data.xlsx"
    wb = openpyxl.Workbook()
    wb.save(str(f))
    wb.close()

    opened = []
    monkeypatch.setattr(win.import_controller, "open_import_dialog", lambda path: opened.append(path))

    ev = MockDragDropEvent([str(f)])
    win.dragEnterEvent(ev)
    assert ev.isAccepted()

    win.dropEvent(ev)
    assert len(opened) == 1
    assert opened[0] == f
    win.close()


def test_71_drag_drop_csv_opens_importer(qapp, tmp_path, monkeypatch):
    """71. Drag & Drop файла .csv открывает диалог импорта."""
    win = MainWindow()
    f = tmp_path / "data.csv"
    f.touch()

    opened = []
    monkeypatch.setattr(win.import_controller, "open_import_dialog", lambda path: opened.append(path))

    ev = MockDragDropEvent([str(f)])
    win.dragEnterEvent(ev)
    assert ev.isAccepted()

    win.dropEvent(ev)
    assert len(opened) == 1
    win.close()


def test_72_drag_drop_txt_opens_importer(qapp, tmp_path, monkeypatch):
    """72. Drag & Drop файла .txt открывает диалог импорта."""
    win = MainWindow()
    f = tmp_path / "data.txt"
    f.touch()

    opened = []
    monkeypatch.setattr(win.import_controller, "open_import_dialog", lambda path: opened.append(path))

    ev = MockDragDropEvent([str(f)])
    win.dragEnterEvent(ev)
    assert ev.isAccepted()

    win.dropEvent(ev)
    assert len(opened) == 1
    win.close()


def test_73_all_invalid_disables_import(qapp, tmp_path):
    """73. Если все строки невалидны, кнопка 'Импортировать' отключена."""
    f = tmp_path / "all_bad.csv"
    f.write_text("lat;lon\nbad1;bad2\n", encoding="utf-8")

    dlg = ImportDialog(file_path=f)
    assert not dlg.btn_import.isEnabled()
    dlg.close()


def test_74_valid_only_import_works(qapp, tmp_path):
    """74. При наличии смешанных строк кнопка предлагает импортировать только корректные."""
    f = tmp_path / "mixed.csv"
    f.write_text("lat;lon\n56.0;47.0\nbad;bad\n", encoding="utf-8")

    dlg = ImportDialog(file_path=f)
    assert dlg.btn_import.isEnabled()
    assert dlg.result.valid_rows == 1
    assert len(dlg.get_valid_points()) == 1
    dlg.close()


# =============================================================================
# Section 63: Тест производительности (тест 75)
# =============================================================================

def test_75_performance_several_thousand_rows(tmp_path):
    """75. Парсинг и валидация нескольких тысяч строк без квадратичной деградации O(n²)."""
    f = tmp_path / "large.csv"
    lines = ["name;latitude;longitude;symbol;size;radius;radius_unit"]
    for i in range(3000):
        lines.append(f"Point_{i};56.{i:05d};47.{i:05d};circle;12;{(i % 1000) + 1};m")
    f.write_text("\n".join(lines), encoding="utf-8")

    start = time.perf_counter()
    service = ImportService()
    res = service.validate_file(f)
    elapsed = time.perf_counter() - start

    assert res.total_rows == 3000
    assert res.valid_rows == 3000
    assert res.invalid_rows == 0
    # 3000 строк должны валидироваться менее чем за 5 секунд на любом нормальном компьютере
    assert elapsed < 5.0
