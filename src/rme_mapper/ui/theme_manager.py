"""Менеджер тем оформления приложения (ThemeManager).

Предоставляет единый стиль оформления, цветовую палитру и таблицы стилей (QSS)
для согласованного, современного и быстрого интерфейса на базе Qt.
Подготовлен для поддержки тем Light, Dark и System.
"""
from __future__ import annotations


import logging
from typing import Any

logger = logging.getLogger("rme_mapper.ui.theme")


# Цветовая палитра светлой темы
class LightPalette:
    BG_APP = "#F5F6F8"
    BG_PANEL = "#FFFFFF"
    BG_HOVER = "#F1F5F9"
    BG_ACTIVE = "#E2E8F0"
    BORDER = "#D9DDE3"
    BORDER_HOVER = "#94A3B8"
    BORDER_FOCUS = "#2563EB"
    TEXT_PRIMARY = "#202124"
    TEXT_SECONDARY = "#6B7280"
    TEXT_MUTED = "#9CA3AF"
    TEXT_DISABLED = "#A0AEC0"
    ACCENT = "#2563EB"
    ACCENT_HOVER = "#1D4ED8"
    ACCENT_PRESSED = "#1E40AF"
    ACCENT_LIGHT = "#EFF6FF"
    DANGER = "#DC2626"
    DANGER_HOVER = "#B91C1C"
    DANGER_LIGHT = "#FEF2F2"
    SELECTION_BG = "#E0EDFF"
    SELECTION_TEXT = "#1E3A8A"
    SPLITTER_HANDLE = "#D9DDE3"
    SPLITTER_HANDLE_HOVER = "#2563EB"
    CANVAS_BG = "#F8FAFC"
    GRIDLINE = "#F1F5F9"
    ACCENT_BORDER = "#BFDBFE"
    ACCENT_HOVER_BG = "#DBEAFE"
    SCROLLBAR_HANDLE = "#CBD5E1"
    SCROLLBAR_HOVER = "#94A3B8"
    HEADER_HIGHLIGHT_BG = "#E1F0FF"
    SECTION_TITLE = "#475569"
    STATUS_OK = "#15803D"
    STATUS_ERR = "#DC2626"
    STATUS_WARN = "#B45309"


