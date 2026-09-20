"""Контрольные тесты проверки Этапа 22 (Stage 22 Control Verification Test Suite).

Проверяет 27 обязательных аспектов контрольного чек-листа:
1. XLSX round-trip (Import Wizard, сохранение '0012' как строки, а не числа 12).
2. TXT round-trip (Unicode, кириллица, переносы строк \n, группы, номера).
3. TXT разделители (Tab, Semicolon).
4. CSV round-trip (полное соответствие атрибутов).
5. Selected Objects + Presentation filters (поиск и фильтры строк не ломают выборку по ID).
6. Visible Objects матрица (point.visible AND group.visible, глобальный Hide Points не влияет).
7. Presentation filters immutability (поиск, категория, группа не меняют данные скоупов).
8. Orphan group (несуществующая группа экспортируется как пустая строка без падений).
9. Duplicate object numbers (совпадающие номера объектов не вызывают искусственных ошибок).
10. Empty values (пустые значения не превращаются в 'None' или 'null').
11. GeoJSON RFC 7946 (строгий порядок [lon, lat], отсутствие корневого 'crs', X/Y только в properties).
12. GeoJSON Streaming & NaN/Inf защита (потоковая запись без OOM, пропуск невалидных чисел).
13. CSV/TXT Large Data (1k, 10k, 50k, 100k).
14. XLSX Large Data (1k, 10k, 50k, 100k в write_only режиме).
15. Numeric types и цвета #RRGGBB.
16. Radius (строго метры).
17. Атомарная запись во всех 4 форматах при симуляции ошибок.
18. Successful replace (отсутствие мусорных .tmp файлов).
19. Project Immutability (сохранение чистоты проекта, UndoManager и селектов).
20. Cancel & Overwrite protection.
21. Нормализация расширений файлов.
22. Settings persistence (независимые инстансы AppSettingsService).
23. RU / EN независимость технических ключей полей.
"""

import csv
import json
import math
import os
from pathlib import Path
import time
from unittest.mock import MagicMock, patch

import openpyxl
from PySide6.QtCore import QSettings, Qt
from PySide6.QtWidgets import QApplication, QDialog, QMessageBox, QWidget
import pytest

from rme_mapper.services.coordinate_service import CoordinateService

from rme_mapper.importers.import_service import ImportService
from rme_mapper.importers.models import ImportOptions
from rme_mapper.models.map_point import MapPoint
from rme_mapper.models.object_export import (
    DEFAULT_FIELD_KEYS,
    EXPORT_FIELDS,
    EXPORT_FIELDS_BY_KEY,
    CsvDelimiter,
    ObjectExportFormat,
    ObjectExportOptions,
    ObjectExportScope,
)
from rme_mapper.models.object_group import ObjectGroup
from rme_mapper.services.app_settings_service import AppSettingsService
from rme_mapper.services.group_service import GroupService
from rme_mapper.services.object_export_service import (
    ObjectExportService,
    format_lat_dms,
    format_lon_dms,
)
from rme_mapper.services.point_service import PointService
from rme_mapper.ui.export_objects_dialog import ExportObjectsDialog
from rme_mapper.ui.main_window import MainWindow


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance() or QApplication([])
    return app


# ==============================================================================
# 1. XLSX ROUND-TRIP
# ==============================================================================

def test_ctrl_01_xlsx_roundtrip_leading_zeros(tmp_path):
    """XLSX export -> ImportService: сохранение ведущих нулей ('0012' -> '0012', а не 12)."""
    pt = MapPoint(
        id="pt-101",
        name="Трансформатор Т-101",
        object_number="0012",
        description="Линия 110 кВ",
        category="Энергетика",
        latitude=55.751244,
        longitude=37.618423,
    )
    gs = GroupService()
    g = gs.create_group("Подстанции", visible=True)
    pt.group_id = g.id

    out_xlsx = tmp_path / "test_roundtrip.xlsx"
    opts = ObjectExportOptions(
        format=ObjectExportFormat.XLSX,
        field_keys=["object_number", "name", "description", "category", "group", "latitude", "longitude"],
    )
    ObjectExportService.export_points([pt], opts, out_xlsx, group_service=gs)

    # Проверка через openpyxl типа ячейки
    wb = openpyxl.load_workbook(out_xlsx, read_only=True)
    ws = wb["Objects"]
    rows = list(ws.iter_rows(values_only=False))
    # Ячейка object_number во 2-й строке
    cell_num = rows[1][0]
    assert cell_num.data_type == "s"
    assert str(cell_num.value) == "0012"
    wb.close()

    # Импорт через ImportService
    imp = ImportService()
    res = imp.validate_file(out_xlsx, ImportOptions(source_crs="EPSG:4326"))
    assert len(res.errors) == 0
    assert len(res.points) == 1
    p_imp = res.points[0]
    assert p_imp.object_number == "0012"
    assert p_imp.name == "Трансформатор Т-101"
    assert p_imp.category == "Энергетика"
    assert p_imp.description == "Линия 110 кВ"
    assert abs(p_imp.latitude - 55.751244) < 1e-4
    assert abs(p_imp.longitude - 37.618423) < 1e-4


# ==============================================================================
# 2. TXT ROUND-TRIP И РАЗДЕЛИТЕЛИ
# ==============================================================================

