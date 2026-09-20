"""Независимый картографический рендерер карты в QImage без привязки к размеру окна."""

import logging
import math
from pathlib import Path
from typing import Any
import numpy as np

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (
    QBrush,
    QColor,
    QFont,
    QImage,
    QPainter,
    QPainterPath,
    QPen,
    QTransform,
)
from shapely.geometry import (
    LineString,
    MultiLineString,
    MultiPoint,
    MultiPolygon,
    Point,
    Polygon,
)

from rme_mapper.app_info import APP_NAME, APP_VERSION, AUTHOR_NAME
from rme_mapper.exporters.decorations import MapDecorationRenderer
from rme_mapper.exporters.models import ImageExportOptions
from rme_mapper.models.map_layer import MapLayer
from rme_mapper.models.map_point import MapPoint
from rme_mapper.services.coordinate_service import CoordinateService
from rme_mapper.services.geodesic_service import GeodesicService
from rme_mapper.services.grid_calculator import GridCalculator

logger = logging.getLogger("rme_mapper.exporters.renderer")


@staticmethod
def _build_path_from_shapely(geom: Any) -> QPainterPath:
    """Построение составного QPainterPath из Shapely геометрии в координатах (x, -y)."""
    path = QPainterPath()
    path.setFillRule(Qt.FillRule.OddEvenFill)

    if geom is None or geom.is_empty:
        return path

    def append_polygon(p: Polygon) -> None:
        ext = list(p.exterior.coords)
        if ext:
            path.moveTo(ext[0][0], -ext[0][1])
            for x, y in ext[1:]:
                path.lineTo(x, -y)
            path.closeSubpath()
        for interior in p.interiors:
            inter = list(interior.coords)
            if inter:
                path.moveTo(inter[0][0], -inter[0][1])
                for x, y in inter[1:]:
                    path.lineTo(x, -y)
                path.closeSubpath()

    def append_linestring(l: LineString) -> None:
        coords = list(l.coords)
        if coords:
            path.moveTo(coords[0][0], -coords[0][1])
            for x, y in coords[1:]:
                path.lineTo(x, -y)

    if isinstance(geom, Polygon):
        append_polygon(geom)
    elif isinstance(geom, MultiPolygon):
        for poly in geom.geoms:
            append_polygon(poly)
    elif isinstance(geom, LineString):
        append_linestring(geom)
    elif isinstance(geom, MultiLineString):
        for line in geom.geoms:
            append_linestring(line)
    elif isinstance(geom, Point):
        path.addEllipse(QPointF(geom.x, -geom.y), 0.02, 0.02)
    elif isinstance(geom, MultiPoint):
        for pt in geom.geoms:
            path.addEllipse(QPointF(pt.x, -pt.y), 0.02, 0.02)

    return path


