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


def test_high05_raster_channel_order_and_alpha_dtype_scale():
    """HIGH-05: исключение alpha_idx из R/G/B (ARGB) и нормировка альфы по максимуму dtype."""
    import numpy as np
    from rasterio.enums import ColorInterp
    from rme_mapper.backends.modern_raster import ModernGeoTiffBackend

    # 1. Канал alpha на индексе 0 ([alpha, red, green, blue]), uint16 полупрозрачный (32768 ~= 50%)
    a = np.full((2, 2), 32768, dtype=np.uint16)
    r = np.array([[0, 65535], [0, 65535]], dtype=np.uint16)
    g = np.array([[0, 0], [65535, 65535]], dtype=np.uint16)
    b = np.full((2, 2), 10000, dtype=np.uint16)
    data = np.stack([a, r, g, b], axis=0)
    ci = [ColorInterp.alpha, ColorInterp.red, ColorInterp.green, ColorInterp.blue]

    rgba = ModernGeoTiffBackend._normalize_to_rgba(data, ci, nodata=None, mask=None)
    assert rgba.shape == (2, 2, 4)
    # R должен соответствовать массиву r (0 в (0,0), 255 в (0,1)), а не alpha (32768)!
    assert rgba[0, 0, 0] == 0
    assert rgba[0, 1, 0] == 255
    assert rgba[1, 0, 1] == 255
    # Альфа 32768 из 65535 должна стать ~127..128, а не 255!
    assert 125 <= int(rgba[0, 0, 3]) <= 130

    # 2. BGR + Alpha ([blue, green, red, alpha]) с float32 в [0.0, 0.5]
    b_f = np.full((2, 2), 10.0, dtype=np.float32)
    g_f = np.full((2, 2), 20.0, dtype=np.float32)
    r_f = np.array([[0.0, 100.0], [0.0, 100.0]], dtype=np.float32)
    a_f = np.full((2, 2), 0.5, dtype=np.float32)
    rgba_f = ModernGeoTiffBackend._normalize_to_rgba(
        np.stack([b_f, g_f, r_f, a_f], axis=0),
        [ColorInterp.blue, ColorInterp.green, ColorInterp.red, ColorInterp.alpha],
        nodata=None,
        mask=None,
    )
    assert rgba_f[0, 0, 0] == 0 and rgba_f[0, 1, 0] == 255
    assert 126 <= int(rgba_f[0, 0, 3]) <= 129


def test_high06_warp_image_edge_cases_and_overlay_relative_path(tmp_path, qapp):
    """HIGH-06: warp_image без DeprecationWarning/ZeroDivisionError/TypeError и сохранение относительного path оверлея."""
    import warnings
    import pytest
    from pathlib import Path
    from PySide6.QtGui import QImage, QColor
    from rme_mapper.models.map_profile import MapProfile
    from rme_mapper.services.raster_warp_service import warp_image
    from rme_mapper.ui.main_window import MainWindow

    # 1. Пустой QImage -> понятный ValueError, не ZeroDivisionError
    with pytest.raises(ValueError):
        warp_image(QImage(), (10, 10), [1, 0, 0, 0, -1, 10], "EPSG:4326", "EPSG:3857")

    # 2. extent без output_size и без PendingDeprecationWarning от Affine * ...
    img = QImage(20, 10, QImage.Format.Format_RGBA8888)
    img.fill(QColor(255, 0, 0, 255))
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        warped, _ = warp_image(
            img,
            (20, 10),
            [0.01, 0.0, 47.0, 0.0, -0.01, 56.0],
            "EPSG:4326",
            "EPSG:3857",
            extent=(5230000.0, 7530000.0, 5260000.0, 7560000.0),
            output_size=None,
        )
    assert not warped.isNull()
    assert warped.width() == 20 and warped.height() > 0
    affine_warnings = [w for w in caught if issubclass(w.category, PendingDeprecationWarning) and "matmul" in str(w.message)]
    assert not affine_warnings

    # 3. RasterOverlays.add_record не затирает относительный путь
    overlay_dir = tmp_path / "overlays"
    overlay_dir.mkdir()
    overlay_file = overlay_dir / "plan.png"
    img.save(str(overlay_file))

    win = MainWindow()
    try:
        profile = MapProfile(
            id="rel-ovl",
            name="Rel",
            crs="EPSG:32639",
            source_type="geopackage",
            base_dir=tmp_path,
        )
        win.map_controller._active_profile = profile
        win.map_canvas._active_crs = "EPSG:32639"
        win.raster_overlays_panel.add_record(
            {
                "path": "overlays/plan.png",
                "crs": "EPSG:32639",
                "affine": [2.0, 0.0, 500000.0, 0.0, -2.0, 6000000.0],
                "opacity": 0.7,
                "visible": True,
            },
            modified=False,
        )
        assert win.raster_overlays_panel.records[0]["path"] == "overlays/plan.png"
        assert Path(profile.raster_overlays[0]["path"]).as_posix() == "overlays/plan.png"
    finally:
        win.project_controller.set_modified(False)
        win.map_controller.unload_map()
        win.close()


