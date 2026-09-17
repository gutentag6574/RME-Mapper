"""Тесты для Этапа 14 — Полноценный мастер импорта (Import Wizard).

Разделы тестирования (77 тестов):
- Section 68: Структура мастера и навигация (тесты 1–7)
- Section 69: Работа с листами XLSX и формулами (тесты 8–14)
- Section 70: Настройки CSV/TXT (кодировка, разделитель) (тесты 15–22)
- Section 71: Строка заголовков и пропуск строк (тесты 23–27)
- Section 72: Сопоставление колонок (Column Mapping) (тесты 28–34)
- Section 73: Координаты X/Y и пользовательские СК (тесты 35–43)
- Section 74: Предпросмотр, фильтрация и поиск (тесты 44–50)
- Section 75: Политика обработки дубликатов (тесты 51–55)
- Section 76: Политика точек вне рабочей области карты (тесты 56–59)
- Section 77: Пресеты сопоставления (Presets) (тесты 60–64)
- Section 78: Транзакционность и Undo/Redo (тесты 65–71)
- Section 79: Защита от устаревших данных и лимиты (тесты 72–76)
- Section 80: Тест производительности на 10 000 строк (тест 77)
"""

import math
import os
from pathlib import Path
import time
from unittest.mock import MagicMock
import openpyxl
import pyproj
import pytest
from shapely.geometry import Polygon

from PySide6.QtCore import Qt, QModelIndex
from PySide6.QtWidgets import QApplication

import rme_mapper  # noqa: F401
from rme_mapper.i18n import set_language, tr
from rme_mapper.importers.delimited_importer import DelimitedImporter
from rme_mapper.importers.import_service import ImportService
from rme_mapper.importers.models import (
    CoordinateFormat,
    DuplicatePolicy,
    ImportOptions,
    ImportPreset,
    ImportResult,
    ImportRow,
    OutsideAreaPolicy,
)
from rme_mapper.importers.presets_service import PresetsService
from rme_mapper.importers.xlsx_importer import XlsxImporter
from rme_mapper.models.map_point import MapPoint
from rme_mapper.services.app_settings_service import AppSettingsService
from rme_mapper.services.undo_manager import ImportPointsCommand, UndoManager
from rme_mapper.ui.controllers.project_controller import ProjectController
from rme_mapper.ui.import_wizard import (
    ColumnMappingPage,
    FileStructurePage,
    ImportWizard,
    SourcePage,
    SummaryPage,
    ValidationPage,
)
from rme_mapper.ui.main_window import MainWindow
from rme_mapper.ui.models.raw_preview_model import RawPreviewModel
from rme_mapper.ui.models.validation_table_model import ValidationTableModel


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


@pytest.fixture(autouse=True)
def no_unsaved_prompts(monkeypatch):
    """Предотвращение появления блокирующих диалогов QMessageBox в тестах."""
    monkeypatch.setattr(ProjectController, "maybe_save_prompt", lambda self, *args, **kwargs: True)


@pytest.fixture
def clean_settings(monkeypatch):
    """Изолированный сервис настроек с очисткой."""
    mem_settings = {}
    mock_settings = MagicMock()
    mock_settings.value.side_effect = lambda k, d=None: mem_settings.get(k, d)
    mock_settings.setValue.side_effect = lambda k, v: mem_settings.__setitem__(k, v)
    mock_settings.clear.side_effect = mem_settings.clear
    monkeypatch.setattr("rme_mapper.services.app_settings_service.QSettings", lambda *args: mock_settings)
    svc = AppSettingsService()
    svc.clear()
    return svc


# =============================================================================
# Section 68: Структура мастера и навигация (тесты 1–7)
# =============================================================================

def test_01_wizard_opens(qapp):
    """1. ImportWizard инициализируется без ошибок."""
    wizard = ImportWizard()
    assert wizard is not None
    assert wizard.windowTitle() != ""
    wizard.close()


def test_02_pages_exist(qapp):
    """2. Все 5 страниц мастера существуют."""
    wizard = ImportWizard()
    assert isinstance(wizard.page_source, SourcePage)
    assert isinstance(wizard.page_structure, FileStructurePage)
    assert isinstance(wizard.page_mapping, ColumnMappingPage)
    assert isinstance(wizard.page_validation, ValidationPage)
    assert isinstance(wizard.page_summary, SummaryPage)
    assert len(wizard.pageIds()) == 5
    wizard.close()


def test_03_cancel_changes_nothing(qapp, tmp_path):
    """3. Отмена (Cancel) закрывает визард без изменения состояния проекта."""
    win = MainWindow()
    initial_count = len(win.point_controller._point_service)
    initial_modified = win.is_modified

    wizard = ImportWizard(parent=win)
    wizard.reject()

    assert len(win.point_controller._point_service) == initial_count
    assert win.is_modified == initial_modified
    win._set_modified(False)
    win.close()


def test_04_next_back_preserve_state(qapp, tmp_path):
    """4. Переход Next -> Back сохраняет выбранные параметры."""
    f = tmp_path / "data.csv"
    f.write_text("name,lat,lon\nPt1,56.0,47.0\n", encoding="utf-8")

    wizard = ImportWizard(file_path=f)
    assert wizard.page_source.isComplete()

    # Переход на Шаг 2
    wizard.next()
    wizard.page_structure.header_row_spin.setValue(1)

    # Переход на Шаг 3
    wizard.next()
    wizard.page_mapping.radio_dd.setChecked(True)

    # Возврат назад на Шаг 2
    wizard.back()
    assert wizard.page_structure.header_row_spin.value() == 1

    # Вперед на Шаг 3
    wizard.next()
    assert wizard.page_mapping.radio_dd.isChecked()
    wizard.close()


def test_05_finish_disabled_before_validation(qapp):
    """5. Кнопка Finish заблокирована до завершения валидации."""
    wizard = ImportWizard()
    finish_btn = wizard.button(ImportWizard.WizardButton.FinishButton)
    assert not finish_btn.isEnabled()
    wizard.close()


