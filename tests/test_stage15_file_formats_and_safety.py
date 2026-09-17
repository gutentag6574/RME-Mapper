"""Тесты форматов файлов, качества JPEG, атомарной записи и безопасности (Этап 15)."""

import os
from pathlib import Path
import pytest
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication

from rme_mapper.exporters.image_export_service import ImageExportService
from rme_mapper.exporters.models import ImageExportOptions
from rme_mapper.models.map_point import MapPoint


@pytest.fixture(scope="module", autouse=True)
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def test_17_png_file_export(tmp_path: Path):
    target = tmp_path / "map_out.png"
    opts = ImageExportOptions(
        file_path=target,
        format="PNG",
        width_px=800,
        height_px=600,
    )
    saved_path = ImageExportService.export_image(
        options=opts,
        active_crs="OGC:CRS84",
        target_extent=(47.0, 56.0, 48.0, 57.0),
    )
    assert saved_path == target
    assert target.exists()
    assert target.stat().st_size > 0

    # Проверяем, что созданный файл валиден для Qt
    loaded = QImage(str(target))
    assert not loaded.isNull()
    assert loaded.width() == 800
    assert loaded.height() == 600


def test_18_jpeg_file_export_and_quality(tmp_path: Path):
    target_q90 = tmp_path / "map_q90.jpg"
    opts_q90 = ImageExportOptions(
        file_path=target_q90,
        format="JPEG",
        width_px=1000,
        height_px=800,
        jpeg_quality=90,
    )
    ImageExportService.export_image(
        options=opts_q90,
        active_crs="OGC:CRS84",
        target_extent=(47.0, 56.0, 48.0, 57.0),
    )
    assert target_q90.exists()
    size_q90 = target_q90.stat().st_size

    target_q30 = tmp_path / "map_q30.jpg"
    opts_q30 = ImageExportOptions(
        file_path=target_q30,
        format="JPEG",
        width_px=1000,
        height_px=800,
        jpeg_quality=30,
    )
    ImageExportService.export_image(
        options=opts_q30,
        active_crs="OGC:CRS84",
        target_extent=(47.0, 56.0, 48.0, 57.0),
    )
    assert target_q30.exists()
    size_q30 = target_q30.stat().st_size

    # Файл с качеством 90 должен быть тяжелее файла с качеством 30
    assert size_q90 > size_q30


def test_19_jpeg_forces_opaque_background(tmp_path: Path):
    target = tmp_path / "map_jpeg_opaque.jpg"
    opts = ImageExportOptions(
        file_path=target,
        format="JPEG",
        width_px=600,
        height_px=400,
        transparent_background=True,  # Даже если запрошена прозрачность
    )
    ImageExportService.export_image(
        options=opts,
        active_crs="OGC:CRS84",
        target_extent=(47.0, 56.0, 48.0, 57.0),
    )
    assert target.exists()
    loaded = QImage(str(target))
    assert not loaded.hasAlphaChannel()


def test_20_atomic_overwrite_preserves_original_on_error(tmp_path: Path):
    target = tmp_path / "important_map.png"
    target.write_text("original content")

    # Передаем заведомо недопустимые размеры, которые вызовут ошибку валидации
    bad_opts = ImageExportOptions(
        file_path=target,
        format="PNG",
        width_px=50,  # Меньше минимума 256
        height_px=600,
    )

    with pytest.raises(ValueError):
        ImageExportService.export_image(
            options=bad_opts,
            active_crs="OGC:CRS84",
            target_extent=(47.0, 56.0, 48.0, 57.0),
        )

    # Исходный файл должен остаться нетронутым!
    assert target.exists()
    assert target.read_text() == "original content"


def test_21_temp_file_cleanup_on_failure(tmp_path: Path, monkeypatch):
    target = tmp_path / "cleanup_test.png"
    opts = ImageExportOptions(
        file_path=target,
        format="PNG",
        width_px=800,
        height_px=600,
    )

    # Симулируем ошибку диска при атомарной замене
    def fake_replace(src, dst):
        # Убеждаемся, что временный файл существовал в момент ошибки
        assert Path(src).exists()
        raise OSError("Simulated disk I/O error during atomic rename")

    monkeypatch.setattr(os, "replace", fake_replace)

    with pytest.raises(OSError):
        ImageExportService.export_image(
            options=opts,
            active_crs="OGC:CRS84",
            target_extent=(47.0, 56.0, 48.0, 57.0),
        )

    current_files = list(tmp_path.iterdir())
    # Никаких оставшихся .tmp файлов быть не должно - блок except удалил его
    tmp_files = [f for f in current_files if f.name.startswith(".tmp_")]
    assert len(tmp_files) == 0
    assert not target.exists()


def test_22_read_only_guarantee(tmp_path: Path):
    pt = MapPoint(id="p1", name="Тест", latitude=56.0, longitude=47.0)
    original_name = pt.name
    original_lat = pt.latitude
    original_lon = pt.longitude

    opts = ImageExportOptions(file_path=tmp_path / "dummy.png", width_px=800, height_px=600)
    img = ImageExportService.export_image(
        options=opts,
        active_crs="OGC:CRS84",
        target_extent=(46.0, 55.0, 48.0, 57.0),
        points=[pt],
    )
    assert pt.name == original_name
    assert pt.latitude == original_lat
    assert pt.longitude == original_lon