def get_light_stylesheet(palette=None) -> str:
    """Генерация согласованного QSS для светлой темы оформления."""
    c = palette or LightPalette
    return f"""
    /* --- Основное окно и фоновые области --- */
    QMainWindow {{
        background-color: {c.BG_APP};
    }}
    QWidget#leftPanel, QWidget#centerPanel, QWidget#propertiesPanel {{
        background-color: {c.BG_PANEL};
    }}

    /* --- Сплиттер (QSplitter) --- */
    QSplitter::handle {{
        background-color: {c.SPLITTER_HANDLE};
    }}
    QSplitter::handle:horizontal {{
        width: 5px;
    }}
    QSplitter::handle:vertical {{
        height: 5px;
    }}
    QSplitter::handle:hover {{
        background-color: {c.SPLITTER_HANDLE_HOVER};
    }}

    /* --- Меню и полоса меню --- */
    QMenuBar {{
        background-color: {c.BG_PANEL};
        color: {c.TEXT_PRIMARY};
        border-bottom: 1px solid {c.BORDER};
        padding: 2px 4px;
    }}
    QMenuBar::item {{
        background: transparent;
        padding: 4px 8px;
        border-radius: 4px;
    }}
    QMenuBar::item:selected {{
        background-color: {c.BG_HOVER};
    }}
    QWidget#customTitleBar {{
        background-color: {c.BG_PANEL};
        border-bottom: 1px solid {c.BORDER};
    }}
    QMenuBar#titleBarMenuBar {{
        background: transparent;
        color: {c.TEXT_PRIMARY};
        border: none;
        padding: 0px 2px;
    }}
    QMenuBar#titleBarMenuBar::item {{
        background: transparent;
        padding: 4px 8px;
        margin: 2px 1px;
        border-radius: 4px;
    }}
    QMenuBar#titleBarMenuBar::item:selected {{
        background-color: {c.BG_HOVER};
    }}
    QMenuBar#titleBarMenuBar::item:pressed {{
        background-color: {c.BG_ACTIVE};
    }}
    QLabel#titleBarTitleLabel {{
        color: {c.TEXT_SECONDARY};
        font-size: 12px;
        font-weight: 500;
        background: transparent;
    }}
    QPushButton#btnTitleMinimize, QPushButton#btnTitleMaximize {{
        background: transparent;
        border: none;
        border-radius: 0px;
        padding: 0px;
    }}
    QPushButton#btnTitleMinimize:hover, QPushButton#btnTitleMaximize:hover {{
        background-color: {c.BG_HOVER};
    }}
    QPushButton#btnTitleMinimize:pressed, QPushButton#btnTitleMaximize:pressed {{
        background-color: {c.BG_ACTIVE};
    }}
    QPushButton#btnTitleClose {{
        background: transparent;
        border: none;
        border-radius: 0px;
        padding: 0px;
    }}
    QPushButton#btnTitleClose:hover {{
        background-color: #E81123;
    }}
    QPushButton#btnTitleClose:pressed {{
        background-color: #B80E1C;
    }}
    QMenu {{
        background-color: {c.BG_PANEL};
        color: {c.TEXT_PRIMARY};
        border: 1px solid {c.BORDER};
        border-radius: 4px;
        padding: 4px 0px;
    }}
    QMenu::item {{
        padding: 6px 24px 6px 20px;
    }}
    QMenu::item:selected {{
        background-color: {c.SELECTION_BG};
        color: {c.SELECTION_TEXT};
    }}
    QMenu::separator {{
        height: 1px;
        background: {c.BORDER};
        margin: 4px 8px;
    }}

    /* --- Панель инструментов (QToolBar) --- */
    QToolBar {{
        background-color: {c.BG_PANEL};
        border-bottom: 1px solid {c.BORDER};
        padding: 3px 6px;
        spacing: 4px;
    }}
    QToolBar QToolButton {{
        background-color: transparent;
        color: {c.TEXT_PRIMARY};
        border: 1px solid transparent;
        border-radius: 4px;
        padding: 4px 8px;
        font-size: 12px;
        font-weight: 500;
    }}
    QToolBar QToolButton:hover {{
        background-color: {c.BG_HOVER};
        border-color: {c.BORDER};
    }}
    QToolBar QToolButton:pressed {{
        background-color: {c.BG_ACTIVE};
    }}
    QToolBar QToolButton:disabled {{
        color: {c.TEXT_DISABLED};
    }}
    QToolBar::separator {{
        width: 1px;
        background-color: {c.BORDER};
        margin: 4px 6px;
    }}

    /* --- Строка состояния (QStatusBar) --- */
    QStatusBar {{
        background-color: {c.BG_PANEL};
        color: {c.TEXT_SECONDARY};
        border-top: 1px solid {c.BORDER};
        padding: 2px 8px;
        font-size: 12px;
    }}
    QStatusBar QLabel {{
        color: {c.TEXT_SECONDARY};
        padding: 0 4px;
    }}

    /* --- Кнопки (QPushButton) --- */
    QPushButton {{
        background-color: {c.BG_PANEL};
        color: {c.TEXT_PRIMARY};
        border: 1px solid {c.BORDER};
        border-radius: 4px;
        padding: 5px 12px;
        font-size: 12px;
        font-weight: 500;
        min-height: 18px;
    }}
    QPushButton:hover {{
        background-color: {c.BG_HOVER};
        border-color: {c.BORDER_HOVER};
    }}
    QPushButton:pressed {{
        background-color: {c.BG_ACTIVE};
    }}
    QPushButton:disabled {{
        background-color: {c.BG_APP};
        color: {c.TEXT_DISABLED};
        border-color: {c.BORDER};
    }}
    QPushButton:default {{
        background-color: {c.ACCENT};
        color: #FFFFFF;
        border-color: {c.ACCENT};
        font-weight: 600;
    }}
    QPushButton:default:hover {{ background-color: {c.ACCENT_HOVER}; }}

    QGroupBox {{
        color: {c.TEXT_PRIMARY};
        border: 1px solid {c.BORDER};
        border-radius: 6px;
        margin-top: 12px;
        padding: 10px;
        font-weight: 600;
    }}
    QGroupBox::title {{ subcontrol-origin: margin; left: 10px; padding: 0 4px; }}

    /* Акцентная кнопка добавления */
    QPushButton#btnAddPoint {{
        background-color: {c.ACCENT_LIGHT};
        border-color: {c.ACCENT_BORDER};
        color: {c.ACCENT};
    }}
    QPushButton#btnAddPoint:hover {{
        background-color: {c.ACCENT_HOVER_BG};
        border-color: {c.ACCENT};
    }}

    QPushButton#btnAddPoint, QPushButton#btnEditPoint, QPushButton#btnDeletePoint {{
        padding: 4px 6px;
        font-size: 11px;
    }}

    QPushButton#btnCreateGroup {{
        background-color: {c.ACCENT_LIGHT};
        border-color: {c.ACCENT_BORDER};
        color: {c.ACCENT};
        font-weight: 600;
        padding: 3px 8px;
    }}
    QPushButton#btnOpenProjectCanvas, QPushButton#btnImportPointsCanvas {{
        color: {c.TEXT_SECONDARY};
        border-color: transparent;
        padding: 4px 7px;
    }}
    QPushButton#btnOpenProjectCanvas:hover, QPushButton#btnImportPointsCanvas:hover {{
        color: {c.ACCENT};
        background-color: {c.ACCENT_LIGHT};
    }}

    /* Сдержанная кнопка удаления */
    QPushButton#btnDeletePoint:hover:!disabled {{
        background-color: {c.DANGER_LIGHT};
        border-color: {c.DANGER};
        color: {c.DANGER};
    }}

    /* --- Поле ввода (QLineEdit) --- */
    QLineEdit {{
        background-color: {c.BG_PANEL};
        color: {c.TEXT_PRIMARY};
        border: 1px solid {c.BORDER};
        border-radius: 4px;
        padding: 4px 8px;
        font-size: 12px;
        selection-background-color: {c.SELECTION_BG};
        selection-color: {c.SELECTION_TEXT};
    }}
    QLineEdit:focus {{
        border-color: {c.BORDER_FOCUS};
    }}

    QComboBox {{
        background: {c.BG_PANEL};
        border: 1px solid {c.BORDER};
        border-radius: 4px;
        padding: 4px 8px;
        min-height: 18px;
    }}
    QComboBox:hover, QComboBox:focus {{ border-color: {c.BORDER_FOCUS}; }}
    QComboBox::drop-down {{ border: none; width: 22px; }}

    /* --- Таблица (QTableWidget) --- */
    QTableWidget {{
        background-color: {c.BG_PANEL};
        color: {c.TEXT_PRIMARY};
        border: 1px solid {c.BORDER};
        border-radius: 4px;
        gridline-color: {c.GRIDLINE};
        selection-background-color: {c.SELECTION_BG};
        selection-color: {c.SELECTION_TEXT};
        font-size: 12px;
    }}
    QTableWidget::item {{
        padding: 4px 6px;
        border-bottom: 1px solid {c.GRIDLINE};
    }}
    QTableWidget::item:selected {{
        background-color: {c.SELECTION_BG};
        color: {c.SELECTION_TEXT};
    }}
    QHeaderView::section {{
        background-color: {c.BG_APP};
        color: {c.TEXT_SECONDARY};
        padding: 5px 6px;
        border: none;
        border-right: 1px solid {c.BORDER};
        border-bottom: 1px solid {c.BORDER};
        font-size: 11px;
        font-weight: 600;
    }}

    /* --- Холст карты --- */
    QGraphicsView#mapCanvas {{
        border: 1px solid {c.BORDER};
        border-radius: 4px;
        background-color: {c.CANVAS_BG};
    }}
    QWidget#measurementHUD {{
        background-color: {c.BG_PANEL};
        border: 1px solid {c.BORDER};
        border-radius: 6px;
    }}

    /* --- Чекбоксы --- */
    QCheckBox {{
        color: {c.TEXT_PRIMARY};
        spacing: 6px;
        font-size: 12px;
    }}

    /* --- Панель свойств --- */
    QFrame#propertiesPlaceholder {{
        border: 1px solid {c.BORDER};
        border-radius: 6px;
        background-color: {c.BG_PANEL};
    }}

    /* --- Диалоги и навигационные списки --- */
    QDialog {{
        background-color: {c.BG_APP};
    }}
    QDialog QLabel {{ color: {c.TEXT_PRIMARY}; }}
    QTabWidget::pane {{ border: 1px solid {c.BORDER}; border-radius: 6px; top: -1px; }}
    QTabBar::tab {{ background: {c.BG_APP}; color: {c.TEXT_SECONDARY}; padding: 7px 12px; margin-right: 2px; border: 1px solid transparent; border-top-left-radius: 5px; border-top-right-radius: 5px; }}
    QTabBar::tab:selected {{ background: {c.BG_PANEL}; color: {c.ACCENT}; border-color: {c.BORDER}; border-bottom-color: {c.BG_PANEL}; font-weight: 600; }}
    QMessageBox {{ background-color: {c.BG_PANEL}; }}
    QTreeWidget {{
        background-color: {c.BG_PANEL};
        color: {c.TEXT_PRIMARY};
        border: 1px solid {c.BORDER};
        border-radius: 6px;
        padding: 3px;
    }}
    QTreeWidget::item {{ padding: 5px 6px; border-radius: 4px; }}
    QTreeWidget::item:selected {{ background-color: {c.SELECTION_BG}; color: {c.SELECTION_TEXT}; }}
    QScrollBar:vertical {{ background: transparent; width: 10px; margin: 3px; }}
    QScrollBar::handle:vertical {{ background: {c.SCROLLBAR_HANDLE}; border-radius: 4px; min-height: 28px; }}
    QScrollBar::handle:vertical:hover {{ background: {c.SCROLLBAR_HOVER}; }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
    """