def test_high07_tile_cache_validation_no_os_walk_per_tile_and_single_write(tmp_path, qapp, monkeypatch):
    """HIGH-07: проверка provider_id в get_total_size_bytes/clear_cache, отсутствие os.walk на каждый тайл и двойной записи."""
    import os
    import pytest
    from PySide6.QtCore import QBuffer, QIODevice
    from PySide6.QtGui import QImage, QColor
    from PySide6.QtWidgets import QGraphicsScene
    from rme_mapper.maps.online_tile_manager import OnlineTileManager
    from rme_mapper.services.tile_cache import TileDiskCache

    cache = TileDiskCache(base_dir=tmp_path / "h7_cache", max_size_bytes=5 * 1024 * 1024)

    for bad_id in ("../escape", "a/b", "bad id", ""):
        with pytest.raises(ValueError):
            cache.get_total_size_bytes(bad_id)
        with pytest.raises(ValueError):
            cache.clear_cache(bad_id)

    img = QImage(16, 16, QImage.Format.Format_RGBA8888)
    img.fill(QColor("#112233"))
    buf = QBuffer()
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    img.save(buf, "PNG")
    png_bytes = bytes(buf.data())

    walk_calls = 0
    orig_walk = os.walk

    def counting_walk(*args, **kwargs):
        nonlocal walk_calls
        walk_calls += 1
        return orig_walk(*args, **kwargs)

    monkeypatch.setattr(os, "walk", counting_walk)
    for x in range(10):
        assert cache.save_tile("osm_standard", 5, x, 0, png_bytes) is True
    # Первоначальный подсчет допустим 1 раз, но не 10 синхронных os.walk на каждый тайл!
    assert walk_calls <= 1

    # OnlineTileManager не должен повторно записывать тайл, если TileLoader делит тот же cache
    scene = QGraphicsScene()
    mgr = OnlineTileManager(scene=scene, tile_cache=cache)
    put_calls: list[tuple[str, int, int, int]] = []
    orig_put = cache.put_tile
    monkeypatch.setattr(cache, "put_tile", lambda pid, z, x, y, data, **kw: put_calls.append((pid, z, x, y)) or orig_put(pid, z, x, y, data, **kw))
    mgr._on_tile_loaded("osm_standard", 5, 0, 0, png_bytes)
    assert put_calls == []


def test_high08_bundle_resolves_relative_and_copies_overlay_sidecars(tmp_path):
    """HIGH-08: разрешение относительных путей от каталога проекта, копирование sidecar-ов оверлеев и относительные пути при build_project_data."""
    import zipfile
    from PySide6.QtGui import QImage, QColor
    from rme_mapper.models.map_profile import MapProfile
    from rme_mapper.models.project_data import ProjectData, ProjectMapData
    from rme_mapper.services.project_bundle_service import create_project_bundle
    from rme_mapper.services.project_service import ProjectService

    proj_dir = tmp_path / "proj_dir"
    (proj_dir / "sub_map").mkdir(parents=True)
    (proj_dir / "sub_ovl").mkdir(parents=True)

    img = QImage(16, 16, QImage.Format.Format_RGBA8888)
    img.fill(QColor("#334455"))

    map_file = proj_dir / "sub_map" / "base.png"
    img.save(str(map_file))
    (proj_dir / "sub_map" / "base.pgw").write_text("1\n0\n0\n-1\n0\n16\n", encoding="utf-8")

    ovl_file = proj_dir / "sub_ovl" / "extra.png"
    img.save(str(ovl_file))
    (proj_dir / "sub_ovl" / "extra.pgw").write_text("1\n0\n0\n-1\n10\n26\n", encoding="utf-8")
    (proj_dir / "sub_ovl" / "extra.prj").write_text("EPSG:32639", encoding="utf-8")

    project = ProjectData(
        map=ProjectMapData(
            relative_path="sub_map/base.png",
            source_type="image",
            crs="EPSG:32639",
            raster_overlays=[
                {
                    "path": "sub_ovl/extra.png",
                    "crs": "EPSG:32639",
                    "affine": [1.0, 0.0, 10.0, 0.0, -1.0, 26.0],
                    "opacity": 0.8,
                    "visible": True,
                }
            ],
        )
    )

    bundle_path = tmp_path / "out.zip"
    create_project_bundle(project, bundle_path, map_path=None, base_dir=proj_dir)

    with zipfile.ZipFile(bundle_path) as zf:
        names = set(zf.namelist())
        assert "maps/base.png" in names
        assert "maps/base.pgw" in names
        assert "overlays/0/extra.png" in names
        assert "overlays/0/extra.pgw" in names
        assert "overlays/0/extra.prj" in names

    # build_project_data сохраняет относительные пути карты и оверлеев относительно project_dir
    prof = MapProfile(
        id="p1",
        name="Test",
        crs="EPSG:32639",
        source_type="image",
        base_dir=proj_dir,
        raster_overlays=[{"path": str(ovl_file), "crs": "EPSG:32639", "affine": [1, 0, 0, 0, -1, 1], "opacity": 1.0, "visible": True}],
    )
    built = ProjectService.build_project_data(map_path=map_file, map_profile=prof, project_dir=proj_dir)
    assert built.map.relative_path == "sub_map/base.png"
    assert built.map.raster_overlays[0]["path"] == "sub_ovl/extra.png"


