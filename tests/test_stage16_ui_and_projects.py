"""Тесты пользовательского интерфейса, диалогов и проектов для GeoTIFF (Этап 16)."""

import json
from pathlib import Path
import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin
from PySide6.QtCore import QMimeData, QPoint, Qt, QUrl
from PySide6.QtGui import QDragEnterEvent, QDropEvent
from PySide6.QtWidgets import QApplication

from rme_mapper.backends.factory import BackendFactory
from rme_mapper.i18n.translations_en import TRANSLATIONS_EN
from rme_mapper.i18n.translations_ru import TRANSLATIONS_RU
from rme_mapper.models.map_point import MapPoint
from rme_mapper.models.map_profile import MapProfile
from rme_mapper.models.project_data import ProjectData, ProjectMapData
from rme_mapper.services.project_service import ProjectService
from rme_mapper.ui.main_window import MainWindow
from rme_mapper.ui.open_map_dialog import OpenMapDialog


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


@pytest.fixture
def sample_geotiff(tmp_path: Path) -> Path:
    """Создание тестового GeoTIFF файла для UI тестов."""
    file_path = tmp_path / "sample_map.tif"
    w, h = 60, 40
    data = np.full((h, w), 150, dtype=np.uint8)
    transform = from_origin(30.0, 60.0, 0.05, 0.05)
    with rasterio.open(
        file_path, "w", driver="GTiff", height=h, width=w, count=1, dtype=np.uint8, crs="EPSG:4326", transform=transform
    ) as dst:
        dst.write(data, 1)
    return file_path


# =============================================================================
# Тесты переводов
# =============================================================================

def test_21_stage16_translations_symmetry():
    """Проверка наличия и симметрии всех строковых ресурсов Этапа 16."""
    keys = [
        "msg.geotiff_no_crs",
        "msg.geotiff_no_georef",
        "msg.geotiff_backend_unavailable",
        "dialog.map.filter_maps",
        "layer.raster",
        "dialog.map.raster_info",
    ]
    for k in keys:
        assert k in TRANSLATIONS_RU, f"Ключ {k} отсутствует в translations_ru"
        assert k in TRANSLATIONS_EN, f"Ключ {k} отсутствует в translations_en"
        assert len(TRANSLATIONS_RU[k]) > 0
        assert len(TRANSLATIONS_EN[k]) > 0


# =============================================================================
# Тесты OpenMapDialog
# =============================================================================

def test_22_open_map_dialog_geotiff_detection(qapp, sample_geotiff: Path):
    """Проверка автоопределения GeoTIFF и формирования профиля в OpenMapDialog."""
    dlg = OpenMapDialog()

    # Симулируем выбор файла GeoTIFF через _set_file_path
    dlg._set_file_path(sample_geotiff)

    assert dlg._is_raster is True
    assert dlg._raster_info is not None
    assert dlg._raster_info["crs"] == "EPSG:4326"
    assert dlg._raster_info["width"] == 60
    assert dlg._raster_info["height"] == 40

    # Профиль создается корректно
    dlg._on_accept_clicked()
    profile = dlg.get_map_profile()
    assert profile is not None
    assert profile.source_type == "geotiff"
    assert profile.crs == "EPSG:4326"
    assert profile.extent is not None
    assert len(profile.layers) == 1
    assert profile.layers[0]["role"] == "raster"
    dlg.close()


# =============================================================================
# Тесты MapController (Загрузка и выгрузка)
# =============================================================================

def test_23_map_controller_load_and_unload_geotiff(qapp, sample_geotiff: Path):
    """Проверка загрузки GeoTIFF через MapController и освобождения ресурсов при выгрузке."""
    win = MainWindow()
    controller = win.map_controller

    controller.load_map(sample_geotiff)

    # Проверяем активную систему координат и профиль
    assert controller.active_crs == "EPSG:4326"
    profile = controller.active_profile
    assert profile is not None
    assert profile.source_type == "geotiff"

    # Холст содержит растровый элемент
    canvas = win.map_canvas
    assert canvas._raster_item is not None
    assert canvas._raster_item.isVisible() is True

    # Панель слоев содержит 1 растровый слой
    layers = win.layers_panel._layers
    assert len(layers) == 1
    assert layers[0].role.value == "raster"

    # Выгрузка карты
    controller.unload_map()
    assert controller.active_profile is None
    assert canvas._raster_item is None
    assert len(win.layers_panel._layers) == 0

    # Файл должен быть разблокирован после unload_map
    # Проверяем попыткой переименования
    new_path = sample_geotiff.with_name("renamed_sample.tif")
    sample_geotiff.rename(new_path)
    assert new_path.exists()
    new_path.rename(sample_geotiff)

    win.close()


# =============================================================================
# Тесты ProjectController и формата *.gpmap
# =============================================================================

def test_24_project_save_and_open_with_geotiff(qapp, tmp_path: Path, sample_geotiff: Path):
    """Проверка сохранения и повторного открытия проекта *.gpmap с растровой картой."""
    proj_file = tmp_path / "test_geotiff_project.gpmap"

    win = MainWindow()
    win.load_map(sample_geotiff)

    # Добавляем точку поверх растра
    pt = win._point_service.add_point("Растровая метка", 60.5, 30.5)
    win.point_controller.add_point_to_table(pt)

    # Сохраняем проект
    save_ok = win.save_project_as(proj_file)
    assert save_ok is True
    assert proj_file.exists()

    # Проверяем структуру JSON
    with open(proj_file, "r", encoding="utf-8") as f:
        data = json.load(f)

    assert data["map"]["source_type"] == "geotiff"
    assert "sample_map.tif" in data["map"]["relative_path"]
    assert len(data["points"]) == 1
    assert data["points"][0]["name"] == "Растровая метка"

    # Закрываем и открываем проект в чистом окне
    win.close()

    win2 = MainWindow()
    open_ok = win2.open_project(proj_file)
    assert open_ok is True

    assert win2.map_controller.active_crs == "EPSG:4326"
    assert win2.map_controller.active_profile.source_type == "geotiff"
    assert len(win2._point_service) == 1
    assert win2.map_canvas._raster_item is not None

    win2.map_controller.unload_map()
    win2.close()


# =============================================================================
# Тесты Drag & Drop в MainWindow
# =============================================================================

def test_25_main_window_drag_and_drop_geotiff(qapp, sample_geotiff: Path):
    """Проверка обработки перетаскивания (Drag & Drop) файла .tif в главное окно."""
    win = MainWindow()

    mime_data = QMimeData()
    mime_data.setUrls([QUrl.fromLocalFile(str(sample_geotiff))])

    # Эмулируем dragEnterEvent
    enter_event = QDragEnterEvent(
        QPoint(100, 100),
        Qt.DropAction.CopyAction,
        mime_data,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    win.dragEnterEvent(enter_event)
    assert enter_event.isAccepted() is True

    # Эмулируем dropEvent
    drop_event = QDropEvent(
        QPoint(100, 100),
        Qt.DropAction.CopyAction,
        mime_data,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    win.dropEvent(drop_event)
    assert drop_event.isAccepted() is True

    # Проверяем, что карта загрузилась
    assert win.map_controller.active_profile is not None
    assert win.map_controller.active_profile.source_type == "geotiff"
    assert win.map_canvas._raster_item is not None

    win.map_controller.unload_map()
    win.close()
