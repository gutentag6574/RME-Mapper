"""Интерактивный диалог ручной геопривязки изображений по контрольным точкам (GeoreferenceDialog)."""
from __future__ import annotations


import logging
import math
from pathlib import Path
from typing import Any

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import (
    QBrush,
    QColor,
    QCursor,
    QFont,
    QImage,
    QKeySequence,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
    QTransform,
)
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QFrame,
    QGraphicsEllipseItem,
    QGraphicsItem,
    QGraphicsPixmapItem,
    QGraphicsScene,
    QGraphicsSimpleTextItem,
    QGraphicsView,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSplitter,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)
import pyproj

from rme_mapper.i18n import tr
from rme_mapper.ui.crs_picker import CrsPicker
from rme_mapper.models.georeference import ControlPoint, MAX_CONTROL_POINTS
from rme_mapper.services.georeference_service import GeoreferenceService

logger = logging.getLogger("rme_mapper.ui.georeference_dialog")

# Цветовая палитра маркеров
COLOR_MARKER_DEFAULT = QColor(250, 204, 21)       # Желтый (contrast #FACC15)
COLOR_MARKER_BORDER = QColor(15, 23, 42)          # Темно-синий (#0F172A)
COLOR_MARKER_SELECTED = QColor(239, 68, 68)       # Красный (#EF4444)
COLOR_MARKER_DISABLED = QColor(148, 163, 184)     # Серый (#94A3B8)


class ControlPointMarkerItem(QGraphicsItem):
    """Графический маркер контрольной точки на изображении."""

    def __init__(
        self,
        point: ControlPoint,
        scale_to_full: float = 1.0,
        parent: QGraphicsItem | None = None,
    ) -> None:
        super().__init__(parent)
        self.point = point
        self.scale_to_full = scale_to_full if scale_to_full > 0 else 1.0

        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, True)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable, True)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges, True)
        self.setAcceptHoverEvents(True)
        self.setZValue(100.0)

        # Пересчет координат полного растра в координаты превью-сцены
        sc_x = point.pixel_x / self.scale_to_full
        sc_y = point.pixel_y / self.scale_to_full
        self.setPos(sc_x, sc_y)

    def boundingRect(self) -> QRectF:
        r = 18.0
        return QRectF(-r, -r, 2 * r + 24.0, 2 * r)

    def paint(self, painter: QPainter, option: Any, widget: Any = None) -> None:
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        is_sel = self.isSelected()
        is_en = self.point.enabled

        if not is_en:
            fill_color = COLOR_MARKER_DISABLED
        elif is_sel:
            fill_color = COLOR_MARKER_SELECTED
        else:
            fill_color = COLOR_MARKER_DEFAULT

        # Внешний кружок
        pen = QPen(COLOR_MARKER_BORDER, 2.0)
        painter.setPen(pen)
        painter.setBrush(QBrush(fill_color))
        painter.drawEllipse(QPointF(0, 0), 8.0, 8.0)

        # Перекрестие в центре
        painter.drawLine(QPointF(-4.0, 0), QPointF(4.0, 0))
        painter.drawLine(QPointF(0, -4.0), QPointF(0, 4.0))

        # Текстовый номер точки
        label = self.point.name or str(self.point.id)[:3]
        painter.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
        painter.setPen(COLOR_MARKER_BORDER)
        painter.drawText(QPointF(11.0, 4.0), label)

        painter.restore()

    def itemChange(self, change: QGraphicsItem.GraphicsItemChange, value: Any) -> Any:
        if change == QGraphicsItem.GraphicsItemChange.ItemPositionChange and self.scene():
            new_pos = value
            # Обновляем координаты полного изображения
            self.point.pixel_x = float(new_pos.x() * self.scale_to_full)
            self.point.pixel_y = float(new_pos.y() * self.scale_to_full)
        return super().itemChange(change, value)


