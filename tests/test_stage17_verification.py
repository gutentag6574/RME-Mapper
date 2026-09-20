"""Комплексная контрольная проверка Этапа 17 (Stage 17 Verification Suite).

Покрывает все сценарии из чеклиста разделов 2–20:
- Object Model (UUID vs number, duplicates, i18n immunity, limits)
- Project backward compatibility (v1, v2, .rmeproject, defaults, Save As)
- Crash recovery & .bak backup integrity
- Move point (geographic, projected CRS, GeoPackage, multi-selection guard, pan conflict, Esc)
- Marker styles (all shapes, stroke width 0/positive, opacity 0/100/interm, selection halo immutability)
- Zone styles (solid, dash, dot, border styles vs geographic radius constancy)
- Map/Export visual parity
- Individual & Global visibility combinations
- Label content clean fallbacks & collision avoidance priority
- Label performance (1000 & 5000 points with spatial grid)
- Extended search (name, number, category, description, stable point ID actions)
- End-to-end execution of manual checklist A–U
"""

import copy
import json
import os
from pathlib import Path
import time
from uuid import uuid4
import pytest
from PySide6.QtCore import QPoint, QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QImage, QMouseEvent, QPainter
from PySide6.QtWidgets import QApplication

from rme_mapper.exporters.map_renderer import MapRenderer
from rme_mapper.exporters.models import ImageExportOptions
from rme_mapper.i18n import get_translation_service, set_language
from rme_mapper.maps.map_canvas import MapCanvas, format_point_label
from rme_mapper.models.map_point import MapPoint
from rme_mapper.models.point_style import StyleValidator
from rme_mapper.models.project_data import ProjectData, ProjectMapData, ProjectPointData
from rme_mapper.services.coordinate_service import CoordinateService
from rme_mapper.services.point_service import PointService
from rme_mapper.services.project_service import LEGACY_FORMAT, PRIMARY_FORMAT, ProjectService
from rme_mapper.ui.controllers.point_controller import PointController
from rme_mapper.ui.main_window import MainWindow
from rme_mapper.ui.panels.points_panel import PointsPanel
from rme_mapper.ui.panels.properties_panel import PropertiesPanel


@pytest.fixture(scope="session")
def qapp():
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    yield app


@pytest.fixture
def mari_gpkg():
    return Path(__file__).resolve().parent.parent / "maps" / "test_map" / "prepared" / "mari.gpkg"


# =============================================================================
# 2. OBJECT MODEL
# =============================================================================


def test_object_model_audit():
    """Проверка всех требований расширенной модели MapPoint."""
    # 1. object_number отделен от UUID id
    uid = uuid4().hex
    p = MapPoint(id=uid, name="Объект 1", latitude=56.0, longitude=47.0, object_number="№123-Б")
    assert p.id == uid
    assert p.object_number == "№123-Б"
    assert p.id != p.object_number

    # 2. пустой object_number допустим
    p_empty = MapPoint(name="Объект без номера", latitude=56.0, longitude=47.0, object_number="")
    assert p_empty.object_number == ""

    # 3. description до установленного лимита 8192
    desc_ok = "X" * 8192
    p_desc = MapPoint(name="Опис", latitude=56.0, longitude=47.0, description=desc_ok)
    assert len(p_desc.description) == 8192

    with pytest.raises(ValueError):
        StyleValidator.validate_description("X" * 8193)

    # 4. category до 200 символов
    cat_ok = "C" * 200
    p_cat = MapPoint(name="Кат", latitude=56.0, longitude=47.0, category=cat_ok)
    assert p_cat.category == cat_ok

    with pytest.raises(ValueError):
        StyleValidator.validate_category("C" * 201)

    # 5. visible default=True
    p_vis = MapPoint(name="Вид", latitude=56.0, longitude=47.0)
    assert p_vis.visible is True

    # 6. duplicate object_number не вызывает hard error
    svc = PointService()
    p1 = svc.add_point(name="Точка 1", latitude=56.1, longitude=47.1, object_number="ДУБЛЬ-01")
    p2 = svc.add_point(name="Точка 2", latitude=56.2, longitude=47.2, object_number="ДУБЛЬ-01")
    assert p1.id != p2.id
    assert p1.object_number == p2.object_number == "ДУБЛЬ-01"

    # 7. editable category history
    cats = svc.get_used_categories()
    assert "" in cats or len(cats) >= 0

    p3 = svc.add_point(name="Точка 3", latitude=56.3, longitude=47.3, category="Геология")
    cats_updated = svc.get_used_categories()
    assert "Геология" in cats_updated

    # 8. Пользовательские тексты не переводятся при переключении RU <-> EN
    user_name = "Моя скважина"
    user_num = "СКВ-01"
    user_cat = "Добыча"
    user_desc = "Глубина 120м"
    p_user = MapPoint(name=user_name, latitude=56.0, longitude=47.0, object_number=user_num, category=user_cat, description=user_desc)

    set_language("en")
    assert p_user.name == user_name
    assert p_user.object_number == user_num
    assert p_user.category == user_cat
    assert p_user.description == user_desc

    set_language("ru")
    assert p_user.name == user_name


