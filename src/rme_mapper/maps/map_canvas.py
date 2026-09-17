"""Виджет интерактивного отображения карты на базе QGraphicsView."""

import logging
from typing import Any

import geopandas as gpd
from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (
    QBrush,
    QColor,
    QPainter,
    QPainterPath,
    QPen,
    QResizeEvent,
    QShowEvent,
    QWheelEvent,
)
from PySide6.QtWidgets import (
    QGraphicsItem,
    QGraphicsPathItem,
    QGraphicsScene,
    QGraphicsTextItem,
    QGraphicsView,
    QPushButton,
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

from rme_mapper.models.map_layer import LayerRole, MapLayer

logger = logging.getLogger("rme_mapper.maps.canvas")


class MapCanvas(QGraphicsView):
    """Интерактивный холст для многослойного векторного отображения карты."""

    ZOOM_IN_FACTOR = 1.15
    ZOOM_OUT_FACTOR = 1.0 / 1.15
    MIN_ZOOM = 0.05
    MAX_ZOOM = 500.0

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("mapCanvas")

        self._scene = QGraphicsScene(self)
        self.setScene(self._scene)

        self._current_zoom = 1.0
        self._initial_fit_done = False

        # Охват административной границы РМЭ (базовый охват для fit_to_view)
        self._boundary_bounds: QRectF | None = None
        # Словарь созданных графических элементов слоев: layer_id -> QGraphicsItem
        self._layer_items: dict[str, QGraphicsItem] = {}

        self._setup_view_properties()
        self._create_controls()

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

    def _create_controls(self) -> None:
        """Создание элементов управления поверх холста."""
        self.btn_fit = QPushButton("⛶ Показать всю карту", self)
        self.btn_fit.setObjectName("btnFitMap")
        self.btn_fit.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_fit.setStyleSheet(
            """
            QPushButton {
                background-color: rgba(255, 255, 255, 0.9);
                border: 1px solid #CCCCCC;
                border-radius: 4px;
                padding: 6px 12px;
                font-size: 12px;
                font-weight: 500;
                color: #333333;
            }
            QPushButton:hover {
                background-color: #FFFFFF;
                border-color: #999999;
            }
            QPushButton:pressed {
                background-color: #E6E6E6;
            }
            """
        )
        self.btn_fit.clicked.connect(self.fit_to_view)

    def add_layer_item(self, layer: MapLayer, gdf: gpd.GeoDataFrame) -> None:
        """Создание и добавление графического элемента слоя на сцену.

        Поддерживает Polygon, MultiPolygon, LineString, MultiLineString, Point, MultiPoint.
        Преобразование: x_scene = lon, y_scene = -lat.
        """
        # Если слой уже был на сцене, удаляем старый элемент
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

        # Если это граница РМЭ, сохраняем ее охват как эталон для fit_to_view
        if layer.role == LayerRole.BOUNDARY:
            rect = item.boundingRect()
            if rect.isValid() and not rect.isEmpty():
                self._boundary_bounds = rect
                self._scene.setSceneRect(rect)
                logger.info("Установлен эталонный охват границы РМЭ: %s", rect)

        # Выполняем автоподгонку, если виджет уже отображается
        if self.viewport().width() > 100 and self.viewport().height() > 100:
            if not self._initial_fit_done:
                self.fit_to_view()

        logger.info(
            "Слой '%s' (%s) добавлен на сцену. Z=%d, Visible=%s, Bounds=%s",
            layer.display_name,
            layer.source_name,
            layer.z_order,
            layer.visible,
            item.boundingRect(),
        )

    def set_layer_visibility(self, layer_id: str, visible: bool) -> None:
        """Мгновенное переключение видимости слоя без перезагрузки данных."""
        if layer_id in self._layer_items:
            item = self._layer_items[layer_id]
            item.setVisible(visible)
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
        """Устаревший метод для обратной совместимости с тестами Этапа 2."""
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
        """Добавление полигона в составной путь с инверсией оси Y."""
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
        """Добавление линии в составной путь с инверсией оси Y."""
        coords = list(line.coords)
        if coords:
            path.moveTo(coords[0][0], -coords[0][1])
            for x, y in coords[1:]:
                path.lineTo(x, -y)

    def fit_to_view(self) -> None:
        """Вписывание карты в окно по охвату границы Республики Марий Эл."""
        # Охват рассчитывается строго по административной границе, если она есть
        target_rect = self._boundary_bounds
        if target_rect is None or not target_rect.isValid() or target_rect.isEmpty():
            items_rect = self._scene.itemsBoundingRect()
            if items_rect.isValid() and not items_rect.isEmpty():
                target_rect = items_rect
            else:
                return

        # Добавляем 5% отступ вокруг границы
        padding_x = target_rect.width() * 0.05
        padding_y = target_rect.height() * 0.05
        padded_rect = target_rect.adjusted(-padding_x, -padding_y, padding_x, padding_y)

        self.resetTransform()
        self.fitInView(padded_rect, Qt.AspectRatioMode.KeepAspectRatio)
        self._current_zoom = 1.0
        if self.viewport().width() > 100 and self.viewport().height() > 100:
            self._initial_fit_done = True
        logger.debug("Выполнен fit_to_view для охвата: %s", padded_rect)

    def set_error(self, message: str) -> None:
        """Отображение сообщения об ошибке на холсте."""
        self._scene.clear()
        self._boundary_bounds = None
        self._layer_items.clear()
        self.resetTransform()

        text_item = QGraphicsTextItem()
        text_item.setHtml(
            f"""
            <div style="text-align: center; color: #D32F2F; font-family: sans-serif;">
                <h3 style="margin-bottom: 8px;">Ошибка загрузки карты</h3>
                <p style="color: #555555; white-space: pre-line;">{message}</p>
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
        """Обработка масштабирования карты колесиком мыши."""
        delta = event.angleDelta().y()
        if delta == 0:
            return

        factor = self.ZOOM_IN_FACTOR if delta > 0 else self.ZOOM_OUT_FACTOR
        new_zoom = self._current_zoom * factor

        if self.MIN_ZOOM <= new_zoom <= self.MAX_ZOOM:
            self.scale(factor, factor)
            self._current_zoom = new_zoom
            event.accept()
        else:
            event.ignore()

    def showEvent(self, event: QShowEvent) -> None:
        """Обработка первого показа виджета на экране."""
        super().showEvent(event)
        if not self._initial_fit_done and (self._boundary_bounds or self._layer_items):
            self.fit_to_view()

    def resizeEvent(self, event: QResizeEvent) -> None:
        """Обработка изменения размера окна: перепозиционирование кнопки и автоподгонка."""
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

        if not self._initial_fit_done and (self._boundary_bounds or self._layer_items):
            self.fit_to_view()