def test_high09_importer_and_wizard_fixes(tmp_path, qapp):
    """HIGH-09: унификация Column_{i+1}, >50 строк заголовка, исключения конфликтов, TSV/дубликаты, предупреждения стилей, bool/NaN."""
    import pytest
    from rme_mapper.importers.delimited_importer import DelimitedImporter
    from rme_mapper.importers.import_service import ImportService
    from rme_mapper.importers.models import CoordinateFormat, ImportOptions
    from rme_mapper.services.project_service import MAX_PROJECT_POINTS
    from rme_mapper.ui.import_wizard import ImportWizard

    # 1. TSV с ведущей табуляцией (пустая 1-я колонка -> Column_1) и дубликатом заголовка
    tsv_lines = ["\tName\tName\tlat\tlon"] + [f"row{i}\tPtA\tPtB\t56.{i}\t47.{i}" for i in range(65)]
    # Строка 60 с заголовками
    lines_60 = [f"skip_{i};x;y" for i in range(59)] + ["\tName\tName\tlat\tlon", "id1\tP1\tP2\t56.1\t47.2"]
    tsv_file = tmp_path / "data_60.tsv"
    tsv_file.write_text("\n".join(lines_60), encoding="utf-8")

    # DelimitedImporter на обычном TSV (header_row=1)
    tsv1 = tmp_path / "hdr1.tsv"
    tsv1.write_text("\n".join(tsv_lines[:5]), encoding="utf-8")
    imp = DelimitedImporter()
    rows, _, delim, _ = imp.read_rows(tsv1, ImportOptions(header_row=1))
    assert delim == "\t"
    assert rows[0][1]["Column_1"] == "row0"
    assert rows[0][1]["Name"] == "PtA"
    assert rows[0][1]["Name (2)"] == "PtB"

    # ImportWizard: header_row > 50 (например 60) и Column_{i+1}
    tsv2 = tmp_path / "hdr60.tsv"
    tsv2.write_text("\n".join([f"skip_{i}\ta\tb\tc\td" for i in range(59)] + ["\tName\tName\tlat\tlon", "r1\tP1\tP2\t56.1\t47.2"]), encoding="utf-8")
    wizard = ImportWizard(file_path=tsv2)
    try:
        wizard.next()
        wizard.page_structure.header_row_spin.setValue(60)
        qapp.processEvents()
        headers = wizard.get_detected_headers()
        assert headers == ["Column_1", "Name", "Name (2)", "lat", "lon"]
        assert wizard.page_structure.isComplete() is True

        # Новые необязательные поля не вызывают конфликт маппинга при совпадении колонок
        wizard.page_mapping._headers = headers
        wizard.page_mapping._populate_combos()
        wizard.page_mapping.radio_dd.setChecked(True)
        for fk, col in (("latitude", "lat"), ("longitude", "lon"), ("object_number", "Name"), ("stroke_width", "Name"), ("zone_border_style", "Name")):
            combo = wizard.page_mapping._combos[fk]
            combo.setCurrentIndex(combo.findData(col))
        wizard.page_mapping._validate_mapping()
        assert wizard.page_mapping.isComplete() is True
    finally:
        wizard.close()

    # ImportService: предупреждения для невалидных visible/stroke_width/marker_opacity/zone_border_style + bool/NaN + лимит
    csv_warn = tmp_path / "warn.csv"
    csv_warn.write_text(
        "name;lat;lon;visible;stroke_width;marker_opacity;zone_border_style\n"
        "P1;56.1;47.2;maybe;notnum;999;wavy\n",
        encoding="utf-8",
    )
    svc = ImportService()
    res = svc.validate_file(csv_warn, ImportOptions(coordinate_format=CoordinateFormat.DD))
    assert res.valid_rows == 1
    assert len(res.warnings) >= 4
    warn_fields = {w.field for w in res.warnings}
    assert {"visible", "stroke_width", "marker_opacity", "zone_border_style"}.issubset(warn_fields)

    with pytest.raises(ValueError):
        ImportService._parse_dd_number(True)
    with pytest.raises(ValueError):
        ImportService._parse_dd_number("nan")
    with pytest.raises(ValueError):
        ImportService._parse_int_component(False, "lat_deg")
    with pytest.raises(ValueError):
        ImportService._parse_float_component(float("inf"), "lat_sec")

    res_limit = svc.validate_file(csv_warn, ImportOptions(coordinate_format=CoordinateFormat.DD), current_project_points_count=MAX_PROJECT_POINTS)
    assert any(e.code == "import.err.max_project_points_exceeded" for e in res_limit.errors)
    assert res_limit.points == []