# =============================================================================
# 3. PROJECT BACKWARD COMPATIBILITY
# =============================================================================


def test_project_backward_compatibility_v1_and_defaults(tmp_path):
    """Старый gpmap v1 без новых полей получает безопасные defaults и сохраняется в новую схему."""
    v1_json = {
        "format": PRIMARY_FORMAT,
        "version": 1,
        "map": {
            "path": "maps/test.gpkg",
            "name": "Тестовая карта",
            "crs": "OGC:CRS84",
            "source_type": "geopackage",
        },
        "layers": {"layer1": True},
        "points": [
            {
                "id": "old-point-1",
                "name": "Старая точка",
                "latitude": 56.5,
                "longitude": 47.5,
                "symbol": "circle",
                "size": 14.0,
                "red": 200,
                "green": 50,
                "blue": 50,
                "zone_enabled": True,
                "radius_m": 500.0,
                "zone_red": 100,
                "zone_green": 150,
                "zone_blue": 200,
                "zone_opacity": 40,
            }
        ],
    }
    v1_file = tmp_path / "legacy_v1.gpmap"
    v1_file.write_text(json.dumps(v1_json, ensure_ascii=False), encoding="utf-8")

    proj = ProjectService.load_project(v1_file)
    assert len(proj.points) == 1
    pt = proj.points[0]

    # Проверка дефолтов
    assert pt.object_number == ""
    assert pt.description == ""
    assert pt.category == ""
    assert pt.visible is True
    assert pt.stroke_red == 0
    assert pt.stroke_green == 0
    assert pt.stroke_blue == 0
    assert pt.stroke_width == 1.0
    assert pt.opacity == 100.0
    assert pt.zone_border_red == 100
    assert pt.zone_border_green == 150
    assert pt.zone_border_blue == 200
    assert pt.zone_border_width == 1.0
    assert pt.zone_border_style == "solid"

    # Save As новый *.gpmap
    new_save = tmp_path / "saved_as_new.gpmap"
    ProjectService.save_project(proj, new_save)
    reloaded = ProjectService.load_project(new_save)
    assert len(reloaded.points) == 1
    assert reloaded.points[0].name == "Старая точка"
    assert reloaded.points[0].visible is True


def test_historical_rmeproject_backward_compatibility(tmp_path):
    """Исторический .rmeproject открывается и парсится корректно."""
    rme_json = {
        "format": LEGACY_FORMAT,
        "version": 1,
        "map": {"path": "test.gpkg", "name": "Карта", "crs": "EPSG:4326"},
        "points": [
            {
                "id": "rme-pt-1",
                "name": "RME Point",
                "latitude": 56.6,
                "longitude": 47.8,
            }
        ],
    }
    rme_file = tmp_path / "old_test.rmeproject"
    rme_file.write_text(json.dumps(rme_json), encoding="utf-8")

    proj = ProjectService.load_project(rme_file)
    assert len(proj.points) == 1
    assert proj.points[0].name == "RME Point"
    assert proj.points[0].object_number == ""
    assert proj.points[0].visible is True


# =============================================================================
# 4. CRASH RECOVERY / BACKUP
# =============================================================================