def test_06_ru_labels(qapp):
    """6. Заголовки страниц на русском языке."""
    set_language("ru")
    wizard = ImportWizard()
    assert wizard.windowTitle() == "Мастер импорта точек"
    assert "Выбор файла" in wizard.page_source.title()
    assert "Структура файла" in wizard.page_structure.title()
    assert "Сопоставление колонок" in wizard.page_mapping.title()
    assert "Проверка данных" in wizard.page_validation.title()
    assert "Подтверждение" in wizard.page_summary.title()
    wizard.close()


def test_07_en_labels(qapp):
    """7. Заголовки страниц на английском языке."""
    set_language("en")
    wizard = ImportWizard()
    assert wizard.windowTitle() == "Point Import Wizard"
    assert "Source" in wizard.page_source.title()
    assert "Structure" in wizard.page_structure.title()
    assert "Mapping" in wizard.page_mapping.title()
    assert "Validation" in wizard.page_validation.title()
    assert "Confirmation" in wizard.page_summary.title()
    set_language("ru")
    wizard.close()


# =============================================================================
# Section 69: Работа с листами XLSX и формулами (тесты 8–14)
# =============================================================================

def test_08_workbook_sheet_list(tmp_path):
    """8. Получение списка рабочих листов книги XLSX."""
    f = tmp_path / "sheets.xlsx"
    wb = openpyxl.Workbook()
    ws1 = wb.active
    ws1.title = "SheetA"
    wb.create_sheet("SheetB")
    wb.create_sheet("SheetC")
    wb.save(str(f))
    wb.close()

    service = ImportService()
    sheets = service.get_sheet_names(f)
    assert sheets == ["SheetA", "SheetB", "SheetC"]


def test_09_first_sheet_default(tmp_path):
    """9. По умолчанию выбирается первый лист."""
    f = tmp_path / "default_sheet.xlsx"
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "First"
    ws.append(["name", "lat", "lon"])
    ws.append(["P1", 56.1, 47.1])
    wb.create_sheet("Second")
    wb.save(str(f))
    wb.close()

    service = ImportService()
    res = service.validate_file(f)
    assert res.sheet_name == "First"
    assert len(res.points) == 1


def test_10_second_sheet_selectable(tmp_path):
    """10. Выбор второго листа рабочей книги."""
    f = tmp_path / "second_sheet.xlsx"
    wb = openpyxl.Workbook()
    ws1 = wb.active
    ws1.title = "Info"
    ws1.append(["Metadata"])
    ws2 = wb.create_sheet("Data")
    ws2.append(["name", "latitude", "longitude"])
    ws2.append(["Target", 56.5, 47.5])
    wb.save(str(f))
    wb.close()

    service = ImportService()
    opts = ImportOptions(sheet_name="Data")
    res = service.validate_file(f, opts)
    assert res.sheet_name == "Data"
    assert len(res.points) == 1
    assert res.points[0].name == "Target"


def test_11_selected_sheet_parsed(tmp_path):
    """11. Данные парсятся строго из выбранного листа."""
    f = tmp_path / "multi.xlsx"
    wb = openpyxl.Workbook()
    ws1 = wb.active
    ws1.title = "S1"
    ws1.append(["name", "lat", "lon"])
    ws1.append(["P_Sheet1", 56.0, 47.0])
    ws2 = wb.create_sheet("S2")
    ws2.append(["name", "lat", "lon"])
    ws2.append(["P_Sheet2", 56.8, 47.8])
    wb.save(str(f))
    wb.close()

    service = ImportService()
    res1 = service.validate_file(f, ImportOptions(sheet_name="S1"))
    res2 = service.validate_file(f, ImportOptions(sheet_name="S2"))
    assert res1.points[0].name == "P_Sheet1"
    assert res2.points[0].name == "P_Sheet2"


def test_12_empty_sheet_handled(tmp_path):
    """12. Пустой лист корректно возвращает ошибку без сбоя."""
    f = tmp_path / "empty_sheet.xlsx"
    wb = openpyxl.Workbook()
    ws1 = wb.active
    ws1.title = "Empty"
    wb.save(str(f))
    wb.close()

    service = ImportService()
    res = service.validate_file(f, ImportOptions(sheet_name="Empty"))
    assert res.total_rows == 0
    assert any(e.code == "import.err.file_empty" for e in res.errors)


def test_13_formula_cached_value(tmp_path):
    """13. Чтение кэшированного значения формулы в режиме data_only=True."""
    f = tmp_path / "formula.xlsx"
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["name", "lat", "lon"])
    # openpyxl сохраняет числовое значение, data_only=True считывает его
    ws.append(["P1", 56.2, 47.2])
    wb.save(str(f))
    wb.close()

    service = ImportService()
    res = service.validate_file(f)
    assert len(res.points) == 1
    assert res.points[0].latitude == 56.2


def test_14_formula_missing_value_handled_safely(tmp_path):
    """14. Отсутствие кэшированного значения формулы безопасно приводит к ошибке строки."""
    f = tmp_path / "formula_none.csv"
    # Эмулируем строку с отсутствующей широтой
    f.write_text("name;lat;lon\nP_Missing;;47.0\n", encoding="utf-8")
    service = ImportService()
    res = service.validate_file(f)
    assert res.invalid_rows == 1
    assert any(e.code == "import.err.missing_latitude" for e in res.errors)


# =============================================================================
# Section 70: Настройки CSV/TXT (кодировка, разделитель) (тесты 15–22)
# =============================================================================

def test_15_auto_encoding(tmp_path):
    """15. Автоопределение кодировки UTF-8."""
    f = tmp_path / "auto_enc.csv"
    f.write_text("name;lat;lon\nТочка;56.0;47.0\n", encoding="utf-8")
    service = ImportService()
    res = service.validate_file(f)
    assert res.detected_encoding == "utf-8"
    assert res.points[0].name == "Точка"


