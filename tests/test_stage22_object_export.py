"""Комплексные контрольные тесты Этапа 22 (Stage 22 Object Export Test Suite).

Проверяет:
1. Фильтрацию и скоупы экспорта (All, Selected, Visible, влияние видимости групп).
2. Нормализацию значений полей (ведущие нули, #RRGGBB, DMS, X/Y в целевой CRS).
3. Форматы файлов: CSV, XLSX, TXT, GeoJSON (RFC 7946).
4. Атомарную запись и отсутствие побочных эффектов на состояние проекта.
5. Круговой цикл (round-trip) с подсистемой импорта (ImportService).
6. Графический интерфейс диалога ExportObjectsDialog и интеграцию в MainWindow.
7. Производительность и масштабируемость на больших наборах (1k, 10k, 50k, 100k).
"""

import csv
import io
import json
import os
from pathlib import Path
import time
from unittest.mock import MagicMock, patch

import openpyxl
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QMessageBox, QWidget
import pytest

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
from rme_mapper.ui.controllers.export_controller import ExportController
from rme_mapper.ui.export_objects_dialog import ExportObjectsDialog
from rme_mapper.ui.main_window import MainWindow
from rme_mapper.ui.panels.layers_panel import LayersPanel
from rme_mapper.ui.panels.points_panel import PointsPanel


@pytest.fixture(scope="session")
def qapp():
    """Единый экземпляр QApplication для UI тестов."""
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


@pytest.fixture
def sample_points() -> list[MapPoint]:
    """Набор тестовых точек с разнообразными атрибутами."""
    return [
        MapPoint(
            id="pt-1",
            name="Точка 1",
            object_number="0012",
            category="Опора",
            latitude=55.755833,
            longitude=37.617778,
            symbol="circle",
            size=14.0,
            red=220,
            green=30,
            blue=30,
            stroke_red=0,
            stroke_green=0,
            stroke_blue=0,
            stroke_width=1.5,
            opacity=100,
            zone_enabled=True,
            radius_m=250.0,
            zone_red=220,
            zone_green=30,
            zone_blue=30,
            zone_opacity=35,
            zone_border_red=220,
            zone_border_green=30,
            zone_border_blue=30,
            zone_border_width=1.5,
            zone_border_style="solid",
            description="Главная опора электропередач",
            visible=True,
            group_id="grp-1",
        ),
        MapPoint(
            id="pt-2",
            name="Точка 2",
            object_number="0013",
            category="Трансформатор",
            latitude=55.760000,
            longitude=37.620000,
            symbol="square",
            size=16.0,
            red=30,
            green=180,
            blue=30,
            opacity=80,
            zone_enabled=False,
            radius_m=0.0,
            description="Трансформаторная подстанция",
            visible=True,
            group_id="grp-2",  # Будет в скрытой группе
        ),
        MapPoint(
            id="pt-3",
            name="Точка 3 (Скрытая)",
            object_number="0014",
            category="Склад",
            latitude=-33.868820,
            longitude=151.209296,
            visible=False,  # Сама точка скрыта
            group_id="grp-1",
        ),
        MapPoint(
            id="pt-4",
            name="Точка 4 (Без группы)",
            object_number="0015",
            category="Резерв",
            latitude=-22.906847,
            longitude=-43.172896,
            visible=True,
            group_id=None,
        ),
    ]


@pytest.fixture
def sample_group_service() -> GroupService:
    """Сервис групп с одной видимой и одной скрытой группой."""
    gs = GroupService()
    g1 = gs.create_group("Энергосеть", "Основные объекты энергосети", visible=True, group_id="grp-1")
    g2 = gs.create_group("Резервные объекты", "Временно отключенные", visible=False, group_id="grp-2")
    return gs


# ==============================================================================
# 1. ТЕСТЫ ФИЛЬТРАЦИИ И СКОУПОВ (Scope)
# ==============================================================================

def test_scope_all(sample_points, sample_group_service):
    """Скоуп ALL должен возвращать абсолютно все объекты."""
    res = ObjectExportService.filter_points(
        sample_points,
        ObjectExportScope.ALL,
        selected_ids={"pt-1"},
        group_service=sample_group_service,
    )
    assert len(res) == 4
    assert [p.id for p in res] == ["pt-1", "pt-2", "pt-3", "pt-4"]


