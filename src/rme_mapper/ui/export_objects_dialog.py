"""Диалоговое окно экспорта объектов в форматы CSV, XLSX, TXT, GeoJSON (Stage 22)."""

import logging
import os
from pathlib import Path
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from rme_mapper.i18n import tr
from rme_mapper.models.map_point import MapPoint
from rme_mapper.models.object_export import (
    DEFAULT_FIELD_KEYS,
    EXPORT_FIELDS,
    EXPORT_FIELDS_BY_KEY,
    CsvDelimiter,
    ObjectExportFormat,
    ObjectExportOptions,
    ObjectExportScope,
)
from rme_mapper.services.app_settings_service import AppSettingsService
from rme_mapper.services.object_export_service import ObjectExportService

logger = logging.getLogger("rme_mapper.ui.export_objects_dialog")


class ExportObjectsDialog(QDialog):
    """Диалог настройки параметров экспорта объектов проекта."""

    def __init__(
        self,
        points: list[MapPoint],
        selected_ids: set[str] | list[str],
        group_service: Any = None,
        active_crs: str = "EPSG:3857",
        settings_service: AppSettingsService | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(tr("dialog.export_objects.title"))
        self.setMinimumSize(580, 680)
        self.resize(620, 720)

        self._points = points
        self._selected_ids = set(selected_ids)
        self._group_service = group_service
        self._active_crs = active_crs or "EPSG:3857"
        self._settings = settings_service or AppSettingsService()

        self._field_checkboxes: dict[str, QCheckBox] = {}
        self._target_path: Path | None = None

        self._setup_ui()
        self._load_settings()
        self._update_counts_and_validation()

    def _setup_ui(self) -> None:
        main_layout = QVBoxLayout(self)
        main_layout.setSpacing(10)

        # 1. Формат экспорта
        format_group = QGroupBox(tr("export_objects.format"))
        format_layout = QHBoxLayout(format_group)
        self.format_combo = QComboBox()
        self.format_combo.addItem("CSV (*.csv)", ObjectExportFormat.CSV)
        self.format_combo.addItem("Excel (*.xlsx)", ObjectExportFormat.XLSX)
        self.format_combo.addItem("TXT (*.txt)", ObjectExportFormat.TXT)
        self.format_combo.addItem("GeoJSON (*.geojson)", ObjectExportFormat.GEOJSON)
        self.format_combo.currentIndexChanged.connect(self._on_format_changed)
        format_layout.addWidget(self.format_combo)
        main_layout.addWidget(format_group)

        # 2. Область экспорта (Scope) и счетчик
        scope_group = QGroupBox(tr("export_objects.scope"))
        scope_layout = QVBoxLayout(scope_group)

        self.scope_btn_group = QButtonGroup(self)
        self.radio_all = QRadioButton(tr("export_objects.scope_all"))
        self.radio_selected = QRadioButton(tr("export_objects.scope_selected"))
        self.radio_visible = QRadioButton(tr("export_objects.scope_visible"))

        self.scope_btn_group.addButton(self.radio_all, 0)
        self.scope_btn_group.addButton(self.radio_selected, 1)
        self.scope_btn_group.addButton(self.radio_visible, 2)
        self.radio_all.setChecked(True)

        radio_layout = QHBoxLayout()
        radio_layout.addWidget(self.radio_all)
        radio_layout.addWidget(self.radio_selected)
        radio_layout.addWidget(self.radio_visible)
        radio_layout.addStretch()
        scope_layout.addLayout(radio_layout)

        # Индикатор количества объектов
        counter_layout = QHBoxLayout()
        self.count_label = QLabel()
        self.count_label.setStyleSheet("font-weight: bold; color: #1E293B;")
        counter_layout.addWidget(self.count_label)
        counter_layout.addStretch()
        scope_layout.addLayout(counter_layout)

        self.radio_all.toggled.connect(self._update_counts_and_validation)
        self.radio_selected.toggled.connect(self._update_counts_and_validation)
        self.radio_visible.toggled.connect(self._update_counts_and_validation)
        main_layout.addWidget(scope_group)

        # 3. Выбор полей (Атрибуты)
        fields_group = QGroupBox(tr("export_objects.fields"))
        fields_layout = QVBoxLayout(fields_group)

        btns_layout = QHBoxLayout()
        self.btn_select_all = QPushButton(tr("export_objects.select_all"))
        self.btn_deselect_all = QPushButton(tr("export_objects.deselect_all"))
        self.btn_select_default = QPushButton(tr("export_objects.select_default"))
        self.btn_select_all.clicked.connect(self._select_all_fields)
        self.btn_deselect_all.clicked.connect(self._deselect_all_fields)
        self.btn_select_default.clicked.connect(self._select_default_fields)

        btns_layout.addWidget(self.btn_select_all)
        btns_layout.addWidget(self.btn_deselect_all)
        btns_layout.addWidget(self.btn_select_default)
        btns_layout.addStretch()
        fields_layout.addLayout(btns_layout)

        # Скролл-зона с чекбоксами атрибутов в 2 колонки
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setMaximumHeight(180)
        scroll_widget = QWidget()
        grid = QGridLayout(scroll_widget)
        grid.setSpacing(6)

        for i, field_def in enumerate(EXPORT_FIELDS):
            cb = QCheckBox(tr(field_def.title_key))
            cb.setChecked(field_def.default_enabled)
            row = i // 2
            col = i % 2
            grid.addWidget(cb, row, col)
            self._field_checkboxes[field_def.key] = cb

        scroll_area.setWidget(scroll_widget)
        fields_layout.addWidget(scroll_area)
        main_layout.addWidget(fields_group)

        # 4. Координаты и проекция
        coords_group = QGroupBox(tr("export_objects.coords_mode"))
        coords_grid = QGridLayout(coords_group)

        coords_grid.addWidget(QLabel(tr("export_objects.target_crs")), 0, 0)
        self.crs_combo = QComboBox()
        self.crs_combo.setEditable(True)
        crs_list = ["EPSG:3857", "EPSG:4326", "EPSG:32637", "EPSG:32638", "EPSG:32636", "EPSG:32635"]
        if self._active_crs and self._active_crs not in crs_list:
            crs_list.insert(0, self._active_crs)
        for c in crs_list:
            self.crs_combo.addItem(c)
        self.crs_combo.setCurrentText(self._active_crs)
        coords_grid.addWidget(self.crs_combo, 0, 1)

        coords_grid.addWidget(QLabel(tr("export_objects.dd_precision")), 1, 0)
        self.dd_precision_spin = QSpinBox()
        self.dd_precision_spin.setRange(2, 9)
        self.dd_precision_spin.setValue(6)
        coords_grid.addWidget(self.dd_precision_spin, 1, 1)

        coords_grid.addWidget(QLabel(tr("export_objects.xy_precision")), 2, 0)
        self.xy_precision_spin = QSpinBox()
        self.xy_precision_spin.setRange(0, 6)
        self.xy_precision_spin.setValue(3)
        coords_grid.addWidget(self.xy_precision_spin, 2, 1)

        main_layout.addWidget(coords_group)

        # 5. Опции текстовых форматов (Delimiter, BOM, Headers)
        self.text_options_group = QGroupBox("Параметры формата")
        text_opts_layout = QVBoxLayout(self.text_options_group)

        delim_layout = QHBoxLayout()
        delim_layout.addWidget(QLabel(tr("export_objects.delimiter")))
        self.delim_combo = QComboBox()
        self.delim_combo.addItem(tr("export_objects.delimiter_comma"), CsvDelimiter.COMMA)
        self.delim_combo.addItem(tr("export_objects.delimiter_semicolon"), CsvDelimiter.SEMICOLON)
        self.delim_combo.addItem(tr("export_objects.delimiter_tab"), CsvDelimiter.TAB)
        delim_layout.addWidget(self.delim_combo)
        delim_layout.addStretch()
        text_opts_layout.addLayout(delim_layout)

        self.bom_checkbox = QCheckBox(tr("export_objects.utf8_bom"))
        self.bom_checkbox.setChecked(True)
        text_opts_layout.addWidget(self.bom_checkbox)

        self.headers_checkbox = QCheckBox("Включать строку заголовков")
        self.headers_checkbox.setChecked(True)
        text_opts_layout.addWidget(self.headers_checkbox)

        main_layout.addWidget(self.text_options_group)

        # 6. Путь сохранения файла
        path_group = QGroupBox("Целевой файл")
        path_layout = QHBoxLayout(path_group)
        self.path_edit = QLineEdit()
        self.path_edit.setPlaceholderText("Выберите путь для сохранения...")
        self.btn_browse = QPushButton("Обзор...")
        self.btn_browse.clicked.connect(self._on_browse)
        path_layout.addWidget(self.path_edit)
        path_layout.addWidget(self.btn_browse)
        main_layout.addWidget(path_group)

        # 7. Нижние кнопки управления
        bottom_layout = QHBoxLayout()
        self.btn_export = QPushButton(tr("export_objects.btn_export"))
        self.btn_export.setDefault(True)
        self.btn_export.setStyleSheet("font-weight: bold; padding: 6px 16px;")
        self.btn_export.clicked.connect(self._on_export_clicked)

        self.btn_cancel = QPushButton(tr("export_objects.btn_cancel"))
        self.btn_cancel.clicked.connect(self.reject)

        bottom_layout.addStretch()
        bottom_layout.addWidget(self.btn_cancel)
        bottom_layout.addWidget(self.btn_export)
        main_layout.addLayout(bottom_layout)

    def _get_current_scope(self) -> ObjectExportScope:
        if self.radio_selected.isChecked():
            return ObjectExportScope.SELECTED
        elif self.radio_visible.isChecked():
            return ObjectExportScope.VISIBLE
        return ObjectExportScope.ALL

    def _update_counts_and_validation(self) -> None:
        scope = self._get_current_scope()
        pts = ObjectExportService.filter_points(
            self._points,
            scope,
            selected_ids=self._selected_ids,
            group_service=self._group_service,
        )
        count = len(pts)
        if count == 0:
            self.count_label.setText(f"{tr('export_objects.count_label', count=0)} — {tr('export_objects.no_objects')}")
            self.count_label.setStyleSheet("font-weight: bold; color: #DC2626;")
            self.btn_export.setEnabled(False)
        else:
            self.count_label.setText(tr("export_objects.count_label", count=count))
            self.count_label.setStyleSheet("font-weight: bold; color: #1E293B;")
            self.btn_export.setEnabled(True)

    def _get_current_format(self) -> ObjectExportFormat:
        raw = self.format_combo.currentData()
        val = raw.value if hasattr(raw, "value") else str(raw)
        return ObjectExportFormat(val)

    def _get_current_delimiter(self) -> CsvDelimiter:
        raw = self.delim_combo.currentData()
        val = raw.value if hasattr(raw, "value") else str(raw)
        return CsvDelimiter(val)

    def _on_format_changed(self) -> None:
        fmt = self._get_current_format()
        is_tabular = fmt in (ObjectExportFormat.CSV, ObjectExportFormat.TXT)
        self.text_options_group.setVisible(is_tabular)

        # Если переключились на TXT и текущий разделитель COMMA, предлагаем TAB по умолчанию.
        # Если уже стоит TAB или SEMICOLON (пользовательский выбор), не сбрасываем!
        if fmt == ObjectExportFormat.TXT:
            if self._get_current_delimiter() == CsvDelimiter.COMMA:
                idx = self.delim_combo.findData(CsvDelimiter.TAB)
                if idx >= 0:
                    self.delim_combo.setCurrentIndex(idx)
        elif fmt == ObjectExportFormat.CSV:
            if self._get_current_delimiter() == CsvDelimiter.TAB:
                idx = self.delim_combo.findData(CsvDelimiter.COMMA)
                if idx >= 0:
                    self.delim_combo.setCurrentIndex(idx)

        # Обновление расширения пути, если путь уже указан
        current_path = self.path_edit.text().strip()
        if current_path:
            p = Path(current_path)
            new_ext = f".{fmt.value}"
            if p.suffix.lower() != new_ext:
                self.path_edit.setText(str(p.with_suffix(new_ext)))

    def _select_all_fields(self) -> None:
        for cb in self._field_checkboxes.values():
            cb.setChecked(True)

    def _deselect_all_fields(self) -> None:
        for cb in self._field_checkboxes.values():
            cb.setChecked(False)

    def _select_default_fields(self) -> None:
        defaults = set(DEFAULT_FIELD_KEYS)
        for key, cb in self._field_checkboxes.items():
            cb.setChecked(key in defaults)

    def _get_filter_for_format(self, fmt: ObjectExportFormat) -> str:
        if fmt == ObjectExportFormat.CSV:
            return f"{tr('export_objects.filter_csv')};;Все файлы (*.*)"
        elif fmt == ObjectExportFormat.XLSX:
            return f"{tr('export_objects.filter_xlsx')};;Все файлы (*.*)"
        elif fmt == ObjectExportFormat.TXT:
            return f"{tr('export_objects.filter_txt')};;Все файлы (*.*)"
        elif fmt == ObjectExportFormat.GEOJSON:
            return f"{tr('export_objects.filter_geojson')};;Все файлы (*.*)"
        return "Все файлы (*.*)"

    def _on_browse(self) -> None:
        fmt = self._get_current_format()
        default_dir = self._settings.get_last_export_directory(check_exists=True)
        default_name = f"objects_export.{fmt.value}"
        initial_path = str(Path(default_dir) / default_name) if default_dir else default_name

        file_filter = self._get_filter_for_format(fmt)
        chosen, _ = QFileDialog.getSaveFileName(
            self,
            tr("export_objects.save_title"),
            initial_path,
            file_filter,
        )
        if chosen:
            # Гарантия наличия корректного расширения
            p = Path(chosen)
            if not p.suffix:
                p = p.with_suffix(f".{fmt.value}")
            self.path_edit.setText(str(p))

    def _load_settings(self) -> None:
        # 1. Формат
        saved_fmt = self._settings.get_object_export_format("csv")
        for i in range(self.format_combo.count()):
            d = self.format_combo.itemData(i)
            d_val = d.value if hasattr(d, "value") else str(d)
            if d_val == saved_fmt:
                self.format_combo.setCurrentIndex(i)
                break

        # 2. Scope
        saved_scope = self._settings.get_object_export_scope("all")
        if saved_scope == "selected" and self._selected_ids:
            self.radio_selected.setChecked(True)
        elif saved_scope == "visible":
            self.radio_visible.setChecked(True)
        else:
            self.radio_all.setChecked(True)

        # 3. Поля
        saved_fields = self._settings.get_object_export_fields(None)
        if saved_fields is not None:
            field_set = set(saved_fields)
            for k, cb in self._field_checkboxes.items():
                cb.setChecked(k in field_set)
        else:
            self._select_default_fields()

        # 4. CRS и точность
        saved_crs = self._settings.get_object_export_target_crs(self._active_crs)
        self.crs_combo.setCurrentText(saved_crs)
        saved_dd_prec = self._settings.get_object_export_dd_precision(6)
        self.dd_precision_spin.setValue(saved_dd_prec)

        # 5. Разделитель и BOM
        saved_delim = self._settings.get_object_export_delimiter(",")
        for i in range(self.delim_combo.count()):
            d = self.delim_combo.itemData(i)
            d_val = d.value if hasattr(d, "value") else str(d)
            if d_val == saved_delim:
                self.delim_combo.setCurrentIndex(i)
                break
        self.bom_checkbox.setChecked(self._settings.get_object_export_bom(True))
        is_tabular = self._get_current_format() in (ObjectExportFormat.CSV, ObjectExportFormat.TXT)
        self.text_options_group.setVisible(is_tabular)

    def _save_settings(self) -> None:
        fmt = self._get_current_format()
        self._settings.set_object_export_format(fmt.value)

        scope = self._get_current_scope()
        self._settings.set_object_export_scope(scope.value)

        selected_fields = [k for k, cb in self._field_checkboxes.items() if cb.isChecked()]
        self._settings.set_object_export_fields(selected_fields)

        self._settings.set_object_export_target_crs(self.crs_combo.currentText().strip())
        self._settings.set_object_export_dd_precision(self.dd_precision_spin.value())

        delim = self._get_current_delimiter()
        self._settings.set_object_export_delimiter(delim.value)
        self._settings.set_object_export_bom(self.bom_checkbox.isChecked())

        if self._target_path:
            self._settings.set_last_export_directory(str(self._target_path.parent))

    def _on_export_clicked(self) -> None:
        target_str = self.path_edit.text().strip()
        if not target_str:
            QMessageBox.warning(self, "Внимание", "Пожалуйста, укажите путь к файлу для сохранения.")
            self._on_browse()
            return

        fmt = self._get_current_format()
        target_path = Path(target_str)
        if not target_path.suffix:
            target_path = target_path.with_suffix(f".{fmt.value}")

        # Проверка Target CRS при выборе спроецированных координат (X/Y/CRS)
        needs_projected = any(
            self._field_checkboxes[k].isChecked()
            for k in ("x", "y", "crs")
            if k in self._field_checkboxes
        )
        if needs_projected:
            target_crs_str = self.crs_combo.currentText().strip()
            if not target_crs_str:
                QMessageBox.warning(
                    self,
                    tr("dialog.export_objects.title"),
                    tr("export_objects.crs_empty_error"),
                )
                return
            try:
                import pyproj
                crs_obj = pyproj.CRS.from_user_input(target_crs_str)
                _ = pyproj.Transformer.from_crs("EPSG:4326", crs_obj, always_xy=True)
            except Exception as err:
                QMessageBox.warning(
                    self,
                    tr("dialog.export_objects.title"),
                    tr("export_objects.crs_invalid_error", crs=target_crs_str, error=str(err)),
                )
                return

        if target_path.exists():
            confirm = QMessageBox.question(
                self,
                "Подтверждение перезаписи",
                tr("export_objects.overwrite_confirm", name=target_path.name),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if confirm != QMessageBox.StandardButton.Yes:
                return

        self._target_path = target_path
        self._save_settings()
        self.accept()

    def get_export_options(self) -> tuple[ObjectExportOptions, Path]:
        """Возвращает сформированные опции экспорта и путь к файлу."""
        if not self._target_path:
            target_str = self.path_edit.text().strip()
            self._target_path = Path(target_str)

        fmt = self._get_current_format()
        scope = self._get_current_scope()
        selected_fields = [k for k, cb in self._field_checkboxes.items() if cb.isChecked()]
        delim = self._get_current_delimiter()

        options = ObjectExportOptions(
            format=fmt,
            scope=scope,
            field_keys=selected_fields,
            target_crs=self.crs_combo.currentText().strip() or "EPSG:3857",
            dd_precision=self.dd_precision_spin.value(),
            projected_precision=self.xy_precision_spin.value(),
            delimiter=delim,
            utf8_bom=self.bom_checkbox.isChecked(),
            include_internal_id=("internal_id" in selected_fields),
            include_headers=self.headers_checkbox.isChecked(),
        )

        return options, self._target_path