def test_high10_export_and_georef_dialog_fixes(qapp, tmp_path, monkeypatch):
    """HIGH-10: Экспорт карты/объектов, декорации, санитизация имён и OpenMap/Georeference dialogs."""
    from PySide6.QtCore import QRectF
    from PySide6.QtGui import QImage, QPainter, QPainterPath
    from PySide6.QtWidgets import QMessageBox

    from rme_mapper.exporters.decorations import NICE_INTERVALS, MapDecorationRenderer
    from rme_mapper.exporters.map_renderer import MapRenderer
    from rme_mapper.exporters.models import ImageExportOptions
    from rme_mapper.models.georeference import ControlPoint
    from rme_mapper.ui.export_image_dialog import ExportImageDialog, _sanitize_filename_stem
    from rme_mapper.ui.export_objects_dialog import ExportObjectsDialog
    from rme_mapper.ui.georeference_dialog import GeoreferenceDialog
    from rme_mapper.ui.open_map_dialog import OpenMapDialog, _extract_clean_crs

    # 1. MapRenderer: битый оверлей и аннотация не срывают экспорт; перо аннотации масштабируется
    img_out = MapRenderer.render_map(
        options=ImageExportOptions(
            file_path=str(tmp_path / "out.png"),
            format="PNG",
            width_px=2400,
            height_px=1600,
            include_legend=True,
            legend_position="top_right",
            include_north_arrow=True,
            include_scale_bar=True,
        ),
        active_crs="EPSG:3857",
        target_extent=(-10_000_000.0, -5_000_000.0, 10_000_000.0, 5_000_000.0),
        loaded_layers_render_data=[],
        points=[MapPoint(id="p1", name="P1", latitude=10.0, longitude=10.0, symbol="circle")],
        selected_point_ids=set(),
        raster_overlays=[{"path": str(tmp_path / "missing.tif"), "visible": True, "opacity": 0.8, "affine": [1, 0, 0, 0, -1, 0], "crs": "EPSG:3857"}],
        annotations=[
            {"id": "bad", "kind": "invalid_kind", "coordinates": [], "visible": True},
            {"id": "ok", "kind": "line", "coordinates": [[0.0, 0.0], [10.0, 10.0]], "visible": True},
        ],
    )
    assert not img_out.isNull()
    assert img_out.width() == 2400

    # 2. Decorations: top_right legend не пересекается с north_arrow; NICE_INTERVALS континентальный; Mapbox badge без дубликата
    assert max(NICE_INTERVALS) >= 10_000_000
    dec_img = QImage(800, 600, QImage.Format.Format_RGBA8888)
    painter = QPainter(dec_img)
    try:
        rect = QRectF(0, 0, 800, 600)
        arrow_rect = MapDecorationRenderer.render_north_arrow(
            painter, (0.0, 0.0, 1000.0, 1000.0), "EPSG:3857", rect, 1.0, 16.0
        )
        legend_rect = MapDecorationRenderer.render_legend(
            painter, [MapPoint(id="p1", name="P1", latitude=0.0, longitude=0.0)], False, "top_right", rect, 1.0, 16.0, has_north_arrow=True
        )
        assert not legend_rect.isEmpty()
        assert not arrow_rect.intersects(legend_rect)

        seen_texts: list[str] = []
        orig_draw_text = QPainter.drawText
        def _capture_draw_text(self_p, *args, **kwargs):
            if args and isinstance(args[-1], str):
                seen_texts.append(args[-1])
            return orig_draw_text(self_p, *args, **kwargs)
        monkeypatch.setattr(QPainter, "drawText", _capture_draw_text)
        MapDecorationRenderer.render_attribution(painter, "© Mapbox © OpenStreetMap", rect, 1.0, 16.0, logo_required=True)
        assert "© Mapbox © OpenStreetMap" in seen_texts
        assert not any(t.startswith("mapbox | © Mapbox") for t in seen_texts)
    finally:
        painter.end()

    # 3. ExportImageDialog: санитизация имени, preview height >= 1 и форматирование error=
    assert _sanitize_filename_stem('Карта: <тест>/1?*.') == "Карта_ _тест_1_"
    assert _sanitize_filename_stem("CON") == "map"

    exp_dlg = ExportImageDialog(
        parent=None,
        active_crs="EPSG:3857",
        map_title='Bad:Name<1>',
        current_view_extent=(0.0, 0.0, 1000.0, 1000.0),
        full_map_extent=(0.0, 0.0, 1000.0, 1000.0),
        loaded_layers_render_data=[],
        points=[],
        selected_point_ids=set(),
    )
    try:
        assert "<" not in exp_dlg.path_edit.text() and ":" not in Path(exp_dlg.path_edit.text()).name
        exp_dlg.chk_lock_aspect.setChecked(False)
        exp_dlg.spin_width.setValue(10000)
        exp_dlg.spin_height.setValue(1)

        captured_opts = {}
        def _fail_render(**kwargs):
            captured_opts["opts"] = kwargs["options"]
            raise RuntimeError("boom-preview")
        monkeypatch.setattr(MapRenderer, "render_map", staticmethod(_fail_render))
        warned = []
        monkeypatch.setattr(QMessageBox, "warning", lambda *a, **kw: warned.append(a[2] if len(a) > 2 else ""))
        exp_dlg._on_preview_clicked()
        assert captured_opts["opts"].height_px >= 1
        assert warned and "boom-preview" in warned[0] and "{error}" not in warned[0]
    finally:
        exp_dlg.close()

    # 4. ExportObjectsDialog: добавление расширения при имени с точкой ('points.v2' -> 'points.v2.csv')
    obj_dlg = ExportObjectsDialog(points=[], selected_ids=set())
    try:
        obj_dlg.path_edit.setText(str(tmp_path / "points.v2"))
        obj_dlg._on_export_clicked()
        assert obj_dlg._target_path is not None
        assert obj_dlg._target_path.name == "points.v2.csv"
    finally:
        obj_dlg.close()

    # 5. GeoreferenceDialog: NaN / Inf отклоняются ДО записи в ControlPoint
    raw_img = tmp_path / "raw.png"
    QImage(32, 32, QImage.Format.Format_RGBA8888).save(str(raw_img))
    geo_dlg = GeoreferenceDialog(raw_img)
    try:
        geo_dlg._control_points.append(ControlPoint(id="1", name="1", pixel_x=5.0, pixel_y=6.0, target_x=100.0, target_y=200.0))
        geo_dlg._populate_table()
        item = geo_dlg.points_table.item(0, 1)
        assert item is not None
        item.setText("nan")
        qapp.processEvents()
        assert geo_dlg._control_points[0].pixel_x == 5.0
    finally:
        geo_dlg.close()

    # 6. OpenMapDialog: _extract_clean_crs и валидный GeoTIFF рядом с .tfw не уходит в ручную привязку
    assert _extract_clean_crs(None, "ESRI:102001 (Canada_Albers_Equal_Area_Conic)") == "ESRI:102001"
    tif_path = tmp_path / "geotiff.tif"
    tif_path.write_bytes(b"fake")
    tif_path.with_suffix(".tfw").write_text("1.0\n0.0\n0.0\n-1.0\n500000.0\n6000000.0\n", encoding="utf-8")

    class _FakeRB:
        def inspect_raster(self, p):
            return {"width": 64, "height": 64, "band_count": 3, "crs": "EPSG:32639", "is_valid_georef": True, "extent": [0, 0, 64, 64]}

    monkeypatch.setattr("rme_mapper.backends.BackendFactory.supports_geotiff", classmethod(lambda cls: True))
    monkeypatch.setattr("rme_mapper.ui.open_map_dialog.get_raster_backend", lambda: _FakeRB())
    om_dlg = OpenMapDialog()
    try:
        launched = []
        monkeypatch.setattr(om_dlg, "_launch_georeference_dialog", lambda p: launched.append(p))
        om_dlg._set_file_path(tif_path)
        assert launched == []
        assert om_dlg._is_raster is True
    finally:
        om_dlg.close()


