"""Комплексные сквозные тесты импорта и экспорта (Этап 25).

Покрывает:
1. Полный сквозной workflow: Import -> Validate -> Edit -> Group -> Save -> Export.
2. Матрица форматов импорта (CSV, TXT, XLSX) и систем координат (DD, DMS, X/Y с авто-преобразованием).
3. Авто-определение разделителей, кодировок, сопоставление колонок и авто-создание групп.
4. Матрица экспорта: CSV, TXT, XLSX, GeoJSON; Scopes (All, Selected, Visible); Координаты (DD, DMS, X/Y).
5. Защита данных: Unicode/кириллица, сохранение ведущих нулей ('00123'), пустые поля.
6. Атомарность экспорта и валидация Target CRS (безопасность исходных файлов при сбоях).
7. Cross-Feature Scenario A: Import -> Groups -> Filter -> Export Visible.
8. Cross-Feature Scenario G: 10k points -> Filter -> Visible Export.
"""
from __future__ import annotations

import csv
import json
import math
from pathlib import Path
from typing import Any
import openpyxl
import pytest

from rme_mapper.importers.import_service import ImportService
from rme_mapper.importers.models import CoordinateFormat, ImportOptions
from rme_mapper.models.map_point import MapPoint
from rme_mapper.models.object_export import (
    DEFAULT_FIELD_KEYS,
    CsvDelimiter,
    ObjectExportFormat,
    ObjectExportOptions,
    ObjectExportScope,
)
from rme_mapper.models.object_group import ObjectGroup
from rme_mapper.models.project_data import ProjectGroupData
from rme_mapper.services.group_service import GroupService
from rme_mapper.services.object_export_service import ObjectExportService
from rme_mapper.services.point_service import PointService
from rme_mapper.services.project_service import ProjectService


def test_01_full_import_edit_group_save_export_pipeline(tmp_path: Path):
    """Сценарий: Import -> Validate -> Edit -> Group -> Save -> Export."""
    # 1. Подготовка исходного CSV файла
    csv_file = tmp_path / "raw_assets.csv"
    csv_content = (
        "number,name,latitude,longitude,category,group,desc,radius\n"
        "001,ТП-10/0.4,56.635,47.885,Энергетика,Север,Основная подстанция,250\n"
        "002,ВЗУ-3,56.640,47.890,Водоснабжение,Север,Скважинный водозабор,150\n"
        "003,ГРС-12,56.645,47.895,Газоснабжение,Юг,Газораспределительный пункт,300\n"
    )
    csv_file.write_text(csv_content, encoding="utf-8")

    # 2. Валидация и импорт через ImportService
    imp_svc = ImportService()
    opts = ImportOptions()
    opts.create_missing_groups = True
    opts.coordinate_format = CoordinateFormat.DD

    res = imp_svc.validate_file(csv_file, opts)
    assert res.valid_rows == 3
    assert len(res.points) == 3
    assert len(res.new_groups) == 2  # "Север", "Юг"

    # 3. Интеграция в сервисы проекта
    pt_svc = PointService()
    grp_svc = GroupService()

    # Добавляем созданные группы
    for g in res.new_groups:
        grp_svc.create_group(name=g.name, group_id=g.id)

    # Добавляем точки пакетом
    pt_svc.add_points_bulk(res.points)

    assert len(pt_svc.get_points()) == 3
    assert len(grp_svc.list_groups()) == 2

    # 4. Редактирование объектов (изменение атрибутов и стилей)
    p1 = pt_svc.get_point(res.points[0].id)
    assert p1.object_number == "001"
    pt_svc.update_point(
        p1.id,
        name="ТП-10/0.4 (Модернизированная)",
        radius_m=500.0,
        zone_enabled=True,
        zone_border_style="solid",
        zone_red=255,
        zone_green=0,
        zone_blue=0,
    )

    # Создание новой группы и переназначение точки
    grp_central = grp_svc.create_group("Центральный район", "Новая объединенная зона")
    pt_svc.update_point(res.points[1].id, group_id=grp_central.id, update_group=True)

    # 5. Сохранение проекта
    proj_path = tmp_path / "imported_pipeline.gpmap"
    proj_svc = ProjectService()
    from rme_mapper.models.project_data import ProjectData, ProjectGroupData, ProjectPointData
    proj = ProjectData(
        points=[ProjectPointData.from_map_point(p) for p in pt_svc.get_points()],
        groups=[
            ProjectGroupData(id=g.id, name=g.name, description=g.description, visible=g.visible)
            for g in grp_svc.list_groups()
        ],
    )
    proj_svc.save_project(proj, str(proj_path))
    assert proj_path.exists()

    # 6. Экспорт в CSV, XLSX и GeoJSON
    out_csv = tmp_path / "exported_pipeline.csv"
    out_xlsx = tmp_path / "exported_pipeline.xlsx"
    out_geojson = tmp_path / "exported_pipeline.geojson"

    exp_opts_csv = ObjectExportOptions(format=ObjectExportFormat.CSV, scope=ObjectExportScope.ALL)
    exp_opts_xlsx = ObjectExportOptions(format=ObjectExportFormat.XLSX, scope=ObjectExportScope.ALL)
    exp_opts_geojson = ObjectExportOptions(format=ObjectExportFormat.GEOJSON, scope=ObjectExportScope.ALL)

    c_csv = ObjectExportService.export_points(pt_svc.get_points(), exp_opts_csv, out_csv, group_service=grp_svc)
    c_xlsx = ObjectExportService.export_points(pt_svc.get_points(), exp_opts_xlsx, out_xlsx, group_service=grp_svc)
    c_geojson = ObjectExportService.export_points(pt_svc.get_points(), exp_opts_geojson, out_geojson, group_service=grp_svc)

    assert c_csv == 3 and c_xlsx == 3 and c_geojson == 3

    # Проверка сохранения изменений в экспорте
    with open(out_csv, "r", encoding="utf-8-sig") as f:
        reader = list(csv.DictReader(f))
        assert len(reader) == 3
        tp_row = next(r for r in reader if r.get("object_number") == "001")
        assert "Модернизированная" in tp_row["name"]

        vzu_row = next(r for r in reader if r.get("object_number") == "002")
        assert vzu_row["group"] == "Центральный район"

    # Проверка GeoJSON FeatureCollection
    with open(out_geojson, "r", encoding="utf-8") as f:
        gj_data = json.load(f)
        assert gj_data["type"] == "FeatureCollection"
        assert len(gj_data["features"]) == 3
        f0 = gj_data["features"][0]
        assert f0["geometry"]["type"] == "Point"
        assert len(f0["geometry"]["coordinates"]) == 2  # [lon, lat]


