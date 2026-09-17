"""Панель управления пользовательскими точками и таблицей точек."""

import logging
from typing import Any

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from rme_mapper.i18n import tr

logger = logging.getLogger("rme_mapper.ui.panels.points_panel")


class PointsPanel(QWidget):
    """Панель со списком точек, кнопками управления, поиском и таблицей."""

    add_clicked = Signal()
    edit_clicked = Signal()
    delete_clicked = Signal()
    row_double_clicked = Signal(int, int)
    selection_changed = Signal()
    custom_context_menu_requested = Signal(object)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("pointsPanel")

        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        # Заголовок блока
        points_header_layout = QHBoxLayout()
        self.title_label = QLabel()
        points_font = QFont()
        points_font.setBold(True)
        points_font.setPointSize(11)
        self.title_label.setFont(points_font)
        points_header_layout.addWidget(self.title_label)
        points_header_layout.addStretch()
        layout.addLayout(points_header_layout)

        # Кнопки добавления, редактирования и удаления точки
        btn_row_layout = QHBoxLayout()
        self.btn_add = QPushButton(self)
        self.btn_add.setObjectName("btnAddPoint")
        self.btn_add.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_add.clicked.connect(self.add_clicked.emit)
        btn_row_layout.addWidget(self.btn_add)

        self.btn_edit = QPushButton(self)
        self.btn_edit.setObjectName("btnEditPoint")
        self.btn_edit.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_edit.setEnabled(False)
        self.btn_edit.clicked.connect(self.edit_clicked.emit)
        btn_row_layout.addWidget(self.btn_edit)

        self.btn_delete = QPushButton(self)
        self.btn_delete.setObjectName("btnDeletePoint")
        self.btn_delete.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_delete.setEnabled(False)
        self.btn_delete.clicked.connect(self.delete_clicked.emit)
        btn_row_layout.addWidget(self.btn_delete)

        layout.addLayout(btn_row_layout)

        # Поле поиска по названию точки
        self.search_input = QLineEdit(self)
        self.search_input.setObjectName("searchPointInput")
        self.search_input.setClearButtonEnabled(True)
        self.search_input.textChanged.connect(self._on_search_text_changed)
        layout.addWidget(self.search_input)

        # Таблица точек
        self.points_table = QTableWidget(0, 6, self)
        self.points_table.setObjectName("pointsTable")
        self.points_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.points_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.points_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.points_table.verticalHeader().setVisible(False)

        header = self.points_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(5, QHeaderView.ResizeMode.ResizeToContents)

        self.points_table.cellDoubleClicked.connect(self.row_double_clicked.emit)
        self.points_table.itemSelectionChanged.connect(self.selection_changed.emit)
        self.points_table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.points_table.customContextMenuRequested.connect(self.custom_context_menu_requested.emit)

        # Перехват клавиш для таблицы
        orig_table_key_press = self.points_table.keyPressEvent

        def table_key_press(event: Any) -> None:
            if event.key() == Qt.Key.Key_Insert:
                self.add_clicked.emit()
                event.accept()
                return
            if event.key() == Qt.Key.Key_F2:
                if self.btn_edit.isEnabled():
                    self.edit_clicked.emit()
                event.accept()
                return
            if event.key() == Qt.Key.Key_Delete:
                if self.btn_delete.isEnabled():
                    self.delete_clicked.emit()
                event.accept()
                return
            orig_table_key_press(event)

        self.points_table.keyPressEvent = table_key_press

        layout.addWidget(self.points_table, stretch=1)

        self.retranslate_ui()

    def keyPressEvent(self, event: Any) -> None:
        """Обработка горячих клавиш панели."""
        if event.key() == Qt.Key.Key_Insert:
            self.add_clicked.emit()
            event.accept()
            return
        if event.key() == Qt.Key.Key_F2:
            if self.btn_edit.isEnabled():
                self.edit_clicked.emit()
            event.accept()
            return
        if event.key() == Qt.Key.Key_Delete and not self.search_input.hasFocus():
            if self.btn_delete.isEnabled():
                self.delete_clicked.emit()
            event.accept()
            return
        super().keyPressEvent(event)

    def _on_search_text_changed(self, text: str) -> None:
        """Фильтрация строк таблицы по введенному названию."""
        query = text.strip().lower()
        for r in range(self.points_table.rowCount()):
            item = self.points_table.item(r, 1)
            name = item.text().lower() if item else ""
            matches = (not query) or (query in name)
            self.points_table.setRowHidden(r, not matches)

    def _apply_filter_to_row(self, row: int) -> None:
        query = self.search_input.text().strip().lower()
        if not query:
            self.points_table.setRowHidden(row, False)
            return
        item = self.points_table.item(row, 1)
        name = item.text().lower() if item else ""
        self.points_table.setRowHidden(row, query not in name)

    def retranslate_ui(self) -> None:
        """Обновление локализованных строк панели и таблицы."""
        self.title_label.setText(tr("panel.points"))
        self.btn_add.setText(tr("btn.add_point"))
        self.btn_edit.setText(tr("btn.edit_point"))
        self.btn_delete.setText(tr("btn.delete_point"))
        if hasattr(self, "search_input"):
            self.search_input.setPlaceholderText(tr("search.placeholder"))
        self.points_table.setHorizontalHeaderLabels([
            tr("table.col_index"),
            tr("table.col_name"),
            tr("table.col_lat"),
            tr("table.col_lon"),
            tr("table.col_shape"),
            tr("table.col_radius"),
        ])


    def set_buttons_enabled(
        self,
        add: bool | None = None,
        edit: bool | None = None,
        delete: bool | None = None,
    ) -> None:
        """Управление активностью кнопок действий."""
        if add is not None:
            self.btn_add.setEnabled(add)
        if edit is not None:
            self.btn_edit.setEnabled(edit)
        if delete is not None:
            self.btn_delete.setEnabled(delete)

    def add_row(
        self,
        num: str,
        name: str,
        lat: str,
        lon: str,
        shape: str,
        radius: str,
    ) -> int:
        """Добавление строки в таблицу."""
        row = self.points_table.rowCount()
        self.points_table.insertRow(row)

        num_item = QTableWidgetItem(num)
        num_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        name_item = QTableWidgetItem(name)
        lat_item = QTableWidgetItem(lat)
        lon_item = QTableWidgetItem(lon)
        shape_item = QTableWidgetItem(shape)
        radius_item = QTableWidgetItem(radius)

        self.points_table.setItem(row, 0, num_item)
        self.points_table.setItem(row, 1, name_item)
        self.points_table.setItem(row, 2, lat_item)
        self.points_table.setItem(row, 3, lon_item)
        self.points_table.setItem(row, 4, shape_item)
        self.points_table.setItem(row, 5, radius_item)
        self._apply_filter_to_row(row)
        return row

    def update_row(
        self,
        row: int,
        name: str,
        lat: str,
        lon: str,
        shape: str,
        radius: str,
    ) -> None:
        """Обновление значений в строке таблицы."""
        if 0 <= row < self.points_table.rowCount():
            self.points_table.item(row, 1).setText(name)
            self.points_table.item(row, 2).setText(lat)
            self.points_table.item(row, 3).setText(lon)
            self.points_table.item(row, 4).setText(shape)
            self.points_table.item(row, 5).setText(radius)
            self._apply_filter_to_row(row)


    def remove_row(self, row: int) -> None:
        """Удаление строки из таблицы и пересчет нумерации."""
        if 0 <= row < self.points_table.rowCount():
            self.points_table.removeRow(row)
            for r in range(self.points_table.rowCount()):
                item = self.points_table.item(r, 0)
                if item:
                    item.setText(str(r + 1))

    def clear_table(self) -> None:
        """Полная очистка строк таблицы."""
        self.points_table.setRowCount(0)

    def selected_row(self) -> int | None:
        """Индекс первой выбранной строки или None."""
        rows = self.points_table.selectionModel().selectedRows()
        return rows[0].row() if rows else None
