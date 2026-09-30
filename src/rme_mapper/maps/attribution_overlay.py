"""Экранный оверлей копирайта / атрибуции онлайн-провайдера карты (AttributionOverlayWidget)."""
from __future__ import annotations


import logging
from typing import Any

from PySide6.QtCore import QSize, Qt
from PySide6.QtWidgets import QHBoxLayout, QLabel, QWidget

logger = logging.getLogger("rme_mapper.maps.attribution_overlay")


class AttributionOverlayWidget(QWidget):
    """Компактный экранный виджет атрибуции картографического провайдера в правом нижнем углу холста."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("attributionOverlayWidget")

        self._attribution_text: str = ""
        self._is_map_active: bool = False

        self._layout = QHBoxLayout(self)
        self._layout.setContentsMargins(6, 2, 6, 2)
        self._layout.setSpacing(0)

        self._label = QLabel(self)
        self._label.setObjectName("attributionLabel")
        self._label.setTextFormat(Qt.TextFormat.RichText)
        self._label.setOpenExternalLinks(True)
        self._label.setTextInteractionFlags(
            Qt.TextInteractionFlag.LinksAccessibleByMouse | Qt.TextInteractionFlag.TextSelectableByMouse
        )
        self._layout.addWidget(self._label)

        self.setStyleSheet(
            """
            QWidget#attributionOverlayWidget {
                background-color: rgba(255, 255, 255, 0.82);
                border: 1px solid rgba(15, 23, 42, 0.15);
                border-radius: 3px;
            }
            QLabel#attributionLabel {
                font-family: 'Segoe UI', sans-serif;
                font-size: 10px;
                color: #334155;
            }
            QLabel#attributionLabel a {
                color: #0284C7;
                text-decoration: none;
            }
            QLabel#attributionLabel a:hover {
                text-decoration: underline;
            }
            """
        )

        self.hide()

    def text(self) -> str:
        """Текущий текст атрибуции."""
        return self._attribution_text

    def set_attribution(self, text: str) -> None:
        """Установка текста атрибуции провайдера."""
        self._attribution_text = (text or "").strip()
        self._label.setText(self._attribution_text)
        self.adjustSize()
        self._update_visibility()

    def set_map_active(self, active: bool) -> None:
        """Флаг активности онлайн-карты."""
        self._is_map_active = active
        self._update_visibility()

    def is_map_active(self) -> bool:
        """Проверка активности онлайн-карты."""
        return self._is_map_active

    def _update_visibility(self) -> None:
        """Синхронизация видимости виджета."""
        if self._is_map_active and bool(self._attribution_text):
            self.show()
            self.raise_()
        else:
            self.hide()

    def sizeHint(self) -> QSize:
        return self._layout.sizeHint()
