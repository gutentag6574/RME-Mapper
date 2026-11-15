"""Контроллер и баннер уведомлений системы автообновлений GeoPoint Mapper."""
from __future__ import annotations

from datetime import datetime, timezone
import logging
import os
from pathlib import Path
import subprocess
import sys
import threading
from typing import Any

from PySide6.QtCore import QObject, Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QDialogButtonBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from rme_mapper.app_info import APP_VERSION
from rme_mapper.i18n import tr
from rme_mapper.services.update_service import (
    INSTALL_MODE_INSTALLED,
    INSTALL_MODE_PORTABLE,
    INSTALL_MODE_SOURCE,
    RELEASES_HTML_URL,
    DownloadResult,
    UpdateCheckResult,
    UpdateInfo,
    UpdateService,
    format_size_human,
    launch_installer_and_relaunch,
)

logger = logging.getLogger("rme_mapper.ui.update_controller")


def format_utc_local_display(iso_utc: str) -> str:
    """Форматировать ISO UTC отметку в локальное читаемое время."""
    text = str(iso_utc or "").strip()
    if not text:
        return tr("updates.last_check_never")
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        local_dt = dt.astimezone()
        return local_dt.strftime("%Y-%m-%d %H:%M")
    except Exception:
        return iso_utc


def install_mode_display_name(mode: str) -> str:
    """Локализованное название режима установки."""
    mapping = {
        INSTALL_MODE_INSTALLED: tr("updates.mode_installed"),
        INSTALL_MODE_PORTABLE: tr("updates.mode_portable"),
        INSTALL_MODE_SOURCE: tr("updates.mode_source"),
    }
    return mapping.get(mode, tr("updates.mode_unknown"))


class ReleaseNotesDialog(QDialog):
    """Окно просмотра описания релиза и ссылки на GitHub."""

    def __init__(self, info: UpdateInfo, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(tr("updates.notes_title", version=info.latest_version))
        self.resize(520, 380)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)

        header = QLabel(f"{info.release_name} ({info.latest_version})", self)
        header.setStyleSheet("font-weight: 700; font-size: 14px;")
        layout.addWidget(header)

        browser = QTextBrowser(self)
        browser.setOpenExternalLinks(True)
        body = (info.notes or "").strip() or info.html_url
        browser.setMarkdown(body) if hasattr(browser, "setMarkdown") else browser.setPlainText(body)
        layout.addWidget(browser, 1)

        footer = QHBoxLayout()
        btn_link = QPushButton("GitHub Releases", self)
        btn_link.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(info.html_url or RELEASES_HTML_URL)))
        footer.addWidget(btn_link)
        footer.addStretch(1)
        box = QDialogButtonBox(QDialogButtonBox.StandardButton.Close, self)
        box.rejected.connect(self.reject)
        box.accepted.connect(self.accept)
        footer.addWidget(box)
        layout.addLayout(footer)


