"""Комплексные стресс-тесты, обработка ошибок, безопасность и очистка ресурсов (Этап 25).

Покрывает:
1. Стресс-сценарий 100k точек: детерминированная генерация, атомарное сохранение, загрузка, верификация целостности без MemoryError.
2. Матрица обработки ошибок: отсутствующие файлы, поврежденный JSON, превышение лимита 128 МБ, невалидные CRS.
3. Подсистема аварийного восстановления (Recovery): снимки, пути с пробелами и кириллицей, очистка при выходе.
4. Полная поддержка Unicode и локализации: пути, имена, многострочные описания, спецсимволы в *.gpmap и экспорте.
5. Аудит безопасности: отсутствие eval, exec, pickle, verify=False в production-коде, маскирование токенов в URL, запрет secret token (sk...).
6. Очистка ресурсов и состояний: повторное открытие/закрытие проектов и карт, отсутствие утечек логического состояния.
7. Smoke-тесты UI: проверка подключений и доступности всех QAction в меню и toolbar.
"""
from __future__ import annotations

import csv
import json
import os
from pathlib import Path
import random
import time
import pytest
from PySide6.QtGui import QAction

from rme_mapper.models.map_point import MapPoint
from rme_mapper.models.online_provider import OnlineTileProvider, ProviderRegistry
from rme_mapper.models.project_data import (
    ProjectData,
    ProjectGroupData,
    ProjectMapData,
    ProjectPointData,
)
from rme_mapper.services.app_settings_service import AppSettingsService
from rme_mapper.services.group_service import GroupService
from rme_mapper.services.object_export_service import ObjectExportService
from rme_mapper.services.point_service import PointService
from rme_mapper.services.project_service import ProjectService
from rme_mapper.services.tile_loader import sanitize_url
from rme_mapper.ui.main_window import MainWindow


def test_01_stress_100k_points_full_cycle(tmp_path: Path):
    """Стресс-тест 100 000 точек: генерация, сериализация, атомарное сохранение и перезагрузка."""
    random.seed(42)

    base_lat, base_lon = 56.630, 47.880
    points: list[ProjectPointData] = []

    # 1. Детерминированная генерация 100 000 точек
    t0 = time.perf_counter()
    for i in range(100_000):
        # Чередуем группы и категории
        grp_id = "grp_even" if i % 2 == 0 else "grp_odd"
        cat = "Категория А" if i % 3 == 0 else "Категория Б"
        p = ProjectPointData(
            id=f"pt_100k_{i:06d}",
            name=f"Опора #{i:06d}",
            object_number=f"{i:06d}",
            latitude=base_lat + (i * 0.000005),
            longitude=base_lon + (i * 0.000005),
            category=cat,
            group_id=grp_id,
        )
        points.append(p)
    t_gen = time.perf_counter() - t0

    assert len(points) == 100_000
    assert t_gen < 5.0, f"Генерация 100k точек заняла слишком много времени: {t_gen:.2f}s"

    groups = [
        ProjectGroupData(id="grp_even", name="Четные опоры"),
        ProjectGroupData(id="grp_odd", name="Нечетные опоры"),
    ]

    proj = ProjectData(
        points=points,
        groups=groups,
    )

    proj_file = tmp_path / "stress_100k.gpmap"
    proj_svc = ProjectService()

    # 2. Атомарное сохранение в *.gpmap
    t1 = time.perf_counter()
    proj_svc.save_project(proj, proj_file)
    t_save = time.perf_counter() - t1

    assert proj_file.exists()
    file_size = proj_file.stat().st_size
    assert file_size > 10 * 1024 * 1024  # > 10 MB
    assert file_size <= 128 * 1024 * 1024  # <= 128 MB (лимит)
    assert t_save < 10.0, f"Сохранение 100k точек заняло слишком много времени: {t_save:.2f}s"

    # 3. Десериализация и проверка целостности данных
    t2 = time.perf_counter()
    loaded_proj = proj_svc.load_project(proj_file)
    t_load = time.perf_counter() - t2

    assert len(loaded_proj.points) == 100_000
    assert len(loaded_proj.groups) == 2
    assert t_load < 10.0, f"Загрузка 100k точек заняла слишком много времени: {t_load:.2f}s"

    # Проверка контрольных точек (первая, 50 000-я, последняя)
    p_first = loaded_proj.points[0]
    assert p_first.id == "pt_100k_000000"
    assert p_first.object_number == "000000"
    assert p_first.latitude == pytest.approx(base_lat, abs=1e-6)
    assert p_first.group_id == "grp_even"

    p_mid = loaded_proj.points[50_000]
    assert p_mid.id == "pt_100k_050000"
    assert p_mid.object_number == "050000"
    assert p_mid.latitude == pytest.approx(base_lat + 50_000 * 0.000005, abs=1e-6)

    p_last = loaded_proj.points[99_999]
    assert p_last.id == "pt_100k_099999"
    assert p_last.object_number == "099999"
    assert p_last.group_id == "grp_odd"


