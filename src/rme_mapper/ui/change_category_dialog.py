"""Диалоговое окно массового изменения категории точек (ChangeCategoryDialog)."""
from __future__ import annotations


import logging

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from rme_mapper.i18n import tr
from rme_mapper.models.point_style import validate_category

logger = logging.getLogger("rme_mapper.ui.change_category_dialog")


class ChangeCategoryDialog(QDialog):
    """Компактный диалог задания новой категории для выбранных точек."""

    def __init__(
        self,
        parent: QWidget | None = None,
        existing_categories: list[str] | None = None,
        current_category: str = "",
    ) -> None:
        super().__init__(parent)
        self.existing_categories = existing_categories or []
        self.category_result: str = ""

        self._setup_ui(current_category)

    def _setup_ui(self, current_category: str) -> None:
        self.setWindowTitle(tr("dialog.change_category.title"))
        self.setMinimumWidth(320)

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(16, 16, 16, 16)
        main_layout.setSpacing(12)

        form_layout = QFormLayout()
        form_layout.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        self.cat_label = QLabel(tr("dialog.change_category.label"))
        self.cat_combo = QComboBox(self)
        self.cat_combo.setObjectName("changeCategoryCombo")
        self.cat_combo.setEditable(True)
        if self.cat_combo.lineEdit():
            self.cat_combo.lineEdit().setMaxLength(200)
            self.cat_combo.lineEdit().setPlaceholderText(tr("dialog.point.category_placeholder"))

        # Добавление пустой категории («Без категории») и существующих
        self.cat_combo.addItem("")
        for cat in self.existing_categories:
            if cat and self.cat_combo.findText(cat) == -1:
                self.cat_combo.addItem(cat)

        self.cat_combo.setCurrentText(current_category)
        form_layout.addRow(self.cat_label, self.cat_combo)

        main_layout.addLayout(form_layout)

        # Кнопки
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()

        self.btn_cancel = QPushButton(tr("btn.cancel"), self)
        self.btn_cancel.setObjectName("btnCategoryCancel")
        self.btn_cancel.clicked.connect(self.reject)
        btn_layout.addWidget(self.btn_cancel)

        self.btn_ok = QPushButton(tr("btn.save"), self)
        self.btn_ok.setObjectName("btnCategorySave")
        self.btn_ok.setDefault(True)
        self.btn_ok.clicked.connect(self._on_save_clicked)
        btn_layout.addWidget(self.btn_ok)

        main_layout.addLayout(btn_layout)

    def _on_save_clicked(self) -> None:
        raw_text = self.cat_combo.currentText().strip()
        try:
            cleaned = validate_category(raw_text)
        except ValueError as e:
            QMessageBox.warning(self, tr("dialog.error_title"), str(e))
            self.cat_combo.setFocus()
            return

        self.category_result = cleaned
        self.accept()
