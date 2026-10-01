"""Панель управления пользовательскими точками и таблицей точек."""
from __future__ import annotations


import logging
from typing import Any

from PySide6.QtCore import (
    QItemSelection,
    QItemSelectionModel,
    QItemSelectionRange,
    QTimer,
    Qt,
    Signal,
)
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
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

        self._active_group_filter: str | None = None
        self._search_debounce_timer = QTimer(self)
        self._search_debounce_timer.setSingleShot(True)
        self._search_debounce_timer.setInterval(180)
        self._search_debounce_timer.timeout.connect(self._reapply_all_filters)

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

        # 2. Поле поиска и компактный фильтр категории
        filter_layout = QHBoxLayout()
        filter_layout.setSpacing(4)

        self.search_input = QLineEdit(self)
        self.search_input.setObjectName("searchPointInput")
        self.search_input.setClearButtonEnabled(True)
        self.search_input.textChanged.connect(self._on_search_text_changed)
        filter_layout.addWidget(self.search_input, stretch=1)

        self.category_combo = QComboBox(self)
        self.category_combo.setObjectName("categoryFilterCombo")
        self.category_combo.setMinimumWidth(115)
        self.category_combo.currentIndexChanged.connect(self._on_category_filter_changed)
        filter_layout.addWidget(self.category_combo, stretch=1)

        layout.addLayout(filter_layout)

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

    def set_group_filter(self, group_id: str | None) -> None:
        """Установка фильтра по группе (None = все, '__ungrouped__', или group_id)."""
        self._active_group_filter = group_id
        self._reapply_all_filters()

    def _on_category_filter_changed(self, index: int) -> None:
        if hasattr(self, "category_combo"):
            self.category_combo.setToolTip(self.category_combo.currentText())
        self._reapply_all_filters()

    def _reapply_all_filters(self) -> None:
        if hasattr(self, "_search_debounce_timer") and self._search_debounce_timer.isActive():
            self._search_debounce_timer.stop()

        self.points_table.setUpdatesEnabled(False)
        query = self.search_input.text().strip().lower() if hasattr(self, "search_input") else ""
        selected_cat = str(self.category_combo.currentData() or "").strip().casefold() if hasattr(self, "category_combo") else ""
        grp_filter = self._active_group_filter

        total = self.points_table.rowCount()
        shown = 0

        for r in range(total):
            num_item = self.points_table.item(r, 0)
            name_item = self.points_table.item(r, 1)

            name = name_item.text().lower() if name_item else ""
            obj_num = str(num_item.data(Qt.ItemDataRole.UserRole + 1) or "").lower() if num_item else ""
            cat = str(num_item.data(Qt.ItemDataRole.UserRole + 2) or "") if num_item else ""
            desc = str(num_item.data(Qt.ItemDataRole.UserRole + 3) or "").lower() if num_item else ""
            row_group_id = num_item.data(Qt.ItemDataRole.UserRole + 5) if num_item else None

            # 1. Фильтр группы
            matches_group = True
            if grp_filter is not None:
                if grp_filter == "__ungrouped__":
                    if row_group_id is not None and str(row_group_id).strip():
                        matches_group = False
                else:
                    if row_group_id != grp_filter:
                        matches_group = False

            # 2. Фильтр категории
            matches_cat = True
            if selected_cat:
                if cat.strip().casefold() != selected_cat:
                    matches_cat = False

            # 3. Текстовый поиск
            matches_search = True
            if query:
                matches_search = (query in name) or (query in obj_num) or (query in cat.lower()) or (query in desc)

            matches = matches_group and matches_cat and matches_search
            self.points_table.setRowHidden(r, not matches)
            if matches:
                shown += 1

        self.points_table.setUpdatesEnabled(True)

        if hasattr(self, "count_label"):
            if shown < total:
                self.count_label.setText(tr("points.count_filtered", shown=shown, total=total))
            else:
                self.count_label.setText(tr("points.count_total", count=total))
        self.count_changed.emit(total, shown)

    def _on_search_text_changed(self, text: str) -> None:
        """Мгновенная пакетная фильтрация строк таблицы без лагов."""
        self._reapply_all_filters()

    def _apply_filter_to_row(
        self,
        row: int,
        query: str | None = None,
        selected_cat: str | None = None,
    ) -> bool:
        if query is None:
            query = self.search_input.text().strip().lower() if hasattr(self, "search_input") else ""
        if selected_cat is None:
            selected_cat = str(self.category_combo.currentData() or "").strip().casefold() if hasattr(self, "category_combo") else ""

        num_item = self.points_table.item(row, 0)
        name_item = self.points_table.item(row, 1)

        name = name_item.text().lower() if name_item else ""
        obj_num = str(num_item.data(Qt.ItemDataRole.UserRole + 1) or "").lower() if num_item else ""
        cat = str(num_item.data(Qt.ItemDataRole.UserRole + 2) or "") if num_item else ""
        desc = str(num_item.data(Qt.ItemDataRole.UserRole + 3) or "").lower() if num_item else ""
        row_group_id = num_item.data(Qt.ItemDataRole.UserRole + 5) if num_item else None

        # 1. Фильтр группы
        matches_group = True
        if self._active_group_filter is not None:
            if self._active_group_filter == "__ungrouped__":
                if row_group_id is not None and str(row_group_id).strip():
                    matches_group = False
            else:
                if row_group_id != self._active_group_filter:
                    matches_group = False

        # 2. Фильтр категории
        matches_cat = True
        if selected_cat:
            if cat.strip().casefold() != selected_cat:
                matches_cat = False

        # 3. Текстовый поиск
        matches_search = True
        if query:
            matches_search = (query in name) or (query in obj_num) or (query in cat.lower()) or (query in desc)

        matches = matches_group and matches_cat and matches_search
        self.points_table.setRowHidden(row, not matches)
        return matches

    def _update_category_combo_items(self, categories: set[str] | None = None) -> None:
        if not hasattr(self, "category_combo"):
            return
        current_data = self.category_combo.currentData()
        self.category_combo.blockSignals(True)
        self.category_combo.clear()
        self.category_combo.addItem(tr("category.all"), "")

        if categories is not None:
            cats = set(categories)
        else:
            cats = set()
            for r in range(self.points_table.rowCount()):
                num_item = self.points_table.item(r, 0)
                if num_item:
                    c = str(num_item.data(Qt.ItemDataRole.UserRole + 2) or "").strip()
                    if c:
                        cats.add(c)

        for c in sorted(cats):
            self.category_combo.addItem(c, c)

        if current_data:
            idx = self.category_combo.findData(current_data)
            if idx != -1:
                self.category_combo.setCurrentIndex(idx)
            else:
                self.category_combo.setCurrentIndex(0)
        else:
            self.category_combo.setCurrentIndex(0)

        self.category_combo.blockSignals(False)
        self.category_combo.setToolTip(self.category_combo.currentText())

    def _update_counter(self) -> None:
        """Обновление счетчика точек (всего / отфильтровано)."""
        total = self.points_table.rowCount()
        shown = sum(1 for r in range(total) if not self.points_table.isRowHidden(r))
        if hasattr(self, "count_label"):
            if shown < total:
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
        if hasattr(self, "category_combo") and self.category_combo.count() > 0:
            self.category_combo.setItemText(0, tr("category.all"))
            self.category_combo.setToolTip(self.category_combo.currentText())
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
        group_id: str | None = None,
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
        num_item.setData(Qt.ItemDataRole.UserRole + 5, group_id)

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
        if not self.points_table.signalsBlocked():
            self._update_category_combo_items()
            self._update_counter()
        return row

    def add_point(self, point: Any) -> int:
        """Удобный метод добавления точки (модели MapPoint) в таблицу."""
        from rme_mapper.models.map_point import MapPoint
        if isinstance(point, MapPoint):
            return self.add_row(
                num=str(self.points_table.rowCount() + 1),
                name=point.name,
                lat=f"{point.latitude:.6f}",
                lon=f"{point.longitude:.6f}",
                shape=point.symbol,
                radius=f"{point.radius_m:.1f}" if point.zone_enabled else "-",
                point_id=point.id,
                object_number=point.object_number,
                category=point.category,
                description=point.description,
                visible=point.visible,
                group_id=point.group_id,
            )
        return -1

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
        group_id: str | None = None,
    ) -> int:
        """Вставка строки по заданному индексу (для восстановления в Undo)."""
        target_row = max(0, min(row, self.points_table.rowCount()))
        if target_row >= self.points_table.rowCount():
            self.points_table.insertRow(target_row)

        num_item = QTableWidgetItem(num)
        num_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        if point_id is not None:
            num_item.setData(Qt.ItemDataRole.UserRole, point_id)
        num_item.setData(Qt.ItemDataRole.UserRole + 1, object_number)
        num_item.setData(Qt.ItemDataRole.UserRole + 2, category)
        num_item.setData(Qt.ItemDataRole.UserRole + 3, description)
        num_item.setData(Qt.ItemDataRole.UserRole + 4, visible)
        num_item.setData(Qt.ItemDataRole.UserRole + 5, group_id)

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

        # Пересчет номеров строк (только при вставке в середину таблицы)
        if target_row < self.points_table.rowCount() - 1:
            for r in range(target_row + 1, self.points_table.rowCount()):
                it = self.points_table.item(r, 0)
                if it:
                    custom_num = it.data(Qt.ItemDataRole.UserRole + 1)
                    it.setText(str(custom_num) if custom_num else str(r + 1))

        self._apply_filter_to_row(target_row)
        if not self.points_table.signalsBlocked():
            self._update_category_combo_items()
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
        group_id: str | None = None,
        update_group: bool = False,
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
            if update_group and num_item:
                num_item.setData(Qt.ItemDataRole.UserRole + 5, group_id)

            self.points_table.item(row, 1).setText(name)
            self.points_table.item(row, 2).setText(lat)
            self.points_table.item(row, 3).setText(lon)
            self.points_table.item(row, 4).setText(shape)
            self.points_table.item(row, 5).setText(radius)
            self._apply_filter_to_row(row)
            self._update_category_combo_items()
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
            self._update_category_combo_items()
            self._update_counter()

    def clear_table(self) -> None:
        """Полная очистка строк таблицы."""
        self.points_table.setRowCount(0)
        self._update_category_combo_items()
        self._update_counter()

    def update_point_group_id(self, point_id: str, group_id: str | None) -> None:
        """Обновление group_id для строки с указанным point_id."""
        for r in range(self.points_table.rowCount()):
            num_item = self.points_table.item(r, 0)
            if num_item and str(num_item.data(Qt.ItemDataRole.UserRole)) == str(point_id):
                num_item.setData(Qt.ItemDataRole.UserRole + 5, group_id)
                self._apply_filter_to_row(r)
                break
        self._update_counter()

    def populate_points_batch(self, points: list[Any]) -> None:
        """Пакетное наполнение таблицы точек с блокировкой перерисовки."""
        self.points_table.setUpdatesEnabled(False)
        self.points_table.blockSignals(True)
        self.points_table.setSortingEnabled(False)

        start_row = self.points_table.rowCount()
        new_total = start_row + len(points)
        self.points_table.setRowCount(new_total)

        muted_color = QColor("#94A3B8")
        cats: set[str] = set()

        from rme_mapper.models.map_point import MapPoint
        from rme_mapper.ui.panels.properties_panel import get_symbol_display_name
        from rme_mapper.services.geodesic_service import GeodesicService

        for idx, pt in enumerate(points):
            r = start_row + idx
            if isinstance(pt, MapPoint):
                num = pt.object_number if pt.object_number else str(r + 1)
                name = pt.name
                lat = f"{pt.latitude:.6f}"
                lon = f"{pt.longitude:.6f}"
                shape = get_symbol_display_name(pt.symbol)
                radius = GeodesicService.format_radius(pt.radius_m, pt.zone_enabled)
                point_id = pt.id
                obj_num = pt.object_number
                category = pt.category
                desc = pt.description
                visible = pt.visible
                group_id = pt.group_id
            else:
                num = str(pt.get("num", r + 1))
                name = str(pt.get("name", ""))
                lat = str(pt.get("lat", ""))
                lon = str(pt.get("lon", ""))
                shape = str(pt.get("shape", ""))
                radius = str(pt.get("radius", "-"))
                point_id = pt.get("point_id")
                obj_num = str(pt.get("object_number", ""))
                category = str(pt.get("category", ""))
                desc = str(pt.get("description", ""))
                visible = bool(pt.get("visible", True))
                group_id = pt.get("group_id")

            if category and category.strip():
                cats.add(category.strip())

            num_item = QTableWidgetItem(num)
            num_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            if point_id is not None:
                num_item.setData(Qt.ItemDataRole.UserRole, point_id)
            num_item.setData(Qt.ItemDataRole.UserRole + 1, obj_num)
            num_item.setData(Qt.ItemDataRole.UserRole + 2, category)
            num_item.setData(Qt.ItemDataRole.UserRole + 3, desc)
            num_item.setData(Qt.ItemDataRole.UserRole + 4, visible)
            num_item.setData(Qt.ItemDataRole.UserRole + 5, group_id)

            name_item = QTableWidgetItem(name)
            lat_item = QTableWidgetItem(lat)
            lon_item = QTableWidgetItem(lon)
            shape_item = QTableWidgetItem(shape)
            radius_item = QTableWidgetItem(radius)

            if not visible:
                for it in (num_item, name_item, lat_item, lon_item, shape_item, radius_item):
                    it.setForeground(muted_color)

            self.points_table.setItem(r, 0, num_item)
            self.points_table.setItem(r, 1, name_item)
            self.points_table.setItem(r, 2, lat_item)
            self.points_table.setItem(r, 3, lon_item)
            self.points_table.setItem(r, 4, shape_item)
            self.points_table.setItem(r, 5, radius_item)

        self.points_table.blockSignals(False)
        self.points_table.setUpdatesEnabled(True)

        self._update_category_combo_items()
        self._reapply_all_filters()

    def remove_rows_by_point_ids(self, point_ids: set[str]) -> None:
        """Пакетное удаление строк таблицы по набору point_id."""
        if not point_ids:
            return
        target_ids = {str(pid) for pid in point_ids}
        self.points_table.setUpdatesEnabled(False)
        self.points_table.blockSignals(True)
        try:
            for r in range(self.points_table.rowCount() - 1, -1, -1):
                num_item = self.points_table.item(r, 0)
                if num_item:
                    pid = str(num_item.data(Qt.ItemDataRole.UserRole))
                    if pid in target_ids:
                        self.points_table.removeRow(r)
        finally:
            self.points_table.blockSignals(False)
            self.points_table.setUpdatesEnabled(True)
            self._update_counter()
            self._update_category_combo_items()

    def update_point_group_id(self, point_id: str, group_id: str | None) -> None:
        """Обновление group_id для строки с указанным point_id."""
        for r in range(self.points_table.rowCount()):
            num_item = self.points_table.item(r, 0)
            if num_item and str(num_item.data(Qt.ItemDataRole.UserRole)) == str(point_id):
                num_item.setData(Qt.ItemDataRole.UserRole + 5, group_id)
                self._apply_filter_to_row(r)
                break
        self._update_counter()

    def update_points_group_ids(self, points_group_map: dict[str, str | None]) -> None:
        """Массовое обновление group_id для списка точек."""
        target_ids = {str(k): v for k, v in points_group_map.items()}
        self.points_table.setUpdatesEnabled(False)
        for r in range(self.points_table.rowCount()):
            num_item = self.points_table.item(r, 0)
            if num_item:
                pid = str(num_item.data(Qt.ItemDataRole.UserRole))
                if pid in target_ids:
                    num_item.setData(Qt.ItemDataRole.UserRole + 5, target_ids[pid])
        self.points_table.setUpdatesEnabled(True)
        self._reapply_all_filters()

    def update_points_categories(self, points_cat_map: dict[str, str]) -> None:
        """Массовое обновление категорий для списка точек."""
        target_ids = {str(k): v for k, v in points_cat_map.items()}
        self.points_table.setUpdatesEnabled(False)
        for r in range(self.points_table.rowCount()):
            num_item = self.points_table.item(r, 0)
            if num_item:
                pid = str(num_item.data(Qt.ItemDataRole.UserRole))
                if pid in target_ids:
                    num_item.setData(Qt.ItemDataRole.UserRole + 2, target_ids[pid])
        self.points_table.setUpdatesEnabled(True)
        self._update_category_combo_items()
        self._reapply_all_filters()

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
        """Программное выделение строк по списку идентификаторов точек (пакетно за 1 вызов)."""
        target_ids = set(point_ids)
        self.points_table.clearSelection()
        model = self.points_table.selectionModel()
        if not model or not target_ids:
            return

        table_model = self.points_table.model()
        selection = QItemSelection()
        col_count = self.points_table.columnCount()

        start_row = None
        for r in range(self.points_table.rowCount()):
            item = self.points_table.item(r, 0)
            is_target = item is not None and str(item.data(Qt.ItemDataRole.UserRole)) in target_ids
            if is_target:
                if start_row is None:
                    start_row = r
            else:
                if start_row is not None:
                    top_left = table_model.index(start_row, 0)
                    bottom_right = table_model.index(r - 1, col_count - 1)
                    selection.append(QItemSelectionRange(top_left, bottom_right))
                    start_row = None

        if start_row is not None:
            top_left = table_model.index(start_row, 0)
            bottom_right = table_model.index(self.points_table.rowCount() - 1, col_count - 1)
            selection.append(QItemSelectionRange(top_left, bottom_right))

        flags = QItemSelectionModel.SelectionFlag.Select | QItemSelectionModel.SelectionFlag.Rows
        model.select(selection, flags)
