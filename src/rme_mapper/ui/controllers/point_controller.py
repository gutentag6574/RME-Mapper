"""Контроллер управления пользовательскими точками."""

from collections.abc import Callable
import copy
import logging
from typing import Any

from PySide6.QtCore import QObject
from PySide6.QtWidgets import QApplication, QMenu, QMessageBox, QWidget

from rme_mapper.i18n import tr
from rme_mapper.maps.map_canvas import MapCanvas
from rme_mapper.models.map_point import MapPoint
from rme_mapper.models.map_profile import MapProfile
from rme_mapper.services.coordinate_service import CoordinateService
from rme_mapper.services.geodesic_service import GeodesicService
from rme_mapper.services.point_service import PointService
from rme_mapper.services.undo_manager import (
    AddPointCommand,
    BulkEditStyleCommand,
    DeleteMultiplePointsCommand,
    DeletePointCommand,
    EditPointCommand,
    UndoManager,
)
from rme_mapper.ui.bulk_point_style_dialog import BulkPointStyleDialog
from rme_mapper.ui.panels.points_panel import PointsPanel
from rme_mapper.ui.panels.properties_panel import PropertiesPanel, get_symbol_display_name
from rme_mapper.ui.point_dialog import PointDialog

logger = logging.getLogger("rme_mapper.ui.controllers.point_controller")