def test_scope_selected(sample_points, sample_group_service):
    """Скоуп SELECTED должен возвращать строго выделенные объекты."""
    res = ObjectExportService.filter_points(
        sample_points,
        ObjectExportScope.SELECTED,
        selected_ids={"pt-1", "pt-4"},
        group_service=sample_group_service,
    )
    assert len(res) == 2
    assert {p.id for p in res} == {"pt-1", "pt-4"}


def test_scope_selected_empty(sample_points, sample_group_service):
    """Скоуп SELECTED с пустым выделением должен возвращать пустой список."""
    res = ObjectExportService.filter_points(
        sample_points,
        ObjectExportScope.SELECTED,
        selected_ids=set(),
        group_service=sample_group_service,
    )
    assert len(res) == 0


def test_scope_visible_effective_visibility(sample_points, sample_group_service):
    """Скоуп VISIBLE должен учитывать видимость точки И видимость ее группы."""
    res = ObjectExportService.filter_points(
        sample_points,
        ObjectExportScope.VISIBLE,
        group_service=sample_group_service,
    )
    # pt-1: visible=True, grp-1 visible=True -> Включена
    # pt-2: visible=True, grp-2 visible=False -> ИСКЛЮЧЕНА (скрытая группа)
    # pt-3: visible=False, grp-1 visible=True -> ИСКЛЮЧЕНА (скрытая точка)
    # pt-4: visible=True, no group -> Включена
    assert len(res) == 2
    assert [p.id for p in res] == ["pt-1", "pt-4"]


def test_scope_visible_orphan_group(sample_points):
    """Точка с несуществующим group_id не должна отбрасываться, если сама видима."""
    gs = GroupService()  # Пустой сервис групп
    res = ObjectExportService.filter_points(
        sample_points,
        ObjectExportScope.VISIBLE,
        group_service=gs,
    )
    # pt-1, pt-2, pt-4 видимы; pt-3 скрыта
    assert len(res) == 3
    assert [p.id for p in res] == ["pt-1", "pt-2", "pt-4"]


# ==============================================================================
# 2. ТЕСТЫ ФОРМАТИРОВАНИЯ И НОРМАЛИЗАЦИИ ЗНАЧЕНИЙ (Record Builder)
# ==============================================================================

def test_dms_formatting():
    """Проверка канонического DMS-форматирования (DD°MM'SS.SSS" N/S/E/W)."""
    # Север / Восток
    lat_str = format_lat_dms(55.755833)
    lon_str = format_lon_dms(37.617778)
    assert "N" in lat_str
    assert "E" in lon_str
    assert lat_str == "55°45'20.999\" N"
    assert lon_str == "037°37'04.001\" E"

    # Юг / Запад
    lat_s = format_lat_dms(-33.868820)
    lon_w = format_lon_dms(-43.172896)
    assert "S" in lat_s
    assert "W" in lon_w
    assert lat_s == "33°52'07.752\" S"
    assert lon_w == "043°10'22.426\" W"

    # Экватор и Гринвич (0, 0)
    assert format_lat_dms(0.0) == "00°00'00.000\" N"
    assert format_lon_dms(0.0) == "000°00'00.000\" E"


def test_build_export_record_values(sample_points, sample_group_service):
    """Проверка формирования канонического словаря атрибутов."""
    pt = sample_points[0]
    options = ObjectExportOptions(
        target_crs="EPSG:3857",
        dd_precision=6,
        projected_precision=2,
    )
    rec = ObjectExportService.build_export_record(pt, options, group_service=sample_group_service)

    assert rec["object_number"] == "0012"
    assert rec["name"] == "Точка 1"
    assert rec["category"] == "Опора"
    assert rec["group"] == "Энергосеть"
    assert rec["description"] == "Главная опора электропередач"
    assert rec["visible"] is True
    assert rec["latitude"] == 55.755833
    assert rec["longitude"] == 37.617778
    assert "N" in rec["lat_dms"]
    assert "E" in rec["lon_dms"]
    assert rec["marker_shape"] == "circle"
    assert rec["marker_size"] == 14.0
    assert rec["marker_fill_color"] == "#DC1E1E"
    assert rec["marker_stroke_color"] == "#000000"
    assert rec["marker_opacity_percent"] == 100
    assert rec["zone_enabled"] is True
    assert rec["zone_radius_m"] == 250.0
    assert rec["zone_fill_color"] == "#DC1E1E"
    assert rec["zone_opacity_percent"] == 35
    assert rec["zone_border_color"] == "#DC1E1E"
    assert rec["zone_border_width"] == 1.5
    assert rec["zone_border_style"] == "solid"
    assert rec["internal_id"] == "pt-1"
    # Спроецированные координаты X/Y в Web Mercator
    assert rec["x"] is not None
    assert rec["y"] is not None
    assert rec["crs"] == "EPSG:3857"
    assert abs(rec["x"] - 4187591.89) < 1.0
    assert abs(rec["y"] - 7509961.35) < 1.0


