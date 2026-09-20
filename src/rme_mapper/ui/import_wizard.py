"""Полноценный пошаговый мастер импорта точек (ImportWizard).

Реализует 5 шагов:
1. Выбор источника данных (SourcePage)
2. Настройка структуры файла (FileStructurePage)
3. Сопоставление колонок и выбор СК (ColumnMappingPage)
4. Построчная проверка данных и фильтрация (ValidationPage)
5. Итоговое подтверждение параметров импорта (SummaryPage)
"""

from collections.abc import Callable
import logging
from pathlib import Path
from typing import Any
import uuid

import rme_mapper  # noqa: F401 - ensures PROJ_DATA is set
import pyproj
from PySide6.QtCore import QModelIndex, QSize, Qt, Signal
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QSplitter,
    QTableView,
    QVBoxLayout,
    QWidget,
    QWizard,
    QWizardPage,
)

from rme_mapper.i18n import tr
from rme_mapper.importers.import_service import (
    CANONICAL_HEADERS,
    ImportService,
    MAX_IMPORT_FILE_SIZE,
)
from rme_mapper.importers.models import (
    CoordinateFormat,
    DuplicatePolicy,
    ImportOptions,
    ImportPreset,
    ImportResult,
    ImportRow,
    OutsideAreaPolicy,
)
from rme_mapper.importers.presets_service import PresetsService
from rme_mapper.models.map_point import MapPoint
from rme_mapper.services.app_settings_service import AppSettingsService
from rme_mapper.services.project_service import MAX_PROJECT_POINTS
from rme_mapper.ui.models.raw_preview_model import RawPreviewModel
from rme_mapper.ui.models.validation_table_model import ValidationTableModel

logger = logging.getLogger("rme_mapper.ui.import_wizard")


# =============================================================================
# Шаг 1: Выбор файла источника
# =============================================================================

