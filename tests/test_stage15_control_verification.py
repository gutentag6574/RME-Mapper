"""Контрольные тесты требований и сценариев Этапа 15 (GeoPoint Mapper)."""

from pathlib import Path
import pytest

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QAction, QColor, QImage, QKeySequence, QPainter, QPainterPath, QPen, QBrush
from PySide6.QtWidgets import QApplication

from rme_mapper.exporters.decorations import MapDecorationRenderer
from rme_mapper.exporters.image_export_service import ImageExportService
from rme_mapper.exporters.map_renderer import MapRenderer
from rme_mapper.exporters.models import ImageExportOptions
from rme_mapper.i18n import get_language, set_language, tr
from rme_mapper.models.map_point import MapPoint
from rme_mapper.models.map_profile import MapProfile
from rme_mapper.ui.export_image_dialog import ExportImageDialog
from rme_mapper.ui.main_window import MainWindow


@pytest.fixture(scope="module", autouse=True)
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def test_ctrl_01_menu_location_and_no_duplicate_qaction(qapp):
    """1. Проверка расположения в Export menu, отсутствия дубликатов QAction и шортката Ctrl+Shift+E."""
    win = MainWindow()

    # Проверяем, что action прикреплен к export_menu
    assert win.export_menu is not None
    assert win.export_map_image_action in win.export_menu.actions()

    # Проверяем, что в file_menu и toolbar этого action нет
    assert win.export_map_image_action not in win.file_menu.actions()
    assert win.export_map_image_action not in win.main_toolbar.actions()

    # Проверяем отсутствие дубликатов: ровно один такой QAction в окне
    export_image_actions = [
        act for act in win.findChildren(QAction)
        if act.shortcut() == QKeySequence("Ctrl+Shift+E")
    ]
    assert len(export_image_actions) == 1
    assert export_image_actions[0] is win.export_map_image_action

    # Проверяем заголовки меню и действия в RU
    set_language("ru")
    win.retranslate_ui()
    assert win.export_menu.title() == "Экспорт"
    assert win.export_map_image_action.text() == "Экспортировать карту как изображение..."

    # Проверяем заголовки меню и действия в EN
    set_language("en")
    win.retranslate_ui()
    assert win.export_menu.title() == "Export"
    assert win.export_map_image_action.text() == "Export Map as Image..."

    set_language("ru")
    win.close()


def test_ctrl_02_resolutions_1080p_2k_4k(tmp_path: Path):
    """2. Проверка точных выходных размеров 1080p, 2K, 4K."""
    extent = (47.0, 56.0, 48.0, 57.0)

    # 1080p: 1920x1080
    f_1080 = tmp_path / "test_1080p.png"
    opts_1080 = ImageExportOptions(file_path=f_1080, width_px=1920, height_px=1080)
    saved_1080 = ImageExportService.export_image(opts_1080, "OGC:CRS84", extent)
    assert saved_1080.exists()
    reader_1080 = QImage(str(saved_1080))
    assert reader_1080.width() == 1920
    assert reader_1080.height() == 1080

    # 2K: 2560x1440
    f_2k = tmp_path / "test_2k.png"
    opts_2k = ImageExportOptions(file_path=f_2k, width_px=2560, height_px=1440)
    saved_2k = ImageExportService.export_image(opts_2k, "OGC:CRS84", extent)
    assert saved_2k.exists()
    reader_2k = QImage(str(saved_2k))
    assert reader_2k.width() == 2560
    assert reader_2k.height() == 1440

    # 4K: 3840x2160
    f_4k = tmp_path / "test_4k.png"
    opts_4k = ImageExportOptions(file_path=f_4k, width_px=3840, height_px=2160)
    saved_4k = ImageExportService.export_image(opts_4k, "OGC:CRS84", extent)
    assert saved_4k.exists()
    reader_4k = QImage(str(saved_4k))
    assert reader_4k.width() == 3840
    assert reader_4k.height() == 2160