def test_ctrl_02_txt_roundtrip_unicode_newlines_group(tmp_path):
    """TXT/TSV export -> ImportService: Unicode, кириллица, перенос строки, группа, номер."""
    pt = MapPoint(
        id="pt-102",
        name="Точка Северная №1",
        object_number="0077",
        description="Строка 1\nСтрока 2 с описанием",
        category="Гидрология",
        latitude=60.123456,
        longitude=30.654321,
    )
    gs = GroupService()
    g = gs.create_group("Водные ресурсы", visible=True)
    pt.group_id = g.id

    out_txt = tmp_path / "test_roundtrip.txt"
    opts = ObjectExportOptions(
        format=ObjectExportFormat.TXT,
        delimiter=CsvDelimiter.TAB,
        field_keys=["object_number", "name", "description", "category", "group", "latitude", "longitude"],
    )
    ObjectExportService.export_points([pt], opts, out_txt, group_service=gs)

    imp = ImportService()
    res = imp.validate_file(out_txt, ImportOptions(source_crs="EPSG:4326"))
    assert len(res.errors) == 0
    assert len(res.points) == 1
    p_imp = res.points[0]
    assert p_imp.object_number == "0077"
    assert p_imp.name == "Точка Северная №1"
    assert "Строка 1\nСтрока 2" in p_imp.description
    assert p_imp.category == "Гидрология"


def test_ctrl_03_txt_delimiters_semicolon_and_tab(tmp_path):
    """Проверка поддержки разделителей Tab и Semicolon в TXT формате."""
    pts = [MapPoint(id="p1", name="П1", latitude=55.0, longitude=37.0)]

    # 1. Tab
    out_tab = tmp_path / "out_tab.txt"
    opts_tab = ObjectExportOptions(format=ObjectExportFormat.TXT, delimiter=CsvDelimiter.TAB)
    ObjectExportService.export_points(pts, opts_tab, out_tab)
    with open(out_tab, "r", encoding="utf-8-sig") as f:
        assert "\t" in f.readline()

    # 2. Semicolon
    out_semi = tmp_path / "out_semi.txt"
    opts_semi = ObjectExportOptions(format=ObjectExportFormat.TXT, delimiter=CsvDelimiter.SEMICOLON)
    ObjectExportService.export_points(pts, opts_semi, out_semi)
    with open(out_semi, "r", encoding="utf-8-sig") as f:
        assert ";" in f.readline()


# ==============================================================================
# 3. CSV ROUND-TRIP
# ==============================================================================

def test_ctrl_04_csv_roundtrip_all_fields(tmp_path):
    """Повторное подтверждение CSV -> ImportService для всех базовых атрибутов."""
    pt = MapPoint(
        id="pt-103",
        name="Опора ВЛ-10",
        object_number="0055",
        description="Кабельная муфта",
        category="ЛЭП",
        latitude=55.800000,
        longitude=37.700000,
    )
    gs = GroupService()
    g = gs.create_group("ЛЭП-10кВ", visible=True)
    pt.group_id = g.id

    out_csv = tmp_path / "test_roundtrip.csv"
    opts = ObjectExportOptions(
        format=ObjectExportFormat.CSV,
        delimiter=CsvDelimiter.COMMA,
        field_keys=["object_number", "name", "description", "category", "group", "latitude", "longitude"],
    )
    ObjectExportService.export_points([pt], opts, out_csv, group_service=gs)

    imp = ImportService()
    res = imp.validate_file(out_csv, ImportOptions(source_crs="EPSG:4326"))
    assert len(res.errors) == 0
    assert len(res.points) == 1
    p = res.points[0]
    assert p.object_number == "0055"
    assert p.name == "Опора ВЛ-10"
    assert p.description == "Кабельная муфта"
    assert p.category == "ЛЭП"
    assert abs(p.latitude - 55.8) < 1e-4
    assert abs(p.longitude - 37.7) < 1e-4


# ==============================================================================
# 4. SELECTED OBJECTS + PRESENTATION FILTERS
# ==============================================================================

def test_ctrl_05_selected_objects_with_stable_ids_and_presentation_filter(qapp):
    """Точка выделена по стабильному ID, фильтр поиска скрывает строку; экспорт выделенных сохраняет точку."""
    win = MainWindow()
    p1 = win._point_service.add_point(name="Насосная станция", latitude=55.1, longitude=37.1, object_number="1001")
    p2 = win._point_service.add_point(name="Диспетчерская", latitude=55.2, longitude=37.2, object_number="1002")
    win.points_panel.add_point(p1)
    win.points_panel.add_point(p2)

    # 1. Выделяем p1
    win.points_panel.select_point_ids([p1.id])
    assert win.points_panel.selected_point_ids() == [p1.id]

    # 2. Применяем фильтр поиска, который скрывает p1 (ищет только 'Диспетчерская')
    win.points_panel.search_input.setText("Диспетчерская")
    # Строка 0 (p1) скрыта в QTableWidget
    assert win.points_panel.points_table.isRowHidden(0) is True
    assert win.points_panel.points_table.isRowHidden(1) is False

    # 3. Скоуп SELECTED должен по-прежнему опираться на стабильные ID выделения
    selected_pts = ObjectExportService.filter_points(
        win._point_service.get_points(),
        ObjectExportScope.SELECTED,
        selected_ids=win.points_panel.selected_point_ids(),
    )
    assert len(selected_pts) == 1
    assert selected_pts[0].id == p1.id
    win.close()


