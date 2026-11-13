"""Виджет интерактивного отображения карты на базе QGraphicsView."""
from __future__ import annotations


import html
import logging
import math
from typing import Any

import numpy as np
import geopandas as gpd
from PySide6.QtCore import QPointF, QRectF, Qt, Signal, QTimer
from PySide6.QtGui import (
    QBrush,
    QColor,
    QFont,
    QFontMetrics,
    QImage,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
    QResizeEvent,
    QShowEvent,
    QTransform,
    QWheelEvent,
)
from PySide6.QtWidgets import (
    QFrame,
    QGraphicsEllipseItem,
    QGraphicsItem,
    QGraphicsItemGroup,
    QGraphicsLineItem,
    QGraphicsPathItem,
    QGraphicsPixmapItem,
    QGraphicsPolygonItem,
    QGraphicsScene,
    QGraphicsSimpleTextItem,
    QGraphicsTextItem,
    QGraphicsView,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)
from shapely.geometry import (
    LineString,
    MultiLineString,
    MultiPoint,
    MultiPolygon,
    Point,
    Polygon,
)

from rme_mapper.i18n import tr
from rme_mapper.maps.attribution_overlay import AttributionOverlayWidget
from rme_mapper.maps.online_tile_manager import OnlineTileManager
from rme_mapper.maps.scale_overlay import ScaleOverlayWidget
from rme_mapper.models.map_layer import LayerRole, MapLayer
from rme_mapper.models.map_point import MapPoint
from rme_mapper.models.object_group import ObjectGroup
from rme_mapper.models.online_provider import OnlineTileProvider
from rme_mapper.services.coordinate_service import CoordinateService
from rme_mapper.services.geodesic_service import GeodesicService
from rme_mapper.services.grid_calculator import GridCalculator
from rme_mapper.services.scale_service import ScaleService

logger = logging.getLogger("rme_mapper.maps.canvas")


def format_point_label(point: MapPoint, content_mode: str) -> str:
    """Формирование текста подписи точки в зависимости от режима содержимого."""
    num = (point.object_number or "").strip()
    name = (point.name or "").strip()
    mode = (content_mode or "name").lower()
    if mode == "number":
        return num
    elif mode == "number_name":
        if num and name:
            return f"{num} - {name}"
        elif num:
            return num
        elif name:
            return name
        return ""
    else:  # "name"
        return name


