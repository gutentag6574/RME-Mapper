"""Диалог настройки и запуска экспорта карты в изображение (ExportImageDialog)."""

import logging
from pathlib import Path
from typing import Any

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QPixmap, QStandardItemModel
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSlider,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from rme_mapper.exporters.map_renderer import MapRenderer
from rme_mapper.exporters.models import (
    MAX_IMAGE_DIMENSION,
    MIN_IMAGE_DIMENSION,
    ImageExportOptions,
)
from rme_mapper.i18n import tr
from rme_mapper.models.map_point import MapPoint
from rme_mapper.services.app_settings_service import AppSettingsService
from rme_mapper.services.coordinate_service import CoordinateService

logger = logging.getLogger("rme_mapper.ui.export_dialog")


PRESETS = [
    ("export.preset_1080p", 1920, 1080),
    ("export.preset_1440p", 2560, 1440),
    ("export.preset_4k", 3840, 2160),
    ("export.preset_a4_landscape", 3508, 2480),
    ("export.preset_a4_portrait", 2480, 3508),
    ("export.preset_custom", 0, 0),
]


class ExportImageDialog(QDialog):
    """Диалог параметров экспорта карты в PNG / JPEG."""

    def __init__(
        self,
        parent: QWidget | None,
        active_crs: str,
        map_title: str,
        current_view_extent: tuple[float, float, float, float] | None,
        full_map_extent: tuple[float, float, float, float] | None,
        points: list[MapPoint],
        selected_point_ids: set[str],
        settings_service: AppSettingsService | None = None,
        loaded_layers_render_data: list[Any] | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("exportImageDialog")
        self.setWindowTitle(tr("dialog.export_map_title"))
        self.resize(780, 680)

        self._active_crs = active_crs
        self._default_map_title = map_title
        self._current_view_extent = current_view_extent
        self._full_map_extent = full_map_extent
        self._points = list(points)
        self._selected_point_ids = set(selected_point_ids)
        self._settings_service = settings_service or AppSettingsService()
        self._loaded_layers_render_data = loaded_layers_render_data or []

        # Предрасчет охватов точек
        self._all_points_extent = self._calculate_points_extent(self._points)
        sel_pts = [p for p in self._points if p.id in self._selected_point_ids]
        self._selected_points_extent = self._calculate_points_extent(sel_pts, is_single_fallback=True)

        self._updating_dimensions = False

        self._setup_ui()
        self._load_saved_settings()
        self._update_extent_display()
        self._update_memory_label()
        self._sync_format_ui()

    # -------------------------------------------------------------------------
    # Расчет охватов
    # -------------------------------------------------------------------------

    def _calculate_points_extent(
        self,
        pts: list[MapPoint],
        is_single_fallback: bool = False,
    ) -> tuple[float, float, float, float] | None:
        """Расчет охвата точек в активной CRS с разумным отступом 15%."""
        if not pts:
            return None

        xs: list[float] = []
        ys: list[float] = []

        for p in pts:
            try:
                mx, my = CoordinateService.transform_xy(
                    p.longitude, p.latitude,
                    source_crs=p.source_crs,
                    target_crs=self._active_crs,
                )
                xs.append(mx)
                ys.append(my)
            except Exception:
                continue

        if not xs or not ys:
            return None

        min_x, max_x = min(xs), max(xs)
        min_y, max_y = min(ys), max(ys)

        if len(xs) == 1 or (abs(max_x - min_x) < 1e-6 and abs(max_y - min_y) < 1e-6):
            # 1 точка: охват +/- 500м или по зоне
            delta = 500.0
            p0 = pts[0]
            if p0.zone_enabled and p0.radius_m > 0:
                delta = max(delta, p0.radius_m * 1.3)
            return (min_x - delta, min_y - delta, max_x + delta, max_y + delta)

        w = max_x - min_x
        h = max_y - min_y
        pad_x = max(w * 0.15, 50.0)
        pad_y = max(h * 0.15, 50.0)
        return (min_x - pad_x, min_y - pad_y, max_x + pad_x, max_y + pad_y)

    # -------------------------------------------------------------------------
    # UI Setup
    # -------------------------------------------------------------------------

    def _setup_ui(self) -> None:
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(16, 16, 16, 16)
        main_layout.setSpacing(12)

        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)

        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(14)

        # 1. Файл
        layout.addWidget(self._create_file_section())

        # 2. Область
        layout.addWidget(self._create_extent_section())

        # 3. Размер
        layout.addWidget(self._create_size_section())

        # 4. Содержимое
        layout.addWidget(self._create_content_section())

        # 5. Оформление
        layout.addWidget(self._create_decorations_section())

        # 6. Качество и фон
        layout.addWidget(self._create_quality_section())

        scroll.setWidget(container)
        main_layout.addWidget(scroll, stretch=1)

        # Нижняя панель с кнопками
        bottom_layout = QHBoxLayout()
        self.btn_preview = QPushButton(tr("export.preview_btn"), self)
        self.btn_preview.setObjectName("btnRefreshPreview")
        self.btn_preview.clicked.connect(self._on_preview_clicked)
        bottom_layout.addWidget(self.btn_preview)

        bottom_layout.addStretch()

        self.btn_export = QPushButton(tr("export.btn_export"), self)
        self.btn_export.setObjectName("btnExecuteExport")
        self.btn_export.setDefault(True)
        self.btn_export.setStyleSheet("font-weight: bold; padding: 6px 18px;")
        self.btn_export.clicked.connect(self._on_export_clicked)
        bottom_layout.addWidget(self.btn_export)

        self.btn_cancel = QPushButton(tr("export.btn_cancel"), self)
        self.btn_cancel.setObjectName("btnCancelExport")
        self.btn_cancel.clicked.connect(self.reject)
        bottom_layout.addWidget(self.btn_cancel)

        main_layout.addLayout(bottom_layout)

    def _create_file_section(self) -> QGroupBox:
        box = QGroupBox(tr("export.section_file"), self)
        grid = QGridLayout(box)
        grid.setSpacing(8)

        # Поле пути
        lbl_file = QLabel(tr("export.file_label"), box)
        grid.addWidget(lbl_file, 0, 0)

        self.path_edit = QLineEdit(box)
        self.path_edit.setObjectName("exportPathEdit")
        self.path_edit.textChanged.connect(self._on_path_text_changed)
        grid.addWidget(self.path_edit, 0, 1)

        self.btn_browse = QPushButton(tr("export.browse_btn"), box)
        self.btn_browse.setObjectName("btnBrowseExport")
        self.btn_browse.clicked.connect(self._on_browse_clicked)
        grid.addWidget(self.btn_browse, 0, 2)

        # Выбор формата
        lbl_fmt = QLabel(tr("export.format_label"), box)
        grid.addWidget(lbl_fmt, 1, 0)

        self.fmt_combo = QComboBox(box)
        self.fmt_combo.setObjectName("exportFormatCombo")
        self.fmt_combo.addItem(tr("export.filter_png"), "PNG")
        self.fmt_combo.addItem(tr("export.filter_jpeg"), "JPEG")
        self.fmt_combo.currentIndexChanged.connect(self._on_format_combo_changed)
        grid.addWidget(self.fmt_combo, 1, 1, 1, 2)

        return box

    def _create_extent_section(self) -> QGroupBox:
        box = QGroupBox(tr("export.section_extent"), self)
        vbox = QVBoxLayout(box)
        vbox.setSpacing(6)

        row = QHBoxLayout()
        lbl = QLabel(tr("export.extent_mode_label"), box)
        row.addWidget(lbl)

        self.extent_combo = QComboBox(box)
        self.extent_combo.setObjectName("exportExtentCombo")
        self.extent_combo.addItem(tr("export.extent_current_view"), "current_view")
        self.extent_combo.addItem(tr("export.extent_full_map"), "full_map")
        self.extent_combo.addItem(tr("export.extent_all_points"), "all_points")
        self.extent_combo.addItem(tr("export.extent_selected_points"), "selected_points")

        # Отключение недоступных режимов
        model = self.extent_combo.model()
        if isinstance(model, QStandardItemModel):
            if not self._full_map_extent:
                idx = self.extent_combo.findData("full_map")
                if idx >= 0:
                    it = model.item(idx)
                    if it:
                        it.setEnabled(False)

            if not self._all_points_extent:
                idx = self.extent_combo.findData("all_points")
                if idx >= 0:
                    it = model.item(idx)
                    if it:
                        it.setEnabled(False)

            if not self._selected_points_extent:
                idx = self.extent_combo.findData("selected_points")
                if idx >= 0:
                    it = model.item(idx)
                    if it:
                        it.setEnabled(False)

        self.extent_combo.currentIndexChanged.connect(self._on_extent_changed)
        row.addWidget(self.extent_combo, stretch=1)
        vbox.addLayout(row)

        self.extent_info_lbl = QLabel(box)
        self.extent_info_lbl.setStyleSheet("color: #64748B; font-size: 11px;")
        vbox.addWidget(self.extent_info_lbl)

        return box

    def _create_size_section(self) -> QGroupBox:
        box = QGroupBox(tr("export.section_size"), self)
        grid = QGridLayout(box)
        grid.setSpacing(8)

        # Пресеты
        lbl_preset = QLabel(tr("export.preset_label"), box)
        grid.addWidget(lbl_preset, 0, 0)

        self.preset_combo = QComboBox(box)
        self.preset_combo.setObjectName("exportPresetCombo")
        for key, w, h in PRESETS:
            token = f"{w}x{h}" if w > 0 and h > 0 else "custom"
            self.preset_combo.addItem(tr(key), token)
        self.preset_combo.currentIndexChanged.connect(self._on_preset_changed)
        grid.addWidget(self.preset_combo, 0, 1, 1, 3)

        # Ширина / Высота
        lbl_w = QLabel(tr("export.width_label"), box)
        grid.addWidget(lbl_w, 1, 0)
        self.spin_width = QSpinBox(box)
        self.spin_width.setObjectName("exportWidthSpin")
        self.spin_width.setRange(MIN_IMAGE_DIMENSION, MAX_IMAGE_DIMENSION)
        self.spin_width.setValue(1920)
        self.spin_width.valueChanged.connect(self._on_width_changed)
        grid.addWidget(self.spin_width, 1, 1)

        lbl_h = QLabel(tr("export.height_label"), box)
        grid.addWidget(lbl_h, 1, 2)
        self.spin_height = QSpinBox(box)
        self.spin_height.setObjectName("exportHeightSpin")
        self.spin_height.setRange(MIN_IMAGE_DIMENSION, MAX_IMAGE_DIMENSION)
        self.spin_height.setValue(1080)
        self.spin_height.valueChanged.connect(self._on_height_changed)
        grid.addWidget(self.spin_height, 1, 3)

        # Сохранять пропорции
        self.chk_lock_aspect = QCheckBox(tr("export.lock_aspect"), box)
        self.chk_lock_aspect.setObjectName("chkLockAspect")
        self.chk_lock_aspect.setChecked(True)
        grid.addWidget(self.chk_lock_aspect, 2, 0, 1, 2)

        # Оценка памяти
        self.memory_lbl = QLabel(box)
        self.memory_lbl.setStyleSheet("color: #64748B; font-size: 11px;")
        grid.addWidget(self.memory_lbl, 2, 2, 1, 2)

        return box

    def _create_content_section(self) -> QGroupBox:
        box = QGroupBox(tr("export.section_content"), self)
        grid = QGridLayout(box)
        grid.setSpacing(8)

        self.chk_points = QCheckBox(tr("export.include_points"), box)
        self.chk_points.setObjectName("chkExportPoints")
        self.chk_points.setChecked(True)
        grid.addWidget(self.chk_points, 0, 0)

        self.chk_zones = QCheckBox(tr("export.include_zones"), box)
        self.chk_zones.setObjectName("chkExportZones")
        has_zones_data = any(p.zone_enabled and p.radius_m > 0 for p in self._points)
        self.chk_zones.setChecked(has_zones_data)
        grid.addWidget(self.chk_zones, 0, 1)

        lbl_labels = QLabel(tr("export.labels_label"), box)
        grid.addWidget(lbl_labels, 1, 0)

        self.labels_combo = QComboBox(box)
        self.labels_combo.setObjectName("exportLabelsCombo")
        self.labels_combo.addItem(tr("export.labels_none"), "none")
        self.labels_combo.addItem(tr("export.labels_selected"), "selected")
        self.labels_combo.addItem(tr("export.labels_all"), "all")
        self.labels_combo.setCurrentIndex(2)  # 'all' по умолчанию
        grid.addWidget(self.labels_combo, 1, 1)

        return box

    def _create_decorations_section(self) -> QGroupBox:
        box = QGroupBox(tr("export.section_decorations"), self)
        grid = QGridLayout(box)
        grid.setSpacing(8)

        # Заголовок
        self.chk_title = QCheckBox(tr("export.include_title"), box)
        self.chk_title.setObjectName("chkExportTitle")
        self.chk_title.setChecked(True)
        self.chk_title.toggled.connect(lambda c: self.title_edit.setEnabled(c))
        grid.addWidget(self.chk_title, 0, 0)

        self.title_edit = QLineEdit(box)
        self.title_edit.setObjectName("exportTitleEdit")
        self.title_edit.setText(self._default_map_title)
        self.title_edit.setPlaceholderText(tr("export.title_placeholder"))
        grid.addWidget(self.title_edit, 0, 1, 1, 2)

        # CRS
        self.chk_crs = QCheckBox(f"{tr('export.include_crs')} ({self._active_crs})", box)
        self.chk_crs.setObjectName("chkExportCrs")
        self.chk_crs.setChecked(True)
        grid.addWidget(self.chk_crs, 1, 0, 1, 3)

        # Легенда
        self.chk_legend = QCheckBox(tr("export.include_legend"), box)
        self.chk_legend.setObjectName("chkExportLegend")
        self.chk_legend.setChecked(True)
        self.chk_legend.toggled.connect(lambda c: self.legend_pos_combo.setEnabled(c))
        grid.addWidget(self.chk_legend, 2, 0)

        lbl_leg_pos = QLabel(tr("export.legend_pos_label"), box)
        grid.addWidget(lbl_leg_pos, 2, 1)

        self.legend_pos_combo = QComboBox(box)
        self.legend_pos_combo.setObjectName("exportLegendPosCombo")
        self.legend_pos_combo.addItem(tr("export.legend_pos_br"), "bottom_right")
        self.legend_pos_combo.addItem(tr("export.legend_pos_bl"), "bottom_left")
        self.legend_pos_combo.addItem(tr("export.legend_pos_tr"), "top_right")
        self.legend_pos_combo.addItem(tr("export.legend_pos_tl"), "top_left")
        grid.addWidget(self.legend_pos_combo, 2, 2)

        # Масштабная линейка и стрелка севера
        self.chk_scale_bar = QCheckBox(tr("export.include_scale_bar"), box)
        self.chk_scale_bar.setObjectName("chkExportScaleBar")
        self.chk_scale_bar.setChecked(True)
        grid.addWidget(self.chk_scale_bar, 3, 0)

        self.chk_north_arrow = QCheckBox(tr("export.include_north_arrow"), box)
        self.chk_north_arrow.setObjectName("chkExportNorthArrow")
        self.chk_north_arrow.setChecked(True)
        grid.addWidget(self.chk_north_arrow, 3, 1)

        return box

    def _create_quality_section(self) -> QGroupBox:
        box = QGroupBox(tr("export.section_quality"), self)
        grid = QGridLayout(box)
        grid.setSpacing(8)

        # Фон
        lbl_bg = QLabel(tr("export.bg_label"), box)
        grid.addWidget(lbl_bg, 0, 0)

        self.bg_combo = QComboBox(box)
        self.bg_combo.setObjectName("exportBgCombo")
        self.bg_combo.addItem(tr("export.bg_white"), "#FFFFFF")
        self.bg_combo.addItem(tr("export.bg_transparent"), "transparent")
        grid.addWidget(self.bg_combo, 0, 1, 1, 2)

        # Качество JPEG
        self.lbl_quality = QLabel(tr("export.jpeg_quality_label"), box)
        grid.addWidget(self.lbl_quality, 1, 0)

        self.quality_slider = QSlider(Qt.Orientation.Horizontal, box)
        self.quality_slider.setObjectName("exportJpegSlider")
        self.quality_slider.setRange(1, 100)
        self.quality_slider.setValue(92)
        grid.addWidget(self.quality_slider, 1, 1)

        self.quality_spin = QSpinBox(box)
        self.quality_spin.setObjectName("exportJpegSpin")
        self.quality_spin.setRange(1, 100)
        self.quality_spin.setValue(92)
        grid.addWidget(self.quality_spin, 1, 2)

        self.quality_slider.valueChanged.connect(self.quality_spin.setValue)
        self.quality_spin.valueChanged.connect(self.quality_slider.setValue)

        return box

    # -------------------------------------------------------------------------
    # Обработчики событий
    # -------------------------------------------------------------------------

    def _on_format_combo_changed(self) -> None:
        """Синхронизация UI при смене формата."""
        fmt = str(self.fmt_combo.currentData())
        path = self.path_edit.text().strip()

        if path:
            p = Path(path)
            cur_ext = p.suffix.lower()
            if fmt == "PNG" and cur_ext in (".jpg", ".jpeg"):
                self.path_edit.setText(str(p.with_suffix(".png")))
            elif fmt == "JPEG" and cur_ext == ".png":
                self.path_edit.setText(str(p.with_suffix(".jpg")))

        self._sync_format_ui()

    def _sync_format_ui(self) -> None:
        """Включение/отключение полей качества и прозрачности в зависимости от формата."""
        is_jpeg = (self.fmt_combo.currentData() == "JPEG")
        self.lbl_quality.setEnabled(is_jpeg)
        self.quality_slider.setEnabled(is_jpeg)
        self.quality_spin.setEnabled(is_jpeg)

        if is_jpeg:
            # Для JPEG прозрачность невозможна -> выбираем белый фон и отключаем
            idx_white = self.bg_combo.findData("#FFFFFF")
            if idx_white >= 0:
                self.bg_combo.setCurrentIndex(idx_white)
            self.bg_combo.setEnabled(False)
        else:
            self.bg_combo.setEnabled(True)

    def _on_path_text_changed(self, text: str) -> None:
        """Синхронизация выбора формата при ручном вводе расширения файла."""
        clean = text.strip()
        if not clean:
            return
        p = Path(clean)
        ext = p.suffix.lower()
        if ext == ".png" and self.fmt_combo.currentData() != "PNG":
            idx = self.fmt_combo.findData("PNG")
            if idx >= 0:
                self.fmt_combo.setCurrentIndex(idx)
        elif ext in (".jpg", ".jpeg") and self.fmt_combo.currentData() != "JPEG":
            idx = self.fmt_combo.findData("JPEG")
            if idx >= 0:
                self.fmt_combo.setCurrentIndex(idx)

    def _on_browse_clicked(self) -> None:
        """Открытие диалога выбора файла для сохранения."""
        last_dir = self._settings_service.get_last_export_directory(check_exists=True)
        default_name = f"{self._default_map_title or 'map'}.png"
        default_path = str(Path(last_dir) / default_name)

        filt = f"{tr('export.filter_png')};;{tr('export.filter_jpeg')};;{tr('export.filter_all')}"
        initial_filter = tr("export.filter_png") if self.fmt_combo.currentData() == "PNG" else tr("export.filter_jpeg")

        selected_file, chosen_filter = QFileDialog.getSaveFileName(
            self,
            tr("dialog.export_map_title"),
            default_path,
            filt,
            initial_filter,
        )

        if selected_file:
            p = Path(selected_file)
            # Автоматическая нормализация расширения
            if chosen_filter == tr("export.filter_jpeg") and p.suffix.lower() not in (".jpg", ".jpeg"):
                p = p.with_suffix(".jpg")
            elif chosen_filter == tr("export.filter_png") and p.suffix.lower() != ".png":
                p = p.with_suffix(".png")
            elif not p.suffix:
                p = p.with_suffix(".png" if self.fmt_combo.currentData() == "PNG" else ".jpg")

            self.path_edit.setText(str(p))
            self._settings_service.set_last_export_directory(str(p.parent))

    def _on_extent_changed(self) -> None:
        """Обновление информационного лейбла охвата."""
        self._update_extent_display()

    def _update_extent_display(self) -> None:
        extent = self.get_current_target_extent()
        if extent:
            min_x, min_y, max_x, max_y = extent
            txt = tr("export.extent_info", min_x=min_x, min_y=min_y, max_x=max_x, max_y=max_y)
            self.extent_info_lbl.setText(txt)
        else:
            self.extent_info_lbl.setText("—")

    def _on_preset_changed(self) -> None:
        """Установка ширины и высоты из выбранного пресета."""
        token = str(self.preset_combo.currentData() or "")
        if "x" in token:
            try:
                w, h = (int(x) for x in token.split("x"))
                if w > 0 and h > 0:
                    self._updating_dimensions = True
                    self.spin_width.setValue(w)
                    self.spin_height.setValue(h)
                    self._updating_dimensions = False
                    self._update_memory_label()
            except ValueError:
                pass

    def _on_width_changed(self, width: int) -> None:
        if self._updating_dimensions:
            return
        if self.chk_lock_aspect.isChecked():
            extent = self.get_current_target_extent()
            if extent:
                ew = extent[2] - extent[0]
                eh = extent[3] - extent[1]
                if ew > 0 and eh > 0:
                    aspect = eh / ew
                    new_h = int(round(width * aspect))
                    if MIN_IMAGE_DIMENSION <= new_h <= MAX_IMAGE_DIMENSION:
                        self._updating_dimensions = True
                        self.spin_height.setValue(new_h)
                        self._updating_dimensions = False

        self._set_preset_to_custom()
        self._update_memory_label()

    def _on_height_changed(self, height: int) -> None:
        if self._updating_dimensions:
            return
        if self.chk_lock_aspect.isChecked():
            extent = self.get_current_target_extent()
            if extent:
                ew = extent[2] - extent[0]
                eh = extent[3] - extent[1]
                if ew > 0 and eh > 0:
                    aspect = ew / eh
                    new_w = int(round(height * aspect))
                    if MIN_IMAGE_DIMENSION <= new_w <= MAX_IMAGE_DIMENSION:
                        self._updating_dimensions = True
                        self.spin_width.setValue(new_w)
                        self._updating_dimensions = False

        self._set_preset_to_custom()
        self._update_memory_label()

    def _set_preset_to_custom(self) -> None:
        """Переключение селектора пресета в 'Пользовательский' при ручном изменении размера."""
        idx = self.preset_combo.findData("custom")
        if idx >= 0 and self.preset_combo.currentIndex() != idx:
            self.preset_combo.blockSignals(True)
            self.preset_combo.setCurrentIndex(idx)
            self.preset_combo.blockSignals(False)

    def _update_memory_label(self) -> None:
        w = self.spin_width.value()
        h = self.spin_height.value()
        mb = (w * h * 4) // (1024 * 1024)
        self.memory_lbl.setText(tr("export.est_memory", mb=mb))

    def _on_preview_clicked(self) -> None:
        """Генерация и показ небольшого эскиза предпросмотра."""
        try:
            options = self.build_export_options()
        except ValueError as err:
            QMessageBox.warning(self, tr("dialog.export_map_title"), str(err))
            return

        extent = self.get_current_target_extent()
        if not extent:
            self._show_no_extent_warning()
            return

        # Для быстрого предпросмотра используем уменьшенное разрешение (например, 480x270)
        preview_opts = ImageExportOptions(
            file_path="preview.png",
            format="PNG",
            width_px=540,
            height_px=int(round(540 * (options.height_px / options.width_px))),
            include_points=options.include_points,
            include_zones=options.include_zones,
            include_labels=options.include_labels,
            labels_mode=options.labels_mode,
            include_title=options.include_title,
            title_text=options.title_text,
            include_crs=options.include_crs,
            include_legend=options.include_legend,
            legend_position=options.legend_position,
            include_scale_bar=options.include_scale_bar,
            include_north_arrow=options.include_north_arrow,
            background_color=options.background_color,
            transparent_background=options.transparent_background,
        )

        try:
            img = MapRenderer.render_map(
                options=preview_opts,
                active_crs=self._active_crs,
                target_extent=extent,
                loaded_layers_render_data=self._loaded_layers_render_data,
                points=self._points,
                selected_point_ids=self._selected_point_ids,
            )

            # Отображаем эскиз в модальном окне
            preview_dialog = QDialog(self)
            preview_dialog.setWindowTitle(tr("export.preview_title"))
            preview_dialog.resize(580, 360)
            pv_layout = QVBoxLayout(preview_dialog)

            lbl = QLabel(preview_dialog)
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            lbl.setPixmap(QPixmap.fromImage(img))
            pv_layout.addWidget(lbl)

            btn_close = QPushButton("OK", preview_dialog)
            btn_close.clicked.connect(preview_dialog.accept)
            pv_layout.addWidget(btn_close, alignment=Qt.AlignmentFlag.AlignCenter)

            preview_dialog.exec()
        except Exception as e:
            QMessageBox.warning(self, tr("dialog.export_map_title"), f"{tr('export.err_failed')}\n{e}")

    def _on_export_clicked(self) -> None:
        """Проверка параметров и закрытие с кодом Accepted."""
        try:
            options = self.build_export_options()
        except ValueError as err:
            QMessageBox.warning(self, tr("dialog.export_map_title"), str(err))
            return

        extent = self.get_current_target_extent()
        if not extent:
            self._show_no_extent_warning()
            return

        # Проверка существования файла
        target_path = Path(options.file_path)
        if target_path.exists():
            reply = QMessageBox.question(
                self,
                tr("export.confirm_overwrite_title"),
                tr("export.confirm_overwrite_text", path=str(target_path)),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
                return

        # Сохранение настроек в AppSettingsService
        self._save_settings()
        self.accept()

    # -------------------------------------------------------------------------
    # Сбор опций и охвата
    # -------------------------------------------------------------------------

    def _show_no_extent_warning(self) -> None:
        """Показ специфичного сообщения при невозможности определить охват."""
        mode = str(self.extent_combo.currentData())
        if mode == "full_map":
            msg = tr("export.err_no_map_extent")
        elif mode == "selected_points":
            msg = tr("export.err_no_selection_for_extent")
        else:
            msg = tr("export.err_no_points_for_extent")
        QMessageBox.warning(self, tr("dialog.export_map_title"), msg)

    def get_current_target_extent(self) -> tuple[float, float, float, float] | None:
        """Получение охвата в соответствии с текущим выбранным режимом."""
        mode = str(self.extent_combo.currentData())
        if mode == "current_view":
            return self._current_view_extent
        elif mode == "full_map":
            return self._full_map_extent
        elif mode == "all_points":
            return self._all_points_extent
        elif mode == "selected_points":
            return self._selected_points_extent
        return self._current_view_extent

    def build_export_options(self) -> ImageExportOptions:
        """Сборка проверенного экземпляра ImageExportOptions из текущих значений UI."""
        path_str = self.path_edit.text().strip()
        if not path_str:
            raise ValueError(tr("export.file_label") + " " + tr("msg.file_not_found"))

        fmt = str(self.fmt_combo.currentData() or "PNG")
        bg_val = str(self.bg_combo.currentData() or "#FFFFFF")
        is_transparent = (bg_val == "transparent") and (fmt == "PNG")

        opts = ImageExportOptions(
            file_path=path_str,
            format=fmt,
            width_px=self.spin_width.value(),
            height_px=self.spin_height.value(),
            extent_mode=str(self.extent_combo.currentData()),
            include_points=self.chk_points.isChecked(),
            include_zones=self.chk_zones.isChecked(),
            include_labels=(self.labels_combo.currentData() != "none"),
            labels_mode=str(self.labels_combo.currentData()),
            include_title=self.chk_title.isChecked(),
            title_text=self.title_edit.text().strip(),
            include_crs=self.chk_crs.isChecked(),
            include_legend=self.chk_legend.isChecked(),
            legend_position=str(self.legend_pos_combo.currentData()),
            include_scale_bar=self.chk_scale_bar.isChecked(),
            include_north_arrow=self.chk_north_arrow.isChecked(),
            background_color="#FFFFFF" if is_transparent else bg_val,
            transparent_background=is_transparent,
            jpeg_quality=self.quality_spin.value(),
        )

        validation_errors = opts.validate()
        if validation_errors:
            raise ValueError("\n".join(validation_errors))

        return opts

    # -------------------------------------------------------------------------
    # Сохранение и загрузка настроек
    # -------------------------------------------------------------------------

    def _load_saved_settings(self) -> None:
        """Загрузка сохраненных значений настроек экспорта."""
        last_dir = self._settings_service.get_last_export_directory(check_exists=True)
        fmt = self._settings_service.get_export_format(default="PNG")
        ext = ".png" if fmt == "PNG" else ".jpg"
        def_name = f"{self._default_map_title or 'map'}{ext}"
        self.path_edit.setText(str(Path(last_dir) / def_name))

        idx_fmt = self.fmt_combo.findData(fmt)
        if idx_fmt >= 0:
            self.fmt_combo.setCurrentIndex(idx_fmt)

        self.spin_width.setValue(self._settings_service.get_export_width(1920))
        self.spin_height.setValue(self._settings_service.get_export_height(1080))
        self.chk_lock_aspect.setChecked(self._settings_service.get_export_lock_aspect(True))
        self.quality_spin.setValue(self._settings_service.get_export_jpeg_quality(92))

        extent_mode = self._settings_service.get_export_extent_mode("current_view")
        idx_ext = self.extent_combo.findData(extent_mode)
        if idx_ext >= 0 and self.extent_combo.model().flags(self.extent_combo.model().index(idx_ext, 0)) & Qt.ItemFlag.ItemIsEnabled:
            self.extent_combo.setCurrentIndex(idx_ext)

    def _save_settings(self) -> None:
        """Сохранение настроек в AppSettingsService."""
        p = Path(self.path_edit.text().strip())
        if p.parent.exists():
            self._settings_service.set_last_export_directory(str(p.parent))
        self._settings_service.set_export_format(str(self.fmt_combo.currentData()))
        self._settings_service.set_export_width(self.spin_width.value())
        self._settings_service.set_export_height(self.spin_height.value())
        self._settings_service.set_export_lock_aspect(self.chk_lock_aspect.isChecked())
        self._settings_service.set_export_jpeg_quality(self.quality_spin.value())
        self._settings_service.set_export_extent_mode(str(self.extent_combo.currentData()))