class UpdateController(QObject):
    """Асинхронный координатор проверки, загрузки и применения обновлений."""

    check_started = Signal()
    check_finished = Signal(object, bool)  # (UpdateCheckResult, manual)
    download_started = Signal()
    download_progress = Signal(int, int)  # (received_bytes, total_bytes)
    download_finished = Signal(object)  # DownloadResult
    state_changed = Signal()

    _sig_check_done = Signal(object, bool)
    _sig_dl_progress = Signal(int, int)
    _sig_dl_done = Signal(object)

    def __init__(
        self,
        settings_service: Any = None,
        update_service: UpdateService | None = None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._settings = settings_service
        self._service = update_service or UpdateService(current_version=APP_VERSION)
        self._last_check_result: UpdateCheckResult | None = None
        self._last_download_result: DownloadResult | None = None
        self._active_info: UpdateInfo | None = None
        self._banner_dismissed_version: str = ""

        self._sig_check_done.connect(self._handle_check_done, Qt.ConnectionType.QueuedConnection)
        self._sig_dl_progress.connect(self.download_progress.emit, Qt.ConnectionType.QueuedConnection)
        self._sig_dl_done.connect(self._handle_download_done, Qt.ConnectionType.QueuedConnection)

    @property
    def service(self) -> UpdateService:
        return self._service

    @property
    def last_check_result(self) -> UpdateCheckResult | None:
        return self._last_check_result

    @property
    def last_download_result(self) -> DownloadResult | None:
        return self._last_download_result

    @property
    def active_info(self) -> UpdateInfo | None:
        return self._active_info

    @property
    def is_checking(self) -> bool:
        return self._service.is_checking

    @property
    def is_downloading(self) -> bool:
        return self._service.is_downloading

    def start_check(self, manual: bool = False) -> bool:
        """Запустить фоновую проверку обновлений вне UI-потока."""
        if self._service.is_checking:
            return False
        timeout = 15
        if self._settings and hasattr(self._settings, "get_network_timeout_sec"):
            timeout = self._settings.get_network_timeout_sec(15)

        self.check_started.emit()
        self.state_changed.emit()

        def _worker() -> None:
            res = self._service.check_for_updates(timeout_sec=timeout)
            self._sig_check_done.emit(res, bool(manual))

        t = threading.Thread(target=_worker, name="rme-update-check", daemon=True)
        t.start()
        return True

    def _handle_check_done(self, result: UpdateCheckResult, manual: bool) -> None:
        self._last_check_result = result
        now_utc = result.checked_at_utc or datetime.now(timezone.utc).isoformat()
        if self._settings is not None:
            if hasattr(self._settings, "set_last_update_check_utc"):
                self._settings.set_last_update_check_utc(now_utc)
            if result.status in ("up_to_date", "update_available") and hasattr(self._settings, "set_last_update_success_utc"):
                self._settings.set_last_update_success_utc(now_utc)

        if result.status == "update_available" and result.info is not None:
            self._active_info = result.info
            self._last_download_result = None
            if manual:
                self._banner_dismissed_version = ""
        elif result.status == "up_to_date":
            self._active_info = result.info
            self._last_download_result = None

        self.check_finished.emit(result, manual)
        self.state_changed.emit()

    def start_download(self, info: UpdateInfo | None = None) -> bool:
        """Начать загрузку и проверку SHA-256 выбранного релиза."""
        target = info or self._active_info
        if target is None or not target.has_update:
            return False
        if self._service.is_downloading:
            return False

        self._active_info = target
        self._last_download_result = None
        timeout = 60
        if self._settings and hasattr(self._settings, "get_network_timeout_sec"):
            timeout = max(30, self._settings.get_network_timeout_sec(15) * 4)

        self.download_started.emit()
        self.state_changed.emit()

        def _worker() -> None:
            res = self._service.download_and_verify(
                target,
                progress_callback=lambda rec, tot: self._sig_dl_progress.emit(rec, tot),
                timeout_sec=timeout,
            )
            self._sig_dl_done.emit(res)

        t = threading.Thread(target=_worker, name="rme-update-download", daemon=True)
        t.start()
        return True

    def _handle_download_done(self, result: DownloadResult) -> None:
        self._last_download_result = result
        self.download_finished.emit(result)
        self.state_changed.emit()

    def cancel_download(self) -> None:
        self._service.cancel_download()

    def dismiss_banner(self) -> None:
        if self._active_info is not None:
            self._banner_dismissed_version = self._active_info.latest_version

    def is_banner_dismissed_for(self, version: str) -> bool:
        return bool(version) and self._banner_dismissed_version == version

    def apply_downloaded_update(
        self,
        main_window: Any,
        launcher: Any = None,
    ) -> bool:
        """Выполнить 'Установить и перезапустить' после стандартной проверки несохраненного проекта."""
        dl = self._last_download_result
        info = self._active_info
        if dl is None or not dl.success or dl.file_path is None or info is None:
            return False

        if info.install_mode == INSTALL_MODE_PORTABLE:
            open_folder_selecting(dl.file_path)
            return True

        if info.install_mode != INSTALL_MODE_INSTALLED:
            QDesktopServices.openUrl(QUrl(info.html_url or RELEASES_HTML_URL))
            return True

        pc = getattr(main_window, "project_controller", None)
        if pc is not None and hasattr(pc, "maybe_save_prompt"):
            can_proceed = pc.maybe_save_prompt(tr("dialog.unsaved_action_exit"))
            if not can_proceed:
                return False

        try:
            launch_fn = launcher or launch_installer_and_relaunch
            launch_fn(
                installer_path=dl.file_path,
                relaunch_exe=Path(sys.executable).resolve(),
                current_pid=os.getpid(),
            )
        except Exception as e:
            QMessageBox.critical(
                main_window,
                tr("dialog.error_title"),
                tr("updates.install_failed", message=str(e)),
            )
            return False

        if main_window is not None:
            main_window.close()
        app = QApplication.instance()
        if app is not None:
            app.quit()
        return True


def open_folder_selecting(file_path: Path) -> None:
    """Открыть проводник Windows с выделением скачанного архива."""
    resolved = Path(file_path).resolve()
    if sys.platform == "win32" and resolved.exists():
        try:
            subprocess.Popen(["explorer.exe", f"/select,{resolved}"])
            return
        except Exception:
            pass
    QDesktopServices.openUrl(QUrl.fromLocalFile(str(resolved.parent)))


class UpdateNotificationBanner(QFrame):
    """Ненавязчивый верхний баннер о доступности, загрузке и готовности обновления."""

    def __init__(self, controller: UpdateController, main_window: Any, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("updateNotificationBanner")
        self._controller = controller
        self._main_window = main_window
        self._current_info: UpdateInfo | None = None

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 6, 12, 6)
        layout.setSpacing(8)

        self.message_label = QLabel("", self)
        self.message_label.setObjectName("updateBannerLabel")
        self.message_label.setWordWrap(False)
        layout.addWidget(self.message_label, 1)

        self.progress_bar = QProgressBar(self)
        self.progress_bar.setMaximumWidth(180)
        self.progress_bar.setFixedHeight(16)
        self.progress_bar.setVisible(False)
        layout.addWidget(self.progress_bar)

        self.btn_notes = QPushButton(tr("updates.btn_release_notes"), self)
        self.btn_notes.clicked.connect(self._show_notes)
        layout.addWidget(self.btn_notes)

        self.btn_primary = QPushButton(tr("updates.btn_update"), self)
        self.btn_primary.setObjectName("primaryAccentBtn")
        self.btn_primary.clicked.connect(self._on_primary_clicked)
        layout.addWidget(self.btn_primary)

        self.btn_cancel = QPushButton(tr("updates.btn_cancel"), self)
        self.btn_cancel.clicked.connect(self._controller.cancel_download)
        self.btn_cancel.setVisible(False)
        layout.addWidget(self.btn_cancel)

        self.btn_later = QPushButton(tr("updates.btn_later"), self)
        self.btn_later.clicked.connect(self._on_later)
        layout.addWidget(self.btn_later)

        self.setVisible(False)

        self._controller.check_finished.connect(self._on_check_finished)
        self._controller.download_started.connect(self._on_download_started)
        self._controller.download_progress.connect(self._on_download_progress)
        self._controller.download_finished.connect(self._on_download_finished)

    def retranslate_ui(self) -> None:
        self.btn_notes.setText(tr("updates.btn_release_notes"))
        self.btn_cancel.setText(tr("updates.btn_cancel"))
        self.btn_later.setText(tr("updates.btn_later"))
        if self._current_info is not None:
            self.show_update_available(self._current_info)

    def show_update_available(self, info: UpdateInfo) -> None:
        """Показать баннер о доступном обновлении (удобно и для тестов/скринов)."""
        self._current_info = info
        self.progress_bar.setVisible(False)
        self.btn_cancel.setVisible(False)
        self.btn_later.setVisible(True)
        self.btn_notes.setVisible(True)
        self.btn_primary.setVisible(True)

        dl = self._controller.last_download_result
        if dl is not None and dl.success and dl.file_path is not None:
            if info.install_mode == INSTALL_MODE_PORTABLE:
                self.message_label.setText(
                    tr("updates.ready_portable", version=info.latest_version, path=dl.file_path.name)
                )
                self.btn_primary.setText(tr("updates.btn_open_downloads"))
            else:
                self.message_label.setText(tr("updates.ready_installer", version=info.latest_version))
                self.btn_primary.setText(tr("updates.btn_install_restart"))
        elif info.install_mode == INSTALL_MODE_SOURCE:
            self.message_label.setText(
                tr("updates.available_source", latest=info.latest_version, current=info.current_version)
            )
            self.btn_primary.setText("GitHub Releases")
        else:
            size_text = format_size_human(info.expected_size)
            self.message_label.setText(
                tr(
                    "updates.available_banner",
                    latest=info.latest_version,
                    current=info.current_version,
                    size=size_text,
                )
            )
            self.btn_primary.setText(tr("updates.btn_update"))
        self.setVisible(True)

    def _on_check_finished(self, result: UpdateCheckResult, manual: bool) -> None:
        if result.status == "update_available" and result.info is not None:
            if manual or not self._controller.is_banner_dismissed_for(result.info.latest_version):
                self.show_update_available(result.info)

    def _on_download_started(self) -> None:
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setVisible(True)
        self.btn_primary.setVisible(False)
        self.btn_later.setVisible(False)
        self.btn_cancel.setVisible(True)
        self.message_label.setText(tr("updates.downloading", percent=0, received="0 B", total="..."))
        self.setVisible(True)

    def _on_download_progress(self, received: int, total: int) -> None:
        if total > 0:
            pct = max(0, min(100, int((received * 100) / total)))
            self.progress_bar.setRange(0, 100)
            self.progress_bar.setValue(pct)
            self.message_label.setText(
                tr(
                    "updates.downloading",
                    percent=pct,
                    received=format_size_human(received),
                    total=format_size_human(total),
                )
            )
        else:
            self.progress_bar.setRange(0, 0)
            self.message_label.setText(
                tr(
                    "updates.downloading",
                    percent=0,
                    received=format_size_human(received),
                    total="...",
                )
            )

    def _on_download_finished(self, result: DownloadResult) -> None:
        self.progress_bar.setVisible(False)
        self.btn_cancel.setVisible(False)
        self.btn_later.setVisible(True)
        self.btn_primary.setVisible(True)
        info = self._current_info or self._controller.active_info
        if result.success and info is not None:
            self.show_update_available(info)
            return
        if result.cancelled:
            self.message_label.setText(tr("updates.cancelled"))
            self.btn_primary.setText(tr("updates.btn_update"))
            return
        self.message_label.setText(tr("updates.error_prefix", message=result.error_message))
        self.btn_primary.setText(tr("updates.btn_retry"))

    def _show_notes(self) -> None:
        info = self._current_info or self._controller.active_info
        if info is not None:
            ReleaseNotesDialog(info, self._main_window).exec()

    def _on_primary_clicked(self) -> None:
        info = self._current_info or self._controller.active_info
        if info is None:
            return
        dl = self._controller.last_download_result
        if dl is not None and dl.success:
            self._controller.apply_downloaded_update(self._main_window)
            return
        if info.install_mode not in (INSTALL_MODE_INSTALLED, INSTALL_MODE_PORTABLE):
            QDesktopServices.openUrl(QUrl(info.html_url or RELEASES_HTML_URL))
            return
        self._controller.start_download(info)

    def _on_later(self) -> None:
        self._controller.dismiss_banner()
        self.setVisible(False)