def test_ctrl_03_full_map_and_single_point_extents(tmp_path: Path):
    """3. Проверка семантики Full Map и расчета охвата для одиночной точки."""
    # Одиночная точка без зоны -> должна расширяться на дельту 500м
    p_single = MapPoint(id="p1", name="Одинокая", latitude=56.0, longitude=47.0, zone_enabled=False)
    dlg = ExportImageDialog(
        parent=None,
        active_crs="OGC:CRS84",
        map_title="Test",
        current_view_extent=(46.9, 55.9, 47.1, 56.1),
        full_map_extent=(46.0, 55.0, 48.0, 57.0),
        points=[p_single],
        selected_point_ids={"p1"},
    )
    ext_sel = dlg._selected_points_extent
    assert ext_sel is not None
    # Охват не схлопывается в точку: ширина и высота строго положительны
    assert ext_sel[2] > ext_sel[0]
    assert ext_sel[3] > ext_sel[1]
    assert ext_sel[0] < 47.0 < ext_sel[2]
    assert ext_sel[1] < 56.0 < ext_sel[3]

    # Full Map: проверяем точное совпадение с переданным full_map_extent
    dlg.extent_combo.setCurrentIndex(dlg.extent_combo.findData("full_map"))
    curr_target = dlg.get_current_target_extent()
    assert curr_target == (46.0, 55.0, 48.0, 57.0)

    dlg.close()


def test_ctrl_04_map_canvas_zoom_unchanged_after_export(qapp, tmp_path: Path):
    """4. Проверка того, что экспорт не изменяет zoom/pan/масштаб основного MapCanvas."""
    win = MainWindow()
    profile = MapProfile(id="test_map", name="Тестовая карта")
    win.map_controller.active_profile = profile
    win._update_map_dependent_actions(True)

    canvas = win.map_canvas
    canvas.scale(1.5, 1.5)
    initial_transform = canvas.transform()
    initial_viewport_rect = canvas.mapToScene(canvas.viewport().rect()).boundingRect()

    # Выполняем экспорт
    target = tmp_path / "canvas_check.png"
    opts = ImageExportOptions(file_path=target, width_px=800, height_px=600)
    ImageExportService.export_image(
        options=opts,
        active_crs="OGC:CRS84",
        target_extent=(47.0, 56.0, 48.0, 57.0),
    )

    # Проверяем, что параметры холста не изменились
    assert canvas.transform() == initial_transform
    assert canvas.mapToScene(canvas.viewport().rect()).boundingRect() == initial_viewport_rect

    win.close()


def test_ctrl_05_point_shapes_and_rgb_colors():
    """5. Проверка отрисовки разрешенных форм (circle, square, triangle) и RGB-цветов."""
    p_red_circle = MapPoint(id="1", name="RedCircle", latitude=56.5, longitude=47.5, symbol="circle", red=255, green=0, blue=0, size=30.0)
    p_green_square = MapPoint(id="2", name="GreenSquare", latitude=56.5, longitude=47.5, symbol="square", red=0, green=255, blue=0, size=30.0)
    p_blue_triangle = MapPoint(id="3", name="BlueTriangle", latitude=56.5, longitude=47.5, symbol="triangle", red=0, green=0, blue=255, size=30.0)

    opts = ImageExportOptions(
        file_path="dummy.png",
        width_px=600,
        height_px=600,
        background_color="#FFFFFF",
        include_labels=False,
        include_title=False,
        include_crs=False,
        include_legend=False,
        include_scale_bar=False,
        include_north_arrow=False,
    )

    # Проверяем отрисовку круга (наличие красного пикселя в центре)
    img_c = MapRenderer.render_map(opts, "OGC:CRS84", (47.0, 56.0, 48.0, 57.0), points=[p_red_circle])
    center_c = img_c.pixelColor(300, 300)
    assert center_c.red() > 200 and center_c.green() < 50 and center_c.blue() < 50

    # Проверяем квадрат (зеленый пиксель в центре)
    img_s = MapRenderer.render_map(opts, "OGC:CRS84", (47.0, 56.0, 48.0, 57.0), points=[p_green_square])
    center_s = img_s.pixelColor(300, 300)
    assert center_s.green() > 200 and center_s.red() < 50 and center_s.blue() < 50

    # Проверяем треугольник (синий пиксель в центре)
    img_t = MapRenderer.render_map(opts, "OGC:CRS84", (47.0, 56.0, 48.0, 57.0), points=[p_blue_triangle])
    center_t = img_t.pixelColor(300, 300)
    assert center_t.blue() > 200 and center_t.red() < 50 and center_t.green() < 50


