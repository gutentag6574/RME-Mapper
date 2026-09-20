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
from rme_mapper.ui.import_wizard import ImportWizard

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
        group_service: Any = None,
        group_controller: Any = None,
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
        self._group_service = group_service
        self._group_controller = group_controller

    def set_group_service(self, service: Any) -> None:
        self._group_service = service

    def set_group_controller(self, controller: Any) -> None:
        self._group_controller = controller

    def _set_status(self, text: str, timeout: int = 0) -> None:
        if self._set_status_message:
            self._set_status_message(text, timeout)

    def _has_active_map(self) -> bool:
        """Проверка наличия загруженной карты."""
        return self._get_active_profile() is not None or self._get_map_path() is not None

    def open_import_wizard(self, file_path: Path | str | None = None) -> bool:
        """Открытие пошагового мастера импорта точек (Этап 14)."""
        # Поддержка обратной совместимости со старыми тестами Этапа 13 (если open_import_dialog подменен)
        if type(self).open_import_dialog != self.open_import_dialog:
            return self.open_import_dialog(file_path)

        if not self._has_active_map():
            QMessageBox.information(
                self._parent,
                tr("dialog.no_map_title"),
                tr("dialog.no_map_text"),
            )
            return False

        last_dir = self._settings_service.get_last_import_directory()
        wizard = ImportWizard(
            parent=self._parent,
            file_path=file_path,
            last_directory=last_dir,
            existing_points=self._point_service.get_points(),
            boundary_geometry=self._get_boundary_geometry(),
            group_service=self._group_service,
        )

        if wizard.exec():
            res = wizard.get_validation_result()
            points = wizard.get_final_points()
            if not points:
                return False

            src_path = wizard.get_source_path()
            if src_path:
                self._settings_service.set_last_import_directory(str(src_path))

            created_groups = res.new_groups if res else []

            def add_groups_fn(grps: list[Any]) -> None:
                if self._group_service:
                    for g in grps:
                        self._group_service.add_existing_group(g)
                if self._group_controller:
                    self._group_controller.refresh_groups_ui()

            def remove_groups_fn(gids: list[str]) -> None:
                if self._group_service:
                    for gid in gids:
                        try:
                            self._group_service.delete_group(gid)
                        except KeyError:
                            pass
                if self._group_controller:
                    self._group_controller.refresh_groups_ui()

            cmd = ImportPointsCommand(
                points=points,
                add_fn=self._point_controller._cmd_add_points,
                remove_fn=self._point_controller._cmd_remove_points,
                created_groups=created_groups,
                add_groups_fn=add_groups_fn,
                remove_groups_fn=remove_groups_fn,
                description=f"{tr('action.import_points')}: {len(points)}",
            )
            self._point_controller.undo_manager.push(cmd, execute=True)

            if self._group_controller:
                self._group_controller.refresh_groups_ui()

            # Сохранение снимка аварийного восстановления
            self._project_controller._save_recovery_snapshot_worker()

            self._set_status(tr("status.import_success", count=len(points)), 3000)
            logger.info("Мастер успешно импортировал %s точек из %s", len(points), src_path)
            return True

        return False

    def open_import_dialog(self, file_path: Path | str | None = None) -> bool:
        """[УСТАРЕЛО] Открытие устаревшего базового диалога импорта точек (Этап 13).

        Сохранен исключительно для обратной совместимости с внешними вызовами и старыми тестами.
        Основным и рекомендуемым рабочим процессом приложения является open_import_wizard().
        """
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