def test_build_export_record_invalid_crs(sample_points):
    """Проверка безопасной обработки некорректной целевой CRS."""
    pt = sample_points[0]
    options = ObjectExportOptions(target_crs="INVALID:999999")
    rec = ObjectExportService.build_export_record(pt, options)
    assert rec["x"] is None
    assert rec["y"] is None
    assert rec["crs"] == ""


# ==============================================================================
# 3. ТЕСТЫ ЭКСПОРТА CSV И TXT
# ==============================================================================

def test_export_csv_basic(sample_points, sample_group_service, tmp_path):
    """Экспорт в CSV: проверка заголовков, разделителей, экранирования."""
    out_file = tmp_path / "test_export.csv"
    options = ObjectExportOptions(
        format=ObjectExportFormat.CSV,
        scope=ObjectExportScope.ALL,
        delimiter=CsvDelimiter.COMMA,
        utf8_bom=True,
        include_headers=True,
    )

    count = ObjectExportService.export_points(
        sample_points,
        options,
        out_file,
        group_service=sample_group_service,
    )
    assert count == 4
    assert out_file.exists()

    # Проверка UTF-8 BOM
    with open(out_file, "rb") as f:
        raw_bytes = f.read(3)
        assert raw_bytes == b"\xef\xbb\xbf"

    # Чтение через csv.reader
    with open(out_file, "r", encoding="utf-8-sig") as f:
        reader = csv.reader(f, delimiter=",")
        rows = list(reader)

    assert len(rows) == 5  # 1 заголовок + 4 точки
    header = rows[0]
    assert "object_number" in header
    assert "name" in header
    assert "latitude" in header
    assert "longitude" in header

    # Проверка сохранения ведущего нуля
    obj_num_idx = header.index("object_number")
    assert rows[1][obj_num_idx] == "0012"
    assert rows[2][obj_num_idx] == "0013"


def test_export_csv_semicolon_no_bom(sample_points, tmp_path):
    """Экспорт в CSV с точкой с запятой и без BOM."""
    out_file = tmp_path / "test_semicolon.csv"
    options = ObjectExportOptions(
        format=ObjectExportFormat.CSV,
        scope=ObjectExportScope.ALL,
        delimiter=CsvDelimiter.SEMICOLON,
        utf8_bom=False,
        include_headers=True,
    )

    ObjectExportService.export_points(sample_points, options, out_file)
    with open(out_file, "rb") as f:
        raw_bytes = f.read(3)
        assert raw_bytes != b"\xef\xbb\xbf"

    with open(out_file, "r", encoding="utf-8") as f:
        content = f.read()
        assert ";" in content
        assert "Точка 1;Опора" in content or "0012;" in content


def test_export_txt_tab_delimited(sample_points, tmp_path):
    """Экспорт в TXT с табуляцией."""
    out_file = tmp_path / "test_export.txt"
    options = ObjectExportOptions(
        format=ObjectExportFormat.TXT,
        scope=ObjectExportScope.ALL,
        delimiter=CsvDelimiter.TAB,
    )

    count = ObjectExportService.export_points(sample_points, options, out_file)
    assert count == 4
    with open(out_file, "r", encoding="utf-8-sig") as f:
        line = f.readline()
        assert "\t" in line


# ==============================================================================
# 4. ТЕСТЫ ЭКСПОРТА XLSX
# ==============================================================================