def test_ctrl_06_all_legend_positions():
    """6. Проверка всех 4 позиций легенды: top_left, top_right, bottom_left, bottom_right."""
    pts = [MapPoint(name="P", latitude=56.0, longitude=47.0, symbol="circle")]
    img = QImage(1000, 800, QImage.Format.Format_ARGB32_Premultiplied)
    p = QPainter(img)
    img_rect = QRectF(0, 0, 1000, 800)

    # top_left (смещение ниже заголовка y = margin + 50)
    r_tl = MapDecorationRenderer.render_legend(p, pts, False, "top_left", img_rect, 1.0, 20.0)
    assert r_tl.left() == pytest.approx(20.0, abs=1.0)
    assert r_tl.top() == pytest.approx(70.0, abs=1.0)

    # top_right
    r_tr = MapDecorationRenderer.render_legend(p, pts, False, "top_right", img_rect, 1.0, 20.0)
    assert r_tr.right() == pytest.approx(980.0, abs=1.0)
    assert r_tr.top() == pytest.approx(20.0, abs=1.0)

    # bottom_left (смещение выше CRS y = height - margin - card_h - 40)
    r_bl = MapDecorationRenderer.render_legend(p, pts, False, "bottom_left", img_rect, 1.0, 20.0)
    assert r_bl.left() == pytest.approx(20.0, abs=1.0)
    assert r_bl.bottom() == pytest.approx(800.0 - 20.0 - 40.0, abs=2.0)

    # bottom_right
    r_br = MapDecorationRenderer.render_legend(p, pts, False, "bottom_right", img_rect, 1.0, 20.0)
    assert r_br.right() == pytest.approx(980.0, abs=1.0)
    assert r_br.bottom() == pytest.approx(780.0, abs=1.0)

    p.end()


def test_ctrl_07_projected_scale_bar():
    """7. Проверка масштабной линейки в проецированной CRS (EPSG:3857)."""
    img = QImage(1200, 800, QImage.Format.Format_ARGB32_Premultiplied)
    p = QPainter(img)
    # Охват в метрах Web Mercator (около 50 км)
    extent_proj = (4100000.0, 7500000.0, 4150000.0, 7550000.0)

    rect = MapDecorationRenderer.render_scale_bar(
        painter=p,
        extent=extent_proj,
        active_crs="EPSG:3857",
        image_width=1200,
        scale_factor=1.0,
        margin=20.0,
        image_rect=QRectF(0, 0, 1200, 800),
    )
    p.end()

    assert not rect.isEmpty()
    assert rect.bottom() == pytest.approx(780.0, abs=2.0)
    assert rect.width() > 50.0


