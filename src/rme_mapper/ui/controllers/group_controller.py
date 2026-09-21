"""Контроллер организационных групп объектов (GroupController).

Координирует работу панели групп, сервиса групп, undo-менеджера, холста карты и таблицы точек.
"""

import copy
import logging
from typing import Any

from PySide6.QtCore import QObject
from PySide6.QtWidgets import QMessageBox, QWidget

from rme_mapper.i18n import tr
from rme_mapper.maps.map_canvas import MapCanvas
from rme_mapper.models.object_group import ObjectGroup
from rme_mapper.services.group_service import GroupService
from rme_mapper.services.point_service import PointService
from rme_mapper.services.undo_manager import (
    CreateGroupCommand,
    DeleteGroupCommand,
    RenameGroupCommand,
    SetGroupVisibilityCommand,
    UndoManager,
)
from rme_mapper.ui.group_dialog import GroupDialog
from rme_mapper.ui.panels.groups_panel import GroupsPanel
from rme_mapper.ui.panels.points_panel import PointsPanel

logger = logging.getLogger("rme_mapper.ui.controllers.group")


class GroupController(QObject):
    """Контроллер управления группами объектов проекта."""

    def __init__(
        self,
        parent: QWidget,
        group_service: GroupService,
        point_service: PointService,
        undo_manager: UndoManager,
        groups_panel: GroupsPanel,
        points_panel: PointsPanel,
        map_canvas: MapCanvas,
        point_controller: Any,
        status_bar_fn: Any = None,
    ) -> None:
        super().__init__(parent)
        self._parent = parent
        self._group_service = group_service
        self._point_service = point_service
        self._undo_manager = undo_manager
        self._groups_panel = groups_panel
        self._points_panel = points_panel
        self._map_canvas = map_canvas
        self._point_controller = point_controller
        self._status_bar_fn = status_bar_fn

        self._connect_signals()

    def _connect_signals(self) -> None:
        self._groups_panel.create_group_requested.connect(self.create_group_workflow)
        self._groups_panel.rename_group_requested.connect(self.rename_group_workflow)
        self._groups_panel.edit_group_desc_requested.connect(self.rename_group_workflow)
        self._groups_panel.delete_group_requested.connect(self.delete_group_workflow)
        self._groups_panel.group_visibility_toggled.connect(self.set_group_visibility_workflow)
        self._groups_panel.group_filter_changed.connect(self._on_group_filter_changed)
        self._groups_panel.select_group_points_requested.connect(self.select_group_points_workflow)
        self._groups_panel.zoom_to_group_requested.connect(self.zoom_to_group_workflow)
        self._groups_panel.bulk_style_group_requested.connect(self.bulk_style_group_workflow)

    def _set_status(self, msg: str, timeout: int = 3000) -> None:
        if self._status_bar_fn:
            self._status_bar_fn(msg, timeout)

    def refresh_groups_ui(self) -> None:
        """Полное обновление состояния панели групп и холста карты."""
        groups = self._group_service.list_groups()
        counts_by_group = self._point_service.count_points_by_groups()
        counts: dict[str | None, int] = {g.id: counts_by_group.get(g.id, 0) for g in groups}
        counts[None] = counts_by_group.get(None, 0)

        total_pts = len(self._point_service)
        self._groups_panel.set_groups_and_counts(groups, counts, total_pts)
        self._map_canvas.set_groups(groups)

    def clear_all_groups(self) -> None:
        """Очистка всех групп проекта."""
        self._group_service.clear()
        self.refresh_groups_ui()

    def apply_project_groups(self, groups: list[Any]) -> None:
        """Применение набора групп из загруженного проекта."""
        self._group_service.clear()
        for g_data in groups:
            grp = g_data.to_object_group() if hasattr(g_data, "to_object_group") else g_data
            self._group_service.add_existing_group(grp)
        self.refresh_groups_ui()

    def _on_group_filter_changed(self, filter_val: str | None) -> None:
        """Передача выбранного фильтра группы в PointsPanel."""
        self._points_panel.set_group_filter(filter_val)

    def create_group_workflow(self) -> None:
        """Диалог создания новой группы."""
        dlg = GroupDialog(self._parent, group=None, group_service=self._group_service)
        if dlg.exec():
            name = dlg.name_result
            desc = dlg.description_result
            group = ObjectGroup(name=name, description=desc, visible=True)

            def add_fn(grp: ObjectGroup) -> None:
                self._group_service.add_existing_group(grp)
                self.refresh_groups_ui()

            def remove_fn(gid: str) -> None:
                self._group_service.delete_group(gid)
                self.refresh_groups_ui()

            cmd = CreateGroupCommand(
                group=group,
                add_fn=add_fn,
                remove_fn=remove_fn,
                description=f"{tr('action.create_group')}: {group.name}",
            )
            self._undo_manager.push(cmd, execute=True)
            self._set_status(tr("status.group_created", name=group.name))

    def rename_group_workflow(self, group_id: str) -> None:
        """Диалог редактирования параметров существующей группы."""
        group = self._group_service.get_group(group_id)
        if not group:
            return

        dlg = GroupDialog(self._parent, group=group, group_service=self._group_service)
        if dlg.exec():
            before_name = group.name
            after_name = dlg.name_result
            before_desc = group.description
            after_desc = dlg.description_result

            if before_name == after_name and before_desc == after_desc:
                return

            def apply_fn(gid: str, name: str, desc: str) -> None:
                self._group_service.rename_group(gid, name, desc)
                self.refresh_groups_ui()

            cmd = RenameGroupCommand(
                group_id=group_id,
                before_name=before_name,
                after_name=after_name,
                before_desc=before_desc,
                after_desc=after_desc,
                apply_fn=apply_fn,
                description=f"{tr('action.rename_group')}: {after_name}",
            )
            self._undo_manager.push(cmd, execute=True)
            self._set_status(tr("status.group_renamed", name=after_name))

    def delete_group_workflow(self, group_id: str) -> None:
        """Удаление группы с подтверждением. Точки группы безопасно переходят в Ungrouped."""
        group = self._group_service.get_group(group_id)
        if not group:
            return

        # Диалог подтверждения удаления согласно ТЗ
        msg = tr("dialog.delete_group.message", name=group.name)
        reply = QMessageBox.question(
            self._parent,
            tr("dialog.delete_group.title"),
            msg,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        affected_points = self._point_service.get_points_by_group(group_id)
        affected_ids = [p.id for p in affected_points]

        def restore_group_fn(grp: ObjectGroup) -> None:
            self._group_service.add_existing_group(grp)
            self.refresh_groups_ui()

        def remove_group_fn(gid: str) -> None:
            self._group_service.delete_group(gid)
            if self._groups_panel.active_group_filter() == gid:
                self._groups_panel.select_filter(None)
                self._points_panel.set_group_filter(None)
            self.refresh_groups_ui()

        def set_points_group_fn(pids: list[str], gid: str | None) -> None:
            self._point_service.set_points_group(pids, gid)
            points_map = {pid: gid for pid in pids}
            self._points_panel.update_points_group_ids(points_map)
            self.refresh_groups_ui()

        cmd = DeleteGroupCommand(
            group=group,
            affected_point_ids=affected_ids,
            restore_group_fn=restore_group_fn,
            remove_group_fn=remove_group_fn,
            set_points_group_fn=set_points_group_fn,
            description=f"{tr('action.delete_group')}: {group.name}",
        )
        self._undo_manager.push(cmd, execute=True)
        self._set_status(tr("status.group_deleted", name=group.name))

    def set_group_visibility_workflow(self, group_id: str, visible: bool) -> None:
        """Переключение видимости группы с поддержкой Undo/Redo."""
        group = self._group_service.get_group(group_id)
        if not group:
            return

        before_vis = group.visible
        after_vis = visible
        if before_vis == after_vis:
            return

        def apply_fn(gid: str, vis: bool) -> None:
            self._group_service.set_group_visibility(gid, vis)
            self._map_canvas.set_group_visibility(gid, vis)
            self.refresh_groups_ui()

        cmd = SetGroupVisibilityCommand(
            group_id=group_id,
            before_visible=before_vis,
            after_visible=after_vis,
            apply_fn=apply_fn,
            description=f"{tr('action.show_group') if after_vis else tr('action.hide_group')}: {group.name}",
        )
        self._undo_manager.push(cmd, execute=True)

    def select_group_points_workflow(self, group_id: str) -> None:
        """Выбор всех точек группы в таблице и на карте."""
        gid = None if not group_id or group_id == "__ungrouped__" else group_id
        points = self._point_service.get_points_by_group(gid)
        pids = [p.id for p in points]
        self._points_panel.select_point_ids(pids)
        if hasattr(self._point_controller, "on_table_selection_changed"):
            self._point_controller.on_table_selection_changed()

    def zoom_to_group_workflow(self, group_id: str) -> None:
        """Приближение карты к точкам группы (navigation)."""
        gid = None if not group_id or group_id == "__ungrouped__" else group_id
        points = self._point_service.get_points_by_group(gid)
        if not points:
            return
        self._map_canvas.zoom_to_group(points)

    def bulk_style_group_workflow(self, group_id: str) -> None:
        """Массовое применение стилей ко всем точкам группы (разовое применение)."""
        gid = None if not group_id or group_id == "__ungrouped__" else group_id
        points = self._point_service.get_points_by_group(gid)
        if not points:
            return
        if hasattr(self._point_controller, "bulk_edit_style_workflow"):
            self._point_controller.bulk_edit_style_workflow(points)
