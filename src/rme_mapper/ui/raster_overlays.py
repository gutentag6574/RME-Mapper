"""Additional georeferenced rasters, in the active map CRS, below user objects."""
from __future__ import annotations
from copy import deepcopy
from pathlib import Path
import math
import pyproj
from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap, QTransform
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QListWidget, QPushButton, QSlider, QLabel, QFileDialog, QDialog, QGraphicsPixmapItem, QMessageBox

from rme_mapper.i18n import tr
from rme_mapper.services.georeference_service import GeoreferenceService


class RasterOverlays(QWidget):
    def __init__(self, window):
        super().__init__(window)
        self.window = window
        self.records = []
        self.missing_records = []
        self.items = []
        layout = QVBoxLayout(self)
        self.add_button = QPushButton(tr("ux.raster_add"))
        self.add_button.clicked.connect(self.add_image)
        layout.addWidget(self.add_button)
        self.list = QListWidget()
        layout.addWidget(self.list)
        self.opacity_label = QLabel(tr("ux.raster_opacity"))
        layout.addWidget(self.opacity_label)
        self.opacity = QSlider(Qt.Orientation.Horizontal)
        self.opacity.setRange(0, 100)
        self.opacity.setValue(100)
        self.opacity.setEnabled(False)
        layout.addWidget(self.opacity)
        row = QHBoxLayout()
        self.up = QPushButton(tr("ux.raster_up"))
        self.down = QPushButton(tr("ux.raster_down"))
        self.remove_button = QPushButton(tr("ux.raster_remove"))
        for button in (self.up, self.down, self.remove_button):
            row.addWidget(button)
            button.setEnabled(False)
        layout.addLayout(row)
        self.up.clicked.connect(lambda: self.move(-1))
        self.down.clicked.connect(lambda: self.move(1))
        self.remove_button.clicked.connect(self.remove_selected)
        self.opacity.valueChanged.connect(self.set_opacity)
        self.list.currentRowChanged.connect(self.select)
        self.list.itemChanged.connect(self.set_visibility)

    def retranslate_ui(self):
        for widget, key in ((self.add_button, "raster_add"), (self.opacity_label, "raster_opacity"), (self.up, "raster_up"), (self.down, "raster_down"), (self.remove_button, "raster_remove")):
            widget.setText(tr(f"ux.{key}"))

    def clear(self):
        import shiboken6
        for item in self.items:
            if shiboken6.isValid(item) and item.scene():
                item.scene().removeItem(item)
        self.items.clear()
        self.records.clear()
        self.missing_records.clear()
        self.list.clear()

    def restore(self):
        profile = self.window.map_controller.active_profile
        records = deepcopy(getattr(profile, "raster_overlays", [])) if profile else []
        self.clear()
        failures = []
        for record in reversed(records):
            try:
                self.add_record(record, modified=False)
            except Exception as error:
                self.missing_records.append(record)
                failures.append(f"{record.get('path', '')}: {error}")
        # Preserve missing entries so a save never silently drops references.
        if profile:
            profile.raster_overlays = records
        if failures:
            QMessageBox.warning(self.window, tr("dialog.error_title"), "\n".join(failures))

    def add_image(self):
        from rme_mapper.ui.georeference_dialog import GeoreferenceDialog
        if self.window.map_controller.active_profile is None:
            QMessageBox.information(self.window, tr("dialog.no_map_title"), tr("dialog.no_map_text"))
            return
        selected, _ = QFileDialog.getOpenFileName(self.window, tr("ux.raster_add"), "", tr("dialog.georef.file_filter"))
        if not selected:
            return
        try:
            dialog = GeoreferenceDialog(selected, parent=self.window)
            if dialog.exec() != QDialog.DialogCode.Accepted:
                return
            self.add_record({"path": str(dialog.image_path), "crs": dialog.get_crs(),
                "affine": list(dialog.get_affine_transform()), "opacity": 1.0, "visible": True})
        except Exception as error:
            QMessageBox.critical(self.window, tr("dialog.error_title"), str(error))

    def add_record(self, record, modified=True):
        record = deepcopy(record)
        canvas = self.window.map_canvas
        same_crs=pyproj.CRS(record["crs"]).equals(pyproj.CRS(canvas.active_crs),ignore_axis_order=True)
        affine = record["affine"]
        if len(affine) != 6 or not all(math.isfinite(float(v)) for v in affine):
            raise ValueError("Invalid affine transform")
        a, b, c, d, e, f = map(float, affine)
        if a * e == b * d:
            raise ValueError("Singular affine transform")
        opacity = float(record.get("opacity", 1))
        if not math.isfinite(opacity) or not 0 <= opacity <= 1:
            raise ValueError("Invalid opacity")
        path = Path(record["path"])
        profile = self.window.map_controller.active_profile
        if not path.is_absolute() and profile and profile.base_dir:
            path = profile.base_dir / path
        record["path"] = str(path.resolve())
        image, (width, height) = GeoreferenceService.load_preview_image(path, 4096)
        if not same_crs:
            from rme_mapper.services.raster_warp_service import warp_image
            image,warped_affine=warp_image(image,(width,height),affine,record["crs"],canvas.active_crs)
            width,height=image.width(),image.height()
            a,b,c,d,e,f=warped_affine
        item = QGraphicsPixmapItem(QPixmap.fromImage(image))
        sx, sy = width / image.width(), height / image.height()
        item.setTransform(QTransform(a*sx, -d*sx, b*sy, -e*sy, c, -f))
        item.setTransformationMode(Qt.TransformationMode.SmoothTransformation)
        item.setOpacity(opacity)
        item.setVisible(bool(record.get("visible", True)))
        canvas._scene.addItem(item)
        canvas._scene.setSceneRect(canvas._scene.sceneRect().united(item.sceneBoundingRect()))
        self.records.insert(0, record)
        self.items.insert(0, item)
        self.refresh_list()
        self.list.setCurrentRow(0)
        self.sync(modified)

    def refresh_list(self):
        from PySide6.QtWidgets import QListWidgetItem
        self.list.blockSignals(True)
        self.list.clear()
        for record in self.records:
            entry = QListWidgetItem(Path(record["path"]).name)
            entry.setFlags(entry.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            entry.setCheckState(Qt.CheckState.Checked if record.get("visible", True) else Qt.CheckState.Unchecked)
            self.list.addItem(entry)
        self.list.blockSignals(False)
        # Base map layers end at z=50; user zones/markers start at z=90.
        # This matches export: base map, then overlays, then user objects.
        for index, item in enumerate(self.items):
            item.setZValue(60 + (len(self.items)-index) / (len(self.items)+1))

    def select(self, index):
        import shiboken6
        if not all(shiboken6.isValid(widget) for widget in (self.opacity, self.up, self.down, self.remove_button)):
            return
        valid = 0 <= index < len(self.records)
        for control in (self.opacity, self.remove_button):
            control.setEnabled(valid)
        self.up.setEnabled(valid and index > 0)
        self.down.setEnabled(valid and index < len(self.records)-1)
        if valid:
            self.opacity.blockSignals(True)
            self.opacity.setValue(round(self.records[index].get("opacity", 1)*100))
            self.opacity.blockSignals(False)

    def set_opacity(self, value):
        index = self.list.currentRow()
        if 0 <= index < len(self.records):
            self.records[index]["opacity"] = value / 100
            self.items[index].setOpacity(value / 100)
            self.sync()

    def set_visibility(self, entry):
        index = self.list.row(entry)
        if 0 <= index < len(self.records):
            visible = entry.checkState() == Qt.CheckState.Checked
            self.records[index]["visible"] = visible
            self.items[index].setVisible(visible)
            self.sync()

    def move(self, direction):
        index = self.list.currentRow()
        other = index + direction
        if index < 0 or not 0 <= other < len(self.records):
            return
        for values in (self.records, self.items):
            values[index], values[other] = values[other], values[index]
        self.refresh_list()
        self.list.setCurrentRow(other)
        self.sync()

    def remove_selected(self):
        index = self.list.currentRow()
        if not 0 <= index < len(self.records):
            return
        self.records.pop(index)
        item = self.items.pop(index)
        if item.scene():
            item.scene().removeItem(item)
        self.refresh_list()
        self.list.setCurrentRow(min(index, len(self.records)-1))
        self.sync()

    def sync(self, modified=True):
        profile = self.window.map_controller.active_profile
        if profile:
            profile.raster_overlays = deepcopy(self.records + self.missing_records)
        if modified:
            self.window.project_controller.set_modified(True)