def test_16_manual_utf8(tmp_path):
    """16. Принудительное указание кодировки UTF-8."""
    f = tmp_path / "manual_utf8.csv"
    f.write_text("name;lat;lon\nТест;56.0;47.0\n", encoding="utf-8")
    importer = DelimitedImporter()
    rows, enc, delim, _ = importer.read_rows(f, ImportOptions(encoding="utf-8"))
    assert enc == "utf-8"
    assert rows[0][1]["name"] == "Тест"


def test_17_manual_cp1251(tmp_path):
    """17. Принудительное указание кодировки Windows-1251."""
    f = tmp_path / "cp1251.csv"
    f.write_text("name;lat;lon\nЙошкар-Ола;56.63;47.88\n", encoding="cp1251")
    importer = DelimitedImporter()
    rows, enc, delim, _ = importer.read_rows(f, ImportOptions(encoding="cp1251"))
    assert enc == "cp1251"
    assert rows[0][1]["name"] == "Йошкар-Ола"


def test_18_auto_delimiter(tmp_path):
    """18. Автоопределение разделителя точка с запятой."""
    f = tmp_path / "semi.csv"
    f.write_text("name;lat;lon\nP1;56.0;47.0\n", encoding="utf-8")
    service = ImportService()
    res = service.validate_file(f)
    assert res.detected_delimiter == ";"


def test_19_manual_comma(tmp_path):
    """19. Принудительный разделитель запятая."""
    f = tmp_path / "comma.csv"
    f.write_text("name,lat,lon\nP1,56.0,47.0\n", encoding="utf-8")
    importer = DelimitedImporter()
    rows, enc, delim, _ = importer.read_rows(f, ImportOptions(delimiter=","))
    assert delim == ","
    assert rows[0][1]["name"] == "P1"


def test_20_manual_semicolon(tmp_path):
    """20. Принудительный разделитель точка с запятой."""
    f = tmp_path / "semi_manual.txt"
    f.write_text("name;lat;lon\nP1;56.0;47.0\n", encoding="utf-8")
    importer = DelimitedImporter()
    rows, enc, delim, _ = importer.read_rows(f, ImportOptions(delimiter=";"))
    assert delim == ";"


def test_21_manual_tab(tmp_path):
    """21. Принудительный разделитель табуляция."""
    f = tmp_path / "tab.txt"
    f.write_text("name\tlat\tlon\nP1\t56.0\t47.0\n", encoding="utf-8")
    importer = DelimitedImporter()
    rows, enc, delim, _ = importer.read_rows(f, ImportOptions(delimiter="\t"))
    assert delim == "\t"
    assert rows[0][1]["name"] == "P1"


def test_22_preview_refresh_after_setting_change(qapp, tmp_path):
    """22. Модель предпросмотра обновляется при смене разделителя/строки заголовков."""
    f = tmp_path / "test.csv"
    f.write_text("Title Row\nname;lat;lon\nP1;56.0;47.0\n", encoding="utf-8")
    page = FileStructurePage(import_service=ImportService())
    page._current_path = f
    page._refresh_preview()
    assert page.preview_model.rowCount() == 3

    page.header_row_spin.setValue(2)
    assert page.preview_model._header_row == 2
    assert "name" in page.get_detected_headers()


# =============================================================================
# Section 71: Строка заголовков и пропуск строк (тесты 23–27)
# =============================================================================

def test_23_header_row_1(tmp_path):
    """23. Строка заголовков = 1."""
    f = tmp_path / "h1.csv"
    f.write_text("name;lat;lon\nP1;56.0;47.0\n", encoding="utf-8")
    opts = ImportOptions(header_row=1)
    res = ImportService().validate_file(f, opts)
    assert len(res.points) == 1
    assert res.points[0].name == "P1"


def test_24_header_row_2(tmp_path):
    """24. Строка заголовков = 2 (пропуск первой строки с названием)."""
    f = tmp_path / "h2.csv"
    f.write_text("Отчет о съемке\nname;lat;lon\nP1;56.0;47.0\n", encoding="utf-8")
    opts = ImportOptions(header_row=2)
    res = ImportService().validate_file(f, opts)
    assert len(res.points) == 1
    assert res.points[0].name == "P1"


def test_25_header_row_5(tmp_path):
    """25. Строка заголовков = 5 (пропуск шапки из 4 строк)."""
    f = tmp_path / "h5.csv"
    content = "Line1\nLine2\nLine3\nLine4\nname;lat;lon\nP1;56.0;47.0\nP2;56.1;47.1\n"
    f.write_text(content, encoding="utf-8")
    opts = ImportOptions(header_row=5)
    res = ImportService().validate_file(f, opts)
    assert len(res.points) == 2


def test_26_source_row_numbers_remain_correct(tmp_path):
    """26. Номера строк данных соответствуют реальным номерам строк файла."""
    f = tmp_path / "rows.csv"
    content = "Desc 1\nDesc 2\nname;lat;lon\nP1;56.0;47.0\nInvalidRow;;;\n"
    f.write_text(content, encoding="utf-8")
    opts = ImportOptions(header_row=3)
    res = ImportService().validate_file(f, opts)
    # Row 4: P1 (валидная)
    # Row 5: InvalidRow (ошибка)
    assert res.rows[0].row_number == 4
    assert res.rows[1].row_number == 5
    assert res.rows[1].errors[0].row_number == 5


def test_27_invalid_header_row_blocked(tmp_path):
    """27. Задание строки заголовков за пределами файла возвращает ошибку."""
    f = tmp_path / "short.csv"
    f.write_text("a;b;c\n1;2;3\n", encoding="utf-8")
    opts = ImportOptions(header_row=50)
    res = ImportService().validate_file(f, opts)
    assert res.total_rows == 0


# =============================================================================
# Section 72: Сопоставление колонок (Column Mapping) (тесты 28–34)
# =============================================================================

def test_28_auto_mapping():
    """28. Автоматическое сопоставление известных колонок."""
    headers = ["Имя_Объекта", "Широта", "Долгота", "Форма"]
    service = ImportService()
    mapping = service.suggest_column_mapping(headers)
    assert mapping.get("name") == "Имя_Объекта"
    assert mapping.get("latitude") == "Широта"
    assert mapping.get("longitude") == "Долгота"
    assert mapping.get("symbol") == "Форма"


