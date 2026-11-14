"""Кастомная верхняя панель (в стиле VS Code / Antigravity) и поддержка нативной безрамочности на Windows."""
from __future__ import annotations

import ctypes
from ctypes import wintypes
import logging
import re
import sys
from pathlib import Path
from typing import Any

from PySide6.QtCore import QEvent, QPoint, QRect, QSize, Qt
from PySide6.QtGui import QColor, QCursor, QGuiApplication, QIcon, QPainter, QPalette, QPen, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QMenuBar,
    QPushButton,
    QSizePolicy,
    QWidget,
)

from rme_mapper.i18n import tr

logger = logging.getLogger("rme_mapper.ui.custom_title_bar")

_WM_NCCALCSIZE = 0x0083
_WM_NCHITTEST = 0x0084

_HTCLIENT = 1
_HTCAPTION = 2
_HTLEFT = 10
_HTRIGHT = 11
_HTTOP = 12
_HTTOPLEFT = 13
_HTTOPRIGHT = 14
_HTBOTTOM = 15
_HTBOTTOMLEFT = 16
_HTBOTTOMRIGHT = 17

_SWP_NOSIZE = 0x0001
_SWP_NOMOVE = 0x0002
_SWP_NOZORDER = 0x0004
_SWP_NOACTIVATE = 0x0010
_SWP_FRAMECHANGED = 0x0020

_SM_CXSIZEFRAME = 32
_SM_CXPADDEDBORDER = 92
_DWMWA_WINDOW_CORNER_PREFERENCE = 33
_DWMWCP_ROUND = 2


class _RECT(ctypes.Structure):
    _fields_ = [
        ("left", ctypes.c_long),
        ("top", ctypes.c_long),
        ("right", ctypes.c_long),
        ("bottom", ctypes.c_long),
    ]


class _NCCALCSIZE_PARAMS(ctypes.Structure):
    _fields_ = [("rgrc", _RECT * 3), ("lppos", ctypes.c_void_p)]


class _MARGINS(ctypes.Structure):
    _fields_ = [
        ("cxLeftWidth", ctypes.c_int),
        ("cxRightWidth", ctypes.c_int),
        ("cyTopHeight", ctypes.c_int),
        ("cyBottomHeight", ctypes.c_int),
    ]


def _render_caption_icon(kind: str, color_hex: str, size: int = 12) -> QIcon:
    """Отрисовка четкой векторной иконки управления окном (2x для HiDPI)."""
    scale = 2
    px = QPixmap(size * scale, size * scale)
    px.fill(Qt.GlobalColor.transparent)
    px.setDevicePixelRatio(float(scale))

    painter = QPainter(px)
    pen = QPen(QColor(color_hex), 1.2)
    pen.setCapStyle(Qt.PenCapStyle.FlatCap)
    pen.setJoinStyle(Qt.PenJoinStyle.MiterJoin)
    painter.setPen(pen)

    if kind == "minimize":
        y = size / 2.0
        painter.drawLine(1, int(round(y)), size - 2, int(round(y)))
    elif kind == "maximize":
        painter.drawRect(2, 2, size - 5, size - 5)
    elif kind == "restore":
        painter.drawRect(2, 4, size - 7, size - 7)
        painter.drawLine(4, 2, size - 3, 2)
        painter.drawLine(size - 3, 2, size - 3, size - 5)
    elif kind == "close":
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        painter.drawLine(2, 2, size - 3, size - 3)
        painter.drawLine(size - 3, 2, 2, size - 3)

    painter.end()
    return QIcon(px)


def _extract_native_msg_address(message: Any) -> int:
    """Извлечение адреса структуры MSG из VoidPtr (совместимо с PySide6 6.12 и более ранними)."""
    try:
        return int(message)
    except (TypeError, NotImplementedError):
        match = re.search(r"0x[0-9a-fA-F]+", repr(message))
        return int(match.group(0), 16) if match else 0


