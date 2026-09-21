"""Панель организационных групп объектов (GroupsPanel).

Обеспечивает:
- Отображение списка групп с индикатором количества объектов;
- Виртуальные элементы «Все объекты» и «Без группы»;
- Переключение видимости групп;
- Фильтрацию таблицы точек при выборе группы;
- Контекстное меню управления группой.
"""

import logging
from typing import Any

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMenu,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from rme_mapper.i18n import tr
from rme_mapper.models.object_group import ObjectGroup

logger = logging.getLogger("rme_mapper.ui.panels.groups_panel")

ITEM_ROLE_GROUP_ID = Qt.ItemDataRole.UserRole
ITEM_ROLE_IS_SYSTEM = Qt.ItemDataRole.UserRole + 1


class GroupsPanel(QWidget):
    """Компактная панель управления группами в левом сайдбаре."""

    # Сигналы
    group_filter_changed = Signal(object)  # None (Все), "__ungrouped__" (Без группы), или group_id: str
    group_visibility_toggled = Signal(str, bool)  # group_id, visible
    create_group_requested = Signal()
    rename_group_requested = Signal(str)  # group_id
    edit_group_desc_requested = Signal(str)  # group_id
    delete_group_requested = Signal(str)  # group_id
    select_group_points_requested = Signal(str)  # group_id
    zoom_to_group_requested = Signal(str)  # group_id
    bulk_style_group_requested = Signal(str)  # group_id

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("groupsPanel")

        self._groups: list[ObjectGroup] = []
        self._counts: dict[str | None, int] = {}
        self._active_filter: str | None = None
        self._block_signals: bool = False

        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        # 1. Шапка: заголовок и понятная кнопка создания группы.
        header_layout = QHBoxLayout()
        header_layout.setContentsMargins(0, 0, 0, 0)

        self.title_label = QLabel()
        title_font = QFont()
        title_font.setBold(True)
        title_font.setPointSize(11)
        self.title_label.setFont(title_font)
        header_layout.addWidget(self.title_label)
        header_layout.addStretch()

        self.btn_create = QPushButton(self)
        self.btn_create.setObjectName("btnCreateGroup")
        self.btn_create.setFixedHeight(28)
        self.btn_create.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_create.setToolTip(tr("action.create_group"))
        self.btn_create.clicked.connect(self.create_group_requested.emit)
        header_layout.addWidget(self.btn_create)

        layout.addLayout(header_layout)

        # 2. Дерево групп (1 уровень)
        self.groups_tree = QTreeWidget(self)
        self.groups_tree.setObjectName("groupsTree")
        self.groups_tree.setHeaderHidden(True)
        self.groups_tree.setRootIsDecorated(False)
        self.groups_tree.setUniformRowHeights(True)
        self.groups_tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.groups_tree.customContextMenuRequested.connect(self._show_context_menu)
        self.groups_tree.itemClicked.connect(self._on_item_clicked)
        self.groups_tree.itemChanged.connect(self._on_item_changed)
        self.groups_tree.itemDoubleClicked.connect(self._on_item_double_clicked)

        # Перехват клавиш
        orig_key_press = self.groups_tree.keyPressEvent

        def tree_key_press(event: Any) -> None:
            if event.key() == Qt.Key.Key_Insert:
                self.create_group_requested.emit()
                event.accept()
                return
            current = self.groups_tree.currentItem()
            if current:
                gid = current.data(0, ITEM_ROLE_GROUP_ID)
                is_sys = bool(current.data(0, ITEM_ROLE_IS_SYSTEM))
                if not is_sys and gid:
                    if event.key() == Qt.Key.Key_F2:
                        self.rename_group_requested.emit(str(gid))
                        event.accept()
                        return
                    if event.key() == Qt.Key.Key_Delete:
                        self.delete_group_requested.emit(str(gid))
                        event.accept()
                        return
            orig_key_press(event)

        self.groups_tree.keyPressEvent = tree_key_press

        layout.addWidget(self.groups_tree, stretch=1)
        self.retranslate_ui()

    def retranslate_ui(self) -> None:
        """Обновление локализованных строк."""
        self.title_label.setText(tr("panel.groups"))
        self.btn_create.setText(tr("btn.create_group"))
        self.btn_create.setToolTip(tr("action.create_group"))
        self._refresh_tree_items()

    def set_groups_and_counts(
        self,
        groups: list[ObjectGroup],
        counts: dict[str | None, int],
        total_count: int,
    ) -> None:
        """Обновление списка групп и их счетчиков."""
        self._groups = list(groups)
        self._counts = dict(counts)
        self._total_count = total_count
        self.setMaximumHeight(132 if not self._groups else 220)
        self._refresh_tree_items()

    def update_counts(self, counts: dict[str | None, int], total_count: int) -> None:
        """Обновление только счетчиков объектов без пересоздания структуры."""
        self._counts = dict(counts)
        self._total_count = total_count
        self._refresh_tree_items()

    def active_group_filter(self) -> str | None:
        """Возвращает текущий активный фильтр: None (все), '__ungrouped__', или group_id."""
        return self._active_filter

    def select_filter(self, filter_val: str | None) -> None:
        """Программный выбор группы в дереве."""
        self._active_filter = filter_val
        for idx in range(self.groups_tree.topLevelItemCount()):
            it = self.groups_tree.topLevelItem(idx)
            gid = it.data(0, ITEM_ROLE_GROUP_ID)
            if gid == filter_val:
                self.groups_tree.setCurrentItem(it)
                break

    def _refresh_tree_items(self) -> None:
        """Перестроение элементов дерева."""
        self._block_signals = True
        current_gid = self._active_filter
        self.groups_tree.clear()

        # 1. Виртуальный элемент: Все объекты
        total_pts = getattr(self, "_total_count", 0)
        item_all = QTreeWidgetItem()
        item_all.setText(0, f"{tr('groups.all')} ({total_pts})")
        item_all.setData(0, ITEM_ROLE_GROUP_ID, None)
        item_all.setData(0, ITEM_ROLE_IS_SYSTEM, True)
        f = item_all.font(0)
        f.setBold(True)
        item_all.setFont(0, f)
        self.groups_tree.addTopLevelItem(item_all)

        # 2. Виртуальный элемент: Без группы
        ungrouped_count = self._counts.get(None, 0)
        item_ungrouped = QTreeWidgetItem()
        item_ungrouped.setText(0, f"{tr('groups.ungrouped')} ({ungrouped_count})")
        item_ungrouped.setData(0, ITEM_ROLE_GROUP_ID, "__ungrouped__")
        item_ungrouped.setData(0, ITEM_ROLE_IS_SYSTEM, True)
        self.groups_tree.addTopLevelItem(item_ungrouped)

        # 3. Пользовательские группы
        for grp in self._groups:
            c = self._counts.get(grp.id, 0)
            item = QTreeWidgetItem()
            item.setText(0, f"{grp.name} ({c})")
            item.setData(0, ITEM_ROLE_GROUP_ID, grp.id)
            item.setData(0, ITEM_ROLE_IS_SYSTEM, False)
            item.setCheckState(0, Qt.CheckState.Checked if grp.visible else Qt.CheckState.Unchecked)

            if not grp.visible:
                item.setForeground(0, QColor("#94A3B8"))

            if grp.description:
                item.setToolTip(0, grp.description)

            self.groups_tree.addTopLevelItem(item)

        # Восстановление выбранного элемента
        selected_found = False
        for idx in range(self.groups_tree.topLevelItemCount()):
            it = self.groups_tree.topLevelItem(idx)
            gid = it.data(0, ITEM_ROLE_GROUP_ID)
            if gid == current_gid:
                self.groups_tree.setCurrentItem(it)
                selected_found = True
                break
        if not selected_found:
            self.groups_tree.setCurrentItem(item_all)
            self._active_filter = None

        self._block_signals = False

    def _on_item_clicked(self, item: QTreeWidgetItem, column: int) -> None:
        gid = item.data(0, ITEM_ROLE_GROUP_ID)
        self._active_filter = gid
        self.group_filter_changed.emit(gid)

    def _on_item_changed(self, item: QTreeWidgetItem, column: int) -> None:
        if self._block_signals:
            return
        is_sys = bool(item.data(0, ITEM_ROLE_IS_SYSTEM))
        if is_sys:
            return
        gid = item.data(0, ITEM_ROLE_GROUP_ID)
        if gid:
            vis = item.checkState(0) == Qt.CheckState.Checked
            item.setForeground(0, QColor("#1E293B") if vis else QColor("#94A3B8"))
            self.group_visibility_toggled.emit(str(gid), vis)

    def _on_item_double_clicked(self, item: QTreeWidgetItem, column: int) -> None:
        is_sys = bool(item.data(0, ITEM_ROLE_IS_SYSTEM))
        if not is_sys:
            gid = item.data(0, ITEM_ROLE_GROUP_ID)
            if gid:
                self.rename_group_requested.emit(str(gid))

    def _show_context_menu(self, pos: Any) -> None:
        item = self.groups_tree.itemAt(pos)
        if not item:
            # Контекстное меню на пустом месте: Создать группу
            menu = QMenu(self)
            act_create = menu.addAction(tr("action.create_group"))
            act_create.triggered.connect(self.create_group_requested.emit)
            menu.exec(self.groups_tree.viewport().mapToGlobal(pos))
            return

        gid = item.data(0, ITEM_ROLE_GROUP_ID)
        is_sys = bool(item.data(0, ITEM_ROLE_IS_SYSTEM))

        menu = QMenu(self)

        if is_sys:
            # Для системных элементов ("Все объекты", "Без группы")
            act_sel = menu.addAction(tr("action.select_group_objects"))
            act_sel.triggered.connect(lambda: self.select_group_points_requested.emit(str(gid or "")))

            act_zoom = menu.addAction(tr("action.zoom_to_group"))
            count = self._total_count if gid is None else self._counts.get(None, 0)
            act_zoom.setEnabled(count > 0)
            act_zoom.triggered.connect(lambda: self.zoom_to_group_requested.emit(str(gid or "")))
        else:
            # Для пользовательских групп
            str_gid = str(gid)
            grp_count = self._counts.get(str_gid, 0)

            act_rename = menu.addAction(tr("action.rename_group"))
            act_rename.triggered.connect(lambda: self.rename_group_requested.emit(str_gid))

            act_desc = menu.addAction(tr("action.edit_group_desc"))
            act_desc.triggered.connect(lambda: self.edit_group_desc_requested.emit(str_gid))

            menu.addSeparator()

            is_vis = item.checkState(0) == Qt.CheckState.Checked
            vis_text = tr("action.hide_group") if is_vis else tr("action.show_group")
            act_vis = menu.addAction(vis_text)
            act_vis.triggered.connect(lambda: self.group_visibility_toggled.emit(str_gid, not is_vis))

            act_sel = menu.addAction(tr("action.select_group_objects"))
            act_sel.triggered.connect(lambda: self.select_group_points_requested.emit(str_gid))

            act_zoom = menu.addAction(tr("action.zoom_to_group"))
            act_zoom.setEnabled(grp_count > 0)
            act_zoom.triggered.connect(lambda: self.zoom_to_group_requested.emit(str_gid))

            act_style = menu.addAction(tr("action.edit_group_style"))
            act_style.setEnabled(grp_count > 0)
            act_style.triggered.connect(lambda: self.bulk_style_group_requested.emit(str_gid))

            menu.addSeparator()

            act_del = menu.addAction(tr("action.delete_group"))
            act_del.triggered.connect(lambda: self.delete_group_requested.emit(str_gid))

        menu.exec(self.groups_tree.viewport().mapToGlobal(pos))