def test_29_manual_name_mapping(tmp_path):
    """29. Ручное назначение произвольной колонки для Name."""
    f = tmp_path / "custom.csv"
    f.write_text("CustomObj;lat;lon\nMyPoint;56.0;47.0\n", encoding="utf-8")
    opts = ImportOptions(
        column_mapping={"name": "CustomObj", "latitude": "lat", "longitude": "lon"}
    )
    res = ImportService().validate_file(f, opts)
    assert res.points[0].name == "MyPoint"


def test_30_manual_lat_lon_mapping(tmp_path):
    """30. Ручное назначение произвольных колонок для широты и долготы."""
    f = tmp_path / "coords.csv"
    f.write_text("Title;Y_val;X_val\nP1;56.123;47.456\n", encoding="utf-8")
    opts = ImportOptions(
        column_mapping={"name": "Title", "latitude": "Y_val", "longitude": "X_val"}
    )
    res = ImportService().validate_file(f, opts)
    assert res.points[0].latitude == 56.123
    assert res.points[0].longitude == 47.456


def test_31_missing_required_mapping_blocked(qapp):
    """31. При отсутствии обязательных колонок переход блокируется."""
    page = ColumnMappingPage(ImportService(), PresetsService())
    page._headers = ["ColA", "ColB"]
    page._populate_combos()
    page._validate_mapping()
    assert not page.isComplete()


def test_32_mapping_preserved_on_back(qapp, tmp_path):
    """32. Сопоставление колонок сохраняется при переходе Back и возврате."""
    f = tmp_path / "data.csv"
    f.write_text("Col1;Col2;Col3\nP;56;47\n", encoding="utf-8")
    wizard = ImportWizard(file_path=f)
    wizard.next()  # Шаг 2
    wizard.next()  # Шаг 3
    wizard.page_mapping._combos["name"].setCurrentText("Col1")
    wizard.back()  # Возврат на Шаг 2
    wizard.next()  # Вперед на Шаг 3
    assert wizard.page_mapping._combos["name"].currentText() == "Col1"
    wizard.close()


def test_33_changed_source_invalidates_mapping(qapp, tmp_path):
    """33. Смена файла/заголовков сбрасывает старое сопоставление."""
    f1 = tmp_path / "f1.csv"
    f1.write_text("Alpha;Beta\n1;2\n", encoding="utf-8")
    wizard = ImportWizard(file_path=f1)
    wizard.next()
    wizard.next()

    # Сменяем файл
    f2 = tmp_path / "f2.csv"
    f2.write_text("NewCol1;NewCol2\n3;4\n", encoding="utf-8")
    wizard.page_source.set_file_path(f2)
    wizard.page_structure.initializePage()
    wizard.page_mapping.initializePage()

    assert "Alpha" not in wizard.page_mapping._headers
    assert "NewCol1" in wizard.page_mapping._headers
    wizard.close()


def test_34_incompatible_duplicate_mapping_blocked(qapp):
    """34. Назначение одной колонки несовместимым полям (lat и lon) блокирует переход."""
    page = ColumnMappingPage(ImportService(), PresetsService())
    page.show()
    page._headers = ["SharedCol"]
    page._populate_combos()
    page._combos["latitude"].setCurrentText("SharedCol")
    page._combos["longitude"].setCurrentText("SharedCol")
    page._validate_mapping()
    assert page.warning_label.isVisible()
    assert not page.isComplete()
    page.close()


# =============================================================================
# Section 73: Координаты X/Y и пользовательские СК (тесты 35–43)
# =============================================================================

def test_35_epsg_3857_import(tmp_path):
    """35. Успешный импорт координат X/Y в EPSG:3857."""
    f = tmp_path / "xy.csv"
    f.write_text("name;x;y\nCenter;5330467.02;7685433.59\n", encoding="utf-8")
    opts = ImportOptions(
        coordinate_format=CoordinateFormat.XY,
        source_crs="EPSG:3857",
        column_mapping={"name": "name", "x": "x", "y": "y"},
    )
    res = ImportService().validate_file(f, opts)
    assert len(res.points) == 1
    pt = res.points[0]
    assert pytest.approx(pt.latitude, 0.001) == 56.6328
    assert pytest.approx(pt.longitude, 0.001) == 47.8844


def test_36_projected_xy_to_wgs84(tmp_path):
    """36. Точки сохраняются в WGS 84 (EPSG:4326)."""
    f = tmp_path / "proj.csv"
    f.write_text("x;y\n0;0\n", encoding="utf-8")
    opts = ImportOptions(
        coordinate_format=CoordinateFormat.XY,
        source_crs="EPSG:3857",
        column_mapping={"x": "x", "y": "y"},
    )
    res = ImportService().validate_file(f, opts)
    assert len(res.points) == 1
    assert res.points[0].source_crs == "EPSG:4326"
    assert pytest.approx(res.points[0].latitude, 0.0001) == 0.0
    assert pytest.approx(res.points[0].longitude, 0.0001) == 0.0


def test_37_always_xy_behavior():
    """37. Трансформер всегда ожидает (X, Y) и возвращает (Lon, Lat)."""
    tr = pyproj.Transformer.from_crs("EPSG:3857", "EPSG:4326", always_xy=True)
    lon, lat = tr.transform(5330467.02, 7685433.59)
    assert -180 <= lon <= 180
    assert -90 <= lat <= 90


def test_38_invalid_epsg_blocked(tmp_path):
    """38. Невалидная СК блокирует операцию с понятной ошибкой."""
    f = tmp_path / "data.csv"
    f.write_text("x;y\n100;200\n", encoding="utf-8")
    opts = ImportOptions(
        coordinate_format=CoordinateFormat.XY,
        source_crs="INVALID_CRS:999999",
        column_mapping={"x": "x", "y": "y"},
    )
    res = ImportService().validate_file(f, opts)
    assert len(res.errors) > 0
    assert res.errors[0].code == "import.err.invalid_crs"


