"""Тесты пользовательского интерфейса, диалога и контроллера экспорта (Этап 15)."""

from pathlib import Path
import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from rme_mapper.i18n import get_language, set_language, tr
from rme_mapper.i18n.translations_en import TRANSLATIONS_EN
from rme_mapper.i18n.translations_ru import TRANSLATIONS_RU
from rme_mapper.models.map_point import MapPoint
from rme_mapper.models.map_profile import MapProfile
from rme_mapper.services.app_settings_service import AppSettingsService
from rme_mapper.ui.controllers.export_controller import ExportController
from rme_mapper.ui.export_image_dialog import ExportImageDialog
from rme_mapper.ui.main_window import MainWindow


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def test_23_translations_symmetry_stage15():
    """Проверка строгой симметрии ключей перевода между RU и EN."""
    stage15_keys = [k for k in TRANSLATIONS_RU if k.startswith("export.") or k.startswith("action.export_")]
    assert len(stage15_keys) > 20

    missing_in_en = [k for k in stage15_keys if k not in TRANSLATIONS_EN]
    assert missing_in_en == [], f"Ключи отсутствуют в translations_en.py: {missing_in_en}"

    missing_in_ru = [k for k in TRANSLATIONS_EN if (k.startswith("export.") or k.startswith("action.export_")) and k not in TRANSLATIONS_RU]
    assert missing_in_ru == [], f"Ключи отсутствуют в translations_ru.py: {missing_in_ru}"


def test_24_main_window_export_action_lifecycle(qapp):
    """Проверка наличия и состояния действия экспорта в главном окне."""
    win = MainWindow()
    assert hasattr(win, "export_map_image_action")
    assert win.export_map_image_action is not None

    # До загрузки карты действие отключено
    assert win.export_map_image_action.isEnabled() is False

    # Эмулируем загрузку карты
    profile = MapProfile(id="test_map", name="Тестовая карта")
    win.map_controller.active_profile = profile
    win._update_map_dependent_actions(True)
    assert win.export_map_image_action.isEnabled() is True

    # Эмулируем выгрузку карты
    win.map_controller.unload_map()
    assert win.export_map_image_action.isEnabled() is False
    win.close()


def test_25_export_dialog_initialization_and_syncing(qapp, tmp_path: Path):
    """Проверка инициализации диалога, синхронизации форматов и пресетов."""
    settings = AppSettingsService(settings=None)
    settings.set_last_export_directory(str(tmp_path))

    pts = [
        MapPoint(id="p1", name="Точка 1", latitude=56.0, longitude=47.0),
        MapPoint(id="p2", name="Точка 2", latitude=56.5, longitude=47.5),
    ]

    dlg = ExportImageDialog(
        parent=None,
        active_crs="OGC:CRS84",
        map_title="Моя Карта",
        current_view_extent=(47.0, 56.0, 48.0, 57.0),
        full_map_extent=(46.0, 55.0, 49.0, 58.0),
        points=pts,
        selected_point_ids={"p1"},
        settings_service=settings,
    )

    # Проверка начальных значений
    assert dlg.spin_width.value() == 1920
    assert dlg.spin_height.value() == 1080
    assert dlg.title_edit.text() == "Моя Карта"
    assert dlg.fmt_combo.currentData() == "PNG"

    # Смена формата на JPEG -> расширение в пути меняется на .jpg
    idx_jpeg = dlg.fmt_combo.findData("JPEG")
    dlg.fmt_combo.setCurrentIndex(idx_jpeg)
    assert dlg.path_edit.text().endswith(".jpg")
    assert dlg.lbl_quality.isEnabled() is True

    # Смена формата обратно на PNG -> расширение в пути меняется на .png
    idx_png = dlg.fmt_combo.findData("PNG")
    dlg.fmt_combo.setCurrentIndex(idx_png)
    assert dlg.path_edit.text().endswith(".png")

    # Ручной ввод .jpg в поле пути синхронизирует формат
    dlg.path_edit.setText(str(tmp_path / "custom.jpg"))
    assert dlg.fmt_combo.currentData() == "JPEG"

    # Пресеты
    idx_4k = dlg.preset_combo.findData("3840x2160")
    assert idx_4k >= 0
    dlg.preset_combo.setCurrentIndex(idx_4k)
    assert dlg.spin_width.value() == 3840
    assert dlg.spin_height.value() == 2160

    dlg.close()


def test_26_export_dialog_extent_mode_disabling(qapp):
    """Проверка отключения режимов при отсутствии точек или выделения."""
    settings = AppSettingsService(settings=None)

    # Диалог без точек и без выделения
    dlg_no_pts = ExportImageDialog(
        parent=None,
        active_crs="OGC:CRS84",
        map_title="Пустая Карта",
        current_view_extent=(47.0, 56.0, 48.0, 57.0),
        full_map_extent=None,
        points=[],
        selected_point_ids=set(),
        settings_service=settings,
    )

    idx_all = dlg_no_pts.extent_combo.findData("all_points")
    assert not (dlg_no_pts.extent_combo.model().flags(dlg_no_pts.extent_combo.model().index(idx_all, 0)) & Qt.ItemFlag.ItemIsEnabled)

    idx_sel = dlg_no_pts.extent_combo.findData("selected_points")
    assert not (dlg_no_pts.extent_combo.model().flags(dlg_no_pts.extent_combo.model().index(idx_sel, 0)) & Qt.ItemFlag.ItemIsEnabled)

    dlg_no_pts.close()


def test_27_export_extent_does_not_change_canvas_zoom(qapp):
    """Гарантия того, что экспорт карты не меняет зум и матрицу трансформации MapCanvas."""
    win = MainWindow()
    # Эмулируем загруженную карту
    win.map_controller.active_profile = MapProfile(id="test", name="Test", extent={"xmin": 47.0, "ymin": 56.0, "xmax": 48.0, "ymax": 57.0})
    initial_transform = win.map_canvas.transform()

    extent = win.export_controller.get_full_map_extent()
    assert extent == (47.0, 56.0, 48.0, 57.0)

    # Проверяем, что матрица трансформации холста осталась строго неизменной
    current_transform = win.map_canvas.transform()
    assert current_transform == initial_transform
    win.close()