class MapRenderer:
    """Служба чистого рендеринга векторной карты, точек, зон и оформления в растровый QImage."""

    @classmethod
    def calculate_adjusted_extent(
        cls,
        extent: tuple[float, float, float, float],
        width_px: int,
        height_px: int,
    ) -> tuple[float, float, float, float]:
        """Корректировка географического охвата для строгого сохранения пропорций без растяжения."""
        min_x, min_y, max_x, max_y = extent
        extent_w = max_x - min_x
        extent_h = max_y - min_y

        if extent_w <= 0:
            extent_w = 1.0
            min_x -= 0.5
            max_x += 0.5
        if extent_h <= 0:
            extent_h = 1.0
            min_y -= 0.5
            max_y += 0.5

        image_aspect = float(width_px) / float(height_px)
        geo_aspect = extent_w / extent_h

        cx = (min_x + max_x) / 2.0
        cy = (min_y + max_y) / 2.0

        if image_aspect > geo_aspect:
            # Изображение шире, чем охват -> симметрично расширяем X
            new_w = extent_h * image_aspect
            adj_min_x = cx - new_w / 2.0
            adj_max_x = cx + new_w / 2.0
            adj_min_y = min_y
            adj_max_y = max_y
        else:
            # Изображение выше, чем охват -> симметрично расширяем Y
            new_h = extent_w / image_aspect
            adj_min_x = min_x
            adj_max_x = max_x
            adj_min_y = cy - new_h / 2.0
            adj_max_y = cy + new_h / 2.0

        return (adj_min_x, adj_min_y, adj_max_x, adj_max_y)

    @classmethod
    def render_map(
        cls,
        options: ImageExportOptions,
        active_crs: str,
        target_extent: tuple[float, float, float, float],
        loaded_layers_render_data: list[tuple[str, QPainterPath, QPen, QBrush, float, bool]] | None = None,
        points: list[MapPoint] | None = None,
        selected_point_ids: set[str] | None = None,
        precomputed_zones: dict[str, Polygon] | None = None,
        raster_source: Path | str | None = None,
        is_raster_visible: bool = True,
        hidden_group_ids: set[str] | None = None,
    ) -> QImage:
        """Полный рендер карты в QImage заданного разрешения."""
        errors = options.validate()
        if errors:
            raise ValueError(f"Некорректные опции экспорта: {'; '.join(errors)}")

        width = options.width_px
        height = options.height_px

        # 1. Корректировка охвата под пропорции изображения
        adj_extent = cls.calculate_adjusted_extent(target_extent, width, height)
        min_x, min_y, max_x, max_y = adj_extent
        extent_w = max_x - min_x
        extent_h = max_y - min_y

        scale_x = width / extent_w
        scale_y = height / extent_h
        scale = scale_x  # scale_x == scale_y после calculate_adjusted_extent

        # 2. Создание QImage
        norm_fmt = options.normalized_format()
        if options.transparent_background and norm_fmt == "PNG":
            image = QImage(width, height, QImage.Format.Format_ARGB32_Premultiplied)
            image.fill(Qt.GlobalColor.transparent)
        else:
            image = QImage(width, height, QImage.Format.Format_ARGB32_Premultiplied)
            bg_color = QColor(options.background_color or "#FFFFFF")
            image.fill(bg_color)

        # 3. Метаданные изображения
        image.setText("Software", APP_NAME)
        image.setText("Author", AUTHOR_NAME)
        image.setText("Version", APP_VERSION)

        painter = QPainter(image)
        painter.setRenderHints(
            QPainter.RenderHint.Antialiasing
            | QPainter.RenderHint.SmoothPixmapTransform
            | QPainter.RenderHint.TextAntialiasing
        )

        try:
            # 3.5 Отрисовка растровой подложки GeoTIFF (до векторных слоев и точек)
            if raster_source and is_raster_visible:
                cls._render_raster_layer(
                    painter=painter,
                    raster_source=raster_source,
                    target_extent=adj_extent,
                    width=width,
                    height=height,
                    min_x=min_x,
                    max_y=max_y,
                    scale=scale,
                )

            # 4. Отрисовка базовых слоев карты
            if loaded_layers_render_data:
                cls._render_base_layers(
                    painter=painter,
                    layers_data=loaded_layers_render_data,
                    min_x=min_x,
                    max_y=max_y,
                    scale=scale,
                )

            # Коэффициент масштабирования экранных элементов
            scale_factor = options.scale_factor()

            # 4.5. Отрисовка координатной сетки (над базовыми слоями, под зонами и точками)
            if options.include_grid:
                cls._render_grid(
                    painter=painter,
                    extent=adj_extent,
                    active_crs=active_crs,
                    min_x=min_x,
                    max_y=max_y,
                    scale=scale,
                    width=width,
                    height=height,
                    scale_factor=scale_factor,
                )

            # 5. Отрисовка геодезических зон
            user_points = points or []
            if hidden_group_ids:
                user_points = [p for p in user_points if p.group_id not in hidden_group_ids]
            if options.include_zones:
                cls._render_zones(
                    painter=painter,
                    points=user_points,
                    active_crs=active_crs,
                    min_x=min_x,
                    max_y=max_y,
                    scale=scale,
                    precomputed_zones=precomputed_zones,
                )

            # 6. Отрисовка пользовательских точек
            if options.include_points:
                cls._render_points(
                    painter=painter,
                    points=user_points,
                    active_crs=active_crs,
                    min_x=min_x,
                    max_y=max_y,
                    scale=scale,
                    scale_factor=scale_factor,
                )

            # 7. Отрисовка подписей точек
            if options.include_labels and options.labels_mode != "none":
                cls._render_labels(
                    painter=painter,
                    points=user_points,
                    active_crs=active_crs,
                    min_x=min_x,
                    max_y=max_y,
                    scale=scale,
                    scale_factor=scale_factor,
                    labels_mode=options.labels_mode,
                    selected_point_ids=selected_point_ids or set(),
                    image_width=width,
                    image_height=height,
                    label_content_mode=getattr(options, "label_content_mode", "name"),
                )

            # 8. Отрисовка элементов картографического оформления
            image_rect = QRectF(0.0, 0.0, float(width), float(height))
            margin = float(options.margin_px) * scale_factor

            # Заголовок
            if options.include_title and options.title_text:
                MapDecorationRenderer.render_title(
                    painter=painter,
                    title=options.title_text,
                    image_rect=image_rect,
                    scale_factor=scale_factor,
                    margin=margin,
                )

            # CRS
            if options.include_crs and active_crs:
                MapDecorationRenderer.render_crs_label(
                    painter=painter,
                    crs_str=active_crs,
                    image_rect=image_rect,
                    scale_factor=scale_factor,
                    margin=margin,
                )

            # Масштабная линейка
            if options.include_scale_bar:
                MapDecorationRenderer.render_scale_bar(
                    painter=painter,
                    extent=adj_extent,
                    active_crs=active_crs,
                    image_width=width,
                    scale_factor=scale_factor,
                    margin=margin,
                    image_rect=image_rect,
                )

            # Легенда
            if options.include_legend:
                MapDecorationRenderer.render_legend(
                    painter=painter,
                    points=user_points,
                    include_zones=options.include_zones,
                    position=options.legend_position,
                    image_rect=image_rect,
                    scale_factor=scale_factor,
                    margin=margin,
                )

            # Стрелка севера
            if options.include_north_arrow:
                MapDecorationRenderer.render_north_arrow(
                    painter=painter,
                    extent=adj_extent,
                    active_crs=active_crs,
                    image_rect=image_rect,
                    scale_factor=scale_factor,
                    margin=margin,
                )

        finally:
            painter.end()

        return image

    @classmethod
    def _render_raster_layer(
        cls,
        painter: QPainter,
        raster_source: Path | str,
        target_extent: tuple[float, float, float, float],
        width: int,
        height: int,
        min_x: float,
        max_y: float,
        scale: float,
    ) -> None:
        """Рендеринг геопривязанной растровой подложки через windowed reading."""
        from rme_mapper.backends.factory import BackendFactory, get_raster_backend
        if not BackendFactory.supports_geotiff():
            return

        try:
            rb = get_raster_backend()
            res = rb.read_window(raster_source, target_extent, width, height)
            if res is None:
                return

            rgba, meta = res
            h_r, w_r = rgba.shape[:2]
            arr_c = np.ascontiguousarray(rgba)
            qimg = QImage(arr_c.data, w_r, h_r, w_r * 4, QImage.Format.Format_RGBA8888)

            win_t = meta.get("transform")
            if not win_t:
                return

            a, b, c_aff, d, e, f_aff = win_t
            # В системе координат изображения:
            # X_img = (geo_x - min_x) * scale = (a * px + b * py + c_aff - min_x) * scale
            # Y_img = (max_y - geo_y) * scale = (max_y - (d * px + e * py + f_aff)) * scale
            m11 = float(a * scale)
            m12 = float(-d * scale)
            m21 = float(b * scale)
            m22 = float(-e * scale)
            dx = float((c_aff - min_x) * scale)
            dy = float((max_y - f_aff) * scale)

            t_export = QTransform(m11, m12, m21, m22, dx, dy)

            painter.save()
            painter.setWorldTransform(t_export)
            painter.drawImage(0, 0, qimg)
            painter.restore()

        except Exception as e:
            logger.warning("Ошибка рендеринга растровой подложки при экспорте: %s", e)

    @classmethod
    def _render_base_layers(
        cls,
        painter: QPainter,
        layers_data: list[tuple[str, QPainterPath, QPen, QBrush, float, bool]],
        min_x: float,
        max_y: float,
        scale: float,
    ) -> None:
        """Отрисовка базовых слоев с применением матрицы трансформации мира в пиксели."""
        # Сортировка по z_order
        sorted_layers = sorted(layers_data, key=lambda item: item[4])

        painter.save()
        # Трансформация: (x, -y) в пиксели (px, py)
        # px = (x - min_x) * scale = x * scale - min_x * scale
        # py = (max_y - y) * scale = (-y + max_y) * scale = (-y) * scale + max_y * scale
        transform = QTransform()
        transform.translate(-min_x * scale, max_y * scale)
        transform.scale(scale, scale)
        painter.setTransform(transform)

        for layer_id, path, pen, brush, z_val, visible in sorted_layers:
            if not visible or path.isEmpty():
                continue

            # Косметическое масштабирование пера для четкости на высоких разрешениях
            export_pen = QPen(pen)
            if export_pen.widthF() <= 0:
                export_pen.setWidthF(1.0 / scale)
            else:
                export_pen.setWidthF(export_pen.widthF() / scale)
            export_pen.setCosmetic(True)

            painter.setPen(export_pen)
            painter.setBrush(brush)
            painter.drawPath(path)

        painter.restore()

    @classmethod
    def _render_zones(
        cls,
        painter: QPainter,
        points: list[MapPoint],
        active_crs: str,
        min_x: float,
        max_y: float,
        scale: float,
        precomputed_zones: dict[str, Polygon] | None = None,
    ) -> None:
        """Отрисовка геодезических зон точек."""
        painter.save()
        transform = QTransform()
        transform.translate(-min_x * scale, max_y * scale)
        transform.scale(scale, scale)
        painter.setTransform(transform)

        for pt in points:
            if not pt.visible or not pt.zone_enabled or pt.radius_m <= 0:
                continue

            # Получаем полигон зоны
            poly: Polygon | None = None
            if precomputed_zones and pt.id in precomputed_zones:
                poly = precomputed_zones[pt.id]
            else:
                try:
                    geo_c = GeodesicService.create_geodesic_circle(pt.longitude, pt.latitude, pt.radius_m)
                    poly = CoordinateService.transform_polygon(
                        geo_c,
                        source_crs="EPSG:4326",
                        target_crs=active_crs,
                    )
                except Exception as err:
                    logger.warning("Ошибка генерации геодезической зоны для точки '%s': %s", pt.name, err)
                    continue

            if poly is None or poly.is_empty:
                continue

            zone_path = _build_path_from_shapely(poly)
            if zone_path.isEmpty():
                continue

            alpha = int(pt.zone_opacity * 255.0 / 100.0)
            brush_color = QColor(pt.zone_red, pt.zone_green, pt.zone_blue, alpha)
            brush = QBrush(brush_color)

            border_style_map = {
                "solid": Qt.PenStyle.SolidLine,
                "dash": Qt.PenStyle.DashLine,
                "dot": Qt.PenStyle.DotLine,
            }
            pen_style = border_style_map.get(pt.zone_border_style, Qt.PenStyle.SolidLine)

            if pt.zone_border_width > 0:
                pen = QPen(
                    QColor(pt.zone_border_red, pt.zone_border_green, pt.zone_border_blue),
                    float(pt.zone_border_width),
                    pen_style,
                )
                pen.setCosmetic(True)
            else:
                pen = QPen(Qt.PenStyle.NoPen)

            painter.setPen(pen)
            painter.setBrush(brush)
            painter.drawPath(zone_path)

        painter.restore()

    @classmethod
    def _render_points(
        cls,
        painter: QPainter,
        points: list[MapPoint],
        active_crs: str,
        min_x: float,
        max_y: float,
        scale: float,
        scale_factor: float,
    ) -> None:
        """Отрисовка значков пользовательских точек в экранных пикселях."""
        # Ограничение масштабирования маркера: базовый размер * scale_factor
        marker_scale = min(max(scale_factor, 0.5), 5.0)

        for pt in points:
            if not pt.visible:
                continue

            try:
                mx, my = CoordinateService.transform_xy(
                    pt.longitude, pt.latitude,
                    source_crs=pt.source_crs,
                    target_crs=active_crs,
                )
            except Exception as e:
                logger.warning("Ошибка пересчета координат точки '%s': %s", pt.name, e)
                continue

            px = (mx - min_x) * scale
            py = (max_y - my) * scale

            marker_size = pt.size * marker_scale
            half = marker_size / 2.0
            sym = (pt.symbol or "circle").strip().lower()

            fill_alpha = int(pt.opacity * 255.0 / 100.0)
            fill_brush = QBrush(QColor(pt.red, pt.green, pt.blue, fill_alpha))
            if pt.stroke_width > 0:
                outline_pen = QPen(
                    QColor(pt.stroke_red, pt.stroke_green, pt.stroke_blue),
                    max(1.0, float(pt.stroke_width) * marker_scale),
                )
            else:
                outline_pen = QPen(Qt.PenStyle.NoPen)

            painter.setPen(outline_pen)
            painter.setBrush(fill_brush)

            if sym == "square":
                painter.drawRect(QRectF(px - half, py - half, marker_size, marker_size))
            elif sym == "triangle":
                path = QPainterPath()
                path.moveTo(px, py - half)
                path.lineTo(px + half, py + half)
                path.lineTo(px - half, py + half)
                path.closeSubpath()
                painter.drawPath(path)
            else:  # circle
                painter.drawEllipse(QPointF(px, py), half, half)

    @classmethod
    def _render_labels(
        cls,
        painter: QPainter,
        points: list[MapPoint],
        active_crs: str,
        min_x: float,
        max_y: float,
        scale: float,
        scale_factor: float,
        labels_mode: str,
        selected_point_ids: set[str],
        image_width: int,
        image_height: int,
        label_content_mode: str = "name",
    ) -> None:
        """Отрисовка текстовых подписей точек с контрастным гало."""
        from rme_mapper.maps.map_canvas import format_point_label

        marker_scale = min(max(scale_factor, 0.5), 5.0)
        font_size = max(8, round(9.0 * marker_scale))
        font = QFont("Segoe UI", font_size, QFont.Weight.Bold)
        painter.setFont(font)
        fm = painter.fontMetrics()

        for pt in points:
            if not pt.visible:
                continue

            # Фильтрация по режиму
            if labels_mode == "selected" and pt.id not in selected_point_ids:
                continue

            label_text = format_point_label(pt, label_content_mode)
            if not label_text.strip():
                continue

            try:
                mx, my = CoordinateService.transform_xy(
                    pt.longitude, pt.latitude,
                    source_crs=pt.source_crs,
                    target_crs=active_crs,
                )
            except Exception:
                continue

            px = (mx - min_x) * scale
            py = (max_y - my) * scale

            # Смещение текста относительно значка
            marker_size = pt.size * marker_scale
            offset_x = (marker_size / 2.0) + (4.0 * marker_scale)
            offset_y = -(marker_size / 2.0)

            tx = px + offset_x
            ty = py + offset_y

            # Проверка выхода за границы изображения
            text_w = fm.horizontalAdvance(label_text)
            text_h = fm.height()
            if tx + text_w < 0 or tx > image_width or ty + text_h < 0 or ty > image_height:
                continue

            label_rect = QRectF(tx, ty, float(text_w), float(text_h))

            # Белое контрастное гало (смещение во все стороны)
            halo_pen = QPen(QColor("#FFFFFF"), max(1.5, 2.0 * marker_scale))
            painter.setPen(halo_pen)

            halo_offsets = [(-1, 0), (1, 0), (0, -1), (0, 1), (-1, -1), (1, -1), (-1, 1), (1, 1)]
            for dx, dy in halo_offsets:
                painter.drawText(
                    label_rect.translated(dx * marker_scale * 0.75, dy * marker_scale * 0.75),
                    Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop,
                    label_text,
                )

            # Основной текст
            painter.setPen(QPen(QColor("#1E293B")))
            painter.drawText(label_rect, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop, label_text)

    @classmethod
    def _render_grid(
        cls,
        painter: QPainter,
        extent: tuple[float, float, float, float],
        active_crs: str,
        min_x: float,
        max_y: float,
        scale: float,
        width: int,
        height: int,
        scale_factor: float,
    ) -> None:
        """Отрисовка координатной сетки с подписями при экспорте карты."""
        grid_res = GridCalculator.calculate_grid(extent, active_crs)
        if not grid_res:
            return

        pen = QPen(QColor(120, 130, 140, 110), max(1.0, 1.0 * scale_factor))
        pen.setStyle(Qt.PenStyle.DashLine)
        pen.setDashPattern([4, 4])

        font_size = max(8, round(9.0 * scale_factor))
        font = QFont("Segoe UI", font_size)
        text_pen = QPen(QColor(70, 80, 90, 220))

        # 1. Вертикальные линии
        for line in grid_res.vertical_lines:
            gx = (line.coord - min_x) * scale
            painter.setPen(pen)
            painter.drawLine(QPointF(gx, 0.0), QPointF(gx, float(height)))

            painter.setFont(font)
            painter.setPen(text_pen)
            painter.drawText(QPointF(gx + 4.0 * scale_factor, 14.0 * scale_factor), line.label)

        # 2. Горизонтальные линии
        for line in grid_res.horizontal_lines:
            gy = (max_y - line.coord) * scale
            painter.setPen(pen)
            painter.drawLine(QPointF(0.0, gy), QPointF(float(width), gy))

            painter.setFont(font)
            painter.setPen(text_pen)
            painter.drawText(QPointF(6.0 * scale_factor, gy - 4.0 * scale_factor), line.label)

