"""Главное окно приложения GeoPoint Mapper."""

import logging
from pathlib import Path
from typing import Any
import uuid

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QActionGroup, QFont, QKeySequence
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMainWindow,
    QMenu,
    QMenuBar,
    QMessageBox,
    QPushButton,
    QSplitter,
    QStatusBar,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from rme_mapper.app_info import APP_NAME
from rme_mapper.backends import MapDataBackend, get_backend
from rme_mapper.i18n import get_language, get_translation_service, set_language, tr
from rme_mapper.maps.map_canvas import MapCanvas
from rme_mapper.maps.map_config import get_default_geopackage_path, get_project_root
from rme_mapper.models.map_layer import LayerRole, MapLayer
from rme_mapper.models.map_point import MapPoint
from rme_mapper.models.map_profile import MapProfile
from rme_mapper.models.project_data import ProjectData
from rme_mapper.services.app_settings_service import AppSettingsService
from rme_mapper.services.coordinate_service import CoordinateService
from rme_mapper.services.geodesic_service import GeodesicService
from rme_mapper.services.geopackage_service import GeoPackageService
from rme_mapper.services.layer_service import LayerService
from rme_mapper.services.map_catalog_service import MapCatalogService
from rme_mapper.services.point_service import PointService
from rme_mapper.services.project_service import ProjectService
from rme_mapper.ui.about_dialog import AboutDialog
from rme_mapper.ui.add_point_dialog import AddPointDialog, PointDialog
from rme_mapper.ui.open_map_dialog import OpenMapDialog

SYMBOL_DISPLAY_NAMES = {
    "circle": "Круг",
    "square": "Квадрат",
    "triangle": "Треугольник",
}


def get_symbol_display_name(symbol: str) -> str:
    """Получение локализованного названия формы маркера."""
    key = f"shape.{symbol}"
    ts = get_translation_service()
    if ts.has_translation(key):
        return ts.translate(key)
    return SYMBOL_DISPLAY_NAMES.get(symbol, symbol)


logger = logging.getLogger("rme_mapper.ui.main_window")


