"""End-to-end checks for the optional UX workspace, clipboard and portable projects."""
import json
from pathlib import Path
from unittest.mock import patch
import zipfile

import pytest
from PIL import Image
from PySide6.QtWidgets import QDialogButtonBox

from rme_mapper.models.map_point import MapPoint
from rme_mapper.models.map_profile import MapProfile
from rme_mapper.models.project_data import ProjectData, ProjectMapData
from rme_mapper.services.georeference_service import GeoreferenceService
from rme_mapper.services.project_bundle_service import create_project_bundle
from rme_mapper.services.project_service import ProjectService
from rme_mapper.ui.clipboard_coordinates_dialog import ClipboardCoordinatesDialog, parse_clipboard_coordinates
from rme_mapper.ui.georeference_dialog import GeoreferenceDialog
from rme_mapper.ui.main_window import MainWindow


@pytest.fixture
def image(tmp_path):
    path = tmp_path / "карта.png"
    Image.new("RGBA", (100, 100), (255, 0, 0, 255)).save(path)
    GeoreferenceService.export_world_file(path, (2, 0, 500000, 0, -2, 6000000), "EPSG:32639")
    return path


@pytest.fixture
def window(qapp, image):
    profile = MapProfile(id="test", name="Map", source_type="georeferenced_image", source_path=str(image), crs="EPSG:32639", affine_transform=[2, 0, 500000, 0, -2, 6000000])
    w = MainWindow(map_profile=profile)
    w.show()
    qapp.processEvents()
    yield w
    w.project_controller.set_modified(False)
    w.close()


def test_panels_switch_and_properties_follow_selection(window, qapp):
    assert window.points_panel.parent() is window.workspace_splitter
    assert window.right_panel.isHidden()
    point = MapPoint("A", 54.1, 51.1)
    window.point_controller._cmd_add_points([point])
    window.points_panel.select_point_ids([point.id])
    qapp.processEvents()
    assert not window.right_panel.isHidden()
    window.points_panel.points_table.clearSelection()
    assert window.right_panel.isHidden()
    assert window.toggle_properties_action.isChecked()
    window.set_points_bottom(False)
    assert window.points_panel.parent() is window.left_panel
    window.set_points_bottom(True)
    assert window.points_panel.parent() is window.workspace_splitter
    window.set_auto_properties(False)
    assert not window.right_panel.isHidden()


def test_layout_preferences_restore(window, qapp):
    window.set_points_bottom(False)
    window.auto_properties_action.setChecked(False)
    window.navigation_tabs.setCurrentIndex(1)
    other = MainWindow()
    other.show()
    qapp.processEvents()
    assert other.points_panel.parent() is other.left_panel
    assert not other.auto_properties_action.isChecked()
    assert other.navigation_tabs.currentIndex() == 1
    other.close()


def test_clipboard_decimal_comma_utm_and_headers():
    points, rows = parse_clipboard_coordinates("X\tY\tИмя\n500000,0\t6000000,0\tТочка", "EPSG:32639", 0, 1, 2, True)
    assert rows[0][-1] == "OK"
    assert points[0].longitude == pytest.approx(51)
    assert 54 < points[0].latitude < 55
    assert points[0].name == "Точка"


@pytest.mark.parametrize("text", ["NaN\t55", "1\t", "200\t100", "1\tbad"])
def test_clipboard_rejects_bad_rows(text):
    points, rows = parse_clipboard_coordinates(text, "EPSG:4326", 0, 1)
    assert not points
    assert rows[0][-1] != "OK"


def test_clipboard_explicit_crs_and_no_silent_skips(qapp):
    dialog = ClipboardCoordinatesDialog("51\t54\n51\tbad")
    assert not dialog.buttons.button(QDialogButtonBox.StandardButton.Ok).isEnabled()
    dialog.crs_picker.edit.setText("EPSG:4326")
    assert not dialog.buttons.button(QDialogButtonBox.StandardButton.Ok).isEnabled()
    dialog.source.setPlainText("51\t54")
    assert dialog.buttons.button(QDialogButtonBox.StandardButton.Ok).isEnabled()
    dialog.x_column.setCurrentIndex(1)
    assert not dialog.buttons.button(QDialogButtonBox.StandardButton.Ok).isEnabled()
    dialog.close()