def test_02_import_format_matrix_dd_dms_xy_xlsx_txt(tmp_path: Path):
    """Матрица форматов импорта: DD (CSV/cp1251), DMS (TXT/tab), X/Y (XLSX с EPSG:3857)."""
    imp_svc = ImportService()

    # --- А: CSV c разделителем точка с запятой и кодировкой cp1251 ---
    csv_cp1251 = tmp_path / "points_cp1251.csv"
    csv_content = (
        "Номер;Название;Широта;Долгота;Категория\n"
        "101;Диспетчерская;56.635;47.885;Связь\n"
        "102;Вышка сотовой связи;56.636;47.886;Телеком\n"
    )
    csv_cp1251.write_bytes(csv_content.encode("cp1251"))

    # Чтение предпросмотра с авто-детекцией (encoding=None, delimiter=None)
    prev_opts = ImportOptions()
    rows, count, enc, delim = imp_svc.read_preview_rows(csv_cp1251, prev_opts, max_rows=10)
    assert count == 3
    assert enc in ("cp1251", "windows-1251")
    assert delim == ";"

    opts_a = ImportOptions()
    opts_a.encoding = enc
    opts_a.delimiter = delim
    res_a = imp_svc.validate_file(csv_cp1251, opts_a)
    assert res_a.valid_rows == 2
    assert res_a.points[0].name == "Диспетчерская"
    assert res_a.points[1].name == "Вышка сотовой связи"

    # --- Б: TXT/TSV с табуляцией и координатами DMS ---
    txt_dms = tmp_path / "points_dms.txt"
    txt_content = (
        "name\tlat_deg\tlat_min\tlat_sec\tlat_dir\tlon_deg\tlon_min\tlon_sec\tlon_dir\n"
        "Репер 1\t56\t38\t6.0\tN\t47\t53\t6.0\tE\n"
        "Репер 2\t56\t38\t24.0\tN\t47\t53\t42.0\tE\n"
    )
    txt_dms.write_text(txt_content, encoding="utf-8")

    opts_b = ImportOptions()
    opts_b.delimiter = "\t"
    opts_b.coordinate_format = CoordinateFormat.DMS
    res_b = imp_svc.validate_file(txt_dms, opts_b)
    assert res_b.valid_rows == 2
    assert res_b.points[0].latitude == pytest.approx(56.635, abs=1e-4)
    assert res_b.points[0].longitude == pytest.approx(47.885, abs=1e-4)
    assert res_b.points[1].latitude == pytest.approx(56.640, abs=1e-4)
    assert res_b.points[1].longitude == pytest.approx(47.895, abs=1e-4)

    # --- В: XLSX со спроецированными координатами X/Y (EPSG:3857) ---
    import pyproj
    transformer = pyproj.Transformer.from_crs("EPSG:4326", "EPSG:3857", always_xy=True)
    x1, y1 = transformer.transform(47.885, 56.635)
    x2, y2 = transformer.transform(47.895, 56.640)

    xlsx_file = tmp_path / "projected_points.xlsx"
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Objects"
    ws.append(["Name", "X", "Y", "Code"])
    ws.append(["Объект В-1", round(x1, 2), round(y1, 2), "X01"])
    ws.append(["Объект В-2", round(x2, 2), round(y2, 2), "X02"])
    wb.save(xlsx_file)
    wb.close()

    opts_c = ImportOptions()
    opts_c.coordinate_format = CoordinateFormat.XY
    opts_c.source_crs = "EPSG:3857"
    opts_c.column_mapping = {"name": "Name", "x": "X", "y": "Y", "object_number": "Code"}

    res_c = imp_svc.validate_file(xlsx_file, opts_c)
    assert res_c.valid_rows == 2
    assert res_c.points[0].latitude == pytest.approx(56.635, abs=1e-4)
    assert res_c.points[0].longitude == pytest.approx(47.885, abs=1e-4)
    assert res_c.points[0].object_number == "X01"


