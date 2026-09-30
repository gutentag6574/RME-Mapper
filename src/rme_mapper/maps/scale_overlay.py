"""Экранный оверлей масштабной линейки (ScaleOverlayWidget) в левом верхнем углу холста карты."""
from __future__ import annotations


import logging
from typing import Any

from PySide6.QtCore import QPointF, QRectF, QSize, Qt
from PySide6.QtGui import QBrush, QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import QWidget

logger = logging.getLogger("rme_mapper.maps.scale_overlay")


class ScaleOverlayWidget(QWidget):
    """Компактный экранный виджет масштаба в левом верхнем углу холста карты."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("scaleOverlayWidget")
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

        self._label_text: str = ""
        self._bar_width_px: float = 100.0
        self._distance_m: float = 0.0
        self._is_map_loaded: bool = False
        self._indicator_visible: bool = True

        self.hide()

    @property
    def distance_m(self) -> float:
        """Текущее геодезическое расстояние линейки в метрах."""
        return self._distance_m

    def text(self) -> str:
        """Текст подписи масштаба."""
        return self._label_text

    def set_map_loaded(self, loaded: bool) -> None:
        """Обновление флага наличия загруженной карты."""
        self._is_map_loaded = loaded
        self._update_visibility()

    def set_indicator_visible(self, visible: bool) -> None:
        """Переключение видимости пользователем (через меню Вид)."""
        self._indicator_visible = visible
        self._update_visibility()

    def is_indicator_visible(self) -> bool:
        """Проверка флага видимости индикатора."""
        return self._indicator_visible

    def _update_visibility(self) -> None:
        """Синхронизация видимости виджета."""
        if self._is_map_loaded and self._indicator_visible and bool(self._label_text):
            self.show()
        else:
            self.hide()

    def update_scale(self, label_text: str, bar_width_px: float, distance_m: float = 0.0) -> None:
        """Обновление параметров масштаба и перерисовка."""
        self._label_text = label_text
        self._bar_width_px = max(50.0, min(bar_width_px, 250.0))
        self._distance_m = distance_m
        self._update_geometry()
        self._update_visibility()
        self.update()

    def _update_geometry(self) -> None:
        """Расчет размеров карточки масштаба."""
        font = QFont("Segoe UI", 9, QFont.Weight.Bold)
        fm = self.fontMetrics()
        text_w = float(fm.horizontalAdvance(self._label_text))
        text_h = float(fm.height())

        pad_x = 10.0
        pad_y = 6.0
        bar_h = 5.0
        gap = 3.0

        card_w = max(self._bar_width_px, text_w) + pad_x * 2.0
        card_h = text_h + bar_h + gap + pad_y * 2.0

        self.resize(int(card_w), int(card_h))

    def sizeHint(self) -> QSize:
        return QSize(self.width(), self.height())

    def paintEvent(self, event: Any) -> None:
        if not self._label_text or not self._is_map_loaded:
            return

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        w = float(self.width())
        h = float(self.height())
        rect = QRectF(0.5, 0.5, w - 1.0, h - 1.0)

        # 1. Фон карточки
        bg_brush = QBrush(QColor(255, 255, 255, 225))
        border_pen = QPen(QColor("#CBD5E1"), 1.0)
        painter.setBrush(bg_brush)
        painter.setPen(border_pen)
        painter.drawRoundedRect(rect, 4.0, 4.0)

        # 2. Текст масштаба
        font = QFont("Segoe UI", 9, QFont.Weight.Bold)
        painter.setFont(font)
        fm = painter.fontMetrics()
        text_h = float(fm.height())

        text_rect = QRectF(0, 5.0, w, text_h)
        painter.setPen(QPen(QColor("#0F172A")))
        painter.drawText(text_rect, Qt.AlignmentFlag.AlignCenter, self._label_text)

        # 3. Сегментированная масштабная линейка
        bar_w = self._bar_width_px
        bar_h = 4.0
        bar_x = (w - bar_w) / 2.0
        bar_y = 5.0 + text_h + 3.0
        half_w = bar_w / 2.0

        # Левый сегмент (черный)
        painter.setPen(QPen(QColor("#0F172A"), 1.0))
        painter.setBrush(QBrush(QColor("#0F172A")))
        painter.drawRect(QRectF(bar_x, bar_y, half_w, bar_h))

        # Правый сегмент (белый)
        painter.setBrush(QBrush(QColor("#FFFFFF")))
        painter.drawRect(QRectF(bar_x + half_w, bar_y, half_w, bar_h))

        # Засечки по краям и в центре
        tick_h = bar_h + 3.0
        tick_y = bar_y - 1.5
        painter.drawLine(QPointF(bar_x, tick_y), QPointF(bar_x, tick_y + tick_h))
        painter.drawLine(QPointF(bar_x + half_w, tick_y), QPointF(bar_x + half_w, tick_y + tick_h))
        painter.drawLine(QPointF(bar_x + bar_w, tick_y), QPointF(bar_x + bar_w, tick_y + tick_h))