def test_med01_groups_panel_and_validation_search(qapp, monkeypatch):
    """MED-01: GroupsPanel._total_count до обновления счётчиков и поиск по warnings вместе с errors."""
    from PySide6.QtWidgets import QMenu

    from rme_mapper.importers.models import ImportRow, ImportRowError, ImportRowWarning
    from rme_mapper.ui.models.validation_table_model import ValidationTableModel
    from rme_mapper.ui.panels.groups_panel import GroupsPanel

    panel = GroupsPanel()
    try:
        assert panel._total_count == 0
        # Симулируем контекстное меню на системном узле "Все объекты" до set_counts
        panel._refresh_tree_items()
        item_all = panel.groups_tree.topLevelItem(0)
        assert item_all is not None
        pos = panel.groups_tree.visualItemRect(item_all).center()
        monkeypatch.setattr(QMenu, "exec", lambda *a, **kw: None)
        panel._show_context_menu(pos)
    finally:
        panel.close()

    row_both = ImportRow(
        row_number=1,
        raw_data={"name": "Alpha"},
        errors=[ImportRowError(row_number=1, field="latitude", code="import.err.missing_coordinates")],
        warnings=[ImportRowWarning(row_number=1, field="stroke_width", code="import.warn.invalid_stroke_width", params={"value": "badflag_token"}, raw_value="badflag_token")],
    )
    model = ValidationTableModel()
    model.set_rows([row_both])
    model.set_search_query("badflag_token")
    assert model.rowCount() == 1


def test_med02_points_panel_controller_and_bulk_style(qapp, monkeypatch):
    """MED-02: Перенумерация remove_rows_by_point_ids, select_point_ids без скрытых, меню PointController и BulkPointStyleDialog."""
    from PySide6.QtWidgets import QMenu, QMessageBox

    from rme_mapper.i18n import tr
    from rme_mapper.ui.bulk_point_style_dialog import BulkPointStyleDialog
    from rme_mapper.ui.panels.points_panel import PointsPanel

    # 1. PointsPanel: remove_rows_by_point_ids перенумеровывает столбец 0; select_point_ids пропускает скрытые
    panel = PointsPanel()
    try:
        p1 = MapPoint(id="id1", name="One", latitude=1.0, longitude=1.0)
        p2 = MapPoint(id="id2", name="Two", latitude=2.0, longitude=2.0)
        p3 = MapPoint(id="id3", name="Three", latitude=3.0, longitude=3.0)
        panel.populate_points_batch([p1, p2, p3])
        panel.remove_rows_by_point_ids(["id1"])
        assert panel.points_table.rowCount() == 2
        assert panel.points_table.item(0, 0).text() == "1"
        assert panel.points_table.item(1, 0).text() == "2"

        panel.points_table.setRowHidden(0, True)
        panel.select_point_ids(["id2", "id3"])
        assert panel.selected_point_ids() == ["id3"]
    finally:
        panel.close()

    # 2. BulkPointStyleDialog: point_count=7 отображается без списка точек и NaN радиус отклоняется
    dlg = BulkPointStyleDialog(parent=None, points=None, point_count=7)
    try:
        assert "7" in dlg.windowTitle()
        assert "7" in dlg.info_label.text()
        dlg.chk_radius.setChecked(True)
        dlg.edit_radius.setText("nan")
        warns = []
        monkeypatch.setattr(QMessageBox, "warning", lambda *a, **kw: warns.append(a[2] if len(a) > 2 else ""))
        dlg._validate_and_accept()
        assert len(warns) == 1
    finally:
        dlg.close()

    # 3. PointController: скрытое групповое меню показывает show_object, одиночное синхронизирует кликнутую строку, workflows обновляют properties_panel
    win = MainWindow()
    win.resize(900, 700)
    win.show()
    qapp.processEvents()
    try:
        pa = MapPoint(id="pa", name="PA", latitude=55.0, longitude=37.0, visible=False, group_id=None, category="")
        pb = MapPoint(id="pb", name="PB", latitude=55.1, longitude=37.1, visible=False, group_id=None, category="")
        win.point_controller._cmd_add_point(pa)
        win.point_controller._cmd_add_point(pb)

        win.points_panel.select_point_ids(["pa", "pb"])
        seen_actions: list[str] = []

        class _FakeMenu(QMenu):
            def exec(self, *args, **kwargs):
                seen_actions.extend(a.text() for a in self.actions() if a.text())
                return None

        monkeypatch.setattr("rme_mapper.ui.controllers.point_controller.QMenu", _FakeMenu)
        from PySide6.QtCore import QPoint
        monkeypatch.setattr(
            win.points_panel.points_table,
            "itemAt",
            lambda pos: win.points_panel.points_table.item(0 if pos.y() < 10 else 1, 1),
        )
        win.point_controller.show_context_menu(QPoint(5, 5))
        assert tr("action.show_object") in seen_actions
        assert tr("action.hide_object") not in seen_actions

        # Клик правой кнопкой на невыделенную строку 1 при одиночном выделении строки 0 выделяет строку 1
        win.points_panel.points_table.selectRow(0)
        win.point_controller.show_context_menu(QPoint(5, 20))
        assert win.points_panel.selected_point_ids() == ["pb"]

        # move_points_to_group_workflow и bulk_change_category_workflow вызывают properties_panel.update_properties
        updated = []
        monkeypatch.setattr(win.properties_panel, "update_properties", lambda p: updated.append((p.id, p.category)))
        win.point_controller.move_points_to_group_workflow(None, ["pb"])
        assert updated and updated[-1][0] == "pb"
    finally:
        win.project_controller.set_modified(False)
        win.close()