class GeoreferenceImageView(QGraphicsView):
    """Интерактивный холст для просмотра изображения и установки контрольных точек."""

    point_placed = Signal(float, float)     # pixel_x, pixel_y в координатах полного растра
    point_moved = Signal(ControlPoint)      # обновлена контрольная точка
    point_selected = Signal(str)            # point_id

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._scene = QGraphicsScene(self)
        self.setScene(self._scene)

        self._pixmap_item: QGraphicsPixmapItem | None = None
        self._scale_x: float = 1.0
        self._scale_y: float = 1.0
        self._full_w: int = 0
        self._full_h: int = 0

        self._markers: dict[str, ControlPointMarkerItem] = {}
        self._is_adding_point: bool = False

        self.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setBackgroundBrush(QBrush(QColor(30, 41, 59)))  # Dark slate #1E293B

    def set_image(self, qimage: QImage, full_size: tuple[int, int]) -> None:
        """Установка превью-изображения на холст."""
        self._scene.clear()
        self._markers.clear()

        pix = QPixmap.fromImage(qimage)
        self._pixmap_item = self._scene.addPixmap(pix)
        self._pixmap_item.setZValue(0)

        self._full_w, self._full_h = full_size
        prev_w = pix.width()
        prev_h = pix.height()

        self._scale_x = self._full_w / prev_w if prev_w > 0 else 1.0
        self._scale_y = self._full_h / prev_h if prev_h > 0 else 1.0

        self.setSceneRect(0, 0, prev_w, prev_h)
        self.fit_to_view()

    def fit_to_view(self) -> None:
        """Вписать изображение в видимую область холста."""
        if self._pixmap_item is not None:
            self.fitInView(self._pixmap_item, Qt.AspectRatioMode.KeepAspectRatio)

    def set_adding_point_mode(self, enabled: bool) -> None:
        """Включение/выключение режима клика для добавления точки."""
        self._is_adding_point = enabled
        if enabled:
            self.setCursor(Qt.CursorShape.CrossCursor)
        else:
            self.setCursor(Qt.CursorShape.ArrowCursor)

    def sync_markers(self, points: list[ControlPoint], selected_id: str | None = None) -> None:
        """Синхронизация маркеров на изображении с текущим списком точек."""
        current_ids = {p.id for p in points}
        # Удаляем устаревшие
        for pid in list(self._markers.keys()):
            if pid not in current_ids:
                item = self._markers.pop(pid)
                if item.scene() == self._scene:
                    self._scene.removeItem(item)

        # Создаем или обновляем маркеры
        for pt in points:
            if pt.id in self._markers:
                marker = self._markers[pt.id]
                marker.point = pt
                marker.scale_to_full = self._scale_x
                sc_x = pt.pixel_x / self._scale_x
                sc_y = pt.pixel_y / self._scale_y
                if (QPointF(sc_x, sc_y) - marker.pos()).manhattanLength() > 0.1:
                    marker.setPos(sc_x, sc_y)
                marker.setSelected(pt.id == selected_id)
                marker.update()
            else:
                marker = ControlPointMarkerItem(pt, scale_to_full=self._scale_x)
                marker.setSelected(pt.id == selected_id)
                self._scene.addItem(marker)
                self._markers[pt.id] = marker

    def wheelEvent(self, event: Any) -> None:
        """Плавный зум колесом мыши."""
        delta = event.angleDelta().y()
        if delta == 0:
            return
        factor = 1.25 if delta > 0 else 0.8
        self.scale(factor, factor)

    def mousePressEvent(self, event: Any) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self._is_adding_point:
            scene_pos = self.mapToScene(event.pos())
            # Проверяем, что клик внутри границ изображения
            if self._pixmap_item and self._pixmap_item.contains(scene_pos):
                pixel_x = float(scene_pos.x() * self._scale_x)
                pixel_y = float(scene_pos.y() * self._scale_y)
                # Ограничение габаритами
                pixel_x = max(0.0, min(pixel_x, float(self._full_w)))
                pixel_y = max(0.0, min(pixel_y, float(self._full_h)))
                self.point_placed.emit(pixel_x, pixel_y)
                event.accept()
                return

        super().mousePressEvent(event)

        # Проверяем кликнутый маркер для синхронизации с таблицей
        item = self.itemAt(event.pos())
        if isinstance(item, ControlPointMarkerItem):
            self.point_selected.emit(item.point.id)

    def mouseReleaseEvent(self, event: Any) -> None:
        super().mouseReleaseEvent(event)
        item = self.itemAt(event.pos())
        if isinstance(item, ControlPointMarkerItem):
            self.point_moved.emit(item.point)


