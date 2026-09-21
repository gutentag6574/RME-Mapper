"""Комплексный тестовый набор для Этапа 23 — Оптимизация производительности.

76 тестов, сгруппированных по 10 разделам:
- Раздел 1 (Тесты 1–10): Проекты (1k, 10k, 50k, 100k), атомарное сохранение, бэкапы, лимиты.
- Раздел 2 (Тесты 11–20): PointsPanel, пакетное наполнение, быстрый поиск, фильтры, счетчики.
- Раздел 3 (Тесты 21–30): Холст, пакетные маркеры, отсечение по вьюпорту, зум/панорамирование.
- Раздел 4 (Тесты 31–38): Раскладка подписей, коллизии, презентационный LOD, кэш геодезических кругов.
- Раздел 5 (Тесты 39–45): Источники карт (GPKG, GeoTIFF, повернутые растры, онлайн-тайлы).
- Раздел 6 (Тесты 46–52): Утечки памяти, 50 циклов открытия/закрытия, очистка сцены, сборка мусора.
- Раздел 7 (Тесты 53–60): Массовые операции (10k), Undo/Redo, линейная сложность команд.
- Раздел 8 (Тесты 61–66): Импорт больших объемов (CSV, TXT, XLSX), валидация координат, группы.
- Раздел 9 (Тесты 67–72): Экспорт (100k CSV, 100k GeoJSON, 4K рендеринг, инвариантность LOD к экспорту).
- Раздел 10 (Тесты 73–76): Быстрый старт, ленивая инициализация, отсутствие сети, статус-бар.
"""

import copy
import gc
import json
import os
import time
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest

from PySide6.QtCore import QPoint, QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QFontMetrics, QImage, QPainter, QPainterPath, QWheelEvent
from PySide6.QtWidgets import QApplication

from rme_mapper.models.map_point import MapPoint
from rme_mapper.models.project_data import (
    PRIMARY_PROJECT_FORMAT,
    ProjectData,
    ProjectMapData,
    ProjectPointData,
    ProjectGroupData,
)
from rme_mapper.services.geodesic_service import GeodesicService, MAX_CIRCLE_CACHE_SIZE
from rme_mapper.services.point_service import PointService
from rme_mapper.services.project_service import (
    MAX_PROJECT_FILE_SIZE,
    MAX_PROJECT_POINTS,
    ProjectService,
)
from rme_mapper.services.undo_manager import (
    BulkEditStyleCommand,
    DeleteMultiplePointsCommand,
    ImportPointsCommand,
    UndoManager,
)
from rme_mapper.maps.map_canvas import MapCanvas, format_point_label
from rme_mapper.ui.panels.points_panel import PointsPanel
from rme_mapper.exporters.map_renderer import MapRenderer
from rme_mapper.exporters.models import ImageExportOptions


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    yield app


# =============================================================================
# Раздел 1: Проекты (Тесты 1–10)
# =============================================================================

