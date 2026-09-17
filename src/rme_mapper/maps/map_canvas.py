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
    QFrame,
    QGraphicsEllipseItem,
    QGraphicsItem,
    QGraphicsPathItem,
    QGraphicsScene,
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

from rme_mapper.models.map_layer import LayerRole, MapLayer
from rme_mapper.models.map_point import MapPoint
from rme_mapper.services.geodesic_service import GeodesicService

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
        # Словарь графических элементов пользовательских точек: point_id -> QGraphicsItem
        self._user_point_items: dict[str, QGraphicsItem] = {}
        # Словарь графических элементов зон радиуса: point_id -> QGraphicsItem
        self._user_zone_items: dict[str, QGraphicsItem] = {}

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
                border: 1px solid #CBD5E1;
                border-radius: 12px;
                padding: 24px 32px;
            }
            """
        )
        card_layout = QVBoxLayout(card)
        card_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        card_layout.setSpacing(10)

        self.empty_title_lbl = QLabel("GeoPoint Mapper", card)
        self.empty_title_lbl.setStyleSheet("font-size: 20px; font-weight: bold; color: #1E293B;")
        self.empty_title_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        card_layout.addWidget(self.empty_title_lbl)

        self.empty_status_lbl = QLabel("Карта не загружена", card)
        self.empty_status_lbl.setStyleSheet("font-size: 14px; font-weight: 600; color: #475569;")
        self.empty_status_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        card_layout.addWidget(self.empty_status_lbl)

        self.empty_hint_lbl = QLabel("Откройте географически привязанную карту,\nчтобы начать работу.", card)
        self.empty_hint_lbl.setStyleSheet("font-size: 12px; color: #64748B;")
        self.empty_hint_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        card_layout.addWidget(self.empty_hint_lbl)

        self.btn_open_map = QPushButton("📂  Открыть карту...", card)
        self.btn_open_map.setObjectName("btnOpenMapCanvas")
        self.btn_open_map.setCursor(Qt.CursorShape.PointingHandCursor)
        self.retranslate_ui()

        self.btn_open_map.setStyleSheet(
            """
            QPushButton#btnOpenMapCanvas {
                background-color: #2563EB;
                color: #FFFFFF;
                border: none;
                border-radius: 6px;
                padding: 10px 20px;
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
        if hasattr(self, "empty_title_lbl"):
            self.empty_title_lbl.setText(tr("startup.title"))
        if hasattr(self, "empty_status_lbl"):
            self.empty_status_lbl.setText(tr("startup.no_map"))
        if hasattr(self, "empty_hint_lbl"):
            self.empty_hint_lbl.setText(tr("startup.instruction"))
        if hasattr(self, "btn_open_map"):
            self.btn_open_map.setText(tr("startup.open_map_btn"))

    def show_empty_state(self) -> None:

        """Показ экрана пустого состояния холста."""
        if hasattr(self, "empty_overlay"):
            self.empty_overlay.setVisible(True)
            self.empty_overlay.raise_()
        if hasattr(self, "btn_fit"):
            self.btn_fit.setVisible(False)

    def hide_empty_state(self) -> None:
        """Скрытие экрана пустого состояния холста при наличии загруженных данных."""
        if hasattr(self, "empty_overlay"):
            self.empty_overlay.setVisible(False)
        if hasattr(self, "btn_fit"):
            self.btn_fit.setVisible(True)

    def clear_map(self) -> None:
        """Полная очистка карты (слои, границы, точки, зоны)."""
        self.clear_user_points()
        for item in self._layer_items.values():
            self._scene.removeItem(item)
        self._layer_items.clear()
        self._boundary_bounds = None
        self._scene.clear()
        self.resetTransform()
        self._initial_fit_done = False
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
        self.remove_user_point(point.id)

        px = point.longitude if map_x is None else float(map_x)
        py = point.latitude if map_y is None else float(map_y)

        path = self._create_marker_path(point.symbol, point.size)
        item = QGraphicsPathItem(path)

        pen = QPen(QColor("#FFFFFF"))
        pen.setWidthF(1.5)
        pen.setCosmetic(True)
        item.setPen(pen)

        brush = QBrush(QColor(point.red, point.green, point.blue))
        item.setBrush(brush)

        # Инвариантность к масштабу карты (размер значка постоянен на экране)
        item.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIgnoresTransformations, True)
        # Пользовательские точки располагаются поверх всех слоев
        item.setZValue(100.0)

        # Преобразование координат сцены: scene_x = map_x, scene_y = -map_y
        item.setPos(px, -py)
        item.setVisible(point.visible)

        self._scene.addItem(item)
        self._user_point_items[point.id] = item
        logger.info(
            "Пользовательская точка '%s' добавлена на карту: pos=(%s, %s), shape=%s, size=%s",
            point.name, px, -py, point.symbol, point.size,
        )
        # Синхронно добавляем/обновляем зону радиуса
        self.update_point_zone(point, zone_polygon=zone_polygon, map_coords=(px, py))

    def update_user_point(
        self,
        point: MapPoint,
        map_x: float | None = None,
        map_y: float | None = None,
        zone_polygon: Polygon | None = None,
    ) -> None:
        """Мгновенное обновление маркера и зоны существующей точки без пересоздания карты."""
        px = point.longitude if map_x is None else float(map_x)
        py = point.latitude if map_y is None else float(map_y)

        item = self._user_point_items.get(point.id)
        if item is not None and isinstance(item, QGraphicsPathItem):
            path = self._create_marker_path(point.symbol, point.size)
            item.setPath(path)

            brush = QBrush(QColor(point.red, point.green, point.blue))
            item.setBrush(brush)

            item.setPos(px, -py)
            item.setVisible(point.visible)
            logger.info(
                "Маркер точки '%s' обновлен: pos=(%s, %s), shape=%s, size=%s",
                point.name, px, -py, point.symbol, point.size,
            )
        else:
            self.add_user_point(point, map_x=px, map_y=py, zone_polygon=zone_polygon)
            return

        # Синхронно обновляем зону радиуса
        self.update_point_zone(point, zone_polygon=zone_polygon, map_coords=(px, py))

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
        if not point.zone_enabled or point.radius_m <= 0 or not point.visible:
            self.remove_point_zone(point.id)
            return

        if zone_polygon is not None:
            path = self._create_zone_path_from_polygon(zone_polygon)
        else:
            path = self._create_zone_path(point.longitude, point.latitude, point.radius_m)

        alpha = int(point.zone_opacity * 255 / 100.0)
        brush_color = QColor(point.zone_red, point.zone_green, point.zone_blue, alpha)
        brush = QBrush(brush_color)

        pen_color = QColor(point.zone_red, point.zone_green, point.zone_blue, max(180, alpha))
        pen = QPen(pen_color, 1.5)
        pen.setCosmetic(True)

        item = self._user_zone_items.get(point.id)
        if item is not None and isinstance(item, QGraphicsPathItem):
            item.setPath(path)
            item.setBrush(brush)
            item.setPen(pen)
            item.setVisible(point.visible)
        else:
            self.remove_point_zone(point.id)
            item = QGraphicsPathItem(path)
            item.setBrush(brush)
            item.setPen(pen)
            item.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIgnoresTransformations, False)
            item.setZValue(90.0)
            item.setVisible(point.visible)
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
            self._scene.removeItem(item)
            logger.info("Зона точки '%s' удалена с карты", point_id)

    def has_point_zone(self, point_id: str) -> bool:
        """Проверка наличия графического элемента зоны на холсте."""
        return point_id in self._user_zone_items

    def remove_user_point(self, point_id: str) -> None:
        """Удаление пользовательской точки и ее зоны с карты."""
        if point_id in self._user_point_items:
            item = self._user_point_items.pop(point_id)
            self._scene.removeItem(item)
            logger.info("Пользовательская точка '%s' удалена с карты", point_id)

        self.remove_point_zone(point_id)

    def clear_user_points(self) -> None:
        """Удаление всех пользовательских точек и зон с карты."""
        for item in self._user_zone_items.values():
            self._scene.removeItem(item)
        self._user_zone_items.clear()

        for item in self._user_point_items.values():
            self._scene.removeItem(item)
        self._user_point_items.clear()
        logger.info("Все пользовательские точки и зоны очищены с карты")

    def has_user_point(self, point_id: str) -> bool:
        """Проверка наличия маркера точки на холсте."""
        return point_id in self._user_point_items

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
        logger.debug("Выполнен fit_to_view для охвата: %s", padded_rect)

    def set_error(self, message: str) -> None:
        """Отображение сообщения об ошибке на холсте."""
        self._scene.clear()
        self._boundary_bounds = None
        self._layer_items.clear()
        self._user_point_items.clear()
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

        if hasattr(self, "empty_overlay"):
            self.empty_overlay.setGeometry(0, 0, self.viewport().width(), self.viewport().height())

        if not self._initial_fit_done and (self._boundary_bounds or self._layer_items):
            self.fit_to_view()
