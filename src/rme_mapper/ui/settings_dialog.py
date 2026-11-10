"""Preferences backed by the same settings used by map and editing controllers."""
from __future__ import annotations
import json
from PySide6.QtWidgets import QDialog, QVBoxLayout, QFormLayout, QTabWidget, QWidget, QComboBox, QCheckBox, QSpinBox, QDoubleSpinBox, QDialogButtonBox, QLineEdit, QPushButton, QColorDialog
from PySide6.QtGui import QColor
from rme_mapper.i18n import tr


class SettingsDialog(QDialog):
    def __init__(self, settings, parent=None):
        super().__init__(parent)
        self.settings = settings
        self.setWindowTitle(tr("audit.preferences"))
        self.resize(540,460)
        layout = QVBoxLayout(self)
        tabs = QTabWidget()
        layout.addWidget(tabs)
        def page(key):
            widget=QWidget()
            form=QFormLayout(widget)
            tabs.addTab(widget,tr(f"audit.{key}"))
            return form
        general=page("general")
        self.language=QComboBox()
        self.language.addItem("Русский","ru")
        self.language.addItem("English","en")
        self.language.setCurrentIndex(self.language.findData(settings.get_language()))
        general.addRow(tr("audit.language"),self.language)
        self.theme=QComboBox()
        for name in ("light","dark","system"):
            self.theme.addItem(tr(f"ux.theme_{name}"),name)
        self.theme.setCurrentIndex(max(0,self.theme.findData(settings._get_str("ui/theme","light"))))
        general.addRow(tr("ux.theme"),self.theme)
        self.recovery=QCheckBox(tr("audit.recovery"))
        self.recovery.setChecked(settings._get_bool("recovery/enabled",True))
        general.addRow(self.recovery)
        self.interval=QSpinBox()
        self.interval.setRange(1,300)
        self.interval.setValue(settings.get_integer("recovery/seconds",3,1,300))
        general.addRow(tr("audit.recovery_seconds"),self.interval)
        maps=page("maps_cache")
        self.cache=QSpinBox()
        self.cache.setRange(16,10240)
        self.cache.setValue(settings.get_online_cache_max_mb())
        maps.addRow(tr("audit.cache_mb"),self.cache)
        self.antialias=QCheckBox(tr("audit.antialias"))
        self.antialias.setChecked(settings._get_bool("map/antialias",True))
        maps.addRow(self.antialias)
        clear=QPushButton(tr("action.clear_tile_cache"))
        if parent is not None:
            clear.clicked.connect(parent.clear_online_tile_cache)
        maps.addRow(clear)
        points=page("point_defaults")
        defaults=settings.get_point_defaults()
        self.shape=QComboBox()
        for name in ("circle","square","triangle"):
            self.shape.addItem(tr(f"shape.{name}"),name)
        self.shape.setCurrentIndex(max(0,self.shape.findData(defaults.get("symbol","circle"))))
        points.addRow(tr("audit.shape"),self.shape)
        self.size=QDoubleSpinBox()
        self.size.setRange(2,64)
        self.size.setValue(defaults.get("size",12))
        points.addRow(tr("audit.marker_size"),self.size)
        self.color=QLineEdit(defaults.get("color","#dc1e1e"))
        points.addRow(tr("audit.marker_color"),self.color)
        pick=QPushButton(tr("audit.choose_color"))
        pick.clicked.connect(self.pick_color)
        points.addRow(pick)
        self.zone=QCheckBox(tr("audit.zone_enabled"))
        self.zone.setChecked(defaults.get("zone_enabled",False))
        points.addRow(self.zone)
        self.radius=QDoubleSpinBox()
        self.radius.setRange(0,10000000)
        self.radius.setValue(defaults.get("radius_m",100))
        points.addRow(tr("audit.radius_m"),self.radius)
        coords=page("coordinates")
        self.format=QComboBox()
        for name in ("DD","DMS"):
            self.format.addItem(name,name)
        self.format.setCurrentIndex(max(0,self.format.findData(settings._get_str("coordinates/format","DD"))))
        coords.addRow(tr("audit.coordinate_format"),self.format)
        self.precision=QSpinBox()
        self.precision.setRange(0,10)
        self.precision.setValue(settings.get_integer("coordinates/precision",6,0,10))
        coords.addRow(tr("audit.precision"),self.precision)
        self.separator=QComboBox()
        for name,value in ((", ",", "),("; ","; "),(tr("ux.tab"),"\t")):
            self.separator.addItem(name,value)
        self.separator.setCurrentIndex(max(0,self.separator.findData(settings._get_str("coordinates/separator",", "))))
        coords.addRow(tr("audit.separator"),self.separator)
        buttons=QDialogButtonBox(QDialogButtonBox.StandardButton.Ok|QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def pick_color(self):
        color=QColorDialog.getColor(QColor(self.color.text()),self)
        if color.isValid():
            self.color.setText(color.name())

    def accept(self):
        if not QColor(self.color.text()).isValid():
            self.color.setFocus()
            return
        s=self.settings
        s.set_language(self.language.currentData())
        s._set_str("ui/theme",self.theme.currentData())
        s._set_bool("recovery/enabled",self.recovery.isChecked())
        s._set_str("recovery/seconds",str(self.interval.value()))
        s.set_online_cache_max_mb(self.cache.value())
        s._set_bool("map/antialias",self.antialias.isChecked())
        s._set_str("points/defaults",json.dumps(dict(symbol=self.shape.currentData(),size=self.size.value(),color=QColor(self.color.text()).name(),zone_enabled=self.zone.isChecked(),radius_m=self.radius.value())))
        s._set_str("coordinates/format",self.format.currentData())
        s._set_str("coordinates/precision",str(self.precision.value()))
        s._set_str("coordinates/separator",self.separator.currentData())
        super().accept()