def test_med03_ndarray_channels_and_scale_overlay(qapp):
    """MED-03: Поддержка c=1/2/3/4 в MapCanvas.add_raster_item и геометрия/ratio ScaleOverlayWidget."""
    import numpy as np
    from PySide6.QtGui import QFont, QFontMetrics
    from rme_mapper.maps.map_canvas import MapCanvas
    from rme_mapper.maps.scale_overlay import ScaleOverlayWidget
    from rme_mapper.models.map_layer import MapLayer

    canvas = MapCanvas()
    try:
        layer = MapLayer(id="r1", source_name="r", display_name="R", geometry_type="raster", crs="EPSG:3857")
        for arr in (
            np.full((8, 10), 128, dtype=np.uint8),
            np.full((8, 10, 2), 200, dtype=np.uint8),
            np.full((8, 10, 3), 180, dtype=np.uint8),
            np.full((8, 10, 4), 220, dtype=np.uint8),
        ):
            canvas.add_raster_item(layer, arr, (1.0, 0.0, 0.0, 0.0, -1.0, 8.0), (10, 8))
            assert canvas._raster_item is not None
            assert canvas._raster_item.pixmap().width() == 10
            assert canvas._raster_item.pixmap().height() == 8
    finally:
        canvas.close()

    overlay = ScaleOverlayWidget()
    try:
        overlay.update_scale("50 м", 100.0, 0.0)
        assert overlay._ratio_text == ""

        overlay.update_scale("10 м", 50.0, 10_000_000.0)
        assert overlay._ratio_text.startswith("≈1:")
        fm = QFontMetrics(QFont("Segoe UI", 9, QFont.Weight.Bold))
        assert overlay.width() >= fm.horizontalAdvance(overlay._ratio_text) + 20
    finally:
        overlay.close()


