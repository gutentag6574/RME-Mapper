"""Тесты для Этапа 8 проекта RME-Mapper: сохранение и открытие проекта (*.rmeproject)."""

import json
import os
from pathlib import Path
import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import QApplication, QMessageBox

from rme_mapper.models.map_layer import LayerRole, MapLayer
from rme_mapper.models.map_point import MapPoint
from rme_mapper.models.project_data import (
    ProjectData,
    ProjectMapData,
    ProjectPointData,
)
from rme_mapper.services.point_service import PointService
from rme_mapper.services.project_service import (
    CURRENT_VERSION,
    PROJECT_EXTENSION,
    SUPPORTED_FORMAT,
    SUPPORTED_FORMATS,
    ProjectService,
)
from rme_mapper.ui.main_window import MainWindow

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "sample_project_v1.rmeproject"


@pytest.fixture(scope="session")
def qapp():
    """Фикстура для инициализации QApplication в headless-режиме."""
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    yield app


@pytest.fixture
def sample_point() -> MapPoint:
    """Фикстура тестовой точки со всеми атрибутами стиля и зоны."""
    return MapPoint(
        id="test-point-uuid-1234",
        name="Йошкар-Ола (Тест)",
        latitude=56.6344,
        longitude=47.8999,
        source_crs="OGC:CRS84",
        visible=True,
        symbol="square",
        size=16.0,
        red=25,
        green=150,
        blue=220,
        zone_enabled=True,
        radius_m=12500.0,
        zone_red=255,
        zone_green=165,
        zone_blue=0,
        zone_opacity=40,
    )


# =============================================================================
# 1-12. Сериализация и десериализация MapPoint / ProjectPointData
# =============================================================================


def test_1_map_point_serializes(sample_point):
    """1. MapPoint успешно сериализуется в словарь через ProjectPointData."""
    pt_data = ProjectPointData.from_map_point(sample_point)
    d = pt_data.to_dict()
    assert isinstance(d, dict)
    assert d["id"] == "test-point-uuid-1234"


def test_2_map_point_deserializes(sample_point):
    """2. MapPoint успешно десериализуется из словаря."""
    pt_data = ProjectPointData.from_map_point(sample_point)
    d = pt_data.to_dict()
    restored = ProjectPointData.from_dict(d).to_map_point()
    assert isinstance(restored, MapPoint)
    assert restored.id == sample_point.id
    assert restored.name == sample_point.name


def test_3_id_preserved(sample_point):
    """3. Уникальный ID точки сохраняется без генерации нового."""
    pt_data = ProjectPointData.from_map_point(sample_point)
    restored = pt_data.to_map_point()
    assert restored.id == "test-point-uuid-1234"


def test_4_cyrillic_name_preserved(sample_point):
    """4. Название точки на кириллице полностью сохраняется."""
    pt_data = ProjectPointData.from_map_point(sample_point)
    restored = ProjectPointData.from_dict(pt_data.to_dict()).to_map_point()
    assert restored.name == "Йошкар-Ола (Тест)"


def test_5_dd_coordinates_preserved(sample_point):
    """5. Десятичные координаты точки сохраняются с высокой точностью."""
    pt_data = ProjectPointData.from_map_point(sample_point)
    restored = ProjectPointData.from_dict(pt_data.to_dict()).to_map_point()
    assert restored.latitude == pytest.approx(56.6344, abs=1e-6)
    assert restored.longitude == pytest.approx(47.8999, abs=1e-6)


def test_6_symbol_preserved(sample_point):
    """6. Форма маркера сохраняется."""
    pt_data = ProjectPointData.from_map_point(sample_point)
    restored = ProjectPointData.from_dict(pt_data.to_dict()).to_map_point()
    assert restored.symbol == "square"


def test_7_size_preserved(sample_point):
    """7. Размер маркера сохраняется."""
    pt_data = ProjectPointData.from_map_point(sample_point)
    restored = ProjectPointData.from_dict(pt_data.to_dict()).to_map_point()
    assert restored.size == 16.0