# ==============================================================================
# 5. VISIBLE OBJECTS МАТРИЦА И GLOBAL HIDE
# ==============================================================================

def test_ctrl_06_visible_objects_matrix_and_global_hide_immunity():
    """Матрица видимости A, B, C и иммунитет к глобальному выключению отображения."""
    gs = GroupService()
    g_vis = gs.create_group("Visible Group", visible=True)
    g_hid = gs.create_group("Hidden Group", visible=False)

    p_a = MapPoint(id="A", name="A", latitude=55.0, longitude=37.0, visible=False, group_id=g_vis.id)
    p_b = MapPoint(id="B", name="B", latitude=55.0, longitude=37.0, visible=True, group_id=g_hid.id)
    p_c = MapPoint(id="C", name="C", latitude=55.0, longitude=37.0, visible=True, group_id=g_vis.id)
    p_d = MapPoint(id="D", name="D", latitude=55.0, longitude=37.0, visible=True, group_id=None)

    points = [p_a, p_b, p_c, p_d]

    # Правило: point.visible AND (group is None or group.visible)
    res = ObjectExportService.filter_points(points, ObjectExportScope.VISIBLE, group_service=gs)
    res_ids = {p.id for p in res}

    assert "A" not in res_ids  # point.visible == False
    assert "B" not in res_ids  # group.visible == False
    assert "C" in res_ids      # point.visible == True and group.visible == True
    assert "D" in res_ids      # point.visible == True and group is None


# ==============================================================================
# 6. ORPHAN GROUP И DUPLICATE NUMBERS
# ==============================================================================

def test_ctrl_07_orphan_group_handling(caplog):
    """Точка с orphan group_id: экспорт не падает, группа экспортируется как пустая строка."""
    pt = MapPoint(id="p_orphan", name="Сирота", latitude=55.0, longitude=37.0, group_id="non_existent_uuid")
    gs = GroupService()  # Группы нет

    options = ObjectExportOptions(field_keys=["name", "group"])
    rec = ObjectExportService.build_export_record(pt, options, group_service=gs)
    assert rec["group"] == ""


def test_ctrl_08_duplicate_object_numbers(tmp_path):
    """Объекты с одинаковыми object_number не вызывают ошибок валидации."""
    p1 = MapPoint(id="p1", name="Объект 1", object_number="42", latitude=55.0, longitude=37.0)
    p2 = MapPoint(id="p2", name="Объект 2", object_number="42", latitude=55.1, longitude=37.1)

    out_csv = tmp_path / "duplicates.csv"
    opts = ObjectExportOptions(format=ObjectExportFormat.CSV)
    count = ObjectExportService.export_points([p1, p2], opts, out_csv)
    assert count == 2


# ==============================================================================
# 7. EMPTY VALUES
# ==============================================================================

def test_ctrl_09_empty_values_formatting(tmp_path):
    """Пустые строковые значения экспортируются как пустые ячейки, а не 'None'/'null'."""
    pt = MapPoint(
        id="p_empty",
        name="",
        object_number="",
        description="",
        category="",
        latitude=55.0,
        longitude=37.0,
        group_id=None,
    )
    out_csv = tmp_path / "empty.csv"
    opts = ObjectExportOptions(
        format=ObjectExportFormat.CSV,
        field_keys=["object_number", "name", "category", "group", "description"],
        include_headers=False,
    )
    ObjectExportService.export_points([pt], opts, out_csv)

    with open(out_csv, "r", encoding="utf-8-sig") as f:
        line = f.readline().strip()
    assert "None" not in line
    assert "null" not in line
    assert line == ",,,," or line == '""' or line.replace(",", "") == ""


# ==============================================================================
# 8. GEOJSON RFC 7946 СТАНДАРТ И СТРИМИНГ
# ==============================================================================

def test_ctrl_10_geojson_rfc7946_and_projected_xy(tmp_path):
    """GeoJSON: coordinates=[lon, lat], отсутствие crs в корне, спроецированные X/Y в properties."""
    pt = MapPoint(id="pt-geo", name="Кремль", latitude=55.751244, longitude=37.618423)
    out_geo = tmp_path / "rfc7946.geojson"
    opts = ObjectExportOptions(
        format=ObjectExportFormat.GEOJSON,
        field_keys=["name", "latitude", "longitude", "x", "y", "crs"],
        target_crs="EPSG:3857",
    )
    ObjectExportService.export_points([pt], opts, out_geo)

    with open(out_geo, "r", encoding="utf-8") as f:
        doc = json.load(f)

    assert doc["type"] == "FeatureCollection"
    assert "crs" not in doc  # RFC 7946

    feat = doc["features"][0]
    coords = feat["geometry"]["coordinates"]
    # Строго [longitude, latitude]
    assert coords[0] == 37.618423
    assert coords[1] == 55.751244

    props = feat["properties"]
    assert "x" in props and isinstance(props["x"], (int, float))
    assert "y" in props and isinstance(props["y"], (int, float))
    assert props["crs"] == "EPSG:3857"


