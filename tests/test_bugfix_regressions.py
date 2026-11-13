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


def _write_test_geotiff(path: Path, xmin: float = 47.80, ymax: float = 56.70, crs: str = "EPSG:4326") -> None:
    data = np.full((32, 32), 180, dtype=np.uint8)
    transform = Affine(0.001, 0.0, xmin, 0.0, -0.001, ymax)
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        height=32,
        width=32,
        count=1,
        dtype=np.uint8,
        crs=crs,
        transform=transform,
    ) as dst:
        dst.write(data, 1)


def test_crit03_switching_maps_and_error_cleanup(qapp, tmp_path):
    """CRIT-03: Смена карты очищает старые слои/границы, а несуществующий файл не портит состояние."""
    tif_a = tmp_path / "map_a.tif"
    _write_test_geotiff(tif_a, xmin=47.80, ymax=56.70, crs="EPSG:4326")

    gpkg_b = tmp_path / "map_b.gpkg"
    import geopandas as gpd
    from shapely.geometry import Polygon

    gdf = gpd.GeoDataFrame(
        {"name": ["Zone B"]},
        geometry=[Polygon([(500000.0, 6000000.0), (501000.0, 6000000.0), (501000.0, 6001000.0), (500000.0, 6001000.0)])],
        crs="EPSG:32637",
    )
    gdf.to_file(gpkg_b, driver="GPKG", layer="boundary")

    win = MainWindow()
    try:
        # 1. Загружаем GeoTIFF и имитируем старый векторный слой + границы + точку с зоной
        win.map_controller.load_map(tif_a)
        assert win.map_canvas._raster_item is not None
        assert win.map_controller.active_crs == "EPSG:4326"

        win.point_controller._cmd_add_point(
            MapPoint(id="pt-crit03", name="Точка", latitude=56.69, longitude=47.81, radius_m=150.0, zone_enabled=True)
        )
        assert "pt-crit03" in win.map_canvas._user_zone_items

        # 2. Загружаем векторную GeoPackage поверх GeoTIFF: старый растр должен полностью очиститься
        win.map_controller.load_map(gpkg_b)
        assert win.map_canvas._raster_item is None
        assert win.map_canvas._raster_window_item is None
        assert win.map_canvas._raster_provider is None
        assert win.map_controller.active_crs == "EPSG:32637"
        assert len(win.map_canvas._layer_items) == 1

        # 3. Загружаем GeoTIFF поверх GeoPackage: старые векторные слои и boundary_bounds должны уйти
        win.map_controller.load_map(tif_a)
        assert list(win.map_canvas._layer_items.keys()) == ["raster_base"]
        assert win.map_canvas._boundary_bounds is None
        assert win.map_canvas._raster_item is not None
        assert win.map_controller.active_crs == "EPSG:4326"

        # 4. Попытка загрузить несуществующий файл с HTML-символами
        missing_path = tmp_path / "<missing>&map.gpkg"
        win.map_controller.load_map(missing_path)
        assert win.map_controller.active_profile is None
        assert win.map_controller.map_path is None
        assert win.map_controller.active_crs == "OGC:CRS84"
        assert win.map_canvas._raster_item is None
        assert win.map_canvas._user_point_items == {}
        assert win.map_canvas._user_zone_items == {}
        assert win.map_canvas._user_label_items == {}
        assert win.map_canvas._selection_halo_items == {}
        assert win.map_canvas._scale_overlay._is_map_loaded is False

        # После set_error очистка карты не должна падать на удалённых Qt-элементах
        win.map_canvas.clear_user_points()
        win.map_canvas.clear_measurements()

        # Экранирование HTML в сообщении об ошибке
        win.map_canvas.set_error("<b>bad</b> & <script>alert(1)</script>")
        from PySide6.QtWidgets import QGraphicsTextItem

        text_items = [it for it in win.map_canvas.scene().items() if isinstance(it, QGraphicsTextItem)]
        assert len(text_items) == 1
        assert "<script>" not in text_items[0].toPlainText() or "<script>alert(1)</script>" in text_items[0].toPlainText()
        assert "&lt;script&gt;" in text_items[0].toHtml()
    finally:
        win.project_controller.set_modified(False)
        win.map_controller.unload_map()
        win.close()