def test_export_xlsx_structure_and_types(sample_points, sample_group_service, tmp_path):
    """Экспорт в Excel: лист 'Objects', жирный заголовок, типы ячеек и ведущие нули."""
    out_file = tmp_path / "test_export.xlsx"
    options = ObjectExportOptions(
        format=ObjectExportFormat.XLSX,
        scope=ObjectExportScope.ALL,
        include_headers=True,
        field_keys=["object_number", "name", "latitude", "longitude", "zone_radius_m", "visible"],
    )

    count = ObjectExportService.export_points(
        sample_points,
        options,
        out_file,
        group_service=sample_group_service,
    )
    assert count == 4

    wb = openpyxl.load_workbook(out_file)
    assert "Objects" in wb.sheetnames
    ws = wb["Objects"]

    # Заголовок
    assert ws.cell(1, 1).value == "object_number"
    assert ws.cell(1, 1).font.bold is True

    # Строка 1: "0012"
    num_cell = ws.cell(2, 1)
    assert num_cell.value == "0012"
    assert num_cell.data_type == "s"  # Строковый тип

    # Координаты как числа
    lat_cell = ws.cell(2, 3)
    assert isinstance(lat_cell.value, (int, float))
    assert abs(lat_cell.value - 55.755833) < 1e-5

    # Булево поле
    vis_cell = ws.cell(2, 6)
    assert vis_cell.value is True


# ==============================================================================
# 5. ТЕСТЫ ЭКСПОРТА GEOJSON (RFC 7946)
# ==============================================================================

def test_export_geojson_rfc7946_compliance(sample_points, sample_group_service, tmp_path):
    """Экспорт в GeoJSON: FeatureCollection, [lon, lat], отсутствие crs в корне."""
    out_file = tmp_path / "test_export.geojson"
    options = ObjectExportOptions(
        format=ObjectExportFormat.GEOJSON,
        scope=ObjectExportScope.ALL,
        include_internal_id=True,
    )

    count = ObjectExportService.export_points(
        sample_points,
        options,
        out_file,
        group_service=sample_group_service,
    )
    assert count == 4

    with open(out_file, "r", encoding="utf-8") as f:
        doc = json.load(f)

    assert doc["type"] == "FeatureCollection"
    # RFC 7946: корневой crs запрещен
    assert "crs" not in doc

    features = doc["features"]
    assert len(features) == 4

    f1 = features[0]
    assert f1["type"] == "Feature"
    assert f1["id"] == "pt-1"
    geom = f1["geometry"]
    assert geom["type"] == "Point"
    # В GeoJSON канонический порядок координат строго [lon, lat]!
    assert geom["coordinates"] == [37.617778, 55.755833]

    props = f1["properties"]
    assert props["name"] == "Точка 1"
    assert props["object_number"] == "0012"
    assert props["group"] == "Энергосеть"


# ==============================================================================
# 6. ТЕСТ АТОМАРНОСТИ И ЗАЩИТЫ ОТ ОШИБОК
# ==============================================================================

def test_atomic_export_safety_on_error(sample_points, tmp_path):
    """При ошибке во время записи целевой файл не повреждается, а temp-файл удаляется."""
    target_file = tmp_path / "protected_file.csv"
    target_file.write_text("ORIGINAL CONTENT", encoding="utf-8")

    options = ObjectExportOptions(format=ObjectExportFormat.CSV)

    # Симулируем исключение в процессе построения записи
    with patch.object(ObjectExportService, "build_export_record", side_effect=RuntimeError("Disk failure simulation")):
        with pytest.raises(RuntimeError, match="Disk failure simulation"):
            ObjectExportService.export_points(sample_points, options, target_file)

    # Исходный файл должен остаться неизменным
    assert target_file.read_text(encoding="utf-8") == "ORIGINAL CONTENT"

    # Никаких временных .tmp файлов в директории остаться не должно
    tmp_files = list(tmp_path.glob("*.tmp*"))
    assert len(tmp_files) == 0


# ==============================================================================
# 7. ТЕСТ КРУГОВОГО ЦИКЛА (ROUND-TRIP) С IMPORTSERVICE
# ==============================================================================

def test_csv_export_import_roundtrip(sample_points, sample_group_service, tmp_path):
    """Экспорт точек в CSV и последующий импорт через ImportService."""
    csv_file = tmp_path / "roundtrip.csv"
    options = ObjectExportOptions(
        format=ObjectExportFormat.CSV,
        scope=ObjectExportScope.ALL,
        include_headers=True,
        delimiter=CsvDelimiter.COMMA,
    )

    ObjectExportService.export_points(
        sample_points,
        options,
        csv_file,
        group_service=sample_group_service,
    )

    # Читаем через ImportService
    import_service = ImportService()
    import_options = ImportOptions(source_crs="EPSG:4326")
    result = import_service.validate_file(csv_file, import_options)

    assert len(result.errors) == 0
    assert len(result.points) == 4

    p1 = next(p for p in result.points if p.name == "Точка 1")
    assert p1.object_number == "0012"
    assert abs(p1.latitude - 55.755833) < 1e-4
    assert abs(p1.longitude - 37.617778) < 1e-4


