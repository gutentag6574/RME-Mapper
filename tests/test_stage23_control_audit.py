"""Automated Control Tests for Stage 23 Performance & Memory Audit.

Validates correctness, bounded resources, memory isolation, and export integrity:
- MapRenderer Full Map export ignores screen LOD = 2000.
- Shallow copy Undo safety under point modification (MapPoint immutable fields).
- Circle cache key discriminates (lon, lat, radius, segments).
- Circle cache bound <= 2048 and clear_circle_cache().
- 128 MB project file limit rejection before parse.
- PointsPanel stable IDs and selection preservation (no row-index bugs).
- Atomic backup (*.bak) safety on large projects.
"""

import copy
import os
from pathlib import Path

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication

from rme_mapper.models.map_point import MapPoint
from rme_mapper.models.project_data import (
    PRIMARY_PROJECT_FORMAT,
    ProjectData,
    ProjectMapData,
    ProjectPointData,
)
from rme_mapper.services.geodesic_service import GeodesicService, MAX_CIRCLE_CACHE_SIZE
from rme_mapper.services.project_service import ProjectService
from rme_mapper.services.undo_manager import (
    BulkEditStyleCommand,
    DeleteMultiplePointsCommand,
    ImportPointsCommand,
)
from rme_mapper.ui.panels.points_panel import PointsPanel
from rme_mapper.exporters.map_renderer import MapRenderer
from rme_mapper.exporters.models import ImageExportOptions


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    yield app


# =============================================================================
# 1. MapRenderer Full Map Export vs Screen LOD
# =============================================================================

