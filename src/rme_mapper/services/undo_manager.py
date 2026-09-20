"""Менеджер отмены и повтора действий (Undo / Redo) на базе паттерна Команда.

Не содержит зависимостей от виджетов Qt и графических элементов сцены.
Работает исключительно со структурами данных модели MapPoint.
"""

from abc import ABC, abstractmethod
from collections.abc import Callable
import copy
import logging
from typing import Any

from rme_mapper.models.map_point import MapPoint

logger = logging.getLogger("rme_mapper.services.undo")


class UndoCommand(ABC):
    """Базовый абстрактный класс команды для стека отмены/повтора."""

    def __init__(self, description: str = "") -> None:
        self.description = description

    @abstractmethod
    def execute(self) -> None:
        """Выполнение команды."""
        pass

    @abstractmethod
    def undo(self) -> None:
        """Откат команды."""
        pass

    def redo(self) -> None:
        """Повтор команды (по умолчанию выполняет execute)."""
        self.execute()


class AddPointCommand(UndoCommand):
    """Команда добавления пользовательской точки."""

    def __init__(
        self,
        point: MapPoint,
        add_fn: Callable[[MapPoint], None],
        remove_fn: Callable[[str], None],
        description: str = "Добавить точку",
    ) -> None:
        super().__init__(description)
        # Сохраняем глубокую копию данных точки
        self.point = copy.deepcopy(point)
        self._add_fn = add_fn
        self._remove_fn = remove_fn

    def execute(self) -> None:
        self._add_fn(copy.deepcopy(self.point))

    def undo(self) -> None:
        self._remove_fn(self.point.id)


class DeletePointCommand(UndoCommand):
    """Команда удаления одиночной точки с сохранением позиции в таблице."""

    def __init__(
        self,
        point: MapPoint,
        row_index: int,
        restore_fn: Callable[[MapPoint, int], None],
        remove_fn: Callable[[str], None],
        description: str = "Удалить точку",
    ) -> None:
        super().__init__(description)
        self.point = copy.deepcopy(point)
        self.row_index = row_index
        self._restore_fn = restore_fn
        self._remove_fn = remove_fn

    def execute(self) -> None:
        self._remove_fn(self.point.id)

    def undo(self) -> None:
        self._restore_fn(copy.deepcopy(self.point), self.row_index)


class DeleteMultiplePointsCommand(UndoCommand):
    """Команда группового удаления точек как единой атомарной транзакции."""

    def __init__(
        self,
        points_with_indices: list[tuple[MapPoint, int]],
        restore_fn: Callable[[MapPoint, int], None],
        remove_fn: Callable[[str], None],
        description: str = "Удалить выбранные точки",
    ) -> None:
        super().__init__(description)
        self.points_with_indices = [
            (copy.deepcopy(pt), idx) for pt, idx in points_with_indices
        ]
        self._restore_fn = restore_fn
        self._remove_fn = remove_fn

    def execute(self) -> None:
        for pt, _ in self.points_with_indices:
            self._remove_fn(pt.id)

    def undo(self) -> None:
        # Восстанавливаем точки в порядке возрастания исходных индексов
        sorted_points = sorted(self.points_with_indices, key=lambda x: x[1])
        for pt, idx in sorted_points:
            self._restore_fn(copy.deepcopy(pt), idx)


class EditPointCommand(UndoCommand):
    """Команда изменения параметров пользовательской точки."""

    def __init__(
        self,
        before_point: MapPoint,
        after_point: MapPoint,
        apply_fn: Callable[[MapPoint], None],
        description: str = "Изменить точку",
    ) -> None:
        super().__init__(description)
        self.before_point = copy.deepcopy(before_point)
        self.after_point = copy.deepcopy(after_point)
        self._apply_fn = apply_fn

    def execute(self) -> None:
        self._apply_fn(copy.deepcopy(self.after_point))

    def undo(self) -> None:
        self._apply_fn(copy.deepcopy(self.before_point))