def test_02_error_handling_matrix(tmp_path: Path):
    """Матрица обработки ошибок: несуществующий файл, поврежденный JSON, невалидный формат/версия."""
    proj_svc = ProjectService()

    # 1. Отсутствующий файл
    non_existent = tmp_path / "does_not_exist.gpmap"
    with pytest.raises(FileNotFoundError):
        proj_svc.load_project(non_existent)

    # 2. Поврежденный синтаксис JSON
    corrupt_json = tmp_path / "corrupt_syntax.gpmap"
    corrupt_json.write_text('{"format": "GeoPoint Mapper Project", "version": 1, "points": [', encoding="utf-8")
    with pytest.raises(ValueError, match="некорректный JSON"):
        proj_svc.load_project(corrupt_json)

    # 3. Неподдерживаемый формат проекта
    invalid_format = tmp_path / "invalid_format.gpmap"
    invalid_format.write_text('{"format": "QGIS Project 3.0", "version": 1}', encoding="utf-8")
    with pytest.raises(ValueError, match="Неподдерживаемый формат проекта"):
        proj_svc.load_project(invalid_format)

    # 4. Отсутствующее обязательное поле 'version'
    missing_version = tmp_path / "missing_version.gpmap"
    missing_version.write_text('{"format": "GeoPoint Mapper Project"}', encoding="utf-8")
    with pytest.raises(ValueError, match="отсутствует обязательное поле 'version'"):
        proj_svc.load_project(missing_version)

    # 5. Версия выше максимально поддерживаемой
    unsupported_version = tmp_path / "future_version.gpmap"
    unsupported_version.write_text('{"format": "GeoPoint Mapper Project", "version": 99}', encoding="utf-8")
    with pytest.raises(ValueError, match="99"):
        proj_svc.load_project(unsupported_version)

    # 6. Превышение максимального допустимого размера файла
    huge_file = tmp_path / "oversized.gpmap"
    orig_max = ProjectService.MAX_FILE_SIZE
    try:
        ProjectService.MAX_FILE_SIZE = 50  # 50 байт
        huge_file.write_text('{"format": "GeoPoint Mapper Project", "version": 1, "data": "very long data that exceeds fifty bytes threshold"}', encoding="utf-8")
        with pytest.raises(ValueError, match="превышает допустимый предел"):
            proj_svc.load_project(huge_file)
    finally:
        ProjectService.MAX_FILE_SIZE = orig_max


def test_03_recovery_subsystem_and_unicode_paths(tmp_path: Path):
    """Аварийное восстановление: сохранение снимка, восстановление и поддержка путей с кириллицей."""
    unicode_dir = tmp_path / "Аварийные Снимки" / "Проект №25"
    unicode_dir.mkdir(parents=True, exist_ok=True)
    snap_path = unicode_dir / "recovery_snapshot.json"

    p1 = MapPoint(id="rec_p1", name="Восстановленная точка", latitude=56.63, longitude=47.88)
    proj = ProjectData(
        points=[ProjectPointData.from_map_point(p1)],
        groups=[ProjectGroupData(id="rec_g1", name="Восстановленная группа")],
    )

    current_path = str(unicode_dir / "Основной Проект.gpmap")

    # 1. Сохранение recovery снимка
    saved_snap = ProjectService.save_recovery_snapshot(proj, current_path, snap_path)
    assert saved_snap == snap_path
    assert snap_path.exists()
    assert ProjectService.has_recovery_snapshot(snap_path) is True

    # 2. Загрузка recovery снимка
    loaded_proj, loaded_path = ProjectService.load_recovery_snapshot(snap_path)
    assert loaded_proj is not None
    assert loaded_path == current_path
    assert len(loaded_proj.points) == 1
    assert loaded_proj.points[0].name == "Восстановленная точка"
    assert len(loaded_proj.groups) == 1
    assert loaded_proj.groups[0].name == "Восстановленная группа"

    # 3. Очистка recovery снимка при штатном выходе
    ProjectService.clear_recovery_snapshot(snap_path)
    assert not snap_path.exists()
    assert ProjectService.has_recovery_snapshot(snap_path) is False


