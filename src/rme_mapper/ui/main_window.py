"""Главное окно приложения GeoPoint Mapper."""
from __future__ import annotations


import logging
import os
import sys
from pathlib import Path
from typing import Any

from PySide6.QtCore import QEvent, QRect, QSize, QStringListModel, QTimer, Qt
from PySide6.QtGui import QAction, QActionGroup, QFont, QGuiApplication, QKeySequence
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMenu,
    QMenuBar,
    QSizePolicy,
    QCompleter,
    QMessageBox,
    QSplitter,
    QStatusBar,
    QStyle,
    QToolBar,
    QTabWidget,
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
from rme_mapper.services.group_service import GroupService
from rme_mapper.services.layer_service import LayerService
from rme_mapper.services.map_catalog_service import MapCatalogService
from rme_mapper.services.point_service import PointService
from rme_mapper.services.project_service import ProjectService
from rme_mapper.ui.about_dialog import AboutDialog
from rme_mapper.ui.controllers.export_controller import ExportController
from rme_mapper.ui.controllers.group_controller import GroupController
from rme_mapper.ui.controllers.import_controller import ImportController
from rme_mapper.ui.controllers.map_controller import MapController
from rme_mapper.ui.controllers.point_controller import PointController
from rme_mapper.ui.controllers.project_controller import ProjectController
from rme_mapper.ui.panels.groups_panel import GroupsPanel
from rme_mapper.ui.panels.layers_panel import LayersPanel
from rme_mapper.ui.panels.points_panel import PointsPanel
from rme_mapper.ui.panels.properties_panel import (
    PropertiesPanel,
    SYMBOL_DISPLAY_NAMES,
    get_symbol_display_name,
)
from rme_mapper.ui.custom_title_bar import CustomTitleBar, Win32FramelessHelper
from rme_mapper.ui.icon_factory import render_toolbar_icon
from rme_mapper.ui.theme_manager import get_theme_manager
from rme_mapper.ui.update_controller import UpdateController, UpdateNotificationBanner
from rme_mapper.services.update_service import should_run_auto_check

logger = logging.getLogger("rme_mapper.ui.main_window")


def sanitize_window_geometry(
    target_rect: QRect,
    screen_geometries: list[QRect] | None = None,
    primary_geometry: QRect | None = None,
) -> QRect:
    """Нормализация и валидация геометрии окна для гарантированной доступности заголовка.

    - Определяет экран с максимальным пересечением целевого прямоугольника.
    - Если пересечения нет (монитор отключен), используется primary_geometry.
    - Ограничивает ширину и высоту размерами рабочей области (availableGeometry).
    - Гарантирует, что верхняя граница окна (title bar) находится в пределах рабочей области:
      y >= avail.top() и y <= avail.bottom() - safety_margin.
    - Гарантирует горизонтальную видимость окна.
    - Корректно работает с отрицательными координатами многомониторных конфигураций.
    """
    screens = screen_geometries or []
    best_screen_rect: QRect | None = None
    max_overlap_area = 0

    for s_rect in screens:
        intersect = s_rect.intersected(target_rect)
        if not intersect.isEmpty():
            area = intersect.width() * intersect.height()
            if area > max_overlap_area:
                max_overlap_area = area
                best_screen_rect = s_rect

    # Если окно не пересекает ни один экран (отключенный монитор / мусорные координаты)
    if best_screen_rect is None or max_overlap_area <= 0:
        if primary_geometry is not None:
            best_screen_rect = primary_geometry
        elif screens:
            best_screen_rect = screens[0]
        else:
            best_screen_rect = QRect(0, 0, 1400, 850)

    avail = best_screen_rect

    # 1. Ограничение размеров рабочей областью
    w = min(max(320, target_rect.width()), avail.width())
    h = min(max(240, target_rect.height()), avail.height())

    # 2. Нормализация координаты Y (гарантия доступности строки заголовка)
    min_y = avail.top()
    max_y = avail.top() + max(0, avail.height() - min(h, 40))
    y = max(min_y, min(target_rect.y(), max_y))

    # 3. Нормализация координаты X (гарантия горизонтальной доступности)
    min_x = avail.left()
    max_x = avail.left() + max(0, avail.width() - min(w, 80))
    if w <= avail.width():
        max_x_bounded = avail.left() + avail.width() - w
        x = max(min_x, min(target_rect.x(), max_x_bounded))
    else:
        x = max(min_x, min(target_rect.x(), max_x))

    if h <= avail.height():
        max_y_bounded = avail.top() + avail.height() - h
        y = max(min_y, min(y, max_y_bounded))

    return QRect(x, y, w, h)


from rme_mapper.ui.workspace_layout import WorkspaceLayoutMixin


