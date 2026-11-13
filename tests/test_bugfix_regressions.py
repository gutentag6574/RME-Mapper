"""Регрессионные тесты для исправлений багов из BUGS_REPORT_1_1_0.md."""
from __future__ import annotations

from pathlib import Path

from affine import Affine
import numpy as np
from PySide6.QtWidgets import QMessageBox
import rasterio

from rme_mapper.models.map_point import MapPoint
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


def test_crit02_undo_delete_first_and_middle_point_preserves_rows_and_order(qapp):
    """CRIT-02: Undo удаления первой или средней строки не затирает строки и сохраняет порядок."""
    win = MainWindow()
    try:
        p1 = MapPoint(id="pt-1", name="Первая", latitude=56.0, longitude=47.0)
        p2 = MapPoint(id="pt-2", name="Вторая", latitude=56.1, longitude=47.1)
        p3 = MapPoint(id="pt-3", name="Третья", latitude=56.2, longitude=47.2)
        win.point_controller._cmd_add_points([p1, p2, p3])

        assert win.points_table.rowCount() == 3
        assert win.point_controller._table_point_ids == ["pt-1", "pt-2", "pt-3"]

        # Удаляем первую строку (index 0) и отменяем (Undo)
        win.points_panel.select_point_ids(["pt-1"])
        win.point_controller.delete_point_workflow(confirm=False)
        assert win.points_table.rowCount() == 2
        assert win.point_controller._table_point_ids == ["pt-2", "pt-3"]

        win.undo()
        assert win.points_table.rowCount() == 3
        assert win.point_controller._table_point_ids == ["pt-1", "pt-2", "pt-3"]
        assert [win.points_table.item(r, 1).text() for r in range(3)] == ["Первая", "Вторая", "Третья"]
        assert [win.points_table.item(r, 0).text() for r in range(3)] == ["1", "2", "3"]
        assert [p.id for p in win._point_service.get_points()] == ["pt-1", "pt-2", "pt-3"]

        # Удаляем среднюю строку (index 1) и отменяем (Undo)
        win.points_panel.select_point_ids(["pt-2"])
        win.point_controller.delete_point_workflow(confirm=False)
        assert win.points_table.rowCount() == 2

        win.undo()
        assert win.points_table.rowCount() == 3
        assert win.point_controller._table_point_ids == ["pt-1", "pt-2", "pt-3"]
        assert [win.points_table.item(r, 1).text() for r in range(3)] == ["Первая", "Вторая", "Третья"]
        assert [p.id for p in win._point_service.get_points()] == ["pt-1", "pt-2", "pt-3"]

        # Массовое удаление несмежных строк (0 и 2) и Undo + перерисовка батчем
        win.points_panel.select_point_ids(["pt-1", "pt-3"])
        win.point_controller.delete_point_workflow(confirm=False)
        assert win.points_table.rowCount() == 1
        assert win.point_controller._table_point_ids == ["pt-2"]

        win.undo()
        assert win.points_table.rowCount() == 3
        assert win.point_controller._table_point_ids == ["pt-1", "pt-2", "pt-3"]
        assert [p.id for p in win._point_service.get_points()] == ["pt-1", "pt-2", "pt-3"]

        win.point_controller.populate_points_table_batch(win._point_service.get_points())
        assert win.point_controller._table_point_ids == ["pt-1", "pt-2", "pt-3"]
        assert [win.points_table.item(r, 1).text() for r in range(3)] == ["Первая", "Вторая", "Третья"]
    finally:
        win.project_controller.set_modified(False)
        win.close()