class ThemeManager:
    """Менеджер тем оформления приложения."""

    THEME_LIGHT = "light"
    THEME_DARK = "dark"
    THEME_SYSTEM = "system"

    def __init__(self) -> None:
        self._current_theme = self.THEME_LIGHT
        self._theme_target_ref = None
        self._color_scheme_slot = None
        self._cleanup_slot = None

    @property
    def current_theme(self) -> str:
        return self._current_theme

    def get_available_themes(self) -> list[str]:
        return [self.THEME_LIGHT, self.THEME_DARK, self.THEME_SYSTEM]

    def _resolve_theme_name(self, theme: str | None = None) -> str:
        t = (theme or self._current_theme).lower()
        if t == self.THEME_SYSTEM:
            from PySide6.QtGui import QGuiApplication
            from PySide6.QtCore import Qt
            return self.THEME_DARK if QGuiApplication.styleHints().colorScheme() == Qt.ColorScheme.Dark else self.THEME_LIGHT
        return self.THEME_DARK if t == self.THEME_DARK else self.THEME_LIGHT

    def is_dark_theme(self, theme: str | None = None) -> bool:
        """Возвращает True, если активна (или выбрана) тёмная тема."""
        return self._resolve_theme_name(theme) == self.THEME_DARK

    def get_palette(self, theme: str | None = None):
        """Возвращает класс палитры (LightPalette или DarkPalette) для текущей темы."""
        return DarkPalette if self.is_dark_theme(theme) else LightPalette

    def get_stylesheet(self, theme: str | None = None) -> str:
        palette = self.get_palette(theme)
        return get_light_stylesheet(palette) + get_shared_widget_stylesheet(palette)

    def apply_theme(self, target: Any, theme: str = THEME_LIGHT) -> None:
        """Применить выбранную тему оформления к приложению или окну."""
        import weakref
        self._current_theme = theme
        self._theme_target_ref = weakref.ref(target) if target is not None else None
        is_dark = self.is_dark_theme(theme)
        qss = self.get_stylesheet(theme)
        if hasattr(target, "setStyleSheet"):
            if target.styleSheet() != qss:
                target.setStyleSheet(qss)
            from PySide6.QtWidgets import QApplication
            from rme_mapper.ui.theme_style_filter import ThemeStyleFilter
            app = QApplication.instance()
            if app:
                if not hasattr(self, "_style_filter") or self._style_filter is None:
                    self._style_filter = ThemeStyleFilter(app)
                    app.installEventFilter(self._style_filter)

                    def _cleanup_theme_hooks(*_args):
                        try:
                            import shiboken6
                            style_filter = getattr(self, "_style_filter", None)
                            if style_filter is not None and shiboken6.isValid(app) and shiboken6.isValid(style_filter):
                                app.removeEventFilter(style_filter)
                            if self._color_scheme_slot is not None and shiboken6.isValid(app):
                                try:
                                    app.styleHints().colorSchemeChanged.disconnect(self._color_scheme_slot)
                                except (RuntimeError, TypeError):
                                    pass
                        except Exception:
                            pass
                        finally:
                            self._style_filter = None
                            self._color_scheme_slot = None

                    def _on_system_scheme_changed(*_args):
                        if self.current_theme != self.THEME_SYSTEM:
                            return
                        real_target = self._theme_target_ref() if self._theme_target_ref is not None else app
                        if real_target is not None:
                            self.apply_theme(real_target, self.THEME_SYSTEM)

                    self._color_scheme_slot = _on_system_scheme_changed
                    self._cleanup_slot = _cleanup_theme_hooks
                    app.styleHints().colorSchemeChanged.connect(self._color_scheme_slot)
                    app.aboutToQuit.connect(self._cleanup_slot)
                if getattr(self, "_style_filter", None) is not None:
                    self._style_filter.apply(is_dark)
            logger.info("Тема оформления '%s' успешно применена", theme)