class MovePointCommand(UndoCommand):
    """Команда перемещения пользовательской точки мышью на карте."""

    def __init__(
        self,
        before_point: MapPoint,
        after_point: MapPoint,
        apply_fn: Callable[[MapPoint], None],
        description: str = "Переместить точку",
    ) -> None:
        super().__init__(description)
        self.before_point = copy.deepcopy(before_point)
        self.after_point = copy.deepcopy(after_point)
        self._apply_fn = apply_fn

    def execute(self) -> None:
        self._apply_fn(copy.deepcopy(self.after_point))

    def undo(self) -> None:
        self._apply_fn(copy.deepcopy(self.before_point))


class BulkEditStyleCommand(UndoCommand):
    """Команда группового изменения стилей точек как единой транзакции."""

    def __init__(
        self,
        before_points: list[MapPoint],
        after_points: list[MapPoint],
        apply_fn: Callable[[list[MapPoint]], None],
        description: str = "Изменить стили точек",
    ) -> None:
        super().__init__(description)
        self.before_points = [copy.deepcopy(p) for p in before_points]
        self.after_points = [copy.deepcopy(p) for p in after_points]
        self._apply_fn = apply_fn

    def execute(self) -> None:
        self._apply_fn([copy.deepcopy(p) for p in self.after_points])

    def undo(self) -> None:
        self._apply_fn([copy.deepcopy(p) for p in self.before_points])


class ImportPointsCommand(UndoCommand):
    """Команда атомарного добавления набора точек из файла импорта."""

    def __init__(
        self,
        points: list[MapPoint],
        add_fn: Callable[[list[MapPoint]], None],
        remove_fn: Callable[[list[str]], None],
        created_groups: list[Any] | None = None,
        add_groups_fn: Callable[[list[Any]], None] | None = None,
        remove_groups_fn: Callable[[list[str]], None] | None = None,
        description: str = "Импорт точек",
    ) -> None:
        super().__init__(description)
        self.points = [copy.deepcopy(p) for p in points]
        self._add_fn = add_fn
        self._remove_fn = remove_fn
        self.created_groups = [copy.deepcopy(g) for g in (created_groups or [])]
        self._add_groups_fn = add_groups_fn
        self._remove_groups_fn = remove_groups_fn

    def execute(self) -> None:
        if self._add_groups_fn and self.created_groups:
            self._add_groups_fn([copy.deepcopy(g) for g in self.created_groups])
        self._add_fn([copy.deepcopy(p) for p in self.points])

    def undo(self) -> None:
        self._remove_fn([p.id for p in self.points])
        if self._remove_groups_fn and self.created_groups:
            self._remove_groups_fn([g.id for g in self.created_groups])


class CreateGroupCommand(UndoCommand):
    """Команда создания группы объектов."""

    def __init__(
        self,
        group: Any,
        add_fn: Callable[[Any], None],
        remove_fn: Callable[[str], None],
        description: str = "Создать группу",
    ) -> None:
        super().__init__(description)
        self.group = copy.deepcopy(group)
        self._add_fn = add_fn
        self._remove_fn = remove_fn

    def execute(self) -> None:
        self._add_fn(copy.deepcopy(self.group))

    def undo(self) -> None:
        self._remove_fn(self.group.id)


class RenameGroupCommand(UndoCommand):
    """Команда переименования и/или редактирования описания группы."""

    def __init__(
        self,
        group_id: str,
        before_name: str,
        after_name: str,
        before_desc: str,
        after_desc: str,
        apply_fn: Callable[[str, str, str], None],
        description: str = "Переименовать группу",
    ) -> None:
        super().__init__(description)
        self.group_id = group_id
        self.before_name = before_name
        self.after_name = after_name
        self.before_desc = before_desc
        self.after_desc = after_desc
        self._apply_fn = apply_fn

    def execute(self) -> None:
        self._apply_fn(self.group_id, self.after_name, self.after_desc)

    def undo(self) -> None:
        self._apply_fn(self.group_id, self.before_name, self.before_desc)


