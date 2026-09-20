"""Тесты для Этапа 17: UI диалоги (PointDialog, BulkPointStyleDialog), панели, экспорт и импорт."""

import os
from pathlib import Path
import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from rme_mapper.exporters.map_renderer import MapRenderer
from rme_mapper.exporters.models import ImageExportOptions
from rme_mapper.i18n.translations_en import TRANSLATIONS_EN
from rme_mapper.i18n.translations_ru import TRANSLATIONS_RU
from rme_mapper.importers.import_service import CANONICAL_HEADERS
from rme_mapper.models.map_point import MapPoint
from rme_mapper.ui.bulk_point_style_dialog import BulkPointStyleDialog
from rme_mapper.ui.panels.points_panel import PointsPanel
from rme_mapper.ui.panels.properties_panel import PropertiesPanel
from rme_mapper.ui.point_dialog import PointDialog


@pytest.fixture(scope="session")
def qapp():
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    yield app


# =============================================================================
# 1. PointDialog: вкладки, категории, живое превью
# =============================================================================


def test_point_dialog_tabs_and_stage17_controls(qapp):
    """Проверка наличия 3 вкладок и элементов оформления точки."""
    existing_categories = ["Опоры", "Скважины", "Мосты"]
    dialog = PointDialog(categories=existing_categories)

    # Проверка QTabWidget
    assert dialog.tab_widget is not None
    assert dialog.tab_widget.count() == 3
    tab_titles = [dialog.tab_widget.tabText(i) for i in range(3)]
    assert any("Основное" in t or "General" in t for t in tab_titles)
    assert any("Координаты" in t or "Coordinates" in t for t in tab_titles)
    assert any("Оформление" in t or "Style" in t for t in tab_titles)

    # Проверка категорий
    assert dialog.cat_combo.count() >= 3
    for cat in existing_categories:
        assert dialog.cat_combo.findText(cat) != -1

    # Заполнение полей
    dialog.name_edit.setText("Точка А")
    dialog.num_edit.setText("№-101")
    dialog.cat_combo.setEditText("НоваяКатегория")
    dialog.desc_edit.setPlainText("Подробное описание объекта")
    dialog.lat_edit.setText("56.5")
    dialog.lon_edit.setText("47.8")
    dialog.stroke_width_spin.setValue(3.0)
    dialog.marker_opacity_spin.setValue(80)
    dialog.zone_chk.setChecked(True)
    dialog.zone_radius_edit.setText("500")
    dialog.zone_border_style_combo.setCurrentIndex(1)  # dash

    # Валидация и сабмит
    dialog._validate_and_submit()
    res = dialog.get_data()
    assert res is not None
    assert res.name == "Точка А"
    assert res.object_number == "№-101"
    assert res.category == "НоваяКатегория"
    assert res.description == "Подробное описание объекта"
    assert res.stroke_width == 3.0
    assert res.opacity == 80.0
    assert res.zone_border_style == "dash"


def test_point_dialog_edit_mode_populates_all_fields(qapp):
    """Проверка заполнения формы при редактировании точки."""
    point = MapPoint(
        name="Точка контроля",
        latitude=56.5,
        longitude=47.8,
        object_number="ТК-01",
        category="Контроль",
        description="Тестовый узел",
        stroke_red=200,
        stroke_green=100,
        stroke_blue=50,
        stroke_width=2.5,
        opacity=75,
        zone_border_red=10,
        zone_border_green=20,
        zone_border_blue=30,
        zone_border_width=1.5,
        zone_border_style="dot",
    )
    dialog = PointDialog(point=point)
    assert dialog.num_edit.text() == "ТК-01"
    assert dialog.cat_combo.currentText() == "Контроль"
    assert dialog.desc_edit.toPlainText() == "Тестовый узел"
    assert dialog.stroke_width_spin.value() == 2.5
    assert dialog.marker_opacity_spin.value() == 75
    assert dialog.zone_border_style_combo.currentData() == "dot"


# =============================================================================
# 2. BulkPointStyleDialog: пакетное изменение стилей
# =============================================================================


def test_bulk_point_style_dialog_stage17_options(qapp):
    """Проверка диалога пакетного редактирования оформления точек."""
    dialog = BulkPointStyleDialog(point_count=5)
    dialog.chk_stroke_width.setChecked(True)
    dialog.spin_stroke_width.setValue(4.0)
    dialog.chk_marker_opacity.setChecked(True)
    dialog.spin_marker_opacity.setValue(60)
    dialog.chk_zone_border_style.setChecked(True)
    dialog.combo_zone_border_style.setCurrentIndex(1)  # dash

    res = dialog.get_style_changes()
    assert res["stroke_width"] == 4.0
    assert res["opacity"] == 60.0
    assert res["zone_border_style"] == "dash"


# =============================================================================
# 3. PropertiesPanel & PointsPanel
# =============================================================================


def test_properties_panel_displays_stage17_fields(qapp):
    """PropertiesPanel корректно отображает новые поля."""
    panel = PropertiesPanel()
    point = MapPoint(
        name="Подстанция 110кВ",
        latitude=56.6,
        longitude=47.9,
        object_number="ПС-110",
        category="Энергетика",
        description="Крупный узловой пункт распределения электроэнергии",
        visible=False,
        stroke_width=2.0,
        opacity=90,
    )
    panel.update_properties(point)
    assert panel.prop_object_number_val.text() == "ПС-110"
    assert panel.prop_category_val.text() == "Энергетика"
    assert "Крупный узловой пункт" in panel.prop_description_val.text()
    assert panel.prop_visibility_val.text() == "Нет"
    assert "90%" in panel.prop_opacity_val.text()


