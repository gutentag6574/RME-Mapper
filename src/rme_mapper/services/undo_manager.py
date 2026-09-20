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
        description: str = "Импорт точек",
    ) -> None:
        super().__init__(description)
        self.points = [copy.deepcopy(p) for p in points]
        self._add_fn = add_fn
        self._remove_fn = remove_fn

    def execute(self) -> None:
        self._add_fn([copy.deepcopy(p) for p in self.points])

    def undo(self) -> None:
        self._remove_fn([p.id for p in self.points])


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