class DeleteGroupCommand(UndoCommand):
    """Команда удаления группы с переводом участников в Ungrouped и полным восстановлением при отмене."""

    def __init__(
        self,
        group: Any,
        affected_point_ids: list[str],
        restore_group_fn: Callable[[Any], None],
        remove_group_fn: Callable[[str], None],
        set_points_group_fn: Callable[[list[str], str | None], None],
        description: str = "Удалить группу",
    ) -> None:
        super().__init__(description)
        self.group = copy.deepcopy(group)
        self.affected_point_ids = list(affected_point_ids)
        self._restore_group_fn = restore_group_fn
        self._remove_group_fn = remove_group_fn
        self._set_points_group_fn = set_points_group_fn

    def execute(self) -> None:
        self._set_points_group_fn(self.affected_point_ids, None)
        self._remove_group_fn(self.group.id)

    def undo(self) -> None:
        self._restore_group_fn(copy.deepcopy(self.group))
        self._set_points_group_fn(self.affected_point_ids, self.group.id)


class AssignPointsToGroupCommand(UndoCommand):
    """Команда перемещения точек в группу с запоминанием исходной группы для каждой точки."""

    def __init__(
        self,
        previous_groups: dict[str, str | None] | None = None,
        target_group_id: str | None = None,
        apply_fn: Callable[[dict[str, str | None]], None] | None = None,
        description: str = "Переместить в группу",
        *,
        point_ids: list[str] | None = None,
        before_groups: dict[str, str | None] | None = None,
        target_group: str | None = None,
    ) -> None:
        super().__init__(description)
        raw_groups = previous_groups if previous_groups is not None else (before_groups or {})
        self.previous_groups = dict(raw_groups)
        self.target_group_id = target_group_id if target_group_id is not None else target_group
        self._apply_fn = apply_fn or (lambda _: None)

    def execute(self) -> None:
        target_dict = {pid: self.target_group_id for pid in self.previous_groups}
        self._apply_fn(target_dict)

    def undo(self) -> None:
        self._apply_fn(self.previous_groups)


class SetGroupVisibilityCommand(UndoCommand):
    """Команда изменения видимости группы объектов."""

    def __init__(
        self,
        group_id: str,
        before_visible: bool,
        after_visible: bool,
        apply_fn: Callable[[str, bool], None],
        description: str = "Изменить видимость группы",
    ) -> None:
        super().__init__(description)
        self.group_id = group_id
        self.before_visible = before_visible
        self.after_visible = after_visible
        self._apply_fn = apply_fn

    def execute(self) -> None:
        self._apply_fn(self.group_id, self.after_visible)

    def undo(self) -> None:
        self._apply_fn(self.group_id, self.before_visible)


class BulkChangeCategoryCommand(UndoCommand):
    """Команда массового изменения категории выбранных точек."""

    def __init__(
        self,
        previous_categories: dict[str, str] | None = None,
        new_category: str = "",
        apply_fn: Callable[[dict[str, str]], None] | None = None,
        description: str = "Изменить категорию",
        *,
        point_ids: list[str] | None = None,
        before_categories: dict[str, str] | None = None,
        target_category: str | None = None,
    ) -> None:
        super().__init__(description)
        raw_cats = previous_categories if previous_categories is not None else (before_categories or {})
        self.previous_categories = dict(raw_cats)
        self.new_category = new_category if new_category != "" else (target_category or "")
        self._apply_fn = apply_fn or (lambda _: None)

    def execute(self) -> None:
        target_dict = {pid: self.new_category for pid in self.previous_categories}
        self._apply_fn(target_dict)

    def undo(self) -> None:
        self._apply_fn(self.previous_categories)


class EditGeoreferencingCommand(UndoCommand):
    """Команда отмены/повтора изменения параметров геопривязки растра."""

    def __init__(
        self,
        apply_fn: Callable[[tuple[float, float, float, float, float, float], list[dict[str, Any]], str], None],
        before_affine: tuple[float, float, float, float, float, float],
        before_control_points: list[dict[str, Any]],
        before_crs: str,
        after_affine: tuple[float, float, float, float, float, float],
        after_control_points: list[dict[str, Any]],
        after_crs: str,
        description: str = "Редактировать геопривязку",
    ) -> None:
        super().__init__(description)
        self.apply_fn = apply_fn
        self.before_affine = before_affine
        self.before_control_points = [dict(cp) for cp in before_control_points]
        self.before_crs = before_crs
        self.after_affine = after_affine
        self.after_control_points = [dict(cp) for cp in after_control_points]
        self.after_crs = after_crs

    def execute(self) -> None:
        self.apply_fn(self.after_affine, self.after_control_points, self.after_crs)

    def undo(self) -> None:
        self.apply_fn(self.before_affine, self.before_control_points, self.before_crs)


