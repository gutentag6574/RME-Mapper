"""Главное окно приложения GeoPoint Mapper."""

import logging
from pathlib import Path
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QActionGroup, QFont, QKeySequence
from PySide6.QtWidgets import (
    QCheckBox,
    QFrame,
    QLabel,
    QMainWindow,
    QMenu,
    QSplitter,
    QStatusBar,
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
from rme_mapper.ui.panels.layers_panel import LayersPanel
from rme_mapper.ui.panels.points_panel import PointsPanel
from rme_mapper.ui.panels.properties_panel import (
    PropertiesPanel,
    SYMBOL_DISPLAY_NAMES,
    get_symbol_display_name,
)

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
            on_map_loaded=lambda crs: self.point_controller.reproject_all_points(crs),
            on_modified=lambda: self.project_controller.set_modified(True),
            is_project_active=lambda: bool(self.project_controller.current_project_path),
            set_status_message=self._show_status_message,
            set_map_title=self.map_title_label.setText,
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
        )

        self.retranslate_ui()
        self._update_window_title()

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

        # Меню: Карта
        self.map_menu = menu_bar.addMenu("")
        self.open_map_action = QAction(self)
        self.open_map_action.setShortcut(QKeySequence("Ctrl+M"))
        self.open_map_action.triggered.connect(lambda: self.open_map())
        self.map_menu.addAction(self.open_map_action)

        self.close_map_action = QAction(self)
        self.close_map_action.triggered.connect(lambda: self.close_map())
        self.map_menu.addAction(self.close_map_action)

        # Меню: Координаты
        self.coords_menu = menu_bar.addMenu("")
        self.add_pt_action = QAction(self)
        self.add_pt_action.setShortcut(QKeySequence("Ctrl+P"))
        self.add_pt_action.triggered.connect(self.show_add_point_dialog)
        self.coords_menu.addAction(self.add_pt_action)

        # Заглушки будущих меню
        self.import_menu = menu_bar.addMenu("")
        self.export_menu = menu_bar.addMenu("")
        self.settings_menu = menu_bar.addMenu("")

        # Меню: Язык (Language)
        self.language_menu = menu_bar.addMenu("")
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

    def _create_central_layout(self) -> None:
        """Создание трехпанельной компоновки: Слои/Точки | Карта | Свойства."""
        splitter = QSplitter(Qt.Orientation.Horizontal, self)

        # Левая панель: Слои и Точки
        self.left_panel = QWidget()
        self.left_panel.setObjectName("leftPanel")
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
        splitter.addWidget(self.left_panel)

        # Центральная область: Карта (MapCanvas)
        self.center_panel = QWidget()
        self.center_panel.setObjectName("centerPanel")
        center_layout = QVBoxLayout(self.center_panel)
        center_layout.setContentsMargins(8, 8, 8, 8)
        center_layout.setSpacing(6)

        self.map_title_label = QLabel(self.center_panel)
        header_font = QFont()
        header_font.setBold(True)
        header_font.setPointSize(12)
        self.map_title_label.setFont(header_font)
        center_layout.addWidget(self.map_title_label)

        self.map_canvas = MapCanvas(self.center_panel)
        self.map_placeholder = self.map_canvas
        self.btn_open_map = self.map_canvas.btn_open_map
        self.btn_open_map_center = self.map_canvas.btn_open_map
        self.map_canvas.btn_open_map.clicked.connect(lambda: self.open_map())
        center_layout.addWidget(self.map_canvas, stretch=1)
        splitter.addWidget(self.center_panel)

        # Правая панель: Свойства
        self.properties_panel = PropertiesPanel(self)
        self.right_panel = self.properties_panel
        splitter.addWidget(self.right_panel)

        splitter.setSizes([300, 800, 300])
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setStretchFactor(2, 0)
        self.setCentralWidget(splitter)

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

    def _create_status_bar(self) -> None:
        """Создание нижней строки состояния."""
        status_bar = QStatusBar(self)
        status_bar.setObjectName("statusBar")
        self.setStatusBar(status_bar)
        status_bar.showMessage(tr("status.no_map"))

    def _show_status_message(self, text: str, timeout: int = 0) -> None:
        if self.statusBar():
            self.statusBar().showMessage(text, timeout)

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
        self.map_menu.setTitle(tr("menu.map"))
        self.coords_menu.setTitle(tr("menu.coordinates"))
        self.import_menu.setTitle(tr("menu.import"))
        self.export_menu.setTitle(tr("menu.export"))
        self.settings_menu.setTitle(tr("menu.settings"))
        self.language_menu.setTitle(tr("menu.language"))
        self.help_menu.setTitle(tr("menu.help"))

        self.new_action.setText(tr("action.new_project"))
        self.open_action.setText(tr("action.open_project"))
        self.save_action.setText(tr("action.save"))
        self.save_as_action.setText(tr("action.save_as"))
        self.exit_action.setText(tr("action.exit"))

        self.open_map_action.setText(tr("action.open_map"))
        self.close_map_action.setText(tr("action.close_map"))
        self.add_pt_action.setText(tr("action.add_point"))
        self.about_action.setText(tr("action.about"))

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
            self.statusBar().showMessage(
                tr(
                    "status.map_info",
                    name=map_name,
                    crs=self.map_controller.active_crs,
                    count=len(self.map_controller.loaded_layers),
                )
            )
        elif self.map_controller.map_path:
            map_name = self.map_controller.map_path.stem
            self.map_title_label.setText(f"{tr('menu.map')}: {map_name}")
            self.statusBar().showMessage(
                tr(
                    "status.map_info",
                    name=map_name,
                    crs=self.map_controller.active_crs,
                    count=len(self.map_controller.loaded_layers),
                )
            )
        else:
            self.map_title_label.setText(tr("status.no_map"))
            self.statusBar().showMessage(tr("status.no_map"))

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

    def closeEvent(self, event: Any) -> None:
        """Обработка события закрытия окна с проверкой несохраненных изменений."""
        if self.project_controller.maybe_save_prompt(tr("dialog.unsaved_action_exit")):
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

    def delete_selected_point(self) -> None:
        self.point_controller.delete_point_workflow()

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
