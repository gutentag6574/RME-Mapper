"""Диалоговое окно создания и редактирования группы объектов (GroupDialog)."""

import logging

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from rme_mapper.i18n import tr
from rme_mapper.models.object_group import (
    ObjectGroup,
    validate_group_description,
    validate_group_name,
)
from rme_mapper.services.group_service import GroupService

logger = logging.getLogger("rme_mapper.ui.group_dialog")


class GroupDialog(QDialog):
    """Компактный модальный диалог создания или редактирования группы объектов."""

    def __init__(
        self,
        parent: QWidget | None = None,
        group: ObjectGroup | None = None,
        group_service: GroupService | None = None,
    ) -> None:
        super().__init__(parent)
        self.group = group
        self.group_service = group_service

        self.name_result: str = ""
        self.description_result: str = ""

        self._setup_ui()
        self._populate_data()

    def _setup_ui(self) -> None:
        is_edit = self.group is not None
        title = tr("dialog.group.title_edit") if is_edit else tr("dialog.group.title_create")
        self.setWindowTitle(title)
        self.setMinimumWidth(380)

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(16, 16, 16, 16)
        main_layout.setSpacing(12)

        form_layout = QFormLayout()
        form_layout.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        form_layout.setSpacing(8)

        # 1. Название группы
        self.name_label = QLabel(tr("dialog.group.name"))
        self.name_edit = QLineEdit(self)
        self.name_edit.setObjectName("groupNameEdit")
        self.name_edit.setMaxLength(200)
        self.name_edit.setPlaceholderText(tr("dialog.group.name_placeholder"))
        form_layout.addRow(self.name_label, self.name_edit)

        # 2. Описание группы
        self.desc_label = QLabel(tr("dialog.group.description"))
        self.desc_edit = QTextEdit(self)
        self.desc_edit.setObjectName("groupDescEdit")
        self.desc_edit.setPlaceholderText(tr("dialog.group.description_placeholder"))
        self.desc_edit.setMaximumHeight(120)
        form_layout.addRow(self.desc_label, self.desc_edit)

        main_layout.addLayout(form_layout)

        # 3. Кнопки Сохранить / Отмена
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()

        self.btn_cancel = QPushButton(tr("btn.cancel"), self)
        self.btn_cancel.setObjectName("btnGroupCancel")
        self.btn_cancel.clicked.connect(self.reject)
        btn_layout.addWidget(self.btn_cancel)

        self.btn_ok = QPushButton(tr("btn.save"), self)
        self.btn_ok.setObjectName("btnGroupSave")
        self.btn_ok.setDefault(True)
        self.btn_ok.clicked.connect(self._on_save_clicked)
        btn_layout.addWidget(self.btn_ok)

        main_layout.addLayout(btn_layout)

    def _populate_data(self) -> None:
        if self.group:
            self.name_edit.setText(self.group.name)
            self.desc_edit.setPlainText(self.group.description)

    def _on_save_clicked(self) -> None:
        raw_name = self.name_edit.text()
        raw_desc = self.desc_edit.toPlainText()

        try:
            cleaned_name = validate_group_name(raw_name)
        except ValueError as e:
            QMessageBox.warning(self, tr("dialog.error_title"), str(e))
            self.name_edit.setFocus()
            return

        try:
            cleaned_desc = validate_group_description(raw_desc)
        except ValueError as e:
            QMessageBox.warning(self, tr("dialog.error_title"), str(e))
            self.desc_edit.setFocus()
            return

        # Проверка уникальности имени в проекте (case-insensitive)
        if self.group_service:
            existing = self.group_service.find_group_by_name(cleaned_name)
            current_id = self.group.id if self.group else None
            if existing and existing.id != current_id:
                QMessageBox.warning(
                    self,
                    tr("dialog.error_title"),
                    tr("dialog.group.err_duplicate_name"),
                )
                self.name_edit.setFocus()
                return

        self.name_result = cleaned_name
        self.description_result = cleaned_desc
        self.accept()
