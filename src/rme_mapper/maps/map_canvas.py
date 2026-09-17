"""Виджет отображения карты на базе QGraphicsView."""

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
from shapely.geometry import MultiPolygon, Polygon

logger = logging.getLogger("rme_mapper.maps.canvas")


class MapCanvas(QGraphicsView):
    """Интерактивный холст для векторного отображения карты."""

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
        self._layer_bounds: QRectF | None = None

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

    def load_geodataframe(
        self,
        gdf: gpd.GeoDataFrame,
        fill_color: str = "#DCEEF8",
        border_color: str = "#2A5B84",
        border_width: float = 0.0,
    ) -> None:
        """Отрисовка полигональной геометрии из GeoDataFrame.

        Координатная привязка:
            x_scene = longitude
            y_scene = -latitude (инверсия для соответствия экранной оси Y Qt).
        """
        self._scene.clear()
        self._initial_fit_done = False
        self._current_zoom = 1.0

        if gdf.empty:
            logger.warning("Передан пустой GeoDataFrame для отрисовки")
            self.set_error("Нет данных для отображения")
            return

        pen = QPen(QColor(border_color))
        # Ширина 0 в Qt означает косметическое перо (всегда 1 пиксель независимо от масштаба)
        pen.setWidthF(border_width)
        pen.setCosmetic(True)

        brush = QBrush(QColor(fill_color))

        total_features = 0

        for geom in gdf.geometry:
            if geom is None or geom.is_empty:
                continue

            if isinstance(geom, Polygon):
                path = self._polygon_to_path(geom)
                self._scene.addPath(path, pen, brush)
                total_features += 1
            elif isinstance(geom, MultiPolygon):
                for poly in geom.geoms:
                    path = self._polygon_to_path(poly)
                    self._scene.addPath(path, pen, brush)
                total_features += 1

        items_rect = self._scene.itemsBoundingRect()
        if items_rect.isValid() and not items_rect.isEmpty():
            self._layer_bounds = items_rect
            self._scene.setSceneRect(items_rect)
            logger.info(
                "Геометрия загружена на холст. Объектов: %d, охват сцены: %s",
                total_features,
                items_rect,
            )
            # Вписываем карту в видимую область, если виджет уже имеет реальные размеры
            if self.viewport().width() > 100 and self.viewport().height() > 100:
                self.fit_to_view()
        else:
            logger.warning("Охват сцены невалиден после загрузки объектов")

    @staticmethod
    def _polygon_to_path(polygon: Polygon) -> QPainterPath:
        """Преобразование полигона Shapely в QPainterPath с учетом инверсии Y."""
        path = QPainterPath()
        path.setFillRule(Qt.FillRule.OddEvenFill)

        # Внешний контур (Exterior)
        exterior_coords = list(polygon.exterior.coords)
        if exterior_coords:
            start_x, start_y = exterior_coords[0]
            path.moveTo(start_x, -start_y)
            for x, y in exterior_coords[1:]:
                path.lineTo(x, -y)
            path.closeSubpath()

        # Внутренние отверстия (Interiors)
        for interior in polygon.interiors:
            interior_coords = list(interior.coords)
            if interior_coords:
                ix, iy = interior_coords[0]
                path.moveTo(ix, -iy)
                for x, y in interior_coords[1:]:
                    path.lineTo(x, -y)
                path.closeSubpath()

        return path

    def fit_to_view(self) -> None:
        """Вписывание всей карты в окно с сохранением географических пропорций."""
        if self._layer_bounds is None or not self._layer_bounds.isValid():
            items_rect = self._scene.itemsBoundingRect()
            if items_rect.isValid() and not items_rect.isEmpty():
                self._layer_bounds = items_rect
            else:
                return

        # Добавляем 5% отступ вокруг границ для эстетичного отображения
        padding_x = self._layer_bounds.width() * 0.05
        padding_y = self._layer_bounds.height() * 0.05
        padded_rect = self._layer_bounds.adjusted(
            -padding_x, -padding_y, padding_x, padding_y
        )

        self.resetTransform()
        self.fitInView(padded_rect, Qt.AspectRatioMode.KeepAspectRatio)
        self._current_zoom = 1.0
        if self.viewport().width() > 100 and self.viewport().height() > 100:
            self._initial_fit_done = True
        logger.debug("Выполнен fit_to_view для охвата: %s", padded_rect)

    def set_error(self, message: str) -> None:
        """Отображение сообщения об ошибке на холсте."""
        self._scene.clear()
        self._layer_bounds = None
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
        if not self._initial_fit_done and self._layer_bounds is not None:
            self.fit_to_view()

    def resizeEvent(self, event: QResizeEvent) -> None:
        """Обработка изменения размера окна: перепозиционирование кнопки и автоподгонка."""
        super().resizeEvent(event)

        # Перемещаем кнопку 'Показать всю карту' в правый верхний угол
        btn_margin = 12
        btn_width = self.btn_fit.sizeHint().width()
        btn_height = self.btn_fit.sizeHint().height()
        self.btn_fit.setGeometry(
            self.width() - btn_width - btn_margin,
            btn_margin,
            btn_width,
            btn_height,
        )

        # Если холст отображается впервые, выполняем автоподгонку
        if not self._initial_fit_done and self._layer_bounds is not None:
            self.fit_to_view()