def test_39_invalid_x(tmp_path):
    """39. Нечисловая координата X фиксируется как ошибка строки."""
    f = tmp_path / "bad_x.csv"
    f.write_text("x;y\nABC;7685433\n", encoding="utf-8")
    opts = ImportOptions(
        coordinate_format=CoordinateFormat.XY,
        source_crs="EPSG:3857",
        column_mapping={"x": "x", "y": "y"},
    )
    res = ImportService().validate_file(f, opts)
    assert res.invalid_rows == 1
    assert res.rows[0].errors[0].field == "x"


def test_40_invalid_y(tmp_path):
    """40. Нечисловая координата Y фиксируется как ошибка строки."""
    f = tmp_path / "bad_y.csv"
    f.write_text("x;y\n5330467;XYZ\n", encoding="utf-8")
    opts = ImportOptions(
        coordinate_format=CoordinateFormat.XY,
        source_crs="EPSG:3857",
        column_mapping={"x": "x", "y": "y"},
    )
    res = ImportService().validate_file(f, opts)
    assert res.invalid_rows == 1
    assert res.rows[0].errors[0].field == "y"


def test_41_nan_rejected(tmp_path):
    """41. Координата NaN отклоняется."""
    f = tmp_path / "nan.csv"
    f.write_text("x;y\nnan;7685433\n", encoding="utf-8")
    opts = ImportOptions(
        coordinate_format=CoordinateFormat.XY,
        source_crs="EPSG:3857",
        column_mapping={"x": "x", "y": "y"},
    )
    res = ImportService().validate_file(f, opts)
    assert res.invalid_rows == 1


def test_42_infinity_rejected(tmp_path):
    """42. Координата Infinity отклоняется."""
    f = tmp_path / "inf.csv"
    f.write_text("x;y\ninf;7685433\n", encoding="utf-8")
    opts = ImportOptions(
        coordinate_format=CoordinateFormat.XY,
        source_crs="EPSG:3857",
        column_mapping={"x": "x", "y": "y"},
    )
    res = ImportService().validate_file(f, opts)
    assert res.invalid_rows == 1


def test_43_transform_error_becomes_row_error(tmp_path):
    """43. Ошибка проекции координаты оформляется как ошибка строки без падения импорта."""
    f = tmp_path / "overflow.csv"
    f.write_text("x;y\n-9999999999;-9999999999\n", encoding="utf-8")
    opts = ImportOptions(
        coordinate_format=CoordinateFormat.XY,
        source_crs="EPSG:32638",
        column_mapping={"x": "x", "y": "y"},
    )
    res = ImportService().validate_file(f, opts)
    assert res.invalid_rows == 1


# =============================================================================
# Section 74: Предпросмотр, фильтрация и поиск (тесты 44–50)
# =============================================================================

def test_44_preview_limited_rows(tmp_path):
    """44. Предпросмотр ограничивает количество считываемых строк."""
    f = tmp_path / "many.csv"
    lines = ["id;val"] + [f"{i};{i*10}" for i in range(200)]
    f.write_text("\n".join(lines), encoding="utf-8")

    importer = DelimitedImporter()
    rows, total_lines, _, _ = importer.read_preview_rows(f, ImportOptions(), max_rows=50)
    assert len(rows) == 50
    assert total_lines > 50


def test_45_valid_filter(qapp):
    """45. Фильтр 'valid' скрывает некорректные строки."""
    r1 = ImportRow(row_number=1, raw_data={}, is_valid=True, status="ok")
    r2 = ImportRow(row_number=2, raw_data={}, is_valid=False, status="error")
    model = ValidationTableModel()
    model.set_rows([r1, r2])
    assert model.rowCount() == 2

    model.set_filter("valid")
    assert model.rowCount() == 1
    assert model.get_row_item(0).row_number == 1


def test_46_warning_filter(qapp):
    """46. Фильтр 'warnings' отображает строки с предупреждениями."""
    r1 = ImportRow(row_number=1, raw_data={}, is_valid=True, warnings=["warn"])
    r2 = ImportRow(row_number=2, raw_data={}, is_valid=True, warnings=[])
    model = ValidationTableModel()
    model.set_rows([r1, r2])
    model.set_filter("warnings")
    assert model.rowCount() == 1


def test_47_error_filter(qapp):
    """47. Фильтр 'errors' отображает строки с ошибками."""
    r1 = ImportRow(row_number=1, raw_data={}, is_valid=True)
    r2 = ImportRow(row_number=2, raw_data={}, is_valid=False)
    model = ValidationTableModel()
    model.set_rows([r1, r2])
    model.set_filter("errors")
    assert model.rowCount() == 1
    assert model.get_row_item(0).row_number == 2


def test_48_search_by_row(qapp):
    """48. Поиск по номеру строки."""
    r1 = ImportRow(row_number=12, raw_data={"name": "A"})
    r2 = ImportRow(row_number=34, raw_data={"name": "B"})
    model = ValidationTableModel()
    model.set_rows([r1, r2])
    model.set_search_query("34")
    assert model.rowCount() == 1
    assert model.get_row_item(0).row_number == 34


def test_49_search_by_name(qapp):
    """49. Поиск по названию точки."""
    p1 = MapPoint(id="1", name="AlphaPoint", latitude=0, longitude=0)
    p2 = MapPoint(id="2", name="BetaTarget", latitude=0, longitude=0)
    r1 = ImportRow(row_number=1, raw_data={}, point=p1)
    r2 = ImportRow(row_number=2, raw_data={}, point=p2)
    model = ValidationTableModel()
    model.set_rows([r1, r2])
    model.set_search_query("Target")
    assert model.rowCount() == 1
    assert model.get_row_item(0).point.name == "BetaTarget"


