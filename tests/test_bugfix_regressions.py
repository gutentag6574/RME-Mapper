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


def test_crit03_clear_online_basemap_and_unload_reset_crs(qapp, monkeypatch):
    """CRIT-03: Отключение онлайн-подложки и выгрузка карты сбрасывают _active_crs и ScaleOverlay."""
    from rme_mapper.maps.online_tile_manager import OnlineTileManager

    monkeypatch.setattr(OnlineTileManager, "update_viewport", lambda *args, **kwargs: None)
    win = MainWindow()
    win.resize(900, 700)
    win.show()
    qapp.processEvents()
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
                raster_overlays=[
                    {
                        "id": "ov-1",
                        "name": "Ov",
                        "path": str(overlay_tif),
                        "crs": "EPSG:4326",
                        "affine": [0.001, 0.0, 47.80, 0.0, -0.001, 56.70],
                        "opacity": 0.5,
                        "visible": True,
                    }
                ],
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


def test_high02_unsaved_project_is_active_and_marks_modified_on_online_map(qapp, monkeypatch):
    """HIGH-02: Несохранённый активный проект учитывается в is_project_active и при смене онлайн-карты."""
    from rme_mapper.maps.online_tile_manager import OnlineTileManager

    monkeypatch.setattr(OnlineTileManager, "update_viewport", lambda *args, **kwargs: None)
    win = MainWindow()
    win.resize(900, 700)
    win.show()
    qapp.processEvents()
    try:
        assert win.project_controller.is_project_active is False
        win.point_controller._cmd_add_point(MapPoint(id="pt-h2", name="Точка", latitude=56.6, longitude=47.8))
        win.project_controller.set_modified(False)
        win.project_controller.project_loaded = True
        assert win.project_controller.current_project_path is None
        assert win.project_controller.is_project_active is True

        from rme_mapper.models.online_provider import ProviderRegistry

        provider = ProviderRegistry.get_provider("osm_standard")
        assert win.map_controller.load_online_map(provider=provider) is True
        assert win.project_controller.is_modified is True
    finally:
        win.project_controller.set_modified(False)
        win.map_controller.unload_map()
        win.close()


def test_high03_reprojection_in_center_zone_and_point_controller(qapp, monkeypatch):
    """HIGH-03: center_on_coordinates, update_point_zone и PointController перепроецируют с учётом CRS."""
    from rme_mapper.maps.online_tile_manager import OnlineTileManager
    from rme_mapper.models.online_provider import ProviderRegistry
    from rme_mapper.services.coordinate_service import CoordinateService

    monkeypatch.setattr(OnlineTileManager, "update_viewport", lambda *args, **kwargs: None)
    win = MainWindow()
    win.resize(900, 700)
    win.show()
    qapp.processEvents()
    try:
        provider = ProviderRegistry.get_provider("osm_standard")
        assert win.map_controller.load_online_map(provider=provider) is True
        assert win.map_canvas.active_crs == "EPSG:3857"

        # 1. Точка в Пулково-1942 (EPSG:4284), проверяем _render_point_on_canvas
        pt = MapPoint(
            id="pt-h3",
            name="Цель 4284",
            object_number="42",
            latitude=56.63,
            longitude=47.89,
            source_crs="EPSG:4284",
            zone_enabled=True,
            radius_m=500.0,
        )
        win.point_controller._cmd_add_point(pt)

        exp_x_4284, exp_y_4284 = CoordinateService.transform_xy(
            47.89, 56.63, source_crs="EPSG:4284", target_crs="EPSG:3857"
        )
        wrong_x_4326, _ = CoordinateService.transform_xy(
            47.89, 56.63, source_crs="EPSG:4326", target_crs="EPSG:3857"
        )
        assert abs(exp_x_4284 - wrong_x_4326) > 50.0
        item_pos = win.map_canvas._user_point_items["pt-h3"].pos()
        assert abs(item_pos.x() - exp_x_4284) < 1e-3
        assert abs(item_pos.y() - (-exp_y_4284)) < 1e-3

        # 2. update_point_zone с zone_polygon=None должен перепроецировать в EPSG:3857 (метры)
        win.map_canvas.update_point_zone(pt, zone_polygon=None)
        zone_rect = win.map_canvas._user_zone_items["pt-h3"].boundingRect()
        assert zone_rect.width() > 500.0
        assert abs(zone_rect.center().x() - exp_x_4284) < 50.0

        # 3. navigate_to_input -> center_on_coordinates переводит в active_crs и не ставит zoom=350 на метры
        win.navigate_edit.setText("Цель 4284")
        win.navigate_to_input()
        center_scene = win.map_canvas.mapToScene(win.map_canvas.viewport().rect().center())
        assert abs(center_scene.x() - exp_x_4284) < 500.0
        assert abs(center_scene.y() - (-exp_y_4284)) < 500.0
        assert win.map_canvas.transform().m11() < 10.0
    finally:
        win.project_controller.set_modified(False)
        win.map_controller.unload_map()
        win.close()


