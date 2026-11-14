"""Контроллер управления пользовательскими точками."""
from __future__ import annotations


from collections.abc import Callable
import copy
import logging
import math
from typing import Any

from pyproj.exceptions import ProjError
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
    AssignPointsToGroupCommand,
    BulkChangeCategoryCommand,
    BulkEditPointStyleCommand,
    BulkEditStyleCommand,
    DeleteMultiplePointsCommand,
    DeletePointCommand,
    EditPointCommand,
    MovePointCommand,
    UndoManager,
)
from rme_mapper.ui.bulk_point_style_dialog import BulkPointStyleDialog
from rme_mapper.ui.change_category_dialog import ChangeCategoryDialog
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
        group_service: Any = None,
        group_controller: Any = None,
    ) -> None:
        super().__init__(parent_widget)
        self._parent = parent_widget
        self._point_service = point_service
        self._points_panel = points_panel
        self._properties_panel = properties_panel
        self._map_canvas = map_canvas
        self._group_service = group_service
        self._group_controller = group_controller

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
        self._settings_service: Any = None

        self._connect_signals()

    def set_group_service(self, service: Any) -> None:
        self._group_service = service

    def set_group_controller(self, controller: Any) -> None:
        self._group_controller = controller

    def _connect_signals(self) -> None:
        self._points_panel.add_clicked.connect(lambda: self.add_point_workflow())
        self._points_panel.edit_clicked.connect(self.edit_point_workflow)
        self._points_panel.delete_clicked.connect(lambda: self.delete_point_workflow(confirm=True))
        self._points_panel.row_double_clicked.connect(self.on_table_row_double_clicked)
        self._points_panel.selection_changed.connect(self.on_table_selection_changed)
        self._points_panel.custom_context_menu_requested.connect(self.show_context_menu)

        self._map_canvas.map_point_clicked.connect(self.on_map_point_clicked)
        self._map_canvas.add_point_mode_cancelled.connect(self.cancel_add_point_on_map_mode)
        self._map_canvas.point_moved.connect(self.on_point_moved_on_canvas)
        self._map_canvas.move_point_mode_cancelled.connect(self.cancel_move_point_mode)

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
        self._point_service.insert_point(point, index=row_index)
        self.add_point_to_table(point, row_index=row_index)
        self._render_point_on_canvas(point)
        if self._group_controller:
            self._group_controller.refresh_groups_ui()
        self._on_undo_state_changed()

    def _cmd_remove_point(self, point_id: str) -> None:
        """Низкоуровневое удаление точки из модели, таблицы и с холста."""
        if point_id in self._table_point_ids:
            row = self._table_point_ids.index(point_id)
            self._table_point_ids.remove(point_id)
            self._points_panel.remove_row(row)

        self._point_service.remove_point(point_id)
        self._map_canvas.remove_user_point(point_id)
        if self._group_controller:
            self._group_controller.refresh_groups_ui()
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
        if self._group_controller:
            self._group_controller.refresh_groups_ui()
        self._on_undo_state_changed()

    def _cmd_add_points(self, points: list[MapPoint]) -> None:
        """Пакетная низкоуровневая вставка точек в модель, таблицу и на холст."""
        for p in points:
            self._point_service._points[p.id] = p
        self.render_points_batch(points)
        self.populate_points_table_batch(self._point_service.get_points())
        if self._group_controller:
            self._group_controller.refresh_groups_ui()
        self._on_undo_state_changed()

    def _cmd_remove_points(self, point_ids: list[str]) -> None:
        """Пакетное низкоуровневое удаление точек из модели, таблицы и с холста."""
        pid_set = set(point_ids)
        self._table_point_ids = [pid for pid in self._table_point_ids if pid not in pid_set]
        self._points_panel.remove_rows_by_point_ids(pid_set)

        with self._map_canvas.defer_labels_layout():
            for pid in point_ids:
                self._point_service.remove_point(pid)
                self._map_canvas.remove_user_point(pid)

        if self._group_controller:
            self._group_controller.refresh_groups_ui()
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

        current_gid = None
        if self._group_controller and hasattr(self._group_controller, "_groups_panel"):
            filt = self._group_controller._groups_panel.active_group_filter()
            if filt and filt != "__ungrouped__":
                current_gid = filt

        groups_list = self._group_service.list_groups() if self._group_service else []

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
            categories=self._point_service.get_used_categories(),
            groups=groups_list,
            current_group_id=current_gid,
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
                    object_number=data.object_number,
                    description=data.description,
                    category=data.category,
                    stroke_red=data.stroke_red,
                    stroke_green=data.stroke_green,
                    stroke_blue=data.stroke_blue,
                    stroke_width=data.stroke_width,
                    opacity=data.opacity,
                    zone_border_red=data.zone_border_red,
                    zone_border_green=data.zone_border_green,
                    zone_border_blue=data.zone_border_blue,
                    zone_border_width=data.zone_border_width,
                    zone_border_style=data.zone_border_style,
                    group_id=data.group_id,
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
        groups_list = self._group_service.list_groups() if self._group_service else []

        dialog = PointDialog(
            parent=self._parent,
            boundary_geometry=self._get_boundary_geometry(),
            point=point,
            mode="EDIT",
            map_name=profile.name if profile else None,
            map_extent=profile.extent if profile else None,
            map_crs=active_crs,
            categories=self._point_service.get_used_categories(),
            groups=groups_list,
            current_group_id=point.group_id,
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
                after_pt.object_number = data.object_number
                after_pt.description = data.description
                after_pt.category = data.category
                after_pt.stroke_red = data.stroke_red
                after_pt.stroke_green = data.stroke_green
                after_pt.stroke_blue = data.stroke_blue
                after_pt.stroke_width = data.stroke_width
                after_pt.opacity = data.opacity
                after_pt.zone_border_red = data.zone_border_red
                after_pt.zone_border_green = data.zone_border_green
                after_pt.zone_border_blue = data.zone_border_blue
                after_pt.zone_border_width = data.zone_border_width
                after_pt.zone_border_style = data.zone_border_style
                after_pt.group_id = data.group_id

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

            table_index_map = {pid: i for i, pid in enumerate(self._table_point_ids)}
            pts_with_indices: list[tuple[MapPoint, int]] = []
            for pid in selected_ids:
                pt = self._point_service.get_point(pid)
                if pt and pid in table_index_map:
                    idx = table_index_map[pid]
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

    def bulk_edit_style_workflow(self, points: list[MapPoint] | None = None) -> None:
        """Сценарий массового редактирования стиля выбранных точек или переданного списка точек группы."""
        if points is not None:
            valid_points = [p for p in points if p is not None]
        else:
            selected_ids = self._get_selected_point_ids()
            if not selected_ids:
                return
            points_list = [self._point_service.get_point(pid) for pid in selected_ids]
            valid_points = [p for p in points_list if p is not None]

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
    # Перемещение точки на холсте
    # -------------------------------------------------------------------------

    def start_move_point_mode(self) -> None:
        """Активация режима перемещения точки на холсте."""
        if self._get_active_profile() is None and self._get_map_path() is None:
            QMessageBox.information(
                self._parent,
                tr("dialog.no_map_title"),
                tr("dialog.no_map_text"),
            )
            return
        self._map_canvas.set_interaction_mode("move_point")
        self._set_status(tr("status.move_point_hint"))

    def cancel_move_point_mode(self) -> None:
        """Отмена режима перемещения точки на холсте."""
        if self._map_canvas.interaction_mode == "move_point":
            self._map_canvas.set_interaction_mode("navigation")
            self._set_status("")

    def on_point_moved_on_canvas(
        self, point_id: str, final_x: float, final_y: float, start_x: float, start_y: float
    ) -> None:
        """Обработка завершения перетаскивания точки на холсте: пересчет в WGS84 и сохранение в Undo."""
        pt = self._point_service.get_point(point_id)
        if not pt:
            return

        active_crs = self._get_active_crs()
        try:
            lon, lat = CoordinateService.transform_xy(
                final_x,
                final_y,
                source_crs=active_crs,
                target_crs="OGC:CRS84",
            )
        except Exception as e:
            logger.warning("Ошибка трансформации координат после перемещения точки: %s", e)
            return

        before_pt = copy.deepcopy(pt)
        after_pt = copy.deepcopy(pt)
        after_pt.longitude = lon
        after_pt.latitude = lat

        cmd = MovePointCommand(
            before_point=before_pt,
            after_point=after_pt,
            apply_fn=lambda p: self._cmd_update_point(p),
            description=f"{tr('action.move_point')}: {after_pt.name}",
        )
        self._undo_manager.push(cmd, execute=True)
        self._set_status(tr("status.point_moved", name=after_pt.name, lat=lat, lon=lon), 3000)
        logger.info("Точка '%s' перемещена на координаты lon=%f, lat=%f", after_pt.name, lon, lat)

    def toggle_point_visibility(self, point_id: str | None = None) -> None:
        """Переключение видимости точки (или всех выделенных точек)."""
        if point_id:
            pt = self._point_service.get_point(point_id)
            if not pt:
                return
            before_pt = copy.deepcopy(pt)
            after_pt = copy.deepcopy(pt)
            after_pt.visible = not before_pt.visible

            desc_key = "action.hide_object" if not after_pt.visible else "action.show_object"
            cmd = EditPointCommand(
                before_point=before_pt,
                after_point=after_pt,
                apply_fn=lambda p: self._cmd_update_point(p),
                description=f"{tr(desc_key)}: {after_pt.name}",
            )
            self._undo_manager.push(cmd, execute=True)
            self._set_status(tr("status.object_visibility_changed"), 2000)
            return

        selected_ids = self._get_selected_point_ids()
        if not selected_ids:
            return

        valid_pts = [self._point_service.get_point(pid) for pid in selected_ids]
        valid_pts = [p for p in valid_pts if p is not None]
        if not valid_pts:
            return

        target_visible = not all(p.visible for p in valid_pts)
        before_pts = [copy.deepcopy(p) for p in valid_pts]
        after_pts: list[MapPoint] = []
        for p in valid_pts:
            after_p = copy.deepcopy(p)
            after_p.visible = target_visible
            after_pts.append(after_p)

        def apply_vis(pts: list[MapPoint]) -> None:
            for p in pts:
                self._cmd_update_point(p)

        desc_key = "action.hide_object" if not target_visible else "action.show_object"
        cmd = BulkEditStyleCommand(
            before_points=before_pts,
            after_points=after_pts,
            apply_fn=apply_vis,
            description=f"{tr(desc_key)} ({len(valid_pts)})",
        )
        self._undo_manager.push(cmd, execute=True)
        self._set_status(tr("status.object_visibility_changed"), 2000)

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
            xy = self._safe_transform_point(pt, active_crs)
            if xy is not None:
                coords.append(xy)
        if coords:
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
                xy = self._safe_transform_point(pt, active_crs)
                if xy is not None:
                    coords.append(xy)
        if coords:
            self._map_canvas.zoom_to_points(coords)

    # -------------------------------------------------------------------------
    # Буфер обмена
    # -------------------------------------------------------------------------

    def copy_selected_coordinates(self) -> str:
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
        if self._settings_service is None:
            from rme_mapper.services.app_settings_service import AppSettingsService
            self._settings_service = AppSettingsService()
        settings = self._settings_service
        precision = settings.get_integer("coordinates/precision", 6, 0, 10)
        separator = settings._get_str("coordinates/separator", ", ")
        text = f"{point.latitude:.{precision}f}{separator}{point.longitude:.{precision}f}"
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
        xy = self._safe_transform_point(point, active_crs)
        if xy is None:
            self._set_status(tr("audit.search_invalid"), 3000)
            return None
        mx, my = xy
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
            num_str = point.object_number if point.object_number else str(row_num)
            self._points_panel.add_row(
                num=num_str,
                name=point.name,
                lat=f"{point.latitude:.6f}",
                lon=f"{point.longitude:.6f}",
                shape=shape_name,
                radius=radius_str,
                point_id=point.id,
                object_number=point.object_number,
                category=point.category,
                description=point.description,
                visible=point.visible,
                group_id=point.group_id,
            )
            self._table_point_ids.append(point.id)
        else:
            target_row = max(0, row_index)
            num_str = point.object_number if point.object_number else str(target_row + 1)
            inserted_row = self._points_panel.insert_row(
                row=target_row,
                num=num_str,
                name=point.name,
                lat=f"{point.latitude:.6f}",
                lon=f"{point.longitude:.6f}",
                shape=shape_name,
                radius=radius_str,
                point_id=point.id,
                object_number=point.object_number,
                category=point.category,
                description=point.description,
                visible=point.visible,
                group_id=point.group_id,
            )
            self._table_point_ids.insert(inserted_row, point.id)

    def update_point_in_table(self, row: int, point: MapPoint) -> None:
        """Обновление значений в строке таблицы."""
        shape_name = get_symbol_display_name(point.symbol)
        radius_str = GeodesicService.format_radius(point.radius_m, point.zone_enabled)
        num_str = point.object_number if point.object_number else str(row + 1)

        self._points_panel.update_row(
            row=row,
            num=num_str,
            name=point.name,
            lat=f"{point.latitude:.6f}",
            lon=f"{point.longitude:.6f}",
            shape=shape_name,
            radius=radius_str,
            object_number=point.object_number,
            category=point.category,
            description=point.description,
            visible=point.visible,
            group_id=point.group_id,
            update_group=True,
        )

    @staticmethod
    def _safe_transform_point(point: MapPoint, target_crs: str) -> tuple[float, float] | None:
        """Безопасное перепроецирование координат точки с обработкой ProjError и non-finite."""
        try:
            mx, my = CoordinateService.transform_xy(
                point.longitude,
                point.latitude,
                source_crs=point.source_crs or "EPSG:4326",
                target_crs=target_crs,
            )
            if not (math.isfinite(mx) and math.isfinite(my)):
                logger.warning(
                    "Неконечный результат перепроецирования точки '%s' (%s, %s) в %s",
                    point.name, point.longitude, point.latitude, target_crs,
                )
                return None
            return mx, my
        except (ProjError, ValueError, RuntimeError) as err:
            logger.warning(
                "Ошибка перепроецирования точки '%s' из %s в %s: %s",
                point.name, point.source_crs, target_crs, err,
            )
            return None

    @staticmethod
    def _build_zone_polygon_for_crs(point: MapPoint, target_crs: str):
        """Построение полигона геодезической зоны точки в целевой CRS."""
        if not point.zone_enabled or point.radius_m <= 0:
            return None
        try:
            src_crs = (point.source_crs or "EPSG:4326").strip()
            lon_wgs, lat_wgs = point.longitude, point.latitude
            if src_crs.upper() not in ("EPSG:4326", "OGC:CRS84"):
                lon_wgs, lat_wgs = CoordinateService.transform_xy(
                    point.longitude,
                    point.latitude,
                    source_crs=src_crs,
                    target_crs="EPSG:4326",
                )
            geo_c = GeodesicService.create_geodesic_circle(lon_wgs, lat_wgs, point.radius_m)
            return CoordinateService.transform_polygon(
                geo_c,
                source_crs="EPSG:4326",
                target_crs=target_crs,
            )
        except (ProjError, ValueError, RuntimeError) as err:
            logger.warning("Ошибка построения зоны для точки '%s' в %s: %s", point.name, target_crs, err)
            return None

    def _render_point_on_canvas(self, point: MapPoint, is_update: bool = False) -> None:
        """Проецирование координат и отрисовка маркера/зоны на MapCanvas."""
        active_crs = self._get_active_crs()
        xy = self._safe_transform_point(point, active_crs)
        if xy is None:
            if is_update:
                self._map_canvas.remove_user_point(point.id)
            return
        mx, my = xy
        zone_poly = self._build_zone_polygon_for_crs(point, active_crs)

        if is_update:
            self._map_canvas.update_user_point(point, map_x=mx, map_y=my, zone_polygon=zone_poly)
        else:
            self._map_canvas.add_user_point(point, map_x=mx, map_y=my, zone_polygon=zone_poly)

    def render_points_batch(self, points: list[MapPoint]) -> None:
        """Пакетное проецирование и отрисовка множества точек на холсте."""
        if not points:
            return
        active_crs = self._get_active_crs()
        batch_data = []
        for point in points:
            xy = self._safe_transform_point(point, active_crs)
            if xy is None:
                continue
            mx, my = xy
            zone_poly = self._build_zone_polygon_for_crs(point, active_crs)
            batch_data.append((point, mx, my, zone_poly))

        if batch_data:
            self._map_canvas.add_user_points_batch(batch_data)

    def populate_points_table_batch(self, points: list[MapPoint]) -> None:
        """Пакетное заполнение таблицы точек."""
        self._table_point_ids = [p.id for p in points]
        self._points_panel.points_table.setRowCount(0)
        self._points_panel.populate_points_batch(points)

    def reproject_all_points(self, target_crs: str) -> None:
        """Пересчет экранных координат всех точек и зон под новую CRS карты."""
        with self._map_canvas.defer_labels_layout():
            for pt in self._point_service.get_points():
                xy = self._safe_transform_point(pt, target_crs)
                if xy is None:
                    self._map_canvas.remove_user_point(pt.id)
                    continue
                mx, my = xy
                zone_poly = self._build_zone_polygon_for_crs(pt, target_crs)
                self._map_canvas.add_user_point(pt, map_x=mx, map_y=my, zone_polygon=zone_poly)

    def move_points_to_group_workflow(self, target_group_id: str | None, point_ids: list[str] | None = None) -> None:
        """Перемещение выбранных точек в указанную группу (или Ungrouped при None)."""
        pids = point_ids or self._get_selected_point_ids()
        if not pids:
            return

        points = [self._point_service.get_point(pid) for pid in pids]
        valid_points = [p for p in points if p is not None]
        if not valid_points:
            return

        prev_groups = {p.id: p.group_id for p in valid_points}

        def apply_fn(mapping: dict[str, str | None]) -> None:
            for pid, gid in mapping.items():
                self._point_service.set_point_group(pid, gid)
            self._points_panel.update_points_group_ids(mapping)
            if self._group_controller:
                self._group_controller.refresh_groups_ui()
            sel_ids = self._get_selected_point_ids()
            if len(sel_ids) == 1 and sel_ids[0] in mapping:
                sel_pt = self._point_service.get_point(sel_ids[0])
                if sel_pt:
                    self._properties_panel.update_properties(sel_pt)

        grp_name = tr("groups.ungrouped")
        if target_group_id and self._group_service:
            g = self._group_service.get_group(target_group_id)
            if g:
                grp_name = g.name

        cmd = AssignPointsToGroupCommand(
            previous_groups=prev_groups,
            target_group_id=target_group_id,
            apply_fn=apply_fn,
            description=f"{tr('action.move_to_group')}: {grp_name} ({len(valid_points)})",
        )
        self._undo_manager.push(cmd, execute=True)
        self._set_status(tr("status.points_moved_to_group", group=grp_name, count=len(valid_points)), 3000)

    def bulk_change_category_workflow(self, point_ids: list[str] | None = None) -> None:
        """Диалог массовой смены категории для выбранных точек."""
        pids = point_ids or self._get_selected_point_ids()
        if not pids:
            return

        points = [self._point_service.get_point(pid) for pid in pids]
        valid_points = [p for p in points if p is not None]
        if not valid_points:
            return

        existing_cats = self._point_service.get_used_categories()
        current_cat = valid_points[0].category if len(valid_points) == 1 else ""

        dlg = ChangeCategoryDialog(self._parent, existing_categories=existing_cats, current_category=current_cat)
        if dlg.exec():
            new_cat = dlg.category_result
            prev_cats = {p.id: p.category for p in valid_points}

            def apply_fn(mapping: dict[str, str]) -> None:
                for pid, cat in mapping.items():
                    pt = self._point_service.get_point(pid)
                    if pt:
                        pt.category = cat
                self._points_panel.update_points_categories(mapping)
                sel_ids = self._get_selected_point_ids()
                if len(sel_ids) == 1 and sel_ids[0] in mapping:
                    sel_pt = self._point_service.get_point(sel_ids[0])
                    if sel_pt:
                        self._properties_panel.update_properties(sel_pt)

            cmd = BulkChangeCategoryCommand(
                previous_categories=prev_cats,
                new_category=new_cat,
                apply_fn=apply_fn,
                description=f"{tr('action.change_category')}: '{new_cat}' ({len(valid_points)})",
            )
            self._undo_manager.push(cmd, execute=True)
            self._set_status(tr("status.category_changed", count=len(valid_points)), 3000)

    def on_table_row_double_clicked(self, row: int, column: int) -> None:
        """Центрирование карты на выбранной точке."""
        if 0 <= row < len(self._table_point_ids):
            point_id = self._table_point_ids[row]
            point = self._point_service.get_point(point_id)
            if point:
                active_crs = self._get_active_crs()
                xy = self._safe_transform_point(point, active_crs)
                if xy is None:
                    self._set_status(tr("audit.search_invalid"), 3000)
                    return
                mx, my = xy
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

        row = table.row(item)
        clicked_point: MapPoint | None = None
        if 0 <= row < len(self._table_point_ids):
            clicked_point = self._point_service.get_point(self._table_point_ids[row])

        if not is_multi and clicked_point is not None and selected_ids != [clicked_point.id]:
            table.selectRow(row)
            selected_ids = [clicked_point.id]

        target_ids = selected_ids if is_multi else ([clicked_point.id] if clicked_point else selected_ids)

        menu = QMenu(self._parent)

        # Подменю: Переместить в группу
        menu_move = menu.addMenu(tr("action.move_to_group"))
        act_move_ungrouped = menu_move.addAction(tr("groups.ungrouped"))
        act_move_ungrouped.triggered.connect(lambda: self.move_points_to_group_workflow(None, target_ids))
        menu_move.addSeparator()

        groups = self._group_service.list_groups() if self._group_service else []
        for grp in groups:
            act_grp = menu_move.addAction(grp.name)
            gid = grp.id
            act_grp.triggered.connect(lambda checked=False, target_id=gid: self.move_points_to_group_workflow(target_id, target_ids))

        act_change_cat = menu.addAction(tr("action.change_category"))
        act_change_cat.triggered.connect(lambda: self.bulk_change_category_workflow(target_ids))

        menu.addSeparator()

        if is_multi:
            act_bulk_style = menu.addAction(tr("action.bulk_edit_style"))
            act_zoom_sel = menu.addAction(tr("action.zoom_to_selected"))
            act_zoom_sel.setEnabled(has_map)
            act_copy_sel = menu.addAction(tr("action.copy_selected_coords"))
            menu.addSeparator()
            sel_pts = [self._point_service.get_point(pid) for pid in target_ids]
            any_visible = any(p.visible for p in sel_pts if p is not None)
            act_toggle_vis = menu.addAction(tr("action.hide_object") if any_visible else tr("action.show_object"))
            menu.addSeparator()
            act_delete = menu.addAction(tr("action.delete_selected"))

            action = menu.exec(table.viewport().mapToGlobal(pos))
            if action == act_bulk_style:
                self.bulk_edit_style_workflow()
            elif action == act_zoom_sel:
                self.zoom_to_selected()
            elif action == act_copy_sel:
                self.copy_selected_coordinates()
            elif action == act_toggle_vis:
                self.toggle_point_visibility()
            elif action == act_delete:
                self.delete_point_workflow(confirm=True)
            return

        # Одиночное выделение
        point = clicked_point

        act_edit = menu.addAction(tr("action.edit_point"))
        act_move = menu.addAction(tr("action.move_point_context"))
        act_move.setEnabled(has_map)
        act_center = menu.addAction(tr("action.center_on_map"))
        act_center.setEnabled(has_map)

        act_vis = None
        if point:
            act_vis = menu.addAction(tr("action.hide_object") if point.visible else tr("action.show_object"))

        copy_menu = menu.addMenu(tr("action.copy_coordinates"))
        act_copy_dd = copy_menu.addAction(tr("action.copy_dd"))
        act_copy_dms = copy_menu.addAction(tr("action.copy_dms"))
        act_copy_map_xy = copy_menu.addAction(tr("action.copy_map_xy"))
        act_copy_map_xy.setEnabled(has_map)

        menu.addSeparator()
        web_menu=menu.addMenu(tr("audit.open_location"))
        act_osm=web_menu.addAction("OpenStreetMap")
        act_google=web_menu.addAction("Google Maps")
        act_yandex=web_menu.addAction(tr("audit.open_yandex"))
        menu.addSeparator()
        act_delete = menu.addAction(tr("action.delete_point"))

        action = menu.exec(table.viewport().mapToGlobal(pos))
        if point:
            if action in (act_osm,act_google,act_yandex):
                from PySide6.QtCore import QUrl
                from PySide6.QtGui import QDesktopServices
                lat,lon=point.latitude,point.longitude
                url=(f"https://www.openstreetmap.org/?mlat={lat}&mlon={lon}#map=16/{lat}/{lon}" if action==act_osm else f"https://www.google.com/maps?q={lat},{lon}" if action==act_google else f"https://yandex.ru/maps/?ll={lon},{lat}&z=16&pt={lon},{lat}")
                QDesktopServices.openUrl(QUrl(url))
                return
            if action == act_copy_dd:
                self.copy_coordinates_dd(point)
                return
            elif action == act_copy_dms:
                self.copy_coordinates_dms(point)
                return
            elif action == act_copy_map_xy:
                self.copy_coordinates_map_xy(point)
                return
            elif action == act_vis:
                self.toggle_point_visibility(point.id)
                return

        if action == act_edit:
            self.edit_point_workflow()
        elif action == act_move:
            self.start_move_point_mode()
        elif action == act_center:
            self.on_table_row_double_clicked(row, 0)
        elif action == act_delete:
            self.delete_point_workflow(confirm=True)