class UndoManager:
    """Сервис управления историей действий (Undo / Redo)."""

    def __init__(
        self,
        on_state_changed: Callable[[], None] | None = None,
    ) -> None:
        self._undo_stack: list[UndoCommand] = []
        self._redo_stack: list[UndoCommand] = []
        self._clean_index: int = 0
        self._state_callbacks: list[Callable[[], None]] = []
        if on_state_changed:
            self._state_callbacks.append(on_state_changed)

    @property
    def can_undo(self) -> bool:
        """Возможно ли отменить последнее действие."""
        return len(self._undo_stack) > 0

    @property
    def can_redo(self) -> bool:
        """Возможно ли повторить отмененное действие."""
        return len(self._redo_stack) > 0

    @property
    def undo_description(self) -> str:
        """Описание действия на вершине стека отмены."""
        if self._undo_stack:
            return self._undo_stack[-1].description
        return ""

    @property
    def redo_description(self) -> str:
        """Описание действия на вершине стека повтора."""
        if self._redo_stack:
            return self._redo_stack[-1].description
        return ""

    @property
    def is_clean(self) -> bool:
        """Находится ли стек в точно сохраненном состоянии проекта."""
        return len(self._undo_stack) == self._clean_index

    def mark_clean(self) -> None:
        """Отметка текущего состояния как сохраненного (чистого)."""
        self._clean_index = len(self._undo_stack)
        self._notify_state_changed()

    def push(self, command: UndoCommand, execute: bool = False) -> None:
        """Регистрация нового действия в стеке отмены.

        Очищает стек Redo при новом действии пользователя.
        """
        if execute:
            command.execute()
        self._undo_stack.append(command)
        self._redo_stack.clear()
        logger.info("Добавлена команда в Undo: '%s' (стек: %d)", command.description, len(self._undo_stack))
        self._notify_state_changed()

    def undo(self) -> bool:
        """Отмена последнего действия."""
        if not self.can_undo:
            return False
        cmd = self._undo_stack.pop()
        try:
            cmd.undo()
            self._redo_stack.append(cmd)
            logger.info("Выполнен Undo: '%s' (осталось: %d, redo: %d)", cmd.description, len(self._undo_stack), len(self._redo_stack))
            self._notify_state_changed()
            return True
        except Exception as e:
            logger.error("Ошибка при выполнении Undo команды '%s': %s", cmd.description, e)
            self._undo_stack.append(cmd)
            raise

    def redo(self) -> bool:
        """Повтор последнего отмененного действия."""
        if not self.can_redo:
            return False
        cmd = self._redo_stack.pop()
        try:
            cmd.redo()
            self._undo_stack.append(cmd)
            logger.info("Выполнен Redo: '%s' (стек: %d, осталось redo: %d)", cmd.description, len(self._undo_stack), len(self._redo_stack))
            self._notify_state_changed()
            return True
        except Exception as e:
            logger.error("Ошибка при выполнении Redo команды '%s': %s", cmd.description, e)
            self._redo_stack.append(cmd)
            raise

    def clear(self) -> None:
        """Полный сброс истории (например, при создании или открытии проекта)."""
        self._undo_stack.clear()
        self._redo_stack.clear()
        self._clean_index = 0
        logger.info("История Undo/Redo очищена")
        self._notify_state_changed()

    def set_on_state_changed(self, callback: Callable[[], None] | None) -> None:
        """Установка обратного вызова при изменении состояния стеков."""
        self._state_callbacks.clear()
        if callback:
            self._state_callbacks.append(callback)

    def add_on_state_changed(self, callback: Callable[[], None]) -> None:
        """Добавление дополнительного слушателя изменения состояния стеков."""
        if callback not in self._state_callbacks:
            self._state_callbacks.append(callback)

    def _notify_state_changed(self) -> None:
        for cb in list(self._state_callbacks):
            try:
                cb()
            except Exception as e:
                logger.warning("Ошибка в обработчике on_state_changed UndoManager: %s", e)


# Алиас для обратной совместимости
BulkEditPointStyleCommand = BulkEditStyleCommand
