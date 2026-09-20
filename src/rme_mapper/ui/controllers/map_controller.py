"""Контроллер управления картой, слоями и координатной системой."""

from collections.abc import Callable
import logging
from pathlib import Path
from typing import Any

import uuid
from PySide6.QtCore import QObject
from PySide6.QtWidgets import QMessageBox, QWidget

from rme_mapper.backends import MapDataBackend, BackendFactory, get_raster_backend
from rme_mapper.i18n import tr
from rme_mapper.maps.map_canvas import MapCanvas
from rme_mapper.models.map_layer import LayerRole, MapLayer
from rme_mapper.models.map_profile import MapProfile
from rme_mapper.services.layer_service import LayerService
from rme_mapper.services.map_catalog_service import MapCatalogService
from rme_mapper.services.point_service import PointService
from rme_mapper.ui.open_map_dialog import OpenMapDialog
from rme_mapper.ui.panels.layers_panel import LayersPanel
from rme_mapper.ui.panels.points_panel import PointsPanel

logger = logging.getLogger("rme_mapper.ui.controllers.map_controller")


class MapController(QObject):
    """Контроллер жизненного цикла карты, загрузки данных и переключения слоев."""

    def __init__(
        self,
        parent_widget: QWidget,
        backend: MapDataBackend,
        map_canvas: MapCanvas,
        layers_panel: LayersPanel,
        points_panel: PointsPanel,
        point_service: PointService,
        layer_service: LayerService,
        map_catalog_service: MapCatalogService,
        on_map_loaded: Callable[[str], None],
        on_modified: Callable[[], None],
        is_project_active: Callable[[], bool] | None = None,
        set_status_message: Callable[[str, int], None] | None = None,
        set_map_title: Callable[[str], None] | None = None,
        settings_service: Any = None,
        on_map_unloaded: Callable[[], None] | None = None,
    ) -> None:
        super().__init__(parent_widget)
        self._parent = parent_widget
        self._backend = backend
        self._map_canvas = map_canvas
        self._layers_panel = layers_panel
        self._points_panel = points_panel
        self._point_service = point_service
        self._layer_service = layer_service
        self._map_catalog_service = map_catalog_service
        self._settings_service = settings_service

        self._on_map_loaded = on_map_loaded
        self._on_modified = on_modified
        self._is_project_active = is_project_active
        self._set_status_message = set_status_message
        self._set_map_title = set_map_title
        self._on_map_unloaded = on_map_unloaded


        # Владение состоянием карты
        self._active_profile: MapProfile | None = None
        self._map_path: Path | None = None
        self._active_crs: str = "OGC:CRS84"
        self._loaded_layers: list[MapLayer] = []
        self._boundary_geometry: Any = None

        self._layers_panel.layer_visibility_changed.connect(self.set_layer_visibility)

    @property
    def active_profile(self) -> MapProfile | None:
        return self._active_profile

    @active_profile.setter
    def active_profile(self, profile: MapProfile | None) -> None:
        self._active_profile = profile

    @property
    def map_path(self) -> Path | None:
        return self._map_path

    @map_path.setter
    def map_path(self, path: Path | None) -> None:
        self._map_path = path

    @property
    def active_crs(self) -> str:
        return self._active_crs

    @active_crs.setter
    def active_crs(self, crs: str) -> None:
        self._active_crs = crs

    @property
    def loaded_layers(self) -> list[MapLayer]:
        return self._loaded_layers

    @loaded_layers.setter
    def loaded_layers(self, layers: list[MapLayer]) -> None:
        self._loaded_layers = layers

    @property
    def boundary_geometry(self) -> Any:
        return self._boundary_geometry

    @boundary_geometry.setter
    def boundary_geometry(self, geom: Any) -> None:
        self._boundary_geometry = geom

    def _set_status(self, text: str, timeout: int = 0) -> None:
        if self._set_status_message:
            self._set_status_message(text, timeout)

    def _update_title(self, title: str) -> None:
        if self._set_map_title:
            self._set_map_title(title)

    def open_map_workflow(self, map_target: MapProfile | Path | str | None = None) -> bool:
        """Открытие карты через OpenMapDialog или напрямую по объекту/пути."""
        if map_target is not None:
            self.load_map(map_target)
            return True

        initial_dir = None
        if self._settings_service:
            initial_dir = self._settings_service.get_last_map_directory(check_exists=True)

        dialog = OpenMapDialog(
            parent=self._parent,
            catalog_service=self._map_catalog_service,
            backend=self._backend,
            initial_dir=initial_dir,
        )

        if dialog.exec():
            profile = dialog.get_map_profile()
            if profile:
                self.load_map(profile)
                if self._is_project_active and self._is_project_active():
                    self._on_modified()
                return True
        return False

    def close_map_workflow(self, prompt: bool = True) -> bool:
        """Безопасная выгрузка карты из приложения."""
        if self._active_profile is None and self._map_path is None:
            return True

        if prompt and len(self._point_service) > 0:
            reply = QMessageBox.question(
                self._parent,
                tr("dialog.close_map_title"),
                tr("dialog.close_map_text", count=len(self._point_service)),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
                return False

        self.unload_map()
        if self._is_project_active and self._is_project_active():
            self._on_modified()
        return True

    def unload_map(self) -> None:
        """Перевод приложения в состояние без активной карты."""
        if self._map_path:
            try:
                if BackendFactory.supports_geotiff():
                    rb = get_raster_backend()
                    rb.close(self._map_path)
            except Exception as e:
                logger.debug("Ошибка при закрытии растрового бэкенда: %s", e)

        self._active_profile = None
        self._map_path = None
        self._boundary_geometry = None
        self._loaded_layers.clear()
        self._layers_panel.clear_layers()
        self._map_canvas.clear_map()

        self._update_title(tr("status.no_map"))
        self._set_status(tr("status.no_map"))
        self._points_panel.set_buttons_enabled(add=False, edit=False, delete=False)
        if self._on_map_unloaded:
            self._on_map_unloaded()

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

        if not path.is_file():
            err_msg = f"{tr('msg.map_file_not_found')}:\n{path}"
            logger.error("Файл карты не найден: %s", path)
            self._map_canvas.set_error(err_msg)
            self._set_status(tr("status.error_map_not_found"))
            return

        is_geotiff = (
            (profile is not None and getattr(profile, "source_type", "") == "geotiff")
            or path.suffix.lower() in (".tif", ".tiff")
        )

        # -------------------------------------------------------------
        # Специальная обработка растровой карты GeoTIFF
        # -------------------------------------------------------------
        if is_geotiff:
            if not BackendFactory.supports_geotiff():
                err_msg = tr("msg.geotiff_backend_unavailable") or "Поддержка GeoTIFF недоступна в этой сборке."
                logger.error("Поддержка GeoTIFF недоступна для %s", path)
                self._map_canvas.set_error(err_msg)
                self._set_status(err_msg)
                return

            try:
                rb = get_raster_backend()
                info = rb.inspect_raster(path)
                crs_val = info.get("crs")
                if not crs_val:
                    err_msg = tr("msg.geotiff_no_crs") or "В файле отсутствует система координат."
                    logger.error(err_msg)
                    self._map_canvas.set_error(err_msg)
                    self._set_status(err_msg)
                    return

                if not info.get("is_valid_georef"):
                    err_msg = tr("msg.geotiff_no_georef") or "Файл не содержит корректной географической привязки."
                    logger.error(err_msg)
                    self._map_canvas.set_error(err_msg)
                    self._set_status(err_msg)
                    return

                rgba_preview, meta = rb.read_preview(path, max_dimension=4096)
                affine_coeffs = meta["transform"]
                full_size = (info["width"], info["height"])

                display_name = tr("layer.raster") or "Растр"
                lid = "raster_base"
                vis = True
                if profile and profile.layers:
                    first_cfg = profile.layers[0]
                    display_name = str(first_cfg.get("display_name") or first_cfg.get("name") or display_name)
                    lid = str(first_cfg.get("id") or lid)
                    vis = bool(first_cfg.get("visible", True))

                raster_layer = MapLayer(
                    id=lid,
                    source_name="raster",
                    display_name=display_name,
                    geometry_type="raster",
                    crs=crs_val,
                    visible=vis,
                    feature_count=1,
                    role=LayerRole.RASTER,
                    z_order=5,
                    style={"border_color": "#000000", "fill_color": None, "border_width": 0.0},
                )

                def raster_provider(win_extent, target_w, target_h):
                    return rb.read_window(path, win_extent, target_w, target_h)

                self._layers_panel.clear_layers()
                self._map_canvas.add_raster_item(
                    layer=raster_layer,
                    image_or_array=rgba_preview,
                    affine_coeffs=affine_coeffs,
                    full_size=full_size,
                    raster_provider=raster_provider,
                )

                self._loaded_layers = [raster_layer]
                self._active_crs = crs_val
                self._boundary_geometry = None

                if profile is not None:
                    if not profile.extent:
                        profile.extent = info.get("extent")
                    if not profile.crs:
                        profile.crs = crs_val
                else:
                    self._active_profile = MapProfile(
                        id=f"runtime_{uuid.uuid4().hex[:8]}",
                        name=path.stem,
                        source_type="geotiff",
                        source_path=str(path.resolve()),
                        base_dir=path.parent,
                        crs=crs_val,
                        boundary_layer=None,
                        boundary_required=False,
                        extent=info.get("extent"),
                        layers=[{
                            "id": lid,
                            "name": "raster",
                            "source_name": "raster",
                            "display_name": display_name,
                            "geometry_type": "raster",
                            "role": "raster",
                            "visible": vis,
                            "style": {"border_color": "#000000", "fill_color": None, "border_width": 0.0},
                            "z_order": 5,
                        }],
                    )

                self._layers_panel.set_layers([raster_layer])
                self._update_title(f"Карта: {map_title}")
                status_text = f"Карта: {map_title} | {self._active_crs} | Растр: {info['width']}×{info['height']}"
                self._set_status(status_text)
                self._points_panel.set_buttons_enabled(add=True)
                logger.info("Растровая карта успешно загружена. %s", status_text)

                self._on_map_loaded(self._active_crs)
                self._map_canvas.fit_to_view()

                if self._settings_service:
                    self._settings_service.add_recent_map(str(path))
                    self._settings_service.set_last_map_directory(str(path))
                return

            except Exception as raster_err:
                logger.exception("Ошибка при загрузке растровой карты %s: %s", path, raster_err)
                self._map_canvas.set_error(f"Ошибка чтения GeoTIFF:\n{raster_err}")
                self._set_status("Ошибка загрузки GeoTIFF")
                return

        # -------------------------------------------------------------
        # Обработка векторной карты GeoPackage
        # -------------------------------------------------------------
        try:
            if profile:
                discovered_layers = self._layer_service.load_profile_layers(profile)
            else:
                discovered_layers = self._layer_service.discover_layers(path)

            logger.info("Обнаружено поддерживаемых слоев: %d", len(discovered_layers))

            if not discovered_layers:
                err_msg = tr("msg.no_layers_found")
                logger.error(err_msg)
                self._map_canvas.set_error(err_msg)
                self._set_status(tr("status.error_no_layers"))
                return

            self._layers_panel.clear_layers()
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

                    self._map_canvas.add_layer_item(layer, gdf)
                    successfully_loaded.append(layer)

                except Exception as layer_err:
                    logger.exception("Ошибка загрузки слоя '%s': %s", layer.display_name, layer_err)
                    if (profile and profile.boundary_required and layer.role == LayerRole.BOUNDARY):
                        self._map_canvas.set_error(f"Ошибка чтения границы карты:\n{layer_err}")
                        self._set_status("Ошибка чтения границы карты")
                        return

            self._loaded_layers = successfully_loaded
            self._active_crs = common_crs

            # Настраиваем чекбоксы слоев в панели
            self._layers_panel.set_layers(successfully_loaded)

            # Обновляем заголовок и строку состояния
            self._update_title(f"Карта: {map_title}")
            status_text = f"Карта: {map_title} | {self._active_crs} | Слоёв: {len(successfully_loaded)}"
            self._set_status(status_text)
            self._points_panel.set_buttons_enabled(add=True)
            logger.info("Карта успешно загружена. %s", status_text)

            # Пересчет пользовательских точек под новую CRS
            self._on_map_loaded(self._active_crs)

            # Автоподгонка охвата
            self._map_canvas.fit_to_view()

            if self._settings_service:
                self._settings_service.add_recent_map(str(path))
                self._settings_service.set_last_map_directory(str(path))


        except Exception as e:
            logger.exception("Критическая ошибка при загрузке карты из %s: %s", path, e)
            self._map_canvas.set_error(f"Ошибка при чтении карты:\n{e}")
            self._set_status("Ошибка загрузки карты")

    def set_layer_visibility(self, layer_id: str, visible: bool) -> None:
        """Переключение видимости слоя и обновление состояния."""
        for layer in self._loaded_layers:
            if layer.id == layer_id:
                layer.visible = visible
                break
        self._map_canvas.set_layer_visibility(layer_id, visible)
        self._layers_panel.set_layer_checked(layer_id, visible)
        self._on_modified()

    def reset_layers_visibility(self) -> None:
        """Сброс видимости всех слоев карты в активное состояние."""
        for layer in self._loaded_layers:
            layer.visible = True
            self._layers_panel.set_layer_checked(layer.id, True)
            self._map_canvas.set_layer_visibility(layer.id, True)
