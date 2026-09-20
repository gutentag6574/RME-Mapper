"""Контроллер управления жизненным циклом проектов (*.gpmap / *.rmeproject)."""

from collections.abc import Callable
import logging
from pathlib import Path
from typing import Any
import uuid

from PySide6.QtCore import QObject, QTimer

from PySide6.QtWidgets import QFileDialog, QMessageBox, QWidget

from rme_mapper.i18n import tr
from rme_mapper.maps.map_config import get_project_root
from rme_mapper.models.map_profile import MapProfile
from rme_mapper.models.project_data import ProjectData
from rme_mapper.services.map_catalog_service import MapCatalogService
from rme_mapper.services.point_service import PointService
from rme_mapper.services.project_service import ProjectService
from rme_mapper.ui.controllers.map_controller import MapController
from rme_mapper.ui.controllers.point_controller import PointController

logger = logging.getLogger("rme_mapper.ui.controllers.project_controller")


class ProjectController(QObject):
    """Контроллер операций с проектами: создание, сохранение, открытие, dirty state."""

    def __init__(
        self,
        parent_widget: QWidget,
        project_service: ProjectService,
        point_service: PointService,
        map_controller: MapController,
        point_controller: PointController,
        map_catalog_service: MapCatalogService,
        on_title_changed: Callable[[], None],
        set_status_message: Callable[[str, int], None] | None = None,
        settings_service: Any = None,
    ) -> None:
        super().__init__(parent_widget)
        self._parent = parent_widget
        self._project_service = project_service
        self._point_service = point_service
        self._map_controller = map_controller
        self._point_controller = point_controller
        self._map_catalog_service = map_catalog_service
        self._on_title_changed = on_title_changed
        self._set_status_message = set_status_message
        self._settings_service = settings_service

        # Владение состоянием проекта
        self._current_project_path: Path | None = None
        self._is_modified: bool = False
        self._project_loaded: bool = False

        # Таймер аварийного снимка (debounce 3 секунды)
        self._recovery_timer = QTimer(self)
        self._recovery_timer.setSingleShot(True)
        self._recovery_timer.setInterval(3000)
        self._recovery_timer.timeout.connect(self._save_recovery_snapshot_worker)


    @property
    def current_project_path(self) -> Path | None:
        return self._current_project_path

    @current_project_path.setter
    def current_project_path(self, path: Path | None) -> None:
        self._current_project_path = path
        self._on_title_changed()

    @property
    def is_modified(self) -> bool:
        return self._is_modified

    @is_modified.setter
    def is_modified(self, modified: bool) -> None:
        self.set_modified(modified)

    @property
    def project_loaded(self) -> bool:
        return self._project_loaded

    @project_loaded.setter
    def project_loaded(self, loaded: bool) -> None:
        self._project_loaded = loaded

    def _set_status(self, text: str, timeout: int = 0) -> None:
        if self._set_status_message:
            self._set_status_message(text, timeout)

    def set_modified(self, modified: bool = True) -> None:
        """Установка флага изменений и уведомление об обновлении заголовка."""
        self._is_modified = modified
        if modified:
            self._project_loaded = True
            if hasattr(self, "_recovery_timer"):
                self._recovery_timer.start()
        else:
            if hasattr(self, "_recovery_timer"):
                self._recovery_timer.stop()
        self._on_title_changed()

    def _save_recovery_snapshot_worker(self) -> None:
        """Фоновое сохранение снимка аварийного восстановления при наличии изменений."""
        if not self._is_modified:
            return
        try:
            points = self._point_service.get_points()
            profile = self._map_controller.active_profile
            project_data = self._project_service.build_project_data(
                map_path=self._map_controller.map_path,
                layers=self._map_controller.loaded_layers,
                points=points,
                map_id=profile.id if profile else "",
                map_profile=profile,
            )
            curr_path = str(self._current_project_path) if self._current_project_path else None
            self._project_service.save_recovery_snapshot(project_data, curr_path)
        except Exception as e:
            logger.warning("Не удалось сохранить аварийный снимок: %s", e)

    def cleanup_on_exit(self) -> None:
        """Очистка таймеров и удаление аварийных снимков при штатном завершении работы."""
        if hasattr(self, "_recovery_timer"):
            self._recovery_timer.stop()
        self._project_service.clear_recovery_snapshot()

    def maybe_save_prompt(self, action_name: str | None = None) -> bool:
        """Запрос сохранения при наличии несохраненных изменений.

        Возвращает:
            True — продолжить действие.
            False — отменить действие.
        """
        if not self._is_modified:
            return True

        if action_name is None:
            action_name = tr("dialog.unsaved_action_exit")

        proj_name = self._current_project_path.name if self._current_project_path else tr("project.untitled")
        reply = QMessageBox.question(
            self._parent,
            tr("dialog.unsaved_title"),
            tr("dialog.unsaved_text", name=proj_name, action=action_name),
            QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Save,
        )

        if reply == QMessageBox.StandardButton.Save:
            return self.save_project_workflow()
        elif reply == QMessageBox.StandardButton.Discard:
            return True
        else:  # Cancel
            return False

    def new_project_workflow(self) -> bool:
        """Сценарий создания нового пустого проекта."""
        if not self.maybe_save_prompt(tr("dialog.unsaved_action_new")):
            return False

        self._point_controller.clear_all_points()
        self._map_controller.unload_map()
        self._current_project_path = None
        self._project_loaded = False
        self.set_modified(False)
        self._project_service.clear_recovery_snapshot()
        self._set_status(tr("status.no_map"))
        logger.info("Создан новый проект")
        return True

    def save_project_workflow(self) -> bool:
        """Сохранение проекта в текущий файл или вызов Save As."""
        if self._current_project_path is None:
            return self.save_project_as_workflow()
        return self._do_save(self._current_project_path)

    def save_project_as_workflow(self, file_path: Path | str | None = None) -> bool:
        """Сохранение проекта с выбором файла через диалог."""
        if file_path is None:
            initial_dir = (
                str(self._current_project_path.parent)
                if self._current_project_path
                else (self._settings_service.get_last_project_directory(check_exists=True) if self._settings_service else "")
            )
            chosen, _ = QFileDialog.getSaveFileName(
                self._parent,
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
        """Сериализация данных проекта и атомарная запись на диск."""
        try:
            points = self._point_service.get_points()
            profile = self._map_controller.active_profile
            project_data = self._project_service.build_project_data(
                map_path=self._map_controller.map_path,
                layers=self._map_controller.loaded_layers,
                points=points,
                map_id=profile.id if profile else "",
                map_profile=profile,
            )
            saved_path = self._project_service.save_project(project_data, path)
            self._current_project_path = saved_path
            self._project_loaded = True
            self.set_modified(False)
            if hasattr(self._point_controller, "undo_manager"):
                self._point_controller.undo_manager.mark_clean()
            self._project_service.clear_recovery_snapshot()
            if self._settings_service:
                self._settings_service.add_recent_project(str(saved_path))
                self._settings_service.set_last_project_directory(str(saved_path))
            self._set_status(tr("status.project_saved", path=saved_path.name), 3000)
            logger.info("Проект успешно сохранен в %s", saved_path)
            return True
        except Exception as e:
            logger.exception("Ошибка при сохранении проекта в %s: %s", path, e)
            QMessageBox.critical(
                self._parent,
                tr("dialog.error_title"),
                tr("msg.save_project_error", err=str(e)),
            )
            return False

    def open_project_workflow(self, file_path: Path | str | None = None) -> bool:
        """Открытие проекта из файла *.gpmap или *.rmeproject."""
        if not self.maybe_save_prompt(tr("dialog.unsaved_action_open")):
            return False

        if not file_path:
            initial_dir = (
                str(self._current_project_path.parent)
                if self._current_project_path
                else (self._settings_service.get_last_project_directory(check_exists=True) if self._settings_service else "")
            )
            selected_file, _ = QFileDialog.getOpenFileName(
                self._parent,
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
                self._parent,
                tr("dialog.open_project_error_title"),
                tr("msg.open_project_error", path=str(path), err=str(e)),
            )
            return False

        if not self._resolve_and_apply_project(project, path):
            return False

        self._current_project_path = path
        self._project_loaded = True
        self.set_modified(False)
        if hasattr(self._point_controller, "undo_manager"):
            self._point_controller.undo_manager.clear()
            self._point_controller.undo_manager.mark_clean()
        self._project_service.clear_recovery_snapshot()
        if self._settings_service:
            self._settings_service.add_recent_project(str(path))
            self._settings_service.set_last_project_directory(str(path))
        self._set_status(tr("status.project_opened", name=path.name), 3000)
        logger.info("Проект открыт: %s (%d точек)", path, len(project.points))
        return True

    def restore_recovery_snapshot(self) -> bool:
        """Восстановление проекта из аварийного снимка."""
        try:
            project, curr_path = self._project_service.load_recovery_snapshot()
            path_obj = Path(curr_path) if curr_path else None
            if not self._resolve_and_apply_project(project, path_obj):
                return False
            self._current_project_path = path_obj
            self._project_loaded = True
            self.set_modified(True)
            self._set_status(tr("dialog.recovery_title"), 3000)
            return True
        except Exception as e:
            logger.exception("Ошибка восстановления из аварийного снимка: %s", e)
            raise

    def _resolve_and_apply_project(self, project: ProjectData, path: Path | None) -> bool:
        """Разрешение связанных слоев карты и применение структуры проекта."""
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
            elif path and (path.parent / p).exists():
                target_map_path = (path.parent / p).resolve()
            elif (get_project_root() / p).exists():
                target_map_path = (get_project_root() / p).resolve()
            elif p.exists():
                target_map_path = p.resolve()

        has_map_reference = bool(project.map.map_id or project.map.relative_path)

        if has_map_reference and (target_map_path is None or not target_map_path.exists()):
            msg_box = QMessageBox(self._parent)
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
                dir_for_search = str(path.parent) if path else str(get_project_root())
                map_filter = tr("dialog.map.filter_maps") or "Файлы карт (*.gpkg *.tif *.tiff);;Все файлы (*.*)"
                chosen, _ = QFileDialog.getOpenFileName(
                    self._parent,
                    tr("dialog.locate_map_title"),
                    dir_for_search,
                    map_filter,
                )
                if not chosen:
                    return False
                target_map_path = Path(chosen)
                target_profile = None
            else:  # btn_no_map
                target_map_path = None
                target_profile = None

        if target_profile:
            self._map_controller.load_map(target_profile)
        elif target_map_path and target_map_path.exists():
            s_type = project.map.source_type or ("geotiff" if target_map_path.suffix.lower() in (".tif", ".tiff") else "geopackage")
            if project.map.layers or s_type == "geotiff":
                runtime_prof = MapProfile(
                    id=project.map.map_id or f"runtime_{uuid.uuid4().hex[:8]}",
                    name=project.map.name or target_map_path.stem,
                    source_type=s_type,
                    source_path=str(target_map_path),
                    base_dir=target_map_path.parent,
                    crs=project.map.crs,
                    boundary_layer=project.map.boundary_layer,
                    layers=project.map.layers,
                )
                self._map_controller.load_map(runtime_prof)
            else:
                self._map_controller.load_map(target_map_path)
        else:
            self._map_controller.unload_map()

        self.apply_project_data(project)
        return True


    def apply_project_data(self, project: ProjectData) -> None:
        """Восстановление состояния карты, видимости слоев, точек и зон из проекта."""
        # 1. Очищаем существующие точки
        self._point_controller.clear_all_points()

        # 2. Восстанавливаем видимость слоев
        for layer in self._map_controller.loaded_layers:
            vis = None
            if layer.id in project.layers:
                vis = project.layers[layer.id]
            elif hasattr(layer, "role") and hasattr(layer.role, "value") and layer.role.value in project.layers:
                vis = project.layers[layer.role.value]

            if vis is not None:
                self._map_controller.set_layer_visibility(layer.id, vis)

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
            self._point_controller._render_point_on_canvas(added_pt)
            self._point_controller.add_point_to_table(added_pt)