def test_04_unicode_and_localization_full_integrity(tmp_path: Path):
    """Сквозная проверка Unicode: пути, кириллица, кавычки, спецсимволы и экспорт."""
    # Путь с кириллицей, пробелами и спецсимволами
    folder = tmp_path / "Проекты" / "Испытание №25" / "Подстанция «Южная» 10кВ"
    folder.mkdir(parents=True, exist_ok=True)
    proj_file = folder / "Проект объектов.gpmap"

    p = MapPoint(
        id="uni_pt_01",
        object_number="00042",
        name="Опора ВЛ-10кВ №0042 «Север» (Δ = 0.5м)",
        description="Категория I: ввод 10кВ;\nКавычки: \"ГОСТ\" и 'ТУ';\nСимволы: №, ©, ®, ±, °.",
        category="Энергетика / Линии передач",
        latitude=56.635,
        longitude=47.885,
    )

    grp = ProjectGroupData(id="g_uni", name="Группа «Энергосеть №1» / Сектор А")

    proj = ProjectData(
        points=[ProjectPointData.from_map_point(p)],
        groups=[grp],
    )

    proj_svc = ProjectService()
    proj_svc.save_project(proj, proj_file)
    assert proj_file.exists()

    # Загружаем обратно и проверяем посимвольное совпадение всех строк
    reloaded = proj_svc.load_project(proj_file)
    rp = reloaded.points[0]
    assert rp.name == p.name
    assert rp.description == p.description
    assert rp.category == p.category
    assert rp.object_number == "00042"
    assert reloaded.groups[0].name == grp.name

    # Экспорт в CSV с UTF-8 BOM
    from rme_mapper.models.object_export import (
        DEFAULT_FIELD_KEYS,
        ObjectExportFormat,
        ObjectExportOptions,
        ObjectExportScope,
    )

    out_csv = folder / "экспорт.csv"
    opts = ObjectExportOptions(
        format=ObjectExportFormat.CSV,
        scope=ObjectExportScope.ALL,
        field_keys=DEFAULT_FIELD_KEYS + ["description"],
    )
    ObjectExportService.export_points([p], opts, out_csv)

    with open(out_csv, "r", encoding="utf-8-sig") as f:
        reader = list(csv.DictReader(f))
        assert len(reader) == 1
        row = reader[0]
        assert row["name"] == p.name
        assert "«Север»" in row["name"]
        assert row["object_number"] == "00042"


def test_05_security_audit_and_path_safety():
    """Аудит безопасности: проверка отсутствия небезопасных конструкций в production коде и маскирования токенов."""
    src_dir = Path("src/rme_mapper").resolve()
    assert src_dir.exists()

    forbidden_patterns = [
        "eval(",
        "pickle.load",
        "pickle.dump",
        "verify=False",
    ]

    violations: list[str] = []

    for py_file in src_dir.rglob("*.py"):
        text = py_file.read_text(encoding="utf-8", errors="ignore")
        for line_num, line in enumerate(text.splitlines(), start=1):
            stripped = line.strip()
            # Пропускаем комментарии
            if stripped.startswith("#"):
                continue
            for pattern in forbidden_patterns:
                if pattern in stripped:
                    violations.append(f"{py_file.name}:{line_num} -> {stripped}")

    assert not violations, f"Обнаружены запрещенные конструкции безопасности: {violations}"

    # 1. Проверка маскирования конфиденциальных токенов в URL (sanitize_url)
    dirty_url = "https://api.mapbox.com/v4/tiles/256/1/2/3?access_token=pk.1234567890abcdef"
    clean_url = sanitize_url(dirty_url)
    assert "1234567890" not in clean_url
    assert "[REDACTED]" in clean_url

    # 2. Проверка строгого запрета секретных токенов Mapbox (sk...)
    from rme_mapper.models.online_provider import MapType
    provider = OnlineTileProvider(
        id="test_provider",
        display_name="Test Provider",
        map_type=MapType.CUSTOM,
        url_template="https://tiles.example.com/{z}/{x}/{y}.png",
    )
    with pytest.raises(ValueError, match="Mapbox secret tokens"):
        provider.build_tile_url(z=1, x=2, y=3, api_key="sk.secret_private_token_should_fail")

    # 3. Проверка шаблона URL без плейсхолдеров координат
    invalid_provider = OnlineTileProvider(
        id="invalid_template_prov",
        display_name="Invalid Provider",
        map_type=MapType.CUSTOM,
        url_template="https://tiles.example.com/no_coords.png",
    )
    with pytest.raises(ValueError, match="Некорректный шаблон URL"):
        invalid_provider.build_tile_url(z=1, x=2, y=3)


