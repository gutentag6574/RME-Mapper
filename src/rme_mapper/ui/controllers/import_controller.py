"""Контроллер пользовательского сценария пакетного импорта точек."""

from collections.abc import Callable
import logging
from pathlib import Path
from typing import Any

from PySide6.QtWidgets import QMessageBox, QWidget

from rme_mapper.i18n import tr
from rme_mapper.importers.models import ImportResult
from rme_mapper.services.app_settings_service import AppSettingsService
from rme_mapper.services.point_service import PointService
from rme_mapper.services.undo_manager import ImportPointsCommand
from rme_mapper.ui.controllers.point_controller import PointController
from rme_mapper.ui.controllers.project_controller import ProjectController
from rme_mapper.ui.import_dialog import ImportDialog

logger = logging.getLogger("rme_mapper.ui.controllers.import")


class ImportController:
    """Контроллер управления процессом импорта точек из внешних табличных файлов."""

    def __init__(
        self,
        parent_widget: QWidget,
        point_controller: PointController,
        point_service: PointService,
        project_controller: ProjectController,
        get_active_profile: Callable[[], Any],
        get_map_path: Callable[[], Any],
        get_boundary_geometry: Callable[[], Any],
        settings_service: AppSettingsService,
        set_status_message: Callable[[str, int], None] | None = None,
    ) -> None:
        self._parent = parent_widget
        self._point_controller = point_controller
        self._point_service = point_service
        self._project_controller = project_controller
        self._get_active_profile = get_active_profile
        self._get_map_path = get_map_path
        self._get_boundary_geometry = get_boundary_geometry
        self._settings_service = settings_service
        self._set_status_message = set_status_message

    def _set_status(self, text: str, timeout: int = 0) -> None:
        if self._set_status_message:
            self._set_status_message(text, timeout)

    def _has_active_map(self) -> bool:
        """Проверка наличия загруженной карты."""
        return self._get_active_profile() is not None or self._get_map_path() is not None

    def open_import_dialog(self, file_path: Path | str | None = None) -> bool:
        """Открытие базового диалога импорта точек и добавление валидных точек в проект."""
        if not self._has_active_map():
            QMessageBox.information(
                self._parent,
                tr("dialog.no_map_title"),
                tr("dialog.no_map_text"),
            )
            return False

        last_dir = self._settings_service.get_last_import_directory()
        dialog = ImportDialog(
            parent=self._parent,
            file_path=file_path,
            last_directory=last_dir,
            boundary_geometry=self._get_boundary_geometry(),
            current_project_points_count=len(self._point_service),
        )

        if dialog.exec():
            points = dialog.get_valid_points()
            if not points:
                return False

            file_selected = dialog.file_input.text().strip()
            if file_selected:
                self._settings_service.set_last_import_directory(file_selected)

            cmd = ImportPointsCommand(
                points=points,
                add_fn=self._point_controller._cmd_add_points,
                remove_fn=self._point_controller._cmd_remove_points,
                description=f"{tr('action.import_points')}: {len(points)}",
            )
            self._point_controller.undo_manager.push(cmd, execute=True)

            # Сохранение снимка аварийного восстановления
            self._project_controller._save_recovery_snapshot_worker()

            self._set_status(tr("status.import_success", count=len(points)), 3000)
            logger.info("Успешно импортировано %s точек из %s", len(points), file_selected)
            return True

        return False
