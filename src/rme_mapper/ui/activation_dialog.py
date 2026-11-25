"""Диалог активации GeoPoint Mapper (показывается до открытия рабочего окна)."""
from __future__ import annotations

import threading
from typing import Any

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from rme_mapper.app_info import APP_NAME, APP_VERSION
from rme_mapper.i18n import tr
from rme_mapper.services.license_service import LicenseCheckResult, LicenseService


class ActivationDialog(QDialog):
    """Окно «Активация GeoPoint Mapper»: название программы, поле для ключа и кнопки."""

    _sig_activation_done = Signal(object)

    def __init__(
        self,
        license_service: LicenseService,
        initial_result: LicenseCheckResult | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._license_service = license_service
        self._result: LicenseCheckResult | None = None
        self._busy = False
        self._worker: threading.Thread | None = None

        self.setWindowTitle(tr("license.dialog_title"))
        self.setModal(True)
        self.setMinimumWidth(460)
        self.resize(480, 170)

        self._sig_activation_done.connect(self._on_activation_finished)
        self._build_ui(initial_result)

    @property
    def activation_result(self) -> LicenseCheckResult | None:
        return self._result

    def _build_ui(self, initial_result: LicenseCheckResult | None) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 20, 20, 18)
        root.setSpacing(12)

        title_lbl = QLabel(f"{APP_NAME} {APP_VERSION}", self)
        title_lbl.setStyleSheet("font-size: 16px; font-weight: 700;")
        root.addWidget(title_lbl)

        self.key_edit = QLineEdit(self)
        self.key_edit.setObjectName("licenseKeyInput")
        self.key_edit.setPlaceholderText("GPM-XXXX-XXXX-XXXX-XXXX-XXXX-XXXX-XXXX-XXXX")
        self.key_edit.setClearButtonEnabled(True)
        self.key_edit.setStyleSheet("font-family: Consolas, monospace; font-size: 13px;")
        self.key_edit.returnPressed.connect(self._on_activate_clicked)
        root.addWidget(self.key_edit)

        self.progress_bar = QProgressBar(self)
        self.progress_bar.setRange(0, 0)
        self.progress_bar.setVisible(False)
        root.addWidget(self.progress_bar)

        self.status_label = QLabel("", self)
        self.status_label.setWordWrap(True)
        self.status_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.status_label.setVisible(False)
        root.addWidget(self.status_label)

        if initial_result is not None and initial_result.message and initial_result.status != "unactivated":
            self._set_status_message(initial_result.message, is_error=not initial_result.authorized)

        root.addStretch(1)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)
        btn_row.addStretch(1)

        self.btn_exit = QPushButton(tr("license.btn_exit"), self)
        self.btn_exit.setObjectName("btnExitUnlicensed")
        self.btn_exit.clicked.connect(self.reject)
        btn_row.addWidget(self.btn_exit)

        self.btn_activate = QPushButton(tr("license.btn_activate"), self)
        self.btn_activate.setObjectName("primaryAccentBtn")
        self.btn_activate.setDefault(True)
        self.btn_activate.clicked.connect(self._on_activate_clicked)
        btn_row.addWidget(self.btn_activate)

        root.addLayout(btn_row)

    def _set_status_message(self, text: str, *, is_error: bool = False) -> None:
        is_dark = self.palette().window().color().lightness() < 128
        if is_error:
            color = "#f87171" if is_dark else "#b91c1c"
            bg = "rgba(239, 68, 68, 0.14)" if is_dark else "rgba(220, 38, 38, 0.08)"
            border = "rgba(248, 113, 113, 0.45)" if is_dark else "rgba(220, 38, 38, 0.35)"
        else:
            color = "#60a5fa" if is_dark else "#1d4ed8"
            bg = "rgba(59, 130, 246, 0.12)" if is_dark else "rgba(37, 99, 235, 0.08)"
            border = "rgba(96, 165, 250, 0.40)" if is_dark else "rgba(37, 99, 235, 0.30)"
        self.status_label.setStyleSheet(
            f"color: {color}; background-color: {bg}; border: 1px solid {border};"
            " border-radius: 6px; padding: 8px 10px; font-weight: 600;"
        )
        self.status_label.setText(text)
        self.status_label.setVisible(bool(text))

    def _set_busy(self, busy: bool) -> None:
        self._busy = busy
        self.key_edit.setEnabled(not busy)
        self.btn_activate.setEnabled(not busy)
        self.progress_bar.setVisible(busy)

    def _on_activate_clicked(self) -> None:
        if self._busy:
            return
        raw_key = self.key_edit.text().strip()
        if not raw_key:
            self._set_status_message(tr("license.err.empty_key"), is_error=True)
            self.key_edit.setFocus()
            return

        self._set_busy(True)
        self._set_status_message(tr("license.status.activating"), is_error=False)

        def _worker() -> None:
            res = self._license_service.activate(raw_key)
            self._sig_activation_done.emit(res)

        self._worker = threading.Thread(target=_worker, daemon=True)
        self._worker.start()

    def _on_activation_finished(self, res: LicenseCheckResult) -> None:
        self._set_busy(False)
        if res.authorized:
            self._result = res
            self.accept()
            return
        self._set_status_message(res.message or tr("license.err.key_invalid"), is_error=True)

    def reject(self) -> None:
        if self._busy:
            return
        super().reject()


def show_blocking_activation(
    license_service: LicenseService,
    *,
    initial_result: LicenseCheckResult | None = None,
    parent: QWidget | None = None,
) -> tuple[bool, LicenseCheckResult | None]:
    """Показать модальное окно «Активация GeoPoint Mapper» до открытия рабочего окна."""
    dlg = ActivationDialog(license_service, initial_result=initial_result, parent=parent)
    accepted = dlg.exec() == QDialog.DialogCode.Accepted
    return accepted, dlg.activation_result

