"""Отрисовка элементов оформления карты: заголовок, CRS, легенда, масштабная линейка, стрелка севера."""

import logging
import math
from typing import Any

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QFont, QPainter, QPainterPath, QPen

from rme_mapper.i18n import tr
from rme_mapper.models.map_point import MapPoint
from rme_mapper.services.coordinate_service import CoordinateService
from rme_mapper.services.geodesic_service import GeodesicService

logger = logging.getLogger("rme_mapper.exporters.decorations")


NICE_INTERVALS = [
    1, 2, 5, 10, 20, 50, 100, 200, 500,
    1_000, 2_000, 5_000, 10_000, 20_000, 50_000, 100_000, 200_000, 500_000, 1_000_000,
]


class MapDecorationRenderer:
    """Рендерер элементов картографического оформления поверх готового холста карты."""

    @classmethod
    def render_title(
        cls,
        painter: QPainter,
        title: str,
        image_rect: QRectF,
        scale_factor: float,
        margin: float,
    ) -> QRectF:
        """Отрисовка заголовка карты в верхней части изображения."""
        clean_title = (title or "").strip()
        if not clean_title:
            return QRectF()

        font_size = max(11, round(16.0 * scale_factor))
        font = QFont("Segoe UI", font_size, QFont.Weight.Bold)
        painter.setFont(font)

        fm = painter.fontMetrics()
        text_width = fm.horizontalAdvance(clean_title)
        text_height = fm.height()

        pad_x = 16.0 * scale_factor
        pad_y = 8.0 * scale_factor
        badge_w = text_width + pad_x * 2.0
        badge_h = text_height + pad_y * 2.0

        # Размещение по центру вверху
        x = (image_rect.width() - badge_w) / 2.0
        y = margin
        badge_rect = QRectF(x, y, badge_w, badge_h)

        cls._draw_badge_background(painter, badge_rect, scale_factor)

        # Текст
        painter.setPen(QPen(QColor("#111827")))
        painter.drawText(badge_rect, Qt.AlignmentFlag.AlignCenter, clean_title)
        return badge_rect

    @classmethod
    def render_crs_label(
        cls,
        painter: QPainter,
        crs_str: str,
        image_rect: QRectF,
        scale_factor: float,
        margin: float,
    ) -> QRectF:
        """Отрисовка плашки с обозначением системы координат (CRS)."""
        clean_crs = (crs_str or "").strip()
        if not clean_crs:
            return QRectF()

        display_text = f"CRS: {clean_crs}"
        font_size = max(9, round(10.0 * scale_factor))
        font = QFont("Segoe UI", font_size, QFont.Weight.Medium)
        painter.setFont(font)

        fm = painter.fontMetrics()
        text_width = fm.horizontalAdvance(display_text)
        text_height = fm.height()

        pad_x = 10.0 * scale_factor
        pad_y = 5.0 * scale_factor
        badge_w = text_width + pad_x * 2.0
        badge_h = text_height + pad_y * 2.0

        # Внизу слева
        x = margin
        y = image_rect.height() - margin - badge_h
        badge_rect = QRectF(x, y, badge_w, badge_h)

        cls._draw_badge_background(painter, badge_rect, scale_factor)

        painter.setPen(QPen(QColor("#374151")))
        painter.drawText(badge_rect, Qt.AlignmentFlag.AlignCenter, display_text)
        return badge_rect

    @classmethod
    def render_legend(
        cls,
        painter: QPainter,
        points: list[MapPoint],
        include_zones: bool,
        position: str,
        image_rect: QRectF,
        scale_factor: float,
        margin: float,
    ) -> QRectF:
        """Отрисовка компактной легенды типов объектов (формы маркеров и зоны)."""
        # Анализируем, какие формы маркеров реально есть среди видимых точек
        shapes_present: set[str] = set()
        has_zones = False

        for pt in points:
            if pt.visible:
                shapes_present.add((pt.symbol or "circle").strip().lower())
                if include_zones and pt.zone_enabled and pt.radius_m > 0:
                    has_zones = True

        items: list[tuple[str, str]] = []
        # Порядок: Круг, Квадрат, Треугольник
        if "circle" in shapes_present:
            items.append(("circle", tr("shape.circle")))
        if "square" in shapes_present:
            items.append(("square", tr("shape.square")))
        if "triangle" in shapes_present:
            items.append(("triangle", tr("shape.triangle")))
        if has_zones:
            items.append(("zone", tr("export.legend_zone")))

        if not items:
            return QRectF()

        title_font = QFont("Segoe UI", max(10, round(11.0 * scale_factor)), QFont.Weight.Bold)
        item_font = QFont("Segoe UI", max(9, round(10.0 * scale_factor)), QFont.Weight.Normal)

        painter.setFont(title_font)
        fm_title = painter.fontMetrics()
        legend_title = tr("export.legend_title")
        max_text_w = fm_title.horizontalAdvance(legend_title)

        painter.setFont(item_font)
        fm_item = painter.fontMetrics()
        for _, label in items:
            w = fm_item.horizontalAdvance(label)
            if w > max_text_w:
                max_text_w = w

        icon_size = 14.0 * scale_factor
        row_height = max(icon_size, float(fm_item.height())) + 6.0 * scale_factor
        pad_x = 12.0 * scale_factor
        pad_y = 10.0 * scale_factor

        card_w = max_text_w + icon_size + pad_x * 2.0 + 10.0 * scale_factor
        card_h = pad_y * 2.0 + fm_title.height() + 8.0 * scale_factor + len(items) * row_height

        # Вычисление координат по положению
        pos = (position or "bottom_right").lower()
        if pos == "top_left":
            x = margin
            y = margin + 50.0 * scale_factor  # отступ ниже возможного заголовка
        elif pos == "top_right":
            x = image_rect.width() - margin - card_w
            y = margin
        elif pos == "bottom_left":
            x = margin
            y = image_rect.height() - margin - card_h - 40.0 * scale_factor  # выше CRS
        else:  # bottom_right
            x = image_rect.width() - margin - card_w
            y = image_rect.height() - margin - card_h

        card_rect = QRectF(x, y, card_w, card_h)
        cls._draw_badge_background(painter, card_rect, scale_factor)

        # Заголовок легенды
        painter.setFont(title_font)
        painter.setPen(QPen(QColor("#111827")))
        title_rect = QRectF(x + pad_x, y + pad_y, card_w - pad_x * 2.0, float(fm_title.height()))
        painter.drawText(title_rect, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, legend_title)

        # Элементы легенды
        curr_y = y + pad_y + fm_title.height() + 8.0 * scale_factor
        painter.setFont(item_font)

        for kind, label in items:
            row_rect = QRectF(x + pad_x, curr_y, card_w - pad_x * 2.0, row_height)
            icon_center_x = x + pad_x + icon_size / 2.0
            icon_center_y = curr_y + row_height / 2.0

            cls._draw_legend_icon(painter, kind, icon_center_x, icon_center_y, icon_size, scale_factor)

            text_rect = QRectF(
                x + pad_x + icon_size + 8.0 * scale_factor,
                curr_y,
                card_w - pad_x * 2.0 - icon_size - 8.0 * scale_factor,
                row_height,
            )
            painter.setPen(QPen(QColor("#374151")))
            painter.drawText(text_rect, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, label)

            curr_y += row_height

        return card_rect

    @classmethod
    def _draw_legend_icon(
        cls,
        painter: QPainter,
        kind: str,
        cx: float,
        cy: float,
        size: float,
        scale_factor: float,
    ) -> None:
        """Отрисовка иконки символа в легенде."""
        half = size / 2.0
        border_pen = QPen(QColor("#4B5563"), max(1.0, 1.2 * scale_factor))
        fill_brush = QBrush(QColor("#3B82F6"))  # характерный синий для маркеров

        if kind == "circle":
            painter.setPen(border_pen)
            painter.setBrush(fill_brush)
            painter.drawEllipse(QPointF(cx, cy), half, half)
        elif kind == "square":
            painter.setPen(border_pen)
            painter.setBrush(fill_brush)
            painter.drawRect(QRectF(cx - half, cy - half, size, size))
        elif kind == "triangle":
            path = QPainterPath()
            path.moveTo(cx, cy - half)
            path.lineTo(cx + half, cy + half)
            path.lineTo(cx - half, cy + half)
            path.closeSubpath()
            painter.setPen(border_pen)
            painter.setBrush(fill_brush)
            painter.drawPath(path)
        elif kind == "zone":
            # Полупрозрачный круговой сектор зоны
            zone_brush = QBrush(QColor(220, 38, 38, 70))
            zone_pen = QPen(QColor(220, 38, 38, 200), max(1.0, 1.2 * scale_factor), Qt.PenStyle.DashLine)
            painter.setPen(zone_pen)
            painter.setBrush(zone_brush)
            painter.drawEllipse(QPointF(cx, cy), half, half)

    @classmethod
    def render_scale_bar(
        cls,
        painter: QPainter,
        extent: tuple[float, float, float, float],
        active_crs: str,
        image_width: int,
        scale_factor: float,
        margin: float,
        image_rect: QRectF,
    ) -> QRectF:
        """Отрисовка масштабно-корректной линейки расстояний на основе GeodesicService."""
        min_x, min_y, max_x, max_y = extent
        extent_w = max_x - min_x
        extent_h = max_y - min_y

        if extent_w <= 0 or extent_h <= 0:
            return QRectF()

        # Две точки в нижней трети охвата для замера реального геодезического расстояния
        test_y = min_y + extent_h * 0.15
        test_x1 = (min_x + max_x) / 2.0 - extent_w * 0.2
        test_x2 = (min_x + max_x) / 2.0 + extent_w * 0.2

        try:
            lon1, lat1 = CoordinateService.transform_xy(test_x1, test_y, active_crs, "OGC:CRS84")
            lon2, lat2 = CoordinateService.transform_xy(test_x2, test_y, active_crs, "OGC:CRS84")
            dist_m = GeodesicService.calculate_distance(lon1, lat1, lon2, lat2)
        except Exception as err:
            logger.warning("Ошибка расчета масштаба через GeodesicService: %s", err)
            dist_m = extent_w * 0.4

        # Пикселей на метр
        pixel_span = (test_x2 - test_x1) * (image_width / extent_w)
        if pixel_span <= 0 or dist_m <= 0:
            return QRectF()

        meters_per_pixel = dist_m / pixel_span

        # Желаемая длина линейки: 120-200 пикселей с учетом масштаба
        target_bar_px = 160.0 * scale_factor
        target_dist_m = target_bar_px * meters_per_pixel

        # Подбираем ближайшее "красивое" значение
        nice_dist_m = NICE_INTERVALS[0]
        for val in NICE_INTERVALS:
            if val <= target_dist_m:
                nice_dist_m = val
            else:
                break

        actual_bar_px = nice_dist_m / meters_per_pixel
        # Ограничиваем разумными пределами
        actual_bar_px = max(40.0 * scale_factor, min(actual_bar_px, image_width * 0.4))

        # Форматирование текста расстояния
        if nice_dist_m >= 1000:
            km_val = nice_dist_m / 1000.0
            km_str = f"{km_val:.0f}" if km_val == int(km_val) else f"{km_val:.1f}"
            unit_str = tr("unit.km") if hasattr(tr, "__call__") else "км"
            label_text = f"{km_str} {unit_str}"
        else:
            unit_str = tr("unit.m") if hasattr(tr, "__call__") else "м"
            label_text = f"{nice_dist_m} {unit_str}"

        font_size = max(9, round(10.0 * scale_factor))
        font = QFont("Segoe UI", font_size, QFont.Weight.Bold)
        painter.setFont(font)
        fm = painter.fontMetrics()

        pad_x = 14.0 * scale_factor
        pad_y = 8.0 * scale_factor
        bar_h = 6.0 * scale_factor
        card_w = max(actual_bar_px, float(fm.horizontalAdvance(label_text))) + pad_x * 2.0
        card_h = bar_h + fm.height() + pad_y * 2.0 + 6.0 * scale_factor

        # Размещение внизу по центру или чуть правее центра
        x = (image_rect.width() - card_w) / 2.0
        y = image_rect.height() - margin - card_h

        card_rect = QRectF(x, y, card_w, card_h)
        cls._draw_badge_background(painter, card_rect, scale_factor)

        # Текст
        painter.setPen(QPen(QColor("#111827")))
        text_rect = QRectF(x, y + pad_y, card_w, float(fm.height()))
        painter.drawText(text_rect, Qt.AlignmentFlag.AlignCenter, label_text)

        # Линейка (черно-белая сегментированная)
        bar_start_x = x + (card_w - actual_bar_px) / 2.0
        bar_y = y + pad_y + fm.height() + 4.0 * scale_factor

        # Делим линейку на 2 сегмента (черный и белый с обводкой)
        half_w = actual_bar_px / 2.0

        painter.setPen(QPen(QColor("#111827"), 1.0))
        painter.setBrush(QBrush(QColor("#111827")))
        painter.drawRect(QRectF(bar_start_x, bar_y, half_w, bar_h))

        painter.setBrush(QBrush(QColor("#FFFFFF")))
        painter.drawRect(QRectF(bar_start_x + half_w, bar_y, half_w, bar_h))

        # Засечки по краям
        tick_h = bar_h + 4.0 * scale_factor
        tick_y = bar_y - 2.0 * scale_factor
        painter.drawLine(QPointF(bar_start_x, tick_y), QPointF(bar_start_x, tick_y + tick_h))
        painter.drawLine(QPointF(bar_start_x + half_w, tick_y), QPointF(bar_start_x + half_w, tick_y + tick_h))
        painter.drawLine(QPointF(bar_start_x + actual_bar_px, tick_y), QPointF(bar_start_x + actual_bar_px, tick_y + tick_h))

        return card_rect

    @classmethod
    def calculate_true_north_angle(
        cls,
        extent: tuple[float, float, float, float],
        active_crs: str,
    ) -> float:
        """Расчет угла истинного севера (в градусах, по часовой стрелке от вертикали) для центра экстента."""
        min_x, min_y, max_x, max_y = extent
        cx = (min_x + max_x) / 2.0
        cy = (min_y + max_y) / 2.0

        try:
            # 1. Центр в WGS84
            lon_c, lat_c = CoordinateService.transform_xy(cx, cy, active_crs, "OGC:CRS84")
            # 2. Точка чуть севернее по меридиану (+0.02 градуса широты)
            lat_n = min(lat_c + 0.02, 89.5)
            # 3. Обратно в активную CRS
            nx, ny = CoordinateService.transform_xy(lon_c, lat_n, "OGC:CRS84", active_crs)

            dx = nx - cx
            dy = ny - cy

            if abs(dx) < 1e-9 and abs(dy) < 1e-9:
                return 0.0

            # В экранных координатах ось Y направлена вниз, поэтому экранный вектор севера:
            # vx = dx, vy = -dy
            # Угол от направления строго вверх (vx=0, vy < 0):
            angle_rad = math.atan2(dx, dy)
            return math.degrees(angle_rad)
        except Exception as e:
            logger.debug("Не удалось рассчитать угол истинного севера (используется 0°): %s", e)
            return 0.0

    @classmethod
    def render_north_arrow(
        cls,
        painter: QPainter,
        extent: tuple[float, float, float, float],
        active_crs: str,
        image_rect: QRectF,
        scale_factor: float,
        margin: float,
    ) -> QRectF:
        """Отрисовка аккуратной стрелки истинного севера в верхнем правом или верхнем левом углу."""
        angle_deg = cls.calculate_true_north_angle(extent, active_crs)

        arrow_box_size = 46.0 * scale_factor
        card_rect = QRectF(
            image_rect.width() - margin - arrow_box_size,
            margin,
            arrow_box_size,
            arrow_box_size + 14.0 * scale_factor,
        )

        cls._draw_badge_background(painter, card_rect, scale_factor)

        cx = card_rect.center().x()
        cy = card_rect.top() + arrow_box_size / 2.0 + 3.0 * scale_factor

        painter.save()
        painter.translate(cx, cy)
        painter.rotate(angle_deg)

        # Отрисовка стрелки (элегантный компасный треугольник)
        arrow_len = 16.0 * scale_factor
        arrow_half_w = 5.0 * scale_factor

        # Левая темная половина
        left_path = QPainterPath()
        left_path.moveTo(0.0, -arrow_len)
        left_path.lineTo(-arrow_half_w, arrow_len * 0.4)
        left_path.lineTo(0.0, 0.0)
        left_path.closeSubpath()
        painter.setPen(QPen(QColor("#111827"), 1.0))
        painter.setBrush(QBrush(QColor("#111827")))
        painter.drawPath(left_path)

        # Правая светлая половина
        right_path = QPainterPath()
        right_path.moveTo(0.0, -arrow_len)
        right_path.lineTo(arrow_half_w, arrow_len * 0.4)
        right_path.lineTo(0.0, 0.0)
        right_path.closeSubpath()
        painter.setPen(QPen(QColor("#111827"), 1.0))
        painter.setBrush(QBrush(QColor("#E5E7EB")))
        painter.drawPath(right_path)

        painter.restore()

        # Буква "N" под стрелкой
        font = QFont("Segoe UI", max(8, round(9.0 * scale_factor)), QFont.Weight.Bold)
        painter.setFont(font)
        painter.setPen(QPen(QColor("#111827")))
        text_rect = QRectF(
            card_rect.left(),
            card_rect.bottom() - 15.0 * scale_factor,
            card_rect.width(),
            14.0 * scale_factor,
        )
        painter.drawText(text_rect, Qt.AlignmentFlag.AlignCenter, "N")

        return card_rect

    @classmethod
    def _draw_badge_background(
        cls,
        painter: QPainter,
        rect: QRectF,
        scale_factor: float,
    ) -> None:
        """Отрисовка стандартной контрастной полупрозрачной карточки-подложки."""
        radius = 6.0 * scale_factor
        painter.setPen(QPen(QColor("#CBD5E1"), max(1.0, 1.0 * scale_factor)))
        # Белый фон с легкой прозрачностью (242/255) для контраста поверх любых карт
        painter.setBrush(QBrush(QColor(255, 255, 255, 242)))
        painter.drawRoundedRect(rect, radius, radius)

    @classmethod
    def render_attribution(
        cls,
        painter: QPainter,
        attribution_text: str,
        image_rect: QRectF,
        scale_factor: float,
        margin: float,
        logo_required: bool = False,
    ) -> QRectF:
        """Отрисовка копирайта/атрибуции онлайн-провайдера в правом нижнем углу изображения."""
        clean_text = (attribution_text or "").strip()
        if not clean_text:
            return QRectF()

        import re
        display_text = re.sub(r"<[^>]+>", "", clean_text).strip()
        if logo_required and "mapbox" in display_text.lower():
            # Если требуется логотип Mapbox, форматируем аккуратную плашку с указанием провайдера
            if not display_text.startswith("mapbox"):
                display_text = f"mapbox | {display_text}"

        font_size = max(8, round(9.0 * scale_factor))
        font = QFont("Segoe UI", font_size)
        painter.setFont(font)

        fm = painter.fontMetrics()
        text_w = fm.horizontalAdvance(display_text)
        text_h = fm.height()

        pad_x = 8.0 * scale_factor
        pad_y = 4.0 * scale_factor
        badge_w = text_w + pad_x * 2.0
        badge_h = text_h + pad_y * 2.0

        x = image_rect.width() - badge_w - margin
        y = image_rect.height() - badge_h - margin
        badge_rect = QRectF(x, y, badge_w, badge_h)

        radius = 4.0 * scale_factor
        painter.setPen(QPen(QColor(15, 23, 42, 50), max(1.0, 1.0 * scale_factor)))
        painter.setBrush(QBrush(QColor(255, 255, 255, 215)))
        painter.drawRoundedRect(badge_rect, radius, radius)

        painter.setPen(QPen(QColor("#334155")))
        painter.drawText(badge_rect, Qt.AlignmentFlag.AlignCenter, display_text)
        return badge_rect

