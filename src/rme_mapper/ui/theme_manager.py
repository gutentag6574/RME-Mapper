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


def get_light_stylesheet() -> str:
    """Генерация согласованного QSS для светлой темы оформления."""
    c = LightPalette
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
        border-color: #BFDBFE;
        color: {c.ACCENT};
    }}
    QPushButton#btnAddPoint:hover {{
        background-color: #DBEAFE;
        border-color: {c.ACCENT};
    }}

    QPushButton#btnAddPoint, QPushButton#btnEditPoint, QPushButton#btnDeletePoint {{
        padding: 4px 6px;
        font-size: 11px;
    }}

    QPushButton#btnCreateGroup {{
        background-color: {c.ACCENT_LIGHT};
        border-color: #BFDBFE;
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
        gridline-color: #F1F5F9;
        selection-background-color: {c.SELECTION_BG};
        selection-color: {c.SELECTION_TEXT};
        font-size: 12px;
    }}
    QTableWidget::item {{
        padding: 4px 6px;
        border-bottom: 1px solid #F1F5F9;
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
        background-color: #F8FAFC;
    }}

    /* --- Чекбоксы --- */
    QCheckBox {{
        color: {c.TEXT_PRIMARY};
        spacing: 6px;
        font-size: 12px;
    }}
    QCheckBox::indicator {{
        width: 16px;
        height: 16px;
        border: 1px solid {c.BORDER};
        border-radius: 3px;
        background-color: {c.BG_PANEL};
    }}
    QCheckBox::indicator:hover {{
        border-color: {c.BORDER_FOCUS};
    }}
    QCheckBox::indicator:checked {{
        background-color: {c.ACCENT};
        border-color: {c.ACCENT};
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
        border: 1px solid {c.BORDER};
        border-radius: 6px;
        padding: 3px;
    }}
    QTreeWidget::item {{ padding: 5px 6px; border-radius: 4px; }}
    QTreeWidget::item:selected {{ background-color: {c.SELECTION_BG}; color: {c.SELECTION_TEXT}; }}
    QScrollBar:vertical {{ background: transparent; width: 10px; margin: 3px; }}
    QScrollBar::handle:vertical {{ background: #CBD5E1; border-radius: 4px; min-height: 28px; }}
    QScrollBar::handle:vertical:hover {{ background: #94A3B8; }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
    """


class ThemeManager:
    """Менеджер тем оформления приложения."""

    THEME_LIGHT = "light"
    THEME_DARK = "dark"
    THEME_SYSTEM = "system"

    def __init__(self) -> None:
        self._current_theme = self.THEME_LIGHT

    @property
    def current_theme(self) -> str:
        return self._current_theme

    def get_available_themes(self) -> list[str]:
        return [self.THEME_LIGHT, self.THEME_DARK, self.THEME_SYSTEM]

    def get_stylesheet(self, theme: str | None = None) -> str:
        t = (theme or self._current_theme).lower()
        if t == self.THEME_LIGHT or t == self.THEME_SYSTEM:
            return get_light_stylesheet()
        # Для незавершенных тем отдаем аккуратную light тему
        return get_light_stylesheet()

    def apply_theme(self, target: Any, theme: str = THEME_LIGHT) -> None:
        """Применить выбранную тему оформления к приложению или окну."""
        self._current_theme = theme
        qss = self.get_stylesheet(theme)
        if hasattr(target, "setStyleSheet"):
            target.setStyleSheet(qss)
            logger.info("Тема оформления '%s' успешно применена", theme)


_THEME_MANAGER_INSTANCE: ThemeManager | None = None


def get_theme_manager() -> ThemeManager:
    global _THEME_MANAGER_INSTANCE
    if _THEME_MANAGER_INSTANCE is None:
        _THEME_MANAGER_INSTANCE = ThemeManager()
    return _THEME_MANAGER_INSTANCE
