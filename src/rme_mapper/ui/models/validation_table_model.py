"""Модель данных для таблицы результатов валидации импорта (ValidationTableModel)."""
from __future__ import annotations


from typing import Any
from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt
from PySide6.QtGui import QBrush, QColor

from rme_mapper.i18n import tr
from rme_mapper.importers.models import ImportRow


class ValidationTableModel(QAbstractTableModel):
    """Табличная модель для отображения и фильтрации результатов построчной валидации."""

    COL_ROW = 0
    COL_STATUS = 1
    COL_NAME = 2
    COL_COORDS = 3
    COL_ISSUE = 4
    COL_COUNT = 5

    def __init__(self, parent: Any = None) -> None:
        super().__init__(parent)
        self._all_rows: list[ImportRow] = []
        self._filtered_indices: list[int] = []
        self._filter_type: str = "all"  # "all", "valid", "warnings", "errors"
        self._search_query: str = ""

    def set_rows(self, rows: list[ImportRow]) -> None:
        """Установка нового набора строк валидации."""
        self.beginResetModel()
        self._all_rows = rows
        self._apply_filter_and_search()
        self.endResetModel()

    def set_filter(self, filter_type: str) -> None:
        """Установка типа фильтра: 'all', 'valid', 'warnings', 'errors'."""
        if self._filter_type != filter_type:
            self.beginResetModel()
            self._filter_type = filter_type
            self._apply_filter_and_search()
            self.endResetModel()

    def set_search_query(self, query: str) -> None:
        """Поиск по номеру строки, названию или тексту проблемы."""
        clean_q = query.strip().lower()
        if self._search_query != clean_q:
            self.beginResetModel()
            self._search_query = clean_q
            self._apply_filter_and_search()
            self.endResetModel()

    def _apply_filter_and_search(self) -> None:
        indices: list[int] = []
        q = self._search_query

        for i, row in enumerate(self._all_rows):
            # 1. Проверка фильтра категории
            if self._filter_type == "valid":
                if not row.is_valid or row.is_excluded:
                    continue
            elif self._filter_type == "warnings":
                if not row.warnings or not row.is_valid:
                    continue
            elif self._filter_type == "errors":
                if row.is_valid:
                    continue

            # 2. Проверка поискового запроса
            if q:
                row_str = str(row.row_number)
                name_str = (row.point.name if row.point else str(row.raw_data.get("name", ""))).lower()
                issue_str = ""
                if row.errors:
                    issue_str = " ".join(e.localized_message().lower() for e in row.errors)
                elif row.warnings:
                    issue_str = " ".join(w.localized_message().lower() for w in row.warnings)

                if q not in row_str and q not in name_str and q not in issue_str:
                    continue

            indices.append(i)

        self._filtered_indices = indices

    def get_row_item(self, model_row_idx: int) -> ImportRow | None:
        """Получение объекта ImportRow по визуальному индексу строки модели."""
        if 0 <= model_row_idx < len(self._filtered_indices):
            real_idx = self._filtered_indices[model_row_idx]
            return self._all_rows[real_idx]
        return None

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
        if parent.isValid():
            return 0
        return len(self._filtered_indices)

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:
        if parent.isValid():
            return 0
        return self.COL_COUNT

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole) -> Any:
        if not index.isValid():
            return None

        row_item = self.get_row_item(index.row())
        if not row_item:
            return None

        col = index.column()

        if role == Qt.ItemDataRole.DisplayRole:
            if col == self.COL_ROW:
                return str(row_item.row_number)
            elif col == self.COL_STATUS:
                if not row_item.is_valid:
                    return f"✕ {tr('dialog.import_status_error')}"
                elif row_item.is_excluded:
                    return f"⊘ {tr('dialog.import_status_skipped')}"
                elif row_item.warnings:
                    return f"⚠ {tr('dialog.import_status_warning')}"
                else:
                    return f"✓ {tr('dialog.import_status_ok')}"
            elif col == self.COL_NAME:
                if row_item.point:
                    return row_item.point.name
                raw_n = row_item.raw_data.get("name")
                return str(raw_n) if raw_n is not None else ""
            elif col == self.COL_COORDS:
                return row_item.formatted_coords
            elif col == self.COL_ISSUE:
                if row_item.errors:
                    return row_item.errors[0].localized_message()
                elif row_item.warnings:
                    return row_item.warnings[0].localized_message()
                elif row_item.is_excluded:
                    return tr("dialog.import_skipped_by_policy")
                return ""

        if role == Qt.ItemDataRole.ForegroundRole:
            if col == self.COL_STATUS:
                if not row_item.is_valid:
                    return QBrush(QColor(220, 40, 40))
                elif row_item.is_excluded:
                    return QBrush(QColor(120, 120, 120))
                elif row_item.warnings:
                    return QBrush(QColor(200, 130, 20))
                else:
                    return QBrush(QColor(30, 140, 50))

        if role == Qt.ItemDataRole.TextAlignmentRole:
            if col in (self.COL_ROW, self.COL_STATUS):
                return int(Qt.AlignmentFlag.AlignCenter)
            return int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)

        return None

    def headerData(self, section: int, orientation: Qt.Orientation, role: int = Qt.ItemDataRole.DisplayRole) -> Any:
        if role == Qt.ItemDataRole.DisplayRole and orientation == Qt.Orientation.Horizontal:
            headers = [
                tr("dialog.import_col_row"),
                tr("dialog.import_col_status"),
                tr("dialog.import_col_name"),
                tr("dialog.import_col_coords"),
                tr("dialog.import_col_issue"),
            ]
            if 0 <= section < len(headers):
                return headers[section]
        return None