class Win32FramelessHelper:
    """Обработчик нативных сообщений Windows для безрамочного окна с Aero Snap и ресайзом."""

    def __init__(self) -> None:
        self._frame_applied = False
        self._user32 = ctypes.windll.user32 if sys.platform == "win32" else None
        self._dwmapi = ctypes.windll.dwmapi if sys.platform == "win32" else None

    @staticmethod
    def is_supported() -> bool:
        return (
            sys.platform == "win32"
            and QGuiApplication.platformName().lower() == "windows"
        )

    def ensure_native_frame(self, window: QWidget) -> None:
        """Применение нативной тени DWM и пересчет клиентской области (однократно при показе)."""
        if self._frame_applied or not self.is_supported():
            return
        try:
            hwnd = int(window.winId())
            if not hwnd:
                return
            margins = _MARGINS(0, 0, 1, 0)
            self._dwmapi.DwmExtendFrameIntoClientArea(hwnd, ctypes.byref(margins))
            try:
                corner = ctypes.c_int(_DWMWCP_ROUND)
                self._dwmapi.DwmSetWindowAttribute(
                    hwnd,
                    _DWMWA_WINDOW_CORNER_PREFERENCE,
                    ctypes.byref(corner),
                    ctypes.sizeof(corner),
                )
            except Exception:
                pass
            flags = _SWP_NOMOVE | _SWP_NOSIZE | _SWP_NOZORDER | _SWP_NOACTIVATE | _SWP_FRAMECHANGED
            self._user32.SetWindowPos(hwnd, 0, 0, 0, 0, 0, flags)
            self._frame_applied = True
        except Exception as exc:
            logger.debug("Не удалось настроить нативный DWM frame: %s", exc)

    def handle_native_event(
        self,
        window: QWidget,
        event_type: Any,
        message: Any,
        title_bar: CustomTitleBar,
    ) -> tuple[bool, int] | None:
        """Обработка WM_NCCALCSIZE и WM_NCHITTEST; возвращает None, если событие не обработано."""
        if not self.is_supported() or self._user32 is None:
            return None
        if bytes(event_type) != b"windows_generic_MSG":
            return None

        addr = _extract_native_msg_address(message)
        if not addr:
            return None

        msg = wintypes.MSG.from_address(addr)

        if msg.message == _WM_NCCALCSIZE and msg.wParam:
            params = _NCCALCSIZE_PARAMS.from_address(msg.lParam)
            dpi = self._user32.GetDpiForWindow(msg.hWnd) or 96
            border = self._user32.GetSystemMetricsForDpi(
                _SM_CXSIZEFRAME, dpi
            ) + self._user32.GetSystemMetricsForDpi(_SM_CXPADDEDBORDER, dpi)
            params.rgrc[0].left += border
            params.rgrc[0].right -= border
            params.rgrc[0].bottom -= border
            if self._user32.IsZoomed(msg.hWnd):
                params.rgrc[0].top += border
            return True, 0

        if msg.message == _WM_NCHITTEST:
            rect = _RECT()
            if not self._user32.GetWindowRect(msg.hWnd, ctypes.byref(rect)):
                return None

            x_phys = ctypes.c_int16(msg.lParam & 0xFFFF).value
            y_phys = ctypes.c_int16((msg.lParam >> 16) & 0xFFFF).value

            is_zoomed = bool(self._user32.IsZoomed(msg.hWnd))
            global_pos = QCursor.pos()

            if not is_zoomed:
                dpr = max(1.0, float(window.devicePixelRatioF()))
                bw = max(6, int(round(6 * dpr)))
                bw_top = max(4, int(round(4 * dpr)))

                on_left = rect.left <= x_phys < rect.left + bw
                on_right = rect.right - bw <= x_phys < rect.right
                on_top = rect.top <= y_phys < rect.top + bw_top
                on_bottom = rect.bottom - bw <= y_phys < rect.bottom

                if on_top and on_left:
                    return True, _HTTOPLEFT
                if on_top and on_right:
                    return True, _HTTOPRIGHT
                if on_bottom and on_left:
                    return True, _HTBOTTOMLEFT
                if on_bottom and on_right:
                    return True, _HTBOTTOMRIGHT
                if on_left:
                    return True, _HTLEFT
                if on_right:
                    return True, _HTRIGHT
                if on_top:
                    return True, _HTTOP
                if on_bottom:
                    return True, _HTBOTTOM

            local_title = title_bar.mapFromGlobal(global_pos)
            if title_bar.rect().contains(local_title):
                if title_bar.is_interactive_at(global_pos):
                    return True, _HTCLIENT
                return True, _HTCAPTION

        return None