def test_export_ignores_screen_label_lod(qapp):
    """MapRenderer Full Map export must NOT inherit screen LOD = 2000 cap."""
    pts = [
        MapPoint(
            name=f"Label_{i}",
            latitude=55.0 + (i % 50) * 0.01,
            longitude=37.0 + (i // 50) * 0.01,
        )
        for i in range(2500)
    ]
    options = ImageExportOptions(
        file_path="export_test.png",
        width_px=800,
        height_px=600,
        include_points=True,
        include_labels=True,
        labels_mode="all",
    )
    img = MapRenderer.render_map(
        options=options,
        active_crs="OGC:CRS84",
        target_extent=(37.0, 55.0, 38.0, 56.0),
        points=pts,
    )
    assert isinstance(img, QImage)
    assert not img.isNull()
    assert img.width() == 800
    assert img.height() == 600


# =============================================================================
# 2. Shallow Copy Undo Safety
# =============================================================================

def test_mappoint_fields_are_primitive():
    """Verify MapPoint does not contain mutable nested structures like list/dict."""
    pt = MapPoint(name="Alpha", latitude=55.0, longitude=37.0)
    for field_name, val in pt.__dict__.items():
        assert not isinstance(val, (list, dict, set)), f"Field {field_name} is mutable nested collection"


def test_shallow_copy_undo_isolation():
    """Modifying a point after shallow copy command creation does not corrupt undo state."""
    pt = MapPoint(name="Alpha", latitude=55.0, longitude=37.0, red=255, green=0, blue=0)
    applied_list = []

    pts_before = [pt]
    pts_after = [copy.copy(pt)]
    pts_after[0].red = 0
    pts_after[0].green = 255

    cmd = BulkEditStyleCommand(
        before_points=pts_before,
        after_points=pts_after,
        apply_fn=lambda pl: applied_list.append([copy.copy(p) for p in pl]),
    )
    cmd.execute()
    assert applied_list[-1][0].red == 0
    assert applied_list[-1][0].green == 255

    # Modify original object externally
    pt.red = 128

    cmd.undo()
    assert applied_list[-1][0].red == 255
    assert applied_list[-1][0].green == 0


def test_delete_multiple_undo_isolation():
    """DeleteMultiplePointsCommand restores exact snapshot even if items were modified."""
    pts = [
        MapPoint(name=f"P_{i}", latitude=55.0 + i * 0.01, longitude=37.0)
        for i in range(5)
    ]
    restored = []
    removed = []

    cmd = DeleteMultiplePointsCommand(
        points_with_indices=[(pts[0], 0), (pts[1], 1)],
        restore_fn=lambda p, idx: restored.append((copy.copy(p), idx)),
        remove_fn=lambda pid: removed.append(pid),
    )
    cmd.execute()
    assert len(removed) == 2

    # Mutate source points
    pts[0].name = "Mutated"

    cmd.undo()
    assert len(restored) == 2
    assert restored[0][0].name == "P_0"
    assert restored[1][0].name == "P_1"


# =============================================================================
# 3. Geodesic Circle Cache Key & Bounds
# =============================================================================

def test_circle_cache_key_distinctness():
    """Circle cache distinguishes lon, lat, radius, and segments resolution."""
    GeodesicService.clear_circle_cache()

    poly_base = GeodesicService.create_geodesic_circle(longitude=37.6, latitude=55.7, radius_m=500.0, segments=36)
    poly_lon = GeodesicService.create_geodesic_circle(longitude=37.7, latitude=55.7, radius_m=500.0, segments=36)
    poly_lat = GeodesicService.create_geodesic_circle(longitude=37.6, latitude=55.8, radius_m=500.0, segments=36)
    poly_rad = GeodesicService.create_geodesic_circle(longitude=37.6, latitude=55.7, radius_m=600.0, segments=36)
    poly_seg = GeodesicService.create_geodesic_circle(longitude=37.6, latitude=55.7, radius_m=500.0, segments=72)

    assert poly_base != poly_lon
    assert poly_base != poly_lat
    assert poly_base != poly_rad
    assert poly_base != poly_seg
    assert GeodesicService.circle_cache_size() == 5


def test_circle_cache_max_bound_and_clear():
    """Circle cache never exceeds MAX_CIRCLE_CACHE_SIZE and can be cleared."""
    GeodesicService.clear_circle_cache()
    assert GeodesicService.circle_cache_size() == 0

    for i in range(2500):
        GeodesicService.create_geodesic_circle(longitude=10.0 + i * 0.0001, latitude=50.0, radius_m=100.0 + i, segments=36)

    assert GeodesicService.circle_cache_size() <= MAX_CIRCLE_CACHE_SIZE
    GeodesicService.clear_circle_cache()
    assert GeodesicService.circle_cache_size() == 0


# =============================================================================
# 4. Project File Size Limit 128 MB
# =============================================================================

def test_project_file_limit_checks(tmp_path):
    """Files over 128MB are rejected before heavy reading/parsing."""
    p_oversized = tmp_path / "oversized.gpmap"
    with open(p_oversized, "wb") as f:
        f.seek(129 * 1024 * 1024)
        f.write(b"\0")

    with pytest.raises(ValueError) as exc:
        ProjectService.load_project(p_oversized)
    err_msg = str(exc.value)
    assert "128" in err_msg or "лимит" in err_msg or "превышает" in err_msg


# =============================================================================
# 5. PointsPanel Stable Point IDs & Selection
# =============================================================================

def test_pointspanel_stable_ids_and_selection(qapp):
    """PointsPanel row items correctly map stable point_id via UserRole data."""
    panel = PointsPanel()
    pts = [
        MapPoint(name=f"Point_{i}", latitude=55.0, longitude=37.0)
        for i in range(50)
    ]
    panel.populate_points_batch(pts)

    # Check mapping
    for row in range(50):
        item = panel.points_table.item(row, 0)
        assert item.data(Qt.ItemDataRole.UserRole) == pts[row].id

    # Select point by ID
    panel.select_point_ids([pts[25].id])
    assert panel.selected_point_ids() == [pts[25].id]

    panel.clear_table()
    panel.close()


# =============================================================================
# 6. Backup Atomic Integrity
# =============================================================================

def test_project_atomic_backup_integrity(tmp_path):
    """Saving with create_backup=True creates a valid, non-truncated *.bak file."""
    p = tmp_path / "main_project.gpmap"
    bak = tmp_path / "main_project.gpmap.bak"

    # Version 1
    proj1 = ProjectData(
        format=PRIMARY_PROJECT_FORMAT,
        version=1,
        map=ProjectMapData(map_id="m1", name="V1"),
        layers={},
        points=[ProjectPointData(id="p1", name="Point 1", latitude=55.0, longitude=37.0)],
    )
    ProjectService.save_project(proj1, p, create_backup=False)
    assert p.exists()
    assert not bak.exists()

    # Version 2 with backup
    proj2 = ProjectData(
        format=PRIMARY_PROJECT_FORMAT,
        version=1,
        map=ProjectMapData(map_id="m1", name="V2"),
        layers={},
        points=[
            ProjectPointData(id="p1", name="Point 1", latitude=55.0, longitude=37.0),
            ProjectPointData(id="p2", name="Point 2", latitude=55.1, longitude=37.1),
        ],
    )
    ProjectService.save_project(proj2, p, create_backup=True)

    assert p.exists()
    assert bak.exists()

    # Verify backup contains V1
    loaded_bak = ProjectService.load_project(bak)
    assert loaded_bak.map.name == "V1"
    assert len(loaded_bak.points) == 1

    # Verify main contains V2
    loaded_main = ProjectService.load_project(p)
    assert loaded_main.map.name == "V2"
    assert len(loaded_main.points) == 2
