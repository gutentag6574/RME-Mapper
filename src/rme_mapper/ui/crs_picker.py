"""CRS entry with explicit units and persistent favorites."""
from __future__ import annotations
import pyproj
from PySide6.QtCore import Signal
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QComboBox, QLineEdit, QLabel, QPushButton

from rme_mapper.i18n import tr
from rme_mapper.services.app_settings_service import AppSettingsService


class CrsPicker(QWidget):
    changed = Signal(str)

    def __init__(self, value="", parent=None):
        super().__init__(parent)
        self.settings = AppSettingsService()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        row = QHBoxLayout()
        self.favorites = QComboBox()
        self.edit = QLineEdit(value)
        self.edit.setPlaceholderText("EPSG:32639")
        self.star = QPushButton("☆")
        self.star.setToolTip(tr("ux.favorite_crs"))
        row.addWidget(self.edit, 1)
        row.addWidget(self.star)
        self.search=QLineEdit()
        self.search.setPlaceholderText(tr("audit.crs_search"))
        self.results=QComboBox()
        self.results.hide()
        self.search.textChanged.connect(self.search_crs)
        self.results.activated.connect(lambda index:self.edit.setText(self.results.itemData(index)))
        layout.addWidget(self.search)
        layout.addWidget(self.results)
        layout.addWidget(self.favorites)
        layout.addLayout(row)
        self.info = QLabel()
        self.info.setWordWrap(True)
        layout.addWidget(self.info)
        self.edit.textChanged.connect(self.validate_crs)
        self.favorites.activated.connect(lambda index: self.edit.setText(self.favorites.itemData(index)))
        self.star.clicked.connect(self.toggle_favorite)
        self.refresh_favorites()
        self.validate_crs(value)

    def refresh_favorites(self):
        self.favorites.clear()
        self.favorites.addItem(tr("ux.choose_crs"), "")
        for code in dict.fromkeys(["EPSG:4326", "EPSG:32639", "EPSG:3857"] + self.settings._get_string_list("crs/favorites")):
            try:
                crs = pyproj.CRS.from_user_input(code)
                self.favorites.addItem(f"{code} — {crs.name}", code)
            except pyproj.exceptions.CRSError:
                continue

    def validate_crs(self, value):
        try:
            crs = pyproj.CRS.from_user_input(value)
            units = crs.axis_info[0].unit_name if crs.axis_info else ""
            axes=tr("audit.axes_geo") if crs.is_geographic else tr("audit.axes_projected")
            self.info.setText(f"{crs.name} · {units} · {axes}")
            self.star.setEnabled(True)
            self.star.setText("★" if crs.to_string() in self.settings._get_string_list("crs/favorites") else "☆")
        except (ValueError, pyproj.exceptions.CRSError):
            self.info.setText(tr("ux.choose_crs"))
            self.star.setEnabled(False)
        self.changed.emit(value)

    def toggle_favorite(self):
        crs = pyproj.CRS.from_user_input(self.edit.text().strip()).to_string()
        favorites = self.settings._get_string_list("crs/favorites")
        if crs in favorites:
            favorites.remove(crs)
        else:
            favorites.append(crs)
        self.settings._set_string_list("crs/favorites", favorites)
        self.refresh_favorites()
        self.validate_crs(self.edit.text())

    def search_crs(self, text):
        if len(text.strip())<2:
            self.results.hide()
            return
        query=text.strip().casefold()
        query={"ск-42":"pulkovo 1942","ск-95":"pulkovo 1995","мск":"msk"}.get(query,query)
        if not hasattr(type(self),"_crs_catalog"):
            type(self)._crs_catalog=pyproj.database.query_crs_info(auth_name="EPSG",allow_deprecated=False)
        self.results.clear()
        for info in self._crs_catalog:
            if query in info.name.casefold() or query in info.code:
                self.results.addItem(f"EPSG:{info.code} — {info.name}",f"EPSG:{info.code}")
                if self.results.count()>=100:
                    break
        self.results.setVisible(self.results.count()>0)
