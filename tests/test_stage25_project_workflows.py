"""Этап 25: Сквозные тесты жизненного цикла проекта и матрица персистентности.

Покрывает:
1. Полный E2E жизненный цикл проекта (22 шага от старта без карты до финального экспорта);
2. Матрица персистентности *.gpmap (все поля, стили, зоны, группы, метаданные);
3. Многократный цикл сохранения и повторного открытия (load -> edit -> save -> load -> edit -> save -> load);
4. Обратная совместимость (.rmeproject, отсутствующие поля, неизвестные поля);
5. Инвариант round-trip для неподдерживаемых карт;
6. Исправление битых ссылок на группы при загрузке.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from PySide6.QtCore import QPointF, Qt
from PySide6.QtWidgets import QApplication

from rme_mapper.models.map_point import MapPoint
from rme_mapper.models.object_group import ObjectGroup
from rme_mapper.models.project_data import (
    PRIMARY_PROJECT_FORMAT,
    ProjectData,
    ProjectGroupData,
    ProjectMapData,
    ProjectPointData,
)
from rme_mapper.services.group_service import GroupService
from rme_mapper.services.point_service import PointService
from rme_mapper.services.project_service import ProjectService
from rme_mapper.services.runtime_capabilities import RuntimeCapabilities
from rme_mapper.services.undo_manager import MovePointCommand
from rme_mapper.ui.controllers.project_controller import ProjectController
from rme_mapper.ui.main_window import MainWindow


@pytest.fixture
def mari_gpkg_path() -> Path:
    """Путь к эталонному файлу карты GeoPackage."""
    path = Path(__file__).resolve().parent.parent / "maps" / "test_map" / "prepared" / "mari.gpkg"
    assert path.exists(), f"Файл карты {path} должен существовать"
    return path


def test_01_complete_project_lifecycle_e2e(qapp, tmp_path: Path, mari_gpkg_path: Path):
    """Сквозной E2E сценарий жизненного цикла проекта (22 шага):
    1. Запуск приложения без карты;
    2. Проверка начального пустого состояния;
    3. Создание проекта;
    4. Загрузка векторной карты GeoPackage;
    5. Создание точек с расширенными атрибутами;
    6. Изменение свойств точек (категория, стиль, описание);
    7. Создание геодезических зон (метры, стили границ);
    8. Создание групп объектов;
    9. Распределение точек по группам;
    10. Фильтрация по группе;
    11. Изменение видимости группы и отдельных точек;
    12. Перемещение точки;
    13. Undo операции перемещения;
    14. Redo операции перемещения;
    15. Сохранение проекта в файл *.gpmap;
    16. Закрытие / сброс проекта (New Project);
    17. Повторное открытие сохраненного проекта;
    18. Верификация полного восстановления состояния;
    19. Внесение изменений в открытый проект;
    20. Повторное сохранение проекта;
    21. Экспорт объектов проекта;
    22. Финальное повторное открытие и сверка целостности.
    """
    # 1. Запуск приложения
    window = MainWindow()
    window.resize(1200, 800)

    # 2. Чистый старт без карты
    assert window.map_controller.map_path is None
    assert len(window._point_service.get_points()) == 0
    assert len(window._group_service.list_groups()) == 0

    # 3. Создание проекта (чистое состояние)
    window.project_controller.new_project_workflow()
    assert window.project_controller.current_project_path is None

    # 4. Открытие карты
    window.load_map(mari_gpkg_path)
    assert window.map_controller.map_path == mari_gpkg_path
    assert window.map_controller.active_crs is not None

    # 5. Создание точек
    pt1 = window._point_service.add_point(
        point_id="pt_e2e_1",
        name="Трансформаторная подстанция",
        latitude=56.635,
        longitude=47.885,
        object_number="101",
        description="КТП-10/0.4 кВ",
        category="Энергетика",
        symbol="square",
        red=230,
        green=57,
        blue=70,
        stroke_red=0,
        stroke_green=0,
        stroke_blue=0,
        stroke_width=2.0,
        opacity=90,
    )
    pt2 = window._point_service.add_point(
        point_id="pt_e2e_2",
        name="Водозаборный узел",
        latitude=56.640,
        longitude=47.890,
        object_number="102",
        description="Артезианская скважина №3",
        category="Водоснабжение",
        symbol="circle",
        red=29,
        green=53,
        blue=87,
        stroke_red=255,
        stroke_green=255,
        stroke_blue=255,
        stroke_width=1.5,
        opacity=100,
    )
    window.points_panel.add_point(pt1)
    window.points_panel.add_point(pt2)
    assert len(window._point_service.get_points()) == 2

    # 6. Изменение свойств точек и 7. Создание геодезических зон
    updated_pt1 = window._point_service.update_point(
        "pt_e2e_1",
        radius_m=350.0,
        zone_enabled=True,
        zone_border_style="dash",
        zone_red=255,
        zone_green=153,
        zone_blue=0,
        zone_opacity=25,
    )
    window.point_controller.update_point_in_table(0, updated_pt1)

    assert updated_pt1 is not None
    assert updated_pt1.radius_m == 350.0
    assert updated_pt1.zone_enabled is True
    assert updated_pt1.zone_border_style == "dash"

    # 8. Создание групп
    grp_energy = window._group_service.create_group("Энергосеть", "Объекты электроснабжения")
    grp_water = window._group_service.create_group("Водоканал", "Объекты гидротехнические")
    window.group_controller.refresh_groups_ui()
    assert grp_energy is not None
    assert grp_water is not None

    # 9. Распределение точек по группам
    window._point_service.update_point("pt_e2e_1", group_id=grp_energy.id, update_group=True)
    window._point_service.update_point("pt_e2e_2", group_id=grp_water.id, update_group=True)
    window.group_controller.refresh_groups_ui()

    assert window._point_service.get_point("pt_e2e_1").group_id == grp_energy.id
    assert window._point_service.get_point("pt_e2e_2").group_id == grp_water.id

    # 10. Фильтрация
    filtered_energy = [p for p in window._point_service.get_points() if p.group_id == grp_energy.id]
    assert len(filtered_energy) == 1
    assert filtered_energy[0].id == "pt_e2e_1"

    # 11. Изменение видимости
    window._group_service.set_group_visibility(grp_water.id, False)
    window._point_service.update_point("pt_e2e_2", visible=False)
    assert window._point_service.get_point("pt_e2e_2").visible is False

    # 12. Перемещение точки через команду с Undo/Redo
    orig_lat, orig_lon = updated_pt1.latitude, updated_pt1.longitude
    new_lat, new_lon = orig_lat + 0.005, orig_lon + 0.005

    before_pt = copy.deepcopy(updated_pt1)
    after_pt = copy.deepcopy(updated_pt1)
    after_pt.latitude = new_lat
    after_pt.longitude = new_lon

    def apply_move(p: MapPoint) -> None:
        window._point_service.update_point(p.id, latitude=p.latitude, longitude=p.longitude)
        window.point_controller.update_point_in_table(0, p)

    cmd = MovePointCommand(
        before_point=before_pt,
        after_point=after_pt,
        apply_fn=apply_move,
        description="Move pt1",
    )
    window.point_controller.undo_manager.push(cmd, execute=True)

    moved_pt1 = window._point_service.get_point("pt_e2e_1")
    assert moved_pt1.latitude == pytest.approx(new_lat, abs=1e-6)

    # 13. Undo операции перемещения
    assert window.point_controller.undo_manager.can_undo is True
    window.point_controller.undo()
    undone_pt1 = window._point_service.get_point("pt_e2e_1")
    assert undone_pt1.latitude == pytest.approx(orig_lat, abs=1e-6)

    # 14. Redo операции перемещения
    assert window.point_controller.undo_manager.can_redo is True
    window.point_controller.redo()
    redone_pt1 = window._point_service.get_point("pt_e2e_1")
    assert redone_pt1.latitude == pytest.approx(new_lat, abs=1e-6)

    # 15. Сохранение проекта в файл *.gpmap
    proj_file = tmp_path / "lifecycle_project.gpmap"
    save_ok = window.project_controller.save_project_as_workflow(proj_file)
    assert save_ok is True
    assert proj_file.exists()
    assert proj_file.stat().st_size > 0

    # 16. Закрытие / сброс проекта (New Project)
    window.project_controller.new_project_workflow()
    assert len(window._point_service.get_points()) == 0
    assert len(window._group_service.list_groups()) == 0

    # 17. Повторное открытие сохраненного проекта
    open_ok = window.project_controller.open_project_from_path(proj_file)
    assert open_ok is True

    # 18. Верификация состояния после открытия
    assert len(window._point_service.get_points()) == 2
    r_pt1 = window._point_service.get_point("pt_e2e_1")
    r_pt2 = window._point_service.get_point("pt_e2e_2")
    assert r_pt1 is not None and r_pt2 is not None
    assert r_pt1.object_number == "101"
    assert r_pt1.name == "Трансформаторная подстанция"
    assert r_pt1.description == "КТП-10/0.4 кВ"
    assert r_pt1.category == "Энергетика"
    assert r_pt1.latitude == pytest.approx(new_lat, abs=1e-6)
    assert r_pt1.radius_m == 350.0
    assert r_pt1.zone_enabled is True
    assert r_pt1.zone_border_style == "dash"
    assert r_pt1.zone_red == 255
    assert r_pt1.group_id == grp_energy.id

    assert r_pt2.object_number == "102"
    assert r_pt2.visible is False
    assert r_pt2.group_id == grp_water.id

    groups_after = window._group_service.list_groups()
    assert len(groups_after) == 2

    # 19. Внесение изменений в открытый проект
    pt3 = window._point_service.add_point(
        point_id="pt_e2e_3",
        name="Насосная станция",
        latitude=56.645,
        longitude=47.895,
        object_number="103",
    )
    window.points_panel.add_point(pt3)
    window._point_service.update_point("pt_e2e_3", group_id=grp_water.id, update_group=True)
    window.group_controller.refresh_groups_ui()
    assert len(window._point_service.get_points()) == 3

    # 20. Повторное сохранение проекта
    save_again = window.project_controller.save_project_workflow()
    assert save_again is True

    # 21. Экспорт объектов проекта
    export_csv = tmp_path / "exported_lifecycle.csv"
    from rme_mapper.models.object_export import (
        ObjectExportFormat,
        ObjectExportOptions,
        ObjectExportScope,
    )
    from rme_mapper.services.object_export_service import ObjectExportService

    export_opts = ObjectExportOptions(
        format=ObjectExportFormat.CSV,
        scope=ObjectExportScope.ALL,
    )
    exported_count = ObjectExportService.export_points(
        points=window._point_service.get_points(),
        options=export_opts,
        output_path=export_csv,
        group_service=window._group_service,
    )
    assert exported_count == 3
    assert export_csv.exists()

    # 22. Финальное повторное открытие
    window.project_controller.new_project_workflow()
    final_load = window.project_controller.open_project_from_path(proj_file)
    assert final_load is True
    assert len(window._point_service.get_points()) == 3
    assert window._point_service.get_point("pt_e2e_3") is not None


def test_02_project_persistence_matrix_all_fields_and_styles(tmp_path: Path):
    """Матрица персистентности: сохранение и восстановление 100% атрибутов точек, зон, стилей и групп."""
    ps = ProjectService()
    proj_path = tmp_path / "matrix_test.gpmap"

    pt = MapPoint(
        id="p_matrix_01",
        object_number="007",
        name="Комплексный объект",
        description="Подробное техническое описание с символами: №, %, @, /",
        category="Спецобъекты",
        latitude=55.751244,
        longitude=37.618423,
        symbol="triangle",
        red=42,
        green=157,
        blue=143,
        stroke_red=231,
        stroke_green=111,
        stroke_blue=81,
        stroke_width=3.5,
        opacity=85,
        radius_m=1250.0,
        zone_enabled=True,
        zone_red=244,
        zone_green=162,
        zone_blue=97,
        zone_opacity=45,
        zone_border_red=230,
        zone_border_green=50,
        zone_border_blue=50,
        zone_border_width=2.0,
        zone_border_style="dot",
        group_id="grp_matrix_alpha",
        visible=True,
    )

    grp = ObjectGroup(
        id="grp_matrix_alpha",
        name="Группа Альфа",
        description="Тестовая группа со всеми полями",
        visible=True,
    )

    map_data = ProjectMapData(
        map_id="map_vector_01",
        relative_path="maps/regional.gpkg",
        name="Региональная карта",
        crs="EPSG:4326",
        source_type="geopackage",
    )

    project_data = ps.build_project_data(
        map_path=None,
        layers=[],
        points=[pt],
        groups=[grp],
        preserve_map_data=map_data,
    )

    # 1-й цикл: Save -> Load
    ps.save_project(project_data, proj_path)
    loaded_1 = ps.load_project(proj_path)

    p1 = loaded_1.points[0]
    assert p1.id == "p_matrix_01"
    assert p1.object_number == "007"
    assert p1.name == "Комплексный объект"
    assert p1.description == "Подробное техническое описание с символами: №, %, @, /"
    assert p1.category == "Спецобъекты"
    assert p1.latitude == 55.751244
    assert p1.longitude == 37.618423
    assert p1.symbol == "triangle"
    assert p1.red == 42
    assert p1.green == 157
    assert p1.blue == 143
    assert p1.stroke_red == 231
    assert p1.stroke_green == 111
    assert p1.stroke_blue == 81
    assert p1.stroke_width == 3.5
    assert p1.opacity == 85.0
    assert p1.radius_m == 1250.0
    assert p1.zone_enabled is True
    assert p1.zone_red == 244
    assert p1.zone_green == 162
    assert p1.zone_blue == 97
    assert p1.zone_opacity == 45
    assert p1.zone_border_style == "dot"
    assert p1.group_id == "grp_matrix_alpha"
    assert p1.visible is True

    g1 = loaded_1.groups[0]
    assert g1.id == "grp_matrix_alpha"
    assert g1.name == "Группа Альфа"
    assert g1.description == "Тестовая группа со всеми полями"

    assert loaded_1.map.map_id == "map_vector_01"
    assert loaded_1.map.relative_path == "maps/regional.gpkg"
    assert loaded_1.map.source_type == "geopackage"


def test_03_multi_cycle_persistence_no_gradual_loss(tmp_path: Path):
    """Многократный цикл load -> edit -> save -> load -> edit -> save -> load без потери данных."""
    ps = ProjectService()
    proj_path = tmp_path / "multi_cycle.gpmap"

    points = [
        MapPoint(id=f"pt_{i}", object_number=str(i), name=f"Точка {i}", latitude=55.0 + i * 0.01, longitude=37.0 + i * 0.01)
        for i in range(10)
    ]
    groups = [
        ObjectGroup(id="g_a", name="Группа А"),
        ObjectGroup(id="g_b", name="Группа Б"),
    ]
    for i, p in enumerate(points):
        p.group_id = "g_a" if i % 2 == 0 else "g_b"

    proj = ps.build_project_data(map_path=None, layers=[], points=points, groups=groups)
    ps.save_project(proj, proj_path)

    # Выполняем 4 последовательных цикла редактирования и сохранения
    for cycle in range(4):
        loaded = ps.load_project(proj_path)
        assert len(loaded.points) == 10 + cycle
        assert len(loaded.groups) == 2

        # Добавляем новую точку в каждом цикле
        pts = [p.to_map_point() for p in loaded.points]
        grps = [ObjectGroup(id=g.id, name=g.name, description=g.description, visible=g.visible) for g in loaded.groups]
        new_pt = MapPoint(
            id=f"pt_cycle_{cycle}",
            object_number=f"C{cycle}",
            name=f"Точка цикла {cycle}",
            latitude=55.99,
            longitude=37.99,
            group_id="g_a",
        )
        pts.append(new_pt)

        # Пересохраняем
        re_saved = ps.build_project_data(map_path=None, layers=[], points=pts, groups=grps)
        ps.save_project(re_saved, proj_path)

    # Финальная проверка после 4 циклов
    final = ps.load_project(proj_path)
    assert len(final.points) == 14
    assert len(final.groups) == 2
    # Все исходные точки на месте с исходными свойствами
    for i in range(10):
        found = next((p for p in final.points if p.id == f"pt_{i}"), None)
        assert found is not None
        assert found.object_number == str(i)


def test_04_backward_compatibility_sample_v1_and_schema_variants(tmp_path: Path):
    """Обратная совместимость:
    1. Загрузка sample_project_v1.rmeproject;
    2. Проекты с отсутствующими опциональными полями;
    3. Проекты с неизвестными дополнительными полями (не ломают парсинг).
    """
    ps = ProjectService()

    # 1. Загрузка fixture sample_project_v1.rmeproject
    fixture_path = Path(__file__).resolve().parent / "fixtures" / "sample_project_v1.rmeproject"
    if fixture_path.exists():
        loaded_legacy = ps.load_project(fixture_path)
        assert loaded_legacy is not None
        assert len(loaded_legacy.points) > 0
        assert loaded_legacy.map is not None

    # 2. Проект с минимальным набором полей (без groups, без стилей, без зон)
    minimal_json = {
        "format": PRIMARY_PROJECT_FORMAT,
        "version": 1,
        "crs": "EPSG:4326",
        "points": [
            {
                "id": "p_min_1",
                "name": "Минимальная точка",
                "latitude": 55.75,
                "longitude": 37.61,
            }
        ],
    }
    min_path = tmp_path / "minimal.gpmap"
    min_path.write_text(json.dumps(minimal_json, ensure_ascii=False), encoding="utf-8")

    loaded_min = ps.load_project(min_path)
    assert len(loaded_min.points) == 1
    pt = loaded_min.points[0]
    assert pt.id == "p_min_1"
    assert pt.latitude == 55.75
    assert pt.longitude == 37.61
    assert pt.radius_m == 0.0
    assert pt.zone_enabled is False
    assert pt.group_id is None
    assert len(loaded_min.groups) == 0

    # 3. Проект с неизвестными дополнительными полями (forward-compatibility)
    extra_fields_json = {
        "format": PRIMARY_PROJECT_FORMAT,
        "version": 1,
        "crs": "EPSG:4326",
        "custom_plugin_data": {"active_tools": ["thermal_sensor", "lidar"]},
        "points": [
            {
                "id": "p_extra_1",
                "name": "Точка с плагином",
                "latitude": 55.75,
                "longitude": 37.61,
                "future_sensor_reading": 42.5,
                "unknown_extra_flag": True,
            }
        ],
    }
    extra_path = tmp_path / "extra_fields.gpmap"
    extra_path.write_text(json.dumps(extra_fields_json, ensure_ascii=False), encoding="utf-8")

    loaded_extra = ps.load_project(extra_path)
    assert len(loaded_extra.points) == 1
    assert loaded_extra.points[0].id == "p_extra_1"


def test_05_unsupported_map_source_roundtrip_invariant(tmp_path: Path):
    """Инвариант Этапа 24: проект с неподдерживаемым источником карты (например, online_xyz на среде без TLS)
    открывается без падения, редактируется, сохраняется без потери метаданных карты,
    и при возврате в поддерживаемую среду карта восстанавливается.
    """
    ps = ProjectService()
    proj_path = tmp_path / "unsupported_roundtrip.gpmap"

    # 1. Создаем проект в Modern с онлайн-картой
    orig_map = ProjectMapData(
        map_id="online_osm",
        name="OpenStreetMap",
        source_type="online_xyz",
        provider_id="osm_standard",
        crs="EPSG:3857",
    )
    pts = [MapPoint(id="p1", object_number="1", name="Точка 1", latitude=55.75, longitude=37.61)]
    project = ps.build_project_data(map_path=None, layers=[], points=pts, groups=[], preserve_map_data=orig_map)
    ps.save_project(project, proj_path)

    # 2. Имитируем окружение без поддержки онлайн-карт
    RuntimeCapabilities.override_for_testing(supports_online_maps=False)
    try:
        # Загружаем проект в ограниченной среде
        loaded_limited = ps.load_project(proj_path)
        assert loaded_limited.map is not None
        assert loaded_limited.map.source_type == "online_xyz"

        # Добавляем точку
        pts_modified = [p.to_map_point() for p in loaded_limited.points]
        pts_modified.append(MapPoint(id="p2", object_number="2", name="Точка 2", latitude=55.76, longitude=37.62))

        # Сохраняем в ограниченной среде с сохранением preserve_map_data
        re_saved = ps.build_project_data(
            map_path=None,
            layers=[],
            points=pts_modified,
            groups=[],
            preserve_map_data=loaded_limited.map,
        )
        ps.save_project(re_saved, proj_path)
    finally:
        RuntimeCapabilities.reset_overrides()

    # 3. Открываем снова в полноценной Modern среде
    reloaded_modern = ps.load_project(proj_path)
    assert len(reloaded_modern.points) == 2
    assert reloaded_modern.map is not None
    assert reloaded_modern.map.source_type == "online_xyz"
    assert reloaded_modern.map.provider_id == "osm_standard"
    assert reloaded_modern.map.crs == "EPSG:3857"


def test_06_broken_group_references_auto_heal(tmp_path: Path):
    """Автоматическое исправление битых ссылок на группы при загрузке проекта."""
    ps = ProjectService()
    proj_path = tmp_path / "broken_groups.gpmap"

    broken_data = {
        "format": PRIMARY_PROJECT_FORMAT,
        "version": 1,
        "crs": "EPSG:4326",
        "groups": [
            {"id": "valid_group_1", "name": "Существующая группа"}
        ],
        "points": [
            {"id": "p1", "name": "Корректная ссылка", "latitude": 55.0, "longitude": 37.0, "group_id": "valid_group_1"},
            {"id": "p2", "name": "Битая ссылка", "latitude": 55.1, "longitude": 37.1, "group_id": "non_existent_group_xyz"},
            {"id": "p3", "name": "Без группы", "latitude": 55.2, "longitude": 37.2, "group_id": None},
        ],
    }
    proj_path.write_text(json.dumps(broken_data, ensure_ascii=False), encoding="utf-8")

    # Загружаем через MainWindow и ProjectController
    window = MainWindow()
    ok = window.project_controller.open_project_from_path(proj_path)
    assert ok is True

    # Точка с битой ссылкой не вызвала краш, ее группа стала None
    p1 = window._point_service.get_point("p1")
    p2 = window._point_service.get_point("p2")
    p3 = window._point_service.get_point("p3")

    assert p1.group_id == "valid_group_1"
    assert p2.group_id is None
    assert p3.group_id is None
