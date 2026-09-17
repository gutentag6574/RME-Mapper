"""Контроллер экспорта карты в растровое изображение."""

from collections.abc import Callable
import logging
from pathlib import Path
from typing import Any

from PySide6.QtCore import QObject
from PySide6.QtGui import QPainterPath, QPen, QBrush
from PySide6.QtWidgets import QGraphicsPathItem, QMessageBox, QWidget

from rme_mapper.exporters.image_export_service import ImageExportService
from rme_mapper.i18n import tr
from rme_mapper.maps.map_canvas import MapCanvas
from rme_mapper.models.map_profile import MapProfile
from rme_mapper.services.app_settings_service import AppSettingsService
from rme_mapper.services.point_service import PointService
from rme_mapper.ui.export_image_dialog import ExportImageDialog
from rme_mapper.ui.panels.layers_panel import LayersPanel
from rme_mapper.ui.panels.points_panel import PointsPanel

logger = logging.getLogger("rme_mapper.ui.controllers.export")


class ExportController(QObject):
    """Контроллер взаимодействия пользователя с экспортом карты в растровые форматы."""

    def __init__(
        self,
        parent_widget: QWidget,
        get_active_profile: Callable[[], MapProfile | None],
        get_active_crs: Callable[[], str],
        get_map_path: Callable[[], Path | None],
        get_boundary_geometry: Callable[[], Any],
        map_canvas: MapCanvas,
        point_service: PointService,
        points_panel: PointsPanel,
        layers_panel: LayersPanel,
        settings_service: AppSettingsService | None = None,
        set_status_message: Callable[[str, int], None] | None = None,
    ) -> None:
        super().__init__(parent_widget)
        self._parent = parent_widget
        self._get_active_profile = get_active_profile
        self._get_active_crs = get_active_crs
        self._get_map_path = get_map_path
        self._get_boundary_geometry = get_boundary_geometry
        self._map_canvas = map_canvas
        self._point_service = point_service
        self._points_panel = points_panel
        self._layers_panel = layers_panel
        self._settings_service = settings_service or AppSettingsService()
        self._set_status_message = set_status_message

    def _set_status(self, text: str, timeout: int = 0) -> None:
        if self._set_status_message:
            self._set_status_message(text, timeout)

    def has_active_map(self) -> bool:
        """Проверка наличия активной карты в приложении."""
        return self._get_active_profile() is not None or self._get_map_path() is not None

    def get_current_view_extent(self) -> tuple[float, float, float, float] | None:
        """Расчет географического охвата текущего вида холста без изменения зума."""
        if hasattr(self._map_canvas, "viewport") and self._map_canvas.viewport():
            vp_rect = self._map_canvas.viewport().rect()
            scene_poly = self._map_canvas.mapToScene(vp_rect)
            scene_rect = scene_poly.boundingRect()
            if scene_rect.isValid() and not scene_rect.isEmpty():
                # В QGraphicsScene: scene_x = map_x, scene_y = -map_y
                min_x = scene_rect.left()
                max_x = scene_rect.right()
                min_y = -scene_rect.bottom()
                max_y = -scene_rect.top()
                if max_x > min_x and max_y > min_y:
                    return (min_x, min_y, max_x, max_y)
        return None

    def get_full_map_extent(self) -> tuple[float, float, float, float] | None:
        """Получение охвата всей карты из профиля или границы."""
        profile = self._get_active_profile()
        if profile and profile.extent:
            try:
                ext = profile.extent
                return (float(ext["xmin"]), float(ext["ymin"]), float(ext["xmax"]), float(ext["ymax"]))
            except (KeyError, TypeError, ValueError):
                pass

        boundary = self._get_boundary_geometry()
        if boundary is not None and hasattr(boundary, "bounds"):
            b = boundary.bounds
            if len(b) == 4 and b[2] > b[0] and b[3] > b[1]:
                return (float(b[0]), float(b[1]), float(b[2]), float(b[3]))

        if hasattr(self._map_canvas, "_boundary_bounds") and self._map_canvas._boundary_bounds:
            bb = self._map_canvas._boundary_bounds
            if bb.isValid() and not bb.isEmpty():
                return (bb.left(), -bb.bottom(), bb.right(), -bb.top())

        return None

    def collect_layer_render_data(self) -> list[tuple[str, QPainterPath, QPen, QBrush, float, bool]]:
        """Сбор данных отрисовки слоев (path, pen, brush, z_value, visible) из MapCanvas."""
        render_data: list[tuple[str, QPainterPath, QPen, QBrush, float, bool]] = []
        if hasattr(self._map_canvas, "_layer_items"):
            for lid, item in self._map_canvas._layer_items.items():
                if isinstance(item, QGraphicsPathItem):
                    render_data.append((
                        lid,
                        item.path(),
                        item.pen(),
                        item.brush(),
                        item.zValue(),
                        item.isVisible(),
                    ))
        return render_data

    def open_export_dialog(self) -> bool:
        """Открытие модального диалога экспорта карты и выполнение экспорта при подтверждении."""
        if not self.has_active_map():
            QMessageBox.information(
                self._parent,
                tr("dialog.export_map_title"),
                tr("export.err_no_map"),
            )
            return False

        profile = self._get_active_profile()
        map_path = self._get_map_path()
        map_title = profile.name if profile else (map_path.stem if map_path else "Map")
        active_crs = self._get_active_crs()

        current_view_extent = self.get_current_view_extent()
        full_map_extent = self.get_full_map_extent()

        # Точки берутся непосредственно из сервиса (не фильтруются поиском в панели)
        all_points = self._point_service.get_points()
        selected_ids = set(self._points_panel.selected_point_ids())
        layers_render_data = self.collect_layer_render_data()

        dialog = ExportImageDialog(
            parent=self._parent,
            active_crs=active_crs,
            map_title=map_title,
            current_view_extent=current_view_extent,
            full_map_extent=full_map_extent,
            points=all_points,
            selected_point_ids=selected_ids,
            settings_service=self._settings_service,
            loaded_layers_render_data=layers_render_data,
        )

        if not dialog.exec():
            return False

        try:
            options = dialog.build_export_options()
            target_extent = dialog.get_current_target_extent()

            if not target_extent:
                QMessageBox.warning(
                    self._parent,
                    tr("dialog.export_map_title"),
                    tr("export.err_no_points_for_extent"),
                )
                return False

            self._set_status(tr("export.status_exporting"))

            out_path = ImageExportService.export_image(
                options=options,
                active_crs=active_crs,
                target_extent=target_extent,
                loaded_layers_render_data=layers_render_data,
                points=all_points,
                selected_point_ids=selected_ids,
            )

            success_msg = tr("export.status_success", path=str(out_path))
            self._set_status(success_msg, 4000)
            logger.info("Экспорт карты успешно завершен: %s", out_path)
            return True

        except Exception as e:
            err_text = tr("export.err_failed", error=str(e))
            logger.exception("Ошибка экспорта карты: %s", e)
            QMessageBox.critical(
                self._parent,
                tr("dialog.export_map_title"),
                err_text,
            )
            self._set_status(tr("status.error"), 3000)
            return False
