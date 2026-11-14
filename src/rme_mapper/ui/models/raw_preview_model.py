"""Модель данных для предпросмотра сырых строк таблицы (RawPreviewModel)."""
from __future__ import annotations


from typing import Any
from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt
from PySide6.QtGui import QBrush, QColor, QFont
from rme_mapper.ui.theme_manager import get_theme_manager


class RawPreviewModel(QAbstractTableModel):
    """Легковесная табличная модель для отображения первых N строк файла."""

    def __init__(self, parent: Any = None) -> None:
        super().__init__(parent)
        self._rows: list[list[str]] = []
        self._header_row: int = 1
        self._col_count: int = 0

    def set_data(self, rows: list[list[str]], header_row: int = 1) -> None:
        """Обновление содержимого таблицы и выбранной строки заголовков."""
        self.beginResetModel()
        self._rows = rows
        self._header_row = header_row
        self._col_count = max((len(r) for r in rows), default=0)
        self.endResetModel()

    def set_header_row(self, header_row: int) -> None:
        """Изменение подсвечиваемой строки заголовка."""
        self._header_row = header_row
        if self._rows:
            top_left = self.index(0, 0)
            bottom_right = self.index(len(self._rows) - 1, max(0, self._col_count - 1))
            self.dataChanged.emit(top_left, bottom_right, [Qt.ItemDataRole.BackgroundRole, Qt.ItemDataRole.FontRole])

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
        if parent.isValid():
            return 0
        return len(self._rows)

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:
        if parent.isValid():
            return 0
        return self._col_count

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole) -> Any:
        if not index.isValid():
            return None

        row_idx = index.row()
        col_idx = index.column()

        if row_idx >= len(self._rows) or col_idx >= len(self._rows[row_idx]):
            return None

        val = self._rows[row_idx][col_idx]
        is_header = (row_idx + 1) == self._header_row

        if role == Qt.ItemDataRole.DisplayRole:
            return val

        if role == Qt.ItemDataRole.BackgroundRole:
            if is_header:
                return QBrush(QColor(get_theme_manager().get_palette().HEADER_HIGHLIGHT_BG))
            return None

        if role == Qt.ItemDataRole.FontRole:
            if is_header:
                font = QFont()
                font.setBold(True)
                return font
            return None

        if role == Qt.ItemDataRole.TextAlignmentRole:
            return int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)

        return None

    def headerData(self, section: int, orientation: Qt.Orientation, role: int = Qt.ItemDataRole.DisplayRole) -> Any:
        if role == Qt.ItemDataRole.DisplayRole:
            if orientation == Qt.Orientation.Horizontal:
                return f"#{section + 1}"
            else:
                return str(section + 1)
        return None