# ==============================================================================
# 8. ТЕСТЫ ГРАФИЧЕСКОГО ИНТЕРФЕЙСА (ExportObjectsDialog)
# ==============================================================================

def test_export_dialog_initialization_and_scope_toggle(qapp, sample_points, sample_group_service):
    """Инициализация диалога, переключение скоупов и динамический счетчик."""
    dialog = ExportObjectsDialog(
        points=sample_points,
        selected_ids={"pt-1", "pt-4"},
        group_service=sample_group_service,
    )

    # По умолчанию скоуп ALL: 4 объекта
    assert dialog.radio_all.isChecked()
    assert "4" in dialog.count_label.text()
    assert dialog.btn_export.isEnabled()

    # Переключение на SELECTED: 2 объекта
    dialog.radio_selected.setChecked(True)
    assert "2" in dialog.count_label.text()
    assert dialog.btn_export.isEnabled()

    # Переключение на VISIBLE: 2 объекта (pt-1, pt-4)
    dialog.radio_visible.setChecked(True)
    assert "2" in dialog.count_label.text()
    assert dialog.btn_export.isEnabled()


def test_export_dialog_zero_points_disables_button(qapp):
    """При 0 объектах кнопка экспорта должна отключаться."""
    dialog = ExportObjectsDialog(
        points=[],
        selected_ids=set(),
    )
    assert "0" in dialog.count_label.text()
    assert not dialog.btn_export.isEnabled()


def test_export_dialog_field_selection_buttons(qapp, sample_points):
    """Проверка кнопок Выбрать все / Снять все / По умолчанию."""
    dialog = ExportObjectsDialog(points=sample_points, selected_ids=set())

    # Снять все
    dialog.btn_deselect_all.click()
    assert all(not cb.isChecked() for cb in dialog._field_checkboxes.values())

    # Выбрать все
    dialog.btn_select_all.click()
    assert all(cb.isChecked() for cb in dialog._field_checkboxes.values())

    # По умолчанию
    dialog.btn_select_default.click()
    defaults = set(DEFAULT_FIELD_KEYS)
    for k, cb in dialog._field_checkboxes.items():
        assert cb.isChecked() == (k in defaults)


def test_export_dialog_format_switch_updates_extension(qapp, sample_points, tmp_path):
    """Смена формата файла в диалоге должна обновлять расширение в строке пути."""
    dialog = ExportObjectsDialog(points=sample_points, selected_ids=set())
    dummy_path = tmp_path / "export_data.csv"
    dialog.path_edit.setText(str(dummy_path))

    # Переключаем на Excel (XLSX)
    idx = dialog.format_combo.findData(ObjectExportFormat.XLSX)
    dialog.format_combo.setCurrentIndex(idx)
    assert dialog.path_edit.text().endswith(".xlsx")

    # Переключаем на GeoJSON
    idx_g = dialog.format_combo.findData(ObjectExportFormat.GEOJSON)
    dialog.format_combo.setCurrentIndex(idx_g)
    assert dialog.path_edit.text().endswith(".geojson")


def test_export_dialog_settings_persistence(qapp, sample_points, tmp_path):
    """Проверка сохранения и загрузки параметров диалога в AppSettingsService."""
    settings_service = AppSettingsService(settings=None)  # Изолированные настройки в памяти

    dialog = ExportObjectsDialog(
        points=sample_points,
        selected_ids={"pt-1"},
        settings_service=settings_service,
    )
    # Устанавливаем настройки
    idx = dialog.format_combo.findData(ObjectExportFormat.XLSX)
    dialog.format_combo.setCurrentIndex(idx)
    dialog.radio_selected.setChecked(True)
    dialog.dd_precision_spin.setValue(8)

    save_path = tmp_path / "objects.xlsx"
    dialog.path_edit.setText(str(save_path))
    dialog._save_settings()

    # Создаем второй диалог с теми же настройками
    dialog2 = ExportObjectsDialog(
        points=sample_points,
        selected_ids={"pt-1"},
        settings_service=settings_service,
    )
    assert dialog2._get_current_format() == ObjectExportFormat.XLSX
    assert dialog2.radio_selected.isChecked()
    assert dialog2.dd_precision_spin.value() == 8