class MapCanvas(QGraphicsView):
    """Интерактивный холст для многослойного векторного отображения карты."""

    ZOOM_IN_FACTOR = 1.15
    ZOOM_OUT_FACTOR = 1.0 / 1.15
    MIN_ZOOM = 0.05
    MAX_ZOOM = 500.0

    cursor_position_changed = Signal(float, float)
    cursor_left = Signal()
    map_point_clicked = Signal(float, float)
    add_point_mode_cancelled = Signal()
    point_moved = Signal(str, float, float, float, float)  # point_id, final_map_x, final_map_y, start_map_x, start_map_y
    move_point_mode_cancelled = Signal()
    measurement_updated = Signal(str)
    measurement_finished = Signal(str)
    measurement_geometry_finished = Signal(object)
    measurement_cancelled = Signal()
    online_tiles_progress = Signal(int)
    online_tiles_auth_error = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("mapCanvas")

        self._scene = QGraphicsScene(self)
        self.setScene(self._scene)

        self._current_zoom = 1.0
        self._initial_fit_done = False
        self._interaction_mode = "navigation"

        # Охват административной границы РМЭ (базовый охват для fit_to_view)
        self._boundary_bounds: QRectF | None = None
        # Словарь созданных графических элементов слоев: layer_id -> QGraphicsItem
        self._layer_items: dict[str, QGraphicsItem] = {}
        # Словарь моделей точек для быстрого доступа: point_id -> MapPoint
        self._points_data: dict[str, MapPoint] = {}
        # Словарь графических элементов пользовательских точек: point_id -> QGraphicsItem
        self._user_point_items: dict[str, QGraphicsItem] = {}
        # Словарь графических элементов зон радиуса: point_id -> QGraphicsItem
        self._user_zone_items: dict[str, QGraphicsItem] = {}
        # Словарь графических элементов текстовых подписей: point_id -> QGraphicsSimpleTextItem
        self._user_label_items: dict[str, QGraphicsSimpleTextItem] = {}
        # Словарь индикаторов выделения: point_id -> QGraphicsItem
        self._selection_halo_items: dict[str, QGraphicsItem] = {}

        # Режимы отображения и содержимого подписей
        self._labels_mode = "hidden"  # 'hidden', 'selected', 'all'
        self._label_content_mode = "name"  # 'name', 'number', 'number_name'
        self._selected_point_ids: set[str] = set()
        self._defer_label_recalc: bool = False

        # Состояние перетаскивания точки мышью (Move Point)
        self._is_dragging_point: bool = False
        self._drag_point_id: str | None = None
        self._drag_start_scene_pos: QPointF | None = None
        self._drag_start_map_coords: tuple[float, float] = (0.0, 0.0)

        # Глобальные флаги видимости точек и зон, а также видимость групп
        self._show_points_visible = True
        self._show_zones_visible = True
        self._group_visibility: dict[str, bool] = {}
        self._active_crs: str = "OGC:CRS84"

        # Растровые слои (GeoTIFF)
        self._raster_layer: MapLayer | None = None
        self._raster_item: QGraphicsPixmapItem | None = None
        self._raster_window_item: QGraphicsPixmapItem | None = None
        self._raster_affine: tuple[float, ...] | None = None
        self._raster_full_size: tuple[int, int] | None = None
        self._raster_provider: Any = None
        self._raster_debounce_timer = QTimer(self)
        self._raster_debounce_timer.setSingleShot(True)
        self._raster_debounce_timer.setInterval(250)
        self._raster_debounce_timer.timeout.connect(self._on_raster_debounce_timeout)

        # Этап 19: Экранный масштаб и координатная сетка
        self._show_scale_indicator = True
        self._show_coordinate_grid = False
        self._scale_overlay = ScaleOverlayWidget(self.viewport())
        self._grid_item_group: QGraphicsItemGroup | None = None
        self._grid_debounce_timer = QTimer(self)
        self._grid_debounce_timer.setSingleShot(True)
        self._grid_debounce_timer.setInterval(60)
        self._grid_debounce_timer.timeout.connect(self._render_coordinate_grid)

        # Этап 19: Инструменты измерений (Distance & Area)
        self._measure_points: list[tuple[float, float]] = []
        self._measure_temp_pos: tuple[float, float] | None = None
        self._measure_active_items: list[QGraphicsItem] = []
        self._measure_completed_items: list[QGraphicsItem] = []

        # Состояние панорамирования средней кнопкой
        self._is_middle_panning: bool = False
        self._middle_pan_last_pos: QPointF | None = None

        # Этап 20: Онлайн-карты (XYZ Web Mercator)
        self._online_tile_manager = OnlineTileManager(self._scene, parent=self)
        self._online_tile_manager.tiles_updated.connect(self._on_online_tiles_updated)
        self._online_tile_manager.loading_progress.connect(self.online_tiles_progress.emit)
        self._online_tile_manager.auth_error.connect(self.online_tiles_auth_error.emit)
        self._attribution_overlay = AttributionOverlayWidget(self.viewport())
        self._online_tile_debounce_timer = QTimer(self)
        self._online_tile_debounce_timer.setSingleShot(True)
        self._online_tile_debounce_timer.setInterval(50)
        self._online_tile_debounce_timer.timeout.connect(self._update_online_tiles_viewport)

        self._labels_debounce_timer = QTimer(self)
        self._labels_debounce_timer.setSingleShot(True)
        self._labels_debounce_timer.setInterval(60)
        self._labels_debounce_timer.timeout.connect(self._recalculate_labels_layout)

        self._setup_view_properties()
        self._create_controls()

        self.horizontalScrollBar().valueChanged.connect(self._on_scroll_changed)
        self.verticalScrollBar().valueChanged.connect(self._on_scroll_changed)

    def _setup_view_properties(self) -> None:
        """Настройка свойств холста и оптимизаций отрисовки."""
        self.setRenderHints(
            QPainter.RenderHint.Antialiasing | QPainter.RenderHint.SmoothPixmapTransform
        )
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorViewCenter)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setBackgroundBrush(QBrush(QColor("#F5F7FA")))
        self.setMouseTracking(True)
        if self.viewport():
            self.viewport().setMouseTracking(True)

    def mouseMoveEvent(self, event: Any) -> None:
        """Отслеживание перемещения курсора мыши и перетаскивание точки в режиме move_point."""
        pos = event.position().toPoint() if hasattr(event, "position") else event.pos()
        scene_pt = self.mapToScene(pos)
        map_x = scene_pt.x()
        map_y = -scene_pt.y()
        self.cursor_position_changed.emit(map_x, map_y)

        # Панорамирование средней кнопкой
        if self._is_middle_panning and self._middle_pan_last_pos is not None:
            delta = pos - self._middle_pan_last_pos
            self._middle_pan_last_pos = pos
            self.horizontalScrollBar().setValue(self.horizontalScrollBar().value() - delta.x())
            self.verticalScrollBar().setValue(self.verticalScrollBar().value() - delta.y())
            event.accept()
            return

        if self._interaction_mode in ("measure_distance", "measure_area"):
            if self._measure_points:
                self._measure_temp_pos = (scene_pt.x(), scene_pt.y())
                self._update_measure_preview()
            event.accept()
            return

        if self._is_dragging_point and self._drag_point_id:
            item = self._user_point_items.get(self._drag_point_id)
            pt = self._points_data.get(self._drag_point_id)
            if item and pt:
                item.setPos(scene_pt)
                # Перемещаем подпись
                lbl = self._user_label_items.get(self._drag_point_id)
                if lbl and lbl.isVisible():
                    half = pt.size / 2.0
                    gap = 4.0
                    lbl.setPos(scene_pt.x() + half + gap, scene_pt.y() - half)
                # Перемещаем гало выделения
                halo = self._selection_halo_items.get(self._drag_point_id)
                if halo:
                    halo.setPos(scene_pt)
            event.accept()
            return

        super().mouseMoveEvent(event)

    def mousePressEvent(self, event: Any) -> None:
        """Обработка клика мыши: выбор точки, создание точки, измерение или начало перемещения."""
        # Обработка панорамирования средней кнопкой мыши
        if event.button() == Qt.MouseButton.MiddleButton:
            self._is_middle_panning = True
            pos = event.position().toPoint() if hasattr(event, "position") else event.pos()
            self._middle_pan_last_pos = pos
            if self.viewport():
                self.viewport().setCursor(Qt.CursorShape.ClosedHandCursor)
            event.accept()
            return

        # Режимы измерений
        if self._interaction_mode in ("measure_distance", "measure_area"):
            if event.button() == Qt.MouseButton.LeftButton:
                pos = event.position().toPoint() if hasattr(event, "position") else event.pos()
                scene_pt = self.mapToScene(pos)
                self._measure_points.append((scene_pt.x(), scene_pt.y()))
                self._update_measure_preview()
                event.accept()
                return
            elif event.button() == Qt.MouseButton.RightButton:
                min_pts = 2 if self._interaction_mode == "measure_distance" else 3
                if len(self._measure_points) >= min_pts:
                    self._finish_measurement()
                    event.accept()
                    return

        if self._interaction_mode == "add_point" and event.button() == Qt.MouseButton.LeftButton:
            pos = event.position().toPoint() if hasattr(event, "position") else event.pos()
            scene_pt = self.mapToScene(pos)
            map_x = scene_pt.x()
            map_y = -scene_pt.y()
            self.map_point_clicked.emit(map_x, map_y)
            event.accept()
            return

        if self._interaction_mode == "move_point" and event.button() == Qt.MouseButton.LeftButton:
            pos = event.position().toPoint() if hasattr(event, "position") else event.pos()
            scene_pt = self.mapToScene(pos)

            # Проверяем клик по маркеру выбранной точки (или любой видимой), если выделено не более 1 точки
            target_pid = None
            if len(self._selected_point_ids) <= 1:
                for pid in self._selected_point_ids:
                    item = self._user_point_items.get(pid)
                    pt = self._points_data.get(pid)
                    if item and pt and pt.visible and item.isVisible():
                        dist = math.hypot(scene_pt.x() - item.pos().x(), scene_pt.y() - item.pos().y())
                        if dist <= max(pt.size / 2.0, 10.0):
                            target_pid = pid
                            break

                # Если выбранная точка не найдена под курсором, проверяем другие точки
                if target_pid is None:
                    for pid, item in self._user_point_items.items():
                        pt = self._points_data.get(pid)
                        if pt and pt.visible and item.isVisible():
                            dist = math.hypot(scene_pt.x() - item.pos().x(), scene_pt.y() - item.pos().y())
                            if dist <= max(pt.size / 2.0, 10.0):
                                target_pid = pid
                                break

            if target_pid is not None:
                item = self._user_point_items[target_pid]
                self._is_dragging_point = True
                self._drag_point_id = target_pid
                self._drag_start_scene_pos = QPointF(item.pos().x(), item.pos().y())
                self._drag_start_map_coords = (item.pos().x(), -item.pos().y())
                if self.viewport():
                    self.viewport().setCursor(Qt.CursorShape.ClosedHandCursor)
                event.accept()
                return
            else:
                # Клик в пустое место: обычная навигация (pan)
                self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
                super().mousePressEvent(event)
                return

        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event: Any) -> None:
        """Двойной клик мыши: завершение измерения расстояния или площади."""
        if self._interaction_mode in ("measure_distance", "measure_area") and event.button() == Qt.MouseButton.LeftButton:
            self._finish_measurement()
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

    def mouseReleaseEvent(self, event: Any) -> None:
        """Завершение перетаскивания точки, панорамирования или навигации."""
        if self._is_middle_panning and event.button() == Qt.MouseButton.MiddleButton:
            self._is_middle_panning = False
            self._middle_pan_last_pos = None
            if self.viewport():
                if self._interaction_mode in ("measure_distance", "measure_area", "add_point"):
                    self.viewport().setCursor(Qt.CursorShape.CrossCursor)
                else:
                    self.viewport().setCursor(Qt.CursorShape.ArrowCursor)
            event.accept()
            return

        if self._is_dragging_point and self._drag_point_id:
            self._is_dragging_point = False
            pid = self._drag_point_id
            self._drag_point_id = None
            if self.viewport():
                self.viewport().setCursor(Qt.CursorShape.ArrowCursor)

            item = self._user_point_items.get(pid)
            if item and self._drag_start_scene_pos is not None:
                final_scene_pos = item.pos()
                start_x, start_y = self._drag_start_map_coords
                final_x, final_y = final_scene_pos.x(), -final_scene_pos.y()
                dist = math.hypot(
                    final_scene_pos.x() - self._drag_start_scene_pos.x(),
                    final_scene_pos.y() - self._drag_start_scene_pos.y(),
                )
                if dist > 1e-4:
                    self.point_moved.emit(pid, final_x, final_y, start_x, start_y)
                else:
                    item.setPos(self._drag_start_scene_pos)
            self._drag_start_scene_pos = None
            if self._interaction_mode == "move_point":
                self.setDragMode(QGraphicsView.DragMode.NoDrag)
            event.accept()
            return

        if self._interaction_mode == "move_point":
            self.setDragMode(QGraphicsView.DragMode.NoDrag)

        super().mouseReleaseEvent(event)
        if self._raster_provider and self._raster_item and self._raster_item.isVisible():
            self._raster_debounce_timer.start()

    def keyPressEvent(self, event: Any) -> None:
        """Обработка клавиш холста: отмена режима добавления/перемещения точки или измерения по Esc."""
        if event.key() == Qt.Key.Key_Escape:
            if self._interaction_mode in ("measure_distance", "measure_area"):
                self.cancel_measurement()
                event.accept()
                return

            if self._is_dragging_point and self._drag_point_id and self._drag_start_scene_pos:
                item = self._user_point_items.get(self._drag_point_id)
                if item:
                    item.setPos(self._drag_start_scene_pos)
                    pt = self._points_data.get(self._drag_point_id)
                    if pt:
                        lbl = self._user_label_items.get(self._drag_point_id)
                        if lbl:
                            half = pt.size / 2.0
                            gap = 4.0
                            lbl.setPos(
                                self._drag_start_scene_pos.x() + half + gap,
                                self._drag_start_scene_pos.y() - half,
                            )
                        halo = self._selection_halo_items.get(self._drag_point_id)
                        if halo:
                            halo.setPos(self._drag_start_scene_pos)
                self._is_dragging_point = False
                self._drag_point_id = None
                self._drag_start_scene_pos = None
                if self.viewport():
                    self.viewport().setCursor(Qt.CursorShape.ArrowCursor)
                self.move_point_mode_cancelled.emit()
                event.accept()
                return

            if self._interaction_mode == "move_point":
                self.set_interaction_mode("navigation")
                self.move_point_mode_cancelled.emit()
                event.accept()
                return

            if self._interaction_mode == "add_point":
                self.set_interaction_mode("navigation")
                self.add_point_mode_cancelled.emit()
                event.accept()
                return

        super().keyPressEvent(event)

    def leaveEvent(self, event: Any) -> None:
        """Курсор покинул область холста."""
        super().leaveEvent(event)
        self.cursor_left.emit()

    def set_interaction_mode(self, mode: str) -> None:
        """Установка режима взаимодействия с холстом."""
        old_mode = self._interaction_mode
        self._interaction_mode = mode

        # Если уходим из режима измерения, очищаем незавершенное измерение
        if old_mode in ("measure_distance", "measure_area") and mode not in ("measure_distance", "measure_area"):
            self._cancel_active_measurement(silent=False)

        if mode == "add_point":
            self.setDragMode(QGraphicsView.DragMode.NoDrag)
            if self.viewport():
                self.viewport().setCursor(Qt.CursorShape.CrossCursor)
        elif mode == "move_point":
            self.setDragMode(QGraphicsView.DragMode.NoDrag)
            if self.viewport():
                self.viewport().setCursor(Qt.CursorShape.ArrowCursor)
        elif mode in ("measure_distance", "measure_area"):
            self.setDragMode(QGraphicsView.DragMode.NoDrag)
            self.setCursor(Qt.CursorShape.CrossCursor)
            if self.viewport():
                self.viewport().setCursor(Qt.CursorShape.CrossCursor)
        else:
            self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
            self.setCursor(Qt.CursorShape.ArrowCursor)
            if self.viewport():
                self.viewport().setCursor(Qt.CursorShape.ArrowCursor)

    @property
    def interaction_mode(self) -> str:
        return self._interaction_mode

    # -------------------------------------------------------------------------
    # Этап 19: Инструменты измерений (Distance & Area)
    # -------------------------------------------------------------------------

    def _calculate_measurement_distance(self, pts: list[tuple[float, float]]) -> float:
        """Суммарное геодезическое расстояние по ломаной в метрах."""
        if len(pts) < 2:
            return 0.0
        total_m = 0.0
        active_crs = self._active_crs
        for i in range(len(pts) - 1):
            x1, y1 = pts[i][0], -pts[i][1]
            x2, y2 = pts[i + 1][0], -pts[i + 1][1]
            lon1, lat1 = CoordinateService.transform_xy(x1, y1, active_crs, "OGC:CRS84")
            lon2, lat2 = CoordinateService.transform_xy(x2, y2, active_crs, "OGC:CRS84")
            total_m += GeodesicService.calculate_distance(lon1, lat1, lon2, lat2)
        return total_m

    def _calculate_measurement_area_perimeter(self, pts: list[tuple[float, float]]) -> tuple[float, float]:
        """Геодезическая площадь (м²) и периметр (м) полигона."""
        if len(pts) < 3:
            return 0.0, 0.0
        active_crs = self._active_crs
        lons: list[float] = []
        lats: list[float] = []
        for p in pts:
            mx, my = p[0], -p[1]
            lon, lat = CoordinateService.transform_xy(mx, my, active_crs, "OGC:CRS84")
            lons.append(lon)
            lats.append(lat)
        return GeodesicService.calculate_area_perimeter(lons, lats)

    def _update_measure_preview(self) -> None:
        """Обновление графических элементов текущего незавершенного измерения."""
        for item in self._measure_active_items:
            if item.scene() == self._scene:
                self._scene.removeItem(item)
        self._measure_active_items.clear()

        all_pts = list(self._measure_points)
        if self._measure_temp_pos is not None:
            all_pts.append(self._measure_temp_pos)

        if not all_pts:
            return

        scale_x = self.transform().m11()
        scale_y = abs(self.transform().m22())
        if scale_x <= 0:
            scale_x = 1.0
        if scale_y <= 0:
            scale_y = 1.0

        line_pen = QPen(QColor("#2563EB"), 2.0, Qt.PenStyle.SolidLine)
        line_pen.setCosmetic(True)

        preview_pen = QPen(QColor("#3B82F6"), 1.5, Qt.PenStyle.DashLine)
        preview_pen.setCosmetic(True)

        # 1. Заливка полупрозрачным полигоном (для Area при >= 3 точках)
        if self._interaction_mode == "measure_area" and len(all_pts) >= 3:
            poly_path = QPainterPath()
            poly_path.moveTo(all_pts[0][0], all_pts[0][1])
            for pt in all_pts[1:]:
                poly_path.lineTo(pt[0], pt[1])
            poly_path.closeSubpath()

            poly_item = QGraphicsPathItem(poly_path)
            poly_item.setBrush(QBrush(QColor(37, 99, 235, 45)))
            poly_item.setPen(QPen(Qt.PenStyle.NoPen))
            poly_item.setZValue(115.0)
            self._scene.addItem(poly_item)
            self._measure_active_items.append(poly_item)

        # 2. Отрезки линий
        fixed_count = len(self._measure_points)
        for i in range(fixed_count - 1):
            p1 = self._measure_points[i]
            p2 = self._measure_points[i + 1]
            seg = QGraphicsLineItem(p1[0], p1[1], p2[0], p2[1])
            seg.setPen(line_pen)
            seg.setZValue(120.0)
            self._scene.addItem(seg)
            self._measure_active_items.append(seg)

        if self._measure_temp_pos is not None and fixed_count > 0:
            last_fixed = self._measure_points[-1]
            rubber = QGraphicsLineItem(last_fixed[0], last_fixed[1], self._measure_temp_pos[0], self._measure_temp_pos[1])
            rubber.setPen(preview_pen)
            rubber.setZValue(120.0)
            self._scene.addItem(rubber)
            self._measure_active_items.append(rubber)

            if self._interaction_mode == "measure_area" and fixed_count >= 2:
                first_pt = self._measure_points[0]
                close_rubber = QGraphicsLineItem(self._measure_temp_pos[0], self._measure_temp_pos[1], first_pt[0], first_pt[1])
                close_rubber.setPen(preview_pen)
                close_rubber.setZValue(120.0)
                self._scene.addItem(close_rubber)
                self._measure_active_items.append(close_rubber)

        # 3. Вершины (маркеры)
        vertex_brush = QBrush(QColor("#FFFFFF"))
        vertex_pen = QPen(QColor("#1D4ED8"), 1.5)
        vertex_pen.setCosmetic(True)
        r_scene_x = 4.0 / scale_x
        r_scene_y = 4.0 / scale_y

        for pt in self._measure_points:
            v_item = QGraphicsEllipseItem(pt[0] - r_scene_x, pt[1] - r_scene_y, r_scene_x * 2, r_scene_y * 2)
            v_item.setBrush(vertex_brush)
            v_item.setPen(vertex_pen)
            v_item.setZValue(125.0)
            self._scene.addItem(v_item)
            self._measure_active_items.append(v_item)

        # 4. Расчет и отображение подписи результата
        if self._interaction_mode == "measure_distance":
            dist_m = self._calculate_measurement_distance(all_pts)
            dist_str = GeodesicService.format_distance(dist_m)
            result_text = tr("measure.distance_result", dist=dist_str)
        else:
            area_m2, perim_m = self._calculate_measurement_area_perimeter(all_pts)
            area_str = GeodesicService.format_area(area_m2)
            perim_str = GeodesicService.format_distance(perim_m)
            result_text = tr("measure.area_result", area=area_str, perim=perim_str)

        anchor_pt = self._measure_temp_pos or (self._measure_points[-1] if self._measure_points else None)
        min_pts_for_badge = 2 if self._interaction_mode == "measure_distance" else 3
        if anchor_pt and len(all_pts) >= min_pts_for_badge:
            badge = QGraphicsSimpleTextItem(result_text)
            badge.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
            badge.setBrush(QBrush(QColor("#0F172A")))
            badge.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIgnoresTransformations, True)
            badge.setPos(anchor_pt[0] + 10.0 / scale_x, anchor_pt[1] - 18.0 / scale_y)
            badge.setZValue(130.0)
            self._scene.addItem(badge)
            self._measure_active_items.append(badge)

        self.measurement_updated.emit(result_text)

    def _finish_measurement(self) -> None:
        """Завершение текущего измерения."""
        min_pts = 2 if self._interaction_mode == "measure_distance" else 3
        if len(self._measure_points) < min_pts:
            self.cancel_measurement()
            return

        self._measure_temp_pos = None
        pts = list(self._measure_points)
        import pyproj
        transform=pyproj.Transformer.from_crs(self.active_crs,"EPSG:4326",always_xy=True)
        geometry=dict(kind="polygon" if self._interaction_mode=="measure_area" else "line",
            coordinates=[list(transform.transform(x,-y,errcheck=True)) for x,y in pts],name=tr("audit.measurement"))

        for item in self._measure_active_items:
            if item.scene() == self._scene:
                self._scene.removeItem(item)
        self._measure_active_items.clear()

        scale_x = self.transform().m11()
        scale_y = abs(self.transform().m22())
        if scale_x <= 0:
            scale_x = 1.0
        if scale_y <= 0:
            scale_y = 1.0

        line_pen = QPen(QColor("#1D4ED8"), 2.0, Qt.PenStyle.SolidLine)
        line_pen.setCosmetic(True)

        if self._interaction_mode == "measure_area" and len(pts) >= 3:
            poly_path = QPainterPath()
            poly_path.moveTo(pts[0][0], pts[0][1])
            for pt in pts[1:]:
                poly_path.lineTo(pt[0], pt[1])
            poly_path.closeSubpath()

            poly_item = QGraphicsPathItem(poly_path)
            poly_item.setBrush(QBrush(QColor(37, 99, 235, 45)))
            poly_item.setPen(line_pen)
            poly_item.setZValue(115.0)
            self._scene.addItem(poly_item)
            self._measure_completed_items.append(poly_item)

            area_m2, perim_m = self._calculate_measurement_area_perimeter(pts)
            area_str = GeodesicService.format_area(area_m2)
            perim_str = GeodesicService.format_distance(perim_m)
            final_text = tr("measure.area_result", area=area_str, perim=perim_str)
        else:
            for i in range(len(pts) - 1):
                seg = QGraphicsLineItem(pts[i][0], pts[i][1], pts[i + 1][0], pts[i + 1][1])
                seg.setPen(line_pen)
                seg.setZValue(120.0)
                self._scene.addItem(seg)
                self._measure_completed_items.append(seg)

            dist_m = self._calculate_measurement_distance(pts)
            dist_str = GeodesicService.format_distance(dist_m)
            final_text = tr("measure.distance_result", dist=dist_str)

        vertex_brush = QBrush(QColor("#FFFFFF"))
        vertex_pen = QPen(QColor("#1E3A8A"), 1.5)
        vertex_pen.setCosmetic(True)
        r_scene_x = 4.0 / scale_x
        r_scene_y = 4.0 / scale_y

        for pt in pts:
            v_item = QGraphicsEllipseItem(pt[0] - r_scene_x, pt[1] - r_scene_y, r_scene_x * 2, r_scene_y * 2)
            v_item.setBrush(vertex_brush)
            v_item.setPen(vertex_pen)
            v_item.setZValue(125.0)
            self._scene.addItem(v_item)
            self._measure_completed_items.append(v_item)

        badge = QGraphicsSimpleTextItem(final_text)
        badge.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
        badge.setBrush(QBrush(QColor("#0F172A")))
        badge.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIgnoresTransformations, True)
        badge.setPos(pts[-1][0] + 10.0 / scale_x, pts[-1][1] - 18.0 / scale_y)
        badge.setZValue(130.0)
        self._scene.addItem(badge)
        self._measure_completed_items.append(badge)

        self._measure_points.clear()
        self._measure_temp_pos = None

        self.set_interaction_mode("navigation")
        geometry["name"]=final_text
        self.measurement_geometry_finished.emit(geometry)
        self.measurement_finished.emit(final_text)

    def cancel_measurement(self) -> None:
        """Отмена текущего незавершенного измерения по Esc или переключении инструмента."""
        self._cancel_active_measurement(silent=False)

    def _cancel_active_measurement(self, silent: bool = False) -> None:
        for item in self._measure_active_items:
            if item.scene() == self._scene:
                self._scene.removeItem(item)
        self._measure_active_items.clear()
        self._measure_points.clear()
        self._measure_temp_pos = None
        if self._interaction_mode in ("measure_distance", "measure_area"):
            self._interaction_mode = "navigation"
            self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
            self.setCursor(Qt.CursorShape.ArrowCursor)
            if self.viewport():
                self.viewport().setCursor(Qt.CursorShape.ArrowCursor)
        if not silent:
            self.measurement_cancelled.emit()

    def clear_measurements(self) -> None:
        """Очистка всех измерений (активных и завершенных) с холста."""
        for item in self._measure_active_items:
            if item.scene() == self._scene:
                self._scene.removeItem(item)
        self._measure_active_items.clear()

        for item in self._measure_completed_items:
            if item.scene() == self._scene:
                self._scene.removeItem(item)
        self._measure_completed_items.clear()

        self._measure_points.clear()
        self._measure_temp_pos = None

    def has_measurements(self) -> bool:
        """Проверка наличия созданных элементов измерений."""
        return bool(self._measure_points or self._measure_completed_items or self._measure_active_items)

    @property
    def mode(self) -> str:
        """Режим взаимодействия холста."""
        if self._interaction_mode == "navigation":
            return "default"
        return self._interaction_mode

    def start_measurement(self, mode: str) -> None:
        """Запуск режима измерения ('measure_distance' или 'measure_area')."""
        self.set_interaction_mode(mode)

    def _add_measurement_vertex(self, scene_pos: QPointF | tuple[float, float]) -> None:
        """Добавление вершины измерения в координатах сцены (вспомогательный метод)."""
        if isinstance(scene_pos, QPointF):
            pt = (scene_pos.x(), scene_pos.y())
        else:
            pt = (float(scene_pos[0]), float(scene_pos[1]))
        self._measure_points.append(pt)
        self._update_measure_preview()

    @property
    def _measure_vertices(self) -> list[QPointF]:
        """Список зафиксированных вершин текущего измерения."""
        return [QPointF(p[0], p[1]) for p in self._measure_points]

    @property
    def _finished_measurements(self) -> list[QGraphicsItem]:
        """Список завершенных графических элементов измерений."""
        return self._measure_completed_items

    @property
    def _rubber_band_line(self) -> QGraphicsLineItem | None:
        """Элемент резиновой линии следующего сегмента."""
        for item in self._measure_active_items:
            if isinstance(item, QGraphicsLineItem):
                return item
        return None

    def _update_rubber_band(self, pos: QPointF) -> None:
        """Обновление позиции плавающего курсора для резиновой линии."""
        self._measure_temp_pos = (pos.x(), pos.y())
        self._update_measure_preview()

    def _calculate_current_measurement(self) -> tuple[float, float]:
        """Расчет текущих метрик (дистанция/площадь, периметр) по зафиксированным точкам."""
        if self._interaction_mode == "measure_area":
            return self._calculate_measurement_area_perimeter(self._measure_points)
        else:
            return self._calculate_measurement_distance(self._measure_points), 0.0

    # -------------------------------------------------------------------------
    # Этап 19: Масштабная линейка и координатная сетка
    # -------------------------------------------------------------------------

    def update_scale_indicator(self) -> None:
        """Обновление экранного индикатора масштаба в левом верхнем углу."""
        if not hasattr(self, "_scale_overlay"):
            return

        if not self._show_scale_indicator:
            self._scale_overlay.set_indicator_visible(False)
            return

        # Проверка наличия активной карты
        if not self._boundary_bounds and not self._layer_items and not self._raster_item and not self.is_online_map_active():
            self._scale_overlay.set_map_loaded(False)
            return

        vp = self.viewport()
        vp_w = float(vp.width()) if (vp and vp.width() > 50) else float(self.width() if self.width() > 50 else 800)
        vp_h = float(vp.height()) if (vp and vp.height() > 50) else float(self.height() if self.height() > 50 else 600)

        center_x = vp_w / 2.0
        center_y = vp_h / 2.0
        half_span_px = 60.0

        p1 = self.mapToScene(QPointF(center_x - half_span_px, center_y).toPoint())
        p2 = self.mapToScene(QPointF(center_x + half_span_px, center_y).toPoint())

        map_x1, map_y = p1.x(), -p1.y()
        map_x2 = p2.x()

        res = ScaleService.calculate_scale_for_span(
            map_x1,
            map_x2,
            map_y,
            half_span_px * 2.0,
            self._active_crs,
        )
        if res is not None:
            nice_dist, actual_px, label = res
            self._scale_overlay.set_map_loaded(True)
            self._scale_overlay.set_indicator_visible(True)
            self._scale_overlay.update_scale(label, actual_px, distance_m=nice_dist)
            self._scale_overlay.move(12, 12)
            self._scale_overlay.raise_()
        else:
            self._scale_overlay.hide()

    def set_scale_indicator_visible(self, visible: bool) -> None:
        """Включение или выключение экранного индикатора масштаба."""
        self._show_scale_indicator = visible
        if hasattr(self, "_scale_overlay"):
            self._scale_overlay.set_indicator_visible(visible)
            if visible:
                self.update_scale_indicator()

    @property
    def show_scale_indicator(self) -> bool:
        return self._show_scale_indicator

    def set_coordinate_grid_visible(self, visible: bool) -> None:
        """Включение или выключение отображения координатной сетки."""
        self._show_coordinate_grid = visible
        if visible:
            self._render_coordinate_grid()
        else:
            self._clear_coordinate_grid()

    @property
    def show_coordinate_grid(self) -> bool:
        return self._show_coordinate_grid

    def _on_scroll_changed(self) -> None:
        """Обработка смещения полос прокрутки для обновления масштаба и сетки."""
        self.update_scale_indicator()
        if self._show_coordinate_grid:
            self._grid_debounce_timer.start()
        if self.is_online_map_active():
            self._online_tile_debounce_timer.start()
        if self._labels_mode != "hidden" and self._show_points_visible:
            self._labels_debounce_timer.start()

    def _render_coordinate_grid(self) -> None:
        """Расчет и перерисовка линий и подписей координатной сетки."""
        if not self._show_coordinate_grid:
            self._clear_coordinate_grid()
            return

        if not self._boundary_bounds and not self._layer_items and not self._raster_item and not self.is_online_map_active():
            self._clear_coordinate_grid()
            return

        vp_rect = self.viewport().rect()
        if vp_rect.width() < 50 or vp_rect.height() < 50:
            vp_rect = self.rect()
            if vp_rect.width() < 50 or vp_rect.height() < 50:
                from PySide6.QtCore import QRect
                vp_rect = QRect(0, 0, 800, 600)

        visible_scene_rect = self.mapToScene(vp_rect).boundingRect()
        min_x = visible_scene_rect.left()
        max_x = visible_scene_rect.right()
        min_y = -visible_scene_rect.bottom()
        max_y = -visible_scene_rect.top()

        grid_res = GridCalculator.calculate_grid((min_x, min_y, max_x, max_y), self._active_crs)
        if grid_res is None:
            self._clear_coordinate_grid()
            return

        self._clear_coordinate_grid()
        self._grid_item_group = QGraphicsItemGroup()
        self._grid_item_group.setZValue(80.0)

        pen = QPen(QColor(148, 163, 184, 110), 1.0, Qt.PenStyle.DotLine)
        pen.setCosmetic(True)

        scale_x = self.transform().m11()
        scale_y = abs(self.transform().m22())
        if scale_x <= 0:
            scale_x = 1.0
        if scale_y <= 0:
            scale_y = 1.0

        label_font = QFont("Segoe UI", 8)

        # 1. Вертикальные линии (X / Longitude)
        for vl in grid_res.vertical_lines:
            line = QGraphicsLineItem(vl.coord, -max_y, vl.coord, -min_y)
            line.setPen(pen)
            self._grid_item_group.addToGroup(line)

            lbl_item = QGraphicsSimpleTextItem(vl.label)
            lbl_item.setFont(label_font)
            lbl_item.setBrush(QBrush(QColor("#475569")))
            lbl_item.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIgnoresTransformations, True)
            lbl_item.setPos(vl.coord + 2.0 / scale_x, -max_y + 4.0 / scale_y)
            self._grid_item_group.addToGroup(lbl_item)

        # 2. Горизонтальные линии (Y / Latitude)
        for hl in grid_res.horizontal_lines:
            line = QGraphicsLineItem(min_x, -hl.coord, max_x, -hl.coord)
            line.setPen(pen)
            self._grid_item_group.addToGroup(line)

            lbl_item = QGraphicsSimpleTextItem(hl.label)
            lbl_item.setFont(label_font)
            lbl_item.setBrush(QBrush(QColor("#475569")))
            lbl_item.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIgnoresTransformations, True)
            lbl_item.setPos(min_x + 4.0 / scale_x, -hl.coord - 12.0 / scale_y)
            self._grid_item_group.addToGroup(lbl_item)

        self._scene.addItem(self._grid_item_group)

    def _clear_coordinate_grid(self) -> None:
        """Удаление координатной сетки со сцены."""
        if self._grid_item_group is not None:
            if self._grid_item_group.scene() == self._scene:
                self._scene.removeItem(self._grid_item_group)
            self._grid_item_group = None



    def _create_controls(self) -> None:
        """Создание элементов управления поверх холста."""
        self.btn_fit = QPushButton("⛶ Показать всю карту", self)
        self.btn_fit.setObjectName("btnFitMap")
        self.btn_fit.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_fit.setStyleSheet(
            """
            QPushButton#btnFitMap {
                background-color: #FFFFFF;
                border: 1px solid #D9DDE3;
                border-radius: 4px;
                padding: 5px 10px;
                font-size: 12px;
                font-weight: 500;
                color: #202124;
            }
            QPushButton#btnFitMap:hover {
                background-color: #F1F5F9;
                border-color: #94A3B8;
            }
            QPushButton#btnFitMap:pressed {
                background-color: #E2E8F0;
            }
            """
        )
        self.btn_fit.clicked.connect(self.fit_to_view)

        # Оверлей пустого состояния холста
        self.empty_overlay = QWidget(self.viewport())
        self.empty_overlay.setObjectName("mapCanvasEmptyOverlay")
        self.empty_overlay.setStyleSheet("background-color: transparent;")

        overlay_layout = QVBoxLayout(self.empty_overlay)
        overlay_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        overlay_layout.setContentsMargins(20, 20, 20, 20)

        card = QFrame(self.empty_overlay)
        card.setObjectName("emptyStateCard")
        card.setStyleSheet(
            """
            QFrame#emptyStateCard {
                background-color: #FFFFFF;
                border: 1px solid #D9DDE3;
                border-radius: 8px;
                padding: 24px 32px;
            }
            """
        )
        card_layout = QVBoxLayout(card)
        card_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        card_layout.setSpacing(10)

        self.empty_title_lbl = QLabel("GeoPoint Mapper", card)
        self.empty_title_lbl.setStyleSheet("font-size: 20px; font-weight: bold; color: #202124;")
        self.empty_title_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        card_layout.addWidget(self.empty_title_lbl)

        self.empty_status_lbl = QLabel("Карта не загружена", card)
        self.empty_status_lbl.setStyleSheet("font-size: 14px; font-weight: 600; color: #475569;")
        self.empty_status_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        card_layout.addWidget(self.empty_status_lbl)

        self.empty_hint_lbl = QLabel("Откройте географически привязанную карту,\nчтобы начать работу.", card)
        self.empty_hint_lbl.setStyleSheet("font-size: 12px; color: #6B7280;")
        self.empty_hint_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        card_layout.addWidget(self.empty_hint_lbl)

        self.btn_open_map = QPushButton("📂  Открыть карту...", card)
        self.btn_open_map.setObjectName("btnOpenMapCanvas")
        self.btn_open_map.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_open_map.setStyleSheet(
            """
            QPushButton#btnOpenMapCanvas {
                background-color: #2563EB;
                color: #FFFFFF;
                border: none;
                border-radius: 4px;
                padding: 8px 18px;
                font-size: 13px;
                font-weight: 600;
            }
            QPushButton#btnOpenMapCanvas:hover {
                background-color: #1D4ED8;
            }
            QPushButton#btnOpenMapCanvas:pressed {
                background-color: #1E40AF;
            }
            """
        )
        card_layout.addWidget(self.btn_open_map, alignment=Qt.AlignmentFlag.AlignCenter)

        overlay_layout.addWidget(card, alignment=Qt.AlignmentFlag.AlignCenter)
        self.retranslate_ui()
        self.show_empty_state()

    def retranslate_ui(self) -> None:
        """Обновление локализованных текстов элементов холста."""
        from rme_mapper.i18n import tr

        if hasattr(self, "btn_fit"):
            self.btn_fit.setText("⛶ " + tr("action.fit_map"))
            self.btn_fit.setToolTip(tr("action.fit_map"))
        if hasattr(self, "empty_title_lbl"):
            self.empty_title_lbl.setText(tr("startup.title"))
        if hasattr(self, "empty_status_lbl"):
            self.empty_status_lbl.setText(tr("startup.no_map"))
        if hasattr(self, "empty_hint_lbl"):
            self.empty_hint_lbl.setText(tr("startup.instruction"))
        if hasattr(self, "btn_open_map"):
            self.btn_open_map.setText(tr("startup.open_map_btn"))

        if hasattr(self, "_scale_overlay") and self._scale_overlay.is_indicator_visible():
            self.update_scale_indicator()
        if self._show_coordinate_grid:
            self._render_coordinate_grid()

    def show_empty_state(self) -> None:
        """Показ экрана пустого состояния холста."""
        if hasattr(self, "empty_overlay"):
            self.empty_overlay.setVisible(True)
            self.empty_overlay.raise_()
        if hasattr(self, "btn_fit"):
            self.btn_fit.setVisible(False)
        if hasattr(self, "_scale_overlay"):
            self._scale_overlay.set_map_loaded(False)
        self._clear_coordinate_grid()

    def hide_empty_state(self) -> None:
        """Скрытие экрана пустого состояния холста при наличии загруженных данных."""
        if hasattr(self, "empty_overlay"):
            self.empty_overlay.setVisible(False)
        if hasattr(self, "btn_fit"):
            self.btn_fit.setVisible(True)
        if hasattr(self, "_scale_overlay"):
            self._scale_overlay.set_map_loaded(True)
            self.update_scale_indicator()
        if self._show_coordinate_grid:
            self._grid_debounce_timer.start()

    def clear_map_layers(self) -> None:
        """Очистка слоёв карты, растра, онлайн-подложки, сетки и границ без удаления точек."""
        self.clear_online_basemap()
        self._clear_coordinate_grid()
        if hasattr(self, "_grid_debounce_timer"):
            self._grid_debounce_timer.stop()

        for item in self._layer_items.values():
            if item.scene() == self._scene:
                self._scene.removeItem(item)
        self._layer_items.clear()

        if self._raster_item is not None:
            if self._raster_item.scene() == self._scene:
                self._scene.removeItem(self._raster_item)
            self._raster_item = None
        if self._raster_window_item is not None:
            if self._raster_window_item.scene() == self._scene:
                self._scene.removeItem(self._raster_window_item)
            self._raster_window_item = None
        self._raster_layer = None
        self._raster_affine = None
        self._raster_full_size = None
        self._raster_provider = None
        if hasattr(self, "_raster_debounce_timer"):
            self._raster_debounce_timer.stop()

        self._boundary_bounds = None
        self._initial_fit_done = False

    def clear_map(self) -> None:
        """Полная очистка карты (слои, границы, точки, зоны, растр, сетка, измерения)."""
        self.clear_measurements()
        self.clear_user_points()
        self.clear_map_layers()
        if hasattr(self, "_labels_debounce_timer"):
            self._labels_debounce_timer.stop()
        self._active_crs = "OGC:CRS84"
        if hasattr(self, "_scale_overlay"):
            self._scale_overlay.set_map_loaded(False)

        self._scene.clear()
        self.resetTransform()
        self.show_empty_state()

    # -------------------------------------------------------------------------
    # Управление слоями
    # -------------------------------------------------------------------------

    def add_layer_item(self, layer: MapLayer, gdf: gpd.GeoDataFrame) -> None:
        """Создание и добавление графического элемента слоя на сцену."""
        self.hide_empty_state()
        if layer.id in self._layer_items:
            old_item = self._layer_items.pop(layer.id)
            self._scene.removeItem(old_item)

        if gdf.empty:
            logger.warning("Слой '%s' пуст, отрисовка пропущена", layer.display_name)
            return

        style = layer.style
        border_color = style.get("border_color", "#333333")
        fill_color = style.get("fill_color")
        border_width = float(style.get("border_width", 0.0))
        point_radius = float(style.get("point_radius", 0.02))

        pen = QPen(QColor(border_color))
        pen.setWidthF(border_width)
        pen.setCosmetic(True)

        if fill_color:
            brush = QBrush(QColor(fill_color))
        else:
            brush = QBrush(Qt.BrushStyle.NoBrush)

        path = self._build_path_from_geodataframe(gdf, point_radius=point_radius)
        if path.isEmpty():
            logger.warning("Сформирован пустой путь для слоя '%s'", layer.display_name)
            return

        item = self._scene.addPath(path, pen, brush)
        item.setZValue(layer.z_order)
        item.setVisible(layer.visible)
        self._layer_items[layer.id] = item

        # Если это граница, сохраняем ее охват как эталон для fit_to_view
        if layer.role == LayerRole.BOUNDARY:
            rect = item.boundingRect()
            if rect.isValid() and not rect.isEmpty():
                self._boundary_bounds = rect
                self._scene.setSceneRect(rect)
                logger.info("Установлен эталонный охват границы карты: %s", rect)
        elif self._boundary_bounds is None:
            # Для карт без границы расширяем sceneRect по добавленным слоям
            cur_rect = self._scene.sceneRect()
            item_rect = item.boundingRect()
            if cur_rect.isEmpty() or not cur_rect.isValid():
                self._scene.setSceneRect(item_rect)
            else:
                self._scene.setSceneRect(cur_rect.united(item_rect))

        # Выполняем автоподгонку, если виджет уже отображается
        if self.viewport().width() > 100 and self.viewport().height() > 100:
            if not self._initial_fit_done:
                self.fit_to_view()

    def add_raster_item(
        self,
        layer: MapLayer,
        image_or_array: Any,
        affine_coeffs: tuple[float, ...],
        full_size: tuple[int, int],
        raster_provider: Any = None,
    ) -> None:
        """Создание и добавление графического элемента растрового слоя на сцену."""
        self.hide_empty_state()
        if layer.id in self._layer_items:
            old_item = self._layer_items.pop(layer.id)
            if old_item.scene() == self._scene:
                self._scene.removeItem(old_item)
        if self._raster_item is not None:
            if self._raster_item.scene() == self._scene:
                self._scene.removeItem(self._raster_item)
            self._raster_item = None
        if self._raster_window_item is not None:
            if self._raster_window_item.scene() == self._scene:
                self._scene.removeItem(self._raster_window_item)
            self._raster_window_item = None

        self._raster_layer = layer
        self._raster_affine = affine_coeffs
        self._raster_full_size = full_size
        self._raster_provider = raster_provider

        # Преобразование в QPixmap
        if isinstance(image_or_array, QPixmap):
            pixmap = image_or_array
        elif isinstance(image_or_array, QImage):
            pixmap = QPixmap.fromImage(image_or_array)
        elif isinstance(image_or_array, np.ndarray):
            h, w = image_or_array.shape[:2]
            c = image_or_array.shape[2] if image_or_array.ndim >= 3 else 1
            arr_contiguous = np.ascontiguousarray(image_or_array)
            qimg = QImage(arr_contiguous.data, w, h, w * 4, QImage.Format.Format_RGBA8888)
            pixmap = QPixmap.fromImage(qimg.copy())
        else:
            raise ValueError(f"Неподдерживаемый тип растрового изображения: {type(image_or_array)}")

        preview_w = pixmap.width()
        preview_h = pixmap.height()
        full_w, full_h = full_size

        sx = full_w / preview_w if preview_w > 0 else 1.0
        sy = full_h / preview_h if preview_h > 0 else 1.0

        a, b, c_aff, d, e, f_aff = affine_coeffs
        # В QGraphicsScene: scene_x = map_x, scene_y = -map_y
        # map_x = a * col + b * row + c
        # map_y = d * col + e * row + f
        # col = px * sx, row = py * sy
        # scene_x = (a * sx) * px + (b * sy) * py + c
        # scene_y = (-d * sx) * px + (-e * sy) * py - f
        # В QTransform(m11, m12, m21, m22, dx, dy):
        # x' = m11 * x + m21 * y + dx
        # y' = m12 * x + m22 * y + dy
        m11 = float(a * sx)
        m12 = float(-d * sx)
        m21 = float(b * sy)
        m22 = float(-e * sy)
        dx = float(c_aff)
        dy = float(-f_aff)

        transform = QTransform(m11, m12, m21, m22, dx, dy)

        item = QGraphicsPixmapItem(pixmap)
        item.setTransformationMode(Qt.TransformationMode.SmoothTransformation)
        item.setTransform(transform)
        item.setZValue(layer.z_order)
        item.setVisible(layer.visible)

        self._scene.addItem(item)
        self._layer_items[layer.id] = item
        self._raster_item = item

        # Настраиваем границы сцены по охвату растра
        scene_bounds = item.sceneBoundingRect()
        if scene_bounds.isValid() and not scene_bounds.isEmpty():
            self._scene.setSceneRect(scene_bounds)
            logger.info("Установлен охват сцены по растру: %s", scene_bounds)

        # Автоподгонка
        if self.viewport().width() > 100 and self.viewport().height() > 100:
            if not self._initial_fit_done:
                self.fit_to_view()

    def _on_raster_debounce_timeout(self) -> None:
        """Обновление разрешения видимого окна растра при завершении зума/панорамирования."""
        if not self._raster_provider or not self._raster_item or not self._raster_item.isVisible():
            return
        if not self.viewport():
            return

        vp_rect = self.viewport().rect()
        scene_poly = self.mapToScene(vp_rect)
        scene_rect = scene_poly.boundingRect()
        if not scene_rect.isValid() or scene_rect.isEmpty():
            return

        min_x = scene_rect.left()
        max_x = scene_rect.right()
        min_y = -scene_rect.bottom()
        max_y = -scene_rect.top()
        vp_w = max(64, self.viewport().width())
        vp_h = max(64, self.viewport().height())

        try:
            res = self._raster_provider((min_x, min_y, max_x, max_y), vp_w, vp_h)
            if res is not None:
                rgba, meta = res
                self._update_raster_window_item(rgba, meta)
        except Exception as e:
            logger.debug("Ошибка обновления растрового окна: %s", e)

    def _update_raster_window_item(self, rgba: np.ndarray, meta: dict[str, Any]) -> None:
        """Отображение высокодетализированного фрагмента растра поверх базового превью."""
        if not self._raster_item or not self._raster_item.isVisible():
            return

        h, w = rgba.shape[:2]
        arr_contiguous = np.ascontiguousarray(rgba)
        qimg = QImage(arr_contiguous.data, w, h, w * 4, QImage.Format.Format_RGBA8888)
        pixmap = QPixmap.fromImage(qimg.copy())

        win_t = meta.get("transform")
        if not win_t:
            return

        a, b, c_aff, d, e, f_aff = win_t
        m11 = float(a)
        m12 = float(-d)
        m21 = float(b)
        m22 = float(-e)
        dx = float(c_aff)
        dy = float(-f_aff)

        transform = QTransform(m11, m12, m21, m22, dx, dy)

        if self._raster_window_item is None:
            self._raster_window_item = QGraphicsPixmapItem(pixmap)
            self._raster_window_item.setTransformationMode(Qt.TransformationMode.SmoothTransformation)
            self._raster_window_item.setZValue(self._raster_item.zValue() + 0.1)
            self._scene.addItem(self._raster_window_item)
        else:
            self._raster_window_item.setPixmap(pixmap)

        self._raster_window_item.setTransform(transform)
        self._raster_window_item.setVisible(self._raster_item.isVisible())

    def set_layer_visibility(self, layer_id: str, visible: bool) -> None:
        """Мгновенное переключение видимости слоя без перезагрузки данных."""
        if layer_id in self._layer_items:
            item = self._layer_items[layer_id]
            item.setVisible(visible)
            if item == self._raster_item and self._raster_window_item:
                self._raster_window_item.setVisible(visible)
            logger.info("Видимость слоя '%s' изменена на %s", layer_id, visible)
        else:
            logger.warning("Слой '%s' не найден на сцене для изменения видимости", layer_id)

    def is_layer_visible(self, layer_id: str) -> bool:
        """Проверка текущей видимости слоя на сцене."""
        if layer_id in self._layer_items:
            return self._layer_items[layer_id].isVisible()
        return False

    def load_geodataframe(
        self,
        gdf: gpd.GeoDataFrame,
        fill_color: str = "#DCEEF8",
        border_color: str = "#2A5B84",
        border_width: float = 0.0,
    ) -> None:
        """Метод для обратной совместимости с тестами Этапа 2."""
        dummy_layer = MapLayer(
            id="default_boundary",
            source_name="default",
            display_name="Граница РМЭ",
            geometry_type="MultiPolygon",
            crs="OGC:CRS84",
            role=LayerRole.BOUNDARY,
            z_order=20,
            style={
                "fill_color": fill_color,
                "border_color": border_color,
                "border_width": border_width,
            },
        )
        self.add_layer_item(dummy_layer, gdf)

    # -------------------------------------------------------------------------
    # Пользовательские точки (Этапы 4 и 6)
    # -------------------------------------------------------------------------

    @staticmethod
    def _create_marker_path(symbol: str, size: float) -> QPainterPath:
        """Создание QPainterPath для формы маркера с центрированием в (0, 0)."""
        path = QPainterPath()
        half = size / 2.0
        sym = (symbol or "circle").strip().lower()

        if sym == "square":
            path.addRect(-half, -half, size, size)
        elif sym == "triangle":
            # Симметричный треугольник, центрированный в (0, 0)
            path.moveTo(0.0, -half)
            path.lineTo(half, half)
            path.lineTo(-half, half)
            path.closeSubpath()
        else:  # "circle" и по умолчанию
            path.addEllipse(-half, -half, size, size)

        return path

    def add_user_point(
        self,
        point: MapPoint,
        map_x: float | None = None,
        map_y: float | None = None,
        zone_polygon: Polygon | None = None,
    ) -> None:
        """Отображение пользовательской точки на холсте.

        Использует координаты активного CRS карты (map_x, map_y).
        Если они не переданы, по умолчанию используются point.longitude, point.latitude.
        Флаг ItemIgnoresTransformations сохраняет постоянный размер маркера в пикселях.
        """
        # Удаляем предыдущий элемент, если был
        # Удаляем предыдущий элемент, если был
        self.remove_user_point(point.id)

        # Сохраняем модель точки
        self._points_data[point.id] = point

        px = point.longitude if map_x is None else float(map_x)
        py = point.latitude if map_y is None else float(map_y)

        path = self._create_marker_path(point.symbol, point.size)
        item = QGraphicsPathItem(path)

        if point.stroke_width > 0:
            pen = QPen(
                QColor(point.stroke_red, point.stroke_green, point.stroke_blue),
                float(point.stroke_width),
            )
            pen.setCosmetic(True)
        else:
            pen = QPen(Qt.PenStyle.NoPen)
        item.setPen(pen)

        alpha = int(point.opacity * 255 / 100.0)
        brush = QBrush(QColor(point.red, point.green, point.blue, alpha))
        item.setBrush(brush)

        # Инвариантность к масштабу карты (размер значка постоянен на экране)
        item.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIgnoresTransformations, True)
        # Пользовательские точки располагаются поверх всех слоев
        item.setZValue(100.0)

        # Преобразование координат сцены: scene_x = map_x, scene_y = -map_y
        item.setPos(px, -py)
        item.setVisible(point.visible and self._show_points_visible and self.is_group_visible(point.group_id))

        self._scene.addItem(item)
        self._user_point_items[point.id] = item
        logger.info(
            "Пользовательская точка '%s' добавлена на карту: pos=(%s, %s), shape=%s, size=%s",
            point.name, px, -py, point.symbol, point.size,
        )
        # Синхронно добавляем/обновляем зону радиуса и подпись
        self.update_point_zone(point, zone_polygon=zone_polygon, map_coords=(px, py))
        self.update_point_label(point, px, -py)
        self._update_selection_halos()

    def add_user_points_batch(
        self,
        points_data: list[tuple[MapPoint, float, float, Any]],
    ) -> None:
        """Пакетное добавление множества пользовательских точек и зон на холст."""
        if not points_data:
            return

        self.setUpdatesEnabled(False)
        try:
            with self.defer_labels_layout():
                for point, px, py, zone_polygon in points_data:
                    self._points_data[point.id] = point
                    path = self._create_marker_path(point.symbol, point.size)
                    item = QGraphicsPathItem(path)

                    if point.stroke_width > 0:
                        pen = QPen(
                            QColor(point.stroke_red, point.stroke_green, point.stroke_blue),
                            float(point.stroke_width),
                        )
                        pen.setCosmetic(True)
                    else:
                        pen = QPen(Qt.PenStyle.NoPen)
                    item.setPen(pen)

                    alpha = int(point.opacity * 255 / 100.0)
                    brush = QBrush(QColor(point.red, point.green, point.blue, alpha))
                    item.setBrush(brush)

                    item.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIgnoresTransformations, True)
                    item.setZValue(100.0)
                    item.setPos(px, -py)
                    item.setVisible(point.visible and self._show_points_visible and self.is_group_visible(point.group_id))

                    self._scene.addItem(item)
                    self._user_point_items[point.id] = item

                    if point.zone_enabled and point.radius_m > 0:
                        self.update_point_zone(point, zone_polygon=zone_polygon, map_coords=(px, py))

                    self.update_point_label(point, px, -py)

                if self._selected_point_ids:
                    self._update_selection_halos()
        finally:
            self.setUpdatesEnabled(True)
            self.viewport().update()

    def update_user_point(
        self,
        point: MapPoint,
        map_x: float | None = None,
        map_y: float | None = None,
        zone_polygon: Polygon | None = None,
    ) -> None:
        """Мгновенное обновление маркера и зоны существующей точки без пересоздания карты."""
        self._points_data[point.id] = point
        px = point.longitude if map_x is None else float(map_x)
        py = point.latitude if map_y is None else float(map_y)

        item = self._user_point_items.get(point.id)
        if item is not None and isinstance(item, QGraphicsPathItem):
            path = self._create_marker_path(point.symbol, point.size)
            item.setPath(path)

            alpha = int(point.opacity * 255 / 100.0)
            brush = QBrush(QColor(point.red, point.green, point.blue, alpha))
            item.setBrush(brush)

            if point.stroke_width > 0:
                pen = QPen(
                    QColor(point.stroke_red, point.stroke_green, point.stroke_blue),
                    float(point.stroke_width),
                )
                pen.setCosmetic(True)
            else:
                pen = QPen(Qt.PenStyle.NoPen)
            item.setPen(pen)

            item.setPos(px, -py)
            item.setVisible(point.visible and self._show_points_visible and self.is_group_visible(point.group_id))
            logger.info(
                "Маркер точки '%s' обновлен: pos=(%s, %s), shape=%s, size=%s",
                point.name, px, -py, point.symbol, point.size,
            )
        else:
            self.add_user_point(point, map_x=px, map_y=py, zone_polygon=zone_polygon)
            return

        # Синхронно обновляем зону радиуса и подпись
        self.update_point_zone(point, zone_polygon=zone_polygon, map_coords=(px, py))
        self.update_point_label(point, px, -py)
        self._update_selection_halos()

    # -------------------------------------------------------------------------
    # Географические зоны радиуса (Этапы 7 и 9)
    # -------------------------------------------------------------------------

    @staticmethod
    def _create_zone_path_from_polygon(polygon: Polygon) -> QPainterPath:
        """Создание QPainterPath из Shapely Polygon с преобразованием y = -y."""
        path = QPainterPath()
        path.setFillRule(Qt.FillRule.OddEvenFill)
        if polygon is None or polygon.is_empty:
            return path

        exterior_coords = list(polygon.exterior.coords)
        if exterior_coords:
            path.moveTo(exterior_coords[0][0], -exterior_coords[0][1])
            for x, y in exterior_coords[1:]:
                path.lineTo(x, -y)
            path.closeSubpath()

        for interior in polygon.interiors:
            interior_coords = list(interior.coords)
            if interior_coords:
                path.moveTo(interior_coords[0][0], -interior_coords[0][1])
                for x, y in interior_coords[1:]:
                    path.lineTo(x, -y)
                path.closeSubpath()

        return path

    @staticmethod
    def _create_zone_path(longitude: float, latitude: float, radius_m: float) -> QPainterPath:
        """Создание QPainterPath для геодезической зоны радиуса в WGS84 (lon/lat)."""
        polygon = GeodesicService.create_geodesic_circle(longitude, latitude, radius_m)
        return MapCanvas._create_zone_path_from_polygon(polygon)

    def update_point_zone(
        self,
        point: MapPoint,
        zone_polygon: Polygon | None = None,
        map_coords: tuple[float, float] | None = None,
    ) -> None:
        """Отображение или обновление зоны радиуса вокруг точки в активном CRS карты.

        Зона располагается на Z=90.0 (между дорогами и маркером) и масштабируется
        вместе с картой (ItemIgnoresTransformations = False).
        """
        if not point.zone_enabled or point.radius_m <= 0 or not point.visible or not self._show_zones_visible or not self.is_group_visible(point.group_id):
            self.remove_point_zone(point.id)
            return

        if zone_polygon is not None:
            path = self._create_zone_path_from_polygon(zone_polygon)
        else:
            path = self._create_zone_path(point.longitude, point.latitude, point.radius_m)

        alpha = int(point.zone_opacity * 255 / 100.0)
        brush_color = QColor(point.zone_red, point.zone_green, point.zone_blue, alpha)
        brush = QBrush(brush_color)

        border_style_map = {
            "solid": Qt.PenStyle.SolidLine,
            "dash": Qt.PenStyle.DashLine,
            "dot": Qt.PenStyle.DotLine,
        }
        pen_style = border_style_map.get(point.zone_border_style, Qt.PenStyle.SolidLine)

        if point.zone_border_width > 0:
            pen = QPen(
                QColor(point.zone_border_red, point.zone_border_green, point.zone_border_blue),
                float(point.zone_border_width),
                pen_style,
            )
            pen.setCosmetic(True)
        else:
            pen = QPen(Qt.PenStyle.NoPen)

        item = self._user_zone_items.get(point.id)
        if item is not None and isinstance(item, QGraphicsPathItem):
            item.setPath(path)
            item.setBrush(brush)
            item.setPen(pen)
            item.setVisible(point.visible and self._show_zones_visible and self.is_group_visible(point.group_id))
        else:
            self.remove_point_zone(point.id)
            item = QGraphicsPathItem(path)
            item.setBrush(brush)
            item.setPen(pen)
            item.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIgnoresTransformations, False)
            item.setZValue(90.0)
            item.setVisible(point.visible and self._show_zones_visible and self.is_group_visible(point.group_id))
            self._scene.addItem(item)
            self._user_zone_items[point.id] = item

        logger.info(
            "Зона точки '%s' обновлена: radius=%s м, opacity=%s%%",
            point.name, point.radius_m, point.zone_opacity,
        )

    def remove_point_zone(self, point_id: str) -> None:
        """Удаление графического элемента зоны с холста."""
        if point_id in self._user_zone_items:
            item = self._user_zone_items.pop(point_id)
            if item.scene() == self._scene:
                self._scene.removeItem(item)
            logger.info("Зона точки '%s' удалена с карты", point_id)

    def has_point_zone(self, point_id: str) -> bool:
        """Проверка наличия графического элемента зоны на холсте."""
        return point_id in self._user_zone_items

    def remove_user_point(self, point_id: str) -> None:
        """Удаление пользовательской точки, ее зоны и подписи с карты."""
        self._points_data.pop(point_id, None)
        if point_id in self._selection_halo_items:
            h = self._selection_halo_items.pop(point_id)
            if h.scene() == self._scene:
                self._scene.removeItem(h)

        if point_id in self._user_point_items:
            item = self._user_point_items.pop(point_id)
            if item.scene() == self._scene:
                self._scene.removeItem(item)
            logger.info("Пользовательская точка '%s' удалена с карты", point_id)

        self.remove_point_zone(point_id)

        if point_id in self._user_label_items:
            lbl_item = self._user_label_items.pop(point_id)
            if lbl_item.scene() == self._scene:
                self._scene.removeItem(lbl_item)

        if not self._defer_label_recalc:
            self._recalculate_labels_layout()

    def clear_user_points(self) -> None:
        """Удаление всех пользовательских точек, зон и подписей с карты."""
        self.setUpdatesEnabled(False)
        try:
            self._points_data.clear()
            for item in self._selection_halo_items.values():
                if item.scene() == self._scene:
                    self._scene.removeItem(item)
            self._selection_halo_items.clear()

            for item in self._user_zone_items.values():
                if item.scene() == self._scene:
                    self._scene.removeItem(item)
            self._user_zone_items.clear()

            for item in self._user_label_items.values():
                if item.scene() == self._scene:
                    self._scene.removeItem(item)
            self._user_label_items.clear()

            for item in self._user_point_items.values():
                if item.scene() == self._scene:
                    self._scene.removeItem(item)
            self._user_point_items.clear()
            logger.info("Все пользовательские точки, зоны и подписи очищены с карты")
        finally:
            self.setUpdatesEnabled(True)
            self.viewport().update()

    def has_user_point(self, point_id: str) -> bool:
        """Проверка наличия маркера точки на холсте."""
        return point_id in self._user_point_items

    # -------------------------------------------------------------------------
    # Гало выделения (Selection Halo)
    # -------------------------------------------------------------------------

    def _update_selection_halos(self) -> None:
        """Обновление графических ореолов (halo) для выделенных точек."""
        if not self._selection_halo_items and not self._selected_point_ids:
            return

        for pid in list(self._selection_halo_items.keys()):
            if pid not in self._selected_point_ids:
                h = self._selection_halo_items.pop(pid)
                if h.scene() == self._scene:
                    self._scene.removeItem(h)

        for pid in self._selected_point_ids:
            pt = self._points_data.get(pid)
            pt_item = self._user_point_items.get(pid)
            if not pt or not pt_item or not pt.visible or not self._show_points_visible or not self.is_group_visible(pt.group_id):
                if pid in self._selection_halo_items:
                    h = self._selection_halo_items.pop(pid)
                    if h.scene() == self._scene:
                        self._scene.removeItem(h)
                continue

            halo = self._selection_halo_items.get(pid)
            if halo is None:
                halo = QGraphicsEllipseItem()
                pen = QPen(QColor("#2563EB"), 1.5, Qt.PenStyle.DashLine)
                pen.setCosmetic(True)
                halo.setPen(pen)
                halo.setBrush(QBrush(Qt.BrushStyle.NoBrush))
                halo.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIgnoresTransformations, True)
                halo.setZValue(105.0)
                self._scene.addItem(halo)
                self._selection_halo_items[pid] = halo

            r = (pt.size / 2.0) + 4.0
            halo.setRect(-r, -r, 2 * r, 2 * r)
            halo.setPos(pt_item.pos())
            halo.setVisible(True)

    # -------------------------------------------------------------------------
    # Подписи точек (Point Labels)
    # -------------------------------------------------------------------------

    def update_point_label(self, point: MapPoint, scene_x: float, scene_y: float) -> None:
        """Создание или обновление текстовой подписи точки на холсте."""
        item = self._user_label_items.get(point.id)
        if item is None:
            item = QGraphicsSimpleTextItem()
            item.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
            item.setBrush(QBrush(QColor("#1E293B")))
            item.setPen(QPen(QColor("#FFFFFF"), 0.5))
            item.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIgnoresTransformations, True)
            item.setZValue(110.0)
            self._scene.addItem(item)
            self._user_label_items[point.id] = item

        text = format_point_label(point, self._label_content_mode)
        item.setText(text)
        offset_x = (point.size / 2.0) + 4.0
        offset_y = -(point.size / 2.0)
        item.setPos(scene_x + offset_x, scene_y + offset_y)
        if not self._defer_label_recalc:
            self._recalculate_labels_layout()

    def defer_labels_layout(self):
        """Контекстный менеджер для отложенного пересчета подписей при пакетных операциях."""
        canvas_self = self

        class _DeferScope:
            def __enter__(self):
                canvas_self._defer_label_recalc = True
                return self

            def __exit__(self, exc_type, exc_val, exc_tb):
                canvas_self._defer_label_recalc = False
                canvas_self._recalculate_labels_layout()

        return _DeferScope()

    def set_labels_mode(self, mode: str) -> None:
        """Установка режима отображения подписей: 'hidden', 'selected', 'all'."""
        self._labels_mode = mode.lower() if mode.lower() in {"hidden", "selected", "all"} else "hidden"
        self._recalculate_labels_layout()

    def set_label_content_mode(self, mode: str) -> None:
        """Установка режима содержимого подписей: 'number', 'name', 'number_name'."""
        self._label_content_mode = mode.lower() if mode.lower() in {"number", "name", "number_name"} else "name"
        for pid, pt in self._points_data.items():
            lbl = self._user_label_items.get(pid)
            if lbl:
                lbl.setText(format_point_label(pt, self._label_content_mode))
        self._recalculate_labels_layout()

    @property
    def label_content_mode(self) -> str:
        return self._label_content_mode

    def update_selected_label_ids(self, selected_ids: set[str]) -> None:
        """Обновление набора выделенных ID для режима 'selected' и ореолов выделения."""
        self._selected_point_ids = set(selected_ids)
        self._update_selection_halos()
        self._recalculate_labels_layout()

    def _should_show_label(self, point_id: str, point_visible: bool) -> bool:
        if not self._show_points_visible or not point_visible:
            return False
        pt = self._points_data.get(point_id)
        if pt and not self.is_group_visible(pt.group_id):
            return False
        if self._labels_mode == "hidden":
            return False
        if self._labels_mode == "all":
            return True
        if self._labels_mode == "selected":
            return point_id in self._selected_point_ids
        return False

    def _recalculate_labels_layout(self) -> None:
        """Пересчет позиций подписей точек с предотвращением взаимного перекрытия (4 позиции)."""
        if self._defer_label_recalc:
            return

        if self._labels_mode == "hidden" or not self._show_points_visible:
            for item in self._user_label_items.values():
                if item.isVisible():
                    item.setVisible(False)
            return

        t = self.transform()
        scale_x = abs(t.m11()) if abs(t.m11()) > 1e-9 else 1.0
        scale_y = abs(t.m22()) if abs(t.m22()) > 1e-9 else 1.0

        vp = self.viewport()
        vp_w = vp.width() if vp else 0
        vp_h = vp.height() if vp else 0
        use_viewport_culling = (vp_w > 50 and vp_h > 50)

        if use_viewport_culling:
            margin = 100
            visible_scene_rect = self.mapToScene(self.viewport().rect().adjusted(-margin, -margin, margin, margin)).boundingRect()
        else:
            visible_scene_rect = None

        if self._labels_mode == "selected":
            target_ids = self._selected_point_ids
            # Скрываем подписи невыделенных точек
            for pid, item in self._user_label_items.items():
                if pid not in target_ids and item.isVisible():
                    item.setVisible(False)
            items_to_check = [(pid, self._user_label_items[pid]) for pid in target_ids if pid in self._user_label_items]
        else:
            items_to_check = list(self._user_label_items.items())

        visible_points: list[tuple[bool, str, MapPoint, QGraphicsSimpleTextItem]] = []
        for pid, item in items_to_check:
            pt = self._points_data.get(pid)
            pt_item = self._user_point_items.get(pid)
            if not pt or not pt_item:
                if item.isVisible():
                    item.setVisible(False)
                continue
            should_show = self._should_show_label(pid, pt.visible)
            if not should_show:
                if item.isVisible():
                    item.setVisible(False)
                continue

            if visible_scene_rect is not None and not visible_scene_rect.contains(pt_item.pos()):
                if item.isVisible():
                    item.setVisible(False)
                continue

            formatted_text = format_point_label(pt, self._label_content_mode)
            if not formatted_text.strip():
                item.setText(formatted_text)
                if item.isVisible():
                    item.setVisible(False)
                continue
            item.setText(formatted_text)
            is_selected = pid in self._selected_point_ids
            # Выделенные точки имеют приоритет (not is_selected == False идет первым)
            visible_points.append((not is_selected, pid, pt, item))

        visible_points.sort(key=lambda x: (x[0], x[2].name, x[1]))

        # Презентационный LOD: если в видимой области тысячи точек, ограничиваем до 2000
        MAX_CANVAS_LABELS = 2000
        if len(visible_points) > MAX_CANVAS_LABELS:
            for _, _, _, item in visible_points[MAX_CANVAS_LABELS:]:
                if item.isVisible():
                    item.setVisible(False)
            visible_points = visible_points[:MAX_CANVAS_LABELS]

        # Пространственный индекс (spatial grid) для быстрого разрешения коллизий за O(1)
        grid_cell_size = 120.0
        spatial_grid: dict[tuple[int, int], list[QRectF]] = {}

        def _get_cells(rect: QRectF) -> list[tuple[int, int]]:
            c1 = int(rect.left() // grid_cell_size)
            c2 = int(rect.right() // grid_cell_size)
            r1 = int(rect.top() // grid_cell_size)
            r2 = int(rect.bottom() // grid_cell_size)
            return [(c, r) for c in range(c1, c2 + 1) for r in range(r1, r2 + 1)]

        def _has_collision(rect: QRectF) -> bool:
            for cell in _get_cells(rect):
                for other in spatial_grid.get(cell, []):
                    if rect.intersects(other):
                        return True
            return False

        def _add_placed(rect: QRectF) -> None:
            for cell in _get_cells(rect):
                if cell not in spatial_grid:
                    spatial_grid[cell] = []
                spatial_grid[cell].append(rect)

        fm_cache: dict[QFont, QFontMetrics] = {}

        for _, pid, pt, item in visible_points:
            pt_item = self._user_point_items[pid]
            scene_pt = pt_item.pos()
            view_pt = self.mapFromScene(scene_pt)

            half = pt.size / 2.0
            gap = 4.0
            font = item.font()
            fm = fm_cache.get(font)
            if fm is None:
                fm = QFontMetrics(font)
                fm_cache[font] = fm

            text = item.text()
            w = float(fm.horizontalAdvance(text))
            h = float(fm.height())

            candidates = [
                (half + gap, -half - h * 0.75, view_pt.x() + half + gap, view_pt.y() - half - h),
                (half + gap, half, view_pt.x() + half + gap, view_pt.y() + half),
                (-half - gap - w, -half - h * 0.75, view_pt.x() - half - gap - w, view_pt.y() - half - h),
                (-half - gap - w, half, view_pt.x() - half - gap - w, view_pt.y() + half),
            ]

            chosen_pos = None
            chosen_rect = None

            for dx_px, dy_px, rx, ry in candidates:
                cand_rect = QRectF(rx, ry, w, h)
                if not _has_collision(cand_rect):
                    chosen_pos = (scene_pt.x() + (dx_px / scale_x), scene_pt.y() + (dy_px / scale_y))
                    chosen_rect = cand_rect
                    break

            if chosen_pos is None:
                dx_px, dy_px, rx, ry = candidates[0]
                chosen_pos = (scene_pt.x() + (dx_px / scale_x), scene_pt.y() + (dy_px / scale_y))
                chosen_rect = QRectF(rx, ry, w, h)

            _add_placed(chosen_rect)
            item.setPos(chosen_pos[0], chosen_pos[1])
            if not item.isVisible():
                item.setVisible(True)

    # -------------------------------------------------------------------------
    # Глобальная видимость точек и зон
    # -------------------------------------------------------------------------

    # -------------------------------------------------------------------------
    # Управление видимостью групп и глобальная видимость
    # -------------------------------------------------------------------------

    def is_group_visible(self, group_id: str | None) -> bool:
        """Проверка видимости группы. Для точек без группы (None) всегда True."""
        if group_id is None:
            return True
        return self._group_visibility.get(group_id, True)

    def set_group_visibility(self, group_id: str, visible: bool) -> None:
        """Управление видимостью группы и обновление элементов на карте."""
        self._group_visibility[group_id] = visible
        self._update_all_points_and_zones_visibility()

    def set_groups(self, groups: list[ObjectGroup]) -> None:
        """Синхронизация списка групп и их видимости."""
        self._group_visibility = {g.id: g.visible for g in groups}
        self._update_all_points_and_zones_visibility()

    def _update_all_points_and_zones_visibility(self) -> None:
        """Пересчет видимости всех маркеров, зон, подписей и ореолов с учетом групп."""
        for pid, item in self._user_point_items.items():
            pt = self._points_data.get(pid)
            if pt:
                vis = self._show_points_visible and pt.visible and self.is_group_visible(pt.group_id)
                item.setVisible(vis)

        for pid, item in self._user_zone_items.items():
            pt = self._points_data.get(pid)
            if pt:
                vis = (
                    self._show_zones_visible
                    and pt.visible
                    and pt.zone_enabled
                    and pt.radius_m > 0
                    and self.is_group_visible(pt.group_id)
                )
                item.setVisible(vis)

        self._update_selection_halos()
        self._recalculate_labels_layout()

    def set_all_points_visible(self, visible: bool) -> None:
        """Глобальное переключение видимости пользовательских точек и подписей."""
        self._show_points_visible = visible
        self._update_all_points_and_zones_visibility()

    def set_all_zones_visible(self, visible: bool) -> None:
        """Глобальное переключение видимости геодезических зон."""
        self._show_zones_visible = visible
        self._update_all_points_and_zones_visibility()

    def zoom_to_group(self, points: list[MapPoint]) -> None:
        """Приближение к экстенту точек группы в активной системе координат."""
        if not points:
            return
        active_crs = self.active_crs
        coords: list[tuple[float, float]] = []
        for pt in points:
            try:
                mx, my = CoordinateService.transform_xy(
                    pt.longitude, pt.latitude,
                    source_crs=pt.source_crs,
                    target_crs=active_crs,
                )
                coords.append((mx, my))
            except Exception as e:
                logger.warning("Ошибка пересчета координат точки '%s' для зума к группе: %s", pt.name, e)
        if coords:
            self.zoom_to_points(coords)

    @property
    def show_points_visible(self) -> bool:
        return self._show_points_visible

    @property
    def show_zones_visible(self) -> bool:
        return self._show_zones_visible

    @property
    def active_crs(self) -> str:
        return self._active_crs

    def set_active_crs(self, crs: str) -> None:
        self._active_crs = crs
        self.update_scale_indicator()
        if self._show_coordinate_grid:
            self._render_coordinate_grid()

    def add_point(self, point: MapPoint, map_x: float | None = None, map_y: float | None = None) -> None:
        """Псевдоним для add_user_point."""
        self.add_user_point(point, map_x=map_x, map_y=map_y)

    def update_point(self, point: MapPoint, map_x: float | None = None, map_y: float | None = None) -> None:
        """Псевдоним для update_user_point."""
        self.update_user_point(point, map_x=map_x, map_y=map_y)

    @property
    def _marker_items(self) -> dict[str, Any]:
        return self._user_point_items

    @property
    def _zone_items(self) -> dict[str, Any]:
        return self._user_zone_items

    # -------------------------------------------------------------------------
    # Центрирование и масштабирование
    # -------------------------------------------------------------------------

    def zoom_to_extent(self, rect: QRectF, margin_ratio: float = 0.15) -> None:
        """Масштабирование холста для отображения прямоугольного экстента."""
        if not rect.isValid() or rect.isEmpty():
            return
        pad_x = max(rect.width() * margin_ratio, 20.0)
        pad_y = max(rect.height() * margin_ratio, 20.0)
        padded = rect.adjusted(-pad_x, -pad_y, pad_x, pad_y)
        self.fitInView(padded, Qt.AspectRatioMode.KeepAspectRatio)

    def zoom_to_points(self, points: list[tuple[float, float]]) -> None:
        """Приближение и центрирование к списку координат (map_x, map_y)."""
        if not points:
            return
        if len(points) == 1:
            self.center_on_map_coordinates(points[0][0], points[0][1])
            return
        xs = [p[0] for p in points]
        ys = [p[1] for p in points]
        min_x, max_x = min(xs), max(xs)
        min_y, max_y = min(ys), max(ys)
        w = max(max_x - min_x, 10.0)
        h = max(max_y - min_y, 10.0)
        rect = QRectF(min_x, -max_y, w, h)
        self.zoom_to_extent(rect)

    def center_on_map_coordinates(
        self,
        map_x: float,
        map_y: float,
    ) -> None:
        """Центрирование карты на координатах активной системы координат карты."""
        scene_pos = QPointF(map_x, -map_y)
        self.centerOn(scene_pos)
        logger.info(
            "Карта отцентрирована на координатах: map_x=%s, map_y=%s (scene=%s)",
            map_x, map_y, scene_pos,
        )

    def center_on_coordinates(
        self,
        longitude: float,
        latitude: float,
        min_zoom: float = 350.0,
    ) -> None:
        """Центрирование карты на заданных географических координатах (обратная совместимость).

        Если текущий масштаб слишком мелкий, выполняется умеренное приближение
        для комфортного детального обзора точки.
        """
        scene_pos = QPointF(longitude, -latitude)
        self.centerOn(scene_pos)

        current_scale = self.transform().m11()
        if current_scale < min_zoom:
            factor = min_zoom / current_scale
            self.scale(factor, factor)
            logger.info("Масштаб увеличен при центрировании: x%s", factor)

        logger.info(
            "Карта отцентрирована на точке: lon=%s, lat=%s (scene=%s)",
            longitude, latitude, scene_pos,
        )

    # -------------------------------------------------------------------------
    # Вспомогательное построение геометрии
    # -------------------------------------------------------------------------

    def _build_path_from_geodataframe(
        self,
        gdf: gpd.GeoDataFrame,
        point_radius: float = 0.02,
    ) -> QPainterPath:
        """Построение высокоэффективного составного QPainterPath из всех объектов GeoDataFrame."""
        path = QPainterPath()
        path.setFillRule(Qt.FillRule.OddEvenFill)

        for geom in gdf.geometry:
            if geom is None or geom.is_empty:
                continue

            if isinstance(geom, Polygon):
                self._append_polygon(path, geom)
            elif isinstance(geom, MultiPolygon):
                for poly in geom.geoms:
                    self._append_polygon(path, poly)
            elif isinstance(geom, LineString):
                self._append_linestring(path, geom)
            elif isinstance(geom, MultiLineString):
                for line in geom.geoms:
                    self._append_linestring(path, line)
            elif isinstance(geom, Point):
                path.addEllipse(QPointF(geom.x, -geom.y), point_radius, point_radius)
            elif isinstance(geom, MultiPoint):
                for pt in geom.geoms:
                    path.addEllipse(QPointF(pt.x, -pt.y), point_radius, point_radius)

        return path

    @staticmethod
    def _append_polygon(path: QPainterPath, polygon: Polygon) -> None:
        exterior_coords = list(polygon.exterior.coords)
        if exterior_coords:
            start_x, start_y = exterior_coords[0]
            path.moveTo(start_x, -start_y)
            for x, y in exterior_coords[1:]:
                path.lineTo(x, -y)
            path.closeSubpath()

        for interior in polygon.interiors:
            interior_coords = list(interior.coords)
            if interior_coords:
                ix, iy = interior_coords[0]
                path.moveTo(ix, -iy)
                for x, y in interior_coords[1:]:
                    path.lineTo(x, -y)
                path.closeSubpath()

    @staticmethod
    def _append_linestring(path: QPainterPath, line: LineString) -> None:
        coords = list(line.coords)
        if coords:
            path.moveTo(coords[0][0], -coords[0][1])
            for x, y in coords[1:]:
                path.lineTo(x, -y)

    def fit_to_view(self) -> None:
        """Вписывание карты в окно по охвату границы Республики Марий Эл."""
        target_rect = self._boundary_bounds
        if target_rect is None or not target_rect.isValid() or target_rect.isEmpty():
            items_rect = self._scene.itemsBoundingRect()
            if items_rect.isValid() and not items_rect.isEmpty():
                target_rect = items_rect
            else:
                return

        padding_x = target_rect.width() * 0.05
        padding_y = target_rect.height() * 0.05
        padded_rect = target_rect.adjusted(-padding_x, -padding_y, padding_x, padding_y)

        self.resetTransform()
        self.fitInView(padded_rect, Qt.AspectRatioMode.KeepAspectRatio)
        self._current_zoom = 1.0
        if self.viewport().width() > 100 and self.viewport().height() > 100:
            self._initial_fit_done = True
        self.update_scale_indicator()
        if self._show_coordinate_grid:
            self._render_coordinate_grid()
        logger.debug("Выполнен fit_to_view для охвата: %s", padded_rect)

    def set_error(self, message: str) -> None:
        """Отображение сообщения об ошибке на холсте."""
        self.hide_empty_state()
        self.clear_measurements()
        self.clear_user_points()
        self.clear_map_layers()
        if hasattr(self, "_labels_debounce_timer"):
            self._labels_debounce_timer.stop()
        self._active_crs = "OGC:CRS84"
        if hasattr(self, "_scale_overlay"):
            self._scale_overlay.set_map_loaded(False)

        self._scene.clear()
        self.resetTransform()

        safe_message = html.escape(str(message))
        text_item = QGraphicsTextItem()
        text_item.setHtml(
            f"""
            <div style="text-align: center; color: #D32F2F; font-family: sans-serif;">
                <h3 style="margin-bottom: 8px;">Ошибка загрузки карты</h3>
                <p style="color: #555555; white-space: pre-line;">{safe_message}</p>
            </div>
            """
        )
        self._scene.addItem(text_item)
        rect = text_item.boundingRect()
        text_item.setPos(-rect.width() / 2, -rect.height() / 2)
        self._scene.setSceneRect(rect.adjusted(-20, -20, 20, 20))
        self.centerOn(0, 0)
        logger.warning("Холст переведен в режим ошибки: %s", message)

    def wheelEvent(self, event: QWheelEvent) -> None:
        delta = event.angleDelta().y()
        if delta == 0:
            return

        factor = self.ZOOM_IN_FACTOR if delta > 0 else self.ZOOM_OUT_FACTOR
        new_zoom = self._current_zoom * factor

        if self.MIN_ZOOM <= new_zoom <= self.MAX_ZOOM:
            self.scale(factor, factor)
            self._current_zoom = new_zoom
            if self._labels_mode != "hidden" and self._show_points_visible:
                self._labels_debounce_timer.start()
            self.update_scale_indicator()
            if self._show_coordinate_grid:
                self._grid_debounce_timer.start()
            if self._raster_provider and self._raster_item and self._raster_item.isVisible():
                self._raster_debounce_timer.start()
            if self.is_online_map_active():
                self._online_tile_debounce_timer.start()
            event.accept()
        else:
            event.ignore()

    def showEvent(self, event: QShowEvent) -> None:
        super().showEvent(event)
        if not self._initial_fit_done and (self._boundary_bounds or self._layer_items):
            self.fit_to_view()

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)

        btn_margin = 12
        btn_width = self.btn_fit.sizeHint().width()
        btn_height = self.btn_fit.sizeHint().height()
        self.btn_fit.setGeometry(
            self.width() - btn_width - btn_margin,
            btn_margin,
            btn_width,
            btn_height,
        )

        if hasattr(self, "_scale_overlay"):
            self._scale_overlay.move(12, 12)
        self._update_attribution_position()
        if hasattr(self,"_measurement_toolbar"):
            self._measurement_toolbar.adjustSize()
            self._measurement_toolbar.move(max(12,self.viewport().width()-self._measurement_toolbar.width()-12),56)
        self.update_scale_indicator()
        if self._show_coordinate_grid:
            if self._grid_item_group is None:
                self._render_coordinate_grid()
            else:
                self._grid_debounce_timer.start()

        if self.is_online_map_active():
            self._online_tile_debounce_timer.start()

        if hasattr(self, "empty_overlay"):
            self.empty_overlay.setGeometry(0, 0, self.viewport().width(), self.viewport().height())

        if not self._initial_fit_done and (self._boundary_bounds or self._layer_items):
            self.fit_to_view()

    # -------------------------------------------------------------------------
    # Этап 20: Методы управления онлайн-картой
    # -------------------------------------------------------------------------

    def is_online_map_active(self) -> bool:
        """Проверка активности онлайн-подложки."""
        return hasattr(self, "_online_tile_manager") and self._online_tile_manager.is_active

    def online_tile_manager(self) -> OnlineTileManager:
        """Получить экземпляр менеджера онлайн-тайлов."""
        return self._online_tile_manager

    @property
    def attribution_overlay(self) -> Any:
        """Получить оверлей копирайта провайдера."""
        return getattr(self, "_attribution_overlay", None)

    def set_online_basemap(self, provider: OnlineTileProvider | None, api_key: str | None = None) -> None:
        """Подключение или отключение онлайн-подложки карты."""
        if provider is None:
            self.clear_online_basemap()
            return

        self.hide_empty_state()
        self._active_crs = "EPSG:3857"
        self._online_tile_manager.set_provider(provider, api_key=api_key)
        self._attribution_overlay.set_attribution(provider.attribution)
        self._attribution_overlay.set_map_active(True)
        self._update_attribution_position()

        if hasattr(self, "_scale_overlay"):
            self._scale_overlay.set_map_loaded(True)
            self.update_scale_indicator()

        if self._show_coordinate_grid:
            self._grid_debounce_timer.start()

        self._update_online_tiles_viewport()

    def clear_online_basemap(self) -> None:
        """Отключение онлайн-подложки и скрытие оверлея атрибуции."""
        if hasattr(self, "_online_tile_debounce_timer"):
            self._online_tile_debounce_timer.stop()
        if hasattr(self, "_online_tile_manager"):
            self._online_tile_manager.clear()
            self._online_tile_manager.set_provider(None)
        if hasattr(self, "_attribution_overlay"):
            self._attribution_overlay.set_map_active(False)
            self._attribution_overlay.set_attribution("")
        has_local_map = bool(self._layer_items or self._raster_item is not None or self._boundary_bounds)
        if not has_local_map:
            self._active_crs = "OGC:CRS84"
            if hasattr(self, "_scale_overlay"):
                self._scale_overlay.set_map_loaded(False)

    def _on_online_tiles_updated(self) -> None:
        """Обработка добавления/обновления тайлов."""
        self.viewport().update()

    def _update_online_tiles_viewport(self) -> None:
        """Перерасчет видимого прямоугольника и запрос необходимых тайлов."""
        if not self.is_online_map_active():
            return
        vp = self.viewport()
        vp_w = vp.width() if vp and vp.width() > 50 else self.width()
        vp_h = vp.height() if vp and vp.height() > 50 else self.height()
        if vp_w < 50 or vp_h < 50:
            return

        top_left = self.mapToScene(0, 0)
        bottom_right = self.mapToScene(vp_w, vp_h)
        scene_rect = QRectF(top_left, bottom_right)

        scale_x = self.transform().m11()
        m_per_px = (1.0 / scale_x) if scale_x > 0 else 1.0
        self._online_tile_manager.update_viewport(scene_rect, m_per_px)

    def _update_attribution_position(self) -> None:
        """Позиционирование виджета копирайта/атрибуции в правом нижнем углу холста."""
        if hasattr(self, "_attribution_overlay") and self._attribution_overlay.is_map_active():
            attr_w = self._attribution_overlay.width()
            attr_h = self._attribution_overlay.height()
            vp_w = self.viewport().width()
            vp_h = self.viewport().height()
            self._attribution_overlay.move(
                max(0, vp_w - attr_w - 8),
                max(0, vp_h - attr_h - 8),
            )
            self._attribution_overlay.raise_()