_THEME_MANAGER_INSTANCE: ThemeManager | None = None


def get_theme_manager() -> ThemeManager:
    global _THEME_MANAGER_INSTANCE
    if _THEME_MANAGER_INSTANCE is None:
        _THEME_MANAGER_INSTANCE = ThemeManager()
    return _THEME_MANAGER_INSTANCE


class DarkPalette(LightPalette):
    BG_APP = "#111827"
    BG_PANEL = "#1F2937"
    BG_HOVER = "#293548"
    BG_ACTIVE = "#334155"
    BORDER = "#475569"
    TEXT_PRIMARY = "#F1F5F9"
    TEXT_SECONDARY = "#CBD5E1"
    TEXT_MUTED = "#94A3B8"
    TEXT_DISABLED = "#94A3B8"
    ACCENT = "#93C5FD"
    ACCENT_LIGHT = "#1E3A5F"
    SELECTION_BG = "#1E40AF"
    SELECTION_TEXT = "#FFFFFF"
    DANGER_LIGHT = "#450A0A"
    DANGER = "#FCA5A5"
    SPLITTER_HANDLE = "#475569"
    CANVAS_BG = "#0F172A"
    GRIDLINE = "#334155"
    ACCENT_BORDER = "#1D4ED8"
    ACCENT_HOVER_BG = "#1E40AF"
    SCROLLBAR_HANDLE = "#475569"
    SCROLLBAR_HOVER = "#64748B"
    HEADER_HIGHLIGHT_BG = "#1E3A5F"
    SECTION_TITLE = "#CBD5E1"
    STATUS_OK = "#4ADE80"
    STATUS_ERR = "#FCA5A5"
    STATUS_WARN = "#FCD34D"