class CustomTitleBar(QWidget):
    """Единая верхняя панель с иконкой, меню, заголовком проекта и кнопками окна."""

    TITLE_BAR_HEIGHT = 34

    def __init__(self, parent_window: QWidget) -> None:
        super().__init__(parent_window)
        self._window = parent_window
        self._is_maximized = False
        self._close_hovered = False
        self._icon_color = "#1E293B"

        self.setObjectName("customTitleBar")
        self.setFixedHeight(self.TITLE_BAR_HEIGHT)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 0, 0, 0)
        layout.setSpacing(6)

        self.icon_label = QLabel(self)
        self.icon_label.setFixedSize(18, 18)
        self.icon_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self._load_app_icon()
        layout.addWidget(self.icon_label)

        self.menu_bar = QMenuBar(self)
        self.menu_bar.setObjectName("titleBarMenuBar")
        self.menu_bar.setNativeMenuBar(False)
        self.menu_bar.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Expanding)
        layout.addWidget(self.menu_bar)

        layout.addStretch(1)

        self.title_label = QLabel(self)
        self.title_label.setObjectName("titleBarTitleLabel")
        self.title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.title_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.title_label.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)
        self.title_label.setMinimumWidth(80)
        layout.addWidget(self.title_label)

        layout.addStretch(1)

        btn_size = QSize(44, self.TITLE_BAR_HEIGHT)
        icon_size = QSize(12, 12)

        self.btn_minimize = QPushButton(self)
        self.btn_minimize.setObjectName("btnTitleMinimize")
        self.btn_minimize.setFixedSize(btn_size)
        self.btn_minimize.setIconSize(icon_size)
        self.btn_minimize.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.btn_minimize.clicked.connect(self._on_minimize_clicked)
        layout.addWidget(self.btn_minimize)

        self.btn_maximize = QPushButton(self)
        self.btn_maximize.setObjectName("btnTitleMaximize")
        self.btn_maximize.setFixedSize(btn_size)
        self.btn_maximize.setIconSize(icon_size)
        self.btn_maximize.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.btn_maximize.clicked.connect(self._on_maximize_clicked)
        layout.addWidget(self.btn_maximize)

        self.btn_close = QPushButton(self)
        self.btn_close.setObjectName("btnTitleClose")
        self.btn_close.setFixedSize(btn_size)
        self.btn_close.setIconSize(icon_size)
        self.btn_close.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.btn_close.installEventFilter(self)
        self.btn_close.clicked.connect(self._on_close_clicked)
        layout.addWidget(self.btn_close)

        self._refresh_icons()
        self.retranslate_ui()

    def _load_app_icon(self) -> None:
        res_dir = Path(__file__).resolve().parent.parent / "resources"
        for name in ("icon.png", "icon.ico"):
            candidate = res_dir / name
            if candidate.exists():
                pix = QIcon(str(candidate)).pixmap(QSize(18, 18))
                if not pix.isNull():
                    self.icon_label.setPixmap(pix)
                    return

    def _on_minimize_clicked(self) -> None:
        self._window.showMinimized()

    def _on_maximize_clicked(self) -> None:
        if self._window.isMaximized():
            self._window.showNormal()
        else:
            self._window.showMaximized()

    def _on_close_clicked(self) -> None:
        self._window.close()

    def set_title(self, title: str) -> None:
        self.title_label.setText(title)

    def set_maximized(self, maximized: bool) -> None:
        self._is_maximized = bool(maximized)
        self._refresh_icons()
        self.retranslate_ui()

    def update_theme(self, is_dark: bool | None = None) -> None:
        if is_dark is None:
            try:
                from rme_mapper.ui.theme_manager import get_theme_manager
                is_dark = get_theme_manager().is_dark_theme()
            except Exception:
                win_color = self.palette().color(QPalette.ColorRole.Window)
                is_dark = win_color.lightness() < 128
        self._icon_color = "#F1F5F9" if is_dark else "#1E293B"
        self._refresh_icons()

    def _refresh_icons(self) -> None:
        self.btn_minimize.setIcon(_render_caption_icon("minimize", self._icon_color))
        max_kind = "restore" if self._is_maximized else "maximize"
        self.btn_maximize.setIcon(_render_caption_icon(max_kind, self._icon_color))
        close_color = "#FFFFFF" if self._close_hovered else self._icon_color
        self.btn_close.setIcon(_render_caption_icon("close", close_color))

    def retranslate_ui(self) -> None:
        self.btn_minimize.setToolTip(tr("window.minimize"))
        self.btn_maximize.setToolTip(
            tr("window.restore") if self._is_maximized else tr("window.maximize")
        )
        self.btn_close.setToolTip(tr("window.close"))

    def is_interactive_at(self, global_pos: QPoint) -> bool:
        """Возвращает True, если курсор находится над кнопками окна, пунктом меню или открытым меню."""
        if QApplication.activePopupWidget() is not None:
            return True

        for btn in (self.btn_minimize, self.btn_maximize, self.btn_close):
            if btn.rect().contains(btn.mapFromGlobal(global_pos)):
                return True

        menu_pos = self.menu_bar.mapFromGlobal(global_pos)
        if self.menu_bar.rect().contains(menu_pos):
            return self.menu_bar.actionAt(menu_pos) is not None

        return False

    def eventFilter(self, watched: Any, event: Any) -> bool:
        if watched is self.btn_close:
            etype = event.type()
            if etype == QEvent.Type.Enter:
                self._close_hovered = True
                self.btn_close.setIcon(_render_caption_icon("close", "#FFFFFF"))
            elif etype == QEvent.Type.Leave:
                self._close_hovered = False
                self.btn_close.setIcon(_render_caption_icon("close", self._icon_color))
        return super().eventFilter(watched, event)

    def changeEvent(self, event: Any) -> None:
        if event.type() in (QEvent.Type.PaletteChange, QEvent.Type.StyleChange):
            self.update_theme()
        super().changeEvent(event)

    def mousePressEvent(self, event: Any) -> None:
        # Fallback для не-Windows платформ / систем без WM_NCHITTEST
        if event.button() == Qt.MouseButton.LeftButton:
            gpos = event.globalPosition().toPoint() if hasattr(event, "globalPosition") else event.globalPos()
            if not self.is_interactive_at(gpos):
                handle = self._window.windowHandle()
                if handle is not None and hasattr(handle, "startSystemMove"):
                    if handle.startSystemMove():
                        event.accept()
                        return
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event: Any) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            gpos = event.globalPosition().toPoint() if hasattr(event, "globalPosition") else event.globalPos()
            if not self.is_interactive_at(gpos):
                self._on_maximize_clicked()
                event.accept()
                return
        super().mouseDoubleClickEvent(event)