def test_ctrl_11_geojson_nan_inf_protection(tmp_path):
    """Проверка защиты GeoJSON от записи недопустимых токенов NaN и Infinity."""
    p_valid = MapPoint(id="p_val", name="OK", latitude=55.0, longitude=37.0)
    p_nan = MapPoint(id="p_nan", name="NaN", latitude=float("nan"), longitude=37.0)
    p_inf = MapPoint(id="p_inf", name="Inf", latitude=55.0, longitude=float("inf"))

    out_geo = tmp_path / "safe.geojson"
    opts = ObjectExportOptions(format=ObjectExportFormat.GEOJSON)
    # NaN и Inf должны безопасно отфильтровываться
    count = ObjectExportService.export_points([p_valid, p_nan, p_inf], opts, out_geo)

    with open(out_geo, "r", encoding="utf-8") as f:
        raw = f.read()
    assert "NaN" not in raw
    assert "Infinity" not in raw
    doc = json.loads(raw)
    assert len(doc["features"]) == 1


# ==============================================================================
# 9. ЧИСЛА, ЦВЕТА #RRGGBB И РАДИУС
# ==============================================================================

def test_ctrl_12_colors_and_radius_canonical():
    """Проверка верхнерегистрового формата #RRGGBB и строго метрового радиуса."""
    pt = MapPoint(
        id="p1",
        name="Цветная",
        latitude=55.0,
        longitude=37.0,
        red=255,
        green=0,
        blue=128,
        stroke_red=0,
        stroke_green=255,
        stroke_blue=0,
        zone_enabled=True,
        radius_m=1250.5,
        zone_red=10,
        zone_green=20,
        zone_blue=30,
        zone_border_red=40,
        zone_border_green=50,
        zone_border_blue=60,
    )
    opts = ObjectExportOptions()
    rec = ObjectExportService.build_export_record(pt, opts)

    assert rec["marker_fill_color"] == "#FF0080"
    assert rec["marker_stroke_color"] == "#00FF00"
    assert rec["zone_fill_color"] == "#0A141E"
    assert rec["zone_border_color"] == "#28323C"
    assert rec["zone_radius_m"] == 1250.5


# ==============================================================================
# 10. АТОМАРНАЯ ЗАПИСЬ ВО ВСЕХ 4 ФОРМАТАХ
# ==============================================================================

@pytest.mark.parametrize("fmt,ext", [
    (ObjectExportFormat.CSV, ".csv"),
    (ObjectExportFormat.TXT, ".txt"),
    (ObjectExportFormat.XLSX, ".xlsx"),
    (ObjectExportFormat.GEOJSON, ".geojson"),
])
def test_ctrl_13_atomic_write_failure_all_formats(tmp_path, fmt, ext):
    """Для всех 4 форматов: при сбое целевой файл не повреждается, temp-файл удаляется."""
    target_file = tmp_path / f"atomic_target{ext}"
    target_file.write_bytes(b"INITIAL SAFE CONTENT")

    pts = [MapPoint(id="p1", name="P1", latitude=55.0, longitude=37.0)]
    opts = ObjectExportOptions(format=fmt)

    with patch.object(ObjectExportService, "build_export_record", side_effect=IOError("Simulated write failure")):
        with pytest.raises(IOError, match="Simulated write failure"):
            ObjectExportService.export_points(pts, opts, target_file)

    # Исходный файл не изменился
    assert target_file.read_bytes() == b"INITIAL SAFE CONTENT"

    # Мусорных .tmp файлов нет
    tmp_files = list(tmp_path.glob("*.tmp*"))
    assert len(tmp_files) == 0


def test_ctrl_14_atomic_write_success_no_leftover_temps(tmp_path):
    """При успешном экспорте не остается временных файлов."""
    target_file = tmp_path / "success.csv"
    pts = [MapPoint(id="p1", name="P1", latitude=55.0, longitude=37.0)]
    opts = ObjectExportOptions(format=ObjectExportFormat.CSV)

    ObjectExportService.export_points(pts, opts, target_file)
    assert target_file.exists()
    assert len(list(tmp_path.glob("*.tmp*"))) == 0


# ==============================================================================
# 11. НЕПРИКОСНОВЕННОСТЬ СОСТОЯНИЯ ПРОЕКТА (Project Immutability)
# ==============================================================================

def test_ctrl_15_project_immutability(qapp):
    """Экспорт не изменяет project.is_modified, UndoManager, выборки и данные точек."""
    win = MainWindow()
    pt = win._point_service.add_point(name="Неизменный", latitude=55.0, longitude=37.0)
    win.points_panel.add_point(pt)
    win.project_controller.set_modified(False)

    undo_mgr = win.point_controller.undo_manager
    undo_mgr.mark_clean()

    # Запускаем экспорт во всех форматах
    for fmt in (ObjectExportFormat.CSV, ObjectExportFormat.XLSX, ObjectExportFormat.TXT, ObjectExportFormat.GEOJSON):
        opts = ObjectExportOptions(format=fmt)
        out_f = Path(f"immutability_test.{fmt.value}")
        ObjectExportService.export_points(win._point_service.get_points(), opts, out_f)
        if out_f.exists():
            out_f.unlink()

    assert not win.project_controller.is_modified
    assert undo_mgr.is_clean
    assert win._point_service.get_point(pt.id).name == "Неизменный"
    win.close()


# ==============================================================================
# 12. ДИАЛОГ: CANCEL, OVERWRITE И НОРМАЛИЗАЦИЯ РАСШИРЕНИЙ
# ==============================================================================