def get_shared_widget_stylesheet(c):
    return f"""
    QWidget {{ color: {c.TEXT_PRIMARY}; }}
    QDialog, QWizard, QTabWidget::pane {{ background: {c.BG_APP}; }}
    QTabWidget::pane {{ border: 1px solid {c.BORDER}; border-radius: 6px; }}
    QTabBar::tab {{ background: {c.BG_PANEL}; padding: 8px 14px; border-bottom: 2px solid transparent; }}
    QTabBar::tab:selected {{ background: {c.BG_HOVER}; border-bottom-color: {c.ACCENT}; }}
    QPlainTextEdit, QTextEdit, QSpinBox, QDoubleSpinBox, QTreeWidget, QListWidget {{
        background: {c.BG_PANEL}; color: {c.TEXT_PRIMARY}; border: 1px solid {c.BORDER}; border-radius: 4px;
    }}
    QGroupBox {{ border: 1px solid {c.BORDER}; border-radius: 6px; margin-top: 10px; padding: 12px; }}
    QGroupBox::title {{ subcontrol-origin: margin; left: 10px; }}
    QToolTip {{ background: {c.BG_PANEL}; color: {c.TEXT_PRIMARY}; border: 1px solid {c.BORDER}; }}
    QScrollArea {{ background: {c.BG_APP}; }}
    QComboBox QAbstractItemView {{ background: {c.BG_PANEL}; color: {c.TEXT_PRIMARY}; selection-background-color: {c.SELECTION_BG}; }}
    """
