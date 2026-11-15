"""Контроллер фоновой и ручной проверки лицензий GeoPoint Mapper."""
from __future__ import annotations

import logging
import threading
from typing import Any

from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtWidgets import QDialog, QMessageBox, QWidget

from rme_mapper.i18n import tr
from rme_mapper.services.license_config import BACKGROUND_CHECK_INTERVAL_SEC
from rme_mapper.services.license_service import LicenseCheckResult, LicenseService
from rme_mapper.ui.activation_dialog import show_blocking_activation

logger = logging.getLogger("rme_mapper.ui.license_controller")


class LicenseController(QObject):
    """Управляет фоновой проверкой списка лицензий, кнопкой «Проверить сейчас» и блокировкой."""

    check_started = Signal()
    check_finished = Signal(object, bool)  # (LicenseCheckResult, manual)
    license_lost = Signal(object)  # LicenseCheckResult

    _sig_bg_done = Signal(object, bool)

    def __init__(
        self,
        license_service: LicenseService,
        *,
        main_window: Any | None = None,
        interval_sec: int = BACKGROUND_CHECK_INTERVAL_SEC,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._service = license_service
        self._main_window = main_window
        self._is_checking = False
        self._lockout_in_progress = False
        self._last_result: LicenseCheckResult | None = license_service.get_status_snapshot()

        self._sig_bg_done.connect(self._on_check_completed)

        self._timer = QTimer(self)
        self._timer.setInterval(max(5, int(interval_sec)) * 1000)
        self._timer.timeout.connect(lambda: self.start_check(manual=False))

    @property
    def service(self) -> LicenseService:
        return self._service

    @property
    def license_service(self) -> LicenseService:
        return self._service

    @property
    def is_checking(self) -> bool:
        return self._is_checking

    @property
    def last_result(self) -> LicenseCheckResult | None:
        return self._last_result

    @property
    def latest_result(self) -> LicenseCheckResult | None:
        return self._last_result

    def check_now_async(self) -> None:
        self.start_check(manual=False)

    @property
    def latest_result(self) -> LicenseCheckResult | None:
        return self._last_result

    def start(self) -> None:
        """Запустить периодическое обновление списка в фоне."""
        self._lockout_in_progress = False
        if not self._timer.isActive():
            self._timer.start()

    def check_now_async(self) -> None:
        """Запустить фоновую онлайн-проверку без блокировки UI."""
        self.start_check(manual=False)

    def stop(self) -> None:
        if self._timer.isActive():
            self._timer.stop()

    def start_background_checks(self) -> None:
        self.start()
        self.check_now_async()

    def stop_background_checks(self) -> None:
        self.stop()

    def reset_activation_flow(self, parent: QWidget | None = None) -> None:
        """Сбросить сохранённую активацию по запросу пользователя и вернуть экран активации."""
        answer = QMessageBox.question(
            parent or (self._main_window if isinstance(self._main_window, QWidget) else None),
            tr("license.reset_confirm_title"),
            tr("license.reset_confirm_body"),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self._service.reset_activation()
        res = self._service.get_status_snapshot()
        self._last_result = res
        self.handle_license_loss(res)

    def check_now_sync(self) -> LicenseCheckResult:
        """Выполнить синхронную онлайн-проверку (для «Настройки → Лицензия → Проверить сейчас»)."""
        res = self._service.verify_online()
        self._last_result = res
        self.check_finished.emit(res, True)
        if not res.authorized:
            QTimer.singleShot(0, lambda r=res: self.handle_license_loss(r))
        return res

    def start_check(self, *, manual: bool = False) -> None:
        if self._is_checking or self._lockout_in_progress:
            return
        self._is_checking = True
        self.check_started.emit()

        def _worker() -> None:
            try:
                res = self._service.verify_online()
            except Exception as exc:
                logger.exception("Непредвиденная ошибка фоновой проверки лицензии: %s", exc)
                res = self._service.get_status_snapshot()
            self._sig_bg_done.emit(res, manual)

        threading.Thread(target=_worker, daemon=True).start()

    def _on_check_completed(self, result: LicenseCheckResult, manual: bool) -> None:
        self._is_checking = False
        self._last_result = result
        self.check_finished.emit(result, manual)
        if not result.authorized:
            self.handle_license_loss(result)

    def handle_license_loss(self, result: LicenseCheckResult) -> None:
        """Заблокировать рабочее окно, дать сохранить изменённый проект и вернуть экран активации."""
        if self._lockout_in_progress:
            return
        self._lockout_in_progress = True
        self.stop()
        self.license_lost.emit(result)

        win = self._main_window
        if win is None:
            return

        if hasattr(win, "set_license_locked"):
            win.set_license_locked(True)

        # Закрываем открытые модальные окна настроек, чтобы они не мешали сохранению и активации
        for dlg in win.findChildren(QDialog) if isinstance(win, QWidget) else []:
            if dlg.isVisible():
                dlg.reject()

        save_modified_project_before_lockout(win, result)

        if hasattr(win, "reset_workspace_on_license_loss"):
            win.reset_workspace_on_license_loss()

        accepted, new_res = show_blocking_activation(
            self._service,
            initial_result=result,
            parent=win if isinstance(win, QWidget) else None,
        )
        if accepted and new_res is not None and new_res.authorized:
            self._last_result = new_res
            self._lockout_in_progress = False
            if hasattr(win, "set_license_locked"):
                win.set_license_locked(False)
            self.start()
            return

        if hasattr(win, "force_close_unlicensed"):
            win.force_close_unlicensed()

    def reset_activation_flow(self, parent: QWidget | None = None) -> bool:
        """Сбросить текущую активацию на этом ПК из «Настройки → Лицензия»."""
        answer = QMessageBox.question(
            parent,
            tr("license.reset_confirm_title"),
            tr("license.reset_confirm_body"),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return False

        self._service.reset_activation()
        new_res = self._service.get_status_snapshot()
        self._last_result = new_res
        self.check_finished.emit(new_res, True)
        if parent is not None and hasattr(parent, "accept"):
            parent.accept()
        self.handle_license_loss(new_res)
        return True


def save_modified_project_before_lockout(window: Any, result: LicenseCheckResult) -> None:
    """При отзыве/истечении во время работы дать сохранить изменённый проект перед экраном активации."""
    pc = getattr(window, "project_controller", None)
    if pc is None:
        return

    def _is_dirty() -> bool:
        if hasattr(window, "is_project_dirty"):
            return bool(window.is_project_dirty())
        return bool(getattr(pc, "is_modified", False))

    if not _is_dirty():
        return

    reason = result.message or tr("license.err.key_revoked")
    parent_widget: QWidget | None = window if isinstance(window, QWidget) else None

    while _is_dirty():
        box = QMessageBox(parent_widget)
        box.setIcon(QMessageBox.Icon.Warning)
        box.setWindowTitle(tr("license.lost_title"))
        box.setText(tr("license.lost_save_prompt", reason=reason))
        btn_save = box.addButton(tr("license.btn_save_project"), QMessageBox.ButtonRole.AcceptRole)
        btn_discard = box.addButton(tr("license.btn_discard_changes"), QMessageBox.ButtonRole.DestructiveRole)
        box.setDefaultButton(btn_save)
        box.exec()

        if box.clickedButton() == btn_discard:
            pc.set_modified(False)
            return

        if box.clickedButton() == btn_save:
            if hasattr(window, "save_project_before_license_lock"):
                saved = bool(window.save_project_before_license_lock())
            else:
                saved = bool(pc.save_project_workflow())
            if saved or not _is_dirty():
                return
            retry_box = QMessageBox(parent_widget)
            retry_box.setIcon(QMessageBox.Icon.Question)
            retry_box.setWindowTitle(tr("license.lost_title"))
            retry_box.setText(tr("license.lost_save_retry_prompt"))
            btn_retry = retry_box.addButton(tr("license.btn_retry_save"), QMessageBox.ButtonRole.AcceptRole)
            btn_drop = retry_box.addButton(tr("license.btn_discard_changes"), QMessageBox.ButtonRole.DestructiveRole)
            retry_box.setDefaultButton(btn_retry)
            retry_box.exec()
            if retry_box.clickedButton() == btn_drop:
                pc.set_modified(False)
                return