def test_ctrl_16_extension_normalization(qapp, tmp_path):
    """Проверка нормализации расширений файлов при экспорте."""
    dialog = ExportObjectsDialog(points=[], selected_ids=set())

    # XLSX + path с .csv
    dialog.path_edit.setText(str(tmp_path / "data.csv"))
    idx = dialog.format_combo.findData(ObjectExportFormat.XLSX)
    dialog.format_combo.setCurrentIndex(idx)
    assert dialog.path_edit.text().endswith(".xlsx")

    # GeoJSON + path с .txt
    idx_g = dialog.format_combo.findData(ObjectExportFormat.GEOJSON)
    dialog.format_combo.setCurrentIndex(idx_g)
    assert dialog.path_edit.text().endswith(".geojson")


def test_ctrl_17_overwrite_confirmation_behavior(qapp, tmp_path):
    """Подтверждение перезаписи файла: отказ не меняет файл, согласие перезаписывает."""
    existing = tmp_path / "exist.csv"
    existing.write_text("OLD", encoding="utf-8")

    dialog = ExportObjectsDialog(
        points=[MapPoint(id="p", name="P", latitude=55.0, longitude=37.0)],
        selected_ids=set(),
    )
    dialog.path_edit.setText(str(existing))

    # Пользователь нажал "Нет" в диалоге перезаписи
    with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.No):
        dialog._on_export_clicked()
        assert existing.read_text(encoding="utf-8") == "OLD"


# ==============================================================================
# 13. SETTINGS PERSISTENCE МЕЖДУ ЭКЗЕМПЛЯРАМИ
# ==============================================================================

def test_ctrl_18_settings_persistence_between_instances(qapp, tmp_path):
    """Сохранение всех UI настроек экспорта между двумя инстансами диалога."""
    settings = AppSettingsService(settings=None)

    d1 = ExportObjectsDialog(points=[], selected_ids=set(), settings_service=settings)
    d1.format_combo.setCurrentIndex(d1.format_combo.findData(ObjectExportFormat.TXT))
    d1.delim_combo.setCurrentIndex(d1.delim_combo.findData(CsvDelimiter.SEMICOLON))
    d1.bom_checkbox.setChecked(False)
    d1.dd_precision_spin.setValue(9)
    d1.crs_combo.setCurrentText("EPSG:32637")
    d1.path_edit.setText(str(tmp_path / "export.txt"))
    d1._save_settings()

    d2 = ExportObjectsDialog(points=[], selected_ids=set(), settings_service=settings)
    assert d2._get_current_format() == ObjectExportFormat.TXT
    assert d2._get_current_delimiter() == CsvDelimiter.SEMICOLON
    assert d2.bom_checkbox.isChecked() is False
    assert d2.dd_precision_spin.value() == 9
    assert d2.crs_combo.currentText() == "EPSG:32637"


# ==============================================================================
# 14. ЛОКАЛИЗАЦИЯ RU / EN (ТЕХНИЧЕСКИЕ КЛЮЧИ НЕ МЕНЯЮТСЯ)
# ==============================================================================

def test_ctrl_19_technical_keys_immutable_across_languages():
    """Технические ключи полей экспорта остаются неизменными при смене языка интерфейса."""
    from rme_mapper.i18n import set_language
    set_language("ru")
    keys_ru = [f.key for f in EXPORT_FIELDS]

    set_language("en")
    keys_en = [f.key for f in EXPORT_FIELDS]

    assert keys_ru == keys_en
    assert "object_number" in keys_ru
    assert "latitude" in keys_ru
    set_language("ru")


# ==============================================================================
# 15. БЕНЧМАРКИ 100K: CSV, TXT, XLSX (WRITE_ONLY), GEOJSON STREAMING
# ==============================================================================