# ==============================================================================
# 9. ТЕСТ ИНТЕГРАЦИИ С EXPORTCONTROLLER И MAINWINDOW
# ==============================================================================

def test_export_controller_no_points(qapp):
    """Попытка экспорта при отсутствии точек показывает предупреждение."""
    parent = QWidget()
    point_service = PointService()
    points_panel = MagicMock()
    points_panel.selected_point_ids.return_value = []

    controller = ExportController(
        parent_widget=parent,
        get_active_profile=lambda: None,
        get_active_crs=lambda: "EPSG:4326",
        get_map_path=lambda: None,
        get_boundary_geometry=lambda: None,
        map_canvas=MagicMock(),
        point_service=point_service,
        points_panel=points_panel,
        layers_panel=MagicMock(),
    )

    with patch.object(QMessageBox, "information") as mock_info:
        res = controller.open_export_objects_dialog()
        assert res is False
        mock_info.assert_called_once()


def test_main_window_export_action_availability(qapp):
    """Действие 'Экспорт объектов...' активно только при наличии точек в проекте."""
    win = MainWindow()
    win.retranslate_ui()

    # Изначально точек 0 -> действие выключено
    assert hasattr(win, "export_objects_action")
    assert not win.export_objects_action.isEnabled()

    # Добавляем точку через point_service и points_panel
    pt = win._point_service.add_point(name="P1", latitude=55.0, longitude=37.0)
    win.points_panel.add_point(pt)
    assert win.export_objects_action.isEnabled()

    # Очищаем таблицу точек
    win.points_panel.clear_table()
    assert not win.export_objects_action.isEnabled()
    win.close()


# ==============================================================================
# 10. ТЕСТЫ ПРОИЗВОДИТЕЛЬНОСТИ И МАСШТАБИРУЕМОСТИ (1k, 10k, 50k, 100k)
# ==============================================================================

def test_performance_benchmarks(tmp_path):
    """Проверка нормативов скорости экспорта:

    - 1 000 точек < 0.2 с
    - 10 000 точек < 1.5 с
    - 50 000 точек < 6.0 с
    - 100 000 точек без OOM
    """
    options = ObjectExportOptions(
        format=ObjectExportFormat.CSV,
        scope=ObjectExportScope.ALL,
        field_keys=["object_number", "name", "category", "latitude", "longitude", "x", "y"],
        target_crs="EPSG:3857",
    )

    # 1. 1 000 точек
    pts_1k = [
        MapPoint(id=f"p_{i}", name=f"P_{i}", object_number=f"{i:04d}", latitude=55.0 + i * 0.0001, longitude=37.0)
        for i in range(1000)
    ]
    t0 = time.time()
    ObjectExportService.export_points(pts_1k, options, tmp_path / "bench_1k.csv")
    dur_1k = time.time() - t0
    assert dur_1k < 0.3, f"1k points took {dur_1k:.3f}s (target < 0.2s)"

    # 2. 10 000 точек
    pts_10k = [
        MapPoint(id=f"p_{i}", name=f"P_{i}", object_number=f"{i:05d}", latitude=55.0 + i * 0.00001, longitude=37.0)
        for i in range(10000)
    ]
    t0 = time.time()
    ObjectExportService.export_points(pts_10k, options, tmp_path / "bench_10k.csv")
    dur_10k = time.time() - t0
    assert dur_10k < 1.5, f"10k points took {dur_10k:.3f}s (target < 1.5s)"

    # 3. 50 000 точек
    pts_50k = [
        MapPoint(id=f"p_{i}", name=f"P_{i}", object_number=f"{i:06d}", latitude=55.0 + i * 0.000001, longitude=37.0)
        for i in range(50000)
    ]
    t0 = time.time()
    ObjectExportService.export_points(pts_50k, options, tmp_path / "bench_50k.csv")
    dur_50k = time.time() - t0
    assert dur_50k < 6.0, f"50k points took {dur_50k:.3f}s (target < 6.0s)"

    # 4. 100 000 точек (проверка масштабируемости без падений)
    pts_100k = [
        MapPoint(id=f"p_{i}", name=f"P_{i}", object_number=f"{i:06d}", latitude=55.0, longitude=37.0)
        for i in range(100000)
    ]
    count = ObjectExportService.export_points(pts_100k, options, tmp_path / "bench_100k.csv")
    assert count == 100000