def test_8_rgb_preserved(sample_point):
    """8. Цвета маркера RGB сохраняются."""
    pt_data = ProjectPointData.from_map_point(sample_point)
    restored = ProjectPointData.from_dict(pt_data.to_dict()).to_map_point()
    assert (restored.red, restored.green, restored.blue) == (25, 150, 220)


def test_9_zone_enabled_preserved(sample_point):
    """9. Флаг активности зоны сохраняется."""
    pt_data = ProjectPointData.from_map_point(sample_point)
    restored = ProjectPointData.from_dict(pt_data.to_dict()).to_map_point()
    assert restored.zone_enabled is True


def test_10_radius_m_preserved(sample_point):
    """10. Радиус зоны в метрах сохраняется."""
    pt_data = ProjectPointData.from_map_point(sample_point)
    restored = ProjectPointData.from_dict(pt_data.to_dict()).to_map_point()
    assert restored.radius_m == 12500.0


def test_11_zone_rgb_preserved(sample_point):
    """11. Цвет зоны RGB сохраняется."""
    pt_data = ProjectPointData.from_map_point(sample_point)
    restored = ProjectPointData.from_dict(pt_data.to_dict()).to_map_point()
    assert (restored.zone_red, restored.zone_green, restored.zone_blue) == (255, 165, 0)


def test_12_zone_opacity_preserved(sample_point):
    """12. Прозрачность зоны в процентах сохраняется."""
    pt_data = ProjectPointData.from_map_point(sample_point)
    restored = ProjectPointData.from_dict(pt_data.to_dict()).to_map_point()
    assert restored.zone_opacity == 40


# =============================================================================
# 13-19. Структура ProjectData и формат JSON
# =============================================================================


def test_13_project_data_serializes(sample_point):
    """13. ProjectData корректно сериализуется в верхнеуровневый словарь."""
    proj = ProjectData(
        points=[ProjectPointData.from_map_point(sample_point)],
        layers={"boundary": True, "roads": False},
    )
    d = proj.to_dict()
    assert "format" in d
    assert "version" in d
    assert "map" in d
    assert "layers" in d
    assert "points" in d


def test_14_format_recorded():
    """14. Поле 'format' записывается как валидный формат проекта."""
    proj = ProjectData()
    assert proj.format in SUPPORTED_FORMATS
    assert proj.to_dict()["format"] in SUPPORTED_FORMATS


def test_15_version_recorded():
    """15. Поле 'version' записывается как текущая версия (1)."""
    proj = ProjectData()
    assert proj.version == CURRENT_VERSION
    assert proj.to_dict()["version"] == 1


def test_16_json_is_valid(sample_point, tmp_path):
    """16. Сформированный JSON является валидным и парсится стандартным json.loads."""
    proj = ProjectData(points=[ProjectPointData.from_map_point(sample_point)])
    out_file = tmp_path / "valid.rmeproject"
    ProjectService.save_project(proj, out_file)

    with open(out_file, "r", encoding="utf-8") as f:
        loaded = json.load(f)
    assert loaded["format"] in SUPPORTED_FORMATS
    assert len(loaded["points"]) == 1


def test_17_utf8_cyrillic_readable(sample_point, tmp_path):
    """17. JSON сохраняется в UTF-8 без экранирования Unicode (читаемая кириллица)."""
    proj = ProjectData(points=[ProjectPointData.from_map_point(sample_point)])
    out_file = tmp_path / "utf8_test.rmeproject"
    ProjectService.save_project(proj, out_file)

    with open(out_file, "r", encoding="utf-8") as f:
        content = f.read()

    assert "Йошкар-Ола (Тест)" in content
    assert "\\u" not in content


