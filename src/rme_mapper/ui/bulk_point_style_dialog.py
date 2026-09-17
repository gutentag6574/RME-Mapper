"""Диалоговое окно группового изменения стиля выбранных точек (BulkPointStyleDialog)."""

import logging
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QColorDialog,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QSlider,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from rme_mapper.i18n import tr
from rme_mapper.models.map_point import MapPoint

logger = logging.getLogger("rme_mapper.ui.bulk_point_style_dialog")


class BulkPointStyleDialog(QDialog):
    """Диалог пакетного изменения визуального стиля группы пользовательских точек."""

    def __init__(
        self,
        parent: QWidget | None = None,
        points: list[MapPoint] | None = None,
        point_count: int | None = None,
    ) -> None:
        super().__init__(parent)
        self._points = points or []
        count = point_count if point_count is not None else len(self._points)
        self._marker_color = QColor(220, 30, 30)
        self._zone_color = QColor(220, 30, 30)

        self.setModal(True)
        self.resize(460, 480)
        self.setWindowTitle(tr("dialog.bulk_style.title", count=count))

        self._setup_ui()
        self._connect_signals()
        self.retranslate_ui()

    def _setup_ui(self) -> None:
        main_layout = QVBoxLayout(self)
        main_layout.setSpacing(12)

        # Информационная плашка
        self.info_label = QLabel(
            tr("dialog.bulk_style.title", count=len(self._points)), self
        )
        self.info_label.setStyleSheet("font-weight: bold; font-size: 13px; color: #202124;")
        main_layout.addWidget(self.info_label)

        # 1. Группа маркера
        self.marker_group = QGroupBox("Стиль маркера", self)
        marker_layout = QFormLayout(self.marker_group)
        marker_layout.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        # Форма маркера
        self.chk_symbol = QCheckBox(tr("dialog.bulk_style.change_symbol"), self)
        self.combo_symbol = QComboBox(self)
        self.combo_symbol.addItem(tr("shape.circle"), "circle")
        self.combo_symbol.addItem(tr("shape.square"), "square")
        self.combo_symbol.addItem(tr("shape.triangle"), "triangle")
        self.combo_symbol.setEnabled(False)
        marker_layout.addRow(self.chk_symbol, self.combo_symbol)

        # Размер маркера
        self.chk_size = QCheckBox(tr("dialog.bulk_style.change_size"), self)
        self.spin_size = QDoubleSpinBox(self)
        self.spin_size.setRange(4.0, 48.0)
        self.spin_size.setValue(12.0)
        self.spin_size.setSuffix(" px")
        self.spin_size.setEnabled(False)
        marker_layout.addRow(self.chk_size, self.spin_size)

        # Цвет маркера
        self.chk_color = QCheckBox(tr("dialog.bulk_style.change_color"), self)
        color_layout = QHBoxLayout()
        self.color_sample = QFrame(self)
        self.color_sample.setFixedSize(24, 24)
        self._update_color_sample(self.color_sample, self._marker_color)
        self.btn_pick_color = QPushButton("Выбрать цвет...", self)
        self.btn_pick_color.setEnabled(False)
        color_layout.addWidget(self.color_sample)
        color_layout.addWidget(self.btn_pick_color)
        color_layout.addStretch()
        marker_layout.addRow(self.chk_color, color_layout)

        main_layout.addWidget(self.marker_group)

        # 2. Группа геодезической зоны
        self.zone_group = QGroupBox("Геодезическая зона", self)
        zone_layout = QFormLayout(self.zone_group)
        zone_layout.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        # Включение зоны
        self.chk_zone = QCheckBox(tr("dialog.bulk_style.change_zone"), self)
        zone_rb_layout = QHBoxLayout()
        self.rb_zone_on = QRadioButton(tr("dialog.bulk_style.enable_zone"), self)
        self.rb_zone_off = QRadioButton(tr("dialog.bulk_style.disable_zone"), self)
        self.rb_zone_on.setChecked(True)
        self.rb_zone_on.setEnabled(False)
        self.rb_zone_off.setEnabled(False)
        zone_rb_layout.addWidget(self.rb_zone_on)
        zone_rb_layout.addWidget(self.rb_zone_off)
        zone_rb_layout.addStretch()
        zone_layout.addRow(self.chk_zone, zone_rb_layout)

        # Радиус зоны
        self.chk_radius = QCheckBox(tr("dialog.bulk_style.change_radius"), self)
        radius_layout = QHBoxLayout()
        self.edit_radius = QLineEdit("500", self)
        self.edit_radius.setEnabled(False)
        self.combo_radius_unit = QComboBox(self)
        self.combo_radius_unit.addItem("м", 1.0)
        self.combo_radius_unit.addItem("км", 1000.0)
        self.combo_radius_unit.setEnabled(False)
        radius_layout.addWidget(self.edit_radius)
        radius_layout.addWidget(self.combo_radius_unit)
        zone_layout.addRow(self.chk_radius, radius_layout)

        # Цвет зоны
        self.chk_zone_color = QCheckBox(tr("dialog.bulk_style.change_zone_color"), self)
        zone_color_layout = QHBoxLayout()
        self.zone_color_sample = QFrame(self)
        self.zone_color_sample.setFixedSize(24, 24)
        self._update_color_sample(self.zone_color_sample, self._zone_color)
        self.btn_pick_zone_color = QPushButton("Выбрать цвет...", self)
        self.btn_pick_zone_color.setEnabled(False)
        zone_color_layout.addWidget(self.zone_color_sample)
        zone_color_layout.addWidget(self.btn_pick_zone_color)
        zone_color_layout.addStretch()
        zone_layout.addRow(self.chk_zone_color, zone_color_layout)

        # Прозрачность зоны
        self.chk_opacity = QCheckBox(tr("dialog.bulk_style.change_opacity"), self)
        opacity_layout = QHBoxLayout()
        self.slider_opacity = QSlider(Qt.Orientation.Horizontal, self)
        self.slider_opacity.setRange(0, 100)
        self.slider_opacity.setValue(30)
        self.slider_opacity.setEnabled(False)
        self.spin_opacity = QSpinBox(self)
        self.spin_opacity.setRange(0, 100)
        self.spin_opacity.setValue(30)
        self.spin_opacity.setSuffix("%")
        self.spin_opacity.setEnabled(False)
        opacity_layout.addWidget(self.slider_opacity, stretch=1)
        opacity_layout.addWidget(self.spin_opacity)
        zone_layout.addRow(self.chk_opacity, opacity_layout)

        main_layout.addWidget(self.zone_group)

        # Кнопки диалога
        self.button_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
            self,
        )
        self.btn_ok = self.button_box.button(QDialogButtonBox.StandardButton.Ok)
        self.btn_cancel = self.button_box.button(QDialogButtonBox.StandardButton.Cancel)
        if self.btn_ok:
            self.btn_ok.setText(tr("dialog.bulk_style.apply"))
        if self.btn_cancel:
            self.btn_cancel.setText(tr("btn.cancel"))

        main_layout.addWidget(self.button_box)

    def _connect_signals(self) -> None:
        self.chk_symbol.toggled.connect(self.combo_symbol.setEnabled)
        self.chk_size.toggled.connect(self.spin_size.setEnabled)
        self.chk_color.toggled.connect(self.btn_pick_color.setEnabled)
        self.btn_pick_color.clicked.connect(self._pick_marker_color)

        self.chk_zone.toggled.connect(self.rb_zone_on.setEnabled)
        self.chk_zone.toggled.connect(self.rb_zone_off.setEnabled)
        self.chk_radius.toggled.connect(self.edit_radius.setEnabled)
        self.chk_radius.toggled.connect(self.combo_radius_unit.setEnabled)
        self.chk_zone_color.toggled.connect(self.btn_pick_zone_color.setEnabled)
        self.btn_pick_zone_color.clicked.connect(self._pick_zone_color)

        self.chk_opacity.toggled.connect(self.slider_opacity.setEnabled)
        self.chk_opacity.toggled.connect(self.spin_opacity.setEnabled)
        self.slider_opacity.valueChanged.connect(self.spin_opacity.setValue)
        self.spin_opacity.valueChanged.connect(self.slider_opacity.setValue)

        self.button_box.accepted.connect(self._validate_and_accept)
        self.button_box.rejected.connect(self.reject)

    def _update_color_sample(self, frame: QFrame, color: QColor) -> None:
        frame.setStyleSheet(
            f"background-color: {color.name()}; border: 1px solid #D9DDE3; border-radius: 3px;"
        )

    def _pick_marker_color(self) -> None:
        col = QColorDialog.getColor(self._marker_color, self, "Выбор цвета маркера")
        if col.isValid():
            self._marker_color = col
            self._update_color_sample(self.color_sample, col)

    def _pick_zone_color(self) -> None:
        col = QColorDialog.getColor(self._zone_color, self, "Выбор цвета зоны")
        if col.isValid():
            self._zone_color = col
            self._update_color_sample(self.zone_color_sample, col)

    def _validate_and_accept(self) -> None:
        if not self.has_any_changes():
            QMessageBox.information(
                self,
                tr("dialog.error_title"),
                "Отметьте хотя бы одно свойство для применения.",
            )
            return

        if self.chk_radius.isChecked():
            raw = self.edit_radius.text().strip().replace(",", ".")
            try:
                val = float(raw)
                if val <= 0:
                    raise ValueError
            except ValueError:
                QMessageBox.warning(
                    self,
                    tr("dialog.error_title"),
                    "Укажите корректный положительный радиус зоны.",
                )
                return

        self.accept()

    _on_apply = _validate_and_accept

    def has_any_changes(self) -> bool:
        """Проверка, выбрано ли хотя бы одно свойство для изменения."""
        return any(
            [
                self.chk_symbol.isChecked(),
                self.chk_size.isChecked(),
                self.chk_color.isChecked(),
                self.chk_zone.isChecked(),
                self.chk_radius.isChecked(),
                self.chk_zone_color.isChecked(),
                self.chk_opacity.isChecked(),
            ]
        )

    def get_style_changes(self) -> dict[str, Any]:
        """Получение словаря изменений только для отмеченных пользователем свойств."""
        changes: dict[str, Any] = {}
        if self.chk_symbol.isChecked():
            changes["symbol"] = self.combo_symbol.currentData() or "circle"
        if self.chk_size.isChecked():
            changes["size"] = self.spin_size.value()
        if self.chk_color.isChecked():
            changes["red"] = self._marker_color.red()
            changes["green"] = self._marker_color.green()
            changes["blue"] = self._marker_color.blue()

        if self.chk_zone.isChecked():
            changes["zone_enabled"] = self.rb_zone_on.isChecked()

        if self.chk_radius.isChecked():
            raw = self.edit_radius.text().strip().replace(",", ".")
            try:
                factor = float(self.combo_radius_unit.currentData() or 1.0)
                changes["radius_m"] = float(raw) * factor
            except ValueError:
                pass

        if self.chk_zone_color.isChecked():
            changes["zone_red"] = self._zone_color.red()
            changes["zone_green"] = self._zone_color.green()
            changes["zone_blue"] = self._zone_color.blue()

        if self.chk_opacity.isChecked():
            changes["zone_opacity"] = self.spin_opacity.value()

        return changes

    def retranslate_ui(self) -> None:
        """Локализация элементов управления диалога."""
        self.setWindowTitle(tr("dialog.bulk_style.title", count=len(self._points)))
        self.info_label.setText(tr("dialog.bulk_style.title", count=len(self._points)))

        self.marker_group.setTitle(tr("properties.section_marker"))
        self.chk_symbol.setText(tr("dialog.bulk_style.change_symbol"))
        self.chk_size.setText(tr("dialog.bulk_style.change_size"))
        self.chk_color.setText(tr("dialog.bulk_style.change_color"))

        self.zone_group.setTitle(tr("properties.section_zone"))
        self.chk_zone.setText(tr("dialog.bulk_style.change_zone"))
        self.rb_zone_on.setText(tr("dialog.bulk_style.enable_zone"))
        self.rb_zone_off.setText(tr("dialog.bulk_style.disable_zone"))
        self.chk_radius.setText(tr("dialog.bulk_style.change_radius"))
        self.chk_zone_color.setText(tr("dialog.bulk_style.change_zone_color"))
        self.chk_opacity.setText(tr("dialog.bulk_style.change_opacity"))

        if self.btn_ok:
            self.btn_ok.setText(tr("dialog.bulk_style.apply"))
        if self.btn_cancel:
            self.btn_cancel.setText(tr("btn.cancel"))