def test_points_panel_columns_and_search(qapp):
    """PointsPanel строго сохраняет 6 колонок и ищет по новым полям."""
    panel = PointsPanel()
    assert panel.points_table.columnCount() == 6

    # Добавляем 2 строки через add_row
    panel.add_row(
        num="A-01",
        name="Альфа",
        lat="56.100000",
        lon="47.100000",
        shape="Круг",
        radius="—",
        point_id="p1",
        object_number="A-01",
        category="Связь",
        description="Вышка 1",
        visible=True,
    )
    panel.add_row(
        num="B-02",
        name="Бета",
        lat="56.200000",
        lon="47.200000",
        shape="Круг",
        radius="—",
        point_id="p2",
        object_number="B-02",
        category="Транспорт",
        description="Мост 2",
        visible=True,
    )
    assert panel.points_table.rowCount() == 2

    # Колонка 0 содержит object_number
    assert panel.points_table.item(0, 0).text() == "A-01"
    assert panel.points_table.item(1, 0).text() == "B-02"

    # Поиск по категории
    panel.search_input.setText("Связь")
    assert panel.points_table.isRowHidden(0) is False
    assert panel.points_table.isRowHidden(1) is True

    # Поиск по описанию
    panel.search_input.setText("Мост")
    assert panel.points_table.isRowHidden(0) is True
    assert panel.points_table.isRowHidden(1) is False

    # Поиск по номеру
    panel.search_input.setText("A-01")
    assert panel.points_table.isRowHidden(0) is False
    assert panel.points_table.isRowHidden(1) is True


# =============================================================================
# 4. ImportService: распознавание заголовков
# =============================================================================


def test_import_service_canonical_headers_stage17():
    """ImportService содержит алиасы для всех новых полей Этапа 17."""
    assert CANONICAL_HEADERS.get("номер") == "object_number"
    assert CANONICAL_HEADERS.get("номер_объекта") == "object_number"
    assert CANONICAL_HEADERS.get("object_number") == "object_number"

    assert CANONICAL_HEADERS.get("категория") == "category"
    assert CANONICAL_HEADERS.get("category") == "category"

    assert CANONICAL_HEADERS.get("описание") == "description"
    assert CANONICAL_HEADERS.get("description") == "description"

    assert CANONICAL_HEADERS.get("толщина_обводки") == "stroke_width"
    assert CANONICAL_HEADERS.get("прозрачность_маркера") == "marker_opacity"
    assert CANONICAL_HEADERS.get("стиль_границы") == "zone_border_style"


# =============================================================================
# 5. MapRenderer: экспорт с новыми стилями и режимами подписей
# =============================================================================


def test_map_renderer_export_stage17(qapp, tmp_path):
    """MapRenderer экспортирует точки с обводкой, непрозрачностью и подписями."""
    p_vis = MapPoint(
        name="Точка Экспорта",
        latitude=56.0,
        longitude=47.0,
        object_number="ЭКСП-1",
        stroke_width=2.0,
        opacity=80,
        zone_enabled=True,
        radius_m=1000,
        zone_border_style="dash",
        visible=True,
    )
    p_hid = MapPoint(
        name="Скрытая",
        latitude=56.1,
        longitude=47.1,
        visible=False,
    )

    export_path = tmp_path / "test_export.png"
    options = ImageExportOptions(
        file_path=export_path,
        format="PNG",
        width_px=800,
        height_px=600,
        include_points=True,
        include_zones=True,
        include_labels=True,
        label_content_mode="number_name",
    )

    image = MapRenderer.render_map(
        options=options,
        active_crs="OGC:CRS84",
        target_extent=(46.0, 55.0, 48.0, 57.0),
        points=[p_vis, p_hid],
    )

    assert image is not None
    assert not image.isNull()
    assert image.width() == 800
    assert image.height() == 600


# =============================================================================
# 6. Симметрия переводов RU / EN
# =============================================================================


def test_i18n_stage17_translations_symmetry():
    """Проверка симметричности переводов RU и EN для новых ключей Этапа 17."""
    new_keys = [
        "properties.object_number",
        "properties.category",
        "properties.description",
        "properties.visibility",
        "properties.marker_opacity",
        "properties.stroke",
        "properties.zone_opacity",
        "properties.zone_border",
        "properties.visible_yes",
        "properties.visible_no",
        "action.move_point",
        "action.show_object",
        "action.hide_object",
        "menu.point_labels_content",
        "label_content.name",
        "label_content.number",
        "label_content.number_name",
        "dialog.point.tab_general",
        "dialog.point.tab_coords",
        "dialog.point.tab_style",
        "dialog.point.stroke_color",
        "dialog.point.stroke_width",
        "dialog.point.marker_opacity",
        "dialog.point.zone_border_color",
        "dialog.point.zone_border_width",
        "dialog.point.zone_border_style",
        "tab.main",
        "tab.coordinates",
        "tab.style",
    ]
    for key in new_keys:
        assert key in TRANSLATIONS_RU, f"Ключ '{key}' отсутствует в TRANSLATIONS_RU"
        assert key in TRANSLATIONS_EN, f"Ключ '{key}' отсутствует в TRANSLATIONS_EN"
        assert TRANSLATIONS_RU[key] != "", f"Ключ '{key}' пуст в TRANSLATIONS_RU"
        assert TRANSLATIONS_EN[key] != "", f"Ключ '{key}' пуст в TRANSLATIONS_EN"