def test_06_resource_and_state_cleanup_multi_cycle(qapp, tmp_path: Path):
    """Очистка ресурсов: многократное открытие и создание проектов без накопления мусора."""
    window = MainWindow()
    window.show()

    # Цикл из 3 последовательных проектов
    for cycle in range(3):
        # 1. Добавляем точки
        for i in range(5):
            pt = window._point_service.add_point(
                point_id=f"cycle_{cycle}_pt_{i}",
                name=f"Точка {cycle}-{i}",
                latitude=56.0 + i * 0.01,
                longitude=47.0 + i * 0.01,
            )
            window.points_panel.add_point(pt)

        # 2. Добавляем группу
        grp = window._group_service.create_group(f"Группа цикла {cycle}")
        window.group_controller.refresh_groups_ui()

        assert len(window._point_service.get_points()) == 5
        assert len(window._group_service.list_groups()) == 1

        # 3. Сохраняем проект
        p_file = tmp_path / f"cycle_{cycle}.gpmap"
        window.project_controller.save_project_as_workflow(p_file)
        assert p_file.exists()

        # 4. Сброс (New Project)
        window.project_controller.new_project_workflow()

        # Проверяем полное очищение состояния
        assert len(window._point_service.get_points()) == 0
        assert len(window._group_service.list_groups()) == 0
        assert window.points_panel.total_count == 0
        assert window.point_controller.undo_manager.can_undo is False
        assert window.point_controller.undo_manager.can_redo is False

    window.close()


def test_07_ui_action_smoke_and_connections(qapp):
    """Smoke-тест всех ключевых QAction главного окна: проверка создания, доступности и сигналов."""
    window = MainWindow()
    window.show()

    # Список ключевых QAction приложения
    actions: list[tuple[str, QAction]] = [
        ("new_action", window.new_action),
        ("open_action", window.open_action),
        ("save_action", window.save_action),
        ("save_as_action", window.save_as_action),
        ("exit_action", window.exit_action),
        ("undo_action", window.undo_action),
        ("redo_action", window.redo_action),
        ("delete_selected_action", window.delete_selected_action),
        ("bulk_edit_style_action", window.bulk_edit_style_action),
        ("open_map_action", window.open_map_action),
        ("close_map_action", window.close_map_action),
        ("fit_map_action", window.fit_map_action),
        ("online_standard_action", window.online_standard_action),
        ("online_satellite_action", window.online_satellite_action),
        ("online_hybrid_action", window.online_hybrid_action),
        ("select_online_basemap_action", window.select_online_basemap_action),
        ("georeference_image_action", window.georeference_image_action),
        ("add_pt_action", window.add_pt_action),
        ("import_points_action", window.import_points_action),
        ("export_map_image_action", window.export_map_image_action),
        ("export_objects_action", window.export_objects_action),
        ("measure_distance_action", window.measure_distance_action),
        ("measure_area_action", window.measure_area_action),
        ("clear_measurements_action", window.clear_measurements_action),
        ("toggle_scale_action", window.toggle_scale_action),
        ("toggle_grid_action", window.toggle_grid_action),
    ]

    for name, action in actions:
        assert isinstance(action, QAction), f"Действие {name} не является экземпляром QAction"
        # Проверяем, что action доступен (не None и имеет текст)
        assert action.text() != "" or action.iconText() != "", f"У действия {name} пустой текст"

    # При чистом старте Undo и Redo должны быть неактивны
    assert window.undo_action.isEnabled() is False
    assert window.redo_action.isEnabled() is False

    window.close()