def test_clipboard_import_undo_redo(window, qapp):
    qapp.clipboard().setText("500000\t6000000")
    original = ClipboardCoordinatesDialog.exec
    def accept(dialog):
        dialog.crs_picker.edit.setText("EPSG:32639")
        assert len(dialog.points) == 1
        return dialog.DialogCode.Accepted
    with patch.object(ClipboardCoordinatesDialog, "exec", accept):
        window.paste_coordinates()
    assert len(window._point_service.get_points()) == 1
    window.undo()
    assert len(window._point_service.get_points()) == 0
    window.redo()
    assert len(window._point_service.get_points()) == 1


def test_georef_steps_skip_points_with_world_file(qapp, image):
    dialog = GeoreferenceDialog(image)
    assert dialog.georef_steps.currentIndex() == 0
    dialog._next_step()
    assert dialog.georef_steps.currentIndex() == 2
    assert image.name in dialog.review_text.text()
    dialog._previous_step()
    assert dialog.georef_steps.currentIndex() == 0
    dialog.close()


def test_manual_georef_crs_required(qapp, image):
    image.with_suffix(".pgw").unlink()
    image.with_suffix(".prj").unlink()
    dialog = GeoreferenceDialog(image)
    dialog._next_step()
    assert dialog.georef_steps.currentIndex() == 0
    dialog.crs_edit.setText("EPSG:32639")
    dialog._next_step()
    assert dialog.georef_steps.currentIndex() == 1
    dialog._next_step()
    assert dialog.georef_steps.currentIndex() == 1
    dialog.close()


def test_crs_favorites_persist(qapp):
    from rme_mapper.ui.crs_picker import CrsPicker
    picker = CrsPicker("EPSG:32639")
    picker.toggle_favorite()
    other = CrsPicker("EPSG:32639")
    assert other.star.text() == "★"
    assert "metre" in other.info.text()
    other.toggle_favorite()
    assert other.star.text() == "☆"
    picker.close()
    other.close()


def test_bundle_portable_and_original_untouched(tmp_path, image):
    project = ProjectData(map=ProjectMapData(relative_path=str(image), source_type="georeferenced_image", crs="EPSG:32639", affine_transform=[2,0,500000,0,-2,6000000]))
    original = project.to_dict()
    target = tmp_path / "bundle.zip"
    create_project_bundle(project, target, image)
    assert project.to_dict() == original
    with zipfile.ZipFile(target) as archive:
        assert {"project.gpmap", "maps/карта.png", "maps/карта.pgw", "maps/карта.prj"} <= set(archive.namelist())
        archive.extractall(tmp_path / "moved")
    restored = ProjectService.load_project(tmp_path / "moved/project.gpmap")
    assert (tmp_path / "moved" / restored.map.relative_path).is_file()


def test_overlay_order_opacity_persistence_and_bundle(window, image, tmp_path):
    manager = window.raster_overlays_panel
    for name, opacity in (("A", .4), ("B", .8)):
        manager.add_record({"path": str(image), "crs": "EPSG:32639", "affine": [2,0,500000,0,-2,6000000], "opacity": opacity, "visible": True})
    assert manager.items[0].zValue() > manager.items[1].zValue()
    manager.list.setCurrentRow(0)
    manager.move(1)
    assert manager.records[1]["opacity"] == .8
    manager.opacity.setValue(25)
    assert manager.items[1].opacity() == .25
    assert window.map_controller.active_profile.raster_overlays[1]["opacity"] == .25
    path = tmp_path / "overlay.gpmap"
    assert window.project_controller.save_project_as_workflow(path)
    data = ProjectService.load_project(path)
    assert len(data.map.raster_overlays) == 2
    manager.restore()
    assert manager.records[1]["opacity"] == .25
    create_project_bundle(data, tmp_path / "overlay.zip", image)
    with zipfile.ZipFile(tmp_path / "overlay.zip") as archive:
        saved = json.loads(archive.read("project.gpmap"))
        assert all(not Path(item["path"]).is_absolute() for item in saved["map"]["raster_overlays"])
    manager.remove_selected()
    window.map_controller.unload_map()
    assert not manager.records


