"""Paste a table, explicitly select axes and CRS, preview all validation results."""
from __future__ import annotations
import csv
import io
import math
import pyproj
from PySide6.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPlainTextEdit, QComboBox, QCheckBox, QTableWidget, QTableWidgetItem, QDialogButtonBox

from rme_mapper.i18n import tr
from rme_mapper.models.map_point import MapPoint
from rme_mapper.services.project_service import MAX_PROJECT_POINTS
from rme_mapper.ui.crs_picker import CrsPicker


def parse_clipboard_coordinates(text, crs, x_column, y_column, name_column=None, skip_header=False, delimiter="\t", existing_count=0):
    rows = list(csv.reader(io.StringIO(text), delimiter=delimiter))
    rows = [row for row in rows if any(cell.strip() for cell in row)]
    if skip_header:
        rows = rows[1:]
    if len(rows) + existing_count > MAX_PROJECT_POINTS:
        raise ValueError(tr("ux.paste_limit", limit=MAX_PROJECT_POINTS))
    if x_column == y_column:
        raise ValueError(tr("ux.different_axes"))
    transformer = pyproj.Transformer.from_crs(crs, "EPSG:4326", always_xy=True)
    points, preview = [], []
    for number, row in enumerate(rows, 2 if skip_header else 1):
        try:
            x = float(row[x_column].strip().replace(" ", "").replace("\xa0", "").replace(",", "."))
            y = float(row[y_column].strip().replace(" ", "").replace("\xa0", "").replace(",", "."))
            if not math.isfinite(x) or not math.isfinite(y):
                raise ValueError(tr("ux.nonfinite"))
            lon, lat = transformer.transform(x, y, errcheck=True)
            if not (math.isfinite(lon) and math.isfinite(lat) and -180 <= lon <= 180 and -90 <= lat <= 90):
                raise ValueError(tr("ux.out_of_range"))
            name = row[name_column].strip() if name_column is not None else str(number)
            point = MapPoint(name=name or str(number), latitude=lat, longitude=lon, source_crs=crs)
            points.append(point)
            preview.append((number, point.name, f"{lon:.7f}", f"{lat:.7f}", "OK"))
        except (ValueError, IndexError, pyproj.exceptions.ProjError) as error:
            preview.append((number, "", "", "", str(error)))
    return points, preview


class ClipboardCoordinatesDialog(QDialog):
    def __init__(self, text, existing_count=0, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("ux.paste"))
        self.resize(850, 650)
        self.existing_count = existing_count
        self.points = []
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(tr("ux.paste_help")))
        self.source = QPlainTextEdit(text)
        self.source.setMaximumHeight(140)
        layout.addWidget(self.source)
        self.crs_picker = CrsPicker("", self)
        layout.addWidget(self.crs_picker)
        row = QHBoxLayout()
        self.delimiter = QComboBox()
        for label, value in ((tr("ux.tab"), "\t"), (";", ";"), (",", ",")):
            self.delimiter.addItem(label, value)
        self.skip_header = QCheckBox(tr("ux.skip_header"))
        self.x_column, self.y_column, self.name_column = QComboBox(), QComboBox(), QComboBox()
        for label, widget in ((tr("ux.separator"), self.delimiter), ("X / Easting / Lon", self.x_column), ("Y / Northing / Lat", self.y_column), (tr("ux.name"), self.name_column)):
            row.addWidget(QLabel(label))
            row.addWidget(widget)
        layout.addLayout(row)
        layout.addWidget(self.skip_header)
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["№", tr("ux.name"), "Longitude", "Latitude", tr("ux.validation")])
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        layout.addWidget(self.table, 1)
        self.status = QLabel()
        layout.addWidget(self.status)
        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)
        self.source.textChanged.connect(self.refresh_columns)
        self.delimiter.currentIndexChanged.connect(self.refresh_columns)
        for combo in (self.x_column, self.y_column, self.name_column):
            combo.currentIndexChanged.connect(self.validate_rows)
        self.skip_header.toggled.connect(self.validate_rows)
        self.crs_picker.changed.connect(self.validate_rows)
        self.refresh_columns()

    def refresh_columns(self):
        try:
            rows = list(csv.reader(io.StringIO(self.source.toPlainText()), delimiter=self.delimiter.currentData()))
            count = max((len(row) for row in rows), default=2)
        except csv.Error:
            count = 2
        for combo, default in ((self.x_column, 0), (self.y_column, 1), (self.name_column, None)):
            combo.blockSignals(True)
            previous = combo.currentData() if combo.count() else default
            combo.clear()
            if combo is self.name_column:
                combo.addItem("—", None)
            for index in range(min(count, 1000)):
                combo.addItem(str(index + 1), index)
            combo.setCurrentIndex(max(0, combo.findData(previous)))
            combo.blockSignals(False)
        self.validate_rows()

    def validate_rows(self, *_):
        self.points = []
        self.table.setRowCount(0)
        try:
            self.points, rows = parse_clipboard_coordinates(self.source.toPlainText(), self.crs_picker.edit.text().strip(), self.x_column.currentData(), self.y_column.currentData(), self.name_column.currentData(), self.skip_header.isChecked(), self.delimiter.currentData(), self.existing_count)
            for values in rows:
                index = self.table.rowCount()
                self.table.insertRow(index)
                for col, value in enumerate(values):
                    self.table.setItem(index, col, QTableWidgetItem(str(value)))
            errors = len(rows) - len(self.points)
            self.status.setText(tr("ux.paste_status", valid=len(self.points), errors=errors))
            # No silent loss of invalid rows: fix them before accepting.
            valid = bool(self.points) and errors == 0
        except (ValueError, TypeError, csv.Error, pyproj.exceptions.CRSError) as error:
            valid = False
            self.status.setText(str(error))
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(valid)
