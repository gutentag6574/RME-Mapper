"""Диалог активации GeoPoint Mapper (показывается до открытия рабочего окна)."""
from __future__ import annotations

import threading
from typing import Any

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from rme_mapper.app_info import (
    APP_NAME,
    APP_VERSION,
    AUTHOR_EMAIL,
    AUTHOR_TELEGRAM,
    format_telegram_url,
)
from rme_mapper.i18n import tr
from rme_mapper.services.license_service import LicenseCheckResult, LicenseService


class ActivationDialog(QDialog):
    """Окно «Активация GeoPoint Mapper»: ввод ключа, справка по активации и выход."""

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
        self.setMinimumWidth(540)
        self.resize(560, 390)

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

        sub_lbl = QLabel(tr("license.header_subtitle"), self)
        sub_lbl.setWordWrap(True)
        root.addWidget(sub_lbl)

        grp = QGroupBox(tr("license.key_group_title"), self)
        grp_layout = QVBoxLayout(grp)
        grp_layout.setSpacing(8)

        lbl_prompt = QLabel(tr("license.key_label"), grp)
        grp_layout.addWidget(lbl_prompt)

        self.key_edit = QLineEdit(grp)
        self.key_edit.setObjectName("licenseKeyInput")
        self.key_edit.setPlaceholderText("GPM-XXXX-XXXX-XXXX-XXXX-XXXX-XXXX-XXXX-XXXX")
        self.key_edit.setClearButtonEnabled(True)
        self.key_edit.setStyleSheet("font-family: Consolas, monospace; font-size: 13px;")
        self.key_edit.returnPressed.connect(self._on_activate_clicked)
        grp_layout.addWidget(self.key_edit)

        hint_lbl = QLabel(tr("license.key_hint"), grp)
        hint_lbl.setWordWrap(True)
        hint_lbl.setStyleSheet("color: #64748b; font-size: 12px;")
        grp_layout.addWidget(hint_lbl)

        root.addWidget(grp)

        self.progress_bar = QProgressBar(self)
        self.progress_bar.setRange(0, 0)
        self.progress_bar.setVisible(False)
        root.addWidget(self.progress_bar)

        self.status_label = QLabel("", self)
        self.status_label.setWordWrap(True)
        self.status_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        root.addWidget(self.status_label)

        if initial_result is not None and initial_result.message and initial_result.status != "unactivated":
            self._set_status_message(initial_result.message, is_error=not initial_result.authorized)

        tg_url = format_telegram_url(AUTHOR_TELEGRAM)
        is_dark = self.palette().window().color().lightness() < 128
        link_color = "#60a5fa" if is_dark else "#2563eb"
        support_html = tr(
            "license.support_contacts",
            telegram=f'<a href="{tg_url}" style="color: {link_color}; text-decoration: none;">{AUTHOR_TELEGRAM}</a>',
            email=f'<a href="mailto:{AUTHOR_EMAIL}" style="color: {link_color}; text-decoration: none;">{AUTHOR_EMAIL}</a>',
        )
        self.support_label = QLabel(support_html, self)
        self.support_label.setOpenExternalLinks(True)
        self.support_label.setWordWrap(True)
        self.support_label.setStyleSheet("font-size: 11px;")
        root.addWidget(self.support_label)

        root.addStretch(1)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)

        self.btn_help = QPushButton(tr("license.btn_help"), self)
        self.btn_help.setObjectName("btnActivationHelp")
        self.btn_help.clicked.connect(self._on_help_clicked)
        btn_row.addWidget(self.btn_help)

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

    def _set_busy(self, busy: bool) -> None:
        self._busy = busy
        self.key_edit.setEnabled(not busy)
        self.btn_activate.setEnabled(not busy)
        self.btn_help.setEnabled(not busy)
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

    def _on_help_clicked(self) -> None:
        body = tr("license.help_body", telegram=AUTHOR_TELEGRAM, email=AUTHOR_EMAIL)
        QMessageBox.information(self, tr("license.help_title"), body)

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