class MainWindow(WorkspaceLayoutMixin, QMainWindow):
    """Главное окно приложения GeoPoint Mapper."""

    DEFAULT_WIDTH = 1400
    DEFAULT_HEIGHT = 850

    def __init__(
        self,
        parent: QWidget | None = None,
        map_profile: MapProfile | None = None,
        map_path: Path | str | None = None,
        backend: MapDataBackend | None = None,
        project_path: Path | str | None = None,
        license_controller: Any | None = None,
        license_service: Any | None = None,
        license_locked: bool = False,
    ) -> None:
        super().__init__(parent)
        self._license_locked: bool = bool(license_locked)
        self._license_controller: Any | None = license_controller
        self._license_service: Any | None = license_service
        self._force_closing_unlicensed: bool = False
        self._frameless_helper = Win32FramelessHelper()
        self._apply_default_geometry()

        self._backend: MapDataBackend = backend or get_backend()
        self._settings_service = AppSettingsService()
        init_lang = self._settings_service.get_language()
        set_language(init_lang)

        # Сервисы
        self._map_catalog_service = MapCatalogService()
        self._layer_service = LayerService(backend=self._backend)
        self._group_service = GroupService()
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
            group_service=self._group_service,
        )

        self.group_controller = GroupController(
            parent=self,
            group_service=self._group_service,
            point_service=self._point_service,
            undo_manager=self.point_controller.undo_manager,
            groups_panel=self.groups_panel,
            points_panel=self.points_panel,
            map_canvas=self.map_canvas,
            point_controller=self.point_controller,
            status_bar_fn=self._show_status_message,
        )
        self.point_controller.set_group_controller(self.group_controller)

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
            is_project_active=lambda: self.project_controller.is_project_active,
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
            group_service=self._group_service,
            group_controller=self.group_controller,
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
            group_service=self._group_service,
            group_controller=self.group_controller,
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
            group_service=self._group_service,
        )

        # Резолвер названия группы для панели свойств
        self.properties_panel.set_group_name_resolver(
            lambda gid: self._group_service.get_group(gid).name if gid and self._group_service.get_group(gid) else tr("groups.ungrouped")
        )

        # Drag & Drop, сигналы курсора и счетчика точек
        self.setAcceptDrops(True)
        self.map_canvas.cursor_position_changed.connect(self._on_canvas_cursor_moved)
        self.map_canvas.cursor_left.connect(self._on_canvas_cursor_left)
        self.points_panel.count_changed.connect(self._on_points_count_changed)
        self.points_panel.count_changed.connect(lambda *_: self.group_controller.refresh_groups_ui())

        # Сигналы отмены/повтора, интерактивного добавления и выделения точек
        self.point_controller.undo_manager.add_on_state_changed(self._update_undo_redo_actions)
        self.map_canvas.add_point_mode_cancelled.connect(lambda: self.add_pt_map_action.setChecked(False))
        self.map_canvas.map_point_clicked.connect(lambda mx, my: self.add_pt_map_action.setChecked(False))
        self.add_pt_map_action.toggled.connect(lambda *_: self._update_active_mode_indicator())
        if hasattr(self, "move_pt_action"):
            self.move_pt_action.toggled.connect(lambda *_: self._update_active_mode_indicator())
        self.measure_distance_action.toggled.connect(lambda *_: self._update_active_mode_indicator())
        self.measure_area_action.toggled.connect(lambda *_: self._update_active_mode_indicator())
        self.map_canvas.measurement_cancelled.connect(lambda *_: self._update_active_mode_indicator())
        self.map_canvas.move_point_mode_cancelled.connect(lambda *_: self._update_active_mode_indicator())
        self.points_panel.selection_changed.connect(self._on_selection_changed_for_actions)

        # Сигналы измерений
        self.map_canvas.measurement_updated.connect(self._on_measurement_updated)
        self.map_canvas.measurement_finished.connect(self._on_measurement_finished)
        self.map_canvas.measurement_cancelled.connect(self._on_measurement_cancelled)
        self.map_canvas.online_tiles_progress.connect(self._on_online_tiles_progress)
        self.map_canvas.online_tiles_auth_error.connect(self._on_online_tiles_auth_error)

        # Тема оформления
        self._theme_manager = get_theme_manager()
        self.setup_workspace_actions()
        from rme_mapper.ui.raster_overlays import RasterOverlays
        self.raster_overlays_panel = RasterOverlays(self)
        self.navigation_tabs.addTab(self.raster_overlays_panel, tr("ux.rasters"))
        self.navigation_tabs.setCurrentIndex(min(2, max(0, self._read_navigation_tab())))

        self.setup_audit_features()
        self.navigation_tabs.setCurrentIndex(min(self.navigation_tabs.count()-1,max(0,self._saved_navigation_index)))

        # Восстановление сохраненного состояния интерфейса
        self.restore_ui_state()
        self._focus_map_active = False
        self._focus_saved_state = None
        self._update_check_scheduled = False
        if hasattr(self, "_finalize_toolbar_right_controls"):
            self._finalize_toolbar_right_controls()
        if hasattr(self, "_refresh_toolbar_icons"):
            self._refresh_toolbar_icons()
        if hasattr(self, "_apply_compact_toolbar_labels"):
            self._apply_compact_toolbar_labels()
        if hasattr(self, "_refresh_empty_state_recent_files"):
            self._refresh_empty_state_recent_files()
        if hasattr(self, "_setup_point_search_enhancement"):
            self._setup_point_search_enhancement()
        self.retranslate_ui()
        self._update_window_title()

        # Проверка аварийного снимка при запуске
        if not self._license_locked:
            self._check_recovery_snapshot_on_startup()

        # Загрузка проекта или карты при старте при наличии параметров
        if not self._license_locked and project_path is not None:
            self.open_project(project_path)
        elif not self._license_locked and map_profile is not None:
            self.load_map(map_profile)
        elif not self._license_locked and map_path is not None:
            self.load_map(map_path)
        elif (
            self.map_controller.active_profile is None
            and self.map_controller.map_path is None
            and not self.project_controller.is_project_active
        ):
            self._unload_map()

        if self._license_locked:
            self.set_license_locked(True)

    def _setup_ui(self) -> None:
        """Инициализация компонентов интерфейса."""
        self.title_bar = CustomTitleBar(self)
        self.setMenuWidget(self.title_bar)
        self._create_menu_bar()
        self._create_toolbar()
        self._create_central_layout()
        self._create_status_bar()

    def menuBar(self) -> QMenuBar:
        """Возвращает полосу меню, встроенную в единую верхнюю панель окна."""
        if hasattr(self, "title_bar"):
            return self.title_bar.menu_bar
        return super().menuBar()

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

        # Этап 20: Онлайн-карты
        self.online_map_menu = self.map_menu.addMenu("")
        self.online_standard_action = QAction(self)
        self.online_standard_action.triggered.connect(self.load_online_standard_map)
        self.online_map_menu.addAction(self.online_standard_action)

        self.online_satellite_action = QAction(self)
        self.online_satellite_action.triggered.connect(self.load_online_satellite_map)
        self.online_map_menu.addAction(self.online_satellite_action)

        self.online_hybrid_action = QAction(self)
        self.online_hybrid_action.triggered.connect(self.load_online_hybrid_map)
        self.online_map_menu.addAction(self.online_hybrid_action)

        self.online_map_menu.addSeparator()

        self.select_online_basemap_action = QAction(self)
        self.select_online_basemap_action.triggered.connect(self.open_online_basemap_dialog)
        self.online_map_menu.addAction(self.select_online_basemap_action)

        self.map_menu.addSeparator()

        # Этап 21: Ручная геопривязка изображений
        self.georeference_image_action = QAction(self)
        self.georeference_image_action.triggered.connect(lambda: self.open_georeference_image_dialog())
        self.map_menu.addAction(self.georeference_image_action)

        self.edit_georeferencing_action = QAction(self)
        self.edit_georeferencing_action.triggered.connect(self.edit_current_georeferencing)
        self.edit_georeferencing_action.setEnabled(False)
        self.map_menu.addAction(self.edit_georeferencing_action)

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
        # Ctrl+M already opens a map; movement is a secondary action.
        self.move_pt_action.setShortcut(QKeySequence("Ctrl+Shift+V"))
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
        self.import_points_action.triggered.connect(lambda: self.open_import_points_workflow())
        self.import_menu.addAction(self.import_points_action)
        self.export_menu = menu_bar.addMenu("")

        self.export_map_image_action = QAction(self)
        self.export_map_image_action.setShortcut(QKeySequence("Ctrl+Shift+E"))
        self.export_map_image_action.triggered.connect(lambda: self.open_export_map_workflow())
        self.export_map_image_action.setEnabled(False)
        self.export_menu.addAction(self.export_map_image_action)

        self.export_objects_action = QAction(self)
        self.export_objects_action.triggered.connect(lambda: self.open_export_objects_workflow())
        self.export_objects_action.setEnabled(False)
        self.export_menu.addAction(self.export_objects_action)

        # Меню: Инструменты
        self.tools_menu = menu_bar.addMenu("")
        self.measure_distance_action = QAction(self)
        self.measure_distance_action.setShortcut(QKeySequence("Ctrl+Shift+M"))
        self.measure_distance_action.setCheckable(True)
        self.measure_distance_action.toggled.connect(self._toggle_measure_distance)
        self.measure_distance_action.setEnabled(False)
        self.tools_menu.addAction(self.measure_distance_action)

        self.measure_area_action = QAction(self)
        self.measure_area_action.setShortcut(QKeySequence("Ctrl+Shift+G"))
        self.measure_area_action.setCheckable(True)
        self.measure_area_action.toggled.connect(self._toggle_measure_area)
        self.measure_area_action.setEnabled(False)
        self.tools_menu.addAction(self.measure_area_action)

        self.tools_menu.addSeparator()

        self.clear_measurements_action = QAction(self)
        self.clear_measurements_action.triggered.connect(self._clear_measurements)
        self.clear_measurements_action.setEnabled(False)
        self.tools_menu.addAction(self.clear_measurements_action)

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

        self.focus_map_action = QAction(self)
        self.focus_map_action.setCheckable(True)
        self.focus_map_action.setShortcut(QKeySequence("F11"))
        self.focus_map_action.toggled.connect(self.toggle_focus_map_mode)
        self.view_menu.addAction(self.focus_map_action)

        # Синхронизированные глобальные параметры карты (настройка в едином окне Настройки)
        self.point_labels_menu = QMenu(self)
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

        self.show_zones_action = QAction(self)
        self.show_zones_action.setCheckable(True)
        self.show_zones_action.setChecked(True)
        self.show_zones_action.triggered.connect(self._toggle_show_zones)

        self.view_menu.addSeparator()

        self.toggle_scale_action = QAction(self)
        self.toggle_scale_action.setCheckable(True)
        self.toggle_scale_action.setChecked(self._settings_service.get_show_scale_indicator())
        self.toggle_scale_action.toggled.connect(self._toggle_scale_indicator)

        self.toggle_grid_action = QAction(self)
        self.toggle_grid_action.setCheckable(True)
        self.toggle_grid_action.setChecked(self._settings_service.get_show_coordinate_grid())
        self.toggle_grid_action.toggled.connect(self._toggle_coordinate_grid)

        # Меню: Настройки
        self.settings_menu = menu_bar.addMenu("")

        # Языковые QAction сохранены для программной синхронизации; интерфейс переключения — в SettingsDialog
        self.language_menu = QMenu(self)
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

        self.clear_tile_cache_action = QAction(self)
        self.clear_tile_cache_action.triggered.connect(self.clear_online_tile_cache)

        self.check_updates_action = QAction(self)
        self.check_updates_action.triggered.connect(self._open_updates_in_settings)
        self.settings_menu.addAction(self.check_updates_action)
        self.settings_menu.addSeparator()

        self.help_about_action = QAction(self)
        self.help_about_action.triggered.connect(lambda: self.open_preferences(section="help_about"))
        self.settings_menu.addAction(self.help_about_action)

        self.quick_start_action = QAction(self)
        self.quick_start_action.triggered.connect(self.show_quick_start)
        self.about_action = QAction(self)
        self.about_action.triggered.connect(self.show_about_dialog)
        self.settings_menu.addAction(self.about_action)

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
            self.measure_distance_action.setIcon(style.standardIcon(QStyle.StandardPixmap.SP_FileDialogInfoView))
            self.measure_area_action.setIcon(style.standardIcon(QStyle.StandardPixmap.SP_FileDialogContentsView))
            self.export_map_image_action.setIcon(style.standardIcon(QStyle.StandardPixmap.SP_DialogSaveButton))

        # Добавление существующих действий в тулбар (без создания дубликатов)
        self.main_toolbar.addAction(self.open_map_action)
        self.main_toolbar.addAction(self.open_action)
        self.main_toolbar.addAction(self.save_action)
        self.main_toolbar.addSeparator()
        self.main_toolbar.addAction(self.undo_action)
        self.main_toolbar.addAction(self.redo_action)
        self.main_toolbar.addSeparator()
        self.main_toolbar.addAction(self.add_pt_action)
        self.main_toolbar.addAction(self.fit_map_action)
        self.main_toolbar.addSeparator()
        self.main_toolbar.addAction(self.measure_distance_action)
        self.main_toolbar.addAction(self.measure_area_action)
        self.main_toolbar.addAction(self.export_map_image_action)
        for action in (self.undo_action, self.redo_action, self.fit_map_action, self.measure_distance_action, self.measure_area_action):
            button = self.main_toolbar.widgetForAction(action)
            if button:
                button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)

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

        self.navigation_tabs = QTabWidget(self.left_panel)
        self.layers_panel = LayersPanel(self.navigation_tabs)
        self.groups_panel = GroupsPanel(self.navigation_tabs)
        self.navigation_tabs.addTab(self.layers_panel, tr("ux.layers"))
        self.navigation_tabs.addTab(self.groups_panel, tr("ux.groups"))
        left_layout.addWidget(self.navigation_tabs, stretch=1)
        self.points_panel = PointsPanel(self.left_panel)
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
        self.map_canvas.open_project_requested.connect(lambda: self.open_project())
        self.map_canvas.recent_file_requested.connect(self._on_empty_recent_clicked)
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
        self.workspace_splitter = QSplitter(Qt.Orientation.Vertical, self)
        self.workspace_splitter.setObjectName("workspaceSplitter")
        self.workspace_splitter.setChildrenCollapsible(False)
        self.workspace_splitter.addWidget(self.splitter)
        self.workspace_splitter.addWidget(self.points_panel)
        self.workspace_splitter.setStretchFactor(0, 1)
        self.workspace_splitter.setStretchFactor(1, 0)

        self.update_controller = UpdateController(self._settings_service, parent=self)
        self.update_controller.check_finished.connect(self._on_update_check_finished_main)
        self.update_banner = UpdateNotificationBanner(self.update_controller, self, self)
        if self.center_panel.layout() is not None:
            self.center_panel.layout().insertWidget(0, self.update_banner)

        self.setCentralWidget(self.workspace_splitter)

        # Ссылки обратной совместимости с существующими тестами
        self._setup_compat_references()

    def _setup_compat_references(self) -> None:
        """Создание ссылок на виджеты панелей для обратной совместимости."""
        self.layers_title_label = self.layers_panel.title_label
        self.layers_container = self.layers_panel.layers_container
        self.layers_layout = self.layers_panel.layers_layout

        self.groups_title_label = self.groups_panel.title_label
        self.groups_tree = self.groups_panel.groups_tree
        self.btn_create_group = self.groups_panel.btn_create

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
        self.map_canvas.set_active_crs(crs)
        self.restore_annotations()
        if hasattr(self, "raster_overlays_panel"):
            self.raster_overlays_panel.restore()
        self.point_controller.reproject_all_points(crs)
        if hasattr(self, "map_crs_label"):
            self.map_crs_label.setText(crs)
        if hasattr(self, "status_crs_label"):
            self.status_crs_label.setText(f"CRS: {crs}")
            self.status_crs_label.setVisible(True)
        self._update_map_dependent_actions(True)
        if hasattr(self, "points_panel"):
            self._on_points_count_changed(self.points_panel.total_count, self.points_panel.shown_count)
        if hasattr(self, "toggle_grid_action") and self.toggle_grid_action.isChecked():
            self.map_canvas.set_coordinate_grid_visible(True)
        if hasattr(self, "toggle_scale_action") and self.toggle_scale_action.isChecked():
            self.map_canvas.set_scale_indicator_visible(True)

    def _on_map_title_changed(self, title: str) -> None:
        """Слушатель изменения заголовка карты."""
        self.map_title_label.setText(title)
        if self.map_controller.active_crs and hasattr(self, "map_crs_label"):
            self.map_crs_label.setText(self.map_controller.active_crs)

        self._refresh_empty_state_recent_files()
        if hasattr(self, "_refresh_point_search_completer"):
            self._refresh_point_search_completer()
        self._update_active_mode_indicator()

    def _on_points_count_changed(self, total: int, shown: int) -> None:
        """Обновление счетчика точек в строке состояния."""
        unlocked = not getattr(self, "_license_locked", False)
        if hasattr(self, "export_objects_action"):
            self.export_objects_action.setEnabled(unlocked and total > 0)

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
        enabled = bool(enabled) and not getattr(self, "_license_locked", False)
        if hasattr(self,"measure_bar"):
            self.measure_bar.setVisible(enabled)
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
        if hasattr(self, "edit_georeferencing_action"):
            is_georef = (
                enabled
                and self.map_controller.active_profile is not None
                and getattr(self.map_controller.active_profile, "source_type", "") == "georeferenced_image"
            )
            self.edit_georeferencing_action.setEnabled(is_georef)
        if hasattr(self, "measure_distance_action"):
            self.measure_distance_action.setEnabled(enabled)
            if not enabled and self.measure_distance_action.isChecked():
                self.measure_distance_action.setChecked(False)
        if hasattr(self, "measure_area_action"):
            self.measure_area_action.setEnabled(enabled)
            if not enabled and self.measure_area_action.isChecked():
                self.measure_area_action.setChecked(False)
        if hasattr(self, "clear_measurements_action"):
            has_meas = self.map_canvas.has_measurements() if hasattr(self, "map_canvas") else False
            self.clear_measurements_action.setEnabled(enabled and has_meas)
        if not enabled and hasattr(self, "map_canvas"):
            self.map_canvas.clear_measurements()

    def _on_selection_changed_for_actions(self) -> None:
        """Обновление доступности действий меню Правка и Координаты при изменении выделения."""
        selected_ids = self.points_panel.selected_point_ids() if hasattr(self, "points_panel") else []
        has_sel = len(selected_ids) > 0
        self.sync_properties_visibility()
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
                self.undo_action.setToolTip(
                    f"{tr('tooltip.undo')}: {desc} (Ctrl+Z)" if desc else f"{tr('tooltip.undo')} (Ctrl+Z)"
                )
            else:
                self.undo_action.setText(tr("action.undo"))
                self.undo_action.setToolTip(f"{tr('tooltip.undo')} (Ctrl+Z)")
        if hasattr(self, "redo_action"):
            self.redo_action.setEnabled(can_redo)
            if can_redo:
                desc = self.point_controller.undo_manager.redo_description
                self.redo_action.setText(f"{tr('action.redo')}: {desc}" if desc else tr("action.redo"))
                self.redo_action.setToolTip(
                    f"{tr('tooltip.redo')}: {desc} (Ctrl+Y)" if desc else f"{tr('tooltip.redo')} (Ctrl+Y)"
                )
            else:
                self.redo_action.setText(tr("action.redo"))
                self.redo_action.setToolTip(f"{tr('tooltip.redo')} (Ctrl+Y)")

    def _toggle_add_point_on_map(self, checked: bool) -> None:
        """Переключение режима интерактивного создания точки кликом по карте."""
        if checked:
            if self.map_controller.active_profile is None and self.map_controller.map_path is None:
                self.add_pt_map_action.blockSignals(True)
                self.add_pt_map_action.setChecked(False)
                self.add_pt_map_action.blockSignals(False)
                QMessageBox.information(
                    self,
                    tr("dialog.no_map_title"),
                    tr("dialog.no_map_text"),
                )
                return
            if hasattr(self, "measure_distance_action") and self.measure_distance_action.isChecked():
                self.measure_distance_action.blockSignals(True)
                self.measure_distance_action.setChecked(False)
                self.measure_distance_action.blockSignals(False)
            if hasattr(self, "measure_area_action") and self.measure_area_action.isChecked():
                self.measure_area_action.blockSignals(True)
                self.measure_area_action.setChecked(False)
                self.measure_area_action.blockSignals(False)
            self.map_canvas.cancel_measurement()
            self.point_controller.start_add_point_on_map_mode()
        else:
            self.point_controller.cancel_add_point_on_map_mode()

    def _toggle_measure_distance(self, checked: bool) -> None:
        """Переключение режима измерения расстояния."""
        if checked:
            if self.map_controller.active_profile is None and self.map_controller.map_path is None:
                self.measure_distance_action.blockSignals(True)
                self.measure_distance_action.setChecked(False)
                self.measure_distance_action.blockSignals(False)
                QMessageBox.information(
                    self,
                    tr("dialog.no_map_title"),
                    tr("dialog.no_map_text"),
                )
                return
            if hasattr(self, "measure_area_action") and self.measure_area_action.isChecked():
                self.measure_area_action.blockSignals(True)
                self.measure_area_action.setChecked(False)
                self.measure_area_action.blockSignals(False)
            if hasattr(self, "add_pt_map_action") and self.add_pt_map_action.isChecked():
                self.add_pt_map_action.blockSignals(True)
                self.add_pt_map_action.setChecked(False)
                self.add_pt_map_action.blockSignals(False)
            if hasattr(self, "point_controller"):
                self.point_controller.cancel_move_point_mode()
            self.map_canvas.start_measurement("measure_distance")
        else:
            if self.map_canvas.interaction_mode == "measure_distance":
                self.map_canvas.cancel_measurement()

    def _toggle_measure_area(self, checked: bool) -> None:
        """Переключение режима измерения площади."""
        if checked:
            if self.map_controller.active_profile is None and self.map_controller.map_path is None:
                self.measure_area_action.blockSignals(True)
                self.measure_area_action.setChecked(False)
                self.measure_area_action.blockSignals(False)
                QMessageBox.information(
                    self,
                    tr("dialog.no_map_title"),
                    tr("dialog.no_map_text"),
                )
                return
            if hasattr(self, "measure_distance_action") and self.measure_distance_action.isChecked():
                self.measure_distance_action.blockSignals(True)
                self.measure_distance_action.setChecked(False)
                self.measure_distance_action.blockSignals(False)
            if hasattr(self, "add_pt_map_action") and self.add_pt_map_action.isChecked():
                self.add_pt_map_action.blockSignals(True)
                self.add_pt_map_action.setChecked(False)
                self.add_pt_map_action.blockSignals(False)
            if hasattr(self, "point_controller"):
                self.point_controller.cancel_move_point_mode()
            self.map_canvas.start_measurement("measure_area")
        else:
            if self.map_canvas.interaction_mode == "measure_area":
                self.map_canvas.cancel_measurement()

    def _clear_measurements(self) -> None:
        """Очистка всех измерений на карте."""
        self.map_canvas.clear_measurements()
        if hasattr(self, "clear_measurements_action"):
            self.clear_measurements_action.setEnabled(False)
        self._show_status_message(tr("measure.cleared"), 3000)

    def _on_measurement_updated(self, text: str) -> None:
        """Обработка обновления промежуточных результатов измерения."""
        self._show_status_message(text)
        if hasattr(self, "clear_measurements_action"):
            self.clear_measurements_action.setEnabled(self.map_canvas.has_measurements())

    def _on_measurement_finished(self, text: str) -> None:
        """Обработка завершения измерения полилинии или полигона."""
        self._show_status_message(text)
        if hasattr(self, "measure_distance_action"):
            self.measure_distance_action.setChecked(False)
        if hasattr(self, "measure_area_action"):
            self.measure_area_action.setChecked(False)
        if hasattr(self, "clear_measurements_action"):
            self.clear_measurements_action.setEnabled(self.map_canvas.has_measurements())

    def _on_measurement_cancelled(self) -> None:
        """Обработка отмены текущего режима измерения."""
        if hasattr(self, "measure_distance_action"):
            self.measure_distance_action.setChecked(False)
        if hasattr(self, "measure_area_action"):
            self.measure_area_action.setChecked(False)
        self._show_status_message(tr("measure.cancelled"), 3000)
        if hasattr(self, "clear_measurements_action"):
            self.clear_measurements_action.setEnabled(self.map_canvas.has_measurements())

    def _toggle_scale_indicator(self, checked: bool) -> None:
        """Переключение видимости экранного масштаба."""
        self._settings_service.set_show_scale_indicator(checked)
        self.map_canvas.set_scale_indicator_visible(checked)

    def _toggle_coordinate_grid(self, checked: bool) -> None:
        """Переключение видимости координатной сетки."""
        self._settings_service.set_show_coordinate_grid(checked)
        self.map_canvas.set_coordinate_grid_visible(checked)

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
        self.sync_properties_visibility()

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
        """Установка геометрии по умолчанию (1400x850) с адаптацией под экран."""
        screen = QGuiApplication.primaryScreen()
        if screen:
            avail = screen.availableGeometry()
            margin_w = 40
            margin_h = 60
            target_w = min(self.DEFAULT_WIDTH, max(640, avail.width() - margin_w))
            target_h = min(self.DEFAULT_HEIGHT, max(480, avail.height() - margin_h))
            self.resize(target_w, target_h)
            x = avail.x() + max(0, (avail.width() - target_w) // 2)
            y = avail.y() + max(0, (avail.height() - target_h) // 2)
            self.move(x, y)
        else:
            self.resize(self.DEFAULT_WIDTH, self.DEFAULT_HEIGHT)

    def restore_ui_state(self) -> None:
        """Восстановление геометрии, состояния сплиттера и видимости панелей."""
        geom = self._settings_service.get_window_geometry()
        screens = QGuiApplication.screens()
        primary = QGuiApplication.primaryScreen()
        screen_geoms = [s.availableGeometry() for s in screens] if screens else []
        primary_geom = primary.availableGeometry() if primary else (screen_geoms[0] if screen_geoms else None)

        if geom and isinstance(geom, dict) and "width" in geom and "height" in geom:
            target_rect = QRect(geom.get("x", 0), geom.get("y", 0), geom["width"], geom["height"])
            sanitized = sanitize_window_geometry(target_rect, screen_geoms, primary_geom)
            self.setGeometry(sanitized)
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

        scale_vis = self._settings_service.get_show_scale_indicator()
        if hasattr(self, "toggle_scale_action"):
            self.toggle_scale_action.setChecked(scale_vis)
        self.map_canvas.set_scale_indicator_visible(scale_vis)

        grid_vis = self._settings_service.get_show_coordinate_grid()
        if hasattr(self, "toggle_grid_action"):
            self.toggle_grid_action.setChecked(grid_vis)
        self.map_canvas.set_coordinate_grid_visible(grid_vis)

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
            self._settings_service.set_right_panel_visible(self.toggle_properties_action.isChecked())
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
        if hasattr(self, "title_bar"):
            self.title_bar.retranslate_ui()
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
        if hasattr(self, "export_objects_action"):
            self.export_objects_action.setText(tr("action.export_objects"))
            self.export_objects_action.setToolTip(tr("tooltip.export_objects"))
            self.export_objects_action.setStatusTip(tr("action.export_objects_tip"))
        if hasattr(self, "view_menu"):
            self.view_menu.setTitle(tr("menu.view"))
        if hasattr(self, "focus_map_action"):
            self.focus_map_action.setText(tr("action.focus_map"))
            self.focus_map_action.setToolTip(tr("tooltip.focus_map"))
        self.settings_menu.setTitle(tr("menu.settings"))
        if hasattr(self, "check_updates_action"):
            self.check_updates_action.setText(tr("settings.btn_check_updates"))
        if hasattr(self, "help_about_action"):
            self.help_about_action.setText(tr("settings.help_and_about"))

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

        if hasattr(self, "online_map_menu"):
            self.online_map_menu.setTitle(tr("menu.online_map"))
        if hasattr(self, "online_standard_action"):
            self.online_standard_action.setText(tr("action.online_standard"))
        if hasattr(self, "online_satellite_action"):
            self.online_satellite_action.setText(tr("action.online_satellite"))
        if hasattr(self, "online_hybrid_action"):
            self.online_hybrid_action.setText(tr("action.online_hybrid"))
        if hasattr(self, "select_online_basemap_action"):
            self.select_online_basemap_action.setText(tr("action.select_online_basemap"))
        if hasattr(self, "clear_tile_cache_action"):
            self.clear_tile_cache_action.setText(tr("action.clear_tile_cache"))
            self.clear_tile_cache_action.setStatusTip(tr("action.clear_tile_cache_tip"))
        if hasattr(self, "georeference_image_action"):
            self.georeference_image_action.setText(tr("action.georeference_image"))
        if hasattr(self, "edit_georeferencing_action"):
            self.edit_georeferencing_action.setText(tr("action.edit_georeferencing"))

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
        if hasattr(self, "quick_start_action"):
            self.quick_start_action.setText(tr("action.quick_start"))
            self.quick_start_action.setToolTip(tr("tooltip.quick_start"))
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
        if hasattr(self, "tools_menu"):
            self.tools_menu.setTitle(tr("menu.tools"))
        if hasattr(self, "measure_distance_action"):
            self.measure_distance_action.setText(tr("action.measure_distance"))
            self.measure_distance_action.setToolTip(f"{tr('tooltip.measure_distance')} (Ctrl+Shift+M)")
            self.measure_distance_action.setStatusTip(tr("action.measure_distance_tip"))
        if hasattr(self, "measure_area_action"):
            self.measure_area_action.setText(tr("action.measure_area"))
            self.measure_area_action.setToolTip(f"{tr('tooltip.measure_area')} (Ctrl+Shift+G)")
            self.measure_area_action.setStatusTip(tr("action.measure_area_tip"))
        if hasattr(self, "clear_measurements_action"):
            self.clear_measurements_action.setText(tr("action.clear_measurements"))
            self.clear_measurements_action.setToolTip(tr("tooltip.clear_measurements"))
            self.clear_measurements_action.setStatusTip(tr("action.clear_measurements_tip"))
        if hasattr(self, "toggle_scale_action"):
            self.toggle_scale_action.setText(tr("menu.scale_indicator"))
        if hasattr(self, "toggle_grid_action"):
            self.toggle_grid_action.setText(tr("menu.coordinate_grid"))

        self.retranslate_workspace()
        self.layers_panel.retranslate_ui()
        if hasattr(self, "groups_panel"):
            self.groups_panel.retranslate_ui()
        self.points_panel.retranslate_ui()
        self.properties_panel.retranslate_ui()
        self.map_canvas.retranslate_ui()
        if hasattr(self, "point_controller"):
            self.point_controller.retranslate_ui()

        if hasattr(self, "preferences_action"):
            self.preferences_action.setToolTip(f"{tr('audit.preferences')} (Ctrl+,)")
        if hasattr(self, "update_banner"):
            self.update_banner.retranslate_ui()
        if hasattr(self, "_apply_compact_toolbar_labels"):
            self._apply_compact_toolbar_labels()
        if hasattr(self, "_update_active_mode_indicator"):
            self._update_active_mode_indicator()

        self._apply_runtime_capabilities()

        # Обновление заголовка карты и строки состояния
        if self.map_controller.active_profile:
            map_name = self.map_controller.active_profile.name
            self.map_title_label.setText(f"{tr('map.title_prefix')}: {map_name}")
            crs = self.map_controller.active_crs or "OGC:CRS84"
            if hasattr(self, "map_crs_label"):
                self.map_crs_label.setText(crs)
            if hasattr(self, "status_crs_label"):
                self.status_crs_label.setText(f"CRS: {crs}")
                self.status_crs_label.setVisible(True)
            self._update_map_dependent_actions(True)
        elif self.map_controller.map_path:
            map_name = self.map_controller.map_path.stem
            self.map_title_label.setText(f"{tr('map.title_prefix')}: {map_name}")
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
        self._refresh_empty_state_recent_files()
        self._update_active_mode_indicator()

        if hasattr(self, "points_panel"):
            self._on_points_count_changed(self.points_panel.total_count, self.points_panel.shown_count)

        self._update_window_title()

    def _update_window_title(self) -> None:
        """Обновление заголовка окна в формате: <APP_NAME> — <Имя>[ *]."""
        proj_path = self.project_controller.current_project_path
        proj_name = proj_path.name if proj_path else tr("project.untitled")
        mod_suffix = " *" if self.project_controller.is_modified else ""
        full_title = f"{APP_NAME} — {proj_name}{mod_suffix}"
        self.setWindowTitle(full_title)
        if hasattr(self, "title_bar"):
            self.title_bar.set_title(full_title)

    def show_about_dialog(self) -> None:
        """Открытие диалогового окна 'О программе'."""
        dlg = AboutDialog(self)
        dlg.exec()

    def show_quick_start(self) -> None:
        """Показать короткую встроенную инструкцию для первого запуска."""
        QMessageBox.information(self, tr("quick_start.title"), tr("quick_start.text"))

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
        import pyproj

        prec = 6
        if self._settings_service and hasattr(self._settings_service, "get_integer"):
            prec = self._settings_service.get_integer("coordinates/precision", 6, 0, 10)

        try:
            is_geo = pyproj.CRS.from_user_input(crs).is_geographic
        except Exception:
            is_geo = "4326" in crs or "CRS84" in crs.upper()

        if is_geo:
            lon, lat = map_x, map_y
            self.status_coords_label.setText(f"X: {lon:.{prec}f}  Y: {lat:.{prec}f}")
        else:
            mx, my = map_x, map_y
            unit_m = tr("unit.m")
            try:
                lon, lat = CoordinateService.transform_xy(mx, my, source_crs=crs, target_crs="OGC:CRS84")
                self.status_coords_label.setText(
                    tr(
                        "status.coords_projected",
                        mx=mx,
                        my=my,
                        unit=unit_m,
                        lat=f"{lat:.{prec}f}",
                        lon=f"{lon:.{prec}f}",
                    )
                )
            except Exception:
                self.status_coords_label.setText(
                    tr("status.coords_projected_only", mx=mx, my=my, unit=unit_m)
                )
        self.status_coords_label.setVisible(True)

    def _on_canvas_cursor_left(self) -> None:
        """Скрытие координат при выходе курсора за пределы холста."""
        self.status_coords_label.setText("")
        self.status_coords_label.setVisible(False)

    def _on_map_unloaded(self) -> None:
        self.restore_annotations()
        if hasattr(self, "raster_overlays_panel"):
            self.raster_overlays_panel.clear()
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
        self._refresh_empty_state_recent_files()
        self._update_active_mode_indicator()

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
        self._refresh_empty_state_recent_files()

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
        self.open_map(p)

    def _clear_recent_maps(self) -> None:
        self._settings_service.clear_recent_maps()
        self._refresh_empty_state_recent_files()

    def dragEnterEvent(self, event: Any) -> None:
        """Обработка события входа курсора при перетаскивании файлов."""
        if event.mimeData().hasUrls():
            urls = event.mimeData().urls()
            has_supported = any(
                url.toLocalFile().lower().endswith((".gpkg", ".tif", ".tiff", ".png", ".jpg", ".jpeg", ".pgw", ".pngw", ".jgw", ".jpgw", ".jpegw", ".tfw", ".tifw", ".tiffw", ".wld", ".gpmap", ".rmeproject", ".gpx", ".kml", ".kmz", ".xlsx", ".csv", ".tsv", ".txt"))
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
        if getattr(self, "_license_locked", False):
            event.ignore()
            self._guard_license_unlocked()
            return
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

        if ext in (".gpkg", ".tif", ".tiff", ".png", ".jpg", ".jpeg", ".pgw", ".pngw", ".jgw", ".jpgw", ".jpegw", ".tfw", ".tifw", ".tiffw", ".wld"):
            event.acceptProposedAction()
            self.open_map(first_path)
        elif ext in (".gpmap", ".rmeproject"):
            event.acceptProposedAction()
            self.project_controller.open_project_workflow(first_path)
        elif ext in (".gpx", ".kml", ".kmz"):
            event.acceptProposedAction()
            self.import_field_file(first_path)
        elif ext in (".xlsx", ".csv", ".tsv", ".txt"):
            event.acceptProposedAction()
            self.import_controller.open_import_wizard(first_path)
        else:
            event.ignore()
            from PySide6.QtWidgets import QMessageBox

            QMessageBox.warning(
                self,
                tr("dialog.drop_title"),
                tr("msg.drop_unsupported", ext=ext),
            )

    def showEvent(self, event: Any) -> None:
        """Настройка безрамочного окна Windows и синхронизация иконок при показе."""
        super().showEvent(event)
        if hasattr(self, "_frameless_helper"):
            self._frameless_helper.ensure_native_frame(self)
        if hasattr(self, "title_bar"):
            self.title_bar.set_maximized(self.isMaximized())
            self.title_bar.update_theme()
        self._maybe_schedule_startup_tasks()

    def changeEvent(self, event: Any) -> None:
        """Обновление состояния кнопки развертывания и темы шапки."""
        super().changeEvent(event)
        if not hasattr(self, "title_bar"):
            return
        etype = event.type()
        if etype == QEvent.Type.WindowStateChange:
            self.title_bar.set_maximized(self.isMaximized())
        elif etype in (QEvent.Type.PaletteChange, QEvent.Type.StyleChange):
            self.title_bar.update_theme()

    def nativeEvent(self, event_type: Any, message: Any) -> tuple[bool, int]:
        """Обработка WinAPI-сообщений безрамочной шапки и границ ресайза."""
        if hasattr(self, "_frameless_helper") and hasattr(self, "title_bar"):
            res = self._frameless_helper.handle_native_event(
                self, event_type, message, self.title_bar
            )
            if res is not None:
                return res
        return False, 0

    def closeEvent(self, event: Any) -> None:
        """Обработка события закрытия окна с проверкой несохраненных изменений."""
        if getattr(self, "_license_controller", None) is not None:
            self._license_controller.stop()
        if getattr(self, "_force_closing_unlicensed", False) or self.project_controller.maybe_save_prompt(
            tr("dialog.unsaved_action_exit")
        ):
            if getattr(self, "_focus_map_active", False):
                self.toggle_focus_map_mode(False)
            self.save_ui_state()
            self.project_controller.cleanup_on_exit()
            try:
                from rme_mapper.backends.factory import BackendFactory
                BackendFactory.close_all()
            except Exception:
                pass
            event.accept()
        else:
            event.ignore()


    # -------------------------------------------------------------------------
    # Лицензионная блокировка рабочей области и управление жизненным циклом
    # -------------------------------------------------------------------------

    @property
    def license_controller(self) -> Any | None:
        return getattr(self, "_license_controller", None)

    def set_license_controller(self, ctrl: Any | None) -> None:
        self._license_controller = ctrl
        if ctrl is not None and getattr(ctrl, "service", None) is not None:
            self._license_service = ctrl.service

    @property
    def license_service(self) -> Any | None:
        return getattr(self, "_license_service", None)

    def set_license_service(self, svc: Any | None) -> None:
        self._license_service = svc

    def is_license_locked(self) -> bool:
        return bool(getattr(self, "_license_locked", False))

    def _guard_license_unlocked(self, interactive: bool = True) -> bool:
        if not getattr(self, "_license_locked", False):
            return True
        if interactive:
            from PySide6.QtWidgets import QMessageBox

            QMessageBox.warning(
                self,
                tr("license.locked_action_title"),
                tr("license.locked_action_body"),
            )
        return False

    def set_license_locked(self, locked: bool) -> None:
        """Заблокировать или разблокировать рабочие функции при потере/подтверждении лицензии."""
        self._license_locked = bool(locked)
        enabled = not self._license_locked
        self.setAcceptDrops(enabled)

        for act_name in (
            "new_action",
            "open_action",
            "open_map_action",
            "import_points_action",
            "recent_projects_menu",
            "recent_maps_menu",
        ):
            obj = getattr(self, act_name, None)
            if obj is not None:
                obj.setEnabled(enabled)

        if self._license_locked:
            for act_name in (
                "export_map_image_action",
                "export_objects_action",
                "add_pt_action",
                "add_pt_map_action",
                "delete_selected_action",
                "bulk_edit_style_action",
                "move_pt_action",
                "btn_add_point",
                "undo_action",
                "redo_action",
                "measure_distance_action",
                "measure_area_action",
            ):
                obj = getattr(self, act_name, None)
                if obj is not None:
                    obj.setEnabled(False)
            if hasattr(self, "points_panel"):
                self.points_panel.setEnabled(False)
            if hasattr(self, "groups_panel"):
                self.groups_panel.setEnabled(False)
            if hasattr(self, "properties_panel"):
                self.properties_panel.setEnabled(False)
            if hasattr(self, "map_canvas"):
                self.map_canvas.setEnabled(False)
        else:
            if hasattr(self, "points_panel"):
                self.points_panel.setEnabled(True)
            if hasattr(self, "groups_panel"):
                self.groups_panel.setEnabled(True)
            if hasattr(self, "properties_panel"):
                self.properties_panel.setEnabled(True)
            if hasattr(self, "map_canvas"):
                self.map_canvas.setEnabled(True)
            has_map = (
                self.map_controller.active_profile is not None
                or self.map_controller.map_path is not None
                or (
                    hasattr(self, "map_canvas")
                    and bool(getattr(self.map_canvas, "active_crs", ""))
                    and self.map_canvas.is_online_map_active()
                )
            )
            self._update_map_dependent_actions(has_map)
            self._update_undo_redo_actions()
            total = self.points_panel.total_count if hasattr(self, "points_panel") else 0
            self._on_points_count_changed(total, total)

    def is_project_dirty(self) -> bool:
        attr = getattr(self.project_controller, "is_modified", False)
        return bool(attr()) if callable(attr) else bool(attr)

    def save_project_before_license_lock(self) -> bool:
        """Разрешённое сохранение уже открытого несохранённого проекта при отзыве/истечении лицензии."""
        return self.save_project()

    def reset_workspace_on_license_loss(self) -> None:
        """Сбросить рабочую область после обработки несохранённого проекта при потере лицензии."""
        try:
            self.project_controller.set_modified(False)
        except Exception:
            pass
        try:
            self.map_controller.close_map_workflow(prompt=False)
        except Exception:
            pass

    def force_close_unlicensed(self) -> None:
        """Закрыть окно после отказа от повторной активации (несохранённый проект уже обработан)."""
        self._force_closing_unlicensed = True
        self.close()

    def open_import_points_workflow(self, file_path: Path | str | None = None) -> None:
        if not self._guard_license_unlocked():
            return
        self.import_controller.open_import_wizard(file_path)

    def open_export_map_workflow(self) -> None:
        if not self._guard_license_unlocked():
            return
        self.export_controller.open_export_dialog()

    def open_export_objects_workflow(self) -> None:
        if not self._guard_license_unlocked():
            return
        self.export_controller.open_export_objects_dialog()

    # -------------------------------------------------------------------------
    # Делегирование методов контроллерам для обратной совместимости
    # -------------------------------------------------------------------------

    def open_map(self, map_target: MapProfile | Path | str | None = None) -> bool:
        if not self._guard_license_unlocked():
            return False
        return self.map_controller.open_map_workflow(map_target)

    def close_map(self, prompt: bool = True) -> bool:
        return self.map_controller.close_map_workflow(prompt)

    def load_map(self, map_target: MapProfile | Path | str) -> None:
        if not self._guard_license_unlocked():
            return
        self.map_controller.load_map(map_target)

    def _unload_map(self) -> None:
        self.map_controller.unload_map()

    def _on_layer_toggled(self, layer_id: str, visible: bool) -> None:
        self.map_controller.set_layer_visibility(layer_id, visible)

    def _reset_layers_visibility(self) -> None:
        self.map_controller.reset_layers_visibility()

    def _clear_layer_checkboxes(self) -> None:
        self.layers_panel.clear_layers()

    def show_add_point_dialog(self) -> None:
        if not self._guard_license_unlocked():
            return
        self.point_controller.add_point_workflow()

    def edit_selected_point(self) -> None:
        if not self._guard_license_unlocked():
            return
        self.point_controller.edit_point_workflow()

    def delete_selected_point(self, confirm: bool = False) -> None:
        if not self._guard_license_unlocked():
            return
        self.point_controller.delete_point_workflow(confirm=confirm)

    # -------------------------------------------------------------------------
    # Этап 20 / Этап 24: Управление онлайн-картами и деградация возможностей
    # -------------------------------------------------------------------------

    def _apply_runtime_capabilities(self) -> None:
        """Применение ограничений рантайм-возможностей к элементам интерфейса (Feature Degradation)."""
        from rme_mapper.services.runtime_capabilities import RuntimeCapabilities

        if not RuntimeCapabilities.supports_online_maps():
            reason = (
                tr("runtime.online_tls_unsupported_tooltip")
                if not RuntimeCapabilities.supports_secure_tls()
                else tr("runtime.online_network_unsupported_tooltip")
            )
            if hasattr(self, "online_map_menu"):
                self.online_map_menu.setEnabled(False)
                self.online_map_menu.setToolTip(reason)
            for act in (
                getattr(self, "online_standard_action", None),
                getattr(self, "online_satellite_action", None),
                getattr(self, "online_hybrid_action", None),
                getattr(self, "select_online_basemap_action", None),
                getattr(self, "clear_tile_cache_action", None),
            ):
                if act is not None:
                    act.setEnabled(False)
                    act.setToolTip(reason)

        if not RuntimeCapabilities.supports_georeferencing():
            if hasattr(self, "georeference_image_action"):
                self.georeference_image_action.setEnabled(False)
                self.georeference_image_action.setToolTip(tr("runtime.georef_unsupported_tooltip"))

    def load_online_standard_map(self) -> None:
        """Загрузка стандартной онлайн-карты OpenStreetMap."""
        from rme_mapper.services.runtime_capabilities import RuntimeCapabilities
        if not RuntimeCapabilities.supports_online_maps():
            QMessageBox.warning(
                self,
                tr("dialog.online_map.title"),
                tr("runtime.online_tls_unsupported_warning"),
            )
            return
        from rme_mapper.models.online_provider import ProviderRegistry
        provider = ProviderRegistry.get_provider("osm_standard")
        if provider:
            self.map_controller.load_online_map(provider=provider)

    def load_online_satellite_map(self) -> None:
        """Загрузка спутниковой онлайн-карты."""
        from rme_mapper.services.runtime_capabilities import RuntimeCapabilities
        if not RuntimeCapabilities.supports_online_maps():
            QMessageBox.warning(
                self,
                tr("dialog.online_map.title"),
                tr("runtime.online_tls_unsupported_warning"),
            )
            return
        from rme_mapper.models.online_provider import ProviderRegistry
        provider = ProviderRegistry.get_provider("mapbox_satellite")
        if not provider:
            return
        effective_key = None
        if self._settings_service:
            effective_key = self._settings_service.get_provider_api_key(provider.id)
        if not effective_key:
            effective_key = provider.get_effective_api_key()

        if not effective_key:
            self.open_online_basemap_dialog(current_provider=provider)
        else:
            self.map_controller.load_online_map(provider=provider, api_key=effective_key)

    def load_online_hybrid_map(self) -> None:
        """Загрузка гибридной онлайн-карты."""
        from rme_mapper.services.runtime_capabilities import RuntimeCapabilities
        if not RuntimeCapabilities.supports_online_maps():
            QMessageBox.warning(
                self,
                tr("dialog.online_map.title"),
                tr("runtime.online_tls_unsupported_warning"),
            )
            return
        from rme_mapper.models.online_provider import ProviderRegistry
        provider = ProviderRegistry.get_provider("mapbox_hybrid")
        if not provider:
            return
        effective_key = None
        if self._settings_service:
            effective_key = self._settings_service.get_provider_api_key(provider.id)
        if not effective_key:
            effective_key = provider.get_effective_api_key()

        if not effective_key:
            self.open_online_basemap_dialog(current_provider=provider)
        else:
            self.map_controller.load_online_map(provider=provider, api_key=effective_key)

    def open_online_basemap_dialog(self, current_provider: Any = None) -> None:
        """Открытие диалога выбора онлайн-подложки."""
        from rme_mapper.services.runtime_capabilities import RuntimeCapabilities
        if not RuntimeCapabilities.supports_online_maps():
            QMessageBox.warning(
                self,
                tr("dialog.online_map.title"),
                tr("runtime.online_tls_unsupported_warning"),
            )
            return
        from rme_mapper.ui.online_basemap_dialog import OnlineBasemapDialog
        active_provider = current_provider or (
            self.map_canvas.online_tile_manager().provider
            if hasattr(self.map_canvas, "online_tile_manager")
            else None
        )
        dialog = OnlineBasemapDialog(
            parent=self,
            settings_service=self._settings_service,
            current_provider=active_provider,
        )
        if dialog.exec():
            provider = dialog.get_selected_provider()
            key = dialog.get_api_key()
            if provider:
                self.map_controller.load_online_map(provider=provider, api_key=key)

    def clear_online_tile_cache(self) -> None:
        """Очистка дискового кэша тайлов онлайн-карт."""
        from rme_mapper.services.tile_cache import TileDiskCache
        cache = TileDiskCache()
        total_size = cache.get_total_size_bytes()
        formatted = TileDiskCache.format_size(total_size)
        reply = QMessageBox.question(
            self,
            tr("action.clear_tile_cache"),
            tr("dialog.online_map.clear_cache_confirm", size=formatted),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            cache.clear_cache()
            self.statusBar().showMessage(tr("status.tile_cache_cleared", size=formatted), 4000)

    def _on_online_tiles_progress(self, pending_count: int) -> None:
        if pending_count > 0:
            self.statusBar().showMessage(tr("status.tile_loading", count=pending_count), 1500)

    def _on_online_tiles_auth_error(self, provider_name: str) -> None:
        msg = tr("dialog.online_map.auth_error_msg", name=provider_name)
        self.statusBar().showMessage(msg, 5000)

    def open_georeference_image_dialog(self, file_path: Path | str | None = None) -> None:
        """Открытие диалога геопривязки изображения по контрольным точкам (Stage 21)."""
        target_path = file_path
        if not target_path:
            last_dir = str(self._settings_service.get_last_map_directory() or Path.home())
            selected, _ = QFileDialog.getOpenFileName(
                self,
                tr("dialog.georef.title"),
                last_dir,
                tr("dialog.georef.file_filter"),
            )
            if not selected:
                return
            target_path = Path(selected)
        else:
            target_path = Path(target_path)

        from uuid import uuid4
        from rme_mapper.ui.georeference_dialog import GeoreferenceDialog
        from rme_mapper.models.map_profile import MapProfile

        try:
            dlg = GeoreferenceDialog(target_path, parent=self)
        except Exception as exc:
            QMessageBox.critical(self, tr("dialog.georef.title"), str(exc))
            return
        target_path = dlg.image_path
        if dlg.exec() == QDialog.DialogCode.Accepted:
            affine = dlg.get_affine_transform()
            cps = [p.to_dict() for p in dlg.get_control_points()]
            crs_val = dlg.get_crs()
            extent_dict = dlg.get_extent()
            profile = MapProfile(
                id=f"georef_{uuid4().hex[:8]}",
                name=target_path.stem,
                source_type="georeferenced_image",
                source_path=str(target_path.resolve()),
                base_dir=target_path.parent,
                crs=crs_val,
                boundary_layer=None,
                boundary_required=False,
                extent=extent_dict,
                affine_transform=list(affine),
                control_points=cps,
                transformation_type="affine",
                layers=[{
                    "id": "raster_base",
                    "name": "raster",
                    "source_name": "raster",
                    "display_name": target_path.stem,
                    "geometry_type": "raster",
                    "visible": True,
                    "crs": crs_val,
                }],
            )
            self.map_controller.load_georeferenced_image(profile, target_path)
            self.project_controller.set_modified(True)
            self._update_map_dependent_actions(True)

    def edit_current_georeferencing(self) -> None:
        """Редактирование геопривязки текущего активного растра (Stage 21)."""
        success = self.map_controller.edit_georeferencing(
            on_applied=lambda: self.project_controller.set_modified(True),
            undo_manager=self.point_controller.undo_manager,
        )
        if success:
            self._update_map_dependent_actions(True)



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
        if not self._guard_license_unlocked():
            return False
        return self.project_controller.new_project_workflow()

    def save_project(self) -> bool:
        return self.project_controller.save_project_workflow()

    def save_project_as(self, file_path: Path | str | None = None) -> bool:
        return self.project_controller.save_project_as_workflow(file_path)

    def open_project(self, file_path: Path | str | None = None) -> bool:
        if not self._guard_license_unlocked():
            return False
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

    @property
    def group_service(self) -> GroupService:
        return self._group_service

    # -------------------------------------------------------------------------
    # Hydrogen UI: панель инструментов, режим фокуса, недавние файлы, поиск и автообновления
    # -------------------------------------------------------------------------

    def _finalize_toolbar_right_controls(self) -> None:
        """Разместить справа индикатор режима, кнопку фокуса и шестерёнку настроек."""
        if not hasattr(self, "main_toolbar") or hasattr(self, "_toolbar_right_ready"):
            return
        self._toolbar_right_ready = True

        spacer = QWidget(self.main_toolbar)
        spacer.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.main_toolbar.addWidget(spacer)

        self.active_mode_label = QLabel("", self.main_toolbar)
        self.active_mode_label.setObjectName("activeToolPill")
        self.active_mode_label.setVisible(False)
        self._active_mode_action = self.main_toolbar.addWidget(self.active_mode_label)
        self._active_mode_action.setVisible(False)

        if hasattr(self, "focus_map_action"):
            self.main_toolbar.addAction(self.focus_map_action)
            focus_btn = self.main_toolbar.widgetForAction(self.focus_map_action)
            if focus_btn is not None:
                focus_btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)

        if hasattr(self, "preferences_action"):
            self.main_toolbar.addAction(self.preferences_action)
            gear_btn = self.main_toolbar.widgetForAction(self.preferences_action)
            if gear_btn is not None:
                gear_btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)

    def _refresh_toolbar_icons(self) -> None:
        """Обновить все иконки верхней панели в едином стиле под активную тему."""
        try:
            tm = get_theme_manager()
            pal = tm.get_palette()
            fg = pal.TEXT_PRIMARY
            accent = pal.ACCENT
        except Exception:
            fg = "#1E293B"
            accent = "#2563EB"

        mapping = (
            ("open_map_action", "open_map"),
            ("open_action", "open_project"),
            ("save_action", "save"),
            ("undo_action", "undo"),
            ("redo_action", "redo"),
            ("add_pt_action", "add_point"),
            ("fit_map_action", "fit_map"),
            ("measure_distance_action", "measure_distance"),
            ("measure_area_action", "measure_area"),
            ("export_map_image_action", "export"),
            ("focus_map_action", "focus_map"),
            ("preferences_action", "settings"),
        )
        for attr, icon_kind in mapping:
            act = getattr(self, attr, None)
            if act is not None:
                act.setIcon(render_toolbar_icon(icon_kind, fg, accent))

    def _apply_compact_toolbar_labels(self) -> None:
        """Установить лаконичные подписи кнопок тулбара без изменения текста в меню."""
        mapping = (
            ("open_map_action", "toolbar.open_map"),
            ("open_action", "toolbar.open_project"),
            ("save_action", "action.save"),
            ("add_pt_action", "toolbar.group_point"),
            ("export_map_image_action", "toolbar.group_export"),
        )
        for attr, key in mapping:
            act = getattr(self, attr, None)
            if act is not None:
                act.setIconText(tr(key))

    def _update_active_mode_indicator(self) -> None:
        """Отобразить активный режим взаимодействия с картой."""
        if not hasattr(self, "active_mode_label"):
            return
        has_map = (
            self.map_controller.active_profile is not None
            or self.map_controller.map_path is not None
            or (bool(getattr(self.map_canvas, "active_crs", "")) and self.map_canvas.is_online_map_active())
        )
        if hasattr(self, "_active_mode_action"):
            self._active_mode_action.setVisible(has_map)
        self.active_mode_label.setVisible(has_map)
        if not has_map:
            return
        if getattr(self, "add_pt_map_action", None) and self.add_pt_map_action.isChecked():
            self.active_mode_label.setText(tr("toolbar.mode_add_point"))
        elif getattr(self, "move_pt_action", None) and self.move_pt_action.isChecked():
            self.active_mode_label.setText(tr("toolbar.mode_move_point"))
        elif getattr(self, "measure_distance_action", None) and self.measure_distance_action.isChecked():
            self.active_mode_label.setText(tr("toolbar.mode_measure_distance"))
        elif getattr(self, "measure_area_action", None) and self.measure_area_action.isChecked():
            self.active_mode_label.setText(tr("toolbar.mode_measure_area"))
        else:
            self.active_mode_label.setText(tr("toolbar.mode_pan"))

    def toggle_focus_map_mode(self, enabled: bool) -> None:
        """Временно скрыть боковые панели и таблицу точек (режим 'Фокус на карте')."""
        enabled = bool(enabled)
        if enabled == getattr(self, "_focus_map_active", False):
            return

        if enabled:
            self._focus_saved_state = {
                "left_visible": self.left_panel.isVisible(),
                "right_visible": self.right_panel.isVisible(),
                "points_visible": self.points_panel.isVisible(),
                "splitter_sizes": self.splitter.sizes(),
                "workspace_sizes": self.workspace_splitter.sizes(),
            }
            self._focus_map_active = True
            self.left_panel.setVisible(False)
            self.right_panel.setVisible(False)
            self.points_panel.setVisible(False)
        else:
            saved = getattr(self, "_focus_saved_state", None) or {}
            self._focus_map_active = False
            self.left_panel.setVisible(bool(saved.get("left_visible", True)))
            self.right_panel.setVisible(bool(saved.get("right_visible", False)))
            self.points_panel.setVisible(bool(saved.get("points_visible", True)))
            sp_sizes = saved.get("splitter_sizes")
            if isinstance(sp_sizes, list) and len(sp_sizes) == 3:
                self.splitter.setSizes(sp_sizes)
            ws_sizes = saved.get("workspace_sizes")
            if isinstance(ws_sizes, list) and len(ws_sizes) == 2:
                self.workspace_splitter.setSizes(ws_sizes)
            self._focus_saved_state = None

        if hasattr(self, "focus_map_action"):
            self.focus_map_action.blockSignals(True)
            self.focus_map_action.setChecked(self._focus_map_active)
            self.focus_map_action.blockSignals(False)

    def _refresh_empty_state_recent_files(self) -> None:
        """Обновить список недавних проектов и карт на пустом экране."""
        if not hasattr(self, "map_canvas") or not hasattr(self.map_canvas, "set_recent_files"):
            return
        entries: list[dict[str, str]] = []
        seen: set[str] = set()
        for path_str in self._settings_service.get_recent_projects():
            p = Path(path_str)
            if p.exists() and path_str not in seen:
                seen.add(path_str)
                entries.append({"kind": "project", "path": path_str, "label": p.name})
        for path_str in self._settings_service.get_recent_maps():
            p = Path(path_str)
            if p.exists() and path_str not in seen:
                seen.add(path_str)
                entries.append({"kind": "map", "path": path_str, "label": p.name})
        self.map_canvas.set_recent_files(entries[:5])

    def _on_empty_recent_clicked(self, kind: str, path_str: str) -> None:
        if kind == "project":
            self._open_recent_project(path_str)
        else:
            self._open_recent_map(path_str)

    def _open_updates_in_settings(self) -> None:
        self.open_preferences(section="updates")
        if hasattr(self, "update_controller") and not self.update_controller.is_checking:
            self.update_controller.start_check(manual=True)

    def _on_update_check_finished_main(self, result: Any, manual: bool) -> None:
        """Обработка результата проверки обновлений на уровне главного окна."""
        if not manual:
            return
        if getattr(result, "status", "") == "error":
            # Если открыт SettingsDialog, он сам покажет ошибку с кнопкой 'Повторить'
            active_modal = QApplication.activeModalWidget()
            if active_modal is not None:
                return
            box = QMessageBox(self)
            box.setIcon(QMessageBox.Icon.Warning)
            box.setWindowTitle(tr("updates.retry_dialog_title"))
            box.setText(tr("updates.error_prefix", message=result.error_message))
            retry_btn = box.addButton(tr("updates.btn_retry"), QMessageBox.ButtonRole.AcceptRole)
            box.addButton(QMessageBox.StandardButton.Close)
            box.exec()
            if box.clickedButton() == retry_btn:
                self.update_controller.start_check(manual=True)

    def _maybe_schedule_startup_tasks(self) -> None:
        """Выполнить стартовые фоновые задачи один раз при первом показе окна."""
        if getattr(self, "_startup_tasks_ran", False):
            return
        self._startup_tasks_ran = True

        # Автозапуск последнего проекта (если включён и окно без загруженного проекта/карты)
        if not os.environ.get("PYTEST_CURRENT_TEST") and "--smoke-test" not in sys.argv:
            startup = self._settings_service.get_startup_behavior("empty")
            if (
                startup == "restore_last_project"
                and self.project_controller.current_project_path is None
                and self.map_controller.active_profile is None
            ):
                recent = self._settings_service.get_recent_projects()
                if recent and Path(recent[0]).exists():
                    QTimer.singleShot(150, lambda p=recent[0]: self.open_project(Path(p)))

        if os.environ.get("PYTEST_CURRENT_TEST") or os.environ.get("RME_DISABLE_AUTO_UPDATE_CHECK") or "--smoke-test" in sys.argv:
            return
        if should_run_auto_check(self._settings_service):
            QTimer.singleShot(1800, lambda: self.update_controller.start_check(manual=False))

    def sync_from_settings_dialog(self, dlg: Any) -> None:
        """Двусторонняя синхронизация всех изменений из единого SettingsDialog в MainWindow."""
        new_lang = str(dlg.language.currentData() or "ru")
        if new_lang != get_language():
            self.switch_language(new_lang)

        new_theme = str(dlg.theme.currentData() or "light")
        if hasattr(self, "set_workspace_theme"):
            self.set_workspace_theme(new_theme)

        self.set_toolbar_visible(dlg.show_toolbar.isChecked())
        self.set_left_panel_visible(dlg.show_left_panel.isChecked())
        self.set_right_panel_visible(dlg.show_right_panel.isChecked())
        self.set_statusbar_visible(dlg.show_statusbar.isChecked())
        if hasattr(self, "set_points_bottom"):
            self.set_points_bottom(dlg.points_bottom.isChecked())
        if hasattr(self, "set_auto_properties"):
            self.set_auto_properties(dlg.auto_properties.isChecked())

        if hasattr(self, "toggle_grid_action") and self.toggle_grid_action.isChecked() != dlg.show_grid.isChecked():
            self.toggle_grid_action.setChecked(dlg.show_grid.isChecked())
        if hasattr(self, "toggle_scale_action") and self.toggle_scale_action.isChecked() != dlg.show_scale.isChecked():
            self.toggle_scale_action.setChecked(dlg.show_scale.isChecked())
        if hasattr(self, "show_points_action") and self.show_points_action.isChecked() != dlg.show_points.isChecked():
            self.show_points_action.setChecked(dlg.show_points.isChecked())
            self._toggle_show_points(dlg.show_points.isChecked())
        if hasattr(self, "show_zones_action") and self.show_zones_action.isChecked() != dlg.show_zones.isChecked():
            self.show_zones_action.setChecked(dlg.show_zones.isChecked())
            self._toggle_show_zones(dlg.show_zones.isChecked())

        if hasattr(self, "_set_labels_mode"):
            self._set_labels_mode(str(dlg.labels_mode.currentData() or "selected"))
        if hasattr(self, "_set_label_content_mode"):
            self._set_label_content_mode(str(dlg.label_content.currentData() or "number_name"))

        self.apply_preferences()

    def _setup_point_search_enhancement(self) -> None:
        """Добавить автодополнение с ведущими нулями для поиска точек на карте."""
        if not hasattr(self, "navigate_edit"):
            return
        self._point_completer_model = QStringListModel(self)
        self._point_completer = QCompleter(self._point_completer_model, self)
        self._point_completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self._point_completer.setFilterMode(Qt.MatchFlag.MatchContains)
        self._point_completer.activated.connect(self._on_completer_activated)
        self.navigate_edit.setCompleter(self._point_completer)
        if hasattr(self, "points_panel"):
            self.points_panel.count_changed.connect(lambda *_: self._refresh_point_search_completer())
        self._refresh_point_search_completer()

    def _refresh_point_search_completer(self) -> None:
        if not hasattr(self, "_point_completer_model"):
            return
        items: list[str] = []
        for idx, pt in enumerate(self._point_service.get_points(), start=1):
            num_str = str(pt.object_number).strip() if pt.object_number else str(idx)
            items.append(f"{num_str} — {pt.name}")
        self._point_completer_model.setStringList(items)

    def _on_completer_activated(self, selected_text: str) -> None:
        """Выбор результата из выпадающего списка сразу выделяет точку и центрирует карту."""
        if " — " in selected_text:
            num_part, name_part = selected_text.split(" — ", 1)
            for pt in self._point_service.get_points():
                if (pt.object_number == num_part or not pt.object_number) and pt.name == name_part:
                    self._select_and_center_found_point(pt)
                    return
        self.navigate_to_input()

    def _select_and_center_found_point(self, point: Any) -> None:
        """Выделить найденную точку в таблице/на карте и центрировать вид."""
        self.points_panel.select_point_ids([point.id])
        if hasattr(self.map_canvas, "set_selected_point_ids"):
            self.map_canvas.set_selected_point_ids([point.id])
        if hasattr(self, "sync_properties_visibility"):
            self.sync_properties_visibility()
        self.map_canvas.center_on_coordinates(point.longitude, point.latitude, source_crs=point.source_crs)

    def navigate_to_input(self) -> None:
        """Поиск точки по имени/номеру (с сохранением ведущих нулей) или переход по координатам."""
        text = self.navigate_edit.text().strip()
        if not text:
            return
        has_map = (
            self.map_controller.active_profile is not None
            or self.map_controller.map_path is not None
            or (bool(getattr(self.map_canvas, "active_crs", "")) and self.map_canvas.is_online_map_active())
        )
        if not has_map or not getattr(self.map_canvas, "active_crs", ""):
            super().navigate_to_input()
            return

        query_text = text
        if " — " in query_text:
            num_part, name_part = query_text.split(" — ", 1)
            for pt in self._point_service.get_points():
                if pt.name == name_part and (pt.object_number == num_part or not pt.object_number):
                    self._select_and_center_found_point(pt)
                    return

        q_cf = query_text.casefold()
        points = self._point_service.get_points()
        # 1. Точное совпадение (сохраняя ведущие нули!)
        for idx, pt in enumerate(points, start=1):
            row_label = str(pt.object_number).strip() if pt.object_number else str(idx)
            if pt.name.casefold() == q_cf or (pt.object_number and str(pt.object_number).strip().casefold() == q_cf) or row_label.casefold() == q_cf:
                self._select_and_center_found_point(pt)
                return
        # 2. Подстрочное совпадение (только если запрос не похож на пару координат)
        matches = [
            pt for pt in points
            if q_cf in pt.name.casefold() or (pt.object_number and q_cf in str(pt.object_number).casefold())
        ]
        if matches:
            self._select_and_center_found_point(matches[0])
            if len(matches) > 1:
                self.statusBar().showMessage(tr("search.results_count", count=len(matches)), 3000)
            return

        # 3. Координатный переход (делегируем исходной логике)
        super().navigate_to_input()