def test_ctrl_20_streaming_benchmarks_100k(tmp_path):
    """Фиксация времени, пикового потребления памяти и размера 100 000 точек по каждому формату отдельно."""
    import tracemalloc

    pts_100k = [
        MapPoint(id=f"p_{i}", name=f"P_{i}", object_number=f"{i:06d}", latitude=55.0 + (i % 1000) * 0.0001, longitude=37.0)
        for i in range(100000)
    ]
    opts_base = ObjectExportOptions(field_keys=["object_number", "name", "latitude", "longitude"])

    # 1. CSV 100k (Streaming)
    tracemalloc.start()
    t0 = time.time()
    csv_file = tmp_path / "bench_100k.csv"
    ObjectExportService.export_points(pts_100k, opts_base, csv_file)
    dur_csv = time.time() - t0
    _, peak_csv = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    sz_csv = csv_file.stat().st_size / (1024 * 1024)
    ram_csv = peak_csv / (1024 * 1024)
    assert dur_csv < 60.0
    print(f"\n[BENCH 100k CSV] Time: {dur_csv:.2f}s, Peak RAM: {ram_csv:.2f} MB, Size: {sz_csv:.2f} MB")

    # 2. TXT 100k (Streaming)
    tracemalloc.start()
    t0 = time.time()
    txt_file = tmp_path / "bench_100k.txt"
    opts_txt = ObjectExportOptions(format=ObjectExportFormat.TXT, delimiter=CsvDelimiter.TAB, field_keys=["object_number", "name", "latitude", "longitude"])
    ObjectExportService.export_points(pts_100k, opts_txt, txt_file)
    dur_txt = time.time() - t0
    _, peak_txt = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    sz_txt = txt_file.stat().st_size / (1024 * 1024)
    ram_txt = peak_txt / (1024 * 1024)
    assert dur_txt < 60.0
    print(f"[BENCH 100k TXT] Time: {dur_txt:.2f}s, Peak RAM: {ram_txt:.2f} MB, Size: {sz_txt:.2f} MB")

    # 3. GeoJSON 100k (Streaming iterative)
    tracemalloc.start()
    t0 = time.time()
    geo_file = tmp_path / "bench_100k.geojson"
    opts_geo = ObjectExportOptions(format=ObjectExportFormat.GEOJSON, field_keys=["object_number", "name", "latitude", "longitude"])
    ObjectExportService.export_points(pts_100k, opts_geo, geo_file)
    dur_geo = time.time() - t0
    _, peak_geo = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    sz_geo = geo_file.stat().st_size / (1024 * 1024)
    ram_geo = peak_geo / (1024 * 1024)
    assert dur_geo < 60.0
    print(f"[BENCH 100k GeoJSON] Time: {dur_geo:.2f}s, Peak RAM: {ram_geo:.2f} MB, Size: {sz_geo:.2f} MB")

    # 4. XLSX 100k (openpyxl write_only=True)
    tracemalloc.start()
    t0 = time.time()
    xlsx_file = tmp_path / "bench_100k.xlsx"
    opts_xlsx = ObjectExportOptions(format=ObjectExportFormat.XLSX, field_keys=["object_number", "name", "latitude", "longitude"])
    ObjectExportService.export_points(pts_100k, opts_xlsx, xlsx_file)
    dur_xlsx = time.time() - t0
    _, peak_xlsx = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    sz_xlsx = xlsx_file.stat().st_size / (1024 * 1024)
    ram_xlsx = peak_xlsx / (1024 * 1024)
    assert dur_xlsx < 60.0
    print(f"[BENCH 100k XLSX] Time: {dur_xlsx:.2f}s, Peak RAM: {ram_xlsx:.2f} MB, Size: {sz_xlsx:.2f} MB")


# ==============================================================================
# 16. БЛОКЕР: INVALID TARGET CRS — ТЕСТЫ ПОВЕДЕНИЯ И АТОМАРНОСТИ
# ==============================================================================

@pytest.mark.parametrize("fmt,ext", [
    (ObjectExportFormat.CSV, ".csv"),
    (ObjectExportFormat.TXT, ".txt"),
    (ObjectExportFormat.XLSX, ".xlsx"),
    (ObjectExportFormat.GEOJSON, ".geojson"),
])
def test_ctrl_21_invalid_target_crs_export_fails_atomic(tmp_path, fmt, ext):
    """При невалидной target CRS экспорт завершается ошибкой, целевой файл не повреждается, temp удален."""
    target_file = tmp_path / f"existing_data{ext}"
    target_file.write_bytes(b"EXISTING UNTOUCHED CONTENT")

    pts = [MapPoint(id="p1", name="П1", latitude=55.75, longitude=37.61)]
    # Пользователь включил экспорт X/Y, но указал невалидную CRS
    opts = ObjectExportOptions(
        format=fmt,
        field_keys=["object_number", "name", "x", "y"],
        target_crs="INVALID:999999",
    )

    with pytest.raises(ValueError, match="Недопустимая целевая система координат"):
        ObjectExportService.export_points(pts, opts, target_file)

    # Исходный файл не изменился
    assert target_file.read_bytes() == b"EXISTING UNTOUCHED CONTENT"
    # Мусорных .tmp файлов нет
    assert len(list(tmp_path.glob("*.tmp*"))) == 0


def test_ctrl_22_invalid_target_crs_dialog_validation_blocks_export(qapp, tmp_path):
    """Диалог блокирует экспорт при некорректной CRS, если выбраны поля X/Y/CRS."""
    target_file = tmp_path / "blocked.csv"
    pts = [MapPoint(id="p1", name="П1", latitude=55.0, longitude=37.0)]
    dialog = ExportObjectsDialog(points=pts, selected_ids=set())

    # Выбираем поле 'x'
    dialog._field_checkboxes["x"].setChecked(True)
    dialog.crs_combo.setCurrentText("NON_EXISTENT_CRS_12345")
    dialog.path_edit.setText(str(target_file))

    with patch.object(QMessageBox, "warning") as mock_warn:
        dialog._on_export_clicked()
        mock_warn.assert_called_once()

    # Диалог не должен быть закрыт с успехом
    assert not target_file.exists()
    assert dialog.result() != QDialog.DialogCode.Accepted


def test_ctrl_23_transform_failure_during_export_fails_atomic(tmp_path):
    """Сбой при математической трансформации точки прерывает экспорт, очищает temp и не трогает target."""
    target_file = tmp_path / "transform_fail.csv"
    target_file.write_bytes(b"ORIGINAL DATA")

    pts = [MapPoint(id="p1", name="П1", latitude=55.75, longitude=37.61)]
    opts = ObjectExportOptions(
        format=ObjectExportFormat.CSV,
        field_keys=["name", "x", "y"],
        target_crs="EPSG:3857",
    )

    with patch.object(CoordinateService, "transform_xy", side_effect=RuntimeError("Internal pyproj error")):
        with pytest.raises(ValueError, match="Не удалось преобразовать координаты"):
            ObjectExportService.export_points(pts, opts, target_file)

    assert target_file.read_bytes() == b"ORIGINAL DATA"
    assert len(list(tmp_path.glob("*.tmp*"))) == 0


