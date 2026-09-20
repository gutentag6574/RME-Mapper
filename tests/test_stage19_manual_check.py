"""Сквозная контрольная проверка (Manual Checklist) для Этапа 19 (GIS-инструменты).

Проверяет комплексный пользовательский сценарий A–G:
A. Инструмент измерения расстояния (поликлики, резиновая нить, расчет m/km, завершение, Esc).
B. Инструмент измерения площади (>= 3 вершины, полупрозрачный полигон, m²/ha/km², периметр).
C. Экранная масштабная линейка (верхний левый угол, геодезический пересчет, красивые числа, переключение, скрытие без карты).
D. Координатная сетка (Z=80, градусы DD и метры UTM, адаптивный шаг, очистка при выгрузке).
E. Взаимодействие инструментов (взаимное исключение, зум/панорамирование без добавления вершин, клик по точке, Esc, Очистить).
F. Экспорт в PNG/JPEG с опциональной сеткой (слои, исключение временных измерений).
G. Двуязычная локализация RU/EN всех новых элементов и единиц измерения.
H. Неизменность состояния проекта (is_modified=False, чистый стек Undo).
"""

from pathlib import Path
import pytest
from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QImage, QKeyEvent, QMouseEvent

from rme_mapper.exporters.map_renderer import MapRenderer
from rme_mapper.exporters.models import ImageExportOptions
from rme_mapper.i18n import get_language, set_language, tr
from rme_mapper.models.map_point import MapPoint
from rme_mapper.services.app_settings_service import AppSettingsService
from rme_mapper.services.geodesic_service import GeodesicService
from rme_mapper.services.grid_calculator import GridCalculator
from rme_mapper.services.scale_service import ScaleService
from rme_mapper.ui.export_image_dialog import ExportImageDialog
from rme_mapper.ui.main_window import MainWindow


@pytest.fixture
def default_gpkg() -> Path:
    """Путь к тестовому GeoPackage."""
    return Path(__file__).resolve().parent.parent / "maps" / "test_map" / "prepared" / "mari.gpkg"