def test_med04_dialogs_and_workspace_layout(qapp, tmp_path, monkeypatch):
    """MED-04: Verify CrsPicker, ClipboardCoordinatesDialog, OnlineBasemapDialog, WorkspaceLayoutMixin, SettingsDialog, PointDialog, AuditFeaturesMixin."""
    from types import SimpleNamespace
    from PySide6.QtCore import QSettings
    from PySide6.QtWidgets import QMessageBox, QSplitter, QWidget

    from rme_mapper.models.map_point import MapPoint
    from rme_mapper.models.online_provider import MapType, ProviderRegistry
    from rme_mapper.services.app_settings_service import AppSettingsService
    from rme_mapper.ui.audit_features import AuditFeaturesMixin
    from rme_mapper.ui.clipboard_coordinates_dialog import ClipboardCoordinatesDialog
    from rme_mapper.ui.crs_picker import CrsPicker
    from rme_mapper.ui.online_basemap_dialog import OnlineBasemapDialog
    from rme_mapper.ui.point_dialog import PointDialog
    from rme_mapper.ui.settings_dialog import SettingsDialog
    from rme_mapper.ui.workspace_layout import WorkspaceLayoutMixin

    # 1. CrsPicker: placeholder itemData ignored & "мск" searches MSK/Gauss-Kruger zones
    picker = CrsPicker("EPSG:4326")
    try:
        picker.edit.setText("EPSG:3857")
        picker._on_favorite_activated(0)
        assert picker.edit.text() == "EPSG:3857"
        picker.results.insertItem(0, "-- Choose --", "")
        picker._on_result_activated(0)
        assert picker.edit.text() == "EPSG:3857"
        picker.search_crs("мск")
        assert picker.results.count() > 0
    finally:
        picker.close()

    # 2. ClipboardCoordinatesDialog: default EPSG:4326 & MAX_PROJECT_POINTS checked after row parsing
    dlg_clip = ClipboardCoordinatesDialog("55.75\t37.62\nbad_row", existing_count=100_000)
    try:
        assert dlg_clip.crs_picker.edit.text() == "EPSG:4326"
        assert "100" in dlg_clip.status.text() or dlg_clip.table.rowCount() == 2

        dlg_clip_ok = ClipboardCoordinatesDialog("55.75\t37.62\n55.76\t37.63", existing_count=99_998)
        try:
            assert len(dlg_clip_ok.points) == 2
        finally:
            dlg_clip_ok.close()

        dlg_clip_over = ClipboardCoordinatesDialog("55.75\t37.62\n55.76\t37.63", existing_count=99_999)
        try:
            assert dlg_clip_over.points == []
            assert not dlg_clip_over.buttons.button(dlg_clip_over.buttons.StandardButton.Ok).isEnabled()
        finally:
            dlg_clip_over.close()
    finally:
        dlg_clip.close()

    # 3. OnlineBasemapDialog: clearing built-in key persists "", custom URL param name detected dynamically
    settings_svc = AppSettingsService(QSettings(str(tmp_path / "settings_bm.ini"), QSettings.Format.IniFormat))
    settings_svc.set_provider_api_key("mapbox_satellite", "old_key")
    dlg_bm = OnlineBasemapDialog(None, settings_service=settings_svc)
    try:
        dlg_bm._rb_satellite.setChecked(True)
        idx_mb = dlg_bm._provider_combo.findData("mapbox_satellite")
        assert idx_mb >= 0
        dlg_bm._provider_combo.setCurrentIndex(idx_mb)
        dlg_bm._key_edit.setText("")
        dlg_bm._on_accept()
        assert settings_svc.get_provider_api_key("mapbox_satellite") in (None, "")

        dlg_bm._rb_custom.setChecked(True)
        dlg_bm._custom_name.setText("Custom Token")
        dlg_bm._url_edit.setText("https://tiles.example.com/{z}/{x}/{y}.png?api_key={api_key}")
        dlg_bm._key_edit.setText("secret123")
        dlg_bm._on_accept()
        custom_list = settings_svc.get_custom_providers()
        assert len(custom_list) == 1
        assert custom_list[0]["api_key_param_name"] == "api_key"
    finally:
        dlg_bm.close()

    # 4. WorkspaceLayoutMixin._read_workspace_sizes: matches 3-pane splitter when points_bottom=True
    class _DummyLayout(WorkspaceLayoutMixin):
        def __init__(self):
            self.workspace_splitter = QSplitter()
            self.workspace_splitter.addWidget(QWidget())
            self.workspace_splitter.addWidget(QWidget())
            self.workspace_splitter.addWidget(QWidget())
            self._settings_service = SimpleNamespace(
                _get_string_list=lambda key: ["200", "500", "300"] if key == "ui/workspace_sizes" else []
            )

    dummy_layout = _DummyLayout()
    assert dummy_layout._read_workspace_sizes() == [200, 500, 300]

    # 5. SettingsDialog: validates hex color and radius > 0 when zone is enabled
    dlg_set = SettingsDialog(settings_svc)
    try:
        set_warnings = []
        monkeypatch.setattr(QMessageBox, "warning", lambda *a, **kw: set_warnings.append(a))
        dlg_set.color.setText("not-a-color")
        dlg_set.accept()
        assert len(set_warnings) == 1
        assert dlg_set.result() != SettingsDialog.DialogCode.Accepted
    finally:
        dlg_set.close()

    # 6. PointDialog: invalid stroke RGB does not crash/mutate preview & unchecked zone preserves radius
    pt = MapPoint(name="Test", latitude=55.75, longitude=37.62, zone_enabled=False, radius_m=250.0)
    dlg_pt = PointDialog(point=pt)
    try:
        dlg_pt.stroke_r_edit.setText("999")
        dlg_pt._on_style_input_changed()
        assert dlg_pt.stroke_r_edit.text() == "999"
        dlg_pt.stroke_r_edit.setText("30")
        dlg_pt.zone_chk.setChecked(False)
        dlg_pt.zone_radius_edit.setText("320")
        dlg_pt._validate_and_submit()
        data = dlg_pt.get_point_data()
        assert data is not None
        assert data.zone_enabled is False
        assert abs(data.radius_m - 320.0) < 1e-6
    finally:
        dlg_pt.close()

    # 7. AuditFeaturesMixin.import_field_file: triggered(bool) does not pass bool as file path
    from PySide6.QtWidgets import QFileDialog
    dialog_opened = []

    class _DummyAudit(AuditFeaturesMixin):
        map_controller = SimpleNamespace(active_profile=object())

    dummy_audit = _DummyAudit()
    monkeypatch.setattr(
        QFileDialog,
        "getOpenFileName",
        lambda *a, **kw: dialog_opened.append(True) or ("", ""),
    )
    dummy_audit.import_field_file(False)
    assert dialog_opened == [True]