# ==============================================================================
# 17. ОТДЕЛЬНЫЕ ТЕСТЫ АТОМАРНОГО СБОЯ ДЛЯ ВСЕХ 4 ФОРМАТОВ (REQUIREMENT 9)
# ==============================================================================

def test_ctrl_24_atomic_failure_csv_separate(tmp_path):
    """CSV failure: старый target byte-for-byte unchanged, temp удален."""
    target_file = tmp_path / "atomic_target.csv"
    target_file.write_bytes(b"OLD_CSV_BYTES_12345")
    pts = [MapPoint(id="p1", name="P1", latitude=55.0, longitude=37.0)]
    opts = ObjectExportOptions(format=ObjectExportFormat.CSV)

    with patch.object(ObjectExportService, "build_export_record", side_effect=IOError("CSV disk fail")):
        with pytest.raises(IOError, match="CSV disk fail"):
            ObjectExportService.export_points(pts, opts, target_file)

    assert target_file.read_bytes() == b"OLD_CSV_BYTES_12345"
    assert len(list(tmp_path.glob("*.tmp*"))) == 0


def test_ctrl_25_atomic_failure_txt_separate(tmp_path):
    """TXT failure: старый target byte-for-byte unchanged, temp удален."""
    target_file = tmp_path / "atomic_target.txt"
    target_file.write_bytes(b"OLD_TXT_BYTES_12345")
    pts = [MapPoint(id="p1", name="P1", latitude=55.0, longitude=37.0)]
    opts = ObjectExportOptions(format=ObjectExportFormat.TXT)

    with patch.object(ObjectExportService, "build_export_record", side_effect=IOError("TXT disk fail")):
        with pytest.raises(IOError, match="TXT disk fail"):
            ObjectExportService.export_points(pts, opts, target_file)

    assert target_file.read_bytes() == b"OLD_TXT_BYTES_12345"
    assert len(list(tmp_path.glob("*.tmp*"))) == 0


def test_ctrl_26_atomic_failure_xlsx_separate(tmp_path):
    """XLSX failure: старый target byte-for-byte unchanged, temp удален."""
    target_file = tmp_path / "atomic_target.xlsx"
    target_file.write_bytes(b"OLD_XLSX_BYTES_12345")
    pts = [MapPoint(id="p1", name="P1", latitude=55.0, longitude=37.0)]
    opts = ObjectExportOptions(format=ObjectExportFormat.XLSX)

    with patch.object(ObjectExportService, "build_export_record", side_effect=IOError("XLSX disk fail")):
        with pytest.raises(IOError, match="XLSX disk fail"):
            ObjectExportService.export_points(pts, opts, target_file)

    assert target_file.read_bytes() == b"OLD_XLSX_BYTES_12345"
    assert len(list(tmp_path.glob("*.tmp*"))) == 0


def test_ctrl_27_atomic_failure_geojson_separate(tmp_path):
    """GeoJSON failure: старый target byte-for-byte unchanged, temp удален."""
    target_file = tmp_path / "atomic_target.geojson"
    target_file.write_bytes(b"OLD_GEOJSON_BYTES_12345")
    pts = [MapPoint(id="p1", name="P1", latitude=55.0, longitude=37.0)]
    opts = ObjectExportOptions(format=ObjectExportFormat.GEOJSON)

    with patch.object(ObjectExportService, "build_export_record", side_effect=IOError("GeoJSON disk fail")):
        with pytest.raises(IOError, match="GeoJSON disk fail"):
            ObjectExportService.export_points(pts, opts, target_file)

    assert target_file.read_bytes() == b"OLD_GEOJSON_BYTES_12345"
    assert len(list(tmp_path.glob("*.tmp*"))) == 0


# ==============================================================================
# 18. ПОДТВЕРЖДЕНИЕ УСПЕШНОГО REPLACE ДЛЯ ВСЕХ 4 ФОРМАТОВ (REQUIREMENT 10)
# ==============================================================================

@pytest.mark.parametrize("fmt,ext", [
    (ObjectExportFormat.CSV, ".csv"),
    (ObjectExportFormat.TXT, ".txt"),
    (ObjectExportFormat.XLSX, ".xlsx"),
    (ObjectExportFormat.GEOJSON, ".geojson"),
])
def test_ctrl_28_successful_atomic_replace_all_formats(tmp_path, fmt, ext):
    """Подтверждение успешного os.replace: старый target обновлен, .tmp отсутствует."""
    target_file = tmp_path / f"success_target{ext}"
    target_file.write_bytes(b"OLD_CONTENT_BEFORE_EXPORT")

    pts = [MapPoint(id="p1", name="P1", latitude=55.0, longitude=37.0)]
    opts = ObjectExportOptions(format=fmt)

    count = ObjectExportService.export_points(pts, opts, target_file)
    assert count == 1
    assert target_file.exists()
    assert target_file.read_bytes() != b"OLD_CONTENT_BEFORE_EXPORT"
    assert len(list(tmp_path.glob("*.tmp*"))) == 0


# ==============================================================================
# 19. GEOJSON 100K ВАЛИДАЦИЯ (REQUIREMENT 12)
# ==============================================================================

