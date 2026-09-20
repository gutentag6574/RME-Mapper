"""Тесты функционала экспорта координатной сетки (Тесты 60–68).

Проверяет:
60: Наличие поля include_grid в ImageExportOptions (по умолчанию False).
61: Наличие чекбокса chk_grid в ExportImageDialog (по умолчанию False).
62: Переключение chk_grid обновляет опции диалога.
63: Отрисовка без сетки (include_grid=False).
64: Отрисовка с сеткой (include_grid=True).
65: Порядок слоев при экспорте (сетка под точками и зонами, над подложкой).
66: Экспорт в PNG с включенной сеткой.
67: Экспорт в JPEG с включенной сеткой.
68: Временные экранные измерения не попадают в экспортируемое изображение.
"""

from pathlib import Path
from unittest.mock import patch
import pytest
from PySide6.QtCore import QPointF
from PySide6.QtGui import QImage

from rme_mapper.exporters.models import ImageExportOptions
from rme_mapper.exporters.map_renderer import MapRenderer
from rme_mapper.models.map_point import MapPoint
from rme_mapper.ui.export_image_dialog import ExportImageDialog
from rme_mapper.ui.main_window import MainWindow


@pytest.fixture
def default_gpkg() -> Path:
    """Путь к тестовому GeoPackage."""
    return Path(__file__).resolve().parent.parent / "maps" / "test_map" / "prepared" / "mari.gpkg"


@pytest.fixture
def sample_point() -> MapPoint:
    return MapPoint(
        id="pt1",
        name="Точка 1",
        latitude=56.63,
        longitude=47.89,
        radius_m=500.0,
        zone_enabled=True,
    )


def test_60_image_export_options_include_grid_default(tmp_path):
    """Тест 60: ImageExportOptions содержит поле include_grid со значением False по умолчанию."""
    options = ImageExportOptions(file_path=tmp_path / "test.png")
    assert hasattr(options, "include_grid")
    assert options.include_grid is False


def test_61_export_image_dialog_has_chk_grid(qapp):
    """Тест 61: ExportImageDialog содержит чекбокс chk_grid, по умолчанию выключенный."""
    dialog = ExportImageDialog(
        parent=None,
        active_crs="OGC:CRS84",
        map_title="Test Map",
        current_view_extent=(47.0, 56.0, 48.0, 57.0),
        full_map_extent=(47.0, 56.0, 48.0, 57.0),
        points=[],
        selected_point_ids=set(),
    )
    assert hasattr(dialog, "chk_grid")
    assert dialog.chk_grid.isChecked() is False
    dialog.close()


def test_62_toggling_chk_grid_updates_options(qapp, tmp_path):
    """Тест 62: Переключение chk_grid в диалоге экспорта обновляет options."""
    dialog = ExportImageDialog(
        parent=None,
        active_crs="OGC:CRS84",
        map_title="Test Map",
        current_view_extent=(47.0, 56.0, 48.0, 57.0),
        full_map_extent=(47.0, 56.0, 48.0, 57.0),
        points=[],
        selected_point_ids=set(),
    )
    out_file = tmp_path / "test.png"
    dialog.path_edit.setText(str(out_file))

    opts_before = dialog.build_export_options()
    assert opts_before.include_grid is False

    dialog.chk_grid.setChecked(True)
    opts_checked = dialog.build_export_options()
    assert opts_checked.include_grid is True

    dialog.chk_grid.setChecked(False)
    opts_unchecked = dialog.build_export_options()
    assert opts_unchecked.include_grid is False
    dialog.close()


def test_63_render_map_without_grid(tmp_path, sample_point):
    """Тест 63: MapRenderer.render_map при include_grid=False не отрисовывает сетку."""
    options = ImageExportOptions(
        file_path=tmp_path / "test.png",
        width_px=400,
        height_px=300,
        include_grid=False,
        include_points=True,
        include_zones=False,
        include_title=False,
        include_scale_bar=False,
        include_north_arrow=False,
        include_legend=False,
    )
    with patch.object(MapRenderer, "_render_grid") as mock_grid:
        img = MapRenderer.render_map(
            options=options,
            active_crs="OGC:CRS84",
            target_extent=(47.0, 56.0, 48.0, 57.0),
            points=[sample_point],
        )
        assert mock_grid.call_count == 0
        assert isinstance(img, QImage)
        assert img.width() == 400
        assert img.height() == 300


def test_64_render_map_with_grid(tmp_path, sample_point):
    """Тест 64: MapRenderer.render_map при include_grid=True отрисовывает сетку."""
    options = ImageExportOptions(
        file_path=tmp_path / "test.png",
        width_px=400,
        height_px=300,
        include_grid=True,
        include_points=True,
        include_zones=False,
        include_title=False,
        include_scale_bar=False,
        include_north_arrow=False,
        include_legend=False,
    )
    with patch.object(MapRenderer, "_render_grid", wraps=MapRenderer._render_grid) as mock_grid:
        img = MapRenderer.render_map(
            options=options,
            active_crs="OGC:CRS84",
            target_extent=(47.0, 56.0, 48.0, 57.0),
            points=[sample_point],
        )
        assert mock_grid.call_count == 1
        assert isinstance(img, QImage)
        assert not img.isNull()