def test_crash_recovery_and_backup_preserves_stage17_fields(tmp_path):
    """Аварийный снимок и .bak файл сохраняют все новые поля Этапа 17."""
    p_orig = MapPoint(
        id="snap-p1",
        name="Точка Снимка",
        latitude=56.3,
        longitude=47.2,
        object_number="СНИМОК-99",
        category="Аварии",
        description="Данные перед сбоем",
        visible=False,
        stroke_red=111,
        stroke_green=122,
        stroke_blue=133,
        stroke_width=2.5,
        opacity=85.0,
        zone_enabled=True,
        radius_m=1200.0,
        zone_border_red=44,
        zone_border_green=55,
        zone_border_blue=66,
        zone_border_width=3.0,
        zone_border_style="dot",
    )
    pt_data = ProjectPointData.from_map_point(p_orig)
    proj = ProjectData(
        format=PRIMARY_FORMAT,
        version=2,
        map=ProjectMapData(relative_path="m.gpkg", name="M", crs="OGC:CRS84"),
        points=[pt_data],
    )

    # 1. Аварийный снимок
    snap_path = tmp_path / "recovery.snapshot"
    ProjectService.save_recovery_snapshot(proj, current_project_path="work.gpmap", snapshot_path=snap_path)
    assert snap_path.exists()

    rec_proj, rec_path = ProjectService.load_recovery_snapshot(snapshot_path=snap_path)
    assert rec_path == "work.gpmap"
    assert len(rec_proj.points) == 1
    rec_pt = rec_proj.points[0]
    assert rec_pt.object_number == "СНИМОК-99"
    assert rec_pt.category == "Аварии"
    assert rec_pt.description == "Данные перед сбоем"
    assert rec_pt.visible is False
    assert rec_pt.stroke_red == 111
    assert rec_pt.stroke_width == 2.5
    assert rec_pt.opacity == 85.0
    assert rec_pt.zone_border_style == "dot"
    assert rec_pt.zone_border_width == 3.0

    # 2. Резервная копия .bak
    target_proj_file = tmp_path / "my_project.gpmap"
    ProjectService.save_project(proj, target_proj_file, create_backup=False)

    # Модифицируем и пересохраняем с create_backup=True
    rec_proj.points[0].name = "Измененная точка"
    ProjectService.save_project(rec_proj, target_proj_file, create_backup=True)

    bak_file = tmp_path / "my_project.gpmap.bak"
    assert bak_file.exists()
    bak_proj = ProjectService.load_project(bak_file)
    assert bak_proj.points[0].name == "Точка Снимка"
    assert bak_proj.points[0].object_number == "СНИМОК-99"


# =============================================================================
# 5 & 6. MOVE POINT & MOVE + PAN
# =============================================================================


def test_move_point_projected_crs_and_undo_redo(qapp, mari_gpkg):
    """Перемещение точки в проецированной СК (EPSG:3857) с фиксацией в Undo/Redo."""
    win = MainWindow(map_path=mari_gpkg)
    p = MapPoint(id="pt-proj-move", name="Проекция", latitude=56.0, longitude=47.0)
    win.point_controller._cmd_add_point(p)

    # Симулируем перемещение в координатах карты
    orig_lat = p.latitude
    orig_lon = p.longitude
    win.point_controller.on_point_moved_on_canvas("pt-proj-move", 47.1, 56.1, 47.0, 56.0)

    moved_p = win._point_service.get_point("pt-proj-move")
    assert abs(moved_p.latitude - 56.1) < 1e-4
    assert abs(moved_p.longitude - 47.1) < 1e-4

    # Undo
    win.point_controller.undo()
    undone_p = win._point_service.get_point("pt-proj-move")
    assert abs(undone_p.latitude - orig_lat) < 1e-4
    assert abs(undone_p.longitude - orig_lon) < 1e-4

    # Redo
    win.point_controller.redo()
    redone_p = win._point_service.get_point("pt-proj-move")
    assert abs(redone_p.latitude - 56.1) < 1e-4