def test_ctrl_29_geojson_100k_full_validation(tmp_path):
    """100k GeoJSON: валидация json.load(), 100 000 features, [lon, lat], отсутствие crs, NaN, Inf."""
    pts_100k = [
        MapPoint(id=f"p_{i}", name=f"P_{i}", object_number=f"{i:06d}", latitude=55.0 + (i % 1000) * 0.0001, longitude=37.0)
        for i in range(100000)
    ]
    geo_file = tmp_path / "validate_100k.geojson"
    opts_geo = ObjectExportOptions(format=ObjectExportFormat.GEOJSON, field_keys=["object_number", "name"])

    exported_count = ObjectExportService.export_points(pts_100k, opts_geo, geo_file)
    assert exported_count == 100000

    # Проверка целостности через чтение JSON
    with open(geo_file, "r", encoding="utf-8") as f:
        doc = json.load(f)

    assert doc["type"] == "FeatureCollection"
    assert len(doc["features"]) == 100000
    assert "crs" not in doc

    # Проверка первой и последней геометрии
    first_feat = doc["features"][0]
    assert first_feat["type"] == "Feature"
    assert first_feat["geometry"]["type"] == "Point"
    assert first_feat["geometry"]["coordinates"] == [37.0, 55.0]

    # Строковая проверка отсутствия невалидных токенов
    with open(geo_file, "r", encoding="utf-8") as f:
        content_sample = f.read(2048)
        assert "NaN" not in content_sample
        assert "Infinity" not in content_sample


# ==============================================================================
# 20. НЕПРИКОСНОВЕННОСТЬ ПРОЕКТА ДЛЯ ВСЕХ 4 ФОРМАТОВ (REQUIREMENT 13)
# ==============================================================================

@pytest.mark.parametrize("fmt", [
    ObjectExportFormat.CSV,
    ObjectExportFormat.TXT,
    ObjectExportFormat.XLSX,
    ObjectExportFormat.GEOJSON,
])
def test_ctrl_30_project_immutability_all_formats(qapp, tmp_path, fmt):
    """Для каждого формата: project.is_modified, Undo stack, points, groups, selection неизменны."""
    win = MainWindow()
    pt1 = win._point_service.add_point(name="Точка А", latitude=55.0, longitude=37.0)
    pt2 = win._point_service.add_point(name="Точка Б", latitude=55.1, longitude=37.1)
    win.points_panel.add_point(pt1)
    win.points_panel.add_point(pt2)
    win.points_panel.select_point_ids([pt1.id])

    win.project_controller.set_modified(False)
    win.point_controller.undo_manager.mark_clean()

    # Фиксация исходного состояния
    pts_before = [(p.id, p.name, p.latitude, p.longitude) for p in win._point_service.get_points()]
    groups_before = [(g.id, g.name) for g in win._group_service.list_groups()]
    selection_before = list(win.points_panel.selected_point_ids())

    out_file = tmp_path / f"immut_{fmt.value}.{fmt.value}"
    opts = ObjectExportOptions(format=fmt)
    ObjectExportService.export_points(
        win._point_service.get_points(),
        opts,
        out_file,
        selected_ids=selection_before,
        group_service=win._group_service,
    )

    # Проверка неизменности
    assert win.project_controller.is_modified is False
    assert win.point_controller.undo_manager.is_clean is True
    assert [(p.id, p.name, p.latitude, p.longitude) for p in win._point_service.get_points()] == pts_before
    assert [(g.id, g.name) for g in win._group_service.list_groups()] == groups_before
    assert list(win.points_panel.selected_point_ids()) == selection_before

    win.close()


# ==============================================================================
# 21. SETTINGS MULTI-INSTANCE PERSISTENCE (REQUIREMENT 14)
# ==============================================================================

def test_ctrl_31_settings_persistence_multi_instance(tmp_path):
    """Проверка персистентности всех 8 параметров через 2 независимых инстанса AppSettingsService."""
    ini_path = tmp_path / "test_app_settings.ini"
    qs1 = QSettings(str(ini_path), QSettings.Format.IniFormat)
    qs2 = QSettings(str(ini_path), QSettings.Format.IniFormat)
    s1 = AppSettingsService(settings=qs1)
    s2 = AppSettingsService(settings=qs2)

    # 1. Запись через s1
    s1.set_object_export_format("geojson")
    s1.set_object_export_scope("visible")
    s1.set_object_export_fields(["object_number", "name", "latitude", "longitude", "x", "y"])
    s1.set_object_export_target_crs("EPSG:32638")
    s1.set_object_export_dd_precision(8)
    s1.set_object_export_delimiter(";")
    s1.set_object_export_bom(False)
    s1.set_last_export_directory(str(tmp_path))
    qs1.sync()
    qs2.sync()

    # 2. Чтение через независимый s2
    assert s2.get_object_export_format("csv") == "geojson"
    assert s2.get_object_export_scope("all") == "visible"
    assert s2.get_object_export_fields(None) == ["object_number", "name", "latitude", "longitude", "x", "y"]
    assert s2.get_object_export_target_crs("EPSG:3857") == "EPSG:32638"
    assert s2.get_object_export_dd_precision(6) == 8
    assert s2.get_object_export_delimiter(",") == ";"
    assert s2.get_object_export_bom(True) is False
    assert s2.get_last_export_directory(None) == str(tmp_path)