def test_30_unwritable_directory_handled(tmp_path: Path, monkeypatch):
    target = tmp_path / "protected_dir" / "out.png"
    # Симулируем отсутствие прав на запись
    monkeypatch.setattr(os, "access", lambda path, mode: False)

    opts = ImageExportOptions(file_path=target, width_px=800, height_px=600)
    with pytest.raises(PermissionError) as exc_info:
        ImageExportService.export_image(
            options=opts,
            active_crs="OGC:CRS84",
            target_extent=(47.0, 56.0, 48.0, 57.0),
        )
    assert "недоступен для записи" in str(exc_info.value)


def test_31_undo_stack_and_recovery_unchanged():
    from rme_mapper.services.undo_manager import UndoManager
    from rme_mapper.services.project_service import ProjectService
    from rme_mapper.ui.main_window import MainWindow

    win = MainWindow()
    undo_mgr = win.point_controller.undo_manager
    initial_undo_count = len(undo_mgr._undo_stack)
    initial_redo_count = len(undo_mgr._redo_stack)

    # Запускаем сбор опций
    opts = win.export_controller.get_current_view_extent()

    assert len(undo_mgr._undo_stack) == initial_undo_count
    assert len(undo_mgr._redo_stack) == initial_redo_count
    assert win.project_controller.is_modified is False
    win.close()


def test_32_scale_bar_projected_crs():
    from PySide6.QtCore import QRectF
    from PySide6.QtGui import QColor, QImage, QPainter
    from rme_mapper.exporters.decorations import MapDecorationRenderer

    img = QImage(1920, 1080, QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(QColor("#FFFFFF"))
    p = QPainter(img)

    # Охват в спроецированной CRS EPSG:3857 (метры)
    extent_3857 = (5200000.0, 7500000.0, 5350000.0, 7600000.0)
    rect = MapDecorationRenderer.render_scale_bar(
        painter=p,
        extent=extent_3857,
        active_crs="EPSG:3857",
        image_width=1920,
        scale_factor=1.0,
        margin=24.0,
        image_rect=QRectF(0, 0, 1920, 1080),
    )
    p.end()
    assert not rect.isEmpty()


def test_33_all_extent_modes_and_single_point():
    from rme_mapper.ui.export_image_dialog import ExportImageDialog
    from rme_mapper.services.app_settings_service import AppSettingsService

    p1 = MapPoint(id="pt_single", name="Одиночная", latitude=56.5, longitude=47.5, radius_m=400.0, zone_enabled=True)
    dlg = ExportImageDialog(
        parent=None,
        active_crs="OGC:CRS84",
        map_title="Map",
        current_view_extent=(47.0, 56.0, 48.0, 57.0),
        full_map_extent=(46.0, 55.0, 49.0, 58.0),
        points=[p1],
        selected_point_ids={"pt_single"},
        settings_service=AppSettingsService(settings=None),
    )

    # Одиночная точка должна сформировать валидный охват вокруг себя
    ext_sel = dlg._selected_points_extent
    assert ext_sel is not None
    assert ext_sel[0] < 47.5 < ext_sel[2]
    assert ext_sel[1] < 56.5 < ext_sel[3]

    dlg.close()


def test_34_settings_persistence():
    from rme_mapper.services.app_settings_service import AppSettingsService

    svc = AppSettingsService(settings=None)
    svc.set_last_export_directory("D:/ExportTest")
    assert os.path.normpath(svc.get_last_export_directory()) == os.path.normpath("D:/ExportTest")

    svc.set_export_format("JPEG")
    assert svc.get_export_format() == "JPEG"

    svc.set_export_width(2560)
    assert svc.get_export_width() == 2560

    svc.set_export_height(1440)
    assert svc.get_export_height() == 1440

    svc.set_export_extent_mode("all_points")
    assert svc.get_export_extent_mode() == "all_points"

    svc.set_export_jpeg_quality(85)
    assert svc.get_export_jpeg_quality() == 85

    svc.set_export_lock_aspect(False)
    assert svc.get_export_lock_aspect() is False


def test_35_search_filter_does_not_remove_export_points(qapp):
    from rme_mapper.ui.main_window import MainWindow

    win = MainWindow()
    # Добавляем 2 точки
    p1 = MapPoint(id="p1", name="Москва", latitude=55.75, longitude=37.61)
    p2 = MapPoint(id="p2", name="Казань", latitude=55.78, longitude=49.12)
    win.point_controller._cmd_add_point(p1)
    win.point_controller._cmd_add_point(p2)

    # Фильтруем таблицу поиском по "Москва"
    win.points_panel.search_input.setText("Москва")
    assert win.points_panel.shown_count == 1
    assert win.points_panel.total_count == 2

    # Экспортный контроллер видит все точки сервиса
    all_pts = win.export_controller._point_service.get_points()
    assert len(all_pts) == 2
    win.close()