def test_invalid_overlay_transform_rejected_without_scene_changes(window, image):
    manager = window.raster_overlays_panel
    before = len(window.map_canvas.scene().items())
    with pytest.raises(ValueError):
        manager.add_record({"path": str(image), "crs": "EPSG:4326", "affine": [float('nan'),0,0,0,-1,0]})
    assert len(window.map_canvas.scene().items()) == before


def test_dark_and_light_are_distinct(window, qapp):
    window.map_canvas.fit_to_view()
    window.set_workspace_theme("dark")
    qapp.processEvents()
    qapp.processEvents()
    dark = qapp.styleSheet()
    assert "#111827" in dark
    center = window.map_canvas.viewport().rect().center()
    pixel = window.map_canvas.viewport().grab().toImage().pixelColor(center)
    assert pixel.red() > 200 and pixel.green() < 50
    window.set_workspace_theme("light")
    qapp.processEvents()
    assert qapp.styleSheet() != dark


def test_recent_and_drop_image_route_through_open_workflow(window, image):
    with patch.object(window.map_controller, "open_map_workflow", return_value=True) as workflow:
        window._open_recent_map(str(image))
    workflow.assert_called_once_with(image)


def test_overlay_export_matches_order_and_opacity(qapp, tmp_path):
    from rme_mapper.exporters.map_renderer import MapRenderer
    from rme_mapper.exporters.models import ImageExportOptions
    files = []
    for name, color in (("red", (255,0,0,255)), ("blue", (0,0,255,255))):
        path = tmp_path / (name + ".png")
        Image.new("RGBA", (100,100), color).save(path)
        files.append(path)
    options = ImageExportOptions(file_path=str(tmp_path / "out.png"), width_px=512, height_px=512,
        include_title=False, include_scale_bar=False, include_legend=False, include_north_arrow=False, margin_px=0)
    overlays = [dict(path=str(files[1]), affine=[1,0,0,0,-1,100], opacity=.5, visible=True),
                dict(path=str(files[0]), affine=[1,0,0,0,-1,100], opacity=1, visible=True)]
    result = MapRenderer.render_map(options, "EPSG:32639", (0,0,100,100), raster_overlays=overlays)
    pixel = result.pixelColor(256,256)
    assert abs(pixel.red()-127) <= 2
    assert abs(pixel.blue()-128) <= 2
    overlays[0]["visible"] = False
    result = MapRenderer.render_map(options, "EPSG:32639", (0,0,100,100), raster_overlays=overlays)
    assert result.pixelColor(256,256).red() == 255
    assert result.pixelColor(256,256).blue() == 0


def test_reopen_packaged_overlay_project(window, image, tmp_path):
    manager = window.raster_overlays_panel
    manager.add_record(dict(path=str(image), crs="EPSG:32639", affine=[2,0,500000,0,-2,6000000], opacity=.6))
    path = tmp_path / "before.gpmap"
    window.project_controller.save_project_as_workflow(path)
    data = ProjectService.load_project(path)
    create_project_bundle(data, tmp_path / "bundle.zip", image)
    with zipfile.ZipFile(tmp_path / "bundle.zip") as archive:
        archive.extractall(tmp_path / "moved")
    assert window.project_controller.open_project_workflow(tmp_path / "moved/project.gpmap")
    assert len(manager.records) == 1
    assert manager.records[0]["opacity"] == .6
    assert "moved" in manager.records[0]["path"]