def test_03_export_scope_and_coordinate_matrix(tmp_path: Path):
    """Матрица экспорта: Scopes (All, Selected, Visible) и системы координат (DD, DMS, X/Y)."""
    grp_svc = GroupService()
    g_active = grp_svc.create_group("Активная группа")
    g_hidden = grp_svc.create_group("Скрытая группа")
    grp_svc.set_group_visibility(g_hidden.id, False)

    pts = [
        MapPoint(id="p1", name="P1", latitude=56.635, longitude=47.885, visible=True, group_id=g_active.id),
        MapPoint(id="p2", name="P2", latitude=56.640, longitude=47.890, visible=True, group_id=g_active.id),
        MapPoint(id="p3", name="P3", latitude=56.645, longitude=47.895, visible=False, group_id=g_active.id),
        MapPoint(id="p4", name="P4", latitude=56.650, longitude=47.900, visible=True, group_id=g_hidden.id),
    ]

    selected_ids = {"p1", "p3"}

    # 1. Проверка Scope: ALL
    f_all = ObjectExportService.filter_points(pts, ObjectExportScope.ALL, selected_ids, grp_svc)
    assert len(f_all) == 4

    # 2. Проверка Scope: SELECTED
    f_sel = ObjectExportService.filter_points(pts, ObjectExportScope.SELECTED, selected_ids, grp_svc)
    assert len(f_sel) == 2
    assert {p.id for p in f_sel} == {"p1", "p3"}

    # 3. Проверка Scope: VISIBLE (p1 и p2 видимы; p3 скрыта явно; p4 скрыта через группу)
    f_vis = ObjectExportService.filter_points(pts, ObjectExportScope.VISIBLE, selected_ids, grp_svc)
    assert len(f_vis) == 2
    assert {p.id for p in f_vis} == {"p1", "p2"}

    # 4. Проверка экспорта координат DD, DMS и X/Y (с target_crs = EPSG:3857)
    out_csv = tmp_path / "coords_matrix.csv"
    opts = ObjectExportOptions(
        format=ObjectExportFormat.CSV,
        scope=ObjectExportScope.ALL,
        target_crs="EPSG:3857",
        field_keys=[
            "name",
            "latitude",
            "longitude",
            "lat_dms",
            "lon_dms",
            "x",
            "y",
            "crs",
            "group",
        ],
    )

    count = ObjectExportService.export_points(pts, opts, out_csv, group_service=grp_svc)
    assert count == 4

    with open(out_csv, "r", encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
        r1 = rows[0]
        # Проверка DD
        assert float(r1["latitude"]) == pytest.approx(56.635, abs=1e-5)
        assert float(r1["longitude"]) == pytest.approx(47.885, abs=1e-5)
        # Проверка DMS
        assert "56°38'" in r1["lat_dms"] and "N" in r1["lat_dms"]
        assert "047°53'" in r1["lon_dms"] and "E" in r1["lon_dms"]
        # Проверка X/Y в EPSG:3857
        assert float(r1["x"]) > 5000000.0
        assert float(r1["y"]) > 7000000.0
        assert r1["crs"] == "EPSG:3857"
        assert r1["group"] == "Активная группа"


def test_04_export_data_integrity_unicode_leading_zeros(tmp_path: Path):
    """Целостность данных: кириллица, спецсимволы, ведущие нули ('00123') во всех форматах."""
    pts = [
        MapPoint(
            id="p_uni_1",
            object_number="00123",
            name="ТП №10/0.4 «Северное сияние»",
            description="Линия 1: ввод 10кВ;\nЛиния 2: отходящие фидеры 0.4кВ;\nКавычки: \"ГОСТ\" и 'ТУ'",
            category="Энергетика / Подстанции",
            latitude=56.635,
            longitude=47.885,
        ),
        MapPoint(
            id="p_uni_2",
            object_number="00007",
            name="Колодец К-7",
            description="",
            category="",
            latitude=56.640,
            longitude=47.890,
        ),
    ]

    all_keys = list(DEFAULT_FIELD_KEYS) + ["description"]

    # --- CSV ---
    csv_file = tmp_path / "unicode_export.csv"
    opts_csv = ObjectExportOptions(
        format=ObjectExportFormat.CSV,
        delimiter=CsvDelimiter.SEMICOLON,
        utf8_bom=True,
        field_keys=all_keys,
    )
    ObjectExportService.export_points(pts, opts_csv, csv_file)

    with open(csv_file, "r", encoding="utf-8-sig") as f:
        reader = list(csv.DictReader(f, delimiter=";"))
        assert len(reader) == 2
        assert reader[0]["object_number"] == "00123"
        assert reader[1]["object_number"] == "00007"
        assert "«Северное сияние»" in reader[0]["name"]
        assert "Линия 2" in reader[0]["description"]

    # --- XLSX ---
    xlsx_file = tmp_path / "unicode_export.xlsx"
    opts_xlsx = ObjectExportOptions(
        format=ObjectExportFormat.XLSX,
        field_keys=all_keys,
    )
    ObjectExportService.export_points(pts, opts_xlsx, xlsx_file)

    wb = openpyxl.load_workbook(xlsx_file)
    ws = wb["Objects"]
    headers = [cell.value for cell in ws[1]]
    num_idx = headers.index("object_number") + 1
    cell_val1 = ws.cell(row=2, column=num_idx).value
    cell_val2 = ws.cell(row=3, column=num_idx).value
    wb.close()

    assert cell_val1 == "00123"
    assert cell_val2 == "00007"

    # --- GeoJSON ---
    gj_file = tmp_path / "unicode_export.geojson"
    opts_gj = ObjectExportOptions(
        format=ObjectExportFormat.GEOJSON,
        field_keys=all_keys,
    )
    ObjectExportService.export_points(pts, opts_gj, gj_file)

    with open(gj_file, "r", encoding="utf-8") as f:
        gj = json.load(f)
        props = gj["features"][0]["properties"]
        assert props["object_number"] == "00123"
        assert "«Северное сияние»" in props["name"]
        assert "Линия 1" in props["description"]


def test_05_export_atomic_safety_and_crs_validation(tmp_path: Path):
    """Атомарная безопасность записи: невалидная целевая CRS не должна повреждать существующий файл."""
    pts = [MapPoint(id="pt1", name="Пункт 1", latitude=56.0, longitude=47.0)]
    target_file = tmp_path / "critical_data.csv"
    original_content = "ORIGINAL_SAFE_CONTENT_12345"
    target_file.write_text(original_content, encoding="utf-8")

    # Попытка экспорта координат X/Y с заведомо недопустимой Target CRS
    invalid_opts = ObjectExportOptions(
        format=ObjectExportFormat.CSV,
        field_keys=["name", "x", "y"],
        target_crs="EPSG:INVALID_CODE_99999",
    )

    with pytest.raises(ValueError, match="Недопустимая целевая система координат"):
        ObjectExportService.export_points(pts, invalid_opts, target_file)

    # Убеждаемся, что исходный файл не поврежден и остался точно таким же
    assert target_file.exists()
    assert target_file.read_text(encoding="utf-8") == original_content


def test_06_cross_feature_scenario_a_import_group_filter_export_visible(tmp_path: Path):
    """Cross-Feature Scenario A: Import -> Groups -> Filter -> Export Visible."""
    # 1. Импорт файла с 6 точками по 3 группам
    import_file = tmp_path / "scenario_a_input.csv"
    import_file.write_text(
        "name,latitude,longitude,group,object_number\n"
        "Объект А-1,56.630,47.880,Сеть А,A1\n"
        "Объект А-2,56.631,47.881,Сеть А,A2\n"
        "Объект Б-1,56.632,47.882,Сеть Б,B1\n"
        "Объект Б-2,56.633,47.883,Сеть Б,B2\n"
        "Объект В-1,56.634,47.884,Сеть В,C1\n"
        "Объект В-2,56.635,47.885,Сеть В,C2\n",
        encoding="utf-8",
    )

    imp_svc = ImportService()
    imp_opts = ImportOptions()
    imp_opts.create_missing_groups = True
    res = imp_svc.validate_file(import_file, imp_opts)
    assert res.valid_rows == 6
    assert len(res.new_groups) == 3

    grp_svc = GroupService()
    for g in res.new_groups:
        grp_svc.create_group(name=g.name, group_id=g.id)

    pt_svc = PointService()
    pt_svc.add_points_bulk(res.points)

    # 2. Фильтрация: отключаем видимость группы "Сеть Б"
    grp_b = next(g for g in grp_svc.list_groups() if g.name == "Сеть Б")
    grp_svc.set_group_visibility(grp_b.id, False)

    # 3. Экспорт только видимых объектов (Visible)
    out_csv = tmp_path / "scenario_a_visible.csv"
    exp_opts = ObjectExportOptions(
        format=ObjectExportFormat.CSV,
        scope=ObjectExportScope.VISIBLE,
        field_keys=["name", "group", "object_number"],
    )

    exported_count = ObjectExportService.export_points(
        points=pt_svc.get_points(),
        options=exp_opts,
        output_path=out_csv,
        group_service=grp_svc,
    )

    assert exported_count == 4

    with open(out_csv, "r", encoding="utf-8-sig") as f:
        exported_rows = list(csv.DictReader(f))
        assert len(exported_rows) == 4
        groups_in_export = {r["group"] for r in exported_rows}
        assert groups_in_export == {"Сеть А", "Сеть В"}
        assert "Сеть Б" not in groups_in_export


def test_07_cross_feature_scenario_g_large_dataset_filter_export(tmp_path: Path):
    """Cross-Feature Scenario G: 10,000 points -> Filter -> Visible Export."""
    import random
    import time

    random.seed(42)

    grp_svc = GroupService()
    g_active = grp_svc.create_group("Активная категория 10k")
    g_hidden = grp_svc.create_group("Скрытая категория 10k")
    grp_svc.set_group_visibility(g_hidden.id, False)

    # Генерируем детерминированно 10 000 точек
    points = []
    base_lat, base_lon = 56.63, 47.88
    for i in range(10000):
        # Четные в активную группу, нечетные в скрытую
        is_even = (i % 2 == 0)
        gid = g_active.id if is_even else g_hidden.id
        p = MapPoint(
            id=f"stress_pt_{i}",
            name=f"Стресс-Точка #{i:05d}",
            object_number=f"{i:05d}",
            latitude=base_lat + (i * 0.00001),
            longitude=base_lon + (i * 0.00001),
            category="Массовый тест",
            group_id=gid,
            visible=True,
        )
        points.append(p)

    out_csv = tmp_path / "stress_10k_visible.csv"
    exp_opts = ObjectExportOptions(
        format=ObjectExportFormat.CSV,
        scope=ObjectExportScope.VISIBLE,
        field_keys=["object_number", "name", "latitude", "longitude", "group"],
    )

    t0 = time.perf_counter()
    exported_count = ObjectExportService.export_points(
        points=points,
        options=exp_opts,
        output_path=out_csv,
        group_service=grp_svc,
    )
    t1 = time.perf_counter()

    # Ровно 5000 видимых точек должно быть экспортировано
    assert exported_count == 5000
    assert (t1 - t0) < 3.0, f"Экспорт 10k занял слишком много времени: {t1 - t0:.2f}s"

    # Проверка файла
    assert out_csv.exists()
    assert out_csv.stat().st_size > 100_000
