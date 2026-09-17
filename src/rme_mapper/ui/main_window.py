"""Главное окно приложения RME-Mapper."""

import logging
from pathlib import Path
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QFont
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMainWindow,
    QMenu,
    QMenuBar,
    QPushButton,
    QSplitter,
    QStatusBar,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from rme_mapper.maps.map_canvas import MapCanvas
from rme_mapper.maps.map_config import get_default_geopackage_path
from rme_mapper.models.map_layer import LayerRole, MapLayer
from rme_mapper.models.map_point import MapPoint
from rme_mapper.services.geopackage_service import GeoPackageService
from rme_mapper.services.layer_service import LayerService
from rme_mapper.services.point_service import PointService
from rme_mapper.ui.add_point_dialog import AddPointDialog, PointDialog

SYMBOL_DISPLAY_NAMES = {
    "circle": "Круг",
    "square": "Квадрат",
    "triangle": "Треугольник",
}

logger = logging.getLogger("rme_mapper.ui.main_window")


class MainWindow(QMainWindow):
    """Главное окно приложения RME-Mapper."""

    DEFAULT_WIDTH = 1400
    DEFAULT_HEIGHT = 850

    def __init__(
        self,
        parent: QWidget | None = None,
        map_path: Path | str | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("RME Mapper — Географическая привязка координат")
        self.resize(self.DEFAULT_WIDTH, self.DEFAULT_HEIGHT)

        self._map_path = Path(map_path) if map_path else get_default_geopackage_path()
        self._layer_service = LayerService()
        self._point_service = PointService()

        # Геометрия границы РМЭ (для проверки выхода за пределы)
        self._boundary_geometry = None

        # Словарь чекбоксов слоев: layer_id -> QCheckBox
        self.layer_checkboxes: dict[str, QCheckBox] = {}
        self.loaded_layers: list[MapLayer] = []

        # Отображение номеров строк таблицы на MapPoint: row_index -> point_id
        self._table_point_ids: list[str] = []

        self._setup_ui()
        self.load_map(self._map_path)

    def _setup_ui(self) -> None:
        """Инициализация компонентов интерфейса."""
        self._create_menu_bar()
        self._create_central_layout()
        self._create_status_bar()

    def _create_menu_bar(self) -> None:
        """Создание верхнего меню приложения."""
        menu_bar = self.menuBar()

        # Меню: Файл
        self.file_menu = menu_bar.addMenu("Файл")
        exit_action = QAction("Выход", self)
        exit_action.triggered.connect(self.close)
        self.file_menu.addAction(exit_action)

        # Меню: Карта
        self.map_menu = menu_bar.addMenu("Карта")
        fit_action = QAction("Показать всю карту", self)
        fit_action.triggered.connect(lambda: self.map_canvas.fit_to_view())
        self.map_menu.addAction(fit_action)

        # Меню: Координаты
        self.coords_menu = menu_bar.addMenu("Координаты")
        add_pt_action = QAction("Добавить точку", self)
        add_pt_action.triggered.connect(self.show_add_point_dialog)
        self.coords_menu.addAction(add_pt_action)

        # Меню: Импорт
        self.import_menu = menu_bar.addMenu("Импорт")

        # Меню: Экспорт
        self.export_menu = menu_bar.addMenu("Экспорт")

        # Меню: Настройки
        self.settings_menu = menu_bar.addMenu("Настройки")

    def _create_central_layout(self) -> None:
        """Создание трехпанельной компоновки: Слои/Точки | Карта | Свойства."""
        splitter = QSplitter(Qt.Orientation.Horizontal, self)

        # Левая панель: Слои и Точки
        self.left_panel = self._create_left_panel()
        splitter.addWidget(self.left_panel)

        # Центральная область: Карта Республики Марий Эл (MapCanvas)
        self.center_panel = self._create_center_panel()
        splitter.addWidget(self.center_panel)

        # Правая панель: Свойства
        self.right_panel = self._create_right_panel()
        splitter.addWidget(self.right_panel)

        # Начальные пропорции сплиттера: 300px, 800px, 300px
        splitter.setSizes([300, 800, 300])
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setStretchFactor(2, 0)

        self.setCentralWidget(splitter)

    def _create_left_panel(self) -> QWidget:
        """Создание левой панели с блоками 'Слои' и 'Точки'."""
        panel = QWidget()
        panel.setObjectName("leftPanel")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(10)

        # 1. Блок 'Слои'
        layers_title = QLabel("Слои")
        layers_font = QFont()
        layers_font.setBold(True)
        layers_font.setPointSize(11)
        layers_title.setFont(layers_font)
        layout.addWidget(layers_title)

        self.layers_container = QWidget()
        self.layers_container.setObjectName("layersContainer")
        self.layers_layout = QVBoxLayout(self.layers_container)
        self.layers_layout.setContentsMargins(4, 2, 4, 4)
        self.layers_layout.setSpacing(4)
        layout.addWidget(self.layers_container)

        # Разделительная линия
        separator = QFrame()
        separator.setFrameShape(QFrame.Shape.HLine)
        separator.setFrameShadow(QFrame.Shadow.Sunken)
        layout.addWidget(separator)

        # 2. Блок 'Точки'
        points_header_layout = QHBoxLayout()
        points_title = QLabel("Точки")
        points_font = QFont()
        points_font.setBold(True)
        points_font.setPointSize(11)
        points_title.setFont(points_font)
        points_header_layout.addWidget(points_title)
        points_header_layout.addStretch()
        layout.addLayout(points_header_layout)

        # Кнопки добавления, редактирования и удаления точки
        btn_row_layout = QHBoxLayout()
        self.btn_add_point = QPushButton("+ Добавить точку", self)
        self.btn_add_point.setObjectName("btnAddPoint")
        self.btn_add_point.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_add_point.clicked.connect(self.show_add_point_dialog)
        btn_row_layout.addWidget(self.btn_add_point)

        self.btn_edit_point = QPushButton("Редактировать", self)
        self.btn_edit_point.setObjectName("btnEditPoint")
        self.btn_edit_point.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_edit_point.setEnabled(False)
        self.btn_edit_point.clicked.connect(self.edit_selected_point)
        btn_row_layout.addWidget(self.btn_edit_point)

        self.btn_delete_point = QPushButton("Удалить", self)
        self.btn_delete_point.setObjectName("btnDeletePoint")
        self.btn_delete_point.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_delete_point.setEnabled(False)
        self.btn_delete_point.clicked.connect(self.delete_selected_point)
        btn_row_layout.addWidget(self.btn_delete_point)

        layout.addLayout(btn_row_layout)

        # Таблица пользовательских точек
        self.points_table = QTableWidget(0, 5, self)
        self.points_table.setObjectName("pointsTable")
        self.points_table.setHorizontalHeaderLabels(["№", "Название", "Широта", "Долгота", "Форма"])
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

        # Сигналы таблицы
        self.points_table.cellDoubleClicked.connect(self._on_table_row_double_clicked)
        self.points_table.itemSelectionChanged.connect(self._on_table_selection_changed)
        self.points_table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.points_table.customContextMenuRequested.connect(self._show_table_context_menu)

        # Сохраняем ссылку на points_placeholder для обратной совместимости с тестами
        self.points_placeholder = self.points_table
        layout.addWidget(self.points_table, stretch=1)

        return panel

    def _create_center_panel(self) -> QWidget:
        """Создание центральной области с MapCanvas."""
        panel = QWidget()
        panel.setObjectName("centerPanel")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        header_layout = QVBoxLayout()
        header_label = QLabel("Карта Республики Марий Эл")
        header_font = QFont()
        header_font.setBold(True)
        header_font.setPointSize(12)
        header_label.setFont(header_font)
        header_layout.addWidget(header_label)
        layout.addLayout(header_layout)

        self.map_canvas = MapCanvas(panel)
        self.map_placeholder = self.map_canvas
        layout.addWidget(self.map_canvas, stretch=1)

        return panel

    def _create_right_panel(self) -> QWidget:
        """Создание правой панели: заголовок 'Свойства' и карточка свойств выбранной точки."""
        panel = QWidget()
        panel.setObjectName("rightPanel")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        title_label = QLabel("Свойства")
        title_font = QFont()
        title_font.setBold(True)
        title_font.setPointSize(11)
        title_label.setFont(title_font)
        layout.addWidget(title_label)

        self.properties_placeholder = QFrame()
        self.properties_placeholder.setObjectName("propertiesPlaceholder")
        self.properties_placeholder.setFrameShape(QFrame.Shape.StyledPanel)
        self.properties_placeholder.setFrameShadow(QFrame.Shadow.Sunken)

        placeholder_layout = QVBoxLayout(self.properties_placeholder)
        placeholder_layout.setContentsMargins(10, 10, 10, 10)

        # Сообщение, если точка не выбрана
        self.prop_empty_label = QLabel("Выберите точку в таблице для просмотра свойств")
        self.prop_empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.prop_empty_label.setStyleSheet("color: #888888; font-style: italic;")
        self.prop_empty_label.setWordWrap(True)
        placeholder_layout.addWidget(self.prop_empty_label)

        # Контейнер свойств выбранной точки
        self.prop_container = QWidget()
        prop_form = QFormLayout(self.prop_container)
        prop_form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        self.prop_name_val = QLabel("—")
        self.prop_name_val.setWordWrap(True)
        prop_form.addRow("<b>Название:</b>", self.prop_name_val)

        self.prop_lat_val = QLabel("—")
        prop_form.addRow("<b>Широта:</b>", self.prop_lat_val)

        self.prop_lon_val = QLabel("—")
        prop_form.addRow("<b>Долгота:</b>", self.prop_lon_val)

        self.prop_shape_val = QLabel("—")
        prop_form.addRow("<b>Форма:</b>", self.prop_shape_val)

        self.prop_size_val = QLabel("—")
        prop_form.addRow("<b>Размер:</b>", self.prop_size_val)

        color_row = QHBoxLayout()
        self.prop_color_val = QLabel("—")
        self.prop_color_swatch = QFrame()
        self.prop_color_swatch.setFixedSize(20, 20)
        self.prop_color_swatch.setStyleSheet("border: 1px solid #999; border-radius: 3px;")
        color_row.addWidget(self.prop_color_val)
        color_row.addWidget(self.prop_color_swatch)
        color_row.addStretch()
        prop_form.addRow("<b>Цвет (RGB):</b>", color_row)

        self.prop_container.setVisible(False)
        placeholder_layout.addWidget(self.prop_container)
        placeholder_layout.addStretch()

        layout.addWidget(self.properties_placeholder, stretch=1)
        return panel


    def _create_status_bar(self) -> None:
        """Создание нижней строки состояния."""
        status_bar = QStatusBar(self)
        status_bar.setObjectName("statusBar")
        status_bar.showMessage("Готово")
        self.setStatusBar(status_bar)

    def load_map(self, map_path: Path | str) -> None:
        """Загрузка слоев карты из указанного GeoPackage."""
        path = Path(map_path)
        logger.info("Загрузка карты из: %s", path)

        if not GeoPackageService.exists(path):
            err_msg = f"Не найден файл карты:\n{path}"
            logger.error("Файл карты не найден: %s", path)
            self.map_canvas.set_error(err_msg)
            self.statusBar().showMessage("Ошибка: файл карты не найден")
            return

        try:
            discovered_layers = self._layer_service.discover_layers(path)
            logger.info("Обнаружено поддерживаемых слоев: %d", len(discovered_layers))

            if not discovered_layers:
                err_msg = "В GeoPackage не найдено поддерживаемых картографических слоев"
                logger.error(err_msg)
                self.map_canvas.set_error(err_msg)
                self.statusBar().showMessage("Ошибка: поддерживаемые слои не найдены")
                return

            self._clear_layer_checkboxes()

            successfully_loaded: list[MapLayer] = []
            common_crs = "OGC:CRS84"

            for layer in discovered_layers:
                try:
                    logger.info("Загрузка слоя '%s' (%s)...", layer.display_name, layer.source_name)
                    gdf = self._layer_service.load_layer_data(path, layer)

                    if gdf.crs:
                        common_crs = gdf.crs.to_string()

                    # Сохраняем полигон границы для проверки точек
                    if layer.role == LayerRole.BOUNDARY:
                        try:
                            self._boundary_geometry = gdf.union_all()
                        except AttributeError:
                            self._boundary_geometry = gdf.unary_union

                    self.map_canvas.add_layer_item(layer, gdf)
                    successfully_loaded.append(layer)
                    self._add_layer_checkbox(layer)

                except Exception as layer_err:
                    logger.exception("Ошибка загрузки слоя '%s': %s", layer.display_name, layer_err)
                    if layer.role == LayerRole.BOUNDARY:
                        self.map_canvas.set_error(f"Ошибка чтения границы РМЭ:\n{layer_err}")
                        self.statusBar().showMessage("Ошибка чтения границы карты")
                        return

            self.loaded_layers = successfully_loaded
            status_text = f"Карта загружена | {common_crs} | Слоёв: {len(successfully_loaded)}"
            self.statusBar().showMessage(status_text)
            logger.info("Карта успешно загружена. %s", status_text)

        except Exception as e:
            logger.exception("Критическая ошибка при загрузке карты из %s: %s", path, e)
            self.map_canvas.set_error(f"Ошибка при чтении карты:\n{e}")
            self.statusBar().showMessage("Ошибка загрузки карты")

    def _clear_layer_checkboxes(self) -> None:
        """Очистка всех чекбоксов слоев."""
        for chk in self.layer_checkboxes.values():
            self.layers_layout.removeWidget(chk)
            chk.deleteLater()
        self.layer_checkboxes.clear()

    def _add_layer_checkbox(self, layer: MapLayer) -> None:
        """Создание чекбокса для управления видимостью слоя."""
        chk = QCheckBox(layer.display_name)
        chk.setObjectName(f"chk_{layer.id}")
        chk.setChecked(layer.visible)
        chk.setCursor(Qt.CursorShape.PointingHandCursor)
        chk.toggled.connect(
            lambda checked, lid=layer.id: self._on_layer_toggled(lid, checked)
        )
        self.layers_layout.addWidget(chk)
        self.layer_checkboxes[layer.id] = chk

    def _on_layer_toggled(self, layer_id: str, visible: bool) -> None:
        """Обработка переключения видимости слоя пользователем."""
        self.map_canvas.set_layer_visibility(layer_id, visible)

    # -------------------------------------------------------------------------
    # Пользовательские точки (Этапы 4, 5 и 6)
    # -------------------------------------------------------------------------

    def show_add_point_dialog(self) -> None:
        """Открытие модального диалога добавления пользовательской точки."""
        auto_name = f"Точка {len(self._point_service) + 1}"
        dialog = PointDialog(
            parent=self,
            boundary_geometry=self._boundary_geometry,
            default_name=auto_name,
            mode="CREATE",
        )
        if dialog.exec():
            data = dialog.get_point_data()
            if data:
                point = self._point_service.add_point(
                    name=data.name,
                    latitude=data.latitude,
                    longitude=data.longitude,
                    symbol=data.symbol,
                    size=data.size,
                    red=data.red,
                    green=data.green,
                    blue=data.blue,
                )
                self.map_canvas.add_user_point(point)
                self._add_point_to_table(point)
                self.statusBar().showMessage(f"Добавлена точка: {point.name}", 3000)

    def edit_selected_point(self) -> None:
        """Открытие диалога редактирования для выбранной в таблице точки."""
        selected_rows = self.points_table.selectionModel().selectedRows()
        if not selected_rows:
            return

        row = selected_rows[0].row()
        if not (0 <= row < len(self._table_point_ids)):
            return

        point_id = self._table_point_ids[row]
        point = self._point_service.get_point(point_id)
        if not point:
            return

        dialog = PointDialog(
            parent=self,
            boundary_geometry=self._boundary_geometry,
            point=point,
            mode="EDIT",
        )
        if dialog.exec():
            data = dialog.get_point_data()
            if data:
                updated = self._point_service.update_point(
                    point_id=point.id,
                    name=data.name,
                    latitude=data.latitude,
                    longitude=data.longitude,
                    symbol=data.symbol,
                    size=data.size,
                    red=data.red,
                    green=data.green,
                    blue=data.blue,
                )
                self.map_canvas.update_user_point(updated)
                self._update_point_in_table(row, updated)
                self._update_properties_panel(updated)
                self.statusBar().showMessage(f"Точка обновлена: {updated.name}", 3000)
                logger.info("Точка '%s' (id=%s) успешно обновлена", updated.name, updated.id)

    def _add_point_to_table(self, point: MapPoint) -> None:
        """Добавление строки с точкой в таблицу интерфейса."""
        row = self.points_table.rowCount()
        self.points_table.insertRow(row)

        num_item = QTableWidgetItem(str(row + 1))
        num_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        name_item = QTableWidgetItem(point.name)
        lat_item = QTableWidgetItem(f"{point.latitude:.6f}")
        lon_item = QTableWidgetItem(f"{point.longitude:.6f}")
        shape_name = SYMBOL_DISPLAY_NAMES.get(point.symbol, point.symbol)
        shape_item = QTableWidgetItem(shape_name)

        self.points_table.setItem(row, 0, num_item)
        self.points_table.setItem(row, 1, name_item)
        self.points_table.setItem(row, 2, lat_item)
        self.points_table.setItem(row, 3, lon_item)
        self.points_table.setItem(row, 4, shape_item)

        self._table_point_ids.append(point.id)

    def _update_point_in_table(self, row: int, point: MapPoint) -> None:
        """Обновление данных точки в строке таблицы."""
        self.points_table.item(row, 1).setText(point.name)
        self.points_table.item(row, 2).setText(f"{point.latitude:.6f}")
        self.points_table.item(row, 3).setText(f"{point.longitude:.6f}")
        shape_name = SYMBOL_DISPLAY_NAMES.get(point.symbol, point.symbol)
        self.points_table.item(row, 4).setText(shape_name)

    def delete_selected_point(self) -> None:
        """Удаление выбранной в таблице точки."""
        selected_rows = self.points_table.selectionModel().selectedRows()
        if not selected_rows:
            return

        row = selected_rows[0].row()
        if 0 <= row < len(self._table_point_ids):
            point_id = self._table_point_ids.pop(row)
            self._point_service.remove_point(point_id)
            self.map_canvas.remove_user_point(point_id)
            self.points_table.removeRow(row)

            # Обновляем нумерацию строк в таблице
            for r in range(self.points_table.rowCount()):
                item = self.points_table.item(r, 0)
                if item:
                    item.setText(str(r + 1))

            self.btn_delete_point.setEnabled(False)
            self.btn_edit_point.setEnabled(False)
            self._clear_properties_panel()
            self.statusBar().showMessage("Точка удалена", 3000)
            logger.info("Точка с ID %s успешно удалена", point_id)

    def _on_table_row_double_clicked(self, row: int, column: int) -> None:
        """Центрирование карты на точке при двойном клике в таблице."""
        if 0 <= row < len(self._table_point_ids):
            point_id = self._table_point_ids[row]
            point = self._point_service.get_point(point_id)
            if point:
                self.map_canvas.center_on_coordinates(point.longitude, point.latitude)
                self.statusBar().showMessage(f"Фокус на точке: {point.name}", 2000)

    def _on_table_selection_changed(self) -> None:
        """Активация/деактивация кнопок и обновление панели свойств."""
        selected_rows = self.points_table.selectionModel().selectedRows()
        has_selection = bool(selected_rows)
        self.btn_delete_point.setEnabled(has_selection)
        self.btn_edit_point.setEnabled(has_selection)

        if has_selection:
            row = selected_rows[0].row()
            if 0 <= row < len(self._table_point_ids):
                point_id = self._table_point_ids[row]
                point = self._point_service.get_point(point_id)
                if point:
                    self._update_properties_panel(point)
                    return

        self._clear_properties_panel()

    def _update_properties_panel(self, point: MapPoint) -> None:
        """Отображение свойств выбранной точки в правой панели."""
        self.prop_empty_label.setVisible(False)
        self.prop_container.setVisible(True)

        self.prop_name_val.setText(point.name)
        self.prop_lat_val.setText(f"{point.latitude:.6f}")
        self.prop_lon_val.setText(f"{point.longitude:.6f}")
        self.prop_shape_val.setText(SYMBOL_DISPLAY_NAMES.get(point.symbol, point.symbol))
        self.prop_size_val.setText(f"{point.size:.1f} px")
        self.prop_color_val.setText(f"RGB({point.red}, {point.green}, {point.blue})")
        self.prop_color_swatch.setStyleSheet(
            f"background-color: rgb({point.red}, {point.green}, {point.blue}); "
            f"border: 1px solid #777; border-radius: 3px;"
        )

    def _clear_properties_panel(self) -> None:
        """Очистка панели свойств при отсутствии выбора."""
        self.prop_container.setVisible(False)
        self.prop_empty_label.setVisible(True)

    def _show_table_context_menu(self, pos: Any) -> None:
        """Контекстное меню таблицы точек."""
        item = self.points_table.itemAt(pos)
        if item is None:
            return

        menu = QMenu(self)
        act_edit = menu.addAction("Редактировать точку...")
        act_center = menu.addAction("Центрировать на карте")
        menu.addSeparator()
        act_delete = menu.addAction("Удалить точку")

        action = menu.exec(self.points_table.viewport().mapToGlobal(pos))
        if action == act_edit:
            self.edit_selected_point()
        elif action == act_center:
            row = self.points_table.currentRow()
            self._on_table_row_double_clicked(row, 0)
        elif action == act_delete:
            self.delete_selected_point()

