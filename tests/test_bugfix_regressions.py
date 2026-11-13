"""Регрессионные тесты для исправлений багов из BUGS_REPORT_1_1_0.md."""
from __future__ import annotations

from pathlib import Path

from affine import Affine
import numpy as np
from PySide6.QtWidgets import QMessageBox
import rasterio

from rme_mapper.models.project_data import (
    PRIMARY_PROJECT_FORMAT,
    ProjectData,
    ProjectMapData,
    ProjectPointData,
)
from rme_mapper.services.project_service import ProjectService
from rme_mapper.ui.main_window import MainWindow


def test_crit01_recovery_snapshot_preserves_restored_map_on_startup(qapp, tmp_path, monkeypatch):
    """CRIT-01: Запуск без аргументов после восстановления снимка не должен выгружать карту."""
    tif_path = tmp_path / "recovered_map.tif"
    data = np.full((32, 32), 180, dtype=np.uint8)
    transform = Affine(0.001, 0.0, 47.80, 0.0, -0.001, 56.70)
    with rasterio.open(
        tif_path,
        "w",
        driver="GTiff",
        height=32,
        width=32,
        count=1,
        dtype=np.uint8,
        crs="EPSG:4326",
        transform=transform,
    ) as dst:
        dst.write(data, 1)

    snap_path = tmp_path / "recovery_snapshot.json"
    proj = ProjectData(
        format=PRIMARY_PROJECT_FORMAT,
        version=1,
        map=ProjectMapData(
            map_id="",
            name="Recovered GeoTIFF",
            source_type="geotiff",
            relative_path=str(tif_path),
            crs="EPSG:4326",
            annotations=[
                {
                    "kind": "line",
                    "name": "Track 1",
                    "coordinates": [[47.805, 56.695], [47.815, 56.685]],
                }
            ],
        ),
        layers={"raster_base": True},
        points=[
            ProjectPointData(
                id="pt-rec-1",
                name="Спасённая точка",
                latitude=56.69,
                longitude=47.81,
            )
        ],
    )
    ProjectService.save_recovery_snapshot(proj, None, snap_path)

    monkeypatch.setattr(ProjectService, "get_recovery_snapshot_path", lambda: snap_path)
    monkeypatch.setattr(QMessageBox, "question", lambda *args, **kwargs: QMessageBox.StandardButton.Yes)

    win = MainWindow()
    try:
        assert win.map_controller.active_profile is not None
        assert win.map_controller.map_path == tif_path.resolve()
        assert len(win.map_controller.loaded_layers) > 0
        assert len(win._annotation_items) == 1
        assert len(win._point_service) == 1
        assert win.points_table.rowCount() == 1
    finally:
        win.project_controller.set_modified(False)
        win.map_controller.unload_map()
        win.close()


def test_crit01_declined_recovery_still_unloads_map_on_startup(qapp, tmp_path, monkeypatch):
    """CRIT-01: При отказе от восстановления снимка на старте карта остаётся выгруженной."""
    snap_path = tmp_path / "recovery_snapshot.json"
    proj = ProjectData(
        format=PRIMARY_PROJECT_FORMAT,
        version=1,
        map=ProjectMapData(map_id="", name="Unused"),
        layers={},
        points=[],
    )
    ProjectService.save_recovery_snapshot(proj, None, snap_path)

    monkeypatch.setattr(ProjectService, "get_recovery_snapshot_path", lambda: snap_path)
    monkeypatch.setattr(QMessageBox, "question", lambda *args, **kwargs: QMessageBox.StandardButton.No)

    win = MainWindow()
    try:
        assert win.map_controller.active_profile is None
        assert win.map_controller.map_path is None
        assert not win.project_controller.is_project_active
        assert not snap_path.exists()
    finally:
        win.close()