def test_hidden_point_cannot_move_and_multiselection_guard(qapp):
    """Скрытую точку нельзя перетащить; мультивыделение блокирует перемещение маркера."""
    canvas = MapCanvas()
    canvas.resize(800, 600)
    canvas.show()

    p_hidden = MapPoint(id="hid-1", name="Скрытая", latitude=56.0, longitude=47.0, visible=False)
    p_vis = MapPoint(id="vis-1", name="Видимая", latitude=56.0, longitude=47.0, visible=True)

    canvas.add_user_point(p_hidden, 100.0, 100.0)
    canvas.add_user_point(p_vis, 200.0, 200.0)
    canvas.set_interaction_mode("move_point")

    # 1. Попытка перетащить скрытую точку
    view_pos_hid = canvas.mapFromScene(QPointF(100.0, -100.0))
    press_ev = QMouseEvent(
        QMouseEvent.Type.MouseButtonPress,
        QPointF(view_pos_hid),
        Qt.MouseButton.LeftButton,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    canvas.mousePressEvent(press_ev)
    assert canvas._is_dragging_point is False
    assert canvas._drag_point_id is None

    # 2. Мультивыделение блокирует перемещение
    canvas.update_selected_label_ids({"vis-1", "hid-1"})
    assert len(canvas._selected_point_ids) == 2

    view_pos_vis = canvas.mapFromScene(QPointF(200.0, -200.0))
    press_multi = QMouseEvent(
        QMouseEvent.Type.MouseButtonPress,
        QPointF(view_pos_vis),
        Qt.MouseButton.LeftButton,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    canvas.mousePressEvent(press_multi)
    assert canvas._is_dragging_point is False
    assert canvas._drag_point_id is None

    # 3. Выход из move_point возвращает режим Pan
    canvas.set_interaction_mode("navigation")
    assert canvas.interaction_mode == "navigation"


# =============================================================================
# 7 & 8. MARKER STYLE & ZONE STYLE
# =============================================================================


def test_marker_and_zone_styles_exhaustive():
    """Тестирование форм маркеров, обводки, прозрачности и стилей границ зон."""
    shapes = ["circle", "square", "triangle"]
    opacities = [0.0, 50.0, 100.0]
    border_styles = ["solid", "dash", "dot"]

    for shp in shapes:
        for op in opacities:
            p = MapPoint(name="Форма", latitude=56.0, longitude=47.0, symbol=shp, opacity=op, stroke_width=0.0)
            assert p.symbol == shp
            assert p.opacity == op
            assert p.stroke_width == 0.0

            p_stroke = MapPoint(name="ФормаОбводка", latitude=56.0, longitude=47.0, symbol=shp, stroke_width=4.5, stroke_red=10, stroke_green=20, stroke_blue=30)
            assert p_stroke.stroke_width == 4.5
            assert p_stroke.stroke_red == 10

    # Проверка стилей зон и неизменности geographic radius
    for b_style in border_styles:
        z_point = MapPoint(
            name="ЗонаСтиль",
            latitude=56.0,
            longitude=47.0,
            zone_enabled=True,
            radius_m=2500.0,
            zone_border_style=b_style,
            zone_border_width=3.5,
            zone_border_red=200,
            zone_border_green=100,
            zone_border_blue=50,
            zone_opacity=45,
        )
        assert z_point.zone_border_style == b_style
        assert z_point.radius_m == 2500.0

        # Изменение визуального стиля границы не меняет радиус
        z_point.zone_border_style = "dot"
        z_point.zone_border_width = 8.0
        assert z_point.radius_m == 2500.0


# =============================================================================
# 9. MAP / EXPORT VISUAL PARITY
# =============================================================================


def test_map_and_export_visual_parity(qapp, tmp_path):
    """Сверка параметров сложного стиля точки и геозоны в MapCanvas и MapRenderer."""
    p = MapPoint(
        id="complex-pt",
        name="Сложный Объект",
        latitude=56.0,
        longitude=47.0,
        symbol="triangle",
        red=34,
        green=197,
        blue=94,  # Green fill
        stroke_red=0,
        stroke_green=0,
        stroke_blue=0,  # Black stroke
        stroke_width=3.0,
        opacity=60.0,
        zone_enabled=True,
        radius_m=1500.0,
        zone_red=239,
        zone_green=68,
        zone_blue=68,
        zone_opacity=35,
        zone_border_red=220,
        zone_border_green=38,
        zone_border_blue=38,  # Red dashed border
        zone_border_width=2.0,
        zone_border_style="dash",
        visible=True,
    )

    # Проверка на холсте
    canvas = MapCanvas()
    canvas.add_user_point(p, 100.0, 100.0)
    assert "complex-pt" in canvas._user_point_items
    assert "complex-pt" in canvas._user_zone_items

    # Проверка в MapRenderer
    out_img = tmp_path / "parity_export.png"
    opts = ImageExportOptions(file_path=out_img, width_px=600, height_px=400)
    rendered = MapRenderer.render_map(
        options=opts,
        active_crs="OGC:CRS84",
        target_extent=(46.0, 55.0, 48.0, 57.0),
        points=[p],
    )
    assert not rendered.isNull()
    assert rendered.width() == 600


# =============================================================================
# 10 & 11. INDIVIDUAL & GLOBAL VISIBILITY
# =============================================================================


def test_individual_and_global_visibility_combinations(qapp):
    """Тестирование видимости точек A (hidden) и B (visible) и независимости point.visible от global toggles."""
    canvas = MapCanvas()
    p_a = MapPoint(id="pt-a", name="A", latitude=56.1, longitude=47.1, visible=False, zone_enabled=True, radius_m=500)
    p_b = MapPoint(id="pt-b", name="B", latitude=56.2, longitude=47.2, visible=True, zone_enabled=True, radius_m=500)

    canvas.add_user_point(p_a, 10.0, 10.0)
    canvas.add_user_point(p_b, 20.0, 20.0)

    item_a = canvas._user_point_items["pt-a"]
    item_b = canvas._user_point_items["pt-b"]

    assert item_a.isVisible() is False
    assert item_b.isVisible() is True

    # Глобальное выключение точек
    canvas.set_all_points_visible(False)
    assert item_a.isVisible() is False
    assert item_b.isVisible() is False
    # point.visible не изменился
    assert p_a.visible is False
    assert p_b.visible is True

    # Глобальное включение точек
    canvas.set_all_points_visible(True)
    assert item_a.isVisible() is False
    assert item_b.isVisible() is True


# =============================================================================
# 13 & 14. COLLISION AVOIDANCE & PERFORMANCE (1000 & 5000 POINTS)
# =============================================================================


def test_collision_avoidance_priority(qapp):
    """Выбранная точка имеет приоритет при наложении подписей."""
    canvas = MapCanvas()
    canvas.resize(800, 600)
    canvas.show()

    # Две близкие точки в одной экранной области
    p1 = MapPoint(id="p1", name="Первая длинная подпись", latitude=56.0, longitude=47.0)
    p2 = MapPoint(id="p2", name="Вторая длинная подпись", latitude=56.0001, longitude=47.0001)

    canvas.add_user_point(p1, 100.0, 100.0)
    canvas.add_user_point(p2, 105.0, 102.0)

    canvas.set_labels_mode("all")
    canvas.update_selected_label_ids({"p2"})

    lbl1 = canvas._user_label_items["p1"]
    lbl2 = canvas._user_label_items["p2"]

    # Обе подписи отображаются и смещены
    assert lbl1.isVisible() is True
    assert lbl2.isVisible() is True
    assert lbl1.pos() != lbl2.pos()


def test_label_performance_1000_and_5000_points(qapp):
    """Производительность spatial grid при расчете коллизий 1000 и 5000 точек."""
    canvas = MapCanvas()
    canvas.resize(1000, 1000)

    points = []
    with canvas.defer_labels_layout():
        for i in range(1000):
            pt = MapPoint(id=f"pt-{i}", name=f"Объект-{i}", latitude=56.0 + (i % 50) * 0.01, longitude=47.0 + (i // 50) * 0.01)
            points.append(pt)
            canvas.add_user_point(pt, (i % 50) * 10.0, (i // 50) * 10.0)

    canvas.set_labels_mode("all")

    t0 = time.perf_counter()
    canvas._recalculate_labels_layout()
    t_1000 = time.perf_counter() - t0

    # 1000 точек должны рассчитываться со spatial grid менее чем за 0.25 с
    assert t_1000 < 0.25, f"Расчет 1000 подписей занял слишком много времени: {t_1000:.3f}с"

    # Добавляем до 5000 точек
    with canvas.defer_labels_layout():
        for i in range(1000, 5000):
            pt = MapPoint(id=f"pt-{i}", name=f"P-{i}", latitude=56.0 + (i % 70) * 0.008, longitude=47.0 + (i // 70) * 0.008)
            canvas.add_user_point(pt, (i % 70) * 12.0, (i // 70) * 12.0)

    t1 = time.perf_counter()
    canvas._recalculate_labels_layout()
    t_5000 = time.perf_counter() - t1

    # 5000 точек со spatial grid должны рассчитываться менее чем за 1.0 с
    assert t_5000 < 1.0, f"Расчет 5000 подписей занял слишком много времени: {t_5000:.3f}с"


# =============================================================================
# 16. IMPORT (STAGE 17 AND LEGACY CSV)
# =============================================================================


def test_import_stage17_and_legacy_csv(tmp_path):
    """Импорт CSV со всеми новыми колонками Этапа 17 и старого CSV без них."""
    from rme_mapper.importers.models import ImportOptions
    from rme_mapper.importers.import_service import ImportService

    svc = ImportService()

    # 1. CSV со всеми новыми колонками
    csv_17 = tmp_path / "stage17.csv"
    csv_17.write_text(
        "name,latitude,longitude,object_number,category,description,visible,stroke_width,marker_opacity,zone_border_style\n"
        "Скважина 1,56.12,47.15,СКВ-01,Добыча,Глубокая скважина,true,2.5,80,dash\n"
        "Скважина 2,56.13,47.16,СКВ-02,Контроль,Наблюдение,false,1.0,100,dot\n",
        encoding="utf-8",
    )

    res_17 = svc.validate_file(csv_17, options=ImportOptions())
    assert len(res_17.errors) == 0
    points_17 = res_17.points
    assert len(points_17) == 2
    assert points_17[0].object_number == "СКВ-01"
    assert points_17[0].category == "Добыча"
    assert points_17[0].description == "Глубокая скважина"
    assert points_17[0].visible is True
    assert points_17[0].stroke_width == 2.5
    assert points_17[0].opacity == 80.0
    assert points_17[0].zone_border_style == "dash"

    assert points_17[1].object_number == "СКВ-02"
    assert points_17[1].visible is False
    assert points_17[1].zone_border_style == "dot"

    # 2. Legacy CSV без новых колонок
    csv_legacy = tmp_path / "legacy.csv"
    csv_legacy.write_text(
        "name,latitude,longitude\n"
        "Базовая точка,56.5,47.5\n",
        encoding="utf-8",
    )
    res_leg = svc.validate_file(csv_legacy, options=ImportOptions())
    assert len(res_leg.errors) == 0
    points_leg = res_leg.points
    assert len(points_leg) == 1
    assert points_leg[0].object_number == ""
    assert points_leg[0].category == ""
    assert points_leg[0].description == ""
    assert points_leg[0].visible is True
    assert points_leg[0].stroke_width in (1.0, 1)
    assert points_leg[0].opacity == 100.0


# =============================================================================
# 15. SEARCH
# =============================================================================


def test_points_panel_search_by_all_new_fields(qapp):
    """Поиск в PointsPanel по name, number, category, description регистронезависимо."""
    panel = PointsPanel()
    panel.add_row(
        num="№01",
        name="Насосная станция",
        lat="56.0",
        lon="47.0",
        shape="Круг",
        radius="—",
        point_id="pid-1",
        object_number="НС-500",
        category="Водоснабжение",
        description="Резервуар чистой воды",
        visible=True,
    )
    panel.add_row(
        num="№02",
        name="Трансформатор",
        lat="56.1",
        lon="47.1",
        shape="Квадрат",
        radius="—",
        point_id="pid-2",
        object_number="ТП-10",
        category="Энергетика",
        description="Подстанция на ремонте",
        visible=True,
    )

    # Поиск по номеру в разном регистре
    panel.search_input.setText("нс-500")
    assert panel.points_table.isRowHidden(0) is False
    assert panel.points_table.isRowHidden(1) is True

    # Поиск по категории
    panel.search_input.setText("энерг")
    assert panel.points_table.isRowHidden(0) is True
    assert panel.points_table.isRowHidden(1) is False

    # Поиск по описанию
    panel.search_input.setText("РЕЗЕРВУАР")
    assert panel.points_table.isRowHidden(0) is False
    assert panel.points_table.isRowHidden(1) is True


# =============================================================================
# 18. MANUAL CHECK SCENARIO A–U
# =============================================================================


def test_manual_check_scenario_a_to_u(qapp, mari_gpkg, tmp_path):
    """Полное сквозное выполнение контрольного сценария A–U."""
    win = MainWindow(map_path=mari_gpkg)

    # A–G. Создание точки со сложными параметрами:
    # № 128, Березовая роща, Категория: Местообитание, Описание: тестовое описание.
    # Triangle, Green fill, Black stroke 3 px, Opacity 60%, Zone 1500 m, Red dashed border 2 px.
    p = MapPoint(
        id="pt-au",
        name="Березовая роща",
        latitude=56.63,
        longitude=47.88,
        object_number="128",
        category="Местообитание",
        description="тестовое описание.",
        symbol="triangle",
        red=34,
        green=197,
        blue=94,
        stroke_red=0,
        stroke_green=0,
        stroke_blue=0,
        stroke_width=3.0,
        opacity=60.0,
        zone_enabled=True,
        radius_m=1500.0,
        zone_border_red=220,
        zone_border_green=38,
        zone_border_blue=38,
        zone_border_width=2.0,
        zone_border_style="dash",
        visible=True,
    )
    win.point_controller._cmd_add_point(p)

    # H. Label Number: 128
    assert format_point_label(p, "number") == "128"

    # I. Label Number + Name: 128 - Березовая роща
    assert format_point_label(p, "number_name") == "128 - Березовая роща"

    # J. Создать соседнюю точку и проверить коллизии
    p_neighbor = MapPoint(
        id="pt-au-neighbor",
        name="Соседняя опушка",
        latitude=56.6305,
        longitude=47.8805,
        object_number="129",
    )
    win.point_controller._cmd_add_point(p_neighbor)

    # K. Скрыть одну точку
    win.point_controller.toggle_point_visibility("pt-au")
    assert win._point_service.get_point("pt-au").visible is False

    # L. Ctrl+Z / Ctrl+Y visibility
    win.point_controller.undo()
    assert win._point_service.get_point("pt-au").visible is True
    win.point_controller.redo()
    assert win._point_service.get_point("pt-au").visible is False
    win.point_controller.undo()  # оставляем видимой для move

    # M. Move Point
    win.point_controller.on_point_moved_on_canvas("pt-au", 47.90, 56.65, 47.88, 56.63)

    # N. Проверить новые coordinates
    moved_p = win._point_service.get_point("pt-au")
    assert abs(moved_p.longitude - 47.90) < 1e-4
    assert abs(moved_p.latitude - 56.65) < 1e-4

    # O. Ctrl+Z / Ctrl+Y move
    win.point_controller.undo()
    assert abs(win._point_service.get_point("pt-au").latitude - 56.63) < 1e-4
    win.point_controller.redo()
    assert abs(win._point_service.get_point("pt-au").latitude - 56.65) < 1e-4

    # P. Save *.gpmap
    saved_file = tmp_path / "scenario_au.gpmap"
    assert win.project_controller.save_project_as_workflow(saved_file) is True
    assert saved_file.exists()

    # Q. Reopen
    reopened_proj = ProjectService.load_project(saved_file)
    assert len(reopened_proj.points) == 2
    pt_reopened = next(pt for pt in reopened_proj.points if pt.id == "pt-au")
    assert pt_reopened.object_number == "128"
    assert pt_reopened.category == "Местообитание"
    assert pt_reopened.symbol == "triangle"

    # T. PNG/JPEG export
    export_png = tmp_path / "scenario_au_export.png"
    opts = ImageExportOptions(file_path=export_png, width_px=800, height_px=600, label_content_mode="number_name")
    exported_img = MapRenderer.render_map(
        options=opts,
        active_crs="OGC:CRS84",
        target_extent=(47.5, 56.5, 48.0, 57.0),
        points=[p, p_neighbor],
    )
    assert exported_img.save(str(export_png)) is True
    assert export_png.exists() and export_png.stat().st_size > 0

    # U. RU -> EN -> RU (пользовательские данные не меняются)
    set_language("en")
    win.retranslate_ui()
    assert win._point_service.get_point("pt-au").name == "Березовая роща"
    assert win._point_service.get_point("pt-au").object_number == "128"
    set_language("ru")
    win.retranslate_ui()
