"""Главное окно приложения GeoPoint Mapper."""

import logging
from pathlib import Path
from typing import Any

from PySide6.QtCore import QRect, QSize, Qt
from PySide6.QtGui import QAction, QActionGroup, QFont, QGuiApplication, QKeySequence
from PySide6.QtWidgets import (
    QCheckBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMenu,
    QMessageBox,
    QSplitter,
    QStatusBar,
    QStyle,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from rme_mapper.app_info import APP_NAME
from rme_mapper.backends import MapDataBackend, get_backend
from rme_mapper.i18n import get_language, set_language, tr
from rme_mapper.maps.map_canvas import MapCanvas
from rme_mapper.models.map_layer import MapLayer
from rme_mapper.models.map_point import MapPoint
from rme_mapper.models.map_profile import MapProfile
from rme_mapper.models.project_data import ProjectData
from rme_mapper.services.app_settings_service import AppSettingsService
from rme_mapper.services.layer_service import LayerService
from rme_mapper.services.map_catalog_service import MapCatalogService
from rme_mapper.services.point_service import PointService
from rme_mapper.services.project_service import ProjectService
from rme_mapper.ui.about_dialog import AboutDialog
from rme_mapper.ui.controllers.map_controller import MapController
from rme_mapper.ui.controllers.point_controller import PointController
from rme_mapper.ui.controllers.project_controller import ProjectController
from rme_mapper.ui.controllers.import_controller import ImportController
from rme_mapper.ui.controllers.export_controller import ExportController
from rme_mapper.ui.panels.layers_panel import LayersPanel
from rme_mapper.ui.panels.points_panel import PointsPanel
from rme_mapper.ui.panels.properties_panel import (
    PropertiesPanel,
    SYMBOL_DISPLAY_NAMES,
    get_symbol_display_name,
)
from rme_mapper.ui.theme_manager import get_theme_manager

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

        # Сервисы
        self._map_catalog_service = MapCatalogService()
        self._layer_service = LayerService(backend=self._backend)
        self._point_service = PointService()
        self._project_service = ProjectService()

        # Построение UI
        self._setup_ui()

        # Инициализация контроллеров
        self.point_controller = PointController(
            parent_widget=self,
            point_service=self._point_service,
            points_panel=self.points_panel,
            properties_panel=self.properties_panel,
            map_canvas=self.map_canvas,
            get_active_crs=lambda: self.map_controller.active_crs,
            get_active_profile=lambda: self.map_controller.active_profile,
            get_map_path=lambda: self.map_controller.map_path,
            get_boundary_geometry=lambda: self.map_controller.boundary_geometry,
            on_modified=lambda: self.project_controller.set_modified(True),
            set_modified=lambda m: self.project_controller.set_modified(m),
            set_status_message=self._show_status_message,
        )

        self.map_controller = MapController(
            parent_widget=self,
            backend=self._backend,
            map_canvas=self.map_canvas,
            layers_panel=self.layers_panel,
            points_panel=self.points_panel,
            point_service=self._point_service,
            layer_service=self._layer_service,
            map_catalog_service=self._map_catalog_service,
            on_map_loaded=self._on_map_loaded,
            on_modified=lambda: self.project_controller.set_modified(True),
            is_project_active=lambda: bool(self.project_controller.current_project_path),
            set_status_message=self._show_status_message,
            set_map_title=self._on_map_title_changed,
            settings_service=self._settings_service,
            on_map_unloaded=self._on_map_unloaded,
        )

        self.project_controller = ProjectController(
            parent_widget=self,
            project_service=self._project_service,
            point_service=self._point_service,
            map_controller=self.map_controller,
            point_controller=self.point_controller,
            map_catalog_service=self._map_catalog_service,
            on_title_changed=self._update_window_title,
            set_status_message=self._show_status_message,
            settings_service=self._settings_service,
        )

        self.import_controller = ImportController(
            parent_widget=self,
            point_controller=self.point_controller,
            point_service=self._point_service,
            project_controller=self.project_controller,
            get_active_profile=lambda: self.map_controller.active_profile,
            get_map_path=lambda: self.map_controller.map_path,
            get_boundary_geometry=lambda: self.map_controller.boundary_geometry,
            settings_service=self._settings_service,
            set_status_message=self._show_status_message,
        )

        self.export_controller = ExportController(
            parent_widget=self,
            get_active_profile=lambda: self.map_controller.active_profile,
            get_active_crs=lambda: self.map_controller.active_crs,
            get_map_path=lambda: self.map_controller.map_path,
            get_boundary_geometry=lambda: self.map_controller.boundary_geometry,
            map_canvas=self.map_canvas,
            point_service=self._point_service,
            points_panel=self.points_panel,
            layers_panel=self.layers_panel,
            settings_service=self._settings_service,
            set_status_message=self._show_status_message,
        )

        # Drag & Drop, сигналы курсора и счетчика точек
        self.setAcceptDrops(True)
        self.map_canvas.cursor_position_changed.connect(self._on_canvas_cursor_moved)
        self.map_canvas.cursor_left.connect(self._on_canvas_cursor_left)
        self.points_panel.count_changed.connect(self._on_points_count_changed)

        # Сигналы отмены/повтора, интерактивного добавления и выделения точек
        self.point_controller.undo_manager.add_on_state_changed(self._update_undo_redo_actions)
        self.map_canvas.add_point_mode_cancelled.connect(lambda: self.add_pt_map_action.setChecked(False))
        self.map_canvas.map_point_clicked.connect(lambda mx, my: self.add_pt_map_action.setChecked(False))
        self.points_panel.selection_changed.connect(self._on_selection_changed_for_actions)

        # Тема оформления
        self._theme_manager = get_theme_manager()
        self._theme_manager.apply_theme(self)

        # Восстановление сохраненного состояния интерфейса
        self.restore_ui_state()

        self.retranslate_ui()
        self._update_window_title()

        # Проверка аварийного снимка при запуске
        self._check_recovery_snapshot_on_startup()

        # Загрузка карты при старте при наличии параметров
        if map_profile is not None:
            self.load_map(map_profile)
        elif map_path is not None:
            self.load_map(map_path)
        else:
            self._unload_map()

    def _setup_ui(self) -> None:
        """Инициализация компонентов интерфейса."""
        self._create_menu_bar()
        self._create_toolbar()
        self._create_central_layout()
        self._create_status_bar()

    def _create_menu_bar(self) -> None:
        """Создание верхнего меню приложения."""
        menu_bar = self.menuBar()

        # Меню: Файл
        self.file_menu = menu_bar.addMenu("")

        self.new_action = QAction(self)
        self.new_action.setShortcut(QKeySequence.StandardKey.New)
        self.new_action.triggered.connect(self.new_project)
        self.file_menu.addAction(self.new_action)

        self.open_action = QAction(self)
        self.open_action.setShortcut(QKeySequence.StandardKey.Open)
        self.open_action.triggered.connect(self.open_project)
        self.file_menu.addAction(self.open_action)

        self.recent_projects_menu = self.file_menu.addMenu("")
        self.recent_projects_menu.aboutToShow.connect(self._update_recent_projects_menu)

        self.save_action = QAction(self)
        self.save_action.setShortcut(QKeySequence.StandardKey.Save)
        self.save_action.triggered.connect(self.save_project)
        self.file_menu.addAction(self.save_action)

        self.save_as_action = QAction(self)
        self.save_as_action.setShortcut(QKeySequence.StandardKey.SaveAs)
        self.save_as_action.triggered.connect(self.save_project_as)
        self.file_menu.addAction(self.save_as_action)

        self.file_menu.addSeparator()

        self.exit_action = QAction(self)
        self.exit_action.setShortcut(QKeySequence.StandardKey.Quit)
        self.exit_action.triggered.connect(self.close)
        self.file_menu.addAction(self.exit_action)

        # Меню: Правка
        self.edit_menu = menu_bar.addMenu("")

        self.undo_action = QAction(self)
        self.undo_action.setShortcut(QKeySequence.StandardKey.Undo)
        self.undo_action.triggered.connect(self.undo)
        self.undo_action.setEnabled(False)
        self.edit_menu.addAction(self.undo_action)

        self.redo_action = QAction(self)
        self.redo_action.setShortcut(QKeySequence("Ctrl+Y"))
        self.redo_action.triggered.connect(self.redo)
        self.redo_action.setEnabled(False)
        self.edit_menu.addAction(self.redo_action)

        self.edit_menu.addSeparator()

        self.delete_selected_action = QAction(self)
        self.delete_selected_action.setShortcut(QKeySequence.StandardKey.Delete)
        self.delete_selected_action.triggered.connect(lambda: self.point_controller.delete_point_workflow(confirm=True))
        self.delete_selected_action.setEnabled(False)
        self.edit_menu.addAction(self.delete_selected_action)

        self.bulk_edit_style_action = QAction(self)
        self.bulk_edit_style_action.triggered.connect(lambda: self.point_controller.bulk_edit_style_workflow())
        self.bulk_edit_style_action.setEnabled(False)
        self.edit_menu.addAction(self.bulk_edit_style_action)

        # Меню: Карта
        self.map_menu = menu_bar.addMenu("")
        self.open_map_action = QAction(self)
        self.open_map_action.setShortcut(QKeySequence("Ctrl+M"))
        self.open_map_action.triggered.connect(lambda: self.open_map())
        self.map_menu.addAction(self.open_map_action)

        self.recent_maps_menu = self.map_menu.addMenu("")
        self.recent_maps_menu.aboutToShow.connect(self._update_recent_maps_menu)

        self.close_map_action = QAction(self)
        self.close_map_action.triggered.connect(lambda: self.close_map())
        self.map_menu.addAction(self.close_map_action)

        self.map_menu.addSeparator()

        self.fit_map_action = QAction(self)
        self.fit_map_action.setShortcut(QKeySequence("Ctrl+0"))
        self.fit_map_action.triggered.connect(lambda: self.map_canvas.fit_to_view())
        self.map_menu.addAction(self.fit_map_action)

        # Меню: Координаты
        self.coords_menu = menu_bar.addMenu("")
        self.add_pt_action = QAction(self)
        self.add_pt_action.setShortcut(QKeySequence("Ctrl+P"))
        self.add_pt_action.triggered.connect(self.show_add_point_dialog)
        self.coords_menu.addAction(self.add_pt_action)

        self.add_pt_map_action = QAction(self)
        self.add_pt_map_action.setShortcut(QKeySequence("Ctrl+Shift+A"))
        self.add_pt_map_action.setCheckable(True)
        self.add_pt_map_action.toggled.connect(self._toggle_add_point_on_map)
        self.coords_menu.addAction(self.add_pt_map_action)

        self.move_pt_action = QAction(self)
        self.move_pt_action.setShortcut(QKeySequence("Ctrl+M"))
        self.move_pt_action.triggered.connect(lambda: self.point_controller.start_move_point_mode())
        self.move_pt_action.setEnabled(False)
        self.coords_menu.addAction(self.move_pt_action)

        self.coords_menu.addSeparator()

        self.copy_selected_coords_action = QAction(self)
        self.copy_selected_coords_action.triggered.connect(lambda: self.point_controller.copy_selected_coordinates())
        self.copy_selected_coords_action.setEnabled(False)
        self.coords_menu.addAction(self.copy_selected_coords_action)

        self.coords_menu.addSeparator()

        self.show_all_points_action = QAction(self)
        self.show_all_points_action.setShortcut(QKeySequence("Ctrl+Shift+0"))
        self.show_all_points_action.triggered.connect(lambda: self.point_controller.show_all_points())
        self.show_all_points_action.setEnabled(False)
        self.coords_menu.addAction(self.show_all_points_action)

        self.zoom_to_selected_action = QAction(self)
        self.zoom_to_selected_action.setShortcut(QKeySequence("Ctrl+Shift+Z"))
        self.zoom_to_selected_action.triggered.connect(lambda: self.point_controller.zoom_to_selected())
        self.zoom_to_selected_action.setEnabled(False)
        self.coords_menu.addAction(self.zoom_to_selected_action)

        # Меню: Импорт / Экспорт
        self.import_menu = menu_bar.addMenu("")
        self.import_points_action = QAction(self)
        self.import_points_action.triggered.connect(lambda: self.import_controller.open_import_wizard())
        self.import_menu.addAction(self.import_points_action)
        self.export_menu = menu_bar.addMenu("")

        self.export_map_image_action = QAction(self)
        self.export_map_image_action.setShortcut(QKeySequence("Ctrl+Shift+E"))
        self.export_map_image_action.triggered.connect(lambda: self.export_controller.open_export_dialog())
        self.export_map_image_action.setEnabled(False)
        self.export_menu.addAction(self.export_map_image_action)

        # Меню: Вид
        self.view_menu = menu_bar.addMenu("")

        self.toggle_toolbar_action = QAction(self)
        self.toggle_toolbar_action.setCheckable(True)
        self.toggle_toolbar_action.setChecked(True)
        self.toggle_toolbar_action.triggered.connect(self.set_toolbar_visible)
        self.view_menu.addAction(self.toggle_toolbar_action)

        self.toggle_layers_points_action = QAction(self)
        self.toggle_layers_points_action.setCheckable(True)
        self.toggle_layers_points_action.setChecked(True)
        self.toggle_layers_points_action.triggered.connect(self.set_left_panel_visible)
        self.view_menu.addAction(self.toggle_layers_points_action)

        self.toggle_properties_action = QAction(self)
        self.toggle_properties_action.setCheckable(True)
        self.toggle_properties_action.setChecked(True)
        self.toggle_properties_action.triggered.connect(self.set_right_panel_visible)
        self.view_menu.addAction(self.toggle_properties_action)

        self.toggle_statusbar_action = QAction(self)
        self.toggle_statusbar_action.setCheckable(True)
        self.toggle_statusbar_action.setChecked(True)
        self.toggle_statusbar_action.triggered.connect(self.set_statusbar_visible)
        self.view_menu.addAction(self.toggle_statusbar_action)

        self.view_menu.addSeparator()

        # Подменю: Подписи точек
        self.point_labels_menu = self.view_menu.addMenu("")
        self.labels_group = QActionGroup(self)
        self.labels_group.setExclusive(True)

        self.labels_hidden_action = QAction(self)
        self.labels_hidden_action.setCheckable(True)
        self.labels_hidden_action.triggered.connect(lambda: self._set_labels_mode("hidden"))
        self.labels_group.addAction(self.labels_hidden_action)
        self.point_labels_menu.addAction(self.labels_hidden_action)

        self.labels_selected_action = QAction(self)
        self.labels_selected_action.setCheckable(True)
        self.labels_selected_action.triggered.connect(lambda: self._set_labels_mode("selected"))
        self.labels_group.addAction(self.labels_selected_action)
        self.point_labels_menu.addAction(self.labels_selected_action)

        self.labels_all_action = QAction(self)
        self.labels_all_action.setCheckable(True)
        self.labels_all_action.triggered.connect(lambda: self._set_labels_mode("all"))
        self.labels_group.addAction(self.labels_all_action)
        self.point_labels_menu.addAction(self.labels_all_action)

        self.point_labels_menu.addSeparator()

        self.labels_content_menu = self.point_labels_menu.addMenu("")
        self.label_content_group = QActionGroup(self)
        self.label_content_group.setExclusive(True)

        self.label_content_name_action = QAction(self)
        self.label_content_name_action.setCheckable(True)
        self.label_content_name_action.triggered.connect(lambda: self._set_label_content_mode("name"))
        self.label_content_group.addAction(self.label_content_name_action)
        self.labels_content_menu.addAction(self.label_content_name_action)

        self.label_content_number_action = QAction(self)
        self.label_content_number_action.setCheckable(True)
        self.label_content_number_action.triggered.connect(lambda: self._set_label_content_mode("number"))
        self.label_content_group.addAction(self.label_content_number_action)
        self.labels_content_menu.addAction(self.label_content_number_action)

        self.label_content_both_action = QAction(self)
        self.label_content_both_action.setCheckable(True)
        self.label_content_both_action.triggered.connect(lambda: self._set_label_content_mode("number_name"))
        self.label_content_group.addAction(self.label_content_both_action)
        self.labels_content_menu.addAction(self.label_content_both_action)

        self.view_menu.addSeparator()

        self.show_points_action = QAction(self)
        self.show_points_action.setCheckable(True)
        self.show_points_action.setChecked(True)
        self.show_points_action.triggered.connect(self._toggle_show_points)
        self.view_menu.addAction(self.show_points_action)

        self.show_zones_action = QAction(self)
        self.show_zones_action.setCheckable(True)
        self.show_zones_action.setChecked(True)
        self.show_zones_action.triggered.connect(self._toggle_show_zones)
        self.view_menu.addAction(self.show_zones_action)

        self.view_menu.addSeparator()
        self.view_menu.addAction(self.show_all_points_action)
        self.view_menu.addAction(self.zoom_to_selected_action)

        # Меню: Настройки
        self.settings_menu = menu_bar.addMenu("")

        # Подменю: Язык (Language) внутри меню Настройки
        self.language_menu = self.settings_menu.addMenu("")
        self.lang_group = QActionGroup(self)
        self.lang_group.setExclusive(True)

        self.lang_ru_action = QAction("Русский (RU)", self)
        self.lang_ru_action.setCheckable(True)
        self.lang_ru_action.triggered.connect(lambda: self.switch_language("ru"))
        self.lang_group.addAction(self.lang_ru_action)
        self.language_menu.addAction(self.lang_ru_action)

        self.lang_en_action = QAction("English (EN)", self)
        self.lang_en_action.setCheckable(True)
        self.lang_en_action.triggered.connect(lambda: self.switch_language("en"))
        self.lang_group.addAction(self.lang_en_action)
        self.language_menu.addAction(self.lang_en_action)

        current_lang = get_language()
        if current_lang == "en":
            self.lang_en_action.setChecked(True)
        else:
            self.lang_ru_action.setChecked(True)

        # Меню: Справка
        self.help_menu = menu_bar.addMenu("")
        self.about_action = QAction(self)
        self.about_action.triggered.connect(self.show_about_dialog)
        self.help_menu.addAction(self.about_action)

    def _create_toolbar(self) -> None:
        """Создание компактной верхней панели инструментов."""
        self.main_toolbar = self.addToolBar("MainToolBar")
        self.main_toolbar.setObjectName("mainToolBar")
        self.main_toolbar.setMovable(False)
        self.main_toolbar.setIconSize(QSize(18, 18))
        self.main_toolbar.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)

        # Системные иконки для действий панели инструментов
        style = self.style()
        if style:
            self.open_map_action.setIcon(style.standardIcon(QStyle.StandardPixmap.SP_DirOpenIcon))
            self.open_action.setIcon(style.standardIcon(QStyle.StandardPixmap.SP_DialogOpenButton))
            self.save_action.setIcon(style.standardIcon(QStyle.StandardPixmap.SP_DialogSaveButton))
            self.undo_action.setIcon(style.standardIcon(QStyle.StandardPixmap.SP_ArrowBack))
            self.redo_action.setIcon(style.standardIcon(QStyle.StandardPixmap.SP_ArrowForward))
            self.add_pt_action.setIcon(style.standardIcon(QStyle.StandardPixmap.SP_FileDialogNewFolder))
            self.add_pt_map_action.setIcon(style.standardIcon(QStyle.StandardPixmap.SP_FileDialogDetailedView))
            self.move_pt_action.setIcon(style.standardIcon(QStyle.StandardPixmap.SP_ArrowRight))
            self.fit_map_action.setIcon(style.standardIcon(QStyle.StandardPixmap.SP_TitleBarMaxButton))

        # Добавление существующих действий в тулбар (без создания дубликатов)
        self.main_toolbar.addAction(self.open_map_action)
        self.main_toolbar.addAction(self.open_action)
        self.main_toolbar.addAction(self.save_action)
        self.main_toolbar.addSeparator()
        self.main_toolbar.addAction(self.undo_action)
        self.main_toolbar.addAction(self.redo_action)
        self.main_toolbar.addSeparator()
        self.main_toolbar.addAction(self.add_pt_action)
        self.main_toolbar.addAction(self.add_pt_map_action)
        self.main_toolbar.addAction(self.move_pt_action)
        self.main_toolbar.addAction(self.fit_map_action)

    def _create_central_layout(self) -> None:
        """Создание трехпанельной компоновки: Слои/Точки | Карта | Свойства на базе QSplitter."""
        self.splitter = QSplitter(Qt.Orientation.Horizontal, self)
        self.splitter.setObjectName("mainSplitter")
        self.splitter.setChildrenCollapsible(False)

        # Левая панель: Слои и Точки
        self.left_panel = QWidget()
        self.left_panel.setObjectName("leftPanel")
        self.left_panel.setMinimumWidth(240)
        left_layout = QVBoxLayout(self.left_panel)
        left_layout.setContentsMargins(8, 8, 8, 8)
        left_layout.setSpacing(10)

        self.layers_panel = LayersPanel(self.left_panel)
        left_layout.addWidget(self.layers_panel)

        separator = QFrame()
        separator.setFrameShape(QFrame.Shape.HLine)
        separator.setFrameShadow(QFrame.Shadow.Sunken)
        left_layout.addWidget(separator)

        self.points_panel = PointsPanel(self.left_panel)
        left_layout.addWidget(self.points_panel, stretch=1)
        self.splitter.addWidget(self.left_panel)

        # Центральная область: Карта (MapCanvas)
        self.center_panel = QWidget()
        self.center_panel.setObjectName("centerPanel")
        self.center_panel.setMinimumWidth(300)
        center_layout = QVBoxLayout(self.center_panel)
        center_layout.setContentsMargins(8, 8, 8, 8)
        center_layout.setSpacing(4)

        # Шапка над картой: Название карты + CRS справа
        map_header_layout = QHBoxLayout()
        map_header_layout.setContentsMargins(0, 0, 0, 0)
        map_header_layout.setSpacing(8)

        self.map_title_label = QLabel(self.center_panel)
        header_font = QFont()
        header_font.setBold(True)
        header_font.setPointSize(12)
        self.map_title_label.setFont(header_font)
        map_header_layout.addWidget(self.map_title_label)
        map_header_layout.addStretch()

        self.map_crs_label = QLabel(self.center_panel)
        crs_font = QFont()
        crs_font.setPointSize(10)
        self.map_crs_label.setFont(crs_font)
        self.map_crs_label.setStyleSheet("color: #6B7280;")
        map_header_layout.addWidget(self.map_crs_label)

        center_layout.addLayout(map_header_layout)

        self.map_canvas = MapCanvas(self.center_panel)
        self.map_placeholder = self.map_canvas
        self.btn_open_map = self.map_canvas.btn_open_map
        self.btn_open_map_center = self.map_canvas.btn_open_map
        self.map_canvas.btn_open_map.clicked.connect(lambda: self.open_map())
        center_layout.addWidget(self.map_canvas, stretch=1)
        self.splitter.addWidget(self.center_panel)

        # Правая панель: Свойства
        self.properties_panel = PropertiesPanel(self)
        self.properties_panel.setMinimumWidth(260)
        self.right_panel = self.properties_panel
        self.splitter.addWidget(self.right_panel)

        self.splitter.setSizes([310, 780, 310])
        self.splitter.setStretchFactor(0, 0)
        self.splitter.setStretchFactor(1, 1)
        self.splitter.setStretchFactor(2, 0)
        self.setCentralWidget(self.splitter)

        # Ссылки обратной совместимости с существующими тестами
        self._setup_compat_references()

    def _setup_compat_references(self) -> None:
        """Создание ссылок на виджеты панелей для обратной совместимости."""
        self.layers_title_label = self.layers_panel.title_label
        self.layers_container = self.layers_panel.layers_container
        self.layers_layout = self.layers_panel.layers_layout

        self.points_title_label = self.points_panel.title_label
        self.points_table = self.points_panel.points_table
        self.points_placeholder = self.points_table
        self.btn_add_point = self.points_panel.btn_add
        self.btn_edit_point = self.points_panel.btn_edit
        self.btn_delete_point = self.points_panel.btn_delete

        self.properties_title_label = self.properties_panel.title_label
        self.properties_placeholder = self.properties_panel.placeholder
        self.prop_empty_label = self.properties_panel.prop_empty_label
        self.prop_container = self.properties_panel.prop_container
        self.sec_coords_lbl = self.properties_panel.sec_coords_lbl
        self.sec_marker_lbl = self.properties_panel.sec_marker_lbl
        self.sec_zone_lbl = self.properties_panel.sec_zone_lbl
        self.prop_name_lbl = self.properties_panel.prop_name_lbl
        self.prop_name_val = self.properties_panel.prop_name_val
        self.prop_lat_lbl = self.properties_panel.prop_lat_lbl
        self.prop_lat_val = self.properties_panel.prop_lat_val
        self.prop_lon_lbl = self.properties_panel.prop_lon_lbl
        self.prop_lon_val = self.properties_panel.prop_lon_val
        self.prop_shape_lbl = self.properties_panel.prop_shape_lbl
        self.prop_shape_val = self.properties_panel.prop_shape_val
        self.prop_size_lbl = self.properties_panel.prop_size_lbl
        self.prop_size_val = self.properties_panel.prop_size_val
        self.prop_color_lbl = self.properties_panel.prop_color_lbl
        self.prop_color_val = self.properties_panel.prop_color_val
        self.prop_color_swatch = self.properties_panel.prop_color_swatch
        self.prop_zone_lbl = self.properties_panel.prop_zone_lbl
        self.prop_zone_val = self.properties_panel.prop_zone_val
        self.prop_zone_radius_lbl = self.properties_panel.prop_zone_radius_lbl
        self.prop_zone_radius_val = self.properties_panel.prop_zone_radius_val
        self.prop_zone_color_lbl = self.properties_panel.prop_zone_color_lbl
        self.prop_zone_color_val = self.properties_panel.prop_zone_color_val
        self.prop_zone_color_swatch = self.properties_panel.prop_zone_color_swatch
        self.prop_zone_opacity_lbl = self.properties_panel.prop_zone_opacity_lbl
        self.prop_zone_opacity_val = self.properties_panel.prop_zone_opacity_val
        self.btn_fit = self.map_canvas.btn_fit

    def _create_status_bar(self) -> None:
        """Создание нижней строки состояния."""
        status_bar = QStatusBar(self)
        status_bar.setObjectName("statusBar")
        self.setStatusBar(status_bar)

        self.status_crs_label = QLabel(self)
        self.status_crs_label.setObjectName("statusCrsLabel")
        status_bar.addPermanentWidget(self.status_crs_label)
        self.status_crs_label.setVisible(False)

        self.status_points_label = QLabel(self)
        self.status_points_label.setObjectName("statusPointsLabel")
        status_bar.addPermanentWidget(self.status_points_label)
        self.status_points_label.setVisible(False)

        self.status_coords_label = QLabel(self)
        self.status_coords_label.setObjectName("statusCoordsLabel")
        status_bar.addPermanentWidget(self.status_coords_label)
        self.status_coords_label.setVisible(False)

        status_bar.showMessage(tr("status.no_map"))

    def _show_status_message(self, text: str, timeout: int = 0) -> None:
        if self.statusBar():
            self.statusBar().showMessage(text, timeout)

    def _on_map_loaded(self, crs: str) -> None:
        """Слушатель успешной загрузки карты контроллером."""
        self.point_controller.reproject_all_points(crs)
        if hasattr(self, "map_crs_label"):
            self.map_crs_label.setText(crs)
        if hasattr(self, "status_crs_label"):
            self.status_crs_label.setText(f"CRS: {crs}")
            self.status_crs_label.setVisible(True)
        self._update_map_dependent_actions(True)
        if hasattr(self, "points_panel"):
            self._on_points_count_changed(self.points_panel.total_count, self.points_panel.shown_count)

    def _on_map_title_changed(self, title: str) -> None:
        """Слушатель изменения заголовка карты."""
        self.map_title_label.setText(title)
        if self.map_controller.active_crs and hasattr(self, "map_crs_label"):
            self.map_crs_label.setText(self.map_controller.active_crs)

    def _on_points_count_changed(self, total: int, shown: int) -> None:
        """Обновление счетчика точек в строке состояния."""
        if self.map_controller.active_profile is None and self.map_controller.map_path is None:
            if hasattr(self, "status_points_label"):
                self.status_points_label.setVisible(False)
            if hasattr(self, "show_all_points_action"):
                self.show_all_points_action.setEnabled(False)
            return

        has_map = True
        if hasattr(self, "show_all_points_action"):
            self.show_all_points_action.setEnabled(has_map and total > 0)

        query = self.points_panel.search_input.text().strip() if hasattr(self, "points_panel") else ""
        if hasattr(self, "status_points_label"):
            if query:
                self.status_points_label.setText(tr("status.points_filtered", shown=shown, total=total))
            else:
                self.status_points_label.setText(tr("status.points_count", count=total))
            self.status_points_label.setVisible(True)

    def _update_map_dependent_actions(self, enabled: bool) -> None:
        """Включение/выключение действий, зависящих от наличия активной карты."""
        if hasattr(self, "add_pt_action"):
            self.add_pt_action.setEnabled(enabled)
        if hasattr(self, "add_pt_map_action"):
            self.add_pt_map_action.setEnabled(enabled)
            if not enabled and self.add_pt_map_action.isChecked():
                self.add_pt_map_action.setChecked(False)
        if hasattr(self, "move_pt_action"):
            self.move_pt_action.setEnabled(enabled)
        if hasattr(self, "fit_map_action"):
            self.fit_map_action.setEnabled(enabled)
        if hasattr(self, "close_map_action"):
            self.close_map_action.setEnabled(enabled)
        if hasattr(self, "btn_add_point"):
            self.btn_add_point.setEnabled(enabled)
        if hasattr(self, "export_map_image_action"):
            self.export_map_image_action.setEnabled(enabled)
        if hasattr(self, "map_canvas") and hasattr(self.map_canvas, "btn_fit"):
            self.map_canvas.btn_fit.setEnabled(enabled)
        if hasattr(self, "show_all_points_action"):
            has_pts = self.points_panel.total_count > 0 if hasattr(self, "points_panel") else False
            self.show_all_points_action.setEnabled(enabled and has_pts)
        if hasattr(self, "zoom_to_selected_action"):
            has_sel = len(self.points_panel.selected_point_ids()) > 0 if hasattr(self, "points_panel") else False
            self.zoom_to_selected_action.setEnabled(enabled and has_sel)

    def _on_selection_changed_for_actions(self) -> None:
        """Обновление доступности действий меню Правка и Координаты при изменении выделения."""
        selected_ids = self.points_panel.selected_point_ids() if hasattr(self, "points_panel") else []
        has_sel = len(selected_ids) > 0
        has_multi = len(selected_ids) > 1
        has_map = self.map_controller.active_profile is not None or self.map_controller.map_path is not None

        if hasattr(self, "delete_selected_action"):
            self.delete_selected_action.setEnabled(has_sel)
        if hasattr(self, "bulk_edit_style_action"):
            self.bulk_edit_style_action.setEnabled(has_multi)
        if hasattr(self, "copy_selected_coords_action"):
            self.copy_selected_coords_action.setEnabled(has_sel)
        if hasattr(self, "zoom_to_selected_action"):
            self.zoom_to_selected_action.setEnabled(has_sel and has_map)

    def undo(self) -> bool:
        """Отмена последнего действия через PointController."""
        return self.point_controller.undo()

    def redo(self) -> bool:
        """Повтор отмененного действия через PointController."""
        return self.point_controller.redo()

    def _update_undo_redo_actions(self) -> None:
        """Синхронизация состояния и текста действий Undo/Redo."""
        can_undo = self.point_controller.undo_manager.can_undo
        can_redo = self.point_controller.undo_manager.can_redo
        if hasattr(self, "undo_action"):
            self.undo_action.setEnabled(can_undo)
            if can_undo:
                desc = self.point_controller.undo_manager.undo_description
                self.undo_action.setText(f"{tr('action.undo')}: {desc}" if desc else tr("action.undo"))
                self.undo_action.setToolTip(f"{tr('tooltip.undo')}: {desc}" if desc else tr("tooltip.undo"))
            else:
                self.undo_action.setText(tr("action.undo"))
                self.undo_action.setToolTip(tr("tooltip.undo"))
        if hasattr(self, "redo_action"):
            self.redo_action.setEnabled(can_redo)
            if can_redo:
                desc = self.point_controller.undo_manager.redo_description
                self.redo_action.setText(f"{tr('action.redo')}: {desc}" if desc else tr("action.redo"))
                self.redo_action.setToolTip(f"{tr('tooltip.redo')}: {desc}" if desc else tr("tooltip.redo"))
            else:
                self.redo_action.setText(tr("action.redo"))
                self.redo_action.setToolTip(tr("tooltip.redo"))

    def _toggle_add_point_on_map(self, checked: bool) -> None:
        """Переключение режима интерактивного создания точки кликом по карте."""
        if checked:
            if self.map_controller.active_profile is None and self.map_controller.map_path is None:
                self.add_pt_map_action.setChecked(False)
                QMessageBox.information(
                    self,
                    tr("dialog.no_map_title"),
                    tr("dialog.no_map_text"),
                )
                return
            self.point_controller.start_add_point_on_map_mode()
        else:
            self.point_controller.cancel_add_point_on_map_mode()

    def _set_labels_mode(self, mode: str) -> None:
        """Переключение режима отображения подписей точек с проверкой порога производительности."""
        if mode == "all":
            total = len(self.point_controller.table_point_ids)
            if total > 5000:
                reply = QMessageBox.question(
                    self,
                    tr("dialog.labels_limit_title"),
                    tr("dialog.labels_limit_text"),
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.No,
                )
                if reply != QMessageBox.StandardButton.Yes:
                    prev = self._settings_service.get_point_labels_mode()
                    self._update_labels_action_checked(prev)
                    return

        self._settings_service.set_point_labels_mode(mode)
        self.map_canvas.set_labels_mode(mode)
        self._update_labels_action_checked(mode)

    def _update_labels_action_checked(self, mode: str) -> None:
        """Синхронизация радио-кнопок меню подписей точек."""
        if mode == "hidden" and hasattr(self, "labels_hidden_action"):
            self.labels_hidden_action.setChecked(True)
        elif mode == "selected" and hasattr(self, "labels_selected_action"):
            self.labels_selected_action.setChecked(True)
        elif mode == "all" and hasattr(self, "labels_all_action"):
            self.labels_all_action.setChecked(True)

    def _set_label_content_mode(self, mode: str) -> None:
        """Переключение режима содержимого подписей ('name', 'number', 'number_name')."""
        self._settings_service.set_point_label_content(mode)
        self.map_canvas.set_label_content_mode(mode)
        self._update_label_content_action_checked(mode)

    def _update_label_content_action_checked(self, mode: str) -> None:
        """Синхронизация радио-кнопок меню содержимого подписей."""
        if mode == "name" and hasattr(self, "label_content_name_action"):
            self.label_content_name_action.setChecked(True)
        elif mode == "number" and hasattr(self, "label_content_number_action"):
            self.label_content_number_action.setChecked(True)
        elif mode == "number_name" and hasattr(self, "label_content_both_action"):
            self.label_content_both_action.setChecked(True)

    def _toggle_show_points(self, checked: bool) -> None:
        """Глобальное переключение видимости маркеров точек."""
        self._settings_service.set_show_points_visible(checked)
        self.map_canvas.set_all_points_visible(checked)

    def _toggle_show_zones(self, checked: bool) -> None:
        """Глобальное переключение видимости геодезических зон."""
        self._settings_service.set_show_zones_visible(checked)
        self.map_canvas.set_all_zones_visible(checked)

    def set_left_panel_visible(self, visible: bool) -> None:
        """Переключение видимости левой панели (Слои и Точки)."""
        self.left_panel.setVisible(visible)
        if hasattr(self, "toggle_layers_points_action"):
            self.toggle_layers_points_action.setChecked(visible)
        self._settings_service.set_left_panel_visible(visible)

    def set_right_panel_visible(self, visible: bool) -> None:
        """Переключение видимости правой панели (Свойства)."""
        self.right_panel.setVisible(visible)
        if hasattr(self, "toggle_properties_action"):
            self.toggle_properties_action.setChecked(visible)
        self._settings_service.set_right_panel_visible(visible)

    def set_toolbar_visible(self, visible: bool) -> None:
        """Переключение видимости панели инструментов."""
        if hasattr(self, "main_toolbar"):
            self.main_toolbar.setVisible(visible)
        if hasattr(self, "toggle_toolbar_action"):
            self.toggle_toolbar_action.setChecked(visible)
        self._settings_service.set_toolbar_visible(visible)

    def set_statusbar_visible(self, visible: bool) -> None:
        """Переключение видимости строки состояния."""
        if self.statusBar():
            self.statusBar().setVisible(visible)
        if hasattr(self, "toggle_statusbar_action"):
            self.toggle_statusbar_action.setChecked(visible)
        self._settings_service.set_statusbar_visible(visible)

    def _apply_default_geometry(self) -> None:
        """Установка геометрии по умолчанию (1400x850) с центрированием на экране."""
        self.resize(self.DEFAULT_WIDTH, self.DEFAULT_HEIGHT)
        screen = QGuiApplication.primaryScreen()
        if screen:
            avail = screen.availableGeometry()
            x = avail.x() + max(0, (avail.width() - self.DEFAULT_WIDTH) // 2)
            y = avail.y() + max(0, (avail.height() - self.DEFAULT_HEIGHT) // 2)
            self.move(x, y)

    def restore_ui_state(self) -> None:
        """Восстановление геометрии, состояния сплиттера и видимости панелей."""
        geom = self._settings_service.get_window_geometry()
        if geom:
            target_rect = QRect(geom["x"], geom["y"], geom["width"], geom["height"])
            valid_screen = False
            for screen in QGuiApplication.screens():
                if screen.availableGeometry().intersects(target_rect):
                    valid_screen = True
                    break
            if valid_screen:
                self.setGeometry(target_rect)
            else:
                self._apply_default_geometry()
        else:
            self._apply_default_geometry()

        if self._settings_service.get_window_maximized():
            self.showMaximized()

        saved_sizes = self._settings_service.get_splitter_sizes()
        if saved_sizes and len(saved_sizes) == 3:
            self.splitter.setSizes(saved_sizes)
        else:
            self.splitter.setSizes([310, 780, 310])

        self.set_left_panel_visible(self._settings_service.get_left_panel_visible())
        self.set_right_panel_visible(self._settings_service.get_right_panel_visible())
        self.set_toolbar_visible(self._settings_service.get_toolbar_visible())
        self.set_statusbar_visible(self._settings_service.get_statusbar_visible())

        # Настройки подписей точек и глобальной видимости
        labels_mode = self._settings_service.get_point_labels_mode()
        self._update_labels_action_checked(labels_mode)
        self.map_canvas.set_labels_mode(labels_mode)

        content_mode = self._settings_service.get_point_label_content()
        self._update_label_content_action_checked(content_mode)
        self.map_canvas.set_label_content_mode(content_mode)

        show_pts = self._settings_service.get_show_points_visible()
        if hasattr(self, "show_points_action"):
            self.show_points_action.setChecked(show_pts)
        self.map_canvas.set_all_points_visible(show_pts)

        show_zn = self._settings_service.get_show_zones_visible()
        if hasattr(self, "show_zones_action"):
            self.show_zones_action.setChecked(show_zn)
        self.map_canvas.set_all_zones_visible(show_zn)

    def save_ui_state(self, force: bool = False) -> None:
        """Сохранение геометрии, состояния сплиттера и видимости панелей."""
        is_max = self.isMaximized()
        self._settings_service.set_window_maximized(is_max)
        if (self.isVisible() or force) and not is_max:
            self._settings_service.set_window_geometry(
                self.x(), self.y(), self.width(), self.height()
            )
        if hasattr(self, "splitter"):
            self._settings_service.set_splitter_sizes(self.splitter.sizes())
        if hasattr(self, "left_panel"):
            self._settings_service.set_left_panel_visible(self.left_panel.isVisible())
        if hasattr(self, "right_panel"):
            self._settings_service.set_right_panel_visible(self.right_panel.isVisible())
        if hasattr(self, "main_toolbar"):
            self._settings_service.set_toolbar_visible(self.main_toolbar.isVisible())
        if self.statusBar():
            self._settings_service.set_statusbar_visible(self.statusBar().isVisible())

    def switch_language(self, lang_code: str) -> None:
        """Переключение языка интерфейса и сохранение настройки."""
        set_language(lang_code)
        self._settings_service.set_language(lang_code)
        self.retranslate_ui()
        if lang_code == "ru":
            self.lang_ru_action.setChecked(True)
        else:
            self.lang_en_action.setChecked(True)

    def retranslate_ui(self) -> None:
        """Динамическое обновление всех локализованных строк интерфейса."""
        self.file_menu.setTitle(tr("menu.file"))
        if hasattr(self, "edit_menu"):
            self.edit_menu.setTitle(tr("menu.edit"))
        self.map_menu.setTitle(tr("menu.map"))
        self.coords_menu.setTitle(tr("menu.coordinates"))
        self.import_menu.setTitle(tr("menu.import"))
        if hasattr(self, "import_points_action"):
            self.import_points_action.setText(tr("action.import_points"))
            self.import_points_action.setStatusTip(tr("action.import_points_tip"))
        self.export_menu.setTitle(tr("menu.export"))
        if hasattr(self, "export_map_image_action"):
            self.export_map_image_action.setText(tr("action.export_map_image"))
            self.export_map_image_action.setToolTip(tr("tooltip.export_map_image"))
            self.export_map_image_action.setStatusTip(tr("action.export_map_image_tip"))
        if hasattr(self, "view_menu"):
            self.view_menu.setTitle(tr("menu.view"))
        self.settings_menu.setTitle(tr("menu.settings"))
        self.language_menu.setTitle(tr("menu.language"))
        self.help_menu.setTitle(tr("menu.help"))

        self.new_action.setText(tr("action.new_project"))
        self.open_action.setText(tr("action.open_project"))
        self.open_action.setToolTip(tr("tooltip.open_project"))
        if hasattr(self, "recent_projects_menu"):
            self.recent_projects_menu.setTitle(tr("menu.recent_projects"))
        self.save_action.setText(tr("action.save"))
        self.save_action.setToolTip(tr("tooltip.save_project"))
        self.save_as_action.setText(tr("action.save_as"))
        self.exit_action.setText(tr("action.exit"))

        # Меню Правка
        self._update_undo_redo_actions()
        if hasattr(self, "delete_selected_action"):
            self.delete_selected_action.setText(tr("action.delete_selected"))
        if hasattr(self, "bulk_edit_style_action"):
            self.bulk_edit_style_action.setText(tr("action.bulk_edit_style"))

        self.open_map_action.setText(tr("action.open_map"))
        self.open_map_action.setToolTip(tr("tooltip.open_map"))
        if hasattr(self, "recent_maps_menu"):
            self.recent_maps_menu.setTitle(tr("menu.recent_maps"))
        self.close_map_action.setText(tr("action.close_map"))
        if hasattr(self, "fit_map_action"):
            self.fit_map_action.setText(tr("action.fit_map"))
            self.fit_map_action.setToolTip(tr("tooltip.fit_map"))
        self.add_pt_action.setText(tr("action.add_point"))
        self.add_pt_action.setToolTip(tr("tooltip.add_point"))
        if hasattr(self, "add_pt_map_action"):
            self.add_pt_map_action.setText(tr("action.add_point_on_map"))
            self.add_pt_map_action.setToolTip(tr("tooltip.add_point_on_map"))
        if hasattr(self, "move_pt_action"):
            self.move_pt_action.setText(tr("action.move_point"))
            self.move_pt_action.setToolTip(tr("tooltip.move_point"))
        if hasattr(self, "copy_selected_coords_action"):
            self.copy_selected_coords_action.setText(tr("action.copy_selected_coords"))
        if hasattr(self, "show_all_points_action"):
            self.show_all_points_action.setText(tr("action.show_all_points"))
            self.show_all_points_action.setToolTip(tr("tooltip.show_all_points"))
        if hasattr(self, "zoom_to_selected_action"):
            self.zoom_to_selected_action.setText(tr("action.zoom_to_selected"))
            self.zoom_to_selected_action.setToolTip(tr("tooltip.zoom_to_selected"))
        self.about_action.setText(tr("action.about"))

        if hasattr(self, "toggle_toolbar_action"):
            self.toggle_toolbar_action.setText(tr("action.view_toolbar"))
        if hasattr(self, "toggle_layers_points_action"):
            self.toggle_layers_points_action.setText(tr("action.view_layers_points"))
        if hasattr(self, "toggle_properties_action"):
            self.toggle_properties_action.setText(tr("action.view_properties"))
        if hasattr(self, "toggle_statusbar_action"):
            self.toggle_statusbar_action.setText(tr("action.view_statusbar"))

        if hasattr(self, "point_labels_menu"):
            self.point_labels_menu.setTitle(tr("menu.point_labels"))
        if hasattr(self, "labels_hidden_action"):
            self.labels_hidden_action.setText(tr("action.labels_hidden"))
        if hasattr(self, "labels_selected_action"):
            self.labels_selected_action.setText(tr("action.labels_selected"))
        if hasattr(self, "labels_all_action"):
            self.labels_all_action.setText(tr("action.labels_all"))
        if hasattr(self, "labels_content_menu"):
            self.labels_content_menu.setTitle(tr("menu.point_labels_content"))
        if hasattr(self, "label_content_name_action"):
            self.label_content_name_action.setText(tr("label_content.name"))
        if hasattr(self, "label_content_number_action"):
            self.label_content_number_action.setText(tr("label_content.number"))
        if hasattr(self, "label_content_both_action"):
            self.label_content_both_action.setText(tr("label_content.number_name"))
        if hasattr(self, "show_points_action"):
            self.show_points_action.setText(tr("action.show_points"))
        if hasattr(self, "show_zones_action"):
            self.show_zones_action.setText(tr("action.show_zones"))

        self.layers_panel.retranslate_ui()
        self.points_panel.retranslate_ui()
        self.properties_panel.retranslate_ui()
        self.map_canvas.retranslate_ui()
        if hasattr(self, "point_controller"):
            self.point_controller.retranslate_ui()

        # Обновление заголовка карты и строки состояния
        if self.map_controller.active_profile:
            map_name = self.map_controller.active_profile.name
            self.map_title_label.setText(f"{tr('menu.map')}: {map_name}")
            crs = self.map_controller.active_crs or "OGC:CRS84"
            if hasattr(self, "map_crs_label"):
                self.map_crs_label.setText(crs)
            if hasattr(self, "status_crs_label"):
                self.status_crs_label.setText(f"CRS: {crs}")
                self.status_crs_label.setVisible(True)
            self._update_map_dependent_actions(True)
        elif self.map_controller.map_path:
            map_name = self.map_controller.map_path.stem
            self.map_title_label.setText(f"{tr('menu.map')}: {map_name}")
            crs = self.map_controller.active_crs or "OGC:CRS84"
            if hasattr(self, "map_crs_label"):
                self.map_crs_label.setText(crs)
            if hasattr(self, "status_crs_label"):
                self.status_crs_label.setText(f"CRS: {crs}")
                self.status_crs_label.setVisible(True)
            self._update_map_dependent_actions(True)
        else:
            self.map_title_label.setText(tr("status.no_map"))
            if hasattr(self, "map_crs_label"):
                self.map_crs_label.setText("")
            if hasattr(self, "status_crs_label"):
                self.status_crs_label.setVisible(False)
            if hasattr(self, "status_points_label"):
                self.status_points_label.setVisible(False)
            self.statusBar().showMessage(tr("status.no_map"))
            self._update_map_dependent_actions(False)

        if hasattr(self, "points_panel"):
            self._on_points_count_changed(self.points_panel.total_count, self.points_panel.shown_count)

        self._update_window_title()

        self._update_window_title()

    def _update_window_title(self) -> None:
        """Обновление заголовка окна в формате: <APP_NAME> — <Имя>[ *]."""
        proj_path = self.project_controller.current_project_path
        proj_name = proj_path.name if proj_path else tr("project.untitled")
        mod_suffix = " *" if self.project_controller.is_modified else ""
        self.setWindowTitle(f"{APP_NAME} — {proj_name}{mod_suffix}")

    def show_about_dialog(self) -> None:
        """Открытие диалогового окна 'О программе'."""
        dlg = AboutDialog(self)
        dlg.exec()

    def _check_recovery_snapshot_on_startup(self) -> None:
        """Проверка наличия аварийного снимка предыдущей сессии при запуске."""
        if not self._project_service.has_recovery_snapshot():
            return
        from PySide6.QtWidgets import QMessageBox

        try:
            self._project_service.load_recovery_snapshot()
            is_valid = True
        except Exception:
            is_valid = False

        if is_valid:
            reply = QMessageBox.question(
                self,
                tr("dialog.recovery_title"),
                tr("dialog.recovery_text"),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.Yes,
            )
            if reply == QMessageBox.StandardButton.Yes:
                self.project_controller.restore_recovery_snapshot()
            else:
                self._project_service.clear_recovery_snapshot()
        else:
            reply = QMessageBox.question(
                self,
                tr("dialog.recovery_corrupt_title"),
                tr("dialog.recovery_corrupt_text"),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.Yes,
            )
            if reply == QMessageBox.StandardButton.Yes:
                self._project_service.clear_recovery_snapshot()

    def _on_canvas_cursor_moved(self, map_x: float, map_y: float) -> None:
        """Отображение координат курсора в строке состояния при наличии активной карты."""
        if self.map_controller.active_profile is None and self.map_controller.map_path is None:
            self.status_coords_label.setText("")
            self.status_coords_label.setVisible(False)
            return

        crs = self.map_controller.active_crs or "OGC:CRS84"
        from rme_mapper.services.coordinate_service import CoordinateService

        is_geo = "4326" in crs or "CRS84" in crs.upper()

        if is_geo:
            lon, lat = map_x, map_y
            self.status_coords_label.setText(f"X: {lon:.6f}  Y: {lat:.6f}")
        else:
            mx, my = map_x, map_y
            try:
                lon, lat = CoordinateService.transform_xy(mx, my, source_crs=crs, target_crs="OGC:CRS84")
                self.status_coords_label.setText(f"X: {mx:.2f} м  Y: {my:.2f} м  ({lat:.6f}, {lon:.6f})")
            except Exception:
                self.status_coords_label.setText(f"X: {mx:.2f} м  Y: {my:.2f} м")
        self.status_coords_label.setVisible(True)

    def _on_canvas_cursor_left(self) -> None:
        """Скрытие координат при выходе курсора за пределы холста."""
        self.status_coords_label.setText("")
        self.status_coords_label.setVisible(False)

    def _on_map_unloaded(self) -> None:
        """Сброс и скрытие виджета координат и счетчиков при выгрузке карты."""
        self.status_coords_label.setText("")
        self.status_coords_label.setVisible(False)
        if hasattr(self, "status_crs_label"):
            self.status_crs_label.setText("")
            self.status_crs_label.setVisible(False)
        if hasattr(self, "status_points_label"):
            self.status_points_label.setText("")
            self.status_points_label.setVisible(False)
        if hasattr(self, "map_crs_label"):
            self.map_crs_label.setText("")
        self._update_map_dependent_actions(False)

    def _update_recent_projects_menu(self) -> None:
        """Динамическое заполнение подменю 'Недавние проекты'."""
        self.recent_projects_menu.clear()
        items = self._settings_service.get_recent_projects()
        if not items:
            act = self.recent_projects_menu.addAction(tr("menu.no_recent"))
            act.setEnabled(False)
            return

        for path_str in items:
            p = Path(path_str)
            act = self.recent_projects_menu.addAction(p.name)
            act.setToolTip(path_str)
            act.triggered.connect(lambda checked=False, pth=path_str: self._open_recent_project(pth))

        self.recent_projects_menu.addSeparator()
        clear_act = self.recent_projects_menu.addAction(tr("menu.clear_recent"))
        clear_act.triggered.connect(self._clear_recent_projects)

    def _open_recent_project(self, path_str: str) -> None:
        p = Path(path_str)
        if not p.exists():
            from PySide6.QtWidgets import QMessageBox

            QMessageBox.warning(self, tr("dialog.error_title"), tr("msg.file_no_longer_exists"))
            self._settings_service.remove_recent_project(path_str)
            return
        self.open_project(p)

    def _clear_recent_projects(self) -> None:
        self._settings_service.clear_recent_projects()

    def _update_recent_maps_menu(self) -> None:
        """Динамическое заполнение подменю 'Недавние карты'."""
        self.recent_maps_menu.clear()
        items = self._settings_service.get_recent_maps()
        if not items:
            act = self.recent_maps_menu.addAction(tr("menu.no_recent"))
            act.setEnabled(False)
            return

        for path_str in items:
            p = Path(path_str)
            act = self.recent_maps_menu.addAction(p.name)
            act.setToolTip(path_str)
            act.triggered.connect(lambda checked=False, pth=path_str: self._open_recent_map(pth))

        self.recent_maps_menu.addSeparator()
        clear_act = self.recent_maps_menu.addAction(tr("menu.clear_recent"))
        clear_act.triggered.connect(self._clear_recent_maps)

    def _open_recent_map(self, path_str: str) -> None:
        p = Path(path_str)
        if not p.exists():
            from PySide6.QtWidgets import QMessageBox

            QMessageBox.warning(self, tr("dialog.error_title"), tr("msg.file_no_longer_exists"))
            self._settings_service.remove_recent_map(path_str)
            return
        self.load_map(p)

    def _clear_recent_maps(self) -> None:
        self._settings_service.clear_recent_maps()

    def dragEnterEvent(self, event: Any) -> None:
        """Обработка события входа курсора при перетаскивании файлов."""
        if event.mimeData().hasUrls():
            urls = event.mimeData().urls()
            has_supported = any(
                url.toLocalFile().lower().endswith((".gpkg", ".tif", ".tiff", ".gpmap", ".rmeproject", ".xlsx", ".csv", ".txt"))
                for url in urls
            )
            if has_supported:
                event.acceptProposedAction()
                return
        event.ignore()

    def dragMoveEvent(self, event: Any) -> None:
        """Перемещение объекта над окном при перетаскивании."""
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event: Any) -> None:
        """Обработка сброса перетащенных файлов."""
        if not event.mimeData().hasUrls():
            event.ignore()
            return

        urls = event.mimeData().urls()
        local_paths = [Path(u.toLocalFile()) for u in urls if u.toLocalFile()]
        if not local_paths:
            event.ignore()
            return

        if len(local_paths) > 1:
            from PySide6.QtWidgets import QMessageBox

            QMessageBox.warning(
                self,
                tr("dialog.drop_title"),
                tr("msg.drop_multiple", path=str(local_paths[0])),
            )

        first_path = local_paths[0]
        ext = first_path.suffix.lower()

        if ext in (".gpkg", ".tif", ".tiff"):
            event.acceptProposedAction()
            self.map_controller.load_map(first_path)
        elif ext in (".gpmap", ".rmeproject"):
            event.acceptProposedAction()
            self.project_controller.open_project_workflow(first_path)
        elif ext in (".xlsx", ".csv", ".txt"):
            event.acceptProposedAction()
            self.import_controller.open_import_dialog(first_path)
        else:
            event.ignore()
            from PySide6.QtWidgets import QMessageBox

            QMessageBox.warning(
                self,
                tr("dialog.drop_title"),
                tr("msg.drop_unsupported", ext=ext),
            )

    def closeEvent(self, event: Any) -> None:
        """Обработка события закрытия окна с проверкой несохраненных изменений."""
        if self.project_controller.maybe_save_prompt(tr("dialog.unsaved_action_exit")):
            self.save_ui_state()
            self.project_controller.cleanup_on_exit()
            event.accept()
        else:
            event.ignore()


    # -------------------------------------------------------------------------
    # Делегирование методов контроллерам для обратной совместимости
    # -------------------------------------------------------------------------

    def open_map(self, map_target: MapProfile | Path | str | None = None) -> bool:
        return self.map_controller.open_map_workflow(map_target)

    def close_map(self, prompt: bool = True) -> bool:
        return self.map_controller.close_map_workflow(prompt)

    def load_map(self, map_target: MapProfile | Path | str) -> None:
        self.map_controller.load_map(map_target)

    def _unload_map(self) -> None:
        self.map_controller.unload_map()

    def _on_layer_toggled(self, layer_id: str, visible: bool) -> None:
        self.map_controller.set_layer_visibility(layer_id, visible)

    def _reset_layers_visibility(self) -> None:
        self.map_controller.reset_layers_visibility()

    def _clear_layer_checkboxes(self) -> None:
        self.layers_panel.clear_layers()

    def _add_layer_checkbox(self, layer: MapLayer) -> None:
        pass

    def show_add_point_dialog(self) -> None:
        self.point_controller.add_point_workflow()

    def edit_selected_point(self) -> None:
        self.point_controller.edit_point_workflow()

    def delete_selected_point(self, confirm: bool = False) -> None:
        self.point_controller.delete_point_workflow(confirm=confirm)


    def _add_point_to_table(self, point: MapPoint) -> None:
        self.point_controller.add_point_to_table(point)

    def _update_point_in_table(self, row: int, point: MapPoint) -> None:
        self.point_controller.update_point_in_table(row, point)

    def _clear_all_points(self) -> None:
        self.point_controller.clear_all_points()

    def _reproject_all_points(self) -> None:
        self.point_controller.reproject_all_points(self.map_controller.active_crs)

    def _on_table_row_double_clicked(self, row: int, column: int) -> None:
        self.point_controller.on_table_row_double_clicked(row, column)

    def _on_table_selection_changed(self) -> None:
        self.point_controller.on_table_selection_changed()

    def _show_table_context_menu(self, pos: Any) -> None:
        self.point_controller.show_context_menu(pos)

    def _update_properties_panel(self, point: MapPoint) -> None:
        self.properties_panel.update_properties(point)

    def _clear_properties_panel(self) -> None:
        self.properties_panel.clear()

    def new_project(self) -> bool:
        return self.project_controller.new_project_workflow()

    def save_project(self) -> bool:
        return self.project_controller.save_project_workflow()

    def save_project_as(self, file_path: Path | str | None = None) -> bool:
        return self.project_controller.save_project_as_workflow(file_path)

    def open_project(self, file_path: Path | str | None = None) -> bool:
        return self.project_controller.open_project_workflow(file_path)

    def _maybe_save_prompt(self, action_name: str | None = None) -> bool:
        return self.project_controller.maybe_save_prompt(action_name)

    def _apply_project_data(self, project: ProjectData) -> None:
        self.project_controller.apply_project_data(project)

    def _set_modified(self, modified: bool = True) -> None:
        self.project_controller.set_modified(modified)

    # -------------------------------------------------------------------------
    # Свойства состояния (State Ownership & Compatibility Properties)
    # -------------------------------------------------------------------------

    @property
    def is_modified(self) -> bool:
        return self.project_controller.is_modified

    @property
    def current_project_path(self) -> Path | None:
        return self.project_controller.current_project_path

    @property
    def _current_project_path(self) -> Path | None:
        return self.project_controller.current_project_path

    @_current_project_path.setter
    def _current_project_path(self, path: Path | None) -> None:
        self.project_controller.current_project_path = path

    @property
    def _is_modified(self) -> bool:
        return self.project_controller.is_modified

    @_is_modified.setter
    def _is_modified(self, modified: bool) -> None:
        self.project_controller.is_modified = modified

    @property
    def _active_profile(self) -> MapProfile | None:
        return self.map_controller.active_profile

    @_active_profile.setter
    def _active_profile(self, profile: MapProfile | None) -> None:
        self.map_controller.active_profile = profile

    @property
    def _map_path(self) -> Path | None:
        return self.map_controller.map_path

    @_map_path.setter
    def _map_path(self, path: Path | None) -> None:
        self.map_controller.map_path = path

    @property
    def _active_crs(self) -> str:
        return self.map_controller.active_crs

    @_active_crs.setter
    def _active_crs(self, crs: str) -> None:
        self.map_controller.active_crs = crs

    @property
    def _boundary_geometry(self) -> Any:
        return self.map_controller.boundary_geometry

    @_boundary_geometry.setter
    def _boundary_geometry(self, geom: Any) -> None:
        self.map_controller.boundary_geometry = geom

    @property
    def loaded_layers(self) -> list[MapLayer]:
        return self.map_controller.loaded_layers

    @loaded_layers.setter
    def loaded_layers(self, layers: list[MapLayer]) -> None:
        self.map_controller.loaded_layers = layers

    @property
    def layer_checkboxes(self) -> dict[str, QCheckBox]:
        return self.layers_panel.layer_checkboxes

    @property
    def _table_point_ids(self) -> list[str]:
        return self.point_controller.table_point_ids