class GeoreferenceDialog(QDialog):
    """Полнофункциональный диалог ручной геопривязки изображений (Stage 21)."""

    def __init__(
        self,
        image_path: Path | str,
        existing_points: list[dict[str, Any]] | list[ControlPoint] | None = None,
        existing_crs: str | None = None,
        parent: QWidget | None = None,
        existing_affine: list[float] | tuple[float, ...] | None = None,
    ) -> None:
        super().__init__(parent)
        self.image_path = GeoreferenceService.resolve_image_path(image_path)
        binding = GeoreferenceService.read_world_file(image_path) if existing_points is None and existing_affine is None else None
        if binding is None and existing_points is None and existing_affine is None and self.image_path.suffix.lower() in (".tif", ".tiff"):
            from rme_mapper.backends import BackendFactory, get_raster_backend
            if BackendFactory.supports_geotiff():
                info = get_raster_backend().inspect_raster(self.image_path)
                if info.get("is_valid_georef"):
                    binding = {"affine": info["transform"], "crs": info["crs"]}
        self._imported_affine = tuple(existing_affine) if existing_affine is not None else (binding["affine"] if binding else None)
        if binding and existing_crs is None:
            existing_crs = binding["crs"] or ""
        self.setWindowTitle(f"{tr('dialog.georef.title')} — {self.image_path.name}")
        self.resize(1100, 720)
        self.setMinimumSize(850, 560)
        self.setModal(True)

        self._image_info: dict[str, Any] = {}
        self._full_size: tuple[int, int] = (0, 0)
        self._control_points: list[ControlPoint] = []
        self._active_crs: str = existing_crs if existing_crs is not None else ""
        self._current_affine: tuple[float, float, float, float, float, float] | None = None
        self._current_rmse: float = 0.0

        # Построение контрольных точек из переданных данных
        if existing_points:
            for pt in existing_points:
                if isinstance(pt, ControlPoint):
                    self._control_points.append(pt)
                elif isinstance(pt, dict):
                    self._control_points.append(ControlPoint.from_dict(pt))

        self._setup_ui()
        self._load_image()
        self._update_crs_ui()
        self._populate_table()
        self._recalculate()
        self._update_step_ui()

    def _setup_ui(self) -> None:
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(12, 12, 12, 12)
        main_layout.setSpacing(10)

        # Верхний сплиттер (слева изображение, справа панель привязки)
        splitter = QSplitter(Qt.Orientation.Horizontal, self)

        # --- Левая панель: Изображение и панель навигации ---
        left_widget = QWidget(splitter)
        left_layout = QVBoxLayout(left_widget)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(6)

        # Тулбар изображения
        img_toolbar = QHBoxLayout()
        self.btn_add_pt = QPushButton(tr("dialog.georef.add_point"), left_widget)
        self.btn_add_pt.setCheckable(True)
        self.btn_add_pt.setStyleSheet("font-weight: bold; padding: 6px 12px;")
        self.btn_add_pt.toggled.connect(self._on_add_point_toggled)
        img_toolbar.addWidget(self.btn_add_pt)

        self.btn_fit = QPushButton(tr("dialog.georef.fit"), left_widget)
        self.btn_fit.clicked.connect(lambda: self.image_view.fit_to_view())
        img_toolbar.addWidget(self.btn_fit)

        self.lbl_cursor_coords = QLabel("X: — | Y: —", left_widget)
        self.lbl_cursor_coords.setStyleSheet("color: #64748B; font-family: monospace;")
        img_toolbar.addStretch()
        img_toolbar.addWidget(self.lbl_cursor_coords)

        left_layout.addLayout(img_toolbar)

        # Холст изображения
        self.image_view = GeoreferenceImageView(left_widget)
        self.image_view.point_placed.connect(self._on_point_placed_on_image)
        self.image_view.point_moved.connect(self._on_marker_moved)
        self.image_view.point_selected.connect(self._on_marker_selected)
        left_layout.addWidget(self.image_view, stretch=1)

        splitter.addWidget(left_widget)

        # --- Правая панель: CRS, таблица точек, метрики ошибки ---
        right_widget = QWidget(splitter)
        right_layout = QVBoxLayout(right_widget)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(10)

        # 1. Выбор CRS
        crs_group = QFrame(right_widget)
        crs_group.setStyleSheet("background: #F8FAFC; border: 1px solid #E2E8F0; border-radius: 6px; padding: 8px;")
        crs_layout = QVBoxLayout(crs_group)
        crs_layout.setSpacing(6)

        crs_title_row = QHBoxLayout()
        lbl_crs = QLabel(tr("dialog.georef.crs"), crs_group)
        lbl_crs.setStyleSheet("font-weight: bold; color: #1E293B;")
        crs_title_row.addWidget(lbl_crs)

        self.crs_combo = QComboBox(crs_group)
        self.crs_combo.addItem("WGS 84 (EPSG:4326)", "EPSG:4326")
        self.crs_combo.addItem("Web Mercator (EPSG:3857)", "EPSG:3857")
        self.crs_combo.addItem("WGS 84 / UTM zone 39N (EPSG:32639)", "EPSG:32639")
        self.crs_combo.addItem(tr("dialog.georef.pulkovo_crs"), "EPSG:28407")
        self.crs_combo.addItem(tr("dialog.georef.custom_crs"), "custom")
        crs_index = self.crs_combo.findData(self._active_crs)
        self.crs_combo.setCurrentIndex(crs_index if crs_index >= 0 else self.crs_combo.findData("custom"))
        self.crs_combo.currentIndexChanged.connect(self._on_crs_combo_changed)
        crs_title_row.addWidget(self.crs_combo, stretch=1)
        crs_layout.addLayout(crs_title_row)

        crs_input_row = QHBoxLayout()
        self.crs_picker = CrsPicker(self._active_crs, crs_group)
        self.crs_edit = self.crs_picker.edit
        self.crs_edit.setPlaceholderText(tr("dialog.georef.crs_placeholder"))
        self.crs_edit.textChanged.connect(self._on_crs_text_changed)
        self.lbl_crs_status = QLabel("✓", crs_group)
        self.lbl_crs_status.setStyleSheet("color: #16A34A; font-weight: bold;")
        crs_input_row.addWidget(self.crs_picker, stretch=1)
        crs_input_row.addWidget(self.lbl_crs_status)
        crs_layout.addLayout(crs_input_row)
        self.crs_help = QLabel(tr("dialog.georef.crs_help"), crs_group)
        self.crs_help.setWordWrap(True)
        crs_layout.addWidget(self.crs_help)

        self.georef_steps = QStackedWidget(right_widget)
        self.crs_page = QWidget()
        crs_page_layout = QVBoxLayout(self.crs_page)
        crs_page_layout.addWidget(crs_group)
        self.binding_summary = QLabel(tr("ux.ready_binding") if self._imported_affine else tr("ux.manual_binding"))
        self.binding_summary.setWordWrap(True)
        crs_page_layout.addWidget(self.binding_summary)
        crs_page_layout.addStretch()
        self.georef_steps.addWidget(self.crs_page)
        self.points_page = QWidget()
        point_page_layout = QVBoxLayout(self.points_page)
        self.step_title = QLabel(tr("ux.georef_step_crs"))
        self.step_title.setStyleSheet("font-weight: 600; font-size: 14px;")
        right_layout.addWidget(self.step_title)
        right_layout.addWidget(self.georef_steps, 1)

        # 2. Таблица контрольных точек
        tbl_header_layout = QHBoxLayout()
        lbl_tbl = QLabel(tr("dialog.georef.control_points"), right_widget)
        lbl_tbl.setStyleSheet("font-weight: bold; color: #1E293B;")
        tbl_header_layout.addWidget(lbl_tbl)
        tbl_header_layout.addStretch()

        self.btn_delete_pt = QPushButton(tr("dialog.georef.delete_point"), right_widget)
        self.btn_delete_pt.clicked.connect(self._on_delete_selected_point)
        tbl_header_layout.addWidget(self.btn_delete_pt)
        point_page_layout.addLayout(tbl_header_layout)

        self.points_table = QTableWidget(0, 7, right_widget)
        self.points_table.setHorizontalHeaderLabels([
            tr("table.col_index"),
            tr("dialog.georef.pixel_x"),
            tr("dialog.georef.pixel_y"),
            tr("dialog.georef.target_x"),
            tr("dialog.georef.target_y"),
            f"{tr('dialog.georef.residual')} ({tr('unit.m')})",
            tr("dialog.georef.enable"),
        ])
        self.points_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.points_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.points_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.points_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        self.points_table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
        self.points_table.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeMode.ResizeToContents)
        self.points_table.horizontalHeader().setSectionResizeMode(6, QHeaderView.ResizeMode.ResizeToContents)
        self.points_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.points_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.points_table.cellChanged.connect(self._on_table_cell_changed)
        self.points_table.itemSelectionChanged.connect(self._on_table_selection_changed)
        point_page_layout.addWidget(self.points_table, stretch=1)

        # 3. Индикатор ошибки (RMSE) и статус
        status_box = QFrame(right_widget)
        status_box.setStyleSheet("background: #F1F5F9; border-radius: 6px; padding: 10px;")
        status_layout = QVBoxLayout(status_box)
        status_layout.setSpacing(4)

        self.lbl_pts_count = QLabel(tr("dialog.georef.pts_count", count=0, min=3), status_box)
        status_layout.addWidget(self.lbl_pts_count)

        self.lbl_rmse = QLabel(f"{tr('dialog.georef.rmse')} —", status_box)
        self.lbl_rmse.setStyleSheet("font-size: 13px; font-weight: bold; color: #0F172A;")
        status_layout.addWidget(self.lbl_rmse)

        self.lbl_status_msg = QLabel("", status_box)
        self.lbl_status_msg.setWordWrap(True)
        self.lbl_status_msg.setStyleSheet("color: #DC2626; font-weight: 500;")
        status_layout.addWidget(self.lbl_status_msg)

        point_page_layout.addWidget(status_box)
        self.georef_steps.addWidget(self.points_page)
        self.review_page = QWidget()
        review_layout = QVBoxLayout(self.review_page)
        self.review_text = QLabel()
        self.review_text.setWordWrap(True)
        review_layout.addWidget(self.review_text)
        review_layout.addStretch()
        self.georef_steps.addWidget(self.review_page)

        splitter.addWidget(right_widget)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)
        main_layout.addWidget(splitter, stretch=1)

        # 4. Нижние кнопки управления
        bottom_bar = QHBoxLayout()
        self.btn_export_wf = QPushButton(tr("dialog.georef.export_world_file"), self)
        self.btn_export_wf.clicked.connect(self._on_export_world_file)
        bottom_bar.addWidget(self.btn_export_wf)

        bottom_bar.addStretch()
        self.btn_back = QPushButton(tr("ux.back"))
        self.btn_back.clicked.connect(self._previous_step)
        bottom_bar.addWidget(self.btn_back)
        self.btn_next = QPushButton(tr("ux.next"))
        self.btn_next.clicked.connect(self._next_step)
        bottom_bar.addWidget(self.btn_next)

        self.btn_preview = QPushButton(tr("dialog.georef.preview"), self)
        self.btn_preview.clicked.connect(self._on_preview_clicked)
        bottom_bar.addWidget(self.btn_preview)

        self.btn_cancel = QPushButton(tr("common.cancel"), self)
        self.btn_cancel.clicked.connect(self.reject)
        bottom_bar.addWidget(self.btn_cancel)

        self.btn_apply = QPushButton(tr("dialog.georef.apply"), self)
        self.btn_apply.setStyleSheet("background: #0284C7; color: white; font-weight: bold; padding: 6px 18px;")
        self.btn_apply.clicked.connect(self._on_apply_clicked)
        self.btn_apply.setEnabled(False)
        bottom_bar.addWidget(self.btn_apply)

        main_layout.addLayout(bottom_bar)

    def _next_step(self):
        index = self.georef_steps.currentIndex()
        if index == 0:
            try:
                pyproj.CRS.from_user_input(self.crs_edit.text().strip())
            except Exception:
                self.crs_edit.setFocus()
                return
            self.georef_steps.setCurrentIndex(2 if self._imported_affine and not self._control_points else 1)
        elif index == 1:
            self._recalculate()
            if self._current_affine is None:
                return
            self.georef_steps.setCurrentIndex(2)
        self.btn_add_pt.setChecked(False)
        self._update_step_ui()

    def _previous_step(self):
        index = self.georef_steps.currentIndex()
        self.georef_steps.setCurrentIndex(0 if index == 1 or (self._imported_affine and not self._control_points) else 1)
        self._update_step_ui()

    def _update_step_ui(self):
        index = self.georef_steps.currentIndex()
        self.step_title.setText(tr(("ux.georef_step_crs", "ux.georef_step_points", "ux.georef_step_review")[index]))
        self.btn_back.setVisible(index > 0)
        self.btn_next.setVisible(index < 2)
        self.btn_apply.setVisible(index == 2)
        self.btn_export_wf.setVisible(index == 2)
        self.btn_add_pt.setEnabled(index == 1)
        if index == 2 and self._current_affine:
            extent = self.get_extent()
            self.review_text.setText(tr("ux.georef_review", name=self.image_path.name,
                crs=self._active_crs, width=self._full_size[0], height=self._full_size[1],
                rmse="—" if not self._control_points else f"{self._current_rmse:.3f} {tr('unit.m')}", **extent))

    def _load_image(self) -> None:
        """Инспекция и загрузка изображения в компонент предварительного просмотра."""
        try:
            self._image_info = GeoreferenceService.inspect_image(self.image_path)
            qimg, full_size = GeoreferenceService.load_preview_image(self.image_path, max_dimension=2048)
            self._full_size = full_size
            self.image_view.set_image(qimg, full_size)
            self.lbl_cursor_coords.setText(
                tr(
                    "dialog.georef.image_size_format",
                    width=full_size[0],
                    height=full_size[1],
                    unit=tr("unit.px"),
                    fmt=self._image_info["format"],
                )
            )
        except Exception as e:
            logger.exception("Ошибка загрузки изображения %s: %s", self.image_path, e)
            QMessageBox.critical(
                self,
                tr("dialog.georef.load_error_title"),
                tr("dialog.georef.load_error_msg", error=e),
            )
            self.reject()

    def _update_crs_ui(self) -> None:
        """Обновление названий колонок таблицы в зависимости от типа CRS."""
        is_geo = False
        try:
            crs_obj = pyproj.CRS.from_user_input(self._active_crs)
            is_geo = crs_obj.is_geographic
        except Exception:
            pass

        if is_geo:
            self.points_table.horizontalHeaderItem(3).setText(tr("dialog.georef.target_lon"))
            self.points_table.horizontalHeaderItem(4).setText(tr("dialog.georef.target_lat"))
        else:
            self.points_table.horizontalHeaderItem(3).setText(tr("dialog.georef.target_easting"))
            self.points_table.horizontalHeaderItem(4).setText(tr("dialog.georef.target_northing"))

    def _on_crs_combo_changed(self, index: int) -> None:
        val = self.crs_combo.currentData()
        if val != "custom":
            self.crs_edit.setText(val)

    def _on_crs_text_changed(self, text: str) -> None:
        clean = text.strip()
        try:
            pyproj.CRS.from_user_input(clean)
            self._active_crs = clean
            self.lbl_crs_status.setText("✓")
            self.lbl_crs_status.setStyleSheet("color: #16A34A; font-weight: bold;")
            self._update_crs_ui()
            self._recalculate()
        except Exception:
            self.lbl_crs_status.setText("✗")
            self.lbl_crs_status.setStyleSheet("color: #DC2626; font-weight: bold;")
            self._recalculate()

    def _on_add_point_toggled(self, checked: bool) -> None:
        self.image_view.set_adding_point_mode(checked)
        if checked:
            self.btn_add_pt.setText(tr("dialog.georef.click_on_image"))
        else:
            self.btn_add_pt.setText(tr("dialog.georef.add_point"))

    def _on_point_placed_on_image(self, pixel_x: float, pixel_y: float) -> None:
        """Пользователь кликнул по изображению для добавления новой точки."""
        if len(self._control_points) >= MAX_CONTROL_POINTS:
            QMessageBox.warning(self, tr("common.limit_exceeded"), tr("dialog.georef.max_pts_limit", max=MAX_CONTROL_POINTS))
            self.btn_add_pt.setChecked(False)
            return

        pt_num = len(self._control_points) + 1
        new_pt = ControlPoint(
            name=str(pt_num),
            pixel_x=round(pixel_x, 2),
            pixel_y=round(pixel_y, 2),
            target_x=0.0,
            target_y=0.0,
            enabled=True,
        )
        self._control_points.append(new_pt)

        self._populate_table()
        self.image_view.sync_markers(self._control_points, selected_id=new_pt.id)

        # Выбираем строку новой точки и активируем редактирование Target X
        row = len(self._control_points) - 1
        self.points_table.selectRow(row)
        self.points_table.editItem(self.points_table.item(row, 3))

        self._recalculate()

    def _on_marker_moved(self, point: ControlPoint) -> None:
        """Маркер точки был перемещен мышью на изображении."""
        self._populate_table()
        self._recalculate()

    def _on_marker_selected(self, point_id: str) -> None:
        """Синхронизация выбора маркера с выделением в таблице."""
        for r, pt in enumerate(self._control_points):
            if pt.id == point_id:
                self.points_table.selectRow(r)
                break

    def _on_table_selection_changed(self) -> None:
        selected_rows = self.points_table.selectionModel().selectedRows()
        sel_id = None
        if selected_rows:
            r = selected_rows[0].row()
            if 0 <= r < len(self._control_points):
                sel_id = self._control_points[r].id
        self.image_view.sync_markers(self._control_points, selected_id=sel_id)

    def _on_delete_selected_point(self) -> None:
        """Удаление выбранной контрольной точки."""
        selected_rows = self.points_table.selectionModel().selectedRows()
        if not selected_rows:
            return
        r = selected_rows[0].row()
        if 0 <= r < len(self._control_points):
            self._control_points.pop(r)
            # Перенумеровываем имена
            for i, p in enumerate(self._control_points):
                if p.name.isdigit():
                    p.name = str(i + 1)
            self._populate_table()
            self.image_view.sync_markers(self._control_points)
            self._recalculate()

    def _populate_table(self) -> None:
        """Заполнение таблицы контрольных точек."""
        self.points_table.blockSignals(True)
        self.points_table.setRowCount(len(self._control_points))

        for row, pt in enumerate(self._control_points):
            # 0. Номер
            num_item = QTableWidgetItem(pt.name or str(row + 1))
            num_item.setFlags(num_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.points_table.setItem(row, 0, num_item)

            # 1. Pixel X
            px_item = QTableWidgetItem(f"{pt.pixel_x:.2f}")
            self.points_table.setItem(row, 1, px_item)

            # 2. Pixel Y
            py_item = QTableWidgetItem(f"{pt.pixel_y:.2f}")
            self.points_table.setItem(row, 2, py_item)

            # 3. Target X
            tx_item = QTableWidgetItem(str(pt.target_x))
            self.points_table.setItem(row, 3, tx_item)

            # 4. Target Y
            ty_item = QTableWidgetItem(str(pt.target_y))
            self.points_table.setItem(row, 4, ty_item)

            # 5. Residual (м)
            res_str = f"{pt.residual_total:.2f}" if pt.residual_total is not None else "—"
            res_item = QTableWidgetItem(res_str)
            res_item.setFlags(res_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            res_item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            self.points_table.setItem(row, 5, res_item)

            # 6. Включена (Checkbox)
            chk_widget = QWidget()
            chk_layout = QHBoxLayout(chk_widget)
            chk_layout.setContentsMargins(0, 0, 0, 0)
            chk_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
            chk = QCheckBox(chk_widget)
            chk.setChecked(pt.enabled)
            chk.toggled.connect(lambda checked, idx=row: self._on_enable_toggled(idx, checked))
            chk_layout.addWidget(chk)
            self.points_table.setCellWidget(row, 6, chk_widget)

        self.points_table.blockSignals(False)

    def _on_enable_toggled(self, row: int, checked: bool) -> None:
        if 0 <= row < len(self._control_points):
            self._control_points[row].enabled = checked
            self.image_view.sync_markers(self._control_points)
            self._recalculate()

    def _on_table_cell_changed(self, row: int, col: int) -> None:
        if row >= len(self._control_points):
            return
        pt = self._control_points[row]
        item = self.points_table.item(row, col)
        if not item:
            return

        text = item.text().strip().replace(",", ".")
        try:
            val = float(text)
            if not math.isfinite(val):
                raise ValueError()
            if col == 1:
                pt.pixel_x = val
            elif col == 2:
                pt.pixel_y = val
            elif col == 3:
                pt.target_x = val
            elif col == 4:
                pt.target_y = val
            item.setBackground(QBrush())
            item.setToolTip("")
        except ValueError:
            item.setBackground(QColor("#FEE2E2"))
            item.setToolTip(tr("ux.invalid_number"))
            self.btn_apply.setEnabled(False)
            self._current_affine = None
            return

        self.image_view.sync_markers(self._control_points)
        self._recalculate()

    def _recalculate(self) -> None:
        """Перерасчет аффинной трансформации, остаточных невязок и RMSE."""
        for row in range(self.points_table.rowCount()):
            for column in range(1, 5):
                item = self.points_table.item(row, column)
                if item is None:
                    continue
                try:
                    if not math.isfinite(float(item.text().strip().replace(",", "."))):
                        raise ValueError()
                except ValueError:
                    self._current_affine = None
                    self.btn_apply.setEnabled(False)
                    self.btn_export_wf.setEnabled(False)
                    self.lbl_status_msg.setText(tr("ux.invalid_number"))
                    return
        try:
            pyproj.CRS.from_user_input(self.crs_edit.text().strip())
        except Exception:
            self._current_affine = None
            self.lbl_crs_status.setText("✗")
            self.lbl_status_msg.setText(tr("dialog.georef.crs_required"))
            self.btn_apply.setEnabled(False)
            self.btn_export_wf.setEnabled(False)
            return
        self.btn_export_wf.setEnabled(True)
        if self._imported_affine is not None and not self._control_points:
            self._current_affine = self._imported_affine
            self.lbl_status_msg.setText(tr("dialog.georef.imported_binding"))
            self.lbl_rmse.setText(f"{tr('dialog.georef.rmse')} —")
            self.btn_apply.setEnabled(True)
            return
        enabled_pts = [p for p in self._control_points if p.enabled]
        n_en = len(enabled_pts)

        self.lbl_pts_count.setText(tr("dialog.georef.active_pts_count", count=n_en, min=3))

        if n_en < 3:
            self.lbl_rmse.setText(f"{tr('dialog.georef.rmse')} —")
            self.lbl_status_msg.setText(tr("msg.georef_not_enough_points"))
            self.btn_apply.setEnabled(False)
            self._current_affine = None
            self._current_rmse = 0.0
            return

        try:
            affine, updated_pts, rmse = GeoreferenceService.solve_affine(
                self._control_points,
                crs_str=self._active_crs,
            )
            self._current_affine = affine
            self._current_rmse = rmse

            # Обновляем невязки в таблице
            self.points_table.blockSignals(True)
            for r, p in enumerate(self._control_points):
                res_item = self.points_table.item(r, 5)
                if res_item:
                    res_str = f"{p.residual_total:.2f}" if p.residual_total is not None else "—"
                    res_item.setText(res_str)
            self.points_table.blockSignals(False)

            self.lbl_rmse.setText(f"{tr('dialog.georef.rmse')} {rmse:.2f} {tr('unit.m')}")
            self.lbl_status_msg.setText("")
            self.btn_apply.setEnabled(True)

        except Exception as err:
            self._current_affine = None
            self._current_rmse = 0.0
            self.lbl_rmse.setText(f"{tr('dialog.georef.rmse')} —")
            self.lbl_status_msg.setText(str(err))
            self.btn_apply.setEnabled(False)

    def _on_preview_clicked(self) -> None:
        """Предпросмотр охвата и трансформации."""
        if not self._current_affine:
            QMessageBox.warning(self, tr("dialog.georef.preview_title"), tr("dialog.georef.preview_min_points_error"))
            return

        a, b, c, d, e, f = self._current_affine
        w, h = self._full_size

        # Расчет 4 углов изображения в координатах CRS
        c_tl = (c, f)
        c_tr = (a * w + c, d * w + f)
        c_bl = (b * h + c, e * h + f)
        c_br = (a * w + b * h + c, d * w + e * h + f)

        xs = [c_tl[0], c_tr[0], c_bl[0], c_br[0]]
        ys = [c_tl[1], c_tr[1], c_bl[1], c_br[1]]

        msg = tr(
            "dialog.georef.preview_details",
            a=a,
            b=b,
            c=c,
            d=d,
            e=e,
            f=f,
            crs=self._active_crs,
            xmin=min(xs),
            xmax=max(xs),
            ymin=min(ys),
            ymax=max(ys),
            rmse=self._current_rmse,
            unit=tr("unit.m"),
        )
        QMessageBox.information(self, tr("dialog.georef.preview"), msg)

    def _on_export_world_file(self) -> None:
        """Экспорт файлов привязки World File (.pgw / .jgw / .tfw)."""
        if not self._current_affine:
            QMessageBox.warning(self, tr("dialog.georef.export_title"), tr("dialog.georef.export_min_points_error"))
            return

        out_dir = QFileDialog.getExistingDirectory(self, tr("dialog.georef.select_world_file_dir"), str(self.image_path.parent))
        if out_dir:
            try:
                files = GeoreferenceService.export_world_file(
                    self.image_path,
                    self._current_affine,
                    crs_str=self._active_crs,
                    target_dir=out_dir,
                )
                file_names = "\n".join(str(f) for f in files)
                QMessageBox.information(self, tr("common.success"), tr("dialog.georef.world_files_success", files=file_names))
            except Exception as e:
                QMessageBox.critical(self, tr("dialog.georef.export_error_title"), tr("dialog.georef.world_files_failed", error=str(e)))

    def _on_apply_clicked(self) -> None:
        """Подтверждение привязки."""
        if not self._current_affine:
            return
        self.accept()

    def keyPressEvent(self, event: Any) -> None:
        """Обработка клавиш: Esc отменяет режим добавления точки, Delete удаляет выбранную точку."""
        if event.key() == Qt.Key.Key_Escape:
            if self._is_adding_point:
                self.btn_add_pt.setChecked(False)
                event.accept()
                return
        elif event.key() == Qt.Key.Key_Delete:
            self._on_delete_selected_point()
            event.accept()
            return
        super().keyPressEvent(event)

    # Публичные методы получения результатов диалога
    def get_affine_transform(self) -> tuple[float, float, float, float, float, float]:
        """Получение коэффициентов аффинной трансформации (a, b, c, d, e, f)."""
        if self._current_affine is None:
            raise RuntimeError(tr("dialog.georef.transform_not_computed"))
        return self._current_affine

    def get_control_points(self) -> list[ControlPoint]:
        """Получение списка контрольных точек."""
        return list(self._control_points)

    def get_crs(self) -> str:
        """Получение выбранной системы координат."""
        return self._active_crs

    def get_rmse(self) -> float:
        """Получение значения RMSE в метрах."""
        return self._current_rmse

    def get_extent(self) -> dict[str, float]:
        """Получение географического охвата растра."""
        if not self._current_affine:
            return {"xmin": 0.0, "ymin": 0.0, "xmax": 0.0, "ymax": 0.0}
        a, b, c, d, e, f = self._current_affine
        w, h = self._full_size
        xs = [c, a * w + c, b * h + c, a * w + b * h + c]
        ys = [f, d * w + f, e * h + f, d * w + e * h + f]
        return {
            "xmin": float(min(xs)),
            "ymin": float(min(ys)),
            "xmax": float(max(xs)),
            "ymax": float(max(ys)),
        }
