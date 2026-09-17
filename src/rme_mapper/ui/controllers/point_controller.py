"""Контроллер управления пользовательскими точками."""

from collections.abc import Callable
import logging
from typing import Any

from PySide6.QtCore import QObject
from PySide6.QtWidgets import QMenu, QMessageBox, QWidget

from rme_mapper.i18n import tr
from rme_mapper.maps.map_canvas import MapCanvas
from rme_mapper.models.map_point import MapPoint
from rme_mapper.models.map_profile import MapProfile
from rme_mapper.services.coordinate_service import CoordinateService
from rme_mapper.services.geodesic_service import GeodesicService
from rme_mapper.services.point_service import PointService
from rme_mapper.ui.panels.points_panel import PointsPanel
from rme_mapper.ui.panels.properties_panel import PropertiesPanel, get_symbol_display_name
from rme_mapper.ui.point_dialog import PointDialog

logger = logging.getLogger("rme_mapper.ui.controllers.point_controller")


class PointController(QObject):
    """Контроллер для сценариев добавления, редактирования, удаления и отображения точек."""

    def __init__(
        self,
        parent_widget: QWidget,
        point_service: PointService,
        points_panel: PointsPanel,
        properties_panel: PropertiesPanel,
        map_canvas: MapCanvas,
        get_active_crs: Callable[[], str],
        get_active_profile: Callable[[], MapProfile | None],
        get_map_path: Callable[[], Any],
        get_boundary_geometry: Callable[[], Any],
        on_modified: Callable[[], None],
        set_status_message: Callable[[str, int], None] | None = None,
    ) -> None:
        super().__init__(parent_widget)
        self._parent = parent_widget
        self._point_service = point_service
        self._points_panel = points_panel
        self._properties_panel = properties_panel
        self._map_canvas = map_canvas

        self._get_active_crs = get_active_crs
        self._get_active_profile = get_active_profile
        self._get_map_path = get_map_path
        self._get_boundary_geometry = get_boundary_geometry
        self._on_modified = on_modified
        self._set_status_message = set_status_message

        # Маппинг индекса строки таблицы на ID точки: row_index -> point_id
        self._table_point_ids: list[str] = []

        self._connect_signals()

    def _connect_signals(self) -> None:
        self._points_panel.add_clicked.connect(self.add_point_workflow)
        self._points_panel.edit_clicked.connect(self.edit_point_workflow)
        self._points_panel.delete_clicked.connect(self.delete_point_workflow)
        self._points_panel.row_double_clicked.connect(self.on_table_row_double_clicked)
        self._points_panel.selection_changed.connect(self.on_table_selection_changed)
        self._points_panel.custom_context_menu_requested.connect(self.show_context_menu)

    def retranslate_ui(self) -> None:
        """Перевод динамических данных в таблице точек (форма, радиус) и панели свойств."""
        table = self._points_panel.points_table
        for row, point_id in enumerate(self._table_point_ids):
            point = self._point_service.get_point(point_id)
            if point:
                shape_item = table.item(row, 4)
                if shape_item:
                    shape_item.setText(get_symbol_display_name(point.symbol))
                radius_item = table.item(row, 5)
                if radius_item:
                    radius_item.setText(GeodesicService.format_radius(point.radius_m, point.zone_enabled))

        row = self._points_panel.selected_row()
        if row is not None and 0 <= row < len(self._table_point_ids):
            pt = self._point_service.get_point(self._table_point_ids[row])
            if pt:
                self._properties_panel.update_properties(pt)

    @property
    def table_point_ids(self) -> list[str]:
        """Список идентификаторов точек в порядке строк таблицы."""
        return self._table_point_ids

    def _set_status(self, text: str, timeout: int = 0) -> None:
        if self._set_status_message:
            self._set_status_message(text, timeout)

    def add_point_workflow(self) -> None:
        """Сценарий создания новой пользовательской точки."""
        if self._get_active_profile() is None and self._get_map_path() is None:
            QMessageBox.information(
                self._parent,
                tr("dialog.no_map_title"),
                tr("dialog.no_map_text"),
            )
            return

        profile = self._get_active_profile()
        active_crs = self._get_active_crs()
        auto_name = f"{tr('point.default_name_prefix')} {len(self._point_service) + 1}"

        dialog = PointDialog(
            parent=self._parent,
            boundary_geometry=self._get_boundary_geometry(),
            default_name=auto_name,
            mode="CREATE",
            map_name=profile.name if profile else None,
            map_extent=profile.extent if profile else None,
            map_crs=active_crs,
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
                self._render_point_on_canvas(point)
                self.add_point_to_table(point)
                self._on_modified()
                self._set_status(tr("status.point_added", name=point.name), 3000)

    def edit_point_workflow(self) -> None:
        """Сценарий редактирования выбранной пользовательской точки."""
        row = self._points_panel.selected_row()
        if row is None or not (0 <= row < len(self._table_point_ids)):
            return

        point_id = self._table_point_ids[row]
        point = self._point_service.get_point(point_id)
        if not point:
            return

        profile = self._get_active_profile()
        active_crs = self._get_active_crs()

        dialog = PointDialog(
            parent=self._parent,
            boundary_geometry=self._get_boundary_geometry(),
            point=point,
            mode="EDIT",
            map_name=profile.name if profile else None,
            map_extent=profile.extent if profile else None,
            map_crs=active_crs,
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
                self._render_point_on_canvas(updated, is_update=True)
                self.update_point_in_table(row, updated)
                self._properties_panel.update_properties(updated)
                self._on_modified()
                self._set_status(tr("status.point_updated", name=updated.name), 3000)
                logger.info("Точка '%s' (id=%s) успешно обновлена", updated.name, updated.id)

    def delete_point_workflow(self) -> None:
        """Сценарий удаления выбранной в таблице точки."""
        row = self._points_panel.selected_row()
        if row is None or not (0 <= row < len(self._table_point_ids)):
            return

        point_id = self._table_point_ids.pop(row)
        self._point_service.remove_point(point_id)
        self._map_canvas.remove_user_point(point_id)
        self._points_panel.remove_row(row)

        self._points_panel.set_buttons_enabled(edit=False, delete=False)
        self._properties_panel.clear()
        self._on_modified()
        self._set_status(tr("status.point_deleted"), 3000)
        logger.info("Точка с ID %s успешно удалена", point_id)

    def clear_all_points(self) -> None:
        """Полная очистка всех точек из сервиса, карты, таблицы и панели свойств."""
        self._point_service.clear()
        self._map_canvas.clear_user_points()
        self._points_panel.clear_table()
        self._table_point_ids.clear()
        self._points_panel.set_buttons_enabled(edit=False, delete=False)
        self._properties_panel.clear()

    def add_point_to_table(self, point: MapPoint) -> None:
        """Добавление записи о точке в таблицу интерфейса."""
        row_num = len(self._table_point_ids) + 1
        shape_name = get_symbol_display_name(point.symbol)
        radius_str = GeodesicService.format_radius(point.radius_m, point.zone_enabled)

        self._points_panel.add_row(
            num=str(row_num),
            name=point.name,
            lat=f"{point.latitude:.6f}",
            lon=f"{point.longitude:.6f}",
            shape=shape_name,
            radius=radius_str,
        )
        self._table_point_ids.append(point.id)

    def update_point_in_table(self, row: int, point: MapPoint) -> None:
        """Обновление значений в строке таблицы."""
        shape_name = get_symbol_display_name(point.symbol)
        radius_str = GeodesicService.format_radius(point.radius_m, point.zone_enabled)

        self._points_panel.update_row(
            row=row,
            name=point.name,
            lat=f"{point.latitude:.6f}",
            lon=f"{point.longitude:.6f}",
            shape=shape_name,
            radius=radius_str,
        )

    def _render_point_on_canvas(self, point: MapPoint, is_update: bool = False) -> None:
        """Проецирование координат и отрисовка маркера/зоны на MapCanvas."""
        active_crs = self._get_active_crs()
        mx, my = CoordinateService.transform_xy(
            point.longitude, point.latitude,
            source_crs=point.source_crs,
            target_crs=active_crs,
        )
        zone_poly = None
        if point.zone_enabled and point.radius_m > 0:
            geo_c = GeodesicService.create_geodesic_circle(
                point.longitude, point.latitude, point.radius_m
            )
            zone_poly = CoordinateService.transform_polygon(
                geo_c,
                source_crs="EPSG:4326",
                target_crs=active_crs,
            )

        if is_update:
            self._map_canvas.update_user_point(point, map_x=mx, map_y=my, zone_polygon=zone_poly)
        else:
            self._map_canvas.add_user_point(point, map_x=mx, map_y=my, zone_polygon=zone_poly)

    def reproject_all_points(self, target_crs: str) -> None:
        """Пересчет экранных координат всех точек и зон под новую CRS карты."""
        for pt in self._point_service.get_points():
            mx, my = CoordinateService.transform_xy(
                pt.longitude, pt.latitude,
                source_crs=pt.source_crs,
                target_crs=target_crs,
            )
            zone_poly = None
            if pt.zone_enabled and pt.radius_m > 0:
                geo_circle = GeodesicService.create_geodesic_circle(
                    pt.longitude, pt.latitude, pt.radius_m
                )
                zone_poly = CoordinateService.transform_polygon(
                    geo_circle,
                    source_crs="EPSG:4326",
                    target_crs=target_crs,
                )
            self._map_canvas.add_user_point(pt, map_x=mx, map_y=my, zone_polygon=zone_poly)

    def on_table_row_double_clicked(self, row: int, column: int) -> None:
        """Центрирование карты на выбранной точке."""
        if 0 <= row < len(self._table_point_ids):
            point_id = self._table_point_ids[row]
            point = self._point_service.get_point(point_id)
            if point:
                active_crs = self._get_active_crs()
                mx, my = CoordinateService.transform_xy(
                    point.longitude, point.latitude,
                    source_crs=point.source_crs,
                    target_crs=active_crs,
                )
                self._map_canvas.center_on_map_coordinates(mx, my)
                self._set_status(tr("status.focus_point", name=point.name), 2000)

    def on_table_selection_changed(self) -> None:
        """Реакция на смену выбора в таблице: обновление кнопок и карточки свойств."""
        row = self._points_panel.selected_row()
        has_selection = row is not None and 0 <= row < len(self._table_point_ids)
        self._points_panel.set_buttons_enabled(edit=has_selection, delete=has_selection)

        if has_selection and row is not None:
            point_id = self._table_point_ids[row]
            point = self._point_service.get_point(point_id)
            if point:
                self._properties_panel.update_properties(point)
                return

        self._properties_panel.clear()

    def show_context_menu(self, pos: Any) -> None:
        """Отображение контекстного меню для строки таблицы."""
        table = self._points_panel.points_table
        item = table.itemAt(pos)
        if item is None:
            return

        menu = QMenu(self._parent)
        act_edit = menu.addAction(tr("action.edit_point"))
        act_center = menu.addAction(tr("action.center_on_map"))
        menu.addSeparator()
        act_delete = menu.addAction(tr("action.delete_point"))

        action = menu.exec(table.viewport().mapToGlobal(pos))
        if action == act_edit:
            self.edit_point_workflow()
        elif action == act_center:
            row = table.currentRow()
            self.on_table_row_double_clicked(row, 0)
        elif action == act_delete:
            self.delete_point_workflow()