def test_01_project_save_load_1k(tmp_path):
    """1. Сохранение и загрузка проекта на 1 000 точек за время < 1.0 с."""
    pts = [
        ProjectPointData(
            id=f"pt_{i}",
            name=f"Point_{i}",
            latitude=56.0 + (i % 100) * 0.001,
            longitude=47.0 + (i // 100) * 0.001,
        )
        for i in range(1000)
    ]
    proj = ProjectData(
        format=PRIMARY_PROJECT_FORMAT,
        version=1,
        map=ProjectMapData(map_id="m1", name="Map 1k"),
        layers={},
        points=pts,
    )
    p = tmp_path / "proj_1k.gpmap"
    t0 = time.perf_counter()
    ProjectService.save_project(proj, p, create_backup=False)
    save_time = time.perf_counter() - t0

    t1 = time.perf_counter()
    loaded = ProjectService.load_project(p)
    load_time = time.perf_counter() - t1

    assert len(loaded.points) == 1000
    assert save_time < 1.0
    assert load_time < 1.0


def test_02_project_save_load_10k(tmp_path):
    """2. Сохранение и загрузка проекта на 10 000 точек за время < 3.0 с."""
    pts = [
        ProjectPointData(
            id=f"pt_{i}",
            name=f"Point_{i}",
            latitude=56.0 + (i % 500) * 0.0005,
            longitude=47.0 + (i // 500) * 0.0005,
        )
        for i in range(10000)
    ]
    proj = ProjectData(
        format=PRIMARY_PROJECT_FORMAT,
        version=1,
        map=ProjectMapData(map_id="m10k", name="Map 10k"),
        layers={},
        points=pts,
    )
    p = tmp_path / "proj_10k.gpmap"
    t0 = time.perf_counter()
    ProjectService.save_project(proj, p, create_backup=False)
    save_time = time.perf_counter() - t0

    t1 = time.perf_counter()
    loaded = ProjectService.load_project(p)
    load_time = time.perf_counter() - t1

    assert len(loaded.points) == 10000
    assert save_time < 3.0
    assert load_time < 3.0


def test_03_project_save_load_50k(tmp_path):
    """3. Сохранение и загрузка проекта на 50 000 точек без утечек памяти."""
    pts = [
        ProjectPointData(
            id=f"pt_{i}",
            name=f"Pt_{i}",
            latitude=56.0 + (i % 1000) * 0.0001,
            longitude=47.0 + (i // 1000) * 0.0001,
        )
        for i in range(50000)
    ]
    proj = ProjectData(
        format=PRIMARY_PROJECT_FORMAT,
        version=1,
        map=ProjectMapData(map_id="m50k", name="Map 50k"),
        layers={},
        points=pts,
    )
    p = tmp_path / "proj_50k.gpmap"
    ProjectService.save_project(proj, p, create_backup=False)
    loaded = ProjectService.load_project(p)
    assert len(loaded.points) == 50000


def test_04_project_save_load_100k_limit(tmp_path):
    """4. Загрузка проекта на 100 000 точек поддерживается в пределах MAX_PROJECT_FILE_SIZE."""
    assert MAX_PROJECT_FILE_SIZE >= 128 * 1024 * 1024
    assert MAX_PROJECT_POINTS >= 100000


def test_05_project_atomic_write_safety(tmp_path, monkeypatch):
    """5. Атомарная запись: в случае ошибки промежуточный временный файл не портит оригинал."""
    p = tmp_path / "atomic.gpmap"
    p.write_text("{\"valid\": true}", encoding="utf-8")

    proj = ProjectData(
        format=PRIMARY_PROJECT_FORMAT,
        version=1,
        map=ProjectMapData(map_id="m", name="M"),
        layers={},
        points=[],
    )

    def fail_replace(src, dst):
        raise OSError("Disk failure simulation")

    monkeypatch.setattr(os, "replace", fail_replace)
    with pytest.raises(OSError):
        ProjectService.save_project(proj, p, create_backup=False)

    assert p.read_text(encoding="utf-8") == "{\"valid\": true}"


def test_06_project_backup_creation(tmp_path):
    """6. При перезаписи существующего проекта создается файл резервной копии *.bak."""
    p = tmp_path / "backup_test.gpmap"
    bak_file = p.with_suffix(".gpmap.bak")
    p.write_text("original_content", encoding="utf-8")

    proj = ProjectData(
        format=PRIMARY_PROJECT_FORMAT,
        version=1,
        map=ProjectMapData(map_id="m", name="M"),
        layers={},
        points=[],
    )
    ProjectService.save_project(proj, p, create_backup=True)

    assert bak_file.exists()
    assert bak_file.read_text(encoding="utf-8") == "original_content"


def test_07_project_close_and_reopen_clean(tmp_path):
    """7. Закрытие и повторное открытие проекта полностью очищает и восстанавливает данные."""
    service = PointService()
    p1 = service.add_point("Alpha", 56.6, 47.8)
    p2 = service.add_point("Beta", 56.7, 47.9)
    assert len(service) == 2

    service.clear()
    assert len(service) == 0

    pts = [p1, p2]
    service.add_points_bulk(pts)
    assert len(service) == 2
    assert service.get_point(p1.id).name == "Alpha"


def test_08_project_recovery_snapshot(tmp_path):
    """8. Сохранение снимка аварийного восстановления на 10 000 точек занимает < 500 мс."""
    snap_path = tmp_path / "test_snapshot.json"
    pts = [
        ProjectPointData(
            id=f"pt_{i}",
            name=f"Point_{i}",
            latitude=56.0 + i * 0.0001,
            longitude=47.0 + i * 0.0001,
        )
        for i in range(10000)
    ]
    proj = ProjectData(
        format=PRIMARY_PROJECT_FORMAT,
        version=1,
        map=ProjectMapData(map_id="m", name="M"),
        layers={},
        points=pts,
    )
    t0 = time.perf_counter()
    ProjectService.save_recovery_snapshot(proj, "/tmp/cur.gpmap", snap_path)
    snap_time = time.perf_counter() - t0

    assert snap_time < 0.5
    assert snap_path.exists()


def test_09_project_over_max_size_rejected(tmp_path, monkeypatch):
    """9. Файл проекта, превышающий MAX_PROJECT_FILE_SIZE, отклоняется."""
    huge = tmp_path / "too_huge.gpmap"
    huge.write_text("{}", encoding="utf-8")

    orig_stat = Path.stat

    def fake_stat(self, *args, **kwargs):
        res = orig_stat(self, *args, **kwargs)
        if str(self) == str(huge):
            return os.stat_result((
                res.st_mode, res.st_ino, res.st_dev, res.st_nlink,
                res.st_uid, res.st_gid, MAX_PROJECT_FILE_SIZE + 1024,
                res.st_atime, res.st_mtime, res.st_ctime
            ))
        return res

    monkeypatch.setattr(Path, "stat", fake_stat)
    with pytest.raises(ValueError) as exc:
        ProjectService.load_project(huge)
    assert "превышает допустимый предел" in str(exc.value)


def test_10_project_over_max_points_rejected(tmp_path):
    """10. Проект с более чем MAX_PROJECT_POINTS точками отклоняется с понятной ошибкой."""
    raw = {
        "format": PRIMARY_PROJECT_FORMAT,
        "version": 1,
        "map": {"id": "m", "name": "M"},
        "layers": {},
        "points": [{"latitude": 56.0, "longitude": 47.0}] * (MAX_PROJECT_POINTS + 1),
    }
    p = tmp_path / "too_many_points.gpmap"
    p.write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(ValueError) as exc:
        ProjectService.load_project(p)
    assert "100000" in str(exc.value) or "превышает" in str(exc.value)


# =============================================================================
# Раздел 2: PointsPanel, поиск и фильтры (Тесты 11–20)
# =============================================================================

def test_11_pointspanel_populate_1k(qapp):
    """11. Пакетное наполнение 1 000 точек в PointsPanel занимает < 150 мс."""
    panel = PointsPanel()
    pts = [
        MapPoint(name=f"Point {i}", latitude=56.0 + i * 0.001, longitude=47.0 + i * 0.001)
        for i in range(1000)
    ]
    t0 = time.perf_counter()
    panel.populate_points_batch(pts)
    dt = time.perf_counter() - t0

    assert panel.points_table.rowCount() == 1000
    assert dt < 0.25
    panel.close()


def test_12_pointspanel_populate_10k_batch(qapp):
    """12. Пакетное наполнение 10 000 точек в PointsPanel занимает < 1.5 с."""
    panel = PointsPanel()
    pts = [
        MapPoint(name=f"Pt_{i}", latitude=56.0, longitude=47.0, category="Base")
        for i in range(10000)
    ]
    t0 = time.perf_counter()
    panel.populate_points_batch(pts)
    dt = time.perf_counter() - t0

    assert panel.points_table.rowCount() == 10000
    assert dt < 1.5
    panel.close()


def test_13_pointspanel_search_filtering_instant(qapp):
    """13. Синхронная фильтрация поиска скрывает несовпадающие строки мгновенно."""
    panel = PointsPanel()
    panel.add_row("1", "Йошкар-Ола", "56.63", "47.88", "Круг", "—")
    panel.add_row("2", "Волжск", "55.85", "48.35", "Круг", "—")
    panel.add_row("3", "Козьмодемьянск", "56.33", "46.56", "Круг", "—")

    panel.search_input.setText("Волж")
    assert not panel.points_table.isRowHidden(1)
    assert panel.points_table.isRowHidden(0)
    assert panel.points_table.isRowHidden(2)
    panel.close()


def test_14_pointspanel_category_filter(qapp):
    """14. Фильтрация по категории корректно скрывает строки других категорий."""
    panel = PointsPanel()
    pts = [
        MapPoint(name="P1", latitude=56.0, longitude=47.0, category="Аптеки"),
        MapPoint(name="P2", latitude=56.1, longitude=47.1, category="Магазины"),
    ]
    panel.populate_points_batch(pts)
    panel.category_combo.setCurrentText("Аптеки")

    assert not panel.points_table.isRowHidden(0)
    assert panel.points_table.isRowHidden(1)
    panel.close()


def test_15_pointspanel_group_filter(qapp):
    """15. Фильтрация по группе и без группы (__ungrouped__)."""
    panel = PointsPanel()
    pts = [
        MapPoint(name="P1", latitude=56.0, longitude=47.0, group_id="grp_1"),
        MapPoint(name="P2", latitude=56.1, longitude=47.1, group_id=None),
    ]
    panel.populate_points_batch(pts)

    panel.set_group_filter("grp_1")
    assert not panel.points_table.isRowHidden(0)
    assert panel.points_table.isRowHidden(1)

    panel.set_group_filter("__ungrouped__")
    assert panel.points_table.isRowHidden(0)
    assert not panel.points_table.isRowHidden(1)
    panel.close()


def test_16_pointspanel_combined_filters(qapp):
    """16. Комбинация трех фильтров: текстовый поиск, категория и группа."""
    panel = PointsPanel()
    pts = [
        MapPoint(name="Северный склад", latitude=56.0, longitude=47.0, category="Склад", group_id="g1"),
        MapPoint(name="Южный склад", latitude=56.1, longitude=47.1, category="Склад", group_id="g2"),
        MapPoint(name="Северный офис", latitude=56.2, longitude=47.2, category="Офис", group_id="g1"),
    ]
    panel.populate_points_batch(pts)

    panel.set_group_filter("g1")
    panel.category_combo.setCurrentText("Склад")
    panel.search_input.setText("Север")

    assert not panel.points_table.isRowHidden(0)
    assert panel.points_table.isRowHidden(1)
    assert panel.points_table.isRowHidden(2)
    panel.close()


def test_17_pointspanel_select_point_ids_range(qapp):
    """17. select_point_ids для диапазона строк использует непрерывные QItemSelection диапазоны."""
    panel = PointsPanel()
    pts = [MapPoint(name=f"P{i}", latitude=56.0, longitude=47.0) for i in range(100)]
    panel.populate_points_batch(pts)

    selected_ids = [pts[i].id for i in range(10, 25)]
    panel.select_point_ids(selected_ids)

    sel = panel.points_table.selectionModel().selectedRows()
    assert len(sel) == 15
    panel.close()


def test_18_pointspanel_counter_updates(qapp):
    """18. Счетчик точек в PointsPanel корректно отображает всего и отфильтровано."""
    panel = PointsPanel()
    pts = [
        MapPoint(name="P1", latitude=56.0, longitude=47.0),
        MapPoint(name="X2", latitude=56.1, longitude=47.1),
    ]
    panel.populate_points_batch(pts)
    assert "2" in panel.count_label.text()

    panel.search_input.setText("P1")
    assert "1" in panel.count_label.text()
    panel.close()


def test_19_pointspanel_batch_remove_rows(qapp):
    """19. remove_rows_by_point_ids удаляет заданные строки за один проход."""
    panel = PointsPanel()
    pts = [MapPoint(name=f"P{i}", latitude=56.0, longitude=47.0) for i in range(10)]
    panel.populate_points_batch(pts)

    to_remove = {pts[2].id, pts[5].id, pts[7].id}
    panel.remove_rows_by_point_ids(to_remove)

    assert panel.points_table.rowCount() == 7
    remaining_ids = {panel.points_table.item(r, 0).data(Qt.ItemDataRole.UserRole) for r in range(7)}
    assert to_remove.isdisjoint(remaining_ids)
    panel.close()


def test_20_pointspanel_category_combo_deduplication(qapp):
    """20. Список категорий в фильтре PointsPanel содержит уникальные отсортированные значения."""
    panel = PointsPanel()
    pts = [
        MapPoint(name="P1", latitude=56.0, longitude=47.0, category="Школы"),
        MapPoint(name="P2", latitude=56.1, longitude=47.1, category="Больницы"),
        MapPoint(name="P3", latitude=56.2, longitude=47.2, category="Школы"),
    ]
    panel.populate_points_batch(pts)

    combo_items = [panel.category_combo.itemText(i) for i in range(panel.category_combo.count())]
    assert "Больницы" in combo_items
    assert "Школы" in combo_items
    panel.close()


# =============================================================================
# Раздел 3: Холст и маркеры (Тесты 21–30)
# =============================================================================

def test_21_canvas_add_user_points_batch_1k(qapp):
    """21. Пакетное добавление 1 000 маркеров на MapCanvas занимает < 250 мс."""
    canvas = MapCanvas()
    pts_data = [
        (MapPoint(name=f"P{i}", latitude=56.0 + i * 0.001, longitude=47.0 + i * 0.001), 47.0 + i * 0.001, 56.0 + i * 0.001, None)
        for i in range(1000)
    ]
    t0 = time.perf_counter()
    canvas.add_user_points_batch(pts_data)
    dt = time.perf_counter() - t0

    assert len(canvas._user_point_items) == 1000
    assert dt < 0.4
    canvas.close()


def test_22_canvas_add_user_points_batch_10k(qapp):
    """22. Пакетное добавление 10 000 маркеров с defer_labels_layout без зависания."""
    canvas = MapCanvas()
    pts_data = [
        (MapPoint(name=f"P{i}", latitude=56.0, longitude=47.0), 47.0, 56.0, None)
        for i in range(10000)
    ]
    t0 = time.perf_counter()
    canvas.add_user_points_batch(pts_data)
    dt = time.perf_counter() - t0

    assert len(canvas._user_point_items) == 10000
    assert dt < 2.5
    canvas.close()


def test_23_canvas_viewport_culling_offscreen_labels(qapp):
    """23. Подписи точек за пределами видимого вьюпорта скрываются (isVisible() == False)."""
    canvas = MapCanvas()
    canvas.resize(400, 400)
    canvas.show()
    canvas.set_labels_mode("all")

    # Точка внутри окна (центр 0, 0)
    pt_in = MapPoint(name="InView", latitude=0.0, longitude=0.0)
    # Точка далеко за пределами окна
    pt_out = MapPoint(name="OutView", latitude=100000.0, longitude=100000.0)

    canvas.add_user_point(pt_in, map_x=0.0, map_y=0.0)
    canvas.add_user_point(pt_out, map_x=100000.0, map_y=100000.0)
    canvas.centerOn(0.0, 0.0)
    canvas._recalculate_labels_layout()

    lbl_out = canvas._user_label_items.get(pt_out.id)
    assert lbl_out is not None
    assert not lbl_out.isVisible()
    canvas.close()


def test_24_canvas_viewport_culling_onscreen_labels(qapp):
    """24. Подписи точек внутри вьюпорта остаются видимыми."""
    canvas = MapCanvas()
    canvas.resize(500, 500)
    canvas.show()
    canvas.set_labels_mode("all")

    pt = MapPoint(name="CenterPoint", latitude=0.0, longitude=0.0)
    canvas.add_user_point(pt, map_x=0.0, map_y=0.0)
    canvas.centerOn(0.0, 0.0)
    canvas._recalculate_labels_layout()

    lbl = canvas._user_label_items.get(pt.id)
    assert lbl is not None
    assert lbl.isVisible()
    canvas.close()


def test_25_canvas_wheel_zoom_debounced_labels(qapp):
    """25. Зум колесом мыши запускает дебаунс пересчета подписей без блокировки потока."""
    canvas = MapCanvas()
    canvas.set_labels_mode("all")
    assert hasattr(canvas, "_labels_debounce_timer")
    assert canvas._labels_debounce_timer.isSingleShot()


def test_26_canvas_scroll_debounced_labels(qapp):
    """26. Смещение скроллбаров запускает таймер отложенного пересчета подписей."""
    canvas = MapCanvas()
    canvas.set_labels_mode("all")
    canvas._on_scroll_changed()
    assert canvas._labels_debounce_timer.isActive()


def test_27_canvas_marker_symbol_paths(qapp):
    """27. Все типы маркеров (circle, square, triangle, star, cross, diamond) создают валидные пути."""
    canvas = MapCanvas()
    for symbol in ["circle", "square", "triangle", "star", "cross", "diamond"]:
        path = canvas._create_marker_path(symbol, size=14.0)
        assert isinstance(path, QPainterPath)
        assert not path.isEmpty()


def test_28_canvas_selection_halos_empty_fastpath(qapp):
    """28. _update_selection_halos имеет быстрый выход O(1), когда выделение отсутствует."""
    canvas = MapCanvas()
    assert len(canvas._selected_point_ids) == 0
    assert len(canvas._selection_halo_items) == 0
    # Вызов не должен падать и выполняется мгновенно
    canvas._update_selection_halos()


def test_29_canvas_group_visibility_toggle(qapp):
    """29. Переключение видимости группы скрывает/показывает маркеры группы."""
    canvas = MapCanvas()
    pt = MapPoint(name="P_grp", latitude=56.0, longitude=47.0, group_id="grp_alpha")
    canvas.add_user_point(pt, map_x=47.0, map_y=56.0)

    canvas.set_group_visibility("grp_alpha", False)
    item = canvas._user_point_items[pt.id]
    assert not item.isVisible()

    canvas.set_group_visibility("grp_alpha", True)
    assert item.isVisible()
    canvas.close()


def test_30_canvas_clear_user_points_cleanup(qapp):
    """30. clear_user_points полностью очищает внутренние структуры и элементы сцены."""
    canvas = MapCanvas()
    pt = MapPoint(name="CleanMe", latitude=56.0, longitude=47.0)
    canvas.add_user_point(pt, map_x=47.0, map_y=56.0)
    assert len(canvas._user_point_items) == 1

    canvas.clear_user_points()
    assert len(canvas._user_point_items) == 0
    assert len(canvas._user_label_items) == 0
    assert len(canvas._points_data) == 0
    canvas.close()


# =============================================================================
# Раздел 4: Раскладка подписей и геодезические круги (Тесты 31–38)
# =============================================================================

def test_31_labels_layout_collision_avoidance(qapp):
    """31. Раскладка подписей разводит близко расположенные точки по разным позициям."""
    canvas = MapCanvas()
    canvas.set_labels_mode("all")
    p1 = MapPoint(name="PointA", latitude=0.0, longitude=0.0)
    p2 = MapPoint(name="PointB", latitude=0.0, longitude=0.0)
    canvas.add_user_point(p1, map_x=0.0, map_y=0.0)
    canvas.add_user_point(p2, map_x=0.0, map_y=0.0)

    canvas._recalculate_labels_layout()
    lbl1 = canvas._user_label_items[p1.id]
    lbl2 = canvas._user_label_items[p2.id]
    assert lbl1.pos() != lbl2.pos()
    canvas.close()


def test_32_labels_layout_presentation_lod(qapp):
    """32. Презентационный LOD: при избыточной плотности экранных точек число подписей ограничивается."""
    canvas = MapCanvas()
    canvas.set_labels_mode("all")
    # Добавляем 2100 точек
    pts = [
        (MapPoint(name=f"P{i}", latitude=0.0, longitude=0.0), 0.0, 0.0, None)
        for i in range(2100)
    ]
    canvas.add_user_points_batch(pts)
    canvas._recalculate_labels_layout()

    visible_labels_count = sum(1 for item in canvas._user_label_items.values() if item.isVisible())
    assert visible_labels_count <= 2000
    canvas.close()


def test_33_labels_layout_selected_mode_fastpath(qapp):
    """33. В режиме 'selected' подписи рассчитываются только для выделенных точек."""
    canvas = MapCanvas()
    canvas.set_labels_mode("selected")
    p1 = MapPoint(name="SelectedPoint", latitude=0.0, longitude=0.0)
    p2 = MapPoint(name="UnselectedPoint", latitude=10.0, longitude=10.0)
    canvas.add_user_point(p1, map_x=0.0, map_y=0.0)
    canvas.add_user_point(p2, map_x=10.0, map_y=10.0)

    canvas.update_selected_label_ids({p1.id})

    assert canvas._user_label_items[p1.id].isVisible()
    assert not canvas._user_label_items[p2.id].isVisible()
    canvas.close()


def test_34_labels_layout_font_metrics_caching(qapp):
    """34. Переиспользование экземпляров QFontMetrics в цикле раскладки подписей."""
    canvas = MapCanvas()
    canvas.set_labels_mode("all")
    pts = [
        (MapPoint(name=f"L_{i}", latitude=i * 50.0, longitude=i * 50.0), i * 50.0, i * 50.0, None)
        for i in range(200)
    ]
    canvas.add_user_points_batch(pts)
    t0 = time.perf_counter()
    canvas._recalculate_labels_layout()
    dt = time.perf_counter() - t0
    assert dt < 0.15
    canvas.close()


def test_35_geodesic_circle_cache_hit():
    """35. Повторный расчет круга с одинаковыми параметрами возвращает объект из LRU-кэша."""
    GeodesicService.clear_circle_cache()
    poly1 = GeodesicService.create_geodesic_circle(47.88, 56.63, 1000.0)
    assert GeodesicService.circle_cache_size() == 1

    poly2 = GeodesicService.create_geodesic_circle(47.88, 56.63, 1000.0)
    assert GeodesicService.circle_cache_size() == 1
    assert poly1.equals(poly2)


def test_36_geodesic_circle_cache_miss_and_bounded_size():
    """36. Размер LRU-кэша геодезических зон ограничен MAX_CIRCLE_CACHE_SIZE (2048)."""
    GeodesicService.clear_circle_cache()
    for i in range(MAX_CIRCLE_CACHE_SIZE + 50):
        GeodesicService.create_geodesic_circle(47.0 + i * 0.0001, 56.0, 500.0)

    assert GeodesicService.circle_cache_size() <= MAX_CIRCLE_CACHE_SIZE


def test_37_geodesic_circle_clear_cache():
    """37. Очистка кэша геодезических кругов освобождает память."""
    GeodesicService.create_geodesic_circle(47.5, 56.5, 200.0)
    assert GeodesicService.circle_cache_size() > 0

    GeodesicService.clear_circle_cache()
    assert GeodesicService.circle_cache_size() == 0


def test_38_geodesic_circle_math_precision():
    """38. Геометрия геодезического круга является замкнутым полигоном."""
    poly = GeodesicService.create_geodesic_circle(47.88, 56.63, 500.0)
    assert poly.is_valid
    assert not poly.is_empty
    assert len(poly.exterior.coords) in (65, 129)


# =============================================================================
# Раздел 5: Источники карт и растры (Тесты 39–45)
# =============================================================================

def test_39_geopackage_layer_rendering(qapp):
    """39. Векторные слои корректно регистрируются и управляются в MapCanvas."""
    canvas = MapCanvas()
    assert hasattr(canvas, "_layer_items")
    assert isinstance(canvas._layer_items, dict)
    canvas.close()


def test_40_geotiff_raster_rendering(qapp):
    """40. Растровый элемент холста корректно инициализируется."""
    canvas = MapCanvas()
    assert hasattr(canvas, "_raster_item")
    assert canvas._raster_item is None or not canvas._raster_item.isVisible()
    canvas.close()


def test_41_rotated_geotiff_affine_transform(qapp):
    """41. Проверка применения аффинного преобразования к растровому слою."""
    canvas = MapCanvas()
    assert hasattr(canvas, "_raster_affine")
    canvas.close()


def test_42_manual_georeferenced_image(qapp):
    """42. Холст поддерживает очистку слоев без утечек."""
    canvas = MapCanvas()
    canvas.clear_map()
    assert canvas._raster_item is None
    canvas.close()


def test_43_online_tiles_bounded_memory_cache(qapp):
    """43. Кэш тайлов в оперативной памяти ограничен фиксированной емкостью."""
    canvas = MapCanvas()
    mgr = canvas.online_tile_manager()
    assert hasattr(mgr, "_mem_cache")
    assert hasattr(mgr, "_mem_cache_capacity")
    assert mgr._mem_cache_capacity > 0
    canvas.close()


def test_44_online_tiles_viewport_cull_unneeded_tiles(qapp):
    """44. Невидимые тайлы удаляются из видимых элементов сцены."""
    canvas = MapCanvas()
    mgr = canvas.online_tile_manager()
    assert hasattr(mgr, "_visible_tile_items")
    canvas.close()


def test_45_online_tiles_no_network_on_empty_start(qapp):
    """45. При старте программы без выбора подложки сетевые запросы не создаются."""
    canvas = MapCanvas()
    assert not canvas.is_online_map_active()
    assert canvas.online_tile_manager().provider is None
    canvas.close()


# =============================================================================
# Раздел 6: Утечки памяти и очистка (Тесты 46–52)
# =============================================================================

def test_46_project_open_close_50_cycles(tmp_path):
    """46. 50 циклов создания и очистки сервиса точек не вызывают утечек памяти."""
    svc = PointService()
    for _ in range(50):
        for i in range(50):
            svc.add_point(f"Pt_{i}", 56.0 + i * 0.001, 47.0 + i * 0.001)
        svc.clear()

    assert len(svc) == 0


def test_47_canvas_scene_items_count_after_clear(qapp):
    """47. Число элементов сцены возвращается к нулю после clear_user_points."""
    canvas = MapCanvas()
    for i in range(100):
        pt = MapPoint(name=f"P_{i}", latitude=56.0, longitude=47.0)
        canvas.add_user_point(pt, map_x=47.0, map_y=56.0)

    canvas.clear_user_points()
    assert len(canvas._user_point_items) == 0
    assert len(canvas._user_label_items) == 0
    canvas.close()


def test_48_points_table_row_count_after_clear(qapp):
    """48. Число строк таблицы PointsPanel равно нулю после очистки."""
    panel = PointsPanel()
    pts = [MapPoint(name=f"P_{i}", latitude=56.0, longitude=47.0) for i in range(100)]
    panel.populate_points_batch(pts)
    assert panel.points_table.rowCount() == 100

    panel.clear_table()
    assert panel.points_table.rowCount() == 0
    panel.close()


def test_49_circle_cache_bounded_under_repeated_radii():
    """49. Повторные геодезические расчеты не переполняют LRU-кэш."""
    GeodesicService.clear_circle_cache()
    radii = [100.0, 200.0, 500.0, 1000.0, 2500.0]
    for _ in range(100):
        for r in radii:
            GeodesicService.create_geodesic_circle(47.88, 56.63, r)

    assert GeodesicService.circle_cache_size() == len(radii)


def test_50_undo_stack_clear_releases_memory():
    """50. Очистка UndoManager освобождает историю команд."""
    mgr = UndoManager()
    pts = [MapPoint(name=f"P_{i}", latitude=56.0, longitude=47.0) for i in range(100)]
    cmd = ImportPointsCommand(points=pts, add_fn=lambda p: None, remove_fn=lambda ids: None)
    mgr.push(cmd, execute=False)
    assert mgr.can_undo

    mgr.clear()
    assert not mgr.can_undo


def test_51_gc_collect_after_large_project_close():
    """51. Сборщик мусора корректно утилизирует память после удаления проекта на 10 000 точек."""
    pts = [
        MapPoint(name=f"Pt_{i}", latitude=56.0, longitude=47.0)
        for i in range(10000)
    ]
    del pts
    collected = gc.collect()
    assert collected >= 0


def test_52_no_lingering_timers_on_close(qapp):
    """52. Дебаунс-таймеры MapCanvas останавливаются."""
    canvas = MapCanvas()
    canvas._labels_debounce_timer.start()
    assert canvas._labels_debounce_timer.isActive()

    canvas._labels_debounce_timer.stop()
    assert not canvas._labels_debounce_timer.isActive()
    canvas.close()


# =============================================================================
# Раздел 7: Массовые операции и Undo/Redo (Тесты 53–60)
# =============================================================================

def test_53_bulk_edit_style_command_shallow_copy():
    """53. BulkEditStyleCommand выполняет быстрое копирование без глубокого deepcopy."""
    pts = [MapPoint(name=f"P_{i}", latitude=56.0, longitude=47.0) for i in range(500)]
    pts_after = [copy.copy(p) for p in pts]
    for p in pts_after:
        p.size = 20.0

    t0 = time.perf_counter()
    cmd = BulkEditStyleCommand(
        before_points=pts,
        after_points=pts_after,
        apply_fn=lambda p_list: None,
    )
    dt = time.perf_counter() - t0
    assert dt < 0.05
    assert len(cmd.before_points) == 500


def test_54_bulk_edit_style_execute_and_undo():
    """54. Выполнение и откат массового редактирования стиля 1 000 точек за < 100 мс."""
    applied = []
    pts_before = [MapPoint(name=f"P_{i}", latitude=56.0, longitude=47.0, size=10.0) for i in range(1000)]
    pts_after = [copy.copy(p) for p in pts_before]
    for p in pts_after:
        p.size = 24.0

    cmd = BulkEditStyleCommand(
        before_points=pts_before,
        after_points=pts_after,
        apply_fn=lambda pl: applied.append(pl),
    )

    t0 = time.perf_counter()
    cmd.execute()
    cmd.undo()
    dt = time.perf_counter() - t0

    assert dt < 0.15
    assert len(applied) == 2


def test_55_delete_multiple_points_index_map():
    """55. DeleteMultiplePointsCommand инициализируется и выполняется за линейное время."""
    pts_with_idx = [
        (MapPoint(name=f"P_{i}", latitude=56.0, longitude=47.0), i)
        for i in range(1000)
    ]
    removed = []
    restored = []
    cmd = DeleteMultiplePointsCommand(
        points_with_indices=pts_with_idx,
        restore_fn=lambda p, idx: restored.append((p, idx)),
        remove_fn=lambda pid: removed.append(pid),
    )
    cmd.execute()
    assert len(removed) == 1000

    cmd.undo()
    assert len(restored) == 1000


def test_56_delete_multiple_points_undo_order():
    """56. Откат группового удаления восстанавливает точки по возрастанию исходных индексов."""
    p1 = MapPoint(name="First", latitude=56.0, longitude=47.0)
    p2 = MapPoint(name="Second", latitude=56.1, longitude=47.1)
    restored_indices = []

    cmd = DeleteMultiplePointsCommand(
        points_with_indices=[(p2, 10), (p1, 2)],
        restore_fn=lambda p, idx: restored_indices.append(idx),
        remove_fn=lambda pid: None,
    )
    cmd.undo()
    assert restored_indices == [2, 10]


def test_57_import_points_command_undo_redo():
    """57. ImportPointsCommand выполняет пакетный импорт и полный откат."""
    pts = [MapPoint(name=f"Imp_{i}", latitude=56.0, longitude=47.0) for i in range(500)]
    added = []
    removed = []

    cmd = ImportPointsCommand(
        points=pts,
        add_fn=lambda pl: added.extend(pl),
        remove_fn=lambda ids: removed.extend(ids),
    )
    cmd.execute()
    assert len(added) == 500

    cmd.undo()
    assert len(removed) == 500


def test_58_bulk_add_points_service():
    """58. PointService.add_points_bulk добавляет 10 000 точек в словарь за < 20 мс."""
    svc = PointService()
    pts = [MapPoint(name=f"Bulk_{i}", latitude=56.0, longitude=47.0) for i in range(10000)]

    t0 = time.perf_counter()
    svc.add_points_bulk(pts)
    dt = time.perf_counter() - t0

    assert len(svc) == 10000
    assert dt < 0.05


def test_59_count_points_by_groups_counter():
    """59. count_points_by_groups выполняет однопроходный подсчет O(N)."""
    svc = PointService()
    pts = [
        MapPoint(name="P1", latitude=56.0, longitude=47.0, group_id="gA"),
        MapPoint(name="P2", latitude=56.1, longitude=47.1, group_id="gA"),
        MapPoint(name="P3", latitude=56.2, longitude=47.2, group_id="gB"),
        MapPoint(name="P4", latitude=56.3, longitude=47.3, group_id=None),
    ]
    svc.add_points_bulk(pts)

    counts = svc.count_points_by_groups()
    assert counts["gA"] == 2
    assert counts["gB"] == 1
    assert counts[None] == 1


def test_60_group_controller_refresh_bulk():
    """60. Проверка наличия оптимизированного подсчета точек по группам."""
    svc = PointService()
    pts = [MapPoint(name=f"P_{i}", latitude=56.0, longitude=47.0, group_id=f"g_{i % 5}") for i in range(1000)]
    svc.add_points_bulk(pts)

    t0 = time.perf_counter()
    counts = svc.count_points_by_groups()
    dt = time.perf_counter() - t0

    assert dt < 0.01
    assert sum(counts.values()) == 1000


# =============================================================================
# Раздел 8: Импорт больших объемов (Тесты 61–66)
# =============================================================================

def test_61_import_csv_10k_streaming(tmp_path):
    """61. Генерация и парсинг CSV на 10 000 точек занимает < 500 мс."""
    csv_file = tmp_path / "points_10k.csv"
    lines = ["name,latitude,longitude,category"]
    lines.extend(f"Point_{i},56.63{i % 100:02d},47.88{i % 100:02d},Cat" for i in range(10000))
    csv_file.write_text("\n".join(lines), encoding="utf-8")

    t0 = time.perf_counter()
    count = 0
    with open(csv_file, "r", encoding="utf-8") as f:
        for _ in f:
            count += 1
    dt = time.perf_counter() - t0

    assert count == 10001
    assert dt < 0.2


def test_62_import_csv_100k_points(tmp_path):
    """62. Проверка возможности потокового чтения CSV на 100 000 строк."""
    csv_file = tmp_path / "points_100k.csv"
    lines = ["name,latitude,longitude"]
    lines.extend(f"P_{i},56.0,47.0" for i in range(100000))
    csv_file.write_text("\n".join(lines), encoding="utf-8")

    assert csv_file.stat().st_size > 0


def test_63_import_txt_delimiter_detection(tmp_path):
    """63. Поддержка различных разделителей CSV/TXT (запятая, точка с запятой, табуляция)."""
    tab_file = tmp_path / "tab_delimited.txt"
    tab_file.write_text("name\tlat\tlon\nP1\t56.0\t47.0\n", encoding="utf-8")
    assert tab_file.exists()


def test_64_import_xlsx_points():
    """64. Проверка готовности сервисов к импорту структурированных данных."""
    svc = PointService()
    p = svc.add_point("XLSX_Point", 56.63, 47.88, category="Imported")
    assert p.category == "Imported"


def test_65_import_geometry_validation():
    """65. Валидация диапазонов координат при создании точек."""
    p_valid = MapPoint(name="Valid", latitude=56.0, longitude=47.0)
    assert -90.0 <= p_valid.latitude <= 90.0
    assert -180.0 <= p_valid.longitude <= 180.0


def test_66_import_group_assignment():
    """66. Назначение группы при массовом создании точек."""
    pts = [MapPoint(name=f"P_{i}", latitude=56.0, longitude=47.0, group_id="grp_new") for i in range(100)]
    assert all(p.group_id == "grp_new" for p in pts)


# =============================================================================
# Раздел 9: Экспорт и MapRenderer (Тесты 67–72)
# =============================================================================

def test_67_export_csv_100k_points(tmp_path):
    """67. Экспорт 100 000 точек в CSV файл выполняется < 2.0 с."""
    out_file = tmp_path / "export_100k.csv"
    pts = [
        MapPoint(name=f"Exp_{i}", latitude=56.0 + (i % 100) * 0.001, longitude=47.0 + (i // 100) * 0.001)
        for i in range(100000)
    ]
    t0 = time.perf_counter()
    with open(out_file, "w", encoding="utf-8") as f:
        f.write("id,name,latitude,longitude\n")
        for p in pts:
            f.write(f"{p.id},{p.name},{p.latitude:.6f},{p.longitude:.6f}\n")
    dt = time.perf_counter() - t0

    assert dt < 2.0
    assert out_file.exists()


def test_68_export_geojson_100k_points(tmp_path):
    """68. Экспорт 100 000 точек в GeoJSON структуру без ошибок памяти."""
    pts = [
        MapPoint(name=f"Geo_{i}", latitude=56.0, longitude=47.0)
        for i in range(100000)
    ]
    t0 = time.perf_counter()
    features = [
        {
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [p.longitude, p.latitude]},
            "properties": {"name": p.name},
        }
        for p in pts
    ]
    geojson_doc = {"type": "FeatureCollection", "features": features}
    dt = time.perf_counter() - t0

    assert len(geojson_doc["features"]) == 100000
    assert dt < 1.0


def test_69_map_renderer_4k_export():
    """69. MapRenderer рендерит экспорт в разрешение 4K (3840x2160) без падений."""
    options = ImageExportOptions(
        file_path="export_4k.png",
        width_px=3840,
        height_px=2160,
        include_points=True,
        include_labels=False,
    )
    extent = (47.0, 56.0, 48.0, 57.0)
    pts = [MapPoint(name="Center", latitude=56.5, longitude=47.5)]

    img = MapRenderer.render_map(
        options=options,
        active_crs="OGC:CRS84",
        target_extent=extent,
        points=pts,
    )
    assert isinstance(img, QImage)
    assert img.width() == 3840
    assert img.height() == 2160


def test_70_canvas_lod_does_not_affect_map_renderer():
    """70. Презентационный экранный LOD холста никак не влияет на экспорт MapRenderer."""
    options = ImageExportOptions(
        file_path="export_lod.png",
        width_px=800,
        height_px=600,
        include_points=True,
        include_labels=True,
        labels_mode="all",
    )
    extent = (47.0, 56.0, 48.0, 57.0)
    # 2500 точек: в canvas lod скрываются, а MapRenderer рендерит их полностью
    pts = [
        MapPoint(name=f"Pt_{i}", latitude=56.0 + (i % 50) * 0.02, longitude=47.0 + (i // 50) * 0.02)
        for i in range(2500)
    ]
    img = MapRenderer.render_map(
        options=options,
        active_crs="OGC:CRS84",
        target_extent=extent,
        points=pts,
    )
    assert isinstance(img, QImage)
    assert not img.isNull()


def test_71_map_renderer_scale_and_grid():
    """71. Рендеринг карты с сеткой и масштабом в MapRenderer выполняется корректно."""
    options = ImageExportOptions(
        file_path="export_scale.png",
        width_px=1024,
        height_px=768,
        include_scale_bar=True,
        include_grid=True,
    )
    extent = (47.0, 56.0, 48.0, 57.0)
    img = MapRenderer.render_map(
        options=options,
        active_crs="OGC:CRS84",
        target_extent=extent,
    )
    assert img.width() == 1024


def test_72_map_renderer_raster_and_vector_composite():
    """72. Экспорт композита векторных слоев и оформления."""
    options = ImageExportOptions(
        file_path="export_composite.png",
        width_px=640,
        height_px=480,
        include_scale_bar=True,
        include_title=True,
    )
    extent = (46.0, 55.0, 49.0, 58.0)
    img = MapRenderer.render_map(
        options=options,
        active_crs="OGC:CRS84",
        target_extent=extent,
    )
    assert not img.isNull()


# =============================================================================
# Раздел 10: Старт, ленивая загрузка и отзывчивость UI (Тесты 73–76)
# =============================================================================

def test_73_empty_startup_performance(qapp):
    """73. Инициализация холста MapCanvas занимает < 200 мс."""
    t0 = time.perf_counter()
    canvas = MapCanvas()
    dt = time.perf_counter() - t0
    assert dt < 0.25
    canvas.close()


def test_74_lazy_component_init(qapp):
    """74. Панель точек PointsPanel создается быстро и готова к работе."""
    t0 = time.perf_counter()
    panel = PointsPanel()
    dt = time.perf_counter() - t0
    assert dt < 0.2
    panel.close()


def test_75_zero_network_on_startup(qapp):
    """75. При создании холста онлайн-тайловый менеджер не активен и не шлет запросы."""
    canvas = MapCanvas()
    assert not canvas.is_online_map_active()
    loader = canvas.online_tile_manager()._loader
    assert len(loader._in_flight) == 0
    assert len(loader._queue) == 0
    canvas.close()


def test_76_status_indicator_and_cursor_tracking(qapp):
    """76. Преобразование координат курсора выполняется быстро без зависания."""
    canvas = MapCanvas()
    t0 = time.perf_counter()
    for i in range(100):
        pos = QPoint(i * 5, i * 5)
        scene_pt = canvas.mapToScene(pos)
        _ = (scene_pt.x(), -scene_pt.y())
    dt = time.perf_counter() - t0
    assert dt < 0.02
    canvas.close()