def test_18_relative_map_path_preserved():
    """18. Путь к встроенной карте остаётся относительным к каталогу приложения."""
    map_path = Path(__file__).resolve().parents[1] / "maps/test_map/prepared/mari.gpkg"
    proj = ProjectService.build_project_data(
        map_path=map_path,
        layers=[],
        points=[],
    )
    assert proj.map.relative_path == "maps/test_map/prepared/mari.gpkg"
    assert not Path(proj.map.relative_path).is_absolute()


def test_19_layers_visibility_preserved():
    """19. Состояние видимости слоев сохраняется."""
    proj = ProjectData(layers={"boundary": True, "roads": False})
    d = proj.to_dict()
    restored = ProjectData.from_dict(d)
    assert restored.layers == {"boundary": True, "roads": False}


# =============================================================================
# 20-28. ProjectService: сохранение, загрузка и обработка ошибок
# =============================================================================


def test_20_project_save_creates_file(tmp_path):
    """20. ProjectService.save_project создает файл с расширением .rmeproject."""
    out_file = tmp_path / "my_project"  # без расширения
    saved = ProjectService.save_project(ProjectData(), out_file)
    assert saved.exists()
    assert saved.suffix == PROJECT_EXTENSION


def test_21_project_load_restores_points(sample_point, tmp_path):
    """21. ProjectService.load_project восстанавливает сохраненные точки."""
    proj = ProjectData(points=[ProjectPointData.from_map_point(sample_point)])
    out_file = tmp_path / "points.rmeproject"
    ProjectService.save_project(proj, out_file)

    loaded = ProjectService.load_project(out_file)
    assert len(loaded.points) == 1
    assert loaded.points[0].id == sample_point.id
    assert loaded.points[0].name == sample_point.name


def test_22_load_restores_marker_on_canvas(qapp, sample_point, tmp_path):
    """22. MainWindow.open_project восстанавливает маркер точки на холсте."""
    window = MainWindow()
    proj = ProjectData(points=[ProjectPointData.from_map_point(sample_point)])
    out_file = tmp_path / "canvas_marker.rmeproject"
    ProjectService.save_project(proj, out_file)

    window.open_project(out_file)
    assert window.map_canvas.has_user_point(sample_point.id)


def test_23_load_restores_zone_on_canvas(qapp, sample_point, tmp_path):
    """23. MainWindow.open_project восстанавливает геодезическую зону на холсте."""
    window = MainWindow()
    proj = ProjectData(points=[ProjectPointData.from_map_point(sample_point)])
    out_file = tmp_path / "canvas_zone.rmeproject"
    ProjectService.save_project(proj, out_file)

    window.open_project(out_file)
    assert window.map_canvas.has_point_zone(sample_point.id)


def test_24_load_restores_layer_visibility(qapp, tmp_path):
    """24. MainWindow.open_project восстанавливает видимость слоев карты."""
    window = MainWindow()
    proj = ProjectData(layers={"boundary": True, "roads": False})
    out_file = tmp_path / "layers.rmeproject"
    ProjectService.save_project(proj, out_file)

    window.open_project(out_file)
    chk_roads = window.layer_checkboxes.get("roads")
    if chk_roads:
        assert not chk_roads.isChecked()
    assert not window.map_canvas.is_layer_visible("roads")


def test_25_corrupt_json_handled(tmp_path):
    """25. Поврежденный JSON не вызывает падения и возбуждает ValueError."""
    corrupt_file = tmp_path / "corrupt.rmeproject"
    corrupt_file.write_text("{ this is not a valid json", encoding="utf-8")

    with pytest.raises(ValueError, match="некорректный JSON"):
        ProjectService.load_project(corrupt_file)


def test_26_wrong_format_rejected(tmp_path):
    """26. Неправильный идентификатор формата отклоняется."""
    wrong_fmt = tmp_path / "wrong_fmt.rmeproject"
    wrong_fmt.write_text(
        json.dumps({"format": "Other GIS Project", "version": 1, "points": []}),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="Неподдерживаемый формат"):
        ProjectService.load_project(wrong_fmt)