class PointController(QObject):
    """Контроллер для сценариев добавления, редактирования, удаления и отображения точек."""

    def __init__(
        self,
        parent_widget: QWidget,
        point_service: PointService,
        points_panel: PointsPanel,
        properties_panel: PropertiesPanel,
        map_canvas: MapCanvas,
        get_active_crs: Callable[[], str],
        get_active_profile: Callable[[], MapProfile | None],
        get_map_path: Callable[[], Any],
        get_boundary_geometry: Callable[[], Any],
        on_modified: Callable[[], None],
        set_status_message: Callable[[str, int], None] | None = None,
        set_modified: Callable[[bool], None] | None = None,
        undo_manager: UndoManager | None = None,
    ) -> None:
        super().__init__(parent_widget)
        self._parent = parent_widget
        self._point_service = point_service
        self._points_panel = points_panel
        self._properties_panel = properties_panel
        self._map_canvas = map_canvas

        self._get_active_crs = get_active_crs
        self._get_active_profile = get_active_profile
        self._get_map_path = get_map_path
        self._get_boundary_geometry = get_boundary_geometry
        self._on_modified = on_modified
        self._set_status_message = set_status_message
        self._set_modified = set_modified

        self._undo_manager = undo_manager or UndoManager()
        self._undo_manager.set_on_state_changed(self._on_undo_state_changed)

        # Маппинг индекса строки таблицы на ID точки: row_index -> point_id
        self._table_point_ids: list[str] = []

        self._connect_signals()

    def _connect_signals(self) -> None:
        self._points_panel.add_clicked.connect(lambda: self.add_point_workflow())
        self._points_panel.edit_clicked.connect(self.edit_point_workflow)
        self._points_panel.delete_clicked.connect(lambda: self.delete_point_workflow(confirm=True))
        self._points_panel.row_double_clicked.connect(self.on_table_row_double_clicked)
        self._points_panel.selection_changed.connect(self.on_table_selection_changed)
        self._points_panel.custom_context_menu_requested.connect(self.show_context_menu)

        self._map_canvas.map_point_clicked.connect(self.on_map_point_clicked)
        self._map_canvas.add_point_mode_cancelled.connect(self.cancel_add_point_on_map_mode)

    @property
    def undo_manager(self) -> UndoManager:
        return self._undo_manager

    def _on_undo_state_changed(self) -> None:
        """Синхронизация dirty state проекта при изменении стеков Undo/Redo."""
        if self._undo_manager.is_clean:
            if self._set_modified:
                self._set_modified(False)
            else:
                self._on_modified()
        else:
            if self._set_modified:
                self._set_modified(True)
            else:
                self._on_modified()

    def undo(self) -> bool:
        """Отмена последнего действия."""
        if self._undo_manager.can_undo:
            desc = self._undo_manager.undo_description
            success = self._undo_manager.undo()
            if success:
                self._set_status(tr("status.undo_done", desc=desc), 2000)
            return success
        return False

    def redo(self) -> bool:
        """Повтор отмененного действия."""
        if self._undo_manager.can_redo:
            desc = self._undo_manager.redo_description
            success = self._undo_manager.redo()
            if success:
                self._set_status(tr("status.redo_done", desc=desc), 2000)
            return success
        return False

    def retranslate_ui(self) -> None:
        """Перевод динамических данных в таблице точек (форма, радиус) и панели свойств."""
        table = self._points_panel.points_table
        for row, point_id in enumerate(self._table_point_ids):
            point = self._point_service.get_point(point_id)
            if point:
                shape_item = table.item(row, 4)
                if shape_item:
                    shape_item.setText(get_symbol_display_name(point.symbol))
                radius_item = table.item(row, 5)
                if radius_item:
                    radius_item.setText(GeodesicService.format_radius(point.radius_m, point.zone_enabled))

        row = self._points_panel.selected_row()
        if row is not None and 0 <= row < len(self._table_point_ids):
            pt = self._point_service.get_point(self._table_point_ids[row])
            if pt:
                self._properties_panel.update_properties(pt)

    @property
    def table_point_ids(self) -> list[str]:
        """Список идентификаторов точек в порядке строк таблицы."""
        return self._table_point_ids

    def _set_status(self, text: str, timeout: int = 0) -> None:
        if self._set_status_message:
            self._set_status_message(text, timeout)

    # -------------------------------------------------------------------------
    # Низкоуровневые операции добавления/удаления/обновления точек
    # -------------------------------------------------------------------------

    def _cmd_add_point(self, point: MapPoint, row_index: int | None = None) -> None:
        """Низкоуровневая вставка точки в модель, таблицу и на холст."""
        self._point_service._points[point.id] = point
        self.add_point_to_table(point, row_index=row_index)
        self._render_point_on_canvas(point)
        self._on_undo_state_changed()

    def _cmd_remove_point(self, point_id: str) -> None:
        """Низкоуровневое удаление точки из модели, таблицы и с холста."""
        if point_id in self._table_point_ids:
            row = self._table_point_ids.index(point_id)
            self._table_point_ids.remove(point_id)
            self._points_panel.remove_row(row)

        self._point_service.remove_point(point_id)
        self._map_canvas.remove_user_point(point_id)
        self._on_undo_state_changed()

    def _cmd_update_point(self, point: MapPoint) -> None:
        """Низкоуровневое обновление параметров точки в модели, таблице и на холсте."""
        self._point_service.update_point_object(point)
        if point.id in self._table_point_ids:
            row = self._table_point_ids.index(point.id)
            self.update_point_in_table(row, point)
        self._render_point_on_canvas(point, is_update=True)

        # Если точка выделена, обновить свойства
        row = self._points_panel.selected_row()
        if row is not None and 0 <= row < len(self._table_point_ids):
            if self._table_point_ids[row] == point.id:
                self._properties_panel.update_properties(point)
        self._on_undo_state_changed()

    # -------------------------------------------------------------------------
    # Сценарии пользователя
    # -------------------------------------------------------------------------

    def add_point_workflow(
        self,
        initial_lat: float | None = None,
        initial_lon: float | None = None,
    ) -> None:
        """Сценарий создания новой пользовательской точки."""
        if self._get_active_profile() is None and self._get_map_path() is None:
            QMessageBox.information(
                self._parent,
                tr("dialog.no_map_title"),
                tr("dialog.no_map_text"),
            )
            return

        profile = self._get_active_profile()
        active_crs = self._get_active_crs()
        auto_name = f"{tr('point.default_name_prefix')} {len(self._point_service) + 1}"

        dialog = PointDialog(
            parent=self._parent,
            boundary_geometry=self._get_boundary_geometry(),
            default_name=auto_name,
            mode="CREATE",
            map_name=profile.name if profile else None,
            map_extent=profile.extent if profile else None,
            map_crs=active_crs,
            initial_lat=initial_lat,
            initial_lon=initial_lon,
        )
        if dialog.exec():
            data = dialog.get_point_data()
            if data:
                point = MapPoint(
                    name=data.name,
                    latitude=data.latitude,
                    longitude=data.longitude,
                    symbol=data.symbol,
                    size=data.size,
                    red=data.red,
                    green=data.green,
                    blue=data.blue,
                    zone_enabled=data.zone_enabled,
                    radius_m=data.radius_m,
                    zone_red=data.zone_red,
                    zone_green=data.zone_green,
                    zone_blue=data.zone_blue,
                    zone_opacity=data.zone_opacity,
                )
                cmd = AddPointCommand(
                    point=point,
                    add_fn=lambda p: self._cmd_add_point(p),
                    remove_fn=lambda pid: self._cmd_remove_point(pid),
                    description=f"{tr('action.add_point')}: {point.name}",
                )
                self._undo_manager.push(cmd, execute=True)
                self._set_status(tr("status.point_added", name=point.name), 3000)

    def _get_selected_point_ids(self) -> list[str]:
        """Возвращает список ID выделенных точек с fallback на _table_point_ids для обратной совместимости."""
        pids = self._points_panel.selected_point_ids()
        if not pids:
            rows = self._points_panel.selected_rows()
            pids = [
                self._table_point_ids[r]
                for r in rows
                if 0 <= r < len(self._table_point_ids)
            ]
        return pids

    def edit_point_workflow(self) -> None:
        """Сценарий редактирования выбранной пользовательской точки."""
        selected_ids = self._get_selected_point_ids()
        if len(selected_ids) != 1:
            return

        point_id = selected_ids[0]
        point = self._point_service.get_point(point_id)
        if not point:
            return

        profile = self._get_active_profile()
        active_crs = self._get_active_crs()

        dialog = PointDialog(
            parent=self._parent,
            boundary_geometry=self._get_boundary_geometry(),
            point=point,
            mode="EDIT",
            map_name=profile.name if profile else None,
            map_extent=profile.extent if profile else None,
            map_crs=active_crs,
        )
        if dialog.exec():
            data = dialog.get_point_data()
            if data:
                before_pt = copy.deepcopy(point)
                after_pt = copy.deepcopy(point)
                after_pt.name = data.name
                after_pt.latitude = data.latitude
                after_pt.longitude = data.longitude
                after_pt.symbol = data.symbol
                after_pt.size = data.size
                after_pt.red = data.red
                after_pt.green = data.green
                after_pt.blue = data.blue
                after_pt.zone_enabled = data.zone_enabled
                after_pt.radius_m = data.radius_m
                after_pt.zone_red = data.zone_red
                after_pt.zone_green = data.zone_green
                after_pt.zone_blue = data.zone_blue
                after_pt.zone_opacity = data.zone_opacity

                cmd = EditPointCommand(
                    before_point=before_pt,
                    after_point=after_pt,
                    apply_fn=lambda p: self._cmd_update_point(p),
                    description=f"{tr('action.edit_point')}: {after_pt.name}",
                )
                self._undo_manager.push(cmd, execute=True)
                self._set_status(tr("status.point_updated", name=after_pt.name), 3000)
                logger.info("Точка '%s' (id=%s) успешно обновлена", after_pt.name, after_pt.id)

    def delete_point_workflow(self, confirm: bool = False) -> None:
        """Сценарий удаления выбранных в таблице точек (одиночного или группового)."""
        selected_ids = self._get_selected_point_ids()
        if not selected_ids:
            return

        # Групповое удаление
        if len(selected_ids) > 1:
            if confirm:
                reply = QMessageBox.question(
                    self._parent,
                    tr("dialog.confirm_delete_multiple_title"),
                    tr("dialog.confirm_delete_multiple_text", count=len(selected_ids)),
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.No,
                )
                if reply != QMessageBox.StandardButton.Yes:
                    return

            pts_with_indices: list[tuple[MapPoint, int]] = []
            for pid in selected_ids:
                pt = self._point_service.get_point(pid)
                if pt and pid in self._table_point_ids:
                    idx = self._table_point_ids.index(pid)
                    pts_with_indices.append((pt, idx))

            cmd = DeleteMultiplePointsCommand(
                points_with_indices=pts_with_indices,
                restore_fn=lambda p, idx: self._cmd_add_point(p, row_index=idx),
                remove_fn=lambda pid: self._cmd_remove_point(pid),
                description=f"{tr('action.delete_selected')} ({len(pts_with_indices)})",
            )
            self._undo_manager.push(cmd, execute=True)
            self._points_panel.set_buttons_enabled(edit=False, delete=False)
            self._properties_panel.clear()
            self._set_status(tr("status.point_deleted"), 3000)
            return

        # Одиночное удаление
        point_id = selected_ids[0]
        point = self._point_service.get_point(point_id)
        if not point or point_id not in self._table_point_ids:
            return

        if confirm:
            reply = QMessageBox.question(
                self._parent,
                tr("dialog.confirm_delete_title"),
                tr("dialog.confirm_delete_text"),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
                return

        row = self._table_point_ids.index(point_id)
        cmd = DeletePointCommand(
            point=point,
            row_index=row,
            restore_fn=lambda p, idx: self._cmd_add_point(p, row_index=idx),
            remove_fn=lambda pid: self._cmd_remove_point(pid),
            description=f"{tr('action.delete_point')}: {point.name}",
        )
        self._undo_manager.push(cmd, execute=True)
        self._points_panel.set_buttons_enabled(edit=False, delete=False)
        self._properties_panel.clear()
        self._set_status(tr("status.point_deleted"), 3000)
        logger.info("Точка с ID %s успешно удалена", point_id)

    def bulk_edit_style_workflow(self) -> None:
        """Сценарий массового редактирования стиля выбранных точек."""
        selected_ids = self._get_selected_point_ids()
        if not selected_ids:
            return

        points = [self._point_service.get_point(pid) for pid in selected_ids]
        valid_points = [p for p in points if p is not None]
        if not valid_points:
            return

        dialog = BulkPointStyleDialog(self._parent, points=valid_points)
        if dialog.exec():
            changes = dialog.get_style_changes()
            if not changes:
                return

            before_points = [copy.deepcopy(p) for p in valid_points]
            after_points: list[MapPoint] = []
            for p in valid_points:
                updated_p = copy.deepcopy(p)
                for k, v in changes.items():
                    setattr(updated_p, k, v)
                after_points.append(updated_p)

            def apply_bulk(pts: list[MapPoint]) -> None:
                for p in pts:
                    self._cmd_update_point(p)

            cmd = BulkEditStyleCommand(
                before_points=before_points,
                after_points=after_points,
                apply_fn=apply_bulk,
                description=f"{tr('action.bulk_edit_style')} ({len(valid_points)})",
            )
            self._undo_manager.push(cmd, execute=True)
            self._set_status(tr("status.bulk_styled", count=len(valid_points)), 3000)

    # -------------------------------------------------------------------------
    # Создание точки кликом по карте
    # -------------------------------------------------------------------------

    def start_add_point_on_map_mode(self) -> None:
        """Активация интерактивного режима добавления точки кликом по карте."""
        if self._get_active_profile() is None and self._get_map_path() is None:
            QMessageBox.information(
                self._parent,
                tr("dialog.no_map_title"),
                tr("dialog.no_map_text"),
            )
            return
        self._map_canvas.set_interaction_mode("add_point")
        self._set_status(tr("status.add_point_on_map_hint"))

    def cancel_add_point_on_map_mode(self) -> None:
        """Отмена интерактивного режима добавления точки кликом по карте."""
        self._map_canvas.set_interaction_mode("navigation")
        self._set_status("")

    def on_map_point_clicked(self, map_x: float, map_y: float) -> None:
        """Обработка клика ЛКМ по карте: пересчет координат в WGS84 и открытие диалога."""
        self.cancel_add_point_on_map_mode()
        active_crs = self._get_active_crs()
        try:
            lon_deg, lat_deg = CoordinateService.transform_xy(
                map_x, map_y,
                source_crs=active_crs,
                target_crs="OGC:CRS84",
            )
        except Exception as e:
            logger.warning("Ошибка трансформации координат клика по карте: %s", e)
            return

        self.add_point_workflow(initial_lat=lat_deg, initial_lon=lon_deg)

    # -------------------------------------------------------------------------
    # Быстрая навигация и экстенты
    # -------------------------------------------------------------------------

    def show_all_points(self) -> None:
        """Масштабирование холста для отображения всех зарегистрированных точек."""
        points = self._point_service.get_points()
        if not points:
            return
        active_crs = self._get_active_crs()
        coords: list[tuple[float, float]] = []
        for pt in points:
            mx, my = CoordinateService.transform_xy(
                pt.longitude, pt.latitude,
                source_crs=pt.source_crs,
                target_crs=active_crs,
            )
            coords.append((mx, my))
        self._map_canvas.zoom_to_points(coords)

    def zoom_to_selected(self) -> None:
        """Масштабирование карты по охвату всех выделенных точек."""
        selected_ids = self._get_selected_point_ids()
        if not selected_ids:
            return
        active_crs = self._get_active_crs()
        coords: list[tuple[float, float]] = []
        for pid in selected_ids:
            pt = self._point_service.get_point(pid)
            if pt:
                mx, my = CoordinateService.transform_xy(
                    pt.longitude, pt.latitude,
                    source_crs=pt.source_crs,
                    target_crs=active_crs,
                )
                coords.append((mx, my))
        if coords:
            self._map_canvas.zoom_to_points(coords)

    # -------------------------------------------------------------------------
    # Буфер обмена
    # -------------------------------------------------------------------------

    def copy_selected_coordinates(self) -> None:
        """Копирование координат всех выделенных точек в буфер обмена в формате TSV."""
        selected_ids = self._get_selected_point_ids()
        if not selected_ids:
            return ""

        lines: list[str] = []
        for pid in selected_ids:
            pt = self._point_service.get_point(pid)
            if pt:
                lines.append(f"{pt.name}\t{pt.latitude:.6f}\t{pt.longitude:.6f}")

        text = "\n".join(lines)
        QApplication.clipboard().setText(text)
        self._set_status(tr("status.coords_selected_copied", count=len(lines)), 2000)
        return text

    def copy_coordinates_dd(self, point: MapPoint) -> str:
        """Форматирование координат точки в формате DD."""
        text = f"{point.latitude:.6f}, {point.longitude:.6f}"
        QApplication.clipboard().setText(text)
        self._set_status(tr("status.coords_copied"), 2000)
        return text

    def copy_coordinates_dms(self, point: MapPoint) -> str:
        """Форматирование координат точки в формате DMS."""
        from rme_mapper.ui.point_dialog import decimal_to_dms

        d_lat, m_lat, s_lat = decimal_to_dms(point.latitude)
        d_lon, m_lon, s_lon = decimal_to_dms(point.longitude)
        lat_dir = "N" if point.latitude >= 0 else "S"
        lon_dir = "E" if point.longitude >= 0 else "W"
        s_lat_str = f"{int(round(s_lat)):02d}" if abs(s_lat - round(s_lat)) < 1e-4 else f"{s_lat:04.1f}"
        s_lon_str = f"{int(round(s_lon)):02d}" if abs(s_lon - round(s_lon)) < 1e-4 else f"{s_lon:04.1f}"
        text = f"{d_lat}°{m_lat:02d}'{s_lat_str}\"{lat_dir}, {d_lon}°{m_lon:02d}'{s_lon_str}\"{lon_dir}"
        QApplication.clipboard().setText(text)
        self._set_status(tr("status.coords_copied"), 2000)
        return text

    def copy_coordinates_map_xy(self, point: MapPoint) -> str | None:
        """Форматирование координат точки в системе координат активной карты (X/Y)."""
        if self._get_active_profile() is None and self._get_map_path() is None:
            return None
        active_crs = self._get_active_crs()
        mx, my = CoordinateService.transform_xy(
            point.longitude, point.latitude,
            source_crs=point.source_crs,
            target_crs=active_crs,
        )
        text = f"{mx:.2f}, {my:.2f}"
        QApplication.clipboard().setText(text)
        self._set_status(tr("status.coords_copied"), 2000)
        return text

    # -------------------------------------------------------------------------
    # Синхронизация таблицы и холста
    # -------------------------------------------------------------------------

    def clear_all_points(self) -> None:
        """Полная очистка всех точек из сервиса, карты, таблицы и панели свойств."""
        self._undo_manager.clear()
        self._point_service.clear()
        self._map_canvas.clear_user_points()
        self._points_panel.clear_table()
        self._table_point_ids.clear()
        self._points_panel.set_buttons_enabled(edit=False, delete=False)
        self._properties_panel.clear()

    def add_point_to_table(self, point: MapPoint, row_index: int | None = None) -> None:
        """Добавление или вставка записи о точке в таблицу интерфейса."""
        shape_name = get_symbol_display_name(point.symbol)
        radius_str = GeodesicService.format_radius(point.radius_m, point.zone_enabled)

        if row_index is None or row_index >= len(self._table_point_ids):
            row_num = len(self._table_point_ids) + 1
            self._points_panel.add_row(
                num=str(row_num),
                name=point.name,
                lat=f"{point.latitude:.6f}",
                lon=f"{point.longitude:.6f}",
                shape=shape_name,
                radius=radius_str,
                point_id=point.id,
            )
            self._table_point_ids.append(point.id)
        else:
            self._points_panel.insert_row(
                row=row_index,
                num=str(row_index + 1),
                name=point.name,
                lat=f"{point.latitude:.6f}",
                lon=f"{point.longitude:.6f}",
                shape=shape_name,
                radius=radius_str,
                point_id=point.id,
            )
            self._table_point_ids.insert(row_index, point.id)

    def update_point_in_table(self, row: int, point: MapPoint) -> None:
        """Обновление значений в строке таблицы."""
        shape_name = get_symbol_display_name(point.symbol)
        radius_str = GeodesicService.format_radius(point.radius_m, point.zone_enabled)

        self._points_panel.update_row(
            row=row,
            name=point.name,
            lat=f"{point.latitude:.6f}",
            lon=f"{point.longitude:.6f}",
            shape=shape_name,
            radius=radius_str,
        )

    def _render_point_on_canvas(self, point: MapPoint, is_update: bool = False) -> None:
        """Проецирование координат и отрисовка маркера/зоны на MapCanvas."""
        active_crs = self._get_active_crs()
        mx, my = CoordinateService.transform_xy(
            point.longitude, point.latitude,
            source_crs=point.source_crs,
            target_crs=active_crs,
        )
        zone_poly = None
        if point.zone_enabled and point.radius_m > 0:
            geo_c = GeodesicService.create_geodesic_circle(
                point.longitude, point.latitude, point.radius_m
            )
            zone_poly = CoordinateService.transform_polygon(
                geo_c,
                source_crs="EPSG:4326",
                target_crs=active_crs,
            )

        if is_update:
            self._map_canvas.update_user_point(point, map_x=mx, map_y=my, zone_polygon=zone_poly)
        else:
            self._map_canvas.add_user_point(point, map_x=mx, map_y=my, zone_polygon=zone_poly)

    def reproject_all_points(self, target_crs: str) -> None:
        """Пересчет экранных координат всех точек и зон под новую CRS карты."""
        for pt in self._point_service.get_points():
            mx, my = CoordinateService.transform_xy(
                pt.longitude, pt.latitude,
                source_crs=pt.source_crs,
                target_crs=target_crs,
            )
            zone_poly = None
            if pt.zone_enabled and pt.radius_m > 0:
                geo_circle = GeodesicService.create_geodesic_circle(
                    pt.longitude, pt.latitude, pt.radius_m
                )
                zone_poly = CoordinateService.transform_polygon(
                    geo_circle,
                    source_crs="EPSG:4326",
                    target_crs=target_crs,
                )
            self._map_canvas.add_user_point(pt, map_x=mx, map_y=my, zone_polygon=zone_poly)

    def on_table_row_double_clicked(self, row: int, column: int) -> None:
        """Центрирование карты на выбранной точке."""
        if 0 <= row < len(self._table_point_ids):
            point_id = self._table_point_ids[row]
            point = self._point_service.get_point(point_id)
            if point:
                active_crs = self._get_active_crs()
                mx, my = CoordinateService.transform_xy(
                    point.longitude, point.latitude,
                    source_crs=point.source_crs,
                    target_crs=active_crs,
                )
                self._map_canvas.center_on_map_coordinates(mx, my)
                self._set_status(tr("status.focus_point", name=point.name), 2000)

    def on_table_selection_changed(self) -> None:
        """Реакция на смену выбора в таблице: обновление кнопок, карточки свойств и подписей."""
        selected_ids = self._get_selected_point_ids()
        has_single = len(selected_ids) == 1
        has_any = len(selected_ids) > 0

        self._points_panel.set_buttons_enabled(edit=has_single, delete=has_any)
        self._map_canvas.update_selected_label_ids(set(selected_ids))

        if has_single:
            point = self._point_service.get_point(selected_ids[0])
            if point:
                self._properties_panel.update_properties(point)
                return
        elif len(selected_ids) > 1:
            self._set_status(tr("status.selection_count", count=len(selected_ids)))

        self._properties_panel.clear()

    def show_context_menu(self, pos: Any) -> None:
        """Отображение контекстного меню для строки таблицы."""
        table = self._points_panel.points_table
        item = table.itemAt(pos)
        if item is None:
            return

        selected_ids = self._get_selected_point_ids()
        is_multi = len(selected_ids) > 1
        has_map = self._get_active_profile() is not None or self._get_map_path() is not None

        menu = QMenu(self._parent)

        if is_multi:
            act_bulk_style = menu.addAction(tr("action.bulk_edit_style"))
            act_zoom_sel = menu.addAction(tr("action.zoom_to_selected"))
            act_zoom_sel.setEnabled(has_map)
            act_copy_sel = menu.addAction(tr("action.copy_selected_coords"))
            menu.addSeparator()
            act_delete = menu.addAction(tr("action.delete_selected"))

            action = menu.exec(table.viewport().mapToGlobal(pos))
            if action == act_bulk_style:
                self.bulk_edit_style_workflow()
            elif action == act_zoom_sel:
                self.zoom_to_selected()
            elif action == act_copy_sel:
                self.copy_selected_coordinates()
            elif action == act_delete:
                self.delete_point_workflow(confirm=True)
            return

        # Одиночное выделение
        act_edit = menu.addAction(tr("action.edit_point"))
        act_center = menu.addAction(tr("action.center_on_map"))
        act_center.setEnabled(has_map)

        copy_menu = menu.addMenu(tr("action.copy_coordinates"))
        act_copy_dd = copy_menu.addAction(tr("action.copy_dd"))
        act_copy_dms = copy_menu.addAction(tr("action.copy_dms"))
        act_copy_map_xy = copy_menu.addAction(tr("action.copy_map_xy"))
        act_copy_map_xy.setEnabled(has_map)

        menu.addSeparator()
        act_delete = menu.addAction(tr("action.delete_point"))

        action = menu.exec(table.viewport().mapToGlobal(pos))
        row = table.row(item)
        if 0 <= row < len(self._table_point_ids):
            point = self._point_service.get_point(self._table_point_ids[row])
            if point:
                if action == act_copy_dd:
                    self.copy_coordinates_dd(point)
                    return
                elif action == act_copy_dms:
                    self.copy_coordinates_dms(point)
                    return
                elif action == act_copy_map_xy:
                    self.copy_coordinates_map_xy(point)
                    return

        if action == act_edit:
            self.edit_point_workflow()
        elif action == act_center:
            r = table.currentRow()
            self.on_table_row_double_clicked(r, 0)
        elif action == act_delete:
            self.delete_point_workflow(confirm=True)
