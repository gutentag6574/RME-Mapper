"""Панель управления слоями карты."""

import logging
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QCheckBox, QLabel, QVBoxLayout, QWidget

from rme_mapper.i18n import tr
from rme_mapper.models.map_layer import MapLayer

logger = logging.getLogger("rme_mapper.ui.panels.layers_panel")


class LayersPanel(QWidget):
    """Панель со списком чекбоксов слоев активной карты."""

    layer_visibility_changed = Signal(str, bool)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("layersPanel")

        self.layer_checkboxes: dict[str, QCheckBox] = {}
        self._layers: list[MapLayer] = []

        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        self.title_label = QLabel()
        title_font = QFont()
        title_font.setBold(True)
        title_font.setPointSize(11)
        self.title_label.setFont(title_font)
        layout.addWidget(self.title_label)

        self.layers_container = QWidget()
        self.layers_container.setObjectName("layersContainer")
        self.layers_layout = QVBoxLayout(self.layers_container)
        self.layers_layout.setContentsMargins(4, 2, 4, 4)
        self.layers_layout.setSpacing(4)
        layout.addWidget(self.layers_container)

        self.retranslate_ui()

    def retranslate_ui(self) -> None:
        """Обновление локализованных текстов панели слоев."""
        self.title_label.setText(tr("panel.layers"))

    def set_layers(self, layers: list[MapLayer]) -> None:
        """Построение списка чекбоксов для переданного набора слоев."""
        self.clear_layers()
        self._layers = list(layers)

        for layer in self._layers:
            chk = QCheckBox(layer.display_name)
            chk.setObjectName(f"chk_{layer.id}")
            chk.setChecked(layer.visible)
            chk.setCursor(Qt.CursorShape.PointingHandCursor)
            chk.toggled.connect(
                lambda checked, lid=layer.id: self._on_checkbox_toggled(lid, checked)
            )
            self.layers_layout.addWidget(chk)
            self.layer_checkboxes[layer.id] = chk

    def _on_checkbox_toggled(self, layer_id: str, visible: bool) -> None:
        self.layer_visibility_changed.emit(layer_id, visible)

    def set_layer_checked(self, layer_id: str, visible: bool) -> None:
        """Установка состояния чекбокса без генерации повторных сигналов."""
        chk = self.layer_checkboxes.get(layer_id)
        if chk:
            chk.blockSignals(True)
            chk.setChecked(visible)
            chk.blockSignals(False)

    def clear_layers(self) -> None:
        """Очистка всех чекбоксов слоев."""
        for chk in self.layer_checkboxes.values():
            self.layers_layout.removeWidget(chk)
            chk.deleteLater()
        self.layer_checkboxes.clear()
        self._layers.clear()