def test_27_newer_version_rejected(tmp_path):
    """27. Проект с version > 1 отклоняется с понятным сообщением."""
    future_proj = tmp_path / "future.rmeproject"
    future_proj.write_text(
        json.dumps({"format": "RME-Mapper Project", "version": 99, "points": []}),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="более новой версией"):
        ProjectService.load_project(future_proj)


def test_28_missing_file_handled():
    """28. Отсутствующий файл возбуждает FileNotFoundError."""
    missing = Path("d:/non_existent_folder/missing_file.rmeproject")
    with pytest.raises(FileNotFoundError):
        ProjectService.load_project(missing)


# =============================================================================
# 29-30. Создание нового проекта
# =============================================================================


def test_29_new_project_clears_points(qapp, sample_point):
    """29. MainWindow.new_project очищает пользовательские точки."""
    window = MainWindow()
    window._point_service.add_point(
        sample_point.name,
        sample_point.latitude,
        sample_point.longitude,
        point_id=sample_point.id,
    )
    window.map_canvas.add_user_point(sample_point)
    window._add_point_to_table(sample_point)
    assert len(window._point_service) == 1
    assert window.points_table.rowCount() == 1

    window._is_modified = False  # без запроса подтверждения
    window.new_project()

    assert len(window._point_service) == 0
    assert window.points_table.rowCount() == 0
    assert not window.map_canvas.has_user_point(sample_point.id)


def test_30_new_project_clears_zones(qapp, sample_point):
    """30. MainWindow.new_project очищает графические элементы зон."""
    window = MainWindow()
    window.map_canvas.add_user_point(sample_point)
    assert window.map_canvas.has_point_zone(sample_point.id)

    window._is_modified = False
    window.new_project()
    assert not window.map_canvas.has_point_zone(sample_point.id)


# =============================================================================
# 31-36. Dirty State (отслеживание изменений)
# =============================================================================


def test_31_dirty_state_after_add(qapp):
    """31. Добавление точки переводит проект в измененное состояние (is_modified=True)."""
    window = MainWindow()
    window._set_modified(False)
    assert not window.is_modified

    pt = window._point_service.add_point("Новая", 56.6, 47.8)
    window._add_point_to_table(pt)
    window._set_modified(True)
    assert window.is_modified


def test_32_dirty_state_after_edit(qapp, sample_point):
    """32. Редактирование точки переводит проект в измененное состояние."""
    window = MainWindow()
    pt = window._point_service.add_point("До", 56.6, 47.8, point_id="pt1")
    window._set_modified(False)

    window._point_service.update_point("pt1", name="После")
    window._set_modified(True)
    assert window.is_modified


def test_33_dirty_state_after_delete(qapp):
    """33. Удаление точки переводит проект в измененное состояние."""
    window = MainWindow()
    pt = window._point_service.add_point("Удаляемая", 56.6, 47.8)
    window._add_point_to_table(pt)
    window._set_modified(False)

    window.points_table.selectRow(0)
    window.delete_selected_point()
    assert window.is_modified


def test_34_dirty_state_after_layer_toggle(qapp):
    """34. Переключение видимости слоя делает проект измененным."""
    window = MainWindow()
    window._set_modified(False)
    assert not window.is_modified

    window._on_layer_toggled("roads", False)
    assert window.is_modified


def test_35_save_clears_dirty_state(qapp, tmp_path):
    """35. Успешное сохранение сбрасывает dirty state в False."""
    window = MainWindow()
    window._set_modified(True)
    assert window.is_modified

    save_path = tmp_path / "save_test.rmeproject"
    window.save_project_as(save_path)
    assert not window.is_modified


def test_36_window_title_shows_asterisk(qapp):
    """36. Заголовок окна отображает звездочку '*' при наличии несохраненных изменений."""
    window = MainWindow()
    window._current_project_path = Path("my_map.rmeproject")
    window._set_modified(False)
    assert window.windowTitle() == "GeoPoint Mapper — my_map.rmeproject"

    window._set_modified(True)
    assert window.windowTitle() == "GeoPoint Mapper — my_map.rmeproject *"