def test_high04_projerror_handling_and_tile_render_bounds(qapp, tmp_path, monkeypatch):
    """HIGH-04: Безопасная обработка ProjError, граничных широт и нулевых размеров при рендере тайлов."""
    import pytest
    from pyproj.exceptions import ProjError
    from PySide6.QtGui import QColor, QImage, QPainter
    from PySide6.QtWidgets import QGraphicsScene

    from rme_mapper.maps.online_tile_manager import OnlineTileManager
    from rme_mapper.models.online_provider import ProviderRegistry
    from rme_mapper.services.annotation_service import annotation_path
    from rme_mapper.services.coordinate_service import CoordinateService
    from rme_mapper.services.tile_cache import TileDiskCache
    from rme_mapper.services.tile_render_service import render_cached_tiles

    # 1. annotation_path не пропускает необработанный ProjError наружу
    with pytest.raises(ValueError):
        annotation_path({"kind": "line", "coordinates": [[47.8, 56.6], [47.9, 56.7]]}, "INVALID:CRS")

    # 2. TileRenderService: нулевой охват, полярные границы EPSG:4326 и fallback на zoom - 1
    cache = TileDiskCache(cache_dir=tmp_path / "tiles_h4", max_size_bytes=5 * 1024 * 1024)
    manager = OnlineTileManager(QGraphicsScene(), tile_cache=cache)
    provider = ProviderRegistry.get_provider("osm_standard")
    manager.set_provider(provider)

    img = QImage(256, 256, QImage.Format.Format_RGBA8888)
    img.fill(QColor(255, 0, 0, 255))
    painter = QPainter(img)
    try:
        render_cached_tiles(painter, manager, (10.0, 10.0, 10.0, 20.0), 256, 256, active_crs="EPSG:3857")
        render_cached_tiles(painter, manager, (-10.0, -90.0, 10.0, 90.0), 256, 256, active_crs="EPSG:4326")

        # Кладём родительский тайл (zoom=0, tx=0, ty=0) и рендерим для zoom=1
        from PySide6.QtCore import QBuffer, QIODevice

        tile_img = QImage(256, 256, QImage.Format.Format_RGBA8888)
        tile_img.fill(QColor(0, 180, 90, 255))
        buf = QBuffer()
        buf.open(QIODevice.OpenModeFlag.WriteOnly)
        tile_img.save(buf, "PNG")
        cache.put_tile(provider.id, 0, 0, 0, bytes(buf.data()))

        out = QImage(256, 256, QImage.Format.Format_RGBA8888)
        out.fill(QColor(0, 0, 0, 0))
        p_out = QPainter(out)
        try:
            render_cached_tiles(
                p_out,
                manager,
                (-20037508.34, -20037508.34, 20037508.34, 20037508.34),
                256,
                256,
                active_crs="EPSG:3857",
            )
        finally:
            p_out.end()
        assert out.pixelColor(64, 64).green() > 100
    finally:
        painter.end()

    # 3. PointController, navigate_to_input (без карты) и _finish_measurement при ProjError
    monkeypatch.setattr(OnlineTileManager, "update_viewport", lambda *args, **kwargs: None)
    info_calls = []
    monkeypatch.setattr(QMessageBox, "information", lambda *args, **kwargs: info_calls.append(args) or QMessageBox.StandardButton.Ok)

    win = MainWindow()
    try:
        win.map_controller.unload_map()
        win.navigate_edit.setText("100, 200")
        win.navigate_to_input()
        assert len(info_calls) == 1

        assert win.map_controller.load_online_map(provider=provider) is True

        p_ok = MapPoint(id="pt-ok", name="Ок", latitude=56.6, longitude=47.8)
        p_bad = MapPoint(id="pt-bad", name="Полюс", latitude=90.0, longitude=0.0)
        win.point_controller._cmd_add_point(p_ok)

        orig_transform = CoordinateService.transform_xy

        def flaky_transform(x, y, source_crs="EPSG:4326", target_crs="EPSG:4326"):
            if abs(float(y) - 90.0) < 1e-9 or abs(float(y) + 90.0) < 1e-9:
                raise ProjError("Simulated pole ProjError")
            return orig_transform(x, y, source_crs=source_crs, target_crs=target_crs)

        monkeypatch.setattr(CoordinateService, "transform_xy", staticmethod(flaky_transform))

        # Ни один из методов PointController не должен падать с ProjError
        win._point_service.insert_point(p_bad)
        win.point_controller._render_point_on_canvas(p_bad)
        win.point_controller.render_points_batch([p_ok, p_bad])
        win.point_controller.reproject_all_points("EPSG:3857")
        win.point_controller.show_all_points()
        win.points_panel.select_point_ids([p_bad.id])
        win.point_controller.zoom_to_selected()
        assert win.point_controller.copy_coordinates_map_xy(p_bad) is None
        win.point_controller._table_point_ids.append(p_bad.id)
        win.point_controller.on_table_row_double_clicked(len(win.point_controller._table_point_ids) - 1, 0)

        # _finish_measurement тоже не должен падать при ProjError
        win.map_canvas.start_measurement("measure_distance")
        win.map_canvas._measure_points = [(0.0, 90.0), (100.0, 90.0)]
        win.map_canvas._finish_measurement()
    finally:
        win.project_controller.set_modified(False)
        win.map_controller.unload_map()
        win.close()

