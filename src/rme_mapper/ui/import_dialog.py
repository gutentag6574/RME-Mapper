"""Базовый диалог импорта точек из файлов XLSX, CSV и TXT.

Предоставляет выбор файла, режима координат (Auto/DD/DMS), отображение сводки
(всего/корректных/ошибок/предупреждений) и список первых обнаруженных ошибок.
"""
from __future__ import annotations


from pathlib import Path
from typing import Any
import logging

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QButtonGroup,
    QDialog,
    QFileDialog,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QRadioButton,
    QVBoxLayout,
    QWidget,
)

from rme_mapper.i18n import tr
from rme_mapper.importers.import_service import ImportService
from rme_mapper.importers.models import CoordinateFormat, ImportOptions, ImportResult
from rme_mapper.models.map_point import MapPoint

logger = logging.getLogger("rme_mapper.ui.import_dialog")


class ImportDialog(QDialog):
    """Диалоговое окно предварительного просмотра и запуска пакетного импорта точек."""

    def __init__(
        self,
        parent: QWidget | None = None,
        file_path: Path | str | None = None,
        initial_format: CoordinateFormat = CoordinateFormat.AUTO,
        last_directory: str = "",
        boundary_geometry: Any = None,
        current_project_points_count: int = 0,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(tr("dialog.import_title"))
        self.setMinimumWidth(560)
        self.resize(600, 520)

        self._last_directory = last_directory
        self._boundary_geometry = boundary_geometry
        self._current_project_points_count = current_project_points_count
        self._import_service = ImportService()
        self._result: ImportResult | None = None

        self._init_ui(file_path, initial_format)

        if file_path:
            p = Path(file_path)
            if p.exists() and p.is_file():
                self.file_input.setText(str(p))
                self._analyze_file()

    def _init_ui(self, initial_path: Path | str | None, initial_format: CoordinateFormat) -> None:
        main_layout = QVBoxLayout(self)
        main_layout.setSpacing(12)
        main_layout.setContentsMargins(16, 16, 16, 16)

        # 1. Секция выбора файла
        file_group = QGroupBox(tr("dialog.import_file"))
        file_layout = QHBoxLayout(file_group)

        self.file_input = QLineEdit()
        self.file_input.setReadOnly(True)
        self.file_input.setPlaceholderText(tr("dialog.import_no_file_selected"))
        file_layout.addWidget(self.file_input, stretch=1)

        self.btn_browse = QPushButton(tr("dialog.import_browse"))
        self.btn_browse.clicked.connect(self._on_browse_clicked)
        file_layout.addWidget(self.btn_browse)

        main_layout.addWidget(file_group)

        # 2. Секция выбора формата координат
        format_group = QGroupBox(tr("dialog.import_coord_format"))
        format_layout = QHBoxLayout(format_group)

        self.btn_group_format = QButtonGroup(self)

        self.rb_auto = QRadioButton(tr("dialog.import_format_auto"))
        self.rb_dd = QRadioButton(tr("dialog.import_format_dd"))
        self.rb_dms = QRadioButton(tr("dialog.import_format_dms"))

        self.btn_group_format.addButton(self.rb_auto)
        self.btn_group_format.addButton(self.rb_dd)
        self.btn_group_format.addButton(self.rb_dms)

        format_layout.addWidget(self.rb_auto)
        format_layout.addWidget(self.rb_dd)
        format_layout.addWidget(self.rb_dms)

        if initial_format == CoordinateFormat.DD:
            self.rb_dd.setChecked(True)
        elif initial_format == CoordinateFormat.DMS:
            self.rb_dms.setChecked(True)
        else:
            self.rb_auto.setChecked(True)

        self.rb_auto.toggled.connect(self._on_format_toggled)
        self.rb_dd.toggled.connect(self._on_format_toggled)
        self.rb_dms.toggled.connect(self._on_format_toggled)

        main_layout.addWidget(format_group)

        # 3. Секция сводки
        self.summary_group = QGroupBox(tr("dialog.import_summary"))
        summary_layout = QVBoxLayout(self.summary_group)
        summary_layout.setSpacing(6)

        stats_row = QHBoxLayout()
        self.lbl_total = QLabel(tr("dialog.import_total_rows", count=0))
        self.lbl_valid = QLabel(tr("dialog.import_valid_rows", count=0))
        self.lbl_valid.setStyleSheet("color: #15803D; font-weight: bold;")
        self.lbl_invalid = QLabel(tr("dialog.import_invalid_rows", count=0))
        self.lbl_invalid.setStyleSheet("color: #DC2626; font-weight: bold;")
        self.lbl_warnings = QLabel(tr("dialog.import_warnings", count=0))
        self.lbl_warnings.setStyleSheet("color: #D97706;")

        stats_row.addWidget(self.lbl_total)
        stats_row.addWidget(self.lbl_valid)
        stats_row.addWidget(self.lbl_invalid)
        stats_row.addWidget(self.lbl_warnings)
        stats_row.addStretch()
        summary_layout.addLayout(stats_row)

        self.lbl_meta = QLabel("")
        self.lbl_meta.setStyleSheet("color: #6B7280; font-size: 11px;")
        summary_layout.addWidget(self.lbl_meta)

        main_layout.addWidget(self.summary_group)

        # 4. Список ошибок и предупреждений
        self.lbl_errors_title = QLabel(tr("dialog.import_errors_list", limit=20))
        self.lbl_errors_title.setStyleSheet("font-weight: 500;")
        main_layout.addWidget(self.lbl_errors_title)

        self.errors_list = QListWidget()
        self.errors_list.setSelectionMode(QListWidget.SelectionMode.NoSelection)
        self.errors_list.setStyleSheet(
            "QListWidget { border: 1px solid #D9DDE3; border-radius: 4px; background: #FFFFFF; font-size: 12px; }"
        )
        main_layout.addWidget(self.errors_list, stretch=1)

        # 5. Кнопки действий
        buttons_layout = QHBoxLayout()
        buttons_layout.addStretch()

        self.btn_cancel = QPushButton(tr("btn.cancel"))
        self.btn_cancel.clicked.connect(self.reject)
        buttons_layout.addWidget(self.btn_cancel)

        self.btn_import = QPushButton(tr("dialog.import_btn_all"))
        self.btn_import.setEnabled(False)
        self.btn_import.setDefault(True)
        self.btn_import.clicked.connect(self.accept)
        buttons_layout.addWidget(self.btn_import)

        main_layout.addLayout(buttons_layout)

    def _get_selected_format(self) -> CoordinateFormat:
        if self.rb_dd.isChecked():
            return CoordinateFormat.DD
        if self.rb_dms.isChecked():
            return CoordinateFormat.DMS
        return CoordinateFormat.AUTO

    def _on_browse_clicked(self) -> None:
        start_dir = self._last_directory or str(Path.home())
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            tr("dialog.import_title"),
            start_dir,
            tr("dialog.import_file_filter"),
        )
        if file_path:
            self.file_input.setText(file_path)
            self._analyze_file()

    def _on_format_toggled(self, checked: bool) -> None:
        if checked and self.file_input.text():
            self._analyze_file()

    def _analyze_file(self) -> None:
        """Запуск анализа и валидации файла через ImportService."""
        path_str = self.file_input.text().strip()
        if not path_str:
            return

        path = Path(path_str)
        if not path.exists():
            return

        fmt = self._get_selected_format()
        opts = ImportOptions(
            coordinate_format=fmt,
            boundary_geometry=self._boundary_geometry,
        )

        self._result = self._import_service.validate_file(
            path,
            options=opts,
            current_project_points_count=self._current_project_points_count,
        )
        self._update_ui_with_result(self._result)

    def _update_ui_with_result(self, result: ImportResult) -> None:
        """Обновление элементов интерфейса по результату валидации."""
        self.lbl_total.setText(tr("dialog.import_total_rows", count=result.total_rows))
        self.lbl_valid.setText(tr("dialog.import_valid_rows", count=result.valid_rows))
        self.lbl_invalid.setText(tr("dialog.import_invalid_rows", count=result.invalid_rows))
        self.lbl_warnings.setText(tr("dialog.import_warnings", count=len(result.warnings)))

        # Мета-информация
        meta_parts: list[str] = []
        if result.detected_encoding:
            meta_parts.append(tr("dialog.import_encoding", enc=result.detected_encoding))
        if result.detected_delimiter:
            delim_name = {",": ",", ";": ";", "\t": "TAB"}.get(result.detected_delimiter, result.detected_delimiter)
            meta_parts.append(tr("dialog.import_delimiter", delim=delim_name))
        if result.sheet_name:
            meta_parts.append(tr("dialog.import_sheet", sheet=result.sheet_name))
        self.lbl_meta.setText("  •  ".join(meta_parts))

        # Список ошибок
        self.errors_list.clear()
        combined_items: list[tuple[str, str, str]] = []  # (kind, prefix, text)

        for err in result.errors[:20]:
            row_prefix = f"[{tr('table.col_index')} {err.row_number}]" if err.row_number > 0 else "[Файл]"
            field_prefix = f" ({err.field})" if err.field else ""
            combined_items.append(("error", f"❌ {row_prefix}{field_prefix}:", err.localized_message()))

        rem = 20 - len(combined_items)
        if rem > 0:
            for warn in result.warnings[:rem]:
                row_prefix = f"[{tr('table.col_index')} {warn.row_number}]" if warn.row_number > 0 else "[Файл]"
                field_prefix = f" ({warn.field})" if warn.field else ""
                combined_items.append(("warning", f"⚠️ {row_prefix}{field_prefix}:", warn.localized_message()))

        if not combined_items:
            it = QListWidgetItem("✅ Все проверенные строки корректны.")
            it.setForeground(Qt.GlobalColor.darkGreen)
            self.errors_list.addItem(it)
        else:
            for kind, prefix, msg in combined_items:
                it = QListWidgetItem(f"{prefix} {msg}")
                if kind == "error":
                    it.setForeground(Qt.GlobalColor.red)
                else:
                    it.setForeground(Qt.GlobalColor.darkYellow)
                self.errors_list.addItem(it)

        # Управление кнопкой импорта
        if result.valid_rows == 0:
            self.btn_import.setEnabled(False)
            self.btn_import.setText(tr("dialog.import_btn_nothing"))
        elif result.invalid_rows > 0:
            self.btn_import.setEnabled(True)
            self.btn_import.setText(tr("dialog.import_btn_valid_only", count=result.valid_rows))
        else:
            self.btn_import.setEnabled(True)
            self.btn_import.setText(tr("dialog.import_btn_all"))

    @property
    def result(self) -> ImportResult | None:
        """Полученный результат анализа файла."""
        return self._result

    def get_valid_points(self) -> list[MapPoint]:
        """Список валидных точек, готовых к добавлению в проект."""
        if self._result:
            return self._result.points
        return []