class MainWindow(QMainWindow):
    """Главное окно приложения GeoPoint Mapper."""

    DEFAULT_WIDTH = 1400
    DEFAULT_HEIGHT = 850

    def __init__(
        self,
        parent: QWidget | None = None,
        map_profile: MapProfile | None = None,
        map_path: Path | str | None = None,
        backend: MapDataBackend | None = None,
    ) -> None:
        super().__init__(parent)
        self.resize(self.DEFAULT_WIDTH, self.DEFAULT_HEIGHT)

        self._backend: MapDataBackend = backend or get_backend()
        self._settings_service = AppSettingsService()
        init_lang = self._settings_service.get_language()
        set_language(init_lang)

        self._map_catalog_service = MapCatalogService()
        self._layer_service = LayerService(backend=self._backend)
        self._point_service = PointService()
        self._project_service = ProjectService()

        # Активный профиль карты и активный CRS (по умолчанию карта НЕ загружена)
        if map_profile is not None:
            self._active_profile: MapProfile | None = map_profile
            self._map_path: Path | None = self._active_profile.get_absolute_source_path()
            self._active_crs: str = self._active_profile.crs or "OGC:CRS84"
        elif map_path is not None:
            self._active_profile = self._map_catalog_service.get_profile_by_path(map_path)
            self._map_path = Path(map_path)
            self._active_crs = (self._active_profile.crs if self._active_profile else None) or "OGC:CRS84"
        else:
            self._active_profile = None
            self._map_path = None
            self._active_crs = "OGC:CRS84"

        # Текущий проект и отслеживание изменений
        self._current_project_path: Path | None = None
        self._is_modified: bool = False
        self._project_loaded: bool = False

        # Геометрия границы активной карты
        self._boundary_geometry = None

        # Словарь чекбоксов слоев: layer_id -> QCheckBox
        self.layer_checkboxes: dict[str, QCheckBox] = {}
        self.loaded_layers: list[MapLayer] = []

        # Отображение номеров строк таблицы на MapPoint: row_index -> point_id
        self._table_point_ids: list[str] = []

        self._setup_ui()
        self._update_window_title()

        if self._active_profile or self._map_path:
            self.load_map(self._active_profile if self._active_profile else self._map_path)
        else:
            self._unload_map()

    def _setup_ui(self) -> None:
        """Инициализация компонентов интерфейса."""
        self._create_menu_bar()
        self._create_central_layout()
        self._create_status_bar()
        self.retranslate_ui()

    def _create_menu_bar(self) -> None:
        """Создание верхнего меню приложения."""
        menu_bar = self.menuBar()

        # Меню: Файл
        self.file_menu = menu_bar.addMenu("Файл")

        self.new_action = QAction("Новый проект", self)
        self.new_action.setShortcut(QKeySequence.StandardKey.New)
        self.new_action.triggered.connect(self.new_project)
        self.file_menu.addAction(self.new_action)

        self.open_action = QAction("Открыть проект...", self)
        self.open_action.setShortcut(QKeySequence.StandardKey.Open)
        self.open_action.triggered.connect(self.open_project)
        self.file_menu.addAction(self.open_action)

        self.save_action = QAction("Сохранить", self)
        self.save_action.setShortcut(QKeySequence.StandardKey.Save)
        self.save_action.triggered.connect(self.save_project)
        self.file_menu.addAction(self.save_action)

        self.save_as_action = QAction("Сохранить как...", self)
        self.save_as_action.setShortcut(QKeySequence("Ctrl+Shift+S"))
        self.save_as_action.triggered.connect(self.save_project_as)
        self.file_menu.addAction(self.save_as_action)

        self.file_menu.addSeparator()

        self.exit_action = QAction("Выход", self)
        self.exit_action.setShortcut(QKeySequence("Ctrl+Q"))
        self.exit_action.triggered.connect(self.close)
        self.file_menu.addAction(self.exit_action)

        # Меню: Карта
        self.map_menu = menu_bar.addMenu("Карта")

        self.open_map_action = QAction("Открыть карту...", self)
        self.open_map_action.setShortcut(QKeySequence("Ctrl+L"))
        self.open_map_action.triggered.connect(lambda: self.open_map())
        self.map_menu.addAction(self.open_map_action)

        self.close_map_action = QAction("Закрыть карту", self)
        self.close_map_action.triggered.connect(lambda: self.close_map())
        self.map_menu.addAction(self.close_map_action)

        self.map_menu.addSeparator()

        self.fit_action = QAction("Показать всю карту", self)
        self.fit_action.triggered.connect(lambda: self.map_canvas.fit_to_view())
        self.map_menu.addAction(self.fit_action)

        # Меню: Координаты
        self.coords_menu = menu_bar.addMenu("Координаты")
        self.add_pt_action = QAction("Добавить точку", self)
        self.add_pt_action.triggered.connect(self.show_add_point_dialog)
        self.coords_menu.addAction(self.add_pt_action)

        # Меню: Импорт
        self.import_menu = menu_bar.addMenu("Импорт")

        # Меню: Экспорт
        self.export_menu = menu_bar.addMenu("Экспорт")

        # Меню: Настройки
        self.settings_menu = menu_bar.addMenu("Настройки")
        self.language_menu = self.settings_menu.addMenu("Язык")

        self.lang_action_group = QActionGroup(self)
        self.lang_action_group.setExclusive(True)

        self.lang_ru_action = QAction("Русский", self)
        self.lang_ru_action.setCheckable(True)
        self.lang_action_group.addAction(self.lang_ru_action)
        self.language_menu.addAction(self.lang_ru_action)

        self.lang_en_action = QAction("English", self)
        self.lang_en_action.setCheckable(True)
        self.lang_action_group.addAction(self.lang_en_action)
        self.language_menu.addAction(self.lang_en_action)

        if get_language() == "en":
            self.lang_en_action.setChecked(True)
        else:
            self.lang_ru_action.setChecked(True)

        self.lang_ru_action.triggered.connect(lambda: self.switch_language("ru"))
        self.lang_en_action.triggered.connect(lambda: self.switch_language("en"))

        # Меню: Справка
        self.help_menu = menu_bar.addMenu("Справка")
        self.about_action = QAction("О программе...", self)
        self.about_action.triggered.connect(self.show_about_dialog)
        self.help_menu.addAction(self.about_action)


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
        self.layers_title_label = QLabel("Слои")
        layers_font = QFont()
        layers_font.setBold(True)
        layers_font.setPointSize(11)
        self.layers_title_label.setFont(layers_font)
        layout.addWidget(self.layers_title_label)

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
        self.points_title_label = QLabel("Точки")
        points_font = QFont()
        points_font.setBold(True)
        points_font.setPointSize(11)
        self.points_title_label.setFont(points_font)
        points_header_layout.addWidget(self.points_title_label)
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
        self.points_table = QTableWidget(0, 6, self)
        self.points_table.setObjectName("pointsTable")
        self.points_table.setHorizontalHeaderLabels(["№", "Название", "Широта", "Долгота", "Форма", "Радиус"])
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
        map_name_init = self._active_profile.name if self._active_profile else "не загружена"
        self.map_title_label = QLabel(f"Карта: {map_name_init}")
        header_font = QFont()
        header_font.setBold(True)
        header_font.setPointSize(12)
        self.map_title_label.setFont(header_font)
        header_layout.addWidget(self.map_title_label)
        layout.addLayout(header_layout)

        self.map_canvas = MapCanvas(panel)
        self.map_placeholder = self.map_canvas
        self.btn_open_map = self.map_canvas.btn_open_map
        self.btn_open_map_center = self.map_canvas.btn_open_map
        self.map_canvas.btn_open_map.clicked.connect(lambda: self.open_map())
        layout.addWidget(self.map_canvas, stretch=1)

        return panel

    def _create_right_panel(self) -> QWidget:
        """Создание правой панели: заголовок 'Свойства' и карточка свойств выбранной точки."""
        panel = QWidget()
        panel.setObjectName("rightPanel")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        self.properties_title_label = QLabel("Свойства")
        title_font = QFont()
        title_font.setBold(True)
        title_font.setPointSize(11)
        self.properties_title_label.setFont(title_font)
        layout.addWidget(self.properties_title_label)

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

        self.prop_name_lbl = QLabel("<b>Название:</b>")
        self.prop_name_val = QLabel("—")
        self.prop_name_val.setWordWrap(True)
        prop_form.addRow(self.prop_name_lbl, self.prop_name_val)

        self.prop_lat_lbl = QLabel("<b>Широта:</b>")
        self.prop_lat_val = QLabel("—")
        prop_form.addRow(self.prop_lat_lbl, self.prop_lat_val)

        self.prop_lon_lbl = QLabel("<b>Долгота:</b>")
        self.prop_lon_val = QLabel("—")
        prop_form.addRow(self.prop_lon_lbl, self.prop_lon_val)

        self.prop_shape_lbl = QLabel("<b>Форма:</b>")
        self.prop_shape_val = QLabel("—")
        prop_form.addRow(self.prop_shape_lbl, self.prop_shape_val)

        self.prop_size_lbl = QLabel("<b>Размер:</b>")
        self.prop_size_val = QLabel("—")
        prop_form.addRow(self.prop_size_lbl, self.prop_size_val)

        color_row = QHBoxLayout()
        self.prop_color_val = QLabel("—")
        self.prop_color_swatch = QFrame()
        self.prop_color_swatch.setFixedSize(20, 20)
        self.prop_color_swatch.setStyleSheet("border: 1px solid #999; border-radius: 3px;")
        color_row.addWidget(self.prop_color_val)
        color_row.addWidget(self.prop_color_swatch)
        color_row.addStretch()
        self.prop_color_lbl = QLabel("<b>Цвет (RGB):</b>")
        prop_form.addRow(self.prop_color_lbl, color_row)

        self.prop_zone_lbl = QLabel("<b>Зона:</b>")
        self.prop_zone_val = QLabel("—")
        prop_form.addRow(self.prop_zone_lbl, self.prop_zone_val)

        self.prop_zone_radius_lbl = QLabel("<b>Радиус зоны:</b>")
        self.prop_zone_radius_val = QLabel("—")
        prop_form.addRow(self.prop_zone_radius_lbl, self.prop_zone_radius_val)

        zone_color_row = QHBoxLayout()
        self.prop_zone_color_val = QLabel("—")
        self.prop_zone_color_swatch = QFrame()
        self.prop_zone_color_swatch.setFixedSize(20, 20)
        self.prop_zone_color_swatch.setStyleSheet("border: 1px solid #999; border-radius: 3px;")
        zone_color_row.addWidget(self.prop_zone_color_val)
        zone_color_row.addWidget(self.prop_zone_color_swatch)
        zone_color_row.addStretch()
        self.prop_zone_color_lbl = QLabel("<b>Цвет зоны:</b>")
        prop_form.addRow(self.prop_zone_color_lbl, zone_color_row)

        self.prop_zone_opacity_lbl = QLabel("<b>Прозрачность зоны:</b>")
        self.prop_zone_opacity_val = QLabel("—")
        prop_form.addRow(self.prop_zone_opacity_lbl, self.prop_zone_opacity_val)

        self.prop_container.setVisible(False)
        placeholder_layout.addWidget(self.prop_container)
        placeholder_layout.addStretch()

        layout.addWidget(self.properties_placeholder, stretch=1)
        return panel



    def _create_status_bar(self) -> None:
        """Создание нижней строки состояния."""
        status_bar = QStatusBar(self)
        status_bar.setObjectName("statusBar")
        status_bar.showMessage(tr("status.no_map") if not self._active_profile else tr("status.ready"))
        self.setStatusBar(status_bar)

    def switch_language(self, lang_code: str) -> None:
        """Переключение языка интерфейса без перезапуска приложения."""
        if get_language() == lang_code:
            return
        set_language(lang_code)
        self._settings_service.set_language(lang_code)
        self.retranslate_ui()

    def retranslate_ui(self) -> None:
        """Динамическое обновление всех компонентов интерфейса на активный язык."""
        cur_lang = get_language()
        if hasattr(self, "lang_ru_action") and hasattr(self, "lang_en_action"):
            if cur_lang == "en":
                self.lang_en_action.setChecked(True)
            else:
                self.lang_ru_action.setChecked(True)

        # 1. Меню верхнего уровня
        if hasattr(self, "file_menu"):
            self.file_menu.setTitle(tr("menu.file"))
        if hasattr(self, "map_menu"):
            self.map_menu.setTitle(tr("menu.map"))
        if hasattr(self, "coords_menu"):
            self.coords_menu.setTitle(tr("menu.coordinates"))
        if hasattr(self, "import_menu"):
            self.import_menu.setTitle(tr("menu.import"))
        if hasattr(self, "export_menu"):
            self.export_menu.setTitle(tr("menu.export"))
        if hasattr(self, "settings_menu"):
            self.settings_menu.setTitle(tr("menu.settings"))
        if hasattr(self, "language_menu"):
            self.language_menu.setTitle(tr("menu.language"))
        if hasattr(self, "help_menu"):
            self.help_menu.setTitle(tr("menu.help"))

        # 2. Действия (Actions)
        if hasattr(self, "new_action"):
            self.new_action.setText(tr("action.new_project"))
        if hasattr(self, "open_action"):
            self.open_action.setText(tr("action.open_project"))
        if hasattr(self, "save_action"):
            self.save_action.setText(tr("action.save"))
        if hasattr(self, "save_as_action"):
            self.save_as_action.setText(tr("action.save_as"))
        if hasattr(self, "exit_action"):
            self.exit_action.setText(tr("action.exit"))
        if hasattr(self, "open_map_action"):
            self.open_map_action.setText(tr("action.open_map"))
        if hasattr(self, "close_map_action"):
            self.close_map_action.setText(tr("action.close_map"))
        if hasattr(self, "fit_action"):
            self.fit_action.setText(tr("action.fit_map"))
        if hasattr(self, "add_pt_action"):
            self.add_pt_action.setText(tr("action.add_point"))
        if hasattr(self, "about_action"):
            self.about_action.setText(tr("action.about"))

        # 3. Панели
        if hasattr(self, "layers_title_label"):
            self.layers_title_label.setText(tr("panel.layers"))
        if hasattr(self, "points_title_label"):
            self.points_title_label.setText(tr("panel.points"))
        if hasattr(self, "properties_title_label"):
            self.properties_title_label.setText(tr("panel.properties"))

        # 4. Кнопки панели точек
        if hasattr(self, "btn_add_point"):
            self.btn_add_point.setText(tr("btn.add_point"))
        if hasattr(self, "btn_edit_point"):
            self.btn_edit_point.setText(tr("btn.edit_point"))
        if hasattr(self, "btn_delete_point"):
            self.btn_delete_point.setText(tr("btn.delete_point"))

        # 5. Заголовки таблицы точек
        if hasattr(self, "points_table"):
            self.points_table.setHorizontalHeaderLabels([
                tr("table.col_index"),
                tr("table.col_name"),
                tr("table.col_lat"),
                tr("table.col_lon"),
                tr("table.col_shape"),
                tr("table.col_radius"),
            ])
            for row, point_id in enumerate(self._table_point_ids):
                point = self._point_service.get_point(point_id)
                if point:
                    self.points_table.item(row, 4).setText(get_symbol_display_name(point.symbol))
                    self.points_table.item(row, 5).setText(GeodesicService.format_radius(point.radius_m, point.zone_enabled))

        # 6. Панель свойств
        if hasattr(self, "prop_empty_label"):
            self.prop_empty_label.setText(tr("properties.empty_hint"))
        if hasattr(self, "prop_name_lbl"):
            self.prop_name_lbl.setText(f"<b>{tr('properties.name')}</b>")
        if hasattr(self, "prop_lat_lbl"):
            self.prop_lat_lbl.setText(f"<b>{tr('properties.latitude')}</b>")
        if hasattr(self, "prop_lon_lbl"):
            self.prop_lon_lbl.setText(f"<b>{tr('properties.longitude')}</b>")
        if hasattr(self, "prop_shape_lbl"):
            self.prop_shape_lbl.setText(f"<b>{tr('properties.shape')}</b>")
        if hasattr(self, "prop_size_lbl"):
            self.prop_size_lbl.setText(f"<b>{tr('properties.size')}</b>")
        if hasattr(self, "prop_color_lbl"):
            self.prop_color_lbl.setText(f"<b>{tr('properties.color')}</b>")
        if hasattr(self, "prop_zone_lbl"):
            self.prop_zone_lbl.setText(f"<b>{tr('properties.zone')}</b>")
        if hasattr(self, "prop_zone_radius_lbl"):
            self.prop_zone_radius_lbl.setText(f"<b>{tr('properties.radius')}</b>")
        if hasattr(self, "prop_zone_color_lbl"):
            self.prop_zone_color_lbl.setText(f"<b>{tr('properties.zone_color')}</b>")
        if hasattr(self, "prop_zone_opacity_lbl"):
            self.prop_zone_opacity_lbl.setText(f"<b>{tr('properties.opacity')}</b>")

        selected_rows = self.points_table.selectionModel().selectedRows() if hasattr(self, "points_table") else []
        if selected_rows and 0 <= selected_rows[0].row() < len(self._table_point_ids):
            point = self._point_service.get_point(self._table_point_ids[selected_rows[0].row()])
            if point:
                self._update_properties_panel(point)

        # 7. Центральная панель и MapCanvas
        if hasattr(self, "map_title_label"):
            if not self._active_profile:
                self.map_title_label.setText(tr("status.no_map"))
            else:
                self.map_title_label.setText(f"{tr('menu.map')}: {self._active_profile.name}")
        if hasattr(self, "map_canvas"):
            self.map_canvas.retranslate_ui()

        # 8. Строка состояния и заголовок окна
        if self.statusBar():
            if not self._active_profile:
                self.statusBar().showMessage(tr("status.no_map"))
            else:
                self.statusBar().showMessage(
                    tr("status.map_info", name=self._active_profile.name, crs=self._active_crs, count=len(self.loaded_layers))
                )
        self._update_window_title()

    def _unload_map(self) -> None:
        """Перевод приложения в состояние без активной карты."""
        self._active_profile = None
        self._map_path = None
        self._boundary_geometry = None
        self.loaded_layers.clear()
        self._clear_layer_checkboxes()
        self.map_canvas.clear_map()
        if hasattr(self, "map_title_label"):
            self.map_title_label.setText(tr("status.no_map"))
        if self.statusBar():
            self.statusBar().showMessage(tr("status.no_map"))
        if hasattr(self, "btn_add_point"):
            self.btn_add_point.setEnabled(False)
        if hasattr(self, "btn_edit_point"):
            self.btn_edit_point.setEnabled(False)
        if hasattr(self, "btn_delete_point"):
            self.btn_delete_point.setEnabled(False)


    def open_map(self, map_target: MapProfile | Path | str | None = None) -> bool:
        """Открытие карты через OpenMapDialog или напрямую по объекту/пути."""
        if map_target is not None:
            self.load_map(map_target)
            return True

        dialog = OpenMapDialog(
            parent=self,
            catalog_service=self._map_catalog_service,
            backend=self._backend,
        )
        if dialog.exec():
            profile = dialog.get_map_profile()
            if profile:
                self.load_map(profile)
                if self._current_project_path:
                    self._set_modified(True)
                return True
        return False

    def close_map(self, prompt: bool = True) -> bool:
        """Безопасная выгрузка карты из приложения."""
        if self._active_profile is None and self._map_path is None:
            return True

        if prompt and len(self._point_service) > 0:
            reply = QMessageBox.question(
                self,
                tr("dialog.close_map_title"),
                tr("dialog.close_map_text", count=len(self._point_service)),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
                return False

        self._unload_map()
        if self._current_project_path:
            self._set_modified(True)
        return True

    def load_map(self, map_target: MapProfile | Path | str) -> None:
        """Загрузка слоев карты из MapProfile или пути к файлу."""
        profile: MapProfile | None = None
        if isinstance(map_target, MapProfile):
            profile = map_target
            path = profile.get_absolute_source_path()
        else:
            path = Path(map_target)
            profile = self._map_catalog_service.get_profile_by_path(path)

        self._active_profile = profile
        self._map_path = path

        map_title = profile.name if profile else path.stem
        logger.info("Загрузка карты '%s' из: %s", map_title, path)

        if not self._backend.exists(path):
            err_msg = f"{tr('msg.map_file_not_found')}:\n{path}"
            logger.error("Файл карты не найден: %s", path)
            self.map_canvas.set_error(err_msg)
            self.statusBar().showMessage(tr("status.error_map_not_found"))
            return

        try:
            if profile:
                discovered_layers = self._layer_service.load_profile_layers(profile)
            else:
                discovered_layers = self._layer_service.discover_layers(path)

            logger.info("Обнаружено поддерживаемых слоев: %d", len(discovered_layers))

            if not discovered_layers:
                err_msg = tr("msg.no_layers_found")
                logger.error(err_msg)
                self.map_canvas.set_error(err_msg)
                self.statusBar().showMessage(tr("status.error_no_layers"))
                return

            self._clear_layer_checkboxes()

            successfully_loaded: list[MapLayer] = []
            common_crs = (profile.crs if profile and profile.crs else None) or "OGC:CRS84"
            self._boundary_geometry = None

            for layer in discovered_layers:
                try:
                    logger.info("Загрузка слоя '%s' (%s)...", layer.display_name, layer.source_name)
                    gdf = self._layer_service.load_layer_data(path, layer)

                    if gdf.crs and not (profile and profile.crs):
                        common_crs = gdf.crs.to_string()

                    # Сохраняем геометрию границы
                    is_boundary = (layer.role == LayerRole.BOUNDARY)
                    if profile and profile.boundary_layer:
                        is_boundary = (layer.source_name == profile.boundary_layer or layer.id == profile.boundary_layer)

                    if is_boundary:
                        try:
                            self._boundary_geometry = gdf.union_all()
                        except AttributeError:
                            self._boundary_geometry = gdf.unary_union

                    self.map_canvas.add_layer_item(layer, gdf)
                    successfully_loaded.append(layer)
                    self._add_layer_checkbox(layer)

                except Exception as layer_err:
                    logger.exception("Ошибка загрузки слоя '%s': %s", layer.display_name, layer_err)
                    if (profile and profile.boundary_required and layer.role == LayerRole.BOUNDARY):
                        self.map_canvas.set_error(f"Ошибка чтения границы карты:\n{layer_err}")
                        self.statusBar().showMessage("Ошибка чтения границы карты")
                        return

            self.loaded_layers = successfully_loaded
            self._active_crs = common_crs

            # Обновляем заголовок и строку состояния
            self.map_title_label.setText(f"Карта: {map_title}")
            status_text = f"Карта: {map_title} | {self._active_crs} | Слоёв: {len(successfully_loaded)}"
            self.statusBar().showMessage(status_text)
            self.btn_add_point.setEnabled(True)
            logger.info("Карта успешно загружена. %s", status_text)

            # Пересчитываем пользовательские точки под новую CRS
            self._reproject_all_points()

            # Автоподгонка охвата
            self.map_canvas.fit_to_view()

        except Exception as e:
            logger.exception("Критическая ошибка при загрузке карты из %s: %s", path, e)
            self.map_canvas.set_error(f"Ошибка при чтении карты:\n{e}")
            self.statusBar().showMessage("Ошибка загрузки карты")

    def _reproject_all_points(self) -> None:
        """Пересчет экранных координат всех точек и полигонов зон под активный CRS карты."""
        for pt in self._point_service.get_points():
            mx, my = CoordinateService.transform_xy(
                pt.longitude, pt.latitude,
                source_crs=pt.source_crs,
                target_crs=self._active_crs,
            )
            zone_poly = None
            if pt.zone_enabled and pt.radius_m > 0:
                geo_circle = GeodesicService.create_geodesic_circle(
                    pt.longitude, pt.latitude, pt.radius_m
                )
                zone_poly = CoordinateService.transform_polygon(
                    geo_circle,
                    source_crs="EPSG:4326",
                    target_crs=self._active_crs,
                )
            self.map_canvas.add_user_point(pt, map_x=mx, map_y=my, zone_polygon=zone_poly)

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
        for layer in self.loaded_layers:
            if layer.id == layer_id:
                layer.visible = visible
                break
        self.map_canvas.set_layer_visibility(layer_id, visible)
        self._set_modified(True)

    # -------------------------------------------------------------------------
    # Пользовательские точки (Этапы 4, 5, 6 и 7)
    # -------------------------------------------------------------------------

    def show_add_point_dialog(self) -> None:
        """Открытие модального диалога добавления пользовательской точки."""
        if self._active_profile is None and self._map_path is None:
            QMessageBox.information(
                self,
                tr("dialog.no_map_title"),
                tr("dialog.no_map_text"),
            )
            return

        auto_name = f"{tr('point.default_name_prefix')} {len(self._point_service) + 1}"
        dialog = PointDialog(
            parent=self,
            boundary_geometry=self._boundary_geometry,
            default_name=auto_name,
            mode="CREATE",
            map_name=self._active_profile.name if self._active_profile else None,
            map_extent=self._active_profile.extent if self._active_profile else None,
            map_crs=self._active_crs,
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
                    zone_enabled=data.zone_enabled,
                    radius_m=data.radius_m,
                    zone_red=data.zone_red,
                    zone_green=data.zone_green,
                    zone_blue=data.zone_blue,
                    zone_opacity=data.zone_opacity,
                )
                mx, my = CoordinateService.transform_xy(
                    point.longitude, point.latitude,
                    source_crs=point.source_crs,
                    target_crs=self._active_crs,
                )
                zone_poly = None
                if point.zone_enabled and point.radius_m > 0:
                    geo_c = GeodesicService.create_geodesic_circle(
                        point.longitude, point.latitude, point.radius_m
                    )
                    zone_poly = CoordinateService.transform_polygon(
                        geo_c,
                        source_crs="EPSG:4326",
                        target_crs=self._active_crs,
                    )
                self.map_canvas.add_user_point(point, map_x=mx, map_y=my, zone_polygon=zone_poly)
                self._add_point_to_table(point)
                self._set_modified(True)
                self.statusBar().showMessage(tr("status.point_added", name=point.name), 3000)

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
            map_name=self._active_profile.name if self._active_profile else None,
            map_extent=self._active_profile.extent if self._active_profile else None,
            map_crs=self._active_crs,
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
                    zone_enabled=data.zone_enabled,
                    radius_m=data.radius_m,
                    zone_red=data.zone_red,
                    zone_green=data.zone_green,
                    zone_blue=data.zone_blue,
                    zone_opacity=data.zone_opacity,
                )
                mx, my = CoordinateService.transform_xy(
                    updated.longitude, updated.latitude,
                    source_crs=updated.source_crs,
                    target_crs=self._active_crs,
                )
                zone_poly = None
                if updated.zone_enabled and updated.radius_m > 0:
                    geo_c = GeodesicService.create_geodesic_circle(
                        updated.longitude, updated.latitude, updated.radius_m
                    )
                    zone_poly = CoordinateService.transform_polygon(
                        geo_c,
                        source_crs="EPSG:4326",
                        target_crs=self._active_crs,
                    )
                self.map_canvas.update_user_point(updated, map_x=mx, map_y=my, zone_polygon=zone_poly)
                self._update_point_in_table(row, updated)
                self._update_properties_panel(updated)
                self._set_modified(True)
                self.statusBar().showMessage(tr("status.point_updated", name=updated.name), 3000)
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
        shape_name = get_symbol_display_name(point.symbol)
        shape_item = QTableWidgetItem(shape_name)
        radius_str = GeodesicService.format_radius(point.radius_m, point.zone_enabled)
        radius_item = QTableWidgetItem(radius_str)

        self.points_table.setItem(row, 0, num_item)
        self.points_table.setItem(row, 1, name_item)
        self.points_table.setItem(row, 2, lat_item)
        self.points_table.setItem(row, 3, lon_item)
        self.points_table.setItem(row, 4, shape_item)
        self.points_table.setItem(row, 5, radius_item)

        self._table_point_ids.append(point.id)

    def _update_point_in_table(self, row: int, point: MapPoint) -> None:
        """Обновление данных точки в строке таблицы."""
        self.points_table.item(row, 1).setText(point.name)
        self.points_table.item(row, 2).setText(f"{point.latitude:.6f}")
        self.points_table.item(row, 3).setText(f"{point.longitude:.6f}")
        shape_name = get_symbol_display_name(point.symbol)
        self.points_table.item(row, 4).setText(shape_name)
        radius_str = GeodesicService.format_radius(point.radius_m, point.zone_enabled)
        self.points_table.item(row, 5).setText(radius_str)

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
            self._set_modified(True)
            self.statusBar().showMessage(tr("status.point_deleted"), 3000)
            logger.info("Точка с ID %s успешно удалена", point_id)

    def _on_table_row_double_clicked(self, row: int, column: int) -> None:
        """Центрирование карты на точке при двойном клике в таблице."""
        if 0 <= row < len(self._table_point_ids):
            point_id = self._table_point_ids[row]
            point = self._point_service.get_point(point_id)
            if point:
                mx, my = CoordinateService.transform_xy(
                    point.longitude, point.latitude,
                    source_crs=point.source_crs,
                    target_crs=self._active_crs,
                )
                self.map_canvas.center_on_map_coordinates(mx, my)
                self.statusBar().showMessage(tr("status.focus_point", name=point.name), 2000)

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
        self.prop_shape_val.setText(get_symbol_display_name(point.symbol))
        self.prop_size_val.setText(f"{point.size:.1f} px")
        self.prop_color_val.setText(f"RGB({point.red}, {point.green}, {point.blue})")
        self.prop_color_swatch.setStyleSheet(
            f"background-color: rgb({point.red}, {point.green}, {point.blue}); "
            f"border: 1px solid #777; border-radius: 3px;"
        )

        self.prop_zone_val.setText(tr("common.yes") if point.zone_enabled else tr("common.no"))
        if point.zone_enabled:
            self.prop_zone_radius_val.setText(GeodesicService.format_radius(point.radius_m, True))
            self.prop_zone_color_val.setText(f"RGB({point.zone_red}, {point.zone_green}, {point.zone_blue})")
            self.prop_zone_color_swatch.setStyleSheet(
                f"background-color: rgb({point.zone_red}, {point.zone_green}, {point.zone_blue}); "
                f"border: 1px solid #777; border-radius: 3px;"
            )
            self.prop_zone_opacity_val.setText(f"{point.zone_opacity}%")
        else:
            self.prop_zone_radius_val.setText("—")
            self.prop_zone_color_val.setText("—")
            self.prop_zone_color_swatch.setStyleSheet("background-color: transparent; border: 1px solid #ccc; border-radius: 3px;")
            self.prop_zone_opacity_val.setText("—")

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
        act_edit = menu.addAction(tr("menu.ctx_edit"))
        act_center = menu.addAction(tr("menu.ctx_center"))
        menu.addSeparator()
        act_delete = menu.addAction(tr("menu.ctx_delete"))

        action = menu.exec(self.points_table.viewport().mapToGlobal(pos))
        if action == act_edit:
            self.edit_selected_point()
        elif action == act_center:
            row = self.points_table.currentRow()
            self._on_table_row_double_clicked(row, 0)
        elif action == act_delete:
            self.delete_selected_point()

    # -------------------------------------------------------------------------
    # Управление проектом (Этап 8: Новый, Открыть, Сохранить, Сохранить как)
    # -------------------------------------------------------------------------

    @property
    def is_modified(self) -> bool:
        """Признак наличия несохраненных изменений в проекте."""
        return self._is_modified

    @property
    def current_project_path(self) -> Path | None:
        """Текущий путь к файлу проекта."""
        return self._current_project_path

    def _set_modified(self, modified: bool = True) -> None:
        """Установка флага изменений и обновление заголовка окна."""
        self._is_modified = modified
        if modified:
            self._project_loaded = True
        self._update_window_title()

    def _update_window_title(self) -> None:
        """Обновление заголовка окна в формате: <APP_NAME> — <Имя>[ *]."""
        proj_name = self._current_project_path.name if self._current_project_path else tr("project.untitled")
        mod_suffix = " *" if self._is_modified else ""
        self.setWindowTitle(f"{APP_NAME} — {proj_name}{mod_suffix}")

    def show_about_dialog(self) -> None:
        """Открытие диалогового окна 'О программе' со сведениями о версии и авторе."""
        dlg = AboutDialog(self)
        dlg.exec()

    def closeEvent(self, event: Any) -> None:
        """Обработка события закрытия окна с проверкой несохраненных изменений."""
        if self._maybe_save_prompt(tr("dialog.unsaved_action_exit")):
            event.accept()
        else:
            event.ignore()

    def _maybe_save_prompt(self, action_name: str | None = None) -> bool:
        """Запрос сохранения при наличии несохраненных изменений.

        Возвращает:
            True — продолжить действие (изменения сохранены или не требовались,
                   либо пользователь выбрал 'Не сохранять').
            False — отменить действие (пользователь нажал 'Отмена' или отменил диалог сохранения).
        """
        if not self._is_modified:
            return True

        if action_name is None:
            action_name = tr("dialog.unsaved_action_exit")

        proj_name = self._current_project_path.name if self._current_project_path else tr("project.untitled")
        reply = QMessageBox.question(
            self,
            tr("dialog.unsaved_title"),
            tr("dialog.unsaved_text", name=proj_name, action=action_name),
            QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Save,
        )

        if reply == QMessageBox.StandardButton.Save:
            return self.save_project()
        elif reply == QMessageBox.StandardButton.Discard:
            return True
        else:  # Cancel
            return False

    def new_project(self) -> bool:
        """Создание нового пустого проекта."""
        if not self._maybe_save_prompt(tr("dialog.unsaved_action_new")):
            return False

        self._clear_all_points()
        self._unload_map()
        self._current_project_path = None
        self._project_loaded = False
        self._set_modified(False)
        self.statusBar().showMessage(tr("status.no_map"))
        logger.info("Создан новый проект")
        return True

    def save_project(self) -> bool:
        """Сохранение проекта. Если путь еще не задан, вызывается save_project_as."""
        if self._current_project_path is None:
            return self.save_project_as()
        return self._do_save(self._current_project_path)

    def save_project_as(self, file_path: Path | str | None = None) -> bool:
        """Сохранение проекта с выбором пути в QFileDialog или по указанному пути."""
        if file_path is None:
            initial_dir = str(self._current_project_path.parent) if self._current_project_path else ""
            chosen, _ = QFileDialog.getSaveFileName(
                self,
                tr("dialog.save_project_title"),
                initial_dir,
                tr("filter.project_files"),
            )
            if not chosen:
                return False
            path = Path(chosen)
        else:
            path = Path(file_path)

        if path.suffix.lower() not in (".gpmap", ".rmeproject"):
            path = path.with_suffix(".gpmap")

        return self._do_save(path)

    def _do_save(self, path: Path) -> bool:
        """Атомарная запись проекта через ProjectService."""
        try:
            points = self._point_service.get_points()
            project_data = self._project_service.build_project_data(
                map_path=self._map_path,
                layers=self.loaded_layers,
                points=points,
                map_id=self._active_profile.id if self._active_profile else "",
                map_profile=self._active_profile,
            )
            saved_path = self._project_service.save_project(project_data, path)
            self._current_project_path = saved_path
            self._project_loaded = True
            self._set_modified(False)
            self.statusBar().showMessage(tr("status.project_saved", path=saved_path.name), 3000)
            logger.info("Проект успешно сохранен в %s", saved_path)
            return True
        except Exception as e:
            logger.exception("Ошибка при сохранении проекта в %s: %s", path, e)
            QMessageBox.critical(
                self,
                tr("dialog.error_title"),
                tr("msg.save_project_error", err=str(e)),
            )
            return False

    def open_project(self, file_path: Path | str | None = None) -> bool:
        """Открытие проекта из файла *.gpmap или *.rmeproject."""
        if not self._maybe_save_prompt(tr("dialog.unsaved_action_open")):
            return False

        if not file_path:
            initial_dir = str(self._current_project_path.parent) if self._current_project_path else ""
            selected_file, _ = QFileDialog.getOpenFileName(
                self,
                tr("dialog.open_project_title"),
                initial_dir,
                tr("filter.project_files_all"),
            )
            if not selected_file:
                return False
            path = Path(selected_file)
        else:
            path = Path(file_path)

        try:
            project = self._project_service.load_project(path)
        except Exception as e:
            logger.exception("Ошибка открытия проекта из %s: %s", path, e)
            QMessageBox.critical(
                self,
                tr("dialog.open_project_error_title"),
                tr("msg.open_project_error", path=str(path), err=str(e)),
            )
            return False

        # Разрешаем карту проекта
        target_map_path: Path | None = None
        target_profile: MapProfile | None = None

        if project.map.map_id:
            target_profile = self._map_catalog_service.get_profile(project.map.map_id)
            if target_profile:
                target_map_path = target_profile.get_absolute_source_path()

        if not target_map_path and project.map.relative_path:
            p = Path(project.map.relative_path)
            if p.is_absolute() and p.exists():
                target_map_path = p
            elif (path.parent / p).exists():
                target_map_path = (path.parent / p).resolve()
            elif (get_project_root() / p).exists():
                target_map_path = (get_project_root() / p).resolve()
            elif p.exists():
                target_map_path = p.resolve()

        has_map_reference = bool(project.map.map_id or project.map.relative_path)

        if has_map_reference and (target_map_path is None or not target_map_path.exists()):
            msg_box = QMessageBox(self)
            msg_box.setWindowTitle(tr("dialog.map_not_found_title"))
            msg_box.setIcon(QMessageBox.Icon.Warning)
            map_name_display = project.map.name or project.map.relative_path or project.map.map_id
            msg_box.setText(tr("dialog.map_not_found_text", name=map_name_display))
            btn_find = msg_box.addButton(tr("dialog.map_not_found_find"), QMessageBox.ButtonRole.ActionRole)
            btn_no_map = msg_box.addButton(tr("dialog.map_not_found_open_without"), QMessageBox.ButtonRole.ActionRole)
            btn_cancel = msg_box.addButton(tr("btn.cancel"), QMessageBox.ButtonRole.RejectRole)
            msg_box.setDefaultButton(btn_find)
            msg_box.exec()

            clicked = msg_box.clickedButton()
            if clicked == btn_cancel:
                return False
            elif clicked == btn_find:
                chosen, _ = QFileDialog.getOpenFileName(
                    self,
                    tr("dialog.locate_map_title"),
                    str(path.parent),
                    tr("filter.geopackage_files"),
                )
                if not chosen:
                    return False
                target_map_path = Path(chosen)
                target_profile = None
            else:  # btn_no_map
                target_map_path = None
                target_profile = None

        if target_profile:
            self.load_map(target_profile)
        elif target_map_path and target_map_path.exists():
            if project.map.layers:
                runtime_prof = MapProfile(
                    id=project.map.map_id or f"runtime_{uuid.uuid4().hex[:8]}",
                    name=project.map.name or target_map_path.stem,
                    source_type=project.map.source_type or "geopackage",
                    source_path=str(target_map_path),
                    base_dir=target_map_path.parent,
                    crs=project.map.crs,
                    boundary_layer=project.map.boundary_layer,
                    layers=project.map.layers,
                )
                self.load_map(runtime_prof)
            else:
                self.load_map(target_map_path)
        else:
            self._unload_map()

        self._apply_project_data(project)
        self._current_project_path = path
        self._project_loaded = True
        self._set_modified(False)
        self.statusBar().showMessage(tr("status.project_opened", name=path.name), 3000)
        logger.info("Проект открыт: %s (%d точек)", path, len(project.points))
        return True

    def _apply_project_data(self, project: ProjectData) -> None:
        """Применение десериализованных данных проекта к интерфейсу и сцене."""
        # 1. Очищаем существующие пользовательские точки
        self._clear_all_points()

        # 2. Восстанавливаем видимость слоев
        for layer in self.loaded_layers:
            vis = None
            if layer.id in project.layers:
                vis = project.layers[layer.id]
            elif hasattr(layer, "role") and hasattr(layer.role, "value") and layer.role.value in project.layers:
                vis = project.layers[layer.role.value]

            if vis is not None:
                layer.visible = vis
                chk = self.layer_checkboxes.get(layer.id)
                if chk:
                    chk.blockSignals(True)
                    chk.setChecked(vis)
                    chk.blockSignals(False)
                self.map_canvas.set_layer_visibility(layer.id, vis)

        # 3. Восстанавливаем точки и зоны
        for pt_data in project.points:
            pt = pt_data.to_map_point()
            added_pt = self._point_service.add_point(
                name=pt.name,
                latitude=pt.latitude,
                longitude=pt.longitude,
                source_crs=pt.source_crs,
                point_id=pt.id,
                symbol=pt.symbol,
                size=pt.size,
                red=pt.red,
                green=pt.green,
                blue=pt.blue,
                zone_enabled=pt.zone_enabled,
                radius_m=pt.radius_m,
                zone_red=pt.zone_red,
                zone_green=pt.zone_green,
                zone_blue=pt.zone_blue,
                zone_opacity=pt.zone_opacity,
            )
            mx, my = CoordinateService.transform_xy(
                added_pt.longitude, added_pt.latitude,
                source_crs=added_pt.source_crs,
                target_crs=self._active_crs,
            )
            zone_poly = None
            if added_pt.zone_enabled and added_pt.radius_m > 0:
                geo_c = GeodesicService.create_geodesic_circle(
                    added_pt.longitude, added_pt.latitude, added_pt.radius_m
                )
                zone_poly = CoordinateService.transform_polygon(
                    geo_c,
                    source_crs="EPSG:4326",
                    target_crs=self._active_crs,
                )
            self.map_canvas.add_user_point(added_pt, map_x=mx, map_y=my, zone_polygon=zone_poly)
            self._add_point_to_table(added_pt)

    def _clear_all_points(self) -> None:
        """Полная очистка пользовательских точек из сервиса, карты и таблицы."""
        self._point_service.clear()
        self.map_canvas.clear_user_points()
        self.points_table.setRowCount(0)
        self._table_point_ids.clear()
        self.btn_delete_point.setEnabled(False)
        self.btn_edit_point.setEnabled(False)
        self._clear_properties_panel()

    def _reset_layers_visibility(self) -> None:
        """Сброс видимости слоев в состояние по умолчанию (все видны)."""
        for layer in self.loaded_layers:
            layer.visible = True
            chk = self.layer_checkboxes.get(layer.id)
            if chk:
                chk.blockSignals(True)
                chk.setChecked(True)
                chk.blockSignals(False)
            self.map_canvas.set_layer_visibility(layer.id, True)


