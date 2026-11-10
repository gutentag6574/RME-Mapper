"""Regression tests for importing existing raster georeferencing."""
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from PIL import Image
from PySide6.QtWidgets import QDialog

from rme_mapper.services.georeference_service import GeoreferenceService as Service
from rme_mapper.ui.georeference_dialog import GeoreferenceDialog
from rme_mapper.ui.open_map_dialog import OpenMapDialog


AFFINE = (2.0, 0.3, 500000.0, -0.2, -2.0, 6000000.0)


@pytest.fixture
def bound_image(tmp_path):
    image = tmp_path / "plan.png"
    Image.new("RGB", (100, 80)).save(image)
    Service.export_world_file(image, AFFINE, "EPSG:32639")
    return image


@pytest.mark.parametrize("extension", [".png", ".jpg", ".jpeg", ".tif", ".tiff"])
def test_round_trip(tmp_path, extension):
    image = tmp_path / ("plan" + extension)
    Image.new("RGB", (100, 80)).save(image)
    original = image.read_bytes()
    world, _ = Service.export_world_file(image, AFFINE, "EPSG:32639")
    for source in (image, world):
        binding = Service.read_world_file(source)
        assert binding["image_path"] == image
        assert binding["affine"] == pytest.approx(AFFINE)
        assert binding["crs"] == "EPSG:32639"
    assert image.read_bytes() == original


@pytest.mark.parametrize("extension", [".PGW", ".pngw", ".wld"])
def test_sidecar_names_case_insensitive(bound_image, extension):
    world = bound_image.with_suffix(".pgw")
    world.rename(bound_image.with_name("PLAN" + extension))
    binding = Service.read_world_file(bound_image)
    assert binding["affine"] == pytest.approx(AFFINE)
    assert Service.resolve_image_path(binding["world_file"]) == bound_image


@pytest.mark.parametrize("content", ["1\n2", "nan\n0\n0\n-1\n0\n0", "1\n2\n2\n4\n0\n0", "x\n0\n0\n-1\n0\n0"])
def test_invalid_world_file_rejected(bound_image, content):
    bound_image.with_suffix(".pgw").write_text(content)
    with pytest.raises(ValueError):
        Service.read_world_file(bound_image)


def test_missing_and_ambiguous_companion(tmp_path):
    world = tmp_path / "plan.jgw"
    world.write_text("1\n0\n0\n-1\n0\n0")
    with pytest.raises(ValueError):
        Service.resolve_image_path(world)
    for ext in (".jpg", ".jpeg"):
        Image.new("RGB", (10, 10)).save(tmp_path / ("plan" + ext))
    with pytest.raises(ValueError):
        Service.resolve_image_path(world)


def test_import_requires_explicit_crs_without_prj(qapp, bound_image):
    bound_image.with_suffix(".prj").unlink()
    dialog = GeoreferenceDialog(bound_image.with_suffix(".pgw"))
    assert not dialog.btn_apply.isEnabled()
    dialog.crs_combo.setCurrentIndex(dialog.crs_combo.findData("EPSG:32639"))
    assert dialog.btn_apply.isEnabled()
    assert dialog.get_crs() == "EPSG:32639"
    assert dialog.get_control_points() == []
    assert dialog.get_affine_transform() == pytest.approx(AFFINE)
    dialog.crs_edit.setText("invalid CRS")
    dialog._recalculate()
    assert not dialog.btn_apply.isEnabled()
    assert not dialog.btn_export_wf.isEnabled()
    with pytest.raises(RuntimeError):
        dialog.get_affine_transform()
    dialog.close()


def test_import_ready_with_prj_and_reopen(qapp, bound_image):
    dialog = GeoreferenceDialog(bound_image)
    assert dialog.btn_apply.isEnabled()
    assert dialog.get_extent() == pytest.approx({"xmin": 500000, "xmax": 500224, "ymin": 5999820, "ymax": 6000000})
    assert dialog.crs_combo.currentData() == "EPSG:32639"
    reopened = GeoreferenceDialog(bound_image, existing_points=[], existing_crs=dialog.get_crs(), existing_affine=dialog.get_affine_transform())
    assert reopened.btn_apply.isEnabled()
    assert reopened.get_affine_transform() == pytest.approx(AFFINE)
    reopened.close()
    dialog.close()


@pytest.mark.parametrize("select_world", [True, False])
def test_open_map_routes_binding_to_image_profile(qapp, bound_image, select_world):
    dialog = OpenMapDialog()
    with patch.object(GeoreferenceDialog, "exec", return_value=QDialog.DialogCode.Accepted), patch("rme_mapper.ui.open_map_dialog.QMessageBox.question") as question:
        dialog.load_file(bound_image.with_suffix(".pgw") if select_world else bound_image)
    profile = dialog.get_map_profile()
    assert profile.source_type == "georeferenced_image"
    assert Path(profile.source_path) == bound_image
    assert profile.affine_transform == pytest.approx(AFFINE)
    assert profile.crs == "EPSG:32639"
    question.assert_not_called()
    dialog.close()


def test_browse_opens_file_picker(qapp, bound_image):
    dialog = OpenMapDialog()
    with patch("rme_mapper.ui.open_map_dialog.QFileDialog.getOpenFileName", return_value=(str(bound_image), "")), patch.object(dialog, "_set_file_path") as inspect:
        dialog._on_browse_clicked()
    inspect.assert_called_once_with(bound_image)
    dialog.close()


def test_main_window_georeference_action(qapp, bound_image):
    from rme_mapper.ui.main_window import MainWindow
    window = MagicMock()
    window._settings_service.get_last_map_directory.return_value = str(bound_image.parent)
    with patch("rme_mapper.ui.main_window.QFileDialog.getOpenFileName", return_value=(str(bound_image.with_suffix(".pgw")), "")), patch.object(GeoreferenceDialog, "exec", return_value=QDialog.DialogCode.Accepted), patch("rme_mapper.ui.main_window.QMessageBox.critical") as error:
        # Use a QWidget parent while keeping this regression independent of app startup.
        from PySide6.QtWidgets import QWidget
        parent = QWidget()
        parent._settings_service = window._settings_service
        parent.map_controller = window.map_controller
        parent.project_controller = window.project_controller
        parent._update_map_dependent_actions = window._update_map_dependent_actions
        MainWindow.open_georeference_image_dialog(parent)
    error.assert_not_called()
    profile, image = window.map_controller.load_georeferenced_image.call_args.args
    assert image == bound_image
    assert profile.crs == "EPSG:32639"
    assert profile.affine_transform == pytest.approx(AFFINE)
    parent.close()


def test_geotiff_embedded_georeferencing(qapp, tmp_path):
    import numpy as np
    import rasterio
    from affine import Affine
    image = tmp_path / "embedded.tif"
    with rasterio.open(image, "w", driver="GTiff", width=20, height=10,
                       count=3, dtype="uint8", crs="EPSG:32639", transform=Affine(*AFFINE)) as dst:
        dst.write(np.zeros((3, 10, 20), dtype="uint8"))
    dialog = GeoreferenceDialog(image)
    assert dialog.btn_apply.isEnabled()
    assert dialog.get_affine_transform() == pytest.approx(AFFINE)
    assert dialog.get_crs() == "EPSG:32639"
    dialog.close()