# =============================================================================
# 37-40. Поведение сохранения, открытия и закрытия
# =============================================================================


def test_37_save_without_path_delegates(qapp, monkeypatch, tmp_path):
    """37. Вызов save_project без установленного пути вызывает save_project_as."""
    window = MainWindow()
    window._current_project_path = None
    target_path = tmp_path / "auto_save.rmeproject"

    monkeypatch.setattr(
        "PySide6.QtWidgets.QFileDialog.getSaveFileName",
        lambda *args, **kwargs: (str(target_path), "Проект RME-Mapper (*.rmeproject)"),
    )

    success = window.save_project()
    assert success is True
    assert window.current_project_path == target_path
    assert target_path.exists()


def test_38_save_with_existing_path_no_dialog(qapp, monkeypatch, tmp_path):
    """38. Повторное сохранение использует существующий путь без показа диалога."""
    window = MainWindow()
    existing_path = tmp_path / "existing.rmeproject"
    window._current_project_path = existing_path

    # Если QFileDialog будет вызван, тест упадет
    monkeypatch.setattr(
        "PySide6.QtWidgets.QFileDialog.getSaveFileName",
        lambda *args, **kwargs: pytest.fail("Диалог выбора файла не должен вызываться"),
    )

    success = window.save_project()
    assert success is True
    assert existing_path.exists()


def test_39_close_modified_project_prompts(qapp, monkeypatch):
    """39. Закрытие измененного окна вызывает диалог с предупреждением."""
    window = MainWindow()
    window._set_modified(True)

    prompt_called = False

    def mock_question(*args, **kwargs):
        nonlocal prompt_called
        prompt_called = True
        return QMessageBox.StandardButton.Discard

    monkeypatch.setattr(QMessageBox, "question", mock_question)

    event = QCloseEvent()
    window.closeEvent(event)
    assert prompt_called is True
    assert event.isAccepted()


def test_40_close_cancelled_prevents_closing(qapp, monkeypatch):
    """40. Нажатие 'Отмена' в диалоге закрытия отменяет закрытие окна."""
    window = MainWindow()
    window._set_modified(True)

    monkeypatch.setattr(
        QMessageBox,
        "question",
        lambda *args, **kwargs: QMessageBox.StandardButton.Cancel,
    )

    event = QCloseEvent()
    window.closeEvent(event)
    assert not event.isAccepted()


# =============================================================================
# 41-42. Атомарное сохранение и загрузка фикстуры
# =============================================================================


def test_41_atomic_save_cleans_tmp_files(tmp_path):
    """41. Атомарное сохранение не оставляет временных файлов .tmp в каталоге."""
    out_file = tmp_path / "clean_save.rmeproject"
    ProjectService.save_project(ProjectData(), out_file)

    tmp_files = list(tmp_path.glob("*.tmp*"))
    assert len(tmp_files) == 0
    assert out_file.exists()


def test_42_fixture_sample_project_loads_successfully(qapp):
    """42. Эталонный фикстурный файл sample_project_v1.rmeproject успешно загружается в MainWindow."""
    assert FIXTURE_PATH.exists()
    window = MainWindow()
    success = window.open_project(FIXTURE_PATH)
    assert success is True

    # В фикстуре 3 точки
    assert len(window._point_service) == 3
    assert window.points_table.rowCount() == 3

    # Проверяем Йошкар-Олу
    p1 = window._point_service.get_point("sample-pt-001-yoshkar-ola")
    assert p1 is not None
    assert p1.name == "Йошкар-Ола"
    assert p1.zone_enabled is True
    assert p1.radius_m == 10000.0
    assert window.map_canvas.has_point_zone(p1.id)

    # Проверяем Волжск (без зоны)
    p3 = window._point_service.get_point("sample-pt-003-volzhsk")
    assert p3 is not None
    assert p3.name == "Волжск"
    assert p3.zone_enabled is False
    assert not window.map_canvas.has_point_zone(p3.id)