def test_med05_models_validation_field_import_and_capabilities(qapp, tmp_path, monkeypatch):
    """MED-05: Verify custom provider IDs, MapProfile control_points, NaN validation, GPX/KML parsing, .tsv drag-drop, and startup init order."""
    from pathlib import Path
    from types import SimpleNamespace
    from PySide6.QtCore import QMimeData, QPointF, Qt, QUrl

    from rme_mapper.coordinates.validator import CoordinateValidator, ValidationError
    from rme_mapper.models.georeference import ControlPoint
    from rme_mapper.models.map_profile import MapProfile
    from rme_mapper.models.online_provider import ProviderRegistry
    from rme_mapper.models.point_style import StyleValidator
    from rme_mapper.services.field_import_service import read_field_file
    from rme_mapper.services.runtime_capabilities import RuntimeCapabilities
    from rme_mapper.ui.main_window import MainWindow

    # 1. Distinct IDs for Cyrillic custom providers & no duplicate keys in OnlineTileProvider.to_dict AST
    import ast
    provider_ast = ast.parse(Path("d:/RME-Mapper/src/rme_mapper/models/online_provider.py").read_text(encoding="utf-8"))
    for node in ast.walk(provider_ast):
        if isinstance(node, ast.FunctionDef) and node.name == "to_dict":
            for inner in ast.walk(node):
                if isinstance(inner, ast.Dict):
                    str_keys = [k.value for k in inner.keys if isinstance(k, ast.Constant) and isinstance(k.value, str)]
                    assert len(str_keys) == len(set(str_keys)), f"Duplicate keys in to_dict: {str_keys}"

    p1 = ProviderRegistry.create_custom_provider(name="Москва", url_template="https://a.example.com/{z}/{x}/{y}.png", attribution="© A")
    p2 = ProviderRegistry.create_custom_provider(name="Казань", url_template="https://b.example.com/{z}/{x}/{y}.png", attribution="© B")
    try:
        assert p1.id != p2.id
    finally:
        ProviderRegistry._providers.pop(p1.id, None)
        ProviderRegistry._providers.pop(p2.id, None)

    # 2. Top-level control_points in MapProfile converted to ControlPoint
    profile = MapProfile.from_dict({
        "id": "m1",
        "name": "M1",
        "source": {"type": "georeferenced_image", "path": "img.png"},
        "control_points": [{"pixel_x": 1.0, "pixel_y": 2.0, "world_x": 37.5, "world_y": 55.7}],
    })
    assert profile.control_points is not None and len(profile.control_points) == 1
    assert isinstance(profile.control_points[0], ControlPoint)

    # 3. Point style NaN raises ValidationError (no raw ValueError from round)
    for fn in (
        StyleValidator.validate_size,
        StyleValidator.validate_stroke_width,
        StyleValidator.validate_border_width,
        StyleValidator.validate_opacity,
    ):
        try:
            fn(float("nan"))
            raise AssertionError(f"Expected ValidationError from {fn.__name__}")
        except ValidationError:
            pass

    # 4. DMS seconds NaN/Inf raises ValidationError
    for args in ((55, 30, "nan", "N"), (55, 30, float("inf"), "N")):
        try:
            CoordinateValidator.validate_dms_latitude(*args)
            raise AssertionError("Expected ValidationError for nonfinite DMS seconds")
        except ValidationError:
            pass

    # 5. Field import GPX missing lat/lon -> ValueError; KML spaces after comma & unnamed line numbering
    bad_gpx = tmp_path / "bad.gpx"
    bad_gpx.write_text('<gpx><wpt lat="55.7"><name>A</name></wpt></gpx>', encoding="utf-8")
    try:
        read_field_file(bad_gpx)
        raise AssertionError("Expected ValueError for GPX missing lon")
    except ValueError:
        pass

    kml_file = tmp_path / "lines.kml"
    kml_file.write_text(
        '<kml><Document>'
        '<Placemark><Point><coordinates>37.6, 55.7, 0</coordinates></Point></Placemark>'
        '<Placemark><LineString><coordinates>37.6, 55.7 37.7, 55.8</coordinates></LineString></Placemark>'
        '<Placemark><LineString><coordinates>37.8, 55.9 37.9, 56.0</coordinates></LineString></Placemark>'
        '</Document></kml>',
        encoding="utf-8",
    )
    pts, anns = read_field_file(kml_file)
    assert len(pts) == 1
    assert abs(pts[0].longitude - 37.6) < 1e-6
    assert len(anns) == 2
    assert anns[0]["name"] == "1" and anns[1]["name"] == "2"

    # 6. MainWindow accepts .tsv on dragEnterEvent and dropEvent
    tsv_path = tmp_path / "points.tsv"
    tsv_path.write_text("lat\tlon\n55.7\t37.6\n", encoding="utf-8")
    opened_wizard = []
    accepted_flags = []

    class _DummyEvent:
        def __init__(self, path: Path):
            self._mime = QMimeData()
            self._mime.setUrls([QUrl.fromLocalFile(str(path))])
        def mimeData(self):
            return self._mime
        def acceptProposedAction(self):
            accepted_flags.append(True)
        def ignore(self):
            accepted_flags.append(False)

    dummy_win = SimpleNamespace(
        import_controller=SimpleNamespace(open_import_wizard=lambda p: opened_wizard.append(p)),
        open_map=lambda p: None,
        project_controller=SimpleNamespace(open_project_workflow=lambda p: None),
        import_field_file=lambda p: None,
    )
    MainWindow.dragEnterEvent(dummy_win, _DummyEvent(tsv_path))
    MainWindow.dropEvent(dummy_win, _DummyEvent(tsv_path))
    assert accepted_flags == [True, True]
    assert opened_wizard == [tsv_path]

    # 7. RuntimeCapabilities unknown source_type returns False & main.py calls log_runtime_environment after QApplication
    assert RuntimeCapabilities.supports_source_type("unknown_backend") is False
    main_src = Path("d:/RME-Mapper/src/rme_mapper/main.py").read_text(encoding="utf-8")
    assert main_src.index("QApplication(sys.argv)") < main_src.index("log_runtime_environment()")












