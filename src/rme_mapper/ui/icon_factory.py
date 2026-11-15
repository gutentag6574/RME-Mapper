"""Фабрика единых векторных иконок панели инструментов (HiDPI 2x, с учётом темы)."""
from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPen, QPixmap


def render_toolbar_icon(kind: str, color_hex: str, accent_hex: str = "#2563EB", size: int = 18) -> QIcon:
    """Нарисовать чёткую векторную иконку в едином стиле."""
    scale = 2
    px = QPixmap(size * scale, size * scale)
    px.fill(Qt.GlobalColor.transparent)
    px.setDevicePixelRatio(float(scale))

    p = QPainter(px)
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    fg = QColor(color_hex)
    accent = QColor(accent_hex)
    pen = QPen(fg, 1.5, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
    p.setPen(pen)

    if kind == "open_map":
        # Сложенная карта
        p.drawPolygon([
            QPointF(2.5, 4.5), QPointF(7.0, 2.8), QPointF(11.0, 4.5), QPointF(15.5, 2.8),
            QPointF(15.5, 13.5), QPointF(11.0, 15.2), QPointF(7.0, 13.5), QPointF(2.5, 15.2),
        ])
        p.drawLine(QPointF(7.0, 2.8), QPointF(7.0, 13.5))
        p.drawLine(QPointF(11.0, 4.5), QPointF(11.0, 15.2))
    elif kind == "open_project":
        p.drawPolygon([
            QPointF(2.5, 4.0), QPointF(7.0, 4.0), QPointF(8.6, 5.8),
            QPointF(15.5, 5.8), QPointF(15.5, 14.5), QPointF(2.5, 14.5),
        ])
    elif kind == "save":
        p.drawRoundedRect(QRectF(3.0, 3.0, 12.0, 12.0), 1.5, 1.5)
        p.drawRect(QRectF(5.5, 3.0, 7.0, 4.2))
        p.drawRect(QRectF(5.5, 10.0, 7.0, 5.0))
    elif kind == "undo":
        p.drawArc(QRectF(4.0, 6.0, 10.0, 8.0), 0, 180 * 16)
        p.drawLine(QPointF(4.0, 10.0), QPointF(4.0, 5.5))
        p.drawLine(QPointF(4.0, 10.0), QPointF(7.5, 8.0))
        p.drawLine(QPointF(4.0, 10.0), QPointF(1.5, 7.5))
    elif kind == "redo":
        p.drawArc(QRectF(4.0, 6.0, 10.0, 8.0), 0, 180 * 16)
        p.drawLine(QPointF(14.0, 10.0), QPointF(14.0, 5.5))
        p.drawLine(QPointF(14.0, 10.0), QPointF(10.5, 8.0))
        p.drawLine(QPointF(14.0, 10.0), QPointF(16.5, 7.5))
    elif kind == "add_point":
        p.setPen(QPen(accent, 1.7, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
        p.drawEllipse(QPointF(9.0, 7.2), 3.6, 3.6)
        p.drawLine(QPointF(9.0, 10.8), QPointF(9.0, 15.5))
        p.drawLine(QPointF(9.0, 5.4), QPointF(9.0, 9.0))
        p.drawLine(QPointF(7.2, 7.2), QPointF(10.8, 7.2))
    elif kind == "fit_map":
        p.drawLine(QPointF(3.0, 6.5), QPointF(3.0, 3.0))
        p.drawLine(QPointF(3.0, 3.0), QPointF(6.5, 3.0))
        p.drawLine(QPointF(11.5, 3.0), QPointF(15.0, 3.0))
        p.drawLine(QPointF(15.0, 3.0), QPointF(15.0, 6.5))
        p.drawLine(QPointF(3.0, 11.5), QPointF(3.0, 15.0))
        p.drawLine(QPointF(3.0, 15.0), QPointF(6.5, 15.0))
        p.drawLine(QPointF(11.5, 15.0), QPointF(15.0, 15.0))
        p.drawLine(QPointF(15.0, 15.0), QPointF(15.0, 11.5))
    elif kind == "measure_distance":
        p.drawLine(QPointF(3.0, 14.5), QPointF(15.0, 3.5))
        p.drawEllipse(QPointF(3.2, 14.3), 1.6, 1.6)
        p.drawEllipse(QPointF(14.8, 3.7), 1.6, 1.6)
        p.drawLine(QPointF(7.0, 10.8), QPointF(8.4, 12.2))
        p.drawLine(QPointF(10.5, 7.6), QPointF(11.9, 9.0))
    elif kind == "measure_area":
        p.drawPolygon([QPointF(3.5, 13.5), QPointF(5.5, 4.0), QPointF(14.5, 5.5), QPointF(13.0, 14.5)])
    elif kind == "export":
        p.drawRoundedRect(QRectF(3.0, 8.5, 12.0, 6.5), 1.5, 1.5)
        p.drawLine(QPointF(9.0, 11.5), QPointF(9.0, 3.0))
        p.drawLine(QPointF(6.0, 6.0), QPointF(9.0, 3.0))
        p.drawLine(QPointF(12.0, 6.0), QPointF(9.0, 3.0))
    elif kind == "focus_map":
        p.drawRect(QRectF(3.0, 3.0, 12.0, 12.0))
        p.drawRect(QRectF(6.0, 5.0, 6.0, 8.0))
    elif kind == "settings":
        cx, cy = 9.0, 9.0
        p.drawEllipse(QPointF(cx, cy), 2.8, 2.8)
        p.drawEllipse(QPointF(cx, cy), 5.6, 5.6)
        for i in range(8):
            ang = i * math.pi / 4.0
            x1 = cx + 5.6 * math.cos(ang)
            y1 = cy + 5.6 * math.sin(ang)
            x2 = cx + 7.2 * math.cos(ang)
            y2 = cy + 7.2 * math.sin(ang)
            p.drawLine(QPointF(x1, y1), QPointF(x2, y2))

    p.end()
    return QIcon(px)