class SourcePage(QWizardPage):
    """Страница выбора исходного файла (XLSX, CSV, TXT)."""

    def __init__(self, last_directory: str = "", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setTitle(tr("wizard.page_source_title"))
        self.setSubTitle(tr("wizard.page_source_sub"))
        self._last_directory = last_directory
        self._selected_path: Path | None = None

        layout = QVBoxLayout(self)
        layout.setSpacing(16)

        file_group = QGroupBox(tr("dialog.import_file"))
        file_layout = QHBoxLayout(file_group)

        self.path_edit = QLineEdit()
        self.path_edit.setReadOnly(True)
        self.path_edit.setPlaceholderText(tr("dialog.import_no_file_selected"))
        self.path_edit.textChanged.connect(self._on_path_changed)
        file_layout.addWidget(self.path_edit, stretch=1)

        self.browse_btn = QPushButton(tr("dialog.import_browse"))
        self.browse_btn.clicked.connect(self._on_browse)
        file_layout.addWidget(self.browse_btn)

        layout.addWidget(file_group)

        # Информационная плашка о файле
        self.info_frame = QFrame()
        self.info_frame.setFrameShape(QFrame.Shape.StyledPanel)
        self.info_frame.setStyleSheet("background-color: #f8f9fa; border: 1px solid #e0e0e0; border-radius: 4px; padding: 8px;")
        info_layout = QVBoxLayout(self.info_frame)

        self.type_label = QLabel()
        self.size_label = QLabel()
        info_layout.addWidget(self.type_label)
        info_layout.addWidget(self.size_label)
        self.info_frame.setVisible(False)
        layout.addWidget(self.info_frame)

        layout.addStretch(1)

    def set_file_path(self, path: Path | str) -> None:
        p = Path(path)
        if p.exists() and p.is_file():
            self._selected_path = p
            self.path_edit.setText(str(p))
            self._update_file_info(p)
            self.completeChanged.emit()

    def _on_browse(self) -> None:
        start_dir = self._last_directory
        if not start_dir and self._selected_path:
            start_dir = str(self._selected_path.parent)

        selected_file, _ = QFileDialog.getOpenFileName(
            self,
            tr("dialog.import_title"),
            start_dir,
            tr("dialog.import_file_filter"),
        )
        if selected_file:
            self.set_file_path(selected_file)

    def _on_path_changed(self, text: str) -> None:
        if text.strip():
            p = Path(text.strip())
            if p.exists() and p.is_file():
                self._selected_path = p
                self._update_file_info(p)
            else:
                self._selected_path = None
                self.info_frame.setVisible(False)
        else:
            self._selected_path = None
            self.info_frame.setVisible(False)
        self.completeChanged.emit()

    def _update_file_info(self, p: Path) -> None:
        ext = p.suffix.upper().replace(".", "")
        size_kb = round(p.stat().st_size / 1024, 1)
        self.type_label.setText(tr("wizard.file_type", type=ext))
        self.size_label.setText(tr("wizard.file_size", size=size_kb))
        self.info_frame.setVisible(True)

    def isComplete(self) -> bool:
        if not self._selected_path:
            return False
        if not self._selected_path.exists() or not self._selected_path.is_file():
            return False
        if self._selected_path.suffix.lower() not in (".xlsx", ".csv", ".txt"):
            return False
        if self._selected_path.stat().st_size > MAX_IMPORT_FILE_SIZE:
            return False
        return True

    def get_selected_path(self) -> Path | None:
        return self._selected_path


# =============================================================================
# Шаг 2: Структура файла
# =============================================================================

class FileStructurePage(QWizardPage):
    """Страница выбора листа, кодировки, разделителя и строки заголовков."""

    def __init__(self, import_service: ImportService, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setTitle(tr("wizard.page_structure_title"))
        self.setSubTitle(tr("wizard.page_structure_sub"))
        self._service = import_service
        self._current_path: Path | None = None

        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        # Панель настроек
        settings_group = QGroupBox(tr("wizard.page_structure_title"))
        grid = QGridLayout(settings_group)
        grid.setSpacing(10)

        # 1. Выбор листа XLSX
        self.sheet_label = QLabel(tr("wizard.sheet"))
        self.sheet_combo = QComboBox()
        self.sheet_combo.currentIndexChanged.connect(self._on_setting_changed)
        grid.addWidget(self.sheet_label, 0, 0)
        grid.addWidget(self.sheet_combo, 0, 1)

        # 2. Кодировка (CSV/TXT)
        self.enc_label = QLabel(tr("wizard.encoding"))
        self.enc_combo = QComboBox()
        self.enc_combo.addItem(tr("dialog.import_format_auto"), "")
        self.enc_combo.addItem("UTF-8", "utf-8")
        self.enc_combo.addItem("UTF-8 BOM", "utf-8-sig")
        self.enc_combo.addItem("Windows-1251", "cp1251")
        self.enc_combo.currentIndexChanged.connect(self._on_setting_changed)
        grid.addWidget(self.enc_label, 0, 2)
        grid.addWidget(self.enc_combo, 0, 3)

        # 3. Разделитель (CSV/TXT)
        self.delim_label = QLabel(tr("wizard.delimiter"))
        self.delim_combo = QComboBox()
        self.delim_combo.addItem(tr("dialog.import_format_auto"), "")
        self.delim_combo.addItem(tr("wizard.delim_comma"), ",")
        self.delim_combo.addItem(tr("wizard.delim_semicolon"), ";")
        self.delim_combo.addItem(tr("wizard.delim_tab"), "\t")
        self.delim_combo.currentIndexChanged.connect(self._on_setting_changed)
        grid.addWidget(self.delim_label, 1, 0)
        grid.addWidget(self.delim_combo, 1, 1)

        # 4. Строка заголовков
        self.header_row_label = QLabel(tr("wizard.header_row"))
        self.header_row_spin = QSpinBox()
        self.header_row_spin.setRange(1, 100)
        self.header_row_spin.setValue(1)
        self.header_row_spin.valueChanged.connect(self._on_header_row_changed)
        grid.addWidget(self.header_row_label, 1, 2)
        grid.addWidget(self.header_row_spin, 1, 3)

        layout.addWidget(settings_group)

        # 5. Таблица предпросмотра структуры
        preview_label = QLabel(tr("wizard.preview_title"))
        layout.addWidget(preview_label)

        self.preview_table = QTableView()
        self.preview_model = RawPreviewModel(self)
        self.preview_table.setModel(self.preview_model)
        self.preview_table.setAlternatingRowColors(True)
        self.preview_table.setSelectionMode(QTableView.SelectionMode.NoSelection)
        self.preview_table.horizontalHeader().setStretchLastSection(True)
        self.preview_table.setMaximumHeight(260)
        layout.addWidget(self.preview_table, stretch=1)

        self._detected_headers: list[str] = []

    def initializePage(self) -> None:
        wizard = self.wizard()
        if not wizard:
            return
        path = wizard.get_source_path()
        if path != self._current_path:
            self._current_path = path
            self._setup_for_file(path)

    def _setup_for_file(self, path: Path | None) -> None:
        if not path or not path.exists():
            return

        is_xlsx = path.suffix.lower() == ".xlsx"
        self.sheet_label.setVisible(is_xlsx)
        self.sheet_combo.setVisible(is_xlsx)
        self.enc_label.setVisible(not is_xlsx)
        self.enc_combo.setVisible(not is_xlsx)
        self.delim_label.setVisible(not is_xlsx)
        self.delim_combo.setVisible(not is_xlsx)

        if is_xlsx:
            sheets = self._service.get_sheet_names(path)
            self.sheet_combo.blockSignals(True)
            self.sheet_combo.clear()
            for s in sheets:
                self.sheet_combo.addItem(s, s)
            self.sheet_combo.blockSignals(False)

        self.header_row_spin.blockSignals(True)
        self.header_row_spin.setValue(1)
        self.header_row_spin.blockSignals(False)

        self._refresh_preview()

    def _on_setting_changed(self) -> None:
        self._refresh_preview()

    def _on_header_row_changed(self, val: int) -> None:
        self.preview_model.set_header_row(val)
        self._extract_headers()

    def _refresh_preview(self) -> None:
        if not self._current_path or not self._current_path.exists():
            return

        opts = self.get_options()
        rows, total_lines, enc, delim = self._service.read_preview_rows(self._current_path, opts, max_rows=50)
        self.preview_model.set_data(rows, self.header_row_spin.value())
        self._extract_headers()

    def _extract_headers(self) -> None:
        h_row = self.header_row_spin.value()
        if 0 <= (h_row - 1) < len(self.preview_model._rows):
            raw_h = self.preview_model._rows[h_row - 1]
            self._detected_headers = [
                h.strip() if h.strip() else f"Col_{i+1}"
                for i, h in enumerate(raw_h)
            ]
        else:
            self._detected_headers = []
        self.completeChanged.emit()

    def get_options(self) -> ImportOptions:
        opts = ImportOptions()
        opts.header_row = self.header_row_spin.value()
        is_xlsx = bool(self._current_path and self._current_path.suffix.lower() == ".xlsx")
        if is_xlsx and self.sheet_combo.currentText():
            opts.sheet_name = self.sheet_combo.currentText()
        elif not is_xlsx:
            opts.encoding = self.enc_combo.currentData() or None
            opts.delimiter = self.delim_combo.currentData() or None
        return opts

    def get_detected_headers(self) -> list[str]:
        return self._detected_headers

    def isComplete(self) -> bool:
        return len(self._detected_headers) > 0


# =============================================================================
# Шаг 3: Сопоставление полей
# =============================================================================

class ColumnMappingPage(QWizardPage):
    """Страница сопоставления колонок файла с полями MapPoint."""

    def __init__(
        self,
        import_service: ImportService,
        presets_service: PresetsService,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setTitle(tr("wizard.page_mapping_title"))
        self.setSubTitle(tr("wizard.page_mapping_sub"))
        self._service = import_service
        self._presets = presets_service

        self._headers: list[str] = []
        self._combos: dict[str, QComboBox] = {}
        self._labels: dict[str, QLabel] = {}

        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        # 1. Формат координат
        format_group = QGroupBox(tr("wizard.coord_mode"))
        f_layout = QHBoxLayout(format_group)
        self.radio_auto = QRadioButton(tr("wizard.format_auto"))
        self.radio_dd = QRadioButton(tr("wizard.format_dd"))
        self.radio_dms = QRadioButton(tr("wizard.format_dms"))
        self.radio_xy = QRadioButton(tr("wizard.format_xy"))

        self.radio_auto.setChecked(True)
        self.format_group_btn = QButtonGroup(self)
        self.format_group_btn.addButton(self.radio_auto)
        self.format_group_btn.addButton(self.radio_dd)
        self.format_group_btn.addButton(self.radio_dms)
        self.format_group_btn.addButton(self.radio_xy)
        self.format_group_btn.buttonClicked.connect(self._on_format_changed)

        f_layout.addWidget(self.radio_auto)
        f_layout.addWidget(self.radio_dd)
        f_layout.addWidget(self.radio_dms)
        f_layout.addWidget(self.radio_xy)
        layout.addWidget(format_group)

        # 2. Исходная СК для режима X/Y
        self.crs_frame = QFrame()
        crs_layout = QHBoxLayout(self.crs_frame)
        crs_layout.setContentsMargins(0, 0, 0, 0)
        crs_label = QLabel(tr("wizard.source_crs"))
        self.crs_edit = QLineEdit("EPSG:3857")
        self.crs_edit.textChanged.connect(self._on_crs_changed)
        self.crs_status = QLabel()
        crs_layout.addWidget(crs_label)
        crs_layout.addWidget(self.crs_edit, stretch=1)
        crs_layout.addWidget(self.crs_status)
        self.crs_frame.setVisible(False)
        layout.addWidget(self.crs_frame)

        # 3. Пресеты сопоставления
        preset_layout = QHBoxLayout()
        p_label = QLabel(tr("wizard.preset_label"))
        self.preset_combo = QComboBox()
        self.preset_combo.addItem(tr("wizard.preset_custom"), None)
        self.preset_combo.currentIndexChanged.connect(self._on_preset_selected)

        self.preset_save_btn = QPushButton(tr("wizard.preset_save"))
        self.preset_save_btn.clicked.connect(self._on_save_preset)
        self.preset_del_btn = QPushButton(tr("wizard.preset_delete"))
        self.preset_del_btn.clicked.connect(self._on_delete_preset)

        preset_layout.addWidget(p_label)
        preset_layout.addWidget(self.preset_combo, stretch=1)
        preset_layout.addWidget(self.preset_save_btn)
        preset_layout.addWidget(self.preset_del_btn)
        layout.addLayout(preset_layout)

        # 4. Предупреждения о конфликтах и ошибках маппинга
        self.warning_label = QLabel()
        self.warning_label.setStyleSheet("color: #d32f2f; font-weight: bold;")
        self.warning_label.setVisible(False)
        layout.addWidget(self.warning_label)

        # 5. Сетка сопоставления в ScrollArea
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll_content = QWidget()
        self.mapping_grid = QGridLayout(scroll_content)
        self.mapping_grid.setSpacing(8)
        self._init_mapping_fields()
        scroll.setWidget(scroll_content)
        layout.addWidget(scroll, stretch=1)

        self._reload_presets()

    def _init_mapping_fields(self) -> None:
        self.fields_order = [
            # Общие
            ("name", tr("wizard.field_name"), False),
            ("object_number", tr("wizard.field_object_number"), False),
            ("group", tr("wizard.field_group"), False),
            ("category", tr("wizard.field_category"), False),
            ("description", tr("wizard.field_description"), False),
            ("visible", tr("wizard.field_visible"), False),
            # DD
            ("latitude", tr("wizard.field_latitude"), True),
            ("longitude", tr("wizard.field_longitude"), True),
            # X/Y
            ("x", tr("wizard.field_x"), True),
            ("y", tr("wizard.field_y"), True),
            # DMS
            ("lat_deg", tr("wizard.field_lat_deg"), True),
            ("lat_min", tr("wizard.field_lat_min"), False),
            ("lat_sec", tr("wizard.field_lat_sec"), False),
            ("lat_dir", tr("wizard.field_lat_dir"), True),
            ("lon_deg", tr("wizard.field_lon_deg"), True),
            ("lon_min", tr("wizard.field_lon_min"), False),
            ("lon_sec", tr("wizard.field_lon_sec"), False),
            ("lon_dir", tr("wizard.field_lon_dir"), True),
            # Маркер
            ("symbol", tr("wizard.field_symbol"), False),
            ("size", tr("wizard.field_size"), False),
            ("red", tr("wizard.field_red"), False),
            ("green", tr("wizard.field_green"), False),
            ("blue", tr("wizard.field_blue"), False),
            ("stroke_red", tr("wizard.field_stroke_red"), False),
            ("stroke_green", tr("wizard.field_stroke_green"), False),
            ("stroke_blue", tr("wizard.field_stroke_blue"), False),
            ("stroke_width", tr("wizard.field_stroke_width"), False),
            ("marker_opacity", tr("wizard.field_marker_opacity"), False),
            # Геозона
            ("zone_enabled", tr("wizard.field_zone_enabled"), False),
            ("radius", tr("wizard.field_radius"), False),
            ("radius_unit", tr("wizard.field_radius_unit"), False),
            ("zone_red", tr("wizard.field_zone_red"), False),
            ("zone_green", tr("wizard.field_zone_green"), False),
            ("zone_blue", tr("wizard.field_zone_blue"), False),
            ("zone_opacity", tr("wizard.field_zone_opacity"), False),
            ("zone_border_red", tr("wizard.field_zone_border_red"), False),
            ("zone_border_green", tr("wizard.field_zone_border_green"), False),
            ("zone_border_blue", tr("wizard.field_zone_border_blue"), False),
            ("zone_border_width", tr("wizard.field_zone_border_width"), False),
            ("zone_border_style", tr("wizard.field_zone_border_style"), False),
        ]

        row = 0
        for f_key, f_title, is_req in self.fields_order:
            lbl = QLabel(f_title)
            if is_req:
                lbl.setStyleSheet("font-weight: bold;")
            combo = QComboBox()
            combo.currentIndexChanged.connect(self._on_mapping_combo_changed)
            self.mapping_grid.addWidget(lbl, row, 0)
            self.mapping_grid.addWidget(combo, row, 1)
            self._combos[f_key] = combo
            self._labels[f_key] = lbl
            row += 1

    def initializePage(self) -> None:
        wizard = self.wizard()
        if not wizard:
            return
        headers = wizard.get_detected_headers()
        if headers != self._headers:
            old_mapping = self.get_column_mapping()
            self._headers = headers
            self._populate_combos()
            has_restored = False
            for f_key, col in old_mapping.items():
                if f_key in self._combos and col in self._headers:
                    combo = self._combos[f_key]
                    idx = combo.findData(col)
                    if idx >= 0:
                        combo.setCurrentIndex(idx)
                        has_restored = True
            if not has_restored:
                self._auto_map()
        self._update_visibility()
        self._validate_mapping()

    def _populate_combos(self) -> None:
        for combo in self._combos.values():
            combo.blockSignals(True)
            combo.clear()
            combo.addItem(tr("wizard.not_used"), "__ignore__")
            for h in self._headers:
                combo.addItem(h, h)
            combo.blockSignals(False)

    def _auto_map(self) -> None:
        fmt = self.get_coordinate_format()
        mapping = self._service.suggest_column_mapping(self._headers, fmt)
        for f_key, combo in self._combos.items():
            if f_key in mapping:
                target_col = mapping[f_key]
                idx = combo.findData(target_col)
                if idx >= 0:
                    combo.setCurrentIndex(idx)
            else:
                combo.setCurrentIndex(0)

    def _on_format_changed(self) -> None:
        self._update_visibility()
        self._auto_map()
        self._validate_mapping()

    def _update_visibility(self) -> None:
        fmt = self.get_coordinate_format()
        is_xy = fmt == CoordinateFormat.XY
        is_dd = fmt == CoordinateFormat.DD or fmt == CoordinateFormat.AUTO
        is_dms = fmt == CoordinateFormat.DMS

        self.crs_frame.setVisible(is_xy)

        # Скрываем/показываем соответствующие поля
        for f_key, combo in self._combos.items():
            lbl = self._labels[f_key]
            if f_key in ("x", "y"):
                combo.setVisible(is_xy)
                lbl.setVisible(is_xy)
            elif f_key in ("latitude", "longitude"):
                combo.setVisible(is_dd)
                lbl.setVisible(is_dd)
            elif f_key.startswith("lat_") or f_key.startswith("lon_"):
                combo.setVisible(is_dms)
                lbl.setVisible(is_dms)

    def _on_crs_changed(self, text: str) -> None:
        clean = text.strip()
        try:
            pyproj.CRS.from_user_input(clean)
            self.crs_status.setText("✓")
            self.crs_status.setStyleSheet("color: green; font-weight: bold;")
        except Exception:
            self.crs_status.setText(tr("wizard.invalid_crs_msg"))
            self.crs_status.setStyleSheet("color: red;")
        self._validate_mapping()

    def _on_mapping_combo_changed(self) -> None:
        self._validate_mapping()

    def _validate_mapping(self) -> None:
        fmt = self.get_coordinate_format()
        errors: list[str] = []

        # 1. Проверка CRS для XY
        if fmt == CoordinateFormat.XY:
            crs = self.crs_edit.text().strip()
            try:
                pyproj.CRS.from_user_input(crs)
            except Exception:
                errors.append(tr("wizard.invalid_crs_msg"))

        # 2. Проверка обязательных полей
        mapping = self.get_column_mapping()
        if fmt == CoordinateFormat.DD or fmt == CoordinateFormat.AUTO:
            if "latitude" not in mapping or "longitude" not in mapping:
                errors.append(tr("wizard.missing_required_mapping"))
        elif fmt == CoordinateFormat.XY:
            if "x" not in mapping or "y" not in mapping:
                errors.append(tr("wizard.missing_required_mapping"))
        elif fmt == CoordinateFormat.DMS:
            for req in ("lat_deg", "lat_dir", "lon_deg", "lon_dir"):
                if req not in mapping:
                    errors.append(tr("wizard.missing_required_mapping"))
                    break

        # 3. Проверка конфликтов (одна колонка назначена несовместимым полям)
        used_cols: dict[str, str] = {}
        for f_key, col in mapping.items():
            if f_key in ("name", "symbol", "size", "red", "green", "blue", "zone_enabled", "radius", "radius_unit", "zone_red", "zone_green", "zone_blue", "zone_opacity"):
                continue
            if col in used_cols:
                errors.append(tr("wizard.conflict_mapping_warning", col=col))
                break
            used_cols[col] = f_key

        self._has_errors = bool(errors)
        if errors:
            self.warning_label.setText(errors[0])
            self.warning_label.setVisible(True)
        else:
            self.warning_label.setText("")
            self.warning_label.setVisible(False)

        self.completeChanged.emit()

    def isComplete(self) -> bool:
        return not getattr(self, "_has_errors", False) and len(self._headers) > 0

    def _is_field_active(self, f_key: str) -> bool:
        fmt = self.get_coordinate_format()
        if f_key in ("x", "y"):
            return fmt == CoordinateFormat.XY
        if f_key in ("latitude", "longitude"):
            return fmt in (CoordinateFormat.DD, CoordinateFormat.AUTO)
        if f_key.startswith("lat_") or f_key.startswith("lon_"):
            return fmt == CoordinateFormat.DMS
        return True

    def get_coordinate_format(self) -> CoordinateFormat:
        if self.radio_dd.isChecked():
            return CoordinateFormat.DD
        if self.radio_dms.isChecked():
            return CoordinateFormat.DMS
        if self.radio_xy.isChecked():
            return CoordinateFormat.XY
        return CoordinateFormat.AUTO

    def get_source_crs(self) -> str:
        return self.crs_edit.text().strip() or "EPSG:4326"

    def get_column_mapping(self) -> dict[str, str]:
        mapping: dict[str, str] = {}
        for f_key, combo in self._combos.items():
            if not self._is_field_active(f_key):
                continue
            val = combo.currentData()
            if val and val != "__ignore__":
                mapping[f_key] = val
        return mapping

    # Пресеты
    def _reload_presets(self) -> None:
        self.preset_combo.blockSignals(True)
        self.preset_combo.clear()
        self.preset_combo.addItem(tr("wizard.preset_custom"), None)
        for p in self._presets.get_presets():
            self.preset_combo.addItem(p.name, p)
        self.preset_combo.blockSignals(False)

    def _on_preset_selected(self) -> None:
        preset: ImportPreset | None = self.preset_combo.currentData()
        if not preset:
            return

        # Устанавливаем формат координат
        if preset.coordinate_format == CoordinateFormat.DD:
            self.radio_dd.setChecked(True)
        elif preset.coordinate_format == CoordinateFormat.DMS:
            self.radio_dms.setChecked(True)
        elif preset.coordinate_format == CoordinateFormat.XY:
            self.radio_xy.setChecked(True)
        else:
            self.radio_auto.setChecked(True)

        if preset.source_crs:
            self.crs_edit.setText(preset.source_crs)

        self._update_visibility()

        # Применяем сопоставление по именам колонок
        for f_key, combo in self._combos.items():
            target_col = preset.column_mapping.get(f_key)
            if target_col:
                idx = combo.findData(target_col)
                if idx >= 0:
                    combo.setCurrentIndex(idx)
                else:
                    combo.setCurrentIndex(0)
            else:
                combo.setCurrentIndex(0)

        self._validate_mapping()

    def _on_save_preset(self) -> None:
        from PySide6.QtWidgets import QInputDialog
        name, ok = QInputDialog.getText(
            self,
            tr("wizard.preset_save_title"),
            tr("wizard.preset_save_prompt"),
        )
        if ok and name.strip():
            preset = ImportPreset(
                name=name.strip(),
                coordinate_format=self.get_coordinate_format(),
                source_crs=self.get_source_crs(),
                column_mapping=self.get_column_mapping(),
            )
            self._presets.save_preset(preset)
            self._reload_presets()
            idx = self.preset_combo.findText(preset.name)
            if idx >= 0:
                self.preset_combo.setCurrentIndex(idx)

    def _on_delete_preset(self) -> None:
        preset: ImportPreset | None = self.preset_combo.currentData()
        if not preset:
            return
        res = QMessageBox.question(
            self,
            tr("wizard.preset_delete_title"),
            tr("wizard.preset_delete_prompt", name=preset.name),
        )
        if res == QMessageBox.StandardButton.Yes:
            self._presets.delete_preset(preset.name)
            self._reload_presets()


# =============================================================================
# Шаг 4: Проверка данных и предпросмотр
# =============================================================================

class ValidationPage(QWizardPage):
    """Страница валидации строк, фильтрации, поиска и детализации ошибок."""

    def __init__(
        self,
        import_service: ImportService,
        get_existing_points: Callable[[], list[MapPoint]],
        get_boundary_geometry: Callable[[], Any],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setTitle(tr("wizard.page_validation_title"))
        self.setSubTitle(tr("wizard.page_validation_sub"))
        self._service = import_service
        self._get_existing_points = get_existing_points
        self._get_boundary_geometry = get_boundary_geometry
        self._result: ImportResult | None = None

        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        # 1. Сводка статистики
        self.summary_frame = QFrame()
        self.summary_frame.setStyleSheet("background-color: #f8f9fa; border: 1px solid #dee2e6; border-radius: 4px; padding: 6px;")
        s_layout = QHBoxLayout(self.summary_frame)
        self.lbl_total = QLabel()
        self.lbl_valid = QLabel()
        self.lbl_errors = QLabel()
        self.lbl_warnings = QLabel()
        self.lbl_valid.setStyleSheet("color: #2e7d32; font-weight: bold;")
        self.lbl_errors.setStyleSheet("color: #d32f2f; font-weight: bold;")
        self.lbl_warnings.setStyleSheet("color: #ed6c02; font-weight: bold;")
        s_layout.addWidget(self.lbl_total)
        s_layout.addWidget(self.lbl_valid)
        s_layout.addWidget(self.lbl_errors)
        s_layout.addWidget(self.lbl_warnings)
        s_layout.addStretch(1)
        layout.addWidget(self.summary_frame)

        # 2. Политики обработки дубликатов и выхода за границы
        policy_group = QGroupBox()
        p_layout = QHBoxLayout(policy_group)
        p_layout.setContentsMargins(8, 4, 8, 4)

        dup_lbl = QLabel(tr("wizard.duplicate_policy_label"))
        self.dup_combo = QComboBox()
        self.dup_combo.addItem(tr("wizard.dup_import_all"), DuplicatePolicy.IMPORT_ALL)
        self.dup_combo.addItem(tr("wizard.dup_skip"), DuplicatePolicy.SKIP_DUPLICATES)
        self.dup_combo.currentIndexChanged.connect(self._on_policy_changed)

        out_lbl = QLabel(tr("wizard.outside_policy_label"))
        self.out_combo = QComboBox()
        self.out_combo.addItem(tr("wizard.outside_import"), OutsideAreaPolicy.IMPORT_OUTSIDE)
        self.out_combo.addItem(tr("wizard.outside_skip"), OutsideAreaPolicy.SKIP_OUTSIDE)
        self.out_combo.currentIndexChanged.connect(self._on_policy_changed)

        p_layout.addWidget(dup_lbl)
        p_layout.addWidget(self.dup_combo)
        p_layout.addSpacing(16)
        p_layout.addWidget(out_lbl)
        p_layout.addWidget(self.out_combo)
        p_layout.addSpacing(16)

        self.chk_create_groups = QCheckBox(tr("wizard.create_missing_groups"))
        self.chk_create_groups.setChecked(True)
        self.chk_create_groups.toggled.connect(self._on_policy_changed)
        p_layout.addWidget(self.chk_create_groups)

        p_layout.addStretch(1)
        layout.addWidget(policy_group)

        # 3. Фильтры и поиск
        toolbar_layout = QHBoxLayout()
        self.btn_all = QPushButton(tr("wizard.filter_all", count=0))
        self.btn_valid = QPushButton(tr("wizard.filter_valid", count=0))
        self.btn_warnings = QPushButton(tr("wizard.filter_warnings", count=0))
        self.btn_errors = QPushButton(tr("wizard.filter_errors", count=0))

        self.btn_all.setCheckable(True)
        self.btn_valid.setCheckable(True)
        self.btn_warnings.setCheckable(True)
        self.btn_errors.setCheckable(True)
        self.btn_all.setChecked(True)

        self.filter_group = QButtonGroup(self)
        self.filter_group.addButton(self.btn_all)
        self.filter_group.addButton(self.btn_valid)
        self.filter_group.addButton(self.btn_warnings)
        self.filter_group.addButton(self.btn_errors)
        self.filter_group.buttonClicked.connect(self._on_filter_clicked)

        toolbar_layout.addWidget(self.btn_all)
        toolbar_layout.addWidget(self.btn_valid)
        toolbar_layout.addWidget(self.btn_warnings)
        toolbar_layout.addWidget(self.btn_errors)
        toolbar_layout.addSpacing(12)

        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText(tr("wizard.search_placeholder"))
        self.search_edit.textChanged.connect(self._on_search_changed)
        toolbar_layout.addWidget(self.search_edit, stretch=1)
        layout.addLayout(toolbar_layout)

        # 4. Таблица валидации
        self.table_view = QTableView()
        self.table_model = ValidationTableModel(self)
        self.table_view.setModel(self.table_model)
        self.table_view.setAlternatingRowColors(True)
        self.table_view.setSelectionBehavior(QTableView.SelectionBehavior.SelectRows)
        self.table_view.setSelectionMode(QTableView.SelectionMode.SingleSelection)
        self.table_view.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self.table_view.horizontalHeader().setStretchLastSection(True)
        self.table_view.selectionModel().currentRowChanged.connect(self._on_row_selected)
        layout.addWidget(self.table_view, stretch=2)

        # 5. Панель подробностей выбранной строки
        self.details_box = QGroupBox(tr("wizard.details_title"))
        d_layout = QVBoxLayout(self.details_box)
        d_layout.setSpacing(4)
        self.lbl_det_row = QLabel()
        self.lbl_det_field = QLabel()
        self.lbl_det_raw = QLabel()
        self.lbl_det_issue = QLabel()
        self.lbl_det_issue.setStyleSheet("color: #d32f2f; font-weight: bold;")
        d_layout.addWidget(self.lbl_det_row)
        d_layout.addWidget(self.lbl_det_field)
        d_layout.addWidget(self.lbl_det_raw)
        d_layout.addWidget(self.lbl_det_issue)
        self.details_box.setVisible(False)
        layout.addWidget(self.details_box, stretch=1)

    def initializePage(self) -> None:
        self._run_validation()

    def _run_validation(self) -> None:
        wizard = self.wizard()
        if not wizard:
            return

        path = wizard.get_source_path()
        if not path:
            return

        opts = wizard.get_import_options()
        opts.duplicate_policy = self.dup_combo.currentData()
        opts.outside_policy = self.out_combo.currentData()
        opts.create_missing_groups = self.chk_create_groups.isChecked()
        opts.existing_points = self._get_existing_points()
        opts.boundary_geometry = self._get_boundary_geometry()

        if hasattr(wizard, "get_group_service") and wizard.get_group_service():
            gs = wizard.get_group_service()
            opts.group_name_to_id = {g.name.casefold(): g.id for g in gs.list_groups()}

        self._result = self._service.validate_file(
            file_path=path,
            options=opts,
            current_project_points_count=len(opts.existing_points),
        )

        self._update_ui_with_result()
        self.completeChanged.emit()

    def _on_policy_changed(self) -> None:
        self._run_validation()

    def _update_ui_with_result(self) -> None:
        if not self._result:
            return

        total = self._result.total_rows
        valid = self._result.valid_rows
        errors = self._result.invalid_rows
        warnings = len(self._result.warnings)

        self.lbl_total.setText(tr("dialog.import_total_rows", count=total))
        self.lbl_valid.setText(tr("dialog.import_valid_rows", count=valid))
        self.lbl_errors.setText(tr("dialog.import_invalid_rows", count=errors))
        self.lbl_warnings.setText(tr("dialog.import_warnings", count=warnings))

        self.btn_all.setText(tr("wizard.filter_all", count=total))
        self.btn_valid.setText(tr("wizard.filter_valid", count=valid))
        self.btn_warnings.setText(tr("wizard.filter_warnings", count=warnings))
        self.btn_errors.setText(tr("wizard.filter_errors", count=errors))

        self.table_model.set_rows(self._result.rows)
        self.details_box.setVisible(False)

    def _on_filter_clicked(self) -> None:
        if self.btn_valid.isChecked():
            self.table_model.set_filter("valid")
        elif self.btn_warnings.isChecked():
            self.table_model.set_filter("warnings")
        elif self.btn_errors.isChecked():
            self.table_model.set_filter("errors")
        else:
            self.table_model.set_filter("all")

    def _on_search_changed(self, text: str) -> None:
        self.table_model.set_search_query(text)

    def _on_row_selected(self, current: QModelIndex, previous: QModelIndex) -> None:
        if not current.isValid():
            self.details_box.setVisible(False)
            return

        row_item = self.table_model.get_row_item(current.row())
        if not row_item:
            self.details_box.setVisible(False)
            return

        self.lbl_det_row.setText(tr("wizard.details_row", row=row_item.row_number))
        field_str = "-"
        raw_val = "-"
        msg_str = "-"

        if row_item.errors:
            err = row_item.errors[0]
            field_str = err.field
            raw_val = str(err.raw_value) if err.raw_value is not None else "-"
            msg_str = err.localized_message()
        elif row_item.warnings:
            warn = row_item.warnings[0]
            field_str = warn.field
            raw_val = str(warn.raw_value) if warn.raw_value is not None else "-"
            msg_str = warn.localized_message()
        elif row_item.is_excluded:
            msg_str = tr("dialog.import_skipped_by_policy")
        else:
            msg_str = tr("dialog.import_status_ok")

        self.lbl_det_field.setText(tr("wizard.details_field", field=field_str))
        self.lbl_det_raw.setText(tr("wizard.details_raw", val=raw_val))
        self.lbl_det_issue.setText(tr("wizard.details_issue", msg=msg_str))
        self.details_box.setVisible(True)

    def isComplete(self) -> bool:
        if not self._result:
            return False
        # Переход возможен, если есть хотя бы одна точка для импорта
        return len(self._result.points) > 0

    def get_result(self) -> ImportResult | None:
        return self._result


# =============================================================================
# Шаг 5: Итоговое подтверждение
# =============================================================================

class SummaryPage(QWizardPage):
    """Страница подтверждения параметров импорта перед выполнением."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setTitle(tr("wizard.page_summary_title"))
        self.setSubTitle(tr("wizard.page_summary_sub"))

        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        self.error_banner = QLabel()
        self.error_banner.setStyleSheet("color: #d32f2f; font-weight: bold; background-color: #ffebee; border: 1px solid #ef5350; border-radius: 4px; padding: 8px;")
        self.error_banner.setVisible(False)
        layout.addWidget(self.error_banner)

        grid = QGridLayout()
        grid.setSpacing(10)

        self.lbl_file = QLabel()
        self.lbl_sheet = QLabel()
        self.lbl_format = QLabel()
        self.lbl_crs = QLabel()
        self.lbl_total = QLabel()
        self.lbl_to_import = QLabel()
        self.lbl_to_skip = QLabel()
        self.lbl_errors = QLabel()
        self.lbl_warnings = QLabel()

        self.lbl_to_import.setStyleSheet("color: #2e7d32; font-weight: bold; font-size: 14px;")
        self.lbl_errors.setStyleSheet("color: #d32f2f; font-weight: bold;")
        self.lbl_warnings.setStyleSheet("color: #ed6c02; font-weight: bold;")

        grid.addWidget(QLabel(tr("wizard.summary_file")), 0, 0)
        grid.addWidget(self.lbl_file, 0, 1)

        grid.addWidget(QLabel(tr("wizard.summary_sheet")), 1, 0)
        grid.addWidget(self.lbl_sheet, 1, 1)

        grid.addWidget(QLabel(tr("wizard.summary_format")), 2, 0)
        grid.addWidget(self.lbl_format, 2, 1)

        grid.addWidget(QLabel(tr("wizard.summary_crs")), 3, 0)
        grid.addWidget(self.lbl_crs, 3, 1)

        grid.addWidget(QLabel(tr("wizard.summary_total")), 4, 0)
        grid.addWidget(self.lbl_total, 4, 1)

        grid.addWidget(QLabel(tr("wizard.summary_to_import")), 5, 0)
        grid.addWidget(self.lbl_to_import, 5, 1)

        grid.addWidget(QLabel(tr("wizard.summary_to_skip")), 6, 0)
        grid.addWidget(self.lbl_to_skip, 6, 1)

        grid.addWidget(QLabel(tr("wizard.summary_errors")), 7, 0)
        grid.addWidget(self.lbl_errors, 7, 1)

        grid.addWidget(QLabel(tr("wizard.summary_warnings")), 8, 0)
        grid.addWidget(self.lbl_warnings, 8, 1)

        self.lbl_new_groups = QLabel()
        grid.addWidget(QLabel(tr("wizard.summary_new_groups")), 9, 0)
        grid.addWidget(self.lbl_new_groups, 9, 1)

        layout.addLayout(grid)
        layout.addStretch(1)

        self._is_stale = False

    def initializePage(self) -> None:
        wizard = self.wizard()
        if not wizard:
            return

        res = wizard.get_validation_result()
        if not res:
            self._is_stale = True
            self.completeChanged.emit()
            return

        # Проверка модификации файла на диске
        path = res.file_path
        if path.exists():
            curr_mtime = path.stat().st_mtime
            curr_size = path.stat().st_size
            if res.file_mtime is not None and (curr_mtime != res.file_mtime or curr_size != res.file_size):
                self._is_stale = True
                self.error_banner.setText(tr("wizard.file_changed_on_disk"))
                self.error_banner.setVisible(True)
                self.completeChanged.emit()
                return

        self._is_stale = False
        self.error_banner.setVisible(False)

        self.lbl_file.setText(str(res.file_path))
        self.lbl_sheet.setText(res.sheet_name or "-")
        self.lbl_format.setText(res.detected_format.value.upper())
        self.lbl_crs.setText(wizard.get_import_options().source_crs if res.detected_format == CoordinateFormat.XY else "EPSG:4326")
        self.lbl_total.setText(str(res.total_rows))
        self.lbl_to_import.setText(str(len(res.points)))
        self.lbl_to_skip.setText(str(res.excluded_rows))
        self.lbl_errors.setText(str(res.invalid_rows))
        self.lbl_warnings.setText(str(len(res.warnings)))
        self.lbl_new_groups.setText(str(len(res.new_group_names)))

        self.completeChanged.emit()

    def isComplete(self) -> bool:
        wizard = self.wizard()
        if not wizard or self._is_stale:
            return False
        res = wizard.get_validation_result()
        return res is not None and len(res.points) > 0


# =============================================================================
# Главный класс ImportWizard
# =============================================================================

class ImportWizard(QWizard):
    """5-шаговый мастер импорта пользовательских точек."""

    def __init__(
        self,
        parent: QWidget | None = None,
        file_path: Path | str | None = None,
        last_directory: str = "",
        existing_points: list[MapPoint] | None = None,
        boundary_geometry: Any = None,
        group_service: Any = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(tr("wizard.import_title"))
        self.setMinimumSize(850, 580)
        self.resize(920, 640)

        self._import_service = ImportService()
        self._presets_service = PresetsService()
        self._existing_points = existing_points or []
        self._boundary_geometry = boundary_geometry
        self._group_service = group_service

        # Страницы
        self.page_source = SourcePage(last_directory=last_directory, parent=self)
        self.page_structure = FileStructurePage(import_service=self._import_service, parent=self)
        self.page_mapping = ColumnMappingPage(
            import_service=self._import_service,
            presets_service=self._presets_service,
            parent=self,
        )
        self.page_validation = ValidationPage(
            import_service=self._import_service,
            get_existing_points=lambda: self._existing_points,
            get_boundary_geometry=lambda: self._boundary_geometry,
            parent=self,
        )
        self.page_summary = SummaryPage(parent=self)

        self.addPage(self.page_source)
        self.addPage(self.page_structure)
        self.addPage(self.page_mapping)
        self.addPage(self.page_validation)
        self.addPage(self.page_summary)

        # Кастомизация кнопок
        self.setButtonText(QWizard.WizardButton.FinishButton, tr("dialog.import_btn_all"))

        if file_path:
            self.page_source.set_file_path(file_path)

        self.restart()

    def get_source_path(self) -> Path | None:
        return self.page_source.get_selected_path()

    def get_group_service(self) -> Any:
        return self._group_service

    def get_detected_headers(self) -> list[str]:
        return self.page_structure.get_detected_headers()

    def get_import_options(self) -> ImportOptions:
        opts = self.page_structure.get_options()
        opts.coordinate_format = self.page_mapping.get_coordinate_format()
        opts.source_crs = self.page_mapping.get_source_crs()
        opts.column_mapping = self.page_mapping.get_column_mapping()
        return opts

    def get_validation_result(self) -> ImportResult | None:
        return self.page_validation.get_result()

    def get_final_points(self) -> list[MapPoint]:
        res = self.get_validation_result()
        return res.points if res else []