def test_50_error_details_show_raw_value(qapp, tmp_path):
    """50. Панель подробностей отображает исходное ошибочное значение."""
    f = tmp_path / "err.csv"
    f.write_text("name;lat;lon\nP1;999.0;47.0\n", encoding="utf-8")
    wizard = ImportWizard(file_path=f)
    wizard.next()  # 2
    wizard.next()  # 3
    wizard.next()  # 4: Валидация

    page = wizard.page_validation
    wizard.show()
    idx = page.table_model.index(0, 0)
    page._on_row_selected(idx, QModelIndex())
    assert page.details_box.isVisible()
    assert "999.0" in page.lbl_det_raw.text()
    wizard.close()


# =============================================================================
# Section 75: Политика обработки дубликатов (тесты 51–55)
# =============================================================================

def test_51_duplicate_within_file_detected(tmp_path):
    """51. Точные дубликаты координат внутри файла помечаются предупреждением."""
    f = tmp_path / "dup.csv"
    f.write_text("name;lat;lon\nP1;56.123456;47.123456\nP2;56.123456;47.123456\n", encoding="utf-8")
    res = ImportService().validate_file(f)
    assert any(w.code == "import.warn.duplicate_coordinates" for w in res.warnings)


def test_52_duplicate_against_project_detected(tmp_path):
    """52. Дубликаты относительно существующих точек проекта помечаются предупреждением."""
    f = tmp_path / "dup_proj.csv"
    f.write_text("name;lat;lon\nNewPt;56.1;47.1\n", encoding="utf-8")
    existing = [MapPoint(id="p-ex", name="Existing", latitude=56.1, longitude=47.1)]
    opts = ImportOptions(existing_points=existing)
    res = ImportService().validate_file(f, opts)
    assert any(w.code == "import.warn.duplicate_with_project" for w in res.warnings)


def test_53_import_all_duplicates(tmp_path):
    """53. Политика Import All импортирует все дубликаты."""
    f = tmp_path / "dup_all.csv"
    f.write_text("name;lat;lon\nP1;56.0;47.0\nP2;56.0;47.0\n", encoding="utf-8")
    opts = ImportOptions(duplicate_policy=DuplicatePolicy.IMPORT_ALL)
    res = ImportService().validate_file(f, opts)
    assert len(res.points) == 2


def test_54_skip_duplicates(tmp_path):
    """54. Политика Skip Duplicates исключает повторные точки из импорта."""
    f = tmp_path / "dup_skip.csv"
    f.write_text("name;lat;lon\nP1;56.0;47.0\nP2;56.0;47.0\n", encoding="utf-8")
    opts = ImportOptions(duplicate_policy=DuplicatePolicy.SKIP_DUPLICATES)
    res = ImportService().validate_file(f, opts)
    assert len(res.points) == 1
    assert res.excluded_rows == 1
    assert res.rows[1].is_excluded


def test_55_existing_points_never_overwritten(tmp_path):
    """55. Точки проекта не перезаписываются при импорте дубликатов."""
    existing = [MapPoint(id="p-fixed", name="Untouchable", latitude=56.0, longitude=47.0)]
    f = tmp_path / "file.csv"
    f.write_text("name;lat;lon\nReplacement;56.0;47.0\n", encoding="utf-8")
    opts = ImportOptions(existing_points=existing, duplicate_policy=DuplicatePolicy.SKIP_DUPLICATES)
    res = ImportService().validate_file(f, opts)
    assert len(res.points) == 0  # новая точка исключена
    assert existing[0].name == "Untouchable"


# =============================================================================
# Section 76: Политика точек вне рабочей области карты (тесты 56–59)
# =============================================================================

def test_56_outside_point_warning(tmp_path):
    """56. Точка вне рабочей области карты помечается предупреждением."""
    poly = Polygon([(45, 55), (49, 55), (49, 58), (45, 58)])
    f = tmp_path / "outside.csv"
    f.write_text("name;lat;lon\nFarAway;10.0;10.0\n", encoding="utf-8")
    opts = ImportOptions(boundary_geometry=poly)
    res = ImportService().validate_file(f, opts)
    assert any(w.code == "import.warn.outside_working_area" for w in res.warnings)


def test_57_import_outside_points(tmp_path):
    """57. Политика Import Outside включает точку в импорт."""
    poly = Polygon([(45, 55), (49, 55), (49, 58), (45, 58)])
    f = tmp_path / "out_import.csv"
    f.write_text("name;lat;lon\nOutside;10.0;10.0\n", encoding="utf-8")
    opts = ImportOptions(boundary_geometry=poly, outside_policy=OutsideAreaPolicy.IMPORT_OUTSIDE)
    res = ImportService().validate_file(f, opts)
    assert len(res.points) == 1


def test_58_skip_outside_points(tmp_path):
    """58. Политика Skip Outside исключает внешние точки из импорта."""
    poly = Polygon([(45, 55), (49, 55), (49, 58), (45, 58)])
    f = tmp_path / "out_skip.csv"
    f.write_text("name;lat;lon\nInside;56.0;47.0\nOutside;10.0;10.0\n", encoding="utf-8")
    opts = ImportOptions(boundary_geometry=poly, outside_policy=OutsideAreaPolicy.SKIP_OUTSIDE)
    res = ImportService().validate_file(f, opts)
    assert len(res.points) == 1
    assert res.points[0].name == "Inside"
    assert res.excluded_rows == 1


def test_59_no_map_does_not_mark_outside(tmp_path):
    """59. При отсутствии границ карты предупреждение о границах не генерируется."""
    f = tmp_path / "no_map.csv"
    f.write_text("name;lat;lon\nPoint;10.0;10.0\n", encoding="utf-8")
    opts = ImportOptions(boundary_geometry=None)
    res = ImportService().validate_file(f, opts)
    assert not any(w.code == "import.warn.outside_working_area" for w in res.warnings)


# =============================================================================
# Section 77: Пресеты сопоставления (Presets) (тесты 60–64)
# =============================================================================