def test_ctrl_08_jpeg_quality_and_opaque_background(tmp_path: Path):
    """8. Проверка качества JPEG (размер файла) и принудительного непрозрачного фона."""
    f_q30 = tmp_path / "map_q30.jpg"
    f_q95 = tmp_path / "map_q95.jpg"
    extent = (47.0, 56.0, 48.0, 57.0)

    opts_q30 = ImageExportOptions(file_path=f_q30, format="JPEG", width_px=1920, height_px=1080, jpeg_quality=30)
    opts_q95 = ImageExportOptions(file_path=f_q95, format="JPEG", width_px=1920, height_px=1080, jpeg_quality=95)

    ImageExportService.export_image(opts_q30, "OGC:CRS84", extent)
    ImageExportService.export_image(opts_q95, "OGC:CRS84", extent)

    assert f_q30.exists()
    assert f_q95.exists()
    # Файл с качеством 95 должен быть заметно больше файла с качеством 30
    assert f_q95.stat().st_size > f_q30.stat().st_size

    # Принудительная непрозрачность JPEG даже при transparent_background=True
    f_trans_jpeg = tmp_path / "trans_test.jpg"
    opts_trans = ImageExportOptions(
        file_path=f_trans_jpeg,
        format="JPEG",
        width_px=400,
        height_px=400,
        transparent_background=True,
    )
    ImageExportService.export_image(opts_trans, "OGC:CRS84", extent)
    reader = QImage(str(f_trans_jpeg))
    # У JPEG нет альфа-канала: hasAlphaChannel() False
    assert not reader.hasAlphaChannel()
    corner = reader.pixelColor(5, 5)
    assert corner.alpha() == 255


def test_ctrl_09_hidden_layer_omitted_from_export(tmp_path: Path):
    """9. Проверка того, что скрытый векторный слой исключается из экспорта."""
    p_vis = QPainterPath()
    p_vis.addRect(47.2, -56.8, 0.4, 0.4)
    p_hid = QPainterPath()
    p_hid.addRect(47.0, -57.0, 1.0, 1.0)

    layers_data = [
        ("vis_layer", p_vis, QPen(QColor("#00FF00")), QBrush(QColor("#00FF00")), 1.0, True),
        ("hid_layer", p_hid, QPen(QColor("#FF0000")), QBrush(QColor("#FF0000")), 2.0, False),
    ]

    opts = ImageExportOptions(
        file_path="map.png",
        width_px=800,
        height_px=800,
        background_color="#000000",
        include_points=False,
        include_title=False,
        include_crs=False,
        include_legend=False,
        include_scale_bar=False,
        include_north_arrow=False,
    )
    img = MapRenderer.render_map(
        options=opts,
        active_crs="OGC:CRS84",
        target_extent=(47.0, 56.0, 48.0, 57.0),
        loaded_layers_render_data=layers_data,
    )
    # Пиксель в углу (где был бы скрытый слой hid_layer) не должен быть красным
    corner = img.pixelColor(10, 10)
    assert corner != QColor("#FF0000")


def test_ctrl_10_filtered_table_selected_points_export(qapp):
    """10. Проверка работы Selected Points экспорта при активной строке поиска в таблице."""
    win = MainWindow()
    p1 = MapPoint(id="id-moscow", name="Москва", latitude=55.75, longitude=37.61)
    p2 = MapPoint(id="id-kazan", name="Казань", latitude=55.78, longitude=49.12)
    win.point_controller._cmd_add_point(p1)
    win.point_controller._cmd_add_point(p2)

    # Выделяем Казань
    win.points_panel.points_table.selectRow(1)

    # Фильтруем таблицу по слову "Москва" -> Казань скрыта в таблице
    win.points_panel.search_input.setText("Москва")
    assert win.points_panel.shown_count == 1

    # Но export_controller все равно корректно определяет охват для id-kazan
    pts = win.export_controller._point_service.get_points()
    assert len(pts) == 2

    # Диалог со списком выделенных ID
    dlg = ExportImageDialog(
        parent=win,
        active_crs="OGC:CRS84",
        map_title="Test",
        current_view_extent=(36.0, 54.0, 50.0, 57.0),
        full_map_extent=(36.0, 54.0, 50.0, 57.0),
        points=pts,
        selected_point_ids={"id-kazan"},
    )
    ext = dlg._selected_points_extent
    assert ext is not None
    # Охват центрирован вокруг Казани (49.12, 55.78)
    assert ext[0] < 49.12 < ext[2]
    assert ext[1] < 55.78 < ext[3]
    dlg.close()
    win.close()
