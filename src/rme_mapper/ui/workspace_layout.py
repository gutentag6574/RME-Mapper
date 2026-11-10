"""Workspace layout and preferences, independent of map data and editing tools."""
from __future__ import annotations
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from rme_mapper.i18n import tr


from rme_mapper.ui.audit_features import AuditFeaturesMixin


class WorkspaceLayoutMixin(AuditFeaturesMixin):
    def setup_workspace_actions(self):
        self._saved_navigation_index=self._read_navigation_tab()
        from PySide6.QtGui import QAction, QActionGroup
        self.bottom_points_action = QAction(tr("ux.bottom_points"), self)
        self.bottom_points_action.setCheckable(True)
        self.bottom_points_action.setChecked(self._settings_service._get_bool("ui/points_bottom", True))
        self.bottom_points_action.toggled.connect(self.set_points_bottom)
        self.view_menu.addAction(self.bottom_points_action)
        self.auto_properties_action = QAction(tr("ux.auto_properties"), self)
        self.auto_properties_action.setCheckable(True)
        self.auto_properties_action.setChecked(self._settings_service._get_bool("ui/auto_properties", True))
        self.auto_properties_action.toggled.connect(self.set_auto_properties)
        self.view_menu.addAction(self.auto_properties_action)
        self.theme_menu = self.settings_menu.addMenu(tr("ux.theme"))
        self.theme_actions = {}
        self.theme_group = QActionGroup(self)
        for key in ("light", "dark", "system"):
            action = self.theme_menu.addAction(tr(f"ux.theme_{key}"))
            action.setCheckable(True)
            self.theme_group.addAction(action)
            action.triggered.connect(lambda checked=False, name=key: self.set_workspace_theme(name))
            self.theme_actions[key] = action
        self.set_points_bottom(self.bottom_points_action.isChecked())
        self.workspace_splitter.setSizes(self._read_workspace_sizes())
        self.workspace_splitter.splitterMoved.connect(lambda *_: self._settings_service._set_string_list("ui/workspace_sizes", [str(v) for v in self.workspace_splitter.sizes()]))
        self.navigation_tabs.setCurrentIndex(min(1, max(0, self._read_navigation_tab())))
        self.navigation_tabs.currentChanged.connect(lambda value: self._settings_service._set_str("ui/navigation_tab", str(value)))
        self.set_workspace_theme(self._settings_service._get_str("ui/theme", "light"))
        self.paste_coordinates_action = self.import_menu.addAction(tr("ux.paste"))
        self.paste_coordinates_action.setShortcut("Ctrl+Shift+V")
        # Ctrl+V belongs to text fields while they are being edited.
        from PySide6.QtGui import QShortcut, QKeySequence
        self.table_paste_shortcut = QShortcut(QKeySequence.StandardKey.Paste, self.points_panel.points_table)
        self.table_paste_shortcut.setContext(Qt.ShortcutContext.WidgetShortcut)
        self.table_paste_shortcut.activated.connect(self.paste_coordinates)
        self.paste_coordinates_action.triggered.connect(self.paste_coordinates)
        self.move_pt_action.setShortcut("Ctrl+Alt+M")
        self.bundle_action = self.file_menu.addAction(tr("ux.bundle"))
        self.bundle_action.triggered.connect(self.package_project)
        self.sync_properties_visibility()

    def _read_navigation_tab(self):
        try:
            return int(self._settings_service._get_str("ui/navigation_tab", "0"))
        except ValueError:
            return 0

    def _read_workspace_sizes(self):
        try:
            sizes = [int(v) for v in self._settings_service._get_string_list("ui/workspace_sizes")]
            if len(sizes) == 2 and min(sizes) > 0:
                return sizes
        except (ValueError, TypeError):
            pass
        return [600, 230]

    def set_points_bottom(self, enabled):
        if not enabled:
            self._settings_service._set_string_list("ui/workspace_sizes", [str(v) for v in self.workspace_splitter.sizes()])
        self.points_panel.setParent(None)
        if enabled:
            self.workspace_splitter.addWidget(self.points_panel)
        else:
            self.left_panel.layout().addWidget(self.points_panel, stretch=1)
        self.points_panel.show()
        self._settings_service._set_bool("ui/points_bottom", enabled)
        self.bottom_points_action.setChecked(enabled)
        if enabled:
            self.workspace_splitter.setSizes(self._read_workspace_sizes())

    def set_auto_properties(self, enabled):
        self.auto_properties_action.blockSignals(True)
        self.auto_properties_action.setChecked(enabled)
        self.auto_properties_action.blockSignals(False)
        self._settings_service._set_bool("ui/auto_properties", enabled)
        self.sync_properties_visibility()

    def sync_properties_visibility(self):
        if not hasattr(self, "auto_properties_action"):
            return
        import shiboken6
        if not all(shiboken6.isValid(widget) for widget in (self.right_panel, self.points_panel, self.auto_properties_action)):
            return
        wanted = self._settings_service.get_right_panel_visible()
        selected = bool(self.points_panel.selected_point_ids())
        self.right_panel.setVisible(wanted and (selected or not self.auto_properties_action.isChecked()))

    def set_workspace_theme(self, name):
        from rme_mapper.ui.theme_manager import get_theme_manager
        if name not in self.theme_actions:
            name = "light"
        self._settings_service._set_str("ui/theme", name)
        self.theme_actions[name].setChecked(True)
        # All dialogs are children of this application; their shared styling follows it.
        canvas = getattr(self, "map_canvas", None)
        # QGraphicsView can change scroll offsets as Qt repolishes widgets.
        center = canvas.mapToScene(canvas.viewport().rect().center()) if canvas else None
        view_transform = canvas.transform() if canvas else None
        get_theme_manager().apply_theme(QApplication.instance(), name)
        if canvas and center is not None:
            from PySide6.QtCore import QTimer
            canvas.centerOn(center)
            def refresh():
                import shiboken6
                if shiboken6.isValid(canvas):
                    canvas.resetTransform()
                    canvas.setTransform(view_transform)
                    canvas.centerOn(center)
                    canvas.scene().invalidate()
                    canvas.update_scale_indicator()
                    canvas.viewport().update()
            QTimer.singleShot(0, refresh)

    def retranslate_workspace(self):
        self.retranslate_audit()
        if not hasattr(self, "navigation_tabs"):
            return
        self.navigation_tabs.setTabText(0, tr("ux.layers"))
        self.navigation_tabs.setTabText(1, tr("ux.groups"))
        if hasattr(self, "raster_overlays_panel"):
            self.navigation_tabs.setTabText(2, tr("ux.rasters"))
            self.raster_overlays_panel.retranslate_ui()
        for attr, key in (("bottom_points_action", "bottom_points"), ("auto_properties_action", "auto_properties")):
            if hasattr(self, attr):
                getattr(self, attr).setText(tr(f"ux.{key}"))
        if hasattr(self, "theme_menu"):
            self.theme_menu.setTitle(tr("ux.theme"))
            for name, action in self.theme_actions.items():
                action.setText(tr(f"ux.theme_{name}"))
        for attr, key in (("paste_coordinates_action", "paste"), ("bundle_action", "bundle")):
            if hasattr(self, attr):
                getattr(self, attr).setText(tr(f"ux.{key}"))

    def paste_coordinates(self):
        from PySide6.QtWidgets import QDialog, QMessageBox
        from rme_mapper.ui.clipboard_coordinates_dialog import ClipboardCoordinatesDialog
        from rme_mapper.services.undo_manager import ImportPointsCommand
        if self.map_controller.map_path is None and self.map_controller.active_profile is None:
            QMessageBox.information(self, tr("dialog.no_map_title"), tr("dialog.no_map_text"))
            return
        dialog = ClipboardCoordinatesDialog(QApplication.clipboard().text(), len(self._point_service.get_points()), self)
        if dialog.exec() != QDialog.DialogCode.Accepted or not dialog.points:
            return
        command = ImportPointsCommand(points=dialog.points,
            add_fn=self.point_controller._cmd_add_points,
            remove_fn=self.point_controller._cmd_remove_points,
            description=tr("ux.paste"))
        self.point_controller.undo_manager.push(command, execute=True)
        self.project_controller.set_modified(True)

    def package_project(self):
        from pathlib import Path
        from PySide6.QtWidgets import QFileDialog, QMessageBox
        from rme_mapper.services.project_bundle_service import create_project_bundle
        chosen, _ = QFileDialog.getSaveFileName(self, tr("ux.bundle"), "project.zip", "ZIP (*.zip)")
        if not chosen:
            return
        try:
            profile = self.map_controller.active_profile
            data = self._project_service.build_project_data(
                map_path=self.map_controller.map_path, layers=self.map_controller.loaded_layers,
                points=self._point_service.get_points(), map_id=profile.id if profile else "",
                map_profile=profile, groups=self._group_service.list_groups())
            if profile is None and getattr(self.project_controller, "_unsupported_map_data", None):
                raise ValueError(tr("ux.missing_map_bundle"))
            target = Path(chosen).with_suffix(".zip")
            current = getattr(self.project_controller, "_current_project_path", None)
            if current is not None and target.resolve() == Path(current).resolve():
                raise ValueError(tr("ux.archive_overwrite"))
            create_project_bundle(data, target, self.map_controller.map_path)
            QMessageBox.information(self, tr("common.success"), tr("ux.bundle_done", path=target))
        except Exception as error:
            QMessageBox.critical(self, tr("dialog.error_title"), str(error))