def test_65_grid_render_layer_order(tmp_path, sample_point):
    """Тест 65: Сетка рисуется над базовыми слоями, но под зонами и точками."""
    render_order = []

    orig_render_grid = MapRenderer._render_grid
    orig_render_zones = MapRenderer._render_zones
    orig_render_points = MapRenderer._render_points

    def tracked_grid(*args, **kwargs):
        render_order.append("grid")
        return orig_render_grid(*args, **kwargs)

    def tracked_zones(*args, **kwargs):
        render_order.append("zones")
        return orig_render_zones(*args, **kwargs)

    def tracked_points(*args, **kwargs):
        render_order.append("points")
        return orig_render_points(*args, **kwargs)

    options = ImageExportOptions(
        file_path=tmp_path / "test.png",
        width_px=400,
        height_px=300,
        include_grid=True,
        include_zones=True,
        include_points=True,
        include_title=False,
        include_scale_bar=False,
    )

    with patch.object(MapRenderer, "_render_grid", side_effect=tracked_grid), \
         patch.object(MapRenderer, "_render_zones", side_effect=tracked_zones), \
         patch.object(MapRenderer, "_render_points", side_effect=tracked_points):
        MapRenderer.render_map(
            options=options,
            active_crs="OGC:CRS84",
            target_extent=(47.0, 56.0, 48.0, 57.0),
            points=[sample_point],
        )

    assert "grid" in render_order
    assert "zones" in render_order
    assert "points" in render_order
    grid_idx = render_order.index("grid")
    zones_idx = render_order.index("zones")
    points_idx = render_order.index("points")
    assert grid_idx < zones_idx, "Сетка должна рендериться ДО (под) зонами"
    assert grid_idx < points_idx, "Сетка должна рендериться ДО (под) точками"


def test_66_export_png_with_grid(tmp_path, sample_point):
    """Тест 66: Успешный экспорт в PNG с включенной координатной сеткой."""
    out_file = tmp_path / "test_export_grid.png"
    options = ImageExportOptions(
        file_path=out_file,
        width_px=500,
        height_px=400,
        include_grid=True,
        include_points=True,
        format="PNG",
    )
    img = MapRenderer.render_map(
        options=options,
        active_crs="OGC:CRS84",
        target_extent=(47.0, 56.0, 48.0, 57.0),
        points=[sample_point],
    )
    success = img.save(str(out_file), "PNG")
    assert success is True
    assert out_file.exists()
    assert out_file.stat().st_size > 1000


def test_67_export_jpeg_with_grid(tmp_path, sample_point):
    """Тест 67: Успешный экспорт в JPEG с включенной координатной сеткой."""
    out_file = tmp_path / "test_export_grid.jpg"
    options = ImageExportOptions(
        file_path=out_file,
        width_px=500,
        height_px=400,
        include_grid=True,
        include_points=True,
        format="JPEG",
        jpeg_quality=90,
    )
    img = MapRenderer.render_map(
        options=options,
        active_crs="OGC:CRS84",
        target_extent=(47.0, 56.0, 48.0, 57.0),
        points=[sample_point],
    )
    success = img.save(str(out_file), "JPEG")
    assert success is True
    assert out_file.exists()
    assert out_file.stat().st_size > 1000


def test_68_measurement_overlays_excluded_from_export(qapp, default_gpkg, sample_point, tmp_path):
    """Тест 68: Временные измерения расстояния и площади не попадают в экспортируемый результат."""
    window = MainWindow()
    window.load_map(default_gpkg)
    window.resize(1000, 700)
    window.show()

    # Запускаем измерение расстояния и добавляем 2 точки
    canvas = window.map_canvas
    canvas.start_measurement("measure_distance")
    canvas._add_measurement_vertex((47.5, -56.5))
    canvas._add_measurement_vertex((47.8, -56.8))
    assert canvas.has_measurements() is True

    # Экспорт карты в изображение
    options = ImageExportOptions(
        file_path=tmp_path / "test_meas.png",
        width_px=500,
        height_px=400,
        include_grid=True,
        include_points=True,
    )
    # Рендерим
    img = MapRenderer.render_map(
        options=options,
        active_crs="OGC:CRS84",
        target_extent=(47.0, 56.0, 48.0, 57.0),
        points=[sample_point],
    )
    assert isinstance(img, QImage)
    assert not img.isNull()

    # Проверяем сигнатуру MapRenderer.render_map — там нет параметров измерений
    import inspect
    sig = inspect.signature(MapRenderer.render_map)
    param_names = list(sig.parameters.keys())
    assert "measurement" not in "".join(param_names).lower()

    window.close()