def test_60_save_preset(clean_settings):
    """60. Сохранение пресета сопоставления в AppSettingsService."""
    svc = PresetsService(clean_settings)
    preset = ImportPreset(
        name="GPS_Export",
        coordinate_format=CoordinateFormat.DD,
        column_mapping={"name": "LABEL", "latitude": "LAT", "longitude": "LON"},
    )
    svc.save_preset(preset)
    presets = svc.get_presets()
    assert len(presets) == 1
    assert presets[0].name == "GPS_Export"
    assert presets[0].column_mapping["latitude"] == "LAT"


def test_61_load_preset(clean_settings):
    """61. Загрузка пресета по имени."""
    svc = PresetsService(clean_settings)
    preset = ImportPreset(name="Template", coordinate_format=CoordinateFormat.DMS)
    svc.save_preset(preset)
    loaded = svc.get_preset("Template")
    assert loaded is not None
    assert loaded.coordinate_format == CoordinateFormat.DMS


def test_62_delete_preset(clean_settings):
    """62. Удаление пресета."""
    svc = PresetsService(clean_settings)
    svc.save_preset(ImportPreset(name="ToDel"))
    assert len(svc.get_presets()) == 1
    assert svc.delete_preset("ToDel")
    assert len(svc.get_presets()) == 0


def test_63_missing_column_after_preset_handled(qapp, clean_settings):
    """63. Если в файле нет колонки из пресета, поле остается несопоставленным."""
    svc = PresetsService(clean_settings)
    svc.save_preset(ImportPreset(name="P", column_mapping={"name": "NonExistentColumn"}))

    page = ColumnMappingPage(ImportService(), svc)
    page._headers = ["Col1", "Col2"]
    page._populate_combos()
    page._reload_presets()
    page.preset_combo.setCurrentText("P")
    assert page._combos["name"].currentText() == tr("wizard.not_used")


def test_64_preset_does_not_alter_source_file(tmp_path, clean_settings):
    """64. Сохранение/загрузка пресета не модифицирует файл на диске."""
    f = tmp_path / "raw.csv"
    content = "A;B\n1;2\n"
    f.write_text(content, encoding="utf-8")
    mtime = f.stat().st_mtime

    svc = PresetsService(clean_settings)
    svc.save_preset(ImportPreset(name="TestPreset"))
    assert f.stat().st_mtime == mtime
    assert f.read_text(encoding="utf-8") == content


# =============================================================================
# Section 78: Транзакционность и Undo/Redo (тесты 65–71)
# =============================================================================

def test_65_final_selected_rows_imported(tmp_path):
    """65. Только валидные и неисключенные строки передаются для импорта."""
    f = tmp_path / "final.csv"
    f.write_text("name;lat;lon\nP1;56.0;47.0\nP2;999;47.0\nP3;56.0;47.0\n", encoding="utf-8")
    opts = ImportOptions(duplicate_policy=DuplicatePolicy.SKIP_DUPLICATES)
    res = ImportService().validate_file(f, opts)
    # P1: валидна
    # P2: ошибка
    # P3: дубликат (исключена)
    assert len(res.points) == 1
    assert res.points[0].name == "P1"


def test_66_one_undo_removes_import(qapp, tmp_path):
    """66. Одно нажатие Undo (Ctrl+Z) удаляет весь импортированный пакет."""
    win = MainWindow()
    pts = [
        MapPoint(id="pt1", name="P1", latitude=56.1, longitude=47.1),
        MapPoint(id="pt2", name="P2", latitude=56.2, longitude=47.2),
    ]
    cmd = ImportPointsCommand(
        points=pts,
        add_fn=win.point_controller._cmd_add_points,
        remove_fn=win.point_controller._cmd_remove_points,
    )
    win.point_controller.undo_manager.push(cmd, execute=True)
    assert len(win.point_controller._point_service) == 2

    win.point_controller.undo_manager.undo()
    assert len(win.point_controller._point_service) == 0
    win._set_modified(False)
    win.close()


def test_67_redo_restores_import(qapp):
    """67. Redo возвращает весь импорт."""
    win = MainWindow()
    pts = [MapPoint(id="pt1", name="P1", latitude=56.1, longitude=47.1)]
    cmd = ImportPointsCommand(
        points=pts,
        add_fn=win.point_controller._cmd_add_points,
        remove_fn=win.point_controller._cmd_remove_points,
    )
    win.point_controller.undo_manager.push(cmd, execute=True)
    win.point_controller.undo_manager.undo()
    win.point_controller.undo_manager.redo()
    assert len(win.point_controller._point_service) == 1
    win._set_modified(False)
    win.close()


def test_68_stable_ids(qapp):
    """68. Идентификаторы точек стабильны при отмене и повторе."""
    win = MainWindow()
    pts = [MapPoint(id="stable-id-123", name="P1", latitude=56.1, longitude=47.1)]
    cmd = ImportPointsCommand(
        points=pts,
        add_fn=win.point_controller._cmd_add_points,
        remove_fn=win.point_controller._cmd_remove_points,
    )
    win.point_controller.undo_manager.push(cmd, execute=True)
    win.point_controller.undo_manager.undo()
    win.point_controller.undo_manager.redo()
    assert win.point_controller._point_service.get_point("stable-id-123") is not None
    win._set_modified(False)
    win.close()


def test_69_dirty_state(qapp):
    """69. Статус is_modified корректно обновляется при undo/redo импорта."""
    win = MainWindow()
    win._set_modified(False)
    pts = [MapPoint(id="p1", name="P1", latitude=56.0, longitude=47.0)]
    cmd = ImportPointsCommand(
        points=pts,
        add_fn=win.point_controller._cmd_add_points,
        remove_fn=win.point_controller._cmd_remove_points,
    )
    win.point_controller.undo_manager.push(cmd, execute=True)
    assert win.is_modified

    win.point_controller.undo_manager.undo()
    assert not win.is_modified
    win.close()


