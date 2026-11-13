"""User-facing settings, map navigation and measurement shortcuts."""
from __future__ import annotations
import json
import math
import re
import pyproj
from PySide6.QtCore import QUrl, Qt
from PySide6.QtGui import QDesktopServices, QPainter
from PySide6.QtWidgets import QWidget, QHBoxLayout, QPushButton, QLineEdit, QComboBox, QDialog, QMessageBox, QToolButton, QStyle, QListWidget, QListWidgetItem,QVBoxLayout
from rme_mapper.i18n import tr


class AuditFeaturesMixin:
    def setup_audit_features(self):
        self._annotation_items=[]
        self.annotation_panel=QWidget()
        annotation_layout=QVBoxLayout(self.annotation_panel)
        self.annotation_list=QListWidget()
        annotation_layout.addWidget(self.annotation_list)
        self.remove_annotation_button=QPushButton(tr("audit.remove_track"))
        annotation_layout.addWidget(self.remove_annotation_button)
        self.remove_annotation_button.clicked.connect(self.remove_selected_annotation)
        self.annotation_list.itemChanged.connect(self.annotation_visibility_changed)
        self.navigation_tabs.addTab(self.annotation_panel,tr("audit.tracks"))
        self.preferences_action=self.settings_menu.addAction(tr("audit.preferences"))
        self.preferences_action.triggered.connect(self.open_preferences)
        self.preferences_action.setShortcut("Ctrl+,")
        self.navigation_bar=QWidget(self)
        row=QHBoxLayout(self.navigation_bar)
        row.setContentsMargins(0,0,0,0)
        self.navigate_edit=QLineEdit()
        self.navigate_edit.setPlaceholderText(tr("audit.search_hint"))
        self.navigate_mode=QComboBox()
        self.navigate_mode.addItem(tr("audit.point_or_latlon"),"wgs84")
        self.navigate_mode.addItem(tr("audit.map_xy"),"map")
        self.navigate_edit.returnPressed.connect(self.navigate_to_input)
        row.addWidget(self.navigate_edit,1)
        row.addWidget(self.navigate_mode)
        self.center_panel.layout().insertWidget(1,self.navigation_bar)
        self.measure_bar=QWidget(self.map_canvas.viewport())
        self.measure_bar.setObjectName("measurementHUD")
        self.measure_bar.setStyleSheet("QWidget#measurementHUD { background: #FFFFFF; border: 1px solid #D9DDE3; border-radius: 6px; }")
        bar=QHBoxLayout(self.measure_bar)
        bar.setContentsMargins(0,0,0,0)
        self.measure_buttons=[]
        for action in (self.measure_distance_action,self.measure_area_action):
            button=QToolButton()
            button.setDefaultAction(action)
            button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
            bar.addWidget(button)
            self.measure_buttons.append((button,action))
        clear=QToolButton()
        clear.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_DialogResetButton))
        clear.setToolTip(tr("audit.clear_measurements"))
        clear.clicked.connect(self.map_canvas.clear_measurements)
        self.clear_measure_button=clear
        bar.addWidget(clear)
        self.save_measurement_button=QToolButton()
        self.save_measurement_button.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_DialogSaveButton))
        self.save_measurement_button.setToolTip(tr("audit.save_measurement"))
        self.save_measurement_button.setEnabled(False)
        self.save_measurement_button.clicked.connect(self.save_last_measurement)
        bar.addWidget(self.save_measurement_button)
        self.map_canvas._measurement_toolbar=self.measure_bar
        self.measure_bar.adjustSize()
        self.measure_bar.move(max(12,self.map_canvas.viewport().width()-self.measure_bar.width()-12),56)
        self.measure_bar.raise_()
        self._last_measurement=None
        self.map_canvas.measurement_geometry_finished.connect(self.remember_measurement)
        self.field_import_action=self.import_menu.addAction(tr("audit.import_field"))
        self.field_import_action.triggered.connect(self.import_field_file)
        self.apply_preferences()

    def retranslate_audit(self):
        if not hasattr(self,"field_import_action"):
            return
        self.preferences_action.setText(tr("audit.preferences"))
        self.navigation_tabs.setTabText(self.navigation_tabs.indexOf(self.annotation_panel),tr("audit.tracks"))
        self.remove_annotation_button.setText(tr("audit.remove_track"))
        self.field_import_action.setText(tr("audit.import_field"))
        self.navigate_edit.setPlaceholderText(tr("audit.search_hint"))
        self.navigate_mode.setItemText(0,tr("audit.point_or_latlon"))
        self.navigate_mode.setItemText(1,tr("audit.map_xy"))
        self.clear_measure_button.setToolTip(tr("audit.clear_measurements"))
        self.save_measurement_button.setToolTip(tr("audit.save_measurement"))
        for button,action in self.measure_buttons:
            button.setText(action.text())

    def restore_annotations(self):
        import shiboken6
        from PySide6.QtGui import QPen,QBrush,QColor
        from rme_mapper.services.annotation_service import annotation_path
        for item in getattr(self,"_annotation_items",[]):
            if shiboken6.isValid(item) and item.scene():
                item.scene().removeItem(item)
        self._annotation_items=[]
        profile=self.map_controller.active_profile
        self.annotation_list.blockSignals(True)
        self.annotation_list.clear()
        for record in getattr(profile,"annotations",[]):
            entry=QListWidgetItem(record.get("name") or tr("audit.measurement"))
            entry.setFlags(entry.flags()|Qt.ItemFlag.ItemIsUserCheckable)
            entry.setCheckState(Qt.CheckState.Checked if record.get("visible",True) else Qt.CheckState.Unchecked)
            self.annotation_list.addItem(entry)
            try:
                path=annotation_path(record,self.map_canvas.active_crs)
                pen=QPen(QColor("#2563eb"),2)
                pen.setCosmetic(True)
                item=self.map_canvas.scene().addPath(path,pen,QBrush(QColor(37,99,235,30)) if record["kind"]=="polygon" else QBrush(Qt.BrushStyle.NoBrush))
                item.setZValue(85)
                item.setVisible(record.get("visible",True))
                item.setToolTip(record.get("name",""))
                self._annotation_items.append(item)
                self.map_canvas.scene().setSceneRect(self.map_canvas.scene().sceneRect().united(item.sceneBoundingRect()))
            except (ValueError,pyproj.exceptions.ProjError) as error:
                self.statusBar().showMessage(str(error),5000)
        self.annotation_list.blockSignals(False)

    def change_annotations(self,records):
        from copy import deepcopy
        from rme_mapper.services.undo_manager import UndoCommand
        profile=self.map_controller.active_profile
        if profile is None:
            return
        before=deepcopy(profile.annotations)
        after=deepcopy(records)
        target_profile_id=getattr(profile,"id",None)
        window=self
        class ChangeAnnotationsCommand(UndoCommand):
            def _is_target_active(command):
                current=window.map_controller.active_profile
                return current is profile and getattr(current,"id",None)==target_profile_id
            def execute(command):
                if not command._is_target_active():
                    return
                profile.annotations=deepcopy(after)
                window.restore_annotations()
                window.project_controller.set_modified(True)
            def undo(command):
                if not command._is_target_active():
                    return
                profile.annotations=deepcopy(before)
                window.restore_annotations()
                window.project_controller.set_modified(True)
        self.point_controller.undo_manager.push(ChangeAnnotationsCommand(tr("audit.tracks")),execute=True)

    def remove_selected_annotation(self):
        index=self.annotation_list.currentRow()
        profile=self.map_controller.active_profile
        if profile is not None and 0<=index<len(profile.annotations):
            self.change_annotations([item for row,item in enumerate(profile.annotations) if row!=index])

    def annotation_visibility_changed(self,entry):
        from copy import deepcopy
        profile=self.map_controller.active_profile
        index=self.annotation_list.row(entry)
        if profile is not None and 0<=index<len(profile.annotations):
            records=deepcopy(profile.annotations)
            records[index]["visible"]=entry.checkState()==Qt.CheckState.Checked
            self.change_annotations(records)

    def add_annotation_batch(self, annotations, points):
        from copy import deepcopy
        from uuid import uuid4
        from rme_mapper.services.undo_manager import UndoCommand
        profile=self.map_controller.active_profile
        if profile is None:
            return
        records=[dict(deepcopy(item),id=uuid4().hex) for item in annotations]
        target_profile_id=getattr(profile,"id",None)
        window=self
        class FieldImportCommand(UndoCommand):
            def _is_target_active(command):
                current=window.map_controller.active_profile
                return current is profile and getattr(current,"id",None)==target_profile_id
            def execute(command):
                if points:
                    window.point_controller._cmd_add_points(deepcopy(points))
                    window.project_controller.set_modified(True)
                if command._is_target_active():
                    profile.annotations.extend(deepcopy(records))
                    window.restore_annotations()
                    window.project_controller.set_modified(True)
            def undo(command):
                if points:
                    window.point_controller._cmd_remove_points([p.id for p in points])
                    window.project_controller.set_modified(True)
                if command._is_target_active():
                    identifiers={record["id"] for record in records}
                    profile.annotations=[record for record in profile.annotations if record.get("id") not in identifiers]
                    window.restore_annotations()
                    window.project_controller.set_modified(True)
        self.point_controller.undo_manager.push(FieldImportCommand(tr("audit.import_field")),execute=True)

    def open_preferences(self):
        from rme_mapper.ui.settings_dialog import SettingsDialog
        dialog=SettingsDialog(self._settings_service,self)
        if dialog.exec()==QDialog.DialogCode.Accepted:
            self.apply_preferences()

    def apply_preferences(self):
        s=self._settings_service
        self.set_workspace_theme(s._get_str("ui/theme","light"))
        self.switch_language(s.get_language())
        self.map_canvas.setRenderHint(QPainter.RenderHint.Antialiasing,s._get_bool("map/antialias",True))
        manager=self.map_canvas.online_tile_manager()
        manager._cache.max_size_bytes=s.get_online_cache_max_mb()*1024*1024
        manager._cache._maybe_evict()
        self.project_controller._recovery_timer.setInterval(s.get_integer("recovery/seconds",3,1,300)*1000)
        if not s._get_bool("recovery/enabled",True):
            self.project_controller._recovery_timer.stop()
        self.preferences_action.setText(tr("audit.preferences"))
        self.navigate_edit.setPlaceholderText(tr("audit.search_hint"))

    def navigate_to_input(self):
        text=self.navigate_edit.text().strip()
        if not text:
            return
        for point in self._point_service.get_points():
            if point.name.casefold()==text.casefold() or (point.object_number and point.object_number.casefold()==text.casefold()):
                self.points_panel.select_point_ids([point.id])
                self.map_canvas.center_on_coordinates(point.longitude,point.latitude)
                return
        try:
            values=[float(value) for value in re.split(r"[;,\s]+",text) if value]
            if len(values)!=2 or not all(math.isfinite(v) for v in values):
                raise ValueError()
            if self.navigate_mode.currentData()=="wgs84":
                lat,lon=values
                if not -90<=lat<=90 or not -180<=lon<=180:
                    raise ValueError()
                x,y=pyproj.Transformer.from_crs("EPSG:4326",self.map_canvas.active_crs,always_xy=True).transform(lon,lat,errcheck=True)
            else:
                x,y=values
            self.map_canvas.center_on_map_coordinates(x,y)
            self.statusBar().showMessage(tr("audit.centered"),2500)
        except (ValueError,pyproj.exceptions.ProjError):
            self.statusBar().showMessage(tr("audit.search_invalid"),5000)

    def remember_measurement(self, data):
        self._last_measurement=data
        self.save_measurement_button.setEnabled(True)

    def save_last_measurement(self):
        if self._last_measurement is not None:
            self.add_annotation_batch([self._last_measurement],[])
            self.save_measurement_button.setEnabled(False)

    def import_field_file(self, path=None):
        from PySide6.QtWidgets import QFileDialog
        from rme_mapper.services.field_import_service import read_field_file
        if self.map_controller.active_profile is None:
            QMessageBox.information(self,tr("dialog.no_map_title"),tr("dialog.no_map_text"))
            return
        if not path:
            path,_=QFileDialog.getOpenFileName(self,tr("audit.import_field"),"","GPX / KML / KMZ (*.gpx *.kml *.kmz)")
        if not path:
            return
        try:
            points,annotations=read_field_file(path)
            if not points and not annotations:
                raise ValueError(tr("audit.no_field_data"))
            from rme_mapper.services.project_service import MAX_PROJECT_POINTS
            if len(points)+len(self._point_service.get_points())>MAX_PROJECT_POINTS:
                raise ValueError(tr("ux.paste_limit",limit=MAX_PROJECT_POINTS))
            answer=QMessageBox.question(self,tr("audit.import_field"),tr("audit.import_field_confirm",points=len(points),tracks=len(annotations)))
            if answer==QMessageBox.StandardButton.Yes:
                self.add_annotation_batch(annotations,points)
                if self._annotation_items:
                    rect=self._annotation_items[0].sceneBoundingRect()
                    for item in self._annotation_items[1:]:
                        rect=rect.united(item.sceneBoundingRect())
                    self.map_canvas.zoom_to_extent(rect)
                elif points:
                    self.map_canvas.zoom_to_group(points)
        except Exception as error:
            QMessageBox.critical(self,tr("dialog.error_title"),str(error))