def test_stage19_manual_check_comprehensive(qapp, default_gpkg, tmp_path):
    """Сквозная проверка всех требований и сценариев Этапа 19."""
    # Убеждаемся в начальном состоянии настроек
    settings = AppSettingsService()
    settings.set_show_coordinate_grid(False)
    settings.set_show_scale_indicator(True)
    set_language("ru")

    window = MainWindow()
    window.load_map(default_gpkg)
    window.resize(1000, 700)
    window.show()

    canvas = window.map_canvas
    canvas.updateGeometry()

    # =========================================================================
    # A. Инструмент измерения расстояния
    # =========================================================================
    # 1. Активация инструмента
    window.measure_distance_action.trigger()
    assert window.measure_distance_action.isChecked() is True
    assert canvas.interaction_mode == "measure_distance"
    assert canvas.cursor().shape() == Qt.CursorShape.CrossCursor

    # 2. Добавление вершин полилинии
    # Точка 1
    canvas._add_measurement_vertex((47.89, -56.63))
    assert len(canvas._measure_points) == 1
    assert canvas.has_measurements() is True

    # Резиновая нить
    canvas._update_rubber_band(QPointF(48.0, -56.7))
    assert canvas._measure_temp_pos is not None

    # Точка 2
    canvas._add_measurement_vertex((48.0, -56.7))
    assert len(canvas._measure_points) == 2
    dist_m, _ = canvas._calculate_current_measurement()
    assert dist_m > 5000.0  # > 5 км
    dist_text = GeodesicService.format_distance(dist_m, "ru")
    assert "км" in dist_text

    # 3. Завершение измерения
    canvas._finish_measurement()
    assert len(canvas._measure_completed_items) > 0
    assert len(canvas._measure_points) == 0  # Сброс активных точек
    assert canvas.has_measurements() is True
    assert window.clear_measurements_action.isEnabled() is True

    # 4. Отмена по Esc нового измерения
    window.measure_distance_action.trigger()
    canvas._add_measurement_vertex((47.5, -56.5))
    assert len(canvas._measure_points) == 1
    esc_ev = QKeyEvent(QKeyEvent.Type.KeyPress, Qt.Key.Key_Escape, Qt.KeyboardModifier.NoModifier)
    canvas.keyPressEvent(esc_ev)
    assert len(canvas._measure_points) == 0
    assert canvas.interaction_mode == "navigation"
    # Ранее завершенное измерение сохраняется
    assert len(canvas._measure_completed_items) > 0

    # =========================================================================
    # B. Инструмент измерения площади
    # =========================================================================
    window.measure_area_action.trigger()
    assert window.measure_area_action.isChecked() is True
    assert window.measure_distance_action.isChecked() is False
    assert canvas.interaction_mode == "measure_area"

    # Добавляем 3 вершины
    canvas._add_measurement_vertex((47.80, -56.60))
    canvas._add_measurement_vertex((47.90, -56.60))
    canvas._add_measurement_vertex((47.90, -56.70))
    assert len(canvas._measure_points) == 3

    area_m2, perim_m = canvas._calculate_current_measurement()
    assert area_m2 > 10000.0  # > 1 га
    assert perim_m > 1000.0
    area_text = GeodesicService.format_area(area_m2, "ru")
    assert ("га" in area_text or "км²" in area_text)

    # Завершаем полигон
    canvas._finish_measurement()
    assert len(canvas._measure_completed_items) >= 2

    # =========================================================================
    # C. Экранная масштабная линейка
    # =========================================================================
    assert hasattr(canvas, "_scale_overlay")
    assert canvas._scale_overlay.is_indicator_visible() is True
    assert canvas._scale_overlay.x() >= 0
    assert canvas._scale_overlay.y() >= 0

    # Масштабная линейка имеет корректный текст
    scale_text = canvas._scale_overlay.text()
    assert ("м" in scale_text or "км" in scale_text)

    # Переключение видимости линейки через меню Вид
    window.toggle_scale_action.trigger()
    assert window.toggle_scale_action.isChecked() is False
    assert canvas.show_scale_indicator is False
    assert canvas._scale_overlay.is_indicator_visible() is False

    # Включаем обратно
    window.toggle_scale_action.trigger()
    assert window.toggle_scale_action.isChecked() is True
    assert canvas.show_scale_indicator is True
    assert canvas._scale_overlay.is_indicator_visible() is True

    # =========================================================================
    # D. Координатная сетка
    # =========================================================================
    # По умолчанию выключена
    assert window.toggle_grid_action.isChecked() is False
    assert canvas.show_coordinate_grid is False

    # Включаем через меню Вид
    window.toggle_grid_action.trigger()
    assert window.toggle_grid_action.isChecked() is True
    assert canvas.show_coordinate_grid is True
    assert canvas._grid_item_group is not None
    assert canvas._grid_item_group.zValue() == 80.0
    assert len(canvas._grid_item_group.childItems()) > 0

    # Проверяем формат подписей для географической CRS (OGC:CRS84)
    grid_calc = GridCalculator.calculate_grid((47.0, 56.0, 49.0, 57.5), "OGC:CRS84")
    assert grid_calc is not None
    assert "°" in grid_calc.vertical_lines[0].label

    # =========================================================================
    # E. Взаимодействие инструментов и неконфликтность
    # =========================================================================
    # 1. Взаимное исключение с добавлением точки
    window.add_pt_map_action.setChecked(True)
    assert window.add_pt_map_action.isChecked() is True
    assert window.measure_distance_action.isChecked() is False
    assert window.measure_area_action.isChecked() is False
    assert canvas.interaction_mode == "add_point"

    # Включаем измерение площади -> add_point выключается
    window.measure_area_action.setChecked(True)
    assert window.measure_area_action.isChecked() is True
    assert window.add_pt_map_action.isChecked() is False
    assert canvas.interaction_mode == "measure_area"

    # 2. Панорамирование средней кнопкой мыши
    mid_event = QMouseEvent(
        QMouseEvent.Type.MouseButtonPress,
        QPointF(300.0, 300.0),
        Qt.MouseButton.MiddleButton,
        Qt.MouseButton.MiddleButton,
        Qt.KeyboardModifier.NoModifier,
    )
    canvas.mousePressEvent(mid_event)
    assert canvas._is_middle_panning is True
    assert len(canvas._measure_points) == 0  # Никаких вершин не добавилось

    # 3. Клик по точке во время измерения добавляет вершину и не выделяет точку
    pt_sample = MapPoint(id="chk_pt", name="Проверочная", latitude=56.65, longitude=47.95)
    canvas.add_user_point(pt_sample)
    canvas._selected_point_ids.clear()

    pt_view_pos = canvas.mapFromScene(QPointF(47.95, -56.65))
    left_click = QMouseEvent(
        QMouseEvent.Type.MouseButtonPress,
        QPointF(pt_view_pos.x(), pt_view_pos.y()),
        Qt.MouseButton.LeftButton,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    canvas.mousePressEvent(left_click)
    assert len(canvas._measure_points) == 1
    assert "chk_pt" not in canvas._selected_point_ids

    # 4. Очистить измерения
    window.clear_measurements_action.trigger()
    assert canvas.has_measurements() is False
    assert len(canvas._measure_completed_items) == 0

    # =========================================================================
    # F. Экспорт карты с сеткой (PNG / JPEG)
    # =========================================================================
    # Диалог экспорта
    dialog = ExportImageDialog(
        parent=None,
        active_crs="OGC:CRS84",
        map_title="Контрольный экспорт",
        current_view_extent=(47.0, 56.0, 48.0, 57.0),
        full_map_extent=(47.0, 56.0, 48.0, 57.0),
        points=[pt_sample],
        selected_point_ids=set(),
    )
    assert hasattr(dialog, "chk_grid")
    assert dialog.chk_grid.isChecked() is False

    dialog.chk_grid.setChecked(True)
    out_png = tmp_path / "stage19_audit_map.png"
    dialog.path_edit.setText(str(out_png))
    opts = dialog.build_export_options()
    assert opts.include_grid is True

    # Рендер через MapRenderer
    img = MapRenderer.render_map(
        options=opts,
        active_crs="OGC:CRS84",
        target_extent=(47.0, 56.0, 48.0, 57.0),
        points=[pt_sample],
    )
    assert isinstance(img, QImage)
    assert not img.isNull()
    img.save(str(out_png), "PNG")
    assert out_png.exists()
    assert out_png.stat().st_size > 1000
    dialog.close()

    # =========================================================================
    # G. Двуязычная локализация RU / EN
    # =========================================================================
    set_language("en")
    window.retranslate_ui()
    assert window.tools_menu.title() == "Tools"
    assert "distance" in window.measure_distance_action.text().lower()
    assert "area" in window.measure_area_action.text().lower()
    assert "clear" in window.clear_measurements_action.text().lower()
    assert "grid" in window.toggle_grid_action.text().lower()
    assert "scale" in window.toggle_scale_action.text().lower()

    set_language("ru")
    window.retranslate_ui()
    assert window.tools_menu.title() == "Инструменты"
    assert "расстояние" in window.measure_distance_action.text().lower()
    assert "площадь" in window.measure_area_action.text().lower()

    # =========================================================================
    # H. Неизменность состояния проекта и Undo
    # =========================================================================
    assert window.is_modified is False
    assert len(window.point_controller.undo_manager._undo_stack) == 0

    # =========================================================================
    # I. Выгрузка карты очищает сетку и переводит масштаб в пустое состояние
    # =========================================================================
    window.close_map(prompt=False)
    assert canvas._grid_item_group is None
    assert canvas._scale_overlay.isHidden() is True

    window.close()
