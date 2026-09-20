"""Панель управления пользовательскими точками и таблицей точек."""

import logging
from typing import Any

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QFont
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
    count_changed = Signal(int, int)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("pointsPanel")

        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        # 1. Заголовок блока и счетчик точек
        points_header_layout = QHBoxLayout()
        self.title_label = QLabel()
        points_font = QFont()
        points_font.setBold(True)
        points_font.setPointSize(11)
        self.title_label.setFont(points_font)
        points_header_layout.addWidget(self.title_label)
        points_header_layout.addStretch()

        self.count_label = QLabel()
        self.count_label.setObjectName("pointCountLabel")
        count_font = QFont()
        count_font.setPointSize(10)
        self.count_label.setFont(count_font)
        self.count_label.setStyleSheet("color: #6B7280;")
        points_header_layout.addWidget(self.count_label)
        layout.addLayout(points_header_layout)

        # 2. Поле поиска по названию точки на всю ширину
        self.search_input = QLineEdit(self)
        self.search_input.setObjectName("searchPointInput")
        self.search_input.setClearButtonEnabled(True)
        self.search_input.textChanged.connect(self._on_search_text_changed)
        layout.addWidget(self.search_input)

        # 3. Кнопки добавления, редактирования и удаления точки (единая высота и стиль)
        btn_row_layout = QHBoxLayout()
        btn_row_layout.setSpacing(4)

        self.btn_add = QPushButton(self)
        self.btn_add.setObjectName("btnAddPoint")
        self.btn_add.setFixedHeight(28)
        self.btn_add.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_add.clicked.connect(self.add_clicked.emit)
        btn_row_layout.addWidget(self.btn_add)

        self.btn_edit = QPushButton(self)
        self.btn_edit.setObjectName("btnEditPoint")
        self.btn_edit.setFixedHeight(28)
        self.btn_edit.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_edit.setEnabled(False)
        self.btn_edit.clicked.connect(self.edit_clicked.emit)
        btn_row_layout.addWidget(self.btn_edit)

        self.btn_delete = QPushButton(self)
        self.btn_delete.setObjectName("btnDeletePoint")
        self.btn_delete.setFixedHeight(28)
        self.btn_delete.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_delete.setEnabled(False)
        self.btn_delete.clicked.connect(self.delete_clicked.emit)
        btn_row_layout.addWidget(self.btn_delete)

        layout.addLayout(btn_row_layout)

        # 4. Таблица точек
        self.points_table = QTableWidget(0, 6, self)
        self.points_table.setObjectName("pointsTable")
        self.points_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.points_table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.points_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.points_table.verticalHeader().setVisible(False)

        header = self.points_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Interactive)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Interactive)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(5, QHeaderView.ResizeMode.ResizeToContents)
        self.points_table.setColumnWidth(2, 85)
        self.points_table.setColumnWidth(3, 85)

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
        """Фильтрация строк таблицы по названию, номеру объекта, категории и описанию."""
        query = text.strip().lower()
        for r in range(self.points_table.rowCount()):
            name_item = self.points_table.item(r, 1)
            name = name_item.text().lower() if name_item else ""
            num_item = self.points_table.item(r, 0)
            obj_num = str(num_item.data(Qt.ItemDataRole.UserRole + 1) or "").lower() if num_item else ""
            cat = str(num_item.data(Qt.ItemDataRole.UserRole + 2) or "").lower() if num_item else ""
            desc = str(num_item.data(Qt.ItemDataRole.UserRole + 3) or "").lower() if num_item else ""
            matches = (not query) or (query in name) or (query in obj_num) or (query in cat) or (query in desc)
            self.points_table.setRowHidden(r, not matches)
        self._update_counter()

    def _apply_filter_to_row(self, row: int) -> None:
        query = self.search_input.text().strip().lower()
        if not query:
            self.points_table.setRowHidden(row, False)
            return
        name_item = self.points_table.item(row, 1)
        name = name_item.text().lower() if name_item else ""
        num_item = self.points_table.item(row, 0)
        obj_num = str(num_item.data(Qt.ItemDataRole.UserRole + 1) or "").lower() if num_item else ""
        cat = str(num_item.data(Qt.ItemDataRole.UserRole + 2) or "").lower() if num_item else ""
        desc = str(num_item.data(Qt.ItemDataRole.UserRole + 3) or "").lower() if num_item else ""
        matches = (query in name) or (query in obj_num) or (query in cat) or (query in desc)
        self.points_table.setRowHidden(row, not matches)

    def _update_counter(self) -> None:
        """Обновление счетчика точек (всего / отфильтровано)."""
        total = self.points_table.rowCount()
        shown = sum(1 for r in range(total) if not self.points_table.isRowHidden(r))
        query = self.search_input.text().strip() if hasattr(self, "search_input") else ""
        if hasattr(self, "count_label"):
            if query:
                self.count_label.setText(tr("points.count_filtered", shown=shown, total=total))
            else:
                self.count_label.setText(tr("points.count_total", count=total))
        self.count_changed.emit(total, shown)

    @property
    def total_count(self) -> int:
        return self.points_table.rowCount()

    @property
    def shown_count(self) -> int:
        total = self.points_table.rowCount()
        return sum(1 for r in range(total) if not self.points_table.isRowHidden(r))

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
        self._update_counter()

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
        point_id: str | None = None,
        object_number: str = "",
        category: str = "",
        description: str = "",
        visible: bool = True,
    ) -> int:
        """Добавление строки в таблицу."""
        row = self.points_table.rowCount()
        self.points_table.insertRow(row)

        num_item = QTableWidgetItem(num)
        num_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        if point_id is not None:
            num_item.setData(Qt.ItemDataRole.UserRole, point_id)
        num_item.setData(Qt.ItemDataRole.UserRole + 1, object_number)
        num_item.setData(Qt.ItemDataRole.UserRole + 2, category)
        num_item.setData(Qt.ItemDataRole.UserRole + 3, description)
        num_item.setData(Qt.ItemDataRole.UserRole + 4, visible)

        name_item = QTableWidgetItem(name)
        lat_item = QTableWidgetItem(lat)
        lon_item = QTableWidgetItem(lon)
        shape_item = QTableWidgetItem(shape)
        radius_item = QTableWidgetItem(radius)

        if not visible:
            muted_color = QColor("#94A3B8")
            for it in (num_item, name_item, lat_item, lon_item, shape_item, radius_item):
                it.setForeground(muted_color)

        self.points_table.setItem(row, 0, num_item)
        self.points_table.setItem(row, 1, name_item)
        self.points_table.setItem(row, 2, lat_item)
        self.points_table.setItem(row, 3, lon_item)
        self.points_table.setItem(row, 4, shape_item)
        self.points_table.setItem(row, 5, radius_item)
        self._apply_filter_to_row(row)
        self._update_counter()
        return row

    def insert_row(
        self,
        row: int,
        num: str,
        name: str,
        lat: str,
        lon: str,
        shape: str,
        radius: str,
        point_id: str | None = None,
        object_number: str = "",
        category: str = "",
        description: str = "",
        visible: bool = True,
    ) -> int:
        """Вставка строки по заданному индексу (для восстановления в Undo)."""
        target_row = max(0, min(row, self.points_table.rowCount()))
        self.points_table.insertRow(target_row)

        num_item = QTableWidgetItem(num)
        num_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        if point_id is not None:
            num_item.setData(Qt.ItemDataRole.UserRole, point_id)
        num_item.setData(Qt.ItemDataRole.UserRole + 1, object_number)
        num_item.setData(Qt.ItemDataRole.UserRole + 2, category)
        num_item.setData(Qt.ItemDataRole.UserRole + 3, description)
        num_item.setData(Qt.ItemDataRole.UserRole + 4, visible)

        name_item = QTableWidgetItem(name)
        lat_item = QTableWidgetItem(lat)
        lon_item = QTableWidgetItem(lon)
        shape_item = QTableWidgetItem(shape)
        radius_item = QTableWidgetItem(radius)

        if not visible:
            muted_color = QColor("#94A3B8")
            for it in (num_item, name_item, lat_item, lon_item, shape_item, radius_item):
                it.setForeground(muted_color)

        self.points_table.setItem(target_row, 0, num_item)
        self.points_table.setItem(target_row, 1, name_item)
        self.points_table.setItem(target_row, 2, lat_item)
        self.points_table.setItem(target_row, 3, lon_item)
        self.points_table.setItem(target_row, 4, shape_item)
        self.points_table.setItem(target_row, 5, radius_item)

        # Пересчет номеров строк (с сохранением пользовательских номеров)
        for r in range(self.points_table.rowCount()):
            it = self.points_table.item(r, 0)
            if it:
                custom_num = it.data(Qt.ItemDataRole.UserRole + 1)
                it.setText(str(custom_num) if custom_num else str(r + 1))

        self._apply_filter_to_row(target_row)
        self._update_counter()
        return target_row

    def update_row(
        self,
        row: int,
        name: str,
        lat: str,
        lon: str,
        shape: str,
        radius: str,
        num: str | None = None,
        object_number: str | None = None,
        category: str | None = None,
        description: str | None = None,
        visible: bool | None = None,
    ) -> None:
        """Обновление значений в строке таблицы."""
        if 0 <= row < self.points_table.rowCount():
            num_item = self.points_table.item(row, 0)
            if num is not None and num_item:
                num_item.setText(num)
            if object_number is not None and num_item:
                num_item.setData(Qt.ItemDataRole.UserRole + 1, object_number)
            if category is not None and num_item:
                num_item.setData(Qt.ItemDataRole.UserRole + 2, category)
            if description is not None and num_item:
                num_item.setData(Qt.ItemDataRole.UserRole + 3, description)
            if visible is not None and num_item:
                num_item.setData(Qt.ItemDataRole.UserRole + 4, visible)
                muted = not visible
                fore_color = QColor("#94A3B8") if muted else QColor("#000000")
                for c in range(6):
                    it = self.points_table.item(row, c)
                    if it:
                        it.setForeground(fore_color)

            self.points_table.item(row, 1).setText(name)
            self.points_table.item(row, 2).setText(lat)
            self.points_table.item(row, 3).setText(lon)
            self.points_table.item(row, 4).setText(shape)
            self.points_table.item(row, 5).setText(radius)
            self._apply_filter_to_row(row)
            self._update_counter()

    def remove_row(self, row: int) -> None:
        """Удаление строки из таблицы и пересчет нумерации."""
        if 0 <= row < self.points_table.rowCount():
            self.points_table.removeRow(row)
            for r in range(self.points_table.rowCount()):
                item = self.points_table.item(r, 0)
                if item:
                    custom_num = item.data(Qt.ItemDataRole.UserRole + 1)
                    item.setText(str(custom_num) if custom_num else str(r + 1))
            self._update_counter()

    def clear_table(self) -> None:
        """Полная очистка строк таблицы."""
        self.points_table.setRowCount(0)
        self._update_counter()

    def selected_rows(self) -> list[int]:
        """Список всех выбранных строк таблицы."""
        model = self.points_table.selectionModel()
        if not model:
            return []
        rows = model.selectedRows()
        return sorted([r.row() for r in rows])

    def selected_row(self) -> int | None:
        """Индекс первой выбранной строки или None (обратная совместимость)."""
        rows = self.selected_rows()
        return rows[0] if rows else None

    def selected_point_ids(self) -> list[str]:
        """Стабильные идентификаторы всех выбранных точек таблицы."""
        result: list[str] = []
        for r in self.selected_rows():
            item = self.points_table.item(r, 0)
            if item:
                pid = item.data(Qt.ItemDataRole.UserRole)
                if pid:
                    result.append(str(pid))
        return result

    def clear_selection(self) -> None:
        """Снятие выделения со всех строк таблицы."""
        self.points_table.clearSelection()

    def select_point_ids(self, point_ids: list[str]) -> None:
        """Программное выделение строк по списку идентификаторов точек."""
        from PySide6.QtCore import QItemSelectionModel
        target_ids = set(point_ids)
        self.points_table.clearSelection()
        model = self.points_table.selectionModel()
        if not model:
            return
        flags = QItemSelectionModel.SelectionFlag.Select | QItemSelectionModel.SelectionFlag.Rows
        for r in range(self.points_table.rowCount()):
            item = self.points_table.item(r, 0)
            if item and str(item.data(Qt.ItemDataRole.UserRole)) in target_ids:
                idx = self.points_table.model().index(r, 0)
                model.select(idx, flags)