def test_crit03_clear_online_basemap_and_unload_reset_crs(qapp):
    """CRIT-03: Отключение онлайн-подложки и выгрузка карты сбрасывают _active_crs и ScaleOverlay."""
    win = MainWindow()
    try:
        from rme_mapper.models.online_provider import ProviderRegistry

        provider = ProviderRegistry.get_provider("osm_standard")
        assert win.map_controller.load_online_map(provider=provider) is True
        assert win.map_canvas._active_crs == "EPSG:3857"
        assert win.map_canvas._scale_overlay._is_map_loaded is True

        win.map_canvas.clear_online_basemap()
        assert win.map_canvas._active_crs == "OGC:CRS84"
        assert win.map_canvas._scale_overlay._is_map_loaded is False

        win.map_controller.load_online_map(provider=provider)
        assert win.map_controller.active_crs == "EPSG:3857"
        win.map_controller.unload_map()
        assert win.map_controller.active_crs == "OGC:CRS84"
        assert win.map_canvas._active_crs == "OGC:CRS84"
    finally:
        win.project_controller.set_modified(False)
        win.close()


def test_crit04_catalog_profile_not_mutated_and_annotation_undo_isolated(qapp, tmp_path):
    """CRIT-04: Каталожный MapProfile не мутируется при открытии проекта, а Undo аннотаций изолирован."""
    tif_a = tmp_path / "map_a.tif"
    tif_b = tmp_path / "map_b.tif"
    _write_test_geotiff(tif_a, xmin=47.80, ymax=56.70, crs="EPSG:4326")
    _write_test_geotiff(tif_b, xmin=48.10, ymax=56.80, crs="EPSG:4326")

    overlay_tif = tmp_path / "overlay.tif"
    _write_test_geotiff(overlay_tif, xmin=47.80, ymax=56.70, crs="EPSG:4326")

    win = MainWindow()
    try:
        catalog = win._map_catalog_service
        original = catalog.get_profile("mari_el")
        assert original is not None
        orig_annotations = list(original.annotations)
        orig_overlays = list(original.raster_overlays)

        proj = ProjectData(
            format=PRIMARY_PROJECT_FORMAT,
            version=1,
            map=ProjectMapData(
                map_id="mari_el",
                name="Республика Марий Эл",
                source_type="geopackage",
                annotations=[
                    {
                        "id": "ann-1",
                        "kind": "line",
                        "name": "Project Track",
                        "coordinates": [[47.81, 56.69], [47.82, 56.68]],
                        "visible": True,
                    }
                ],
                raster_overlays=[{"id": "ov-1", "name": "Ov", "path": str(overlay_tif), "opacity": 0.5, "visible": True}],
            ),
            layers={},
            points=[],
        )
        assert win.project_controller._resolve_and_apply_project(proj, tmp_path / "p.rmeproject") is True

        # Каталог не должен содержать аннотации/оверлеи из проекта
        fresh_from_catalog = catalog.get_profile("mari_el")
        assert fresh_from_catalog is not None
        assert fresh_from_catalog.annotations == orig_annotations
        assert fresh_from_catalog.raster_overlays == orig_overlays

        # Проверка без активной карты: change_annotations не должен падать
        win.map_controller.unload_map()
        assert win.map_controller.active_profile is None
        win.change_annotations([{"kind": "line", "name": "NoMap", "coordinates": [[47.0, 56.0], [47.1, 56.1]]}])

        # Загружаем карту A, добавляем аннотацию и переключаемся на карту B
        win.map_controller.load_map(tif_a)
        profile_a = win.map_controller.active_profile
        assert profile_a is not None
        win.change_annotations([{"kind": "line", "name": "Track A", "coordinates": [[47.805, 56.695], [47.81, 56.69]]}])
        assert len(profile_a.annotations) == 1

        win.map_controller.load_map(tif_b)
        profile_b = win.map_controller.active_profile
        assert profile_b is not None
        assert profile_b is not profile_a
        assert profile_b.annotations == []

        # Undo после смены карты не должен менять profile_a или ломать profile_b
        win.undo()
        assert len(profile_a.annotations) == 1
        assert profile_b.annotations == []
    finally:
        win.project_controller.set_modified(False)
        win.map_controller.unload_map()
        win.close()


def test_high01_undo_manager_is_clean_false_after_branching():
    """HIGH-01: Undo + новое действие (ветвление стека) должно сбрасывать clean_index."""
    from rme_mapper.services.undo_manager import UndoCommand, UndoManager

    class DummyCmd(UndoCommand):
        def execute(self) -> None:
            pass

        def undo(self) -> None:
            pass

    mgr = UndoManager()
    mgr.push(DummyCmd("c1"), execute=True)
    mgr.push(DummyCmd("c2"), execute=True)
    mgr.mark_clean()
    assert mgr.is_clean is True

    assert mgr.undo() is True
    assert mgr.is_clean is False

    # Ветвление стека: отрезаем c2 и добавляем c3 — длина снова 2, но состояние НЕ чистое!
    mgr.push(DummyCmd("c3"), execute=True)
    assert mgr.is_clean is False
    mgr.undo()
    assert mgr.is_clean is False