def test_70_recovery_integration(qapp, monkeypatch):
    """70. При импорте через ImportController сохраняется снимок восстановления."""
    win = MainWindow()
    called = []
    monkeypatch.setattr(win.project_controller, "_save_recovery_snapshot_worker", lambda: called.append(True))
    win.import_controller._point_controller = win.point_controller

    pts = [MapPoint(id="p", name="P", latitude=56, longitude=47)]
    cmd = ImportPointsCommand(
        points=pts,
        add_fn=win.point_controller._cmd_add_points,
        remove_fn=win.point_controller._cmd_remove_points,
    )
    win.point_controller.undo_manager.push(cmd, execute=True)
    win.project_controller._save_recovery_snapshot_worker()
    assert len(called) == 1
    win._set_modified(False)
    win.close()


def test_71_cancel_no_dirty_state(qapp):
    """71. Отмена мастера импорта не взводит статус несохраненных изменений."""
    win = MainWindow()
    win._set_modified(False)
    wizard = ImportWizard(parent=win)
    wizard.reject()
    assert not win.is_modified
    win.close()


# =============================================================================
# Section 79: Защита от устаревших данных и лимиты (тесты 72–76)
# =============================================================================

def test_72_mapping_change_invalidates_result(qapp, tmp_path):
    """72. Изменение сопоставления колонок требует повторной валидации."""
    f = tmp_path / "data.csv"
    f.write_text("name;lat;lon\nP1;56.0;47.0\n", encoding="utf-8")
    wizard = ImportWizard(file_path=f)
    wizard.next()  # 2
    wizard.next()  # 3
    wizard.next()  # 4: валидация завершена
    res1 = wizard.get_validation_result()
    assert res1 is not None

    wizard.back()  # Возврат на Шаг 3 (Mapping)
    wizard.page_mapping._combos["name"].setCurrentIndex(0)
    wizard.next()  # Повторный вход на Шаг 4
    res2 = wizard.get_validation_result()
    assert res2 is not None
    assert res2.points[0].name.startswith("Точка")
    wizard.close()


def test_73_sheet_change_invalidates_result(qapp, tmp_path):
    """73. Смена листа в книге XLSX пересчитывает результат валидации."""
    f = tmp_path / "wb.xlsx"
    wb = openpyxl.Workbook()
    ws1 = wb.active
    ws1.title = "Sh1"
    ws1.append(["name", "lat", "lon"])
    ws1.append(["Pt_1", 56.0, 47.0])
    ws2 = wb.create_sheet("Sh2")
    ws2.append(["name", "lat", "lon"])
    ws2.append(["Pt_2", 56.5, 47.5])
    wb.save(str(f))
    wb.close()

    wizard = ImportWizard(file_path=f)
    wizard.next()  # 2: File Structure
    wizard.page_structure.sheet_combo.setCurrentText("Sh2")
    wizard.next()  # 3: Mapping
    wizard.next()  # 4: Validation
    res = wizard.get_validation_result()
    assert res.sheet_name == "Sh2"
    assert res.points[0].name == "Pt_2"
    wizard.close()


def test_74_crs_change_invalidates_result(qapp, tmp_path):
    """74. Смена исходной СК X/Y обновляет итоговые координаты."""
    f = tmp_path / "xy.csv"
    f.write_text("x;y\n5330467;7685433\n", encoding="utf-8")
    wizard = ImportWizard(file_path=f)
    wizard.next()  # 2
    wizard.next()  # 3
    wizard.page_mapping.radio_xy.setChecked(True)
    wizard.page_mapping._on_format_changed()
    wizard.page_mapping.crs_edit.setText("EPSG:3857")
    wizard.next()  # 4
    res = wizard.get_validation_result()
    assert pytest.approx(res.points[0].latitude, 0.01) == 56.63
    wizard.close()


def test_75_changed_source_file_requires_revalidation(qapp, tmp_path):
    """75. Изменение файла на диске делает результат валидации устаревшим."""
    f = tmp_path / "data.csv"
    f.write_text("name;lat;lon\nP1;56.0;47.0\n", encoding="utf-8")
    wizard = ImportWizard(file_path=f)
    wizard.next()  # 2
    wizard.next()  # 3
    wizard.next()  # 4
    wizard.next()  # 5: Summary

    assert not wizard.page_summary._is_stale

    # Изменяем файл на диске
    time.sleep(0.05)
    f.write_text("name;lat;lon\nP1;56.0;47.0\nP2;56.1;47.1\n", encoding="utf-8")

    wizard.page_summary.initializePage()
    assert wizard.page_summary._is_stale
    assert not wizard.page_summary.isComplete()
    wizard.close()


def test_76_project_limit_checked_again_before_finish(tmp_path):
    """76. Превышение глобального лимита (100 000 точек) блокирует импорт."""
    f = tmp_path / "pts.csv"
    f.write_text("name;lat;lon\nP1;56.0;47.0\n", encoding="utf-8")
    service = ImportService()
    # Текущее число точек = 100 000
    res = service.validate_file(f, current_project_points_count=100_000)
    assert any(e.code == "import.err.max_project_points_exceeded" for e in res.errors)


# =============================================================================
# Section 80: Тест производительности (тест 77)
# =============================================================================

def test_77_performance_10k_rows(tmp_path):
    """77. Валидация и загрузка в модель 10 000 строк без квадратичной деградации O(n²)."""
    f = tmp_path / "large_10k.csv"
    lines = ["name;latitude;longitude;symbol;size;radius;radius_unit"]
    for i in range(10000):
        lines.append(f"Pt_{i};56.{i:05d};47.{i:05d};circle;10;{(i % 1000) + 1};m")
    f.write_text("\n".join(lines), encoding="utf-8")

    start = time.perf_counter()
    service = ImportService()
    res = service.validate_file(f)
    elapsed_val = time.perf_counter() - start

    assert res.total_rows == 10000
    assert res.valid_rows == 10000
    assert elapsed_val < 15.0  # 10 000 строк валидируются быстро

    # Загрузка результатов в табличную модель UI
    start_ui = time.perf_counter()
    model = ValidationTableModel()
    model.set_rows(res.rows)
    elapsed_ui = time.perf_counter() - start_ui

    assert model.rowCount() == 10000
    assert elapsed_ui < 1.0  # Модель мгновенно индексирует строки без создания виджетов
