"""Тесты для безопасного удаления групп и Undo/Redo (Этап 18)."""

from rme_mapper.models.object_group import ObjectGroup
from rme_mapper.services.group_service import GroupService
from rme_mapper.services.point_service import PointService
from rme_mapper.services.undo_manager import DeleteGroupCommand, UndoManager


def test_delete_group_safe_policy_and_undo_redo():
    """Проверка, что удаление группы не удаляет точки, переводит их в Ungrouped и восстанавливается по Undo."""
    gs = GroupService()
    ps = PointService()
    undo_mgr = UndoManager()

    # Создаем группу и 3 точки
    group = gs.create_group("Промышленная зона", "Объекты промзоны")
    p1 = ps.add_point(name="Завод", latitude=56.0, longitude=47.0, group_id=group.id)
    p2 = ps.add_point(name="Склад", latitude=56.1, longitude=47.1, group_id=group.id)
    p3 = ps.add_point(name="Офис", latitude=56.2, longitude=47.2, group_id=None)

    affected_point_ids = [p.id for p in ps.get_points_by_group(group.id)]
    assert affected_point_ids == [p1.id, p2.id]

    def restore_group_fn(grp: ObjectGroup) -> None:
        gs.add_existing_group(grp)

    def remove_group_fn(gid: str) -> None:
        gs.delete_group(gid)

    def set_points_group_fn(pids: list[str], gid: str | None) -> None:
        ps.set_points_group(pids, gid)

    cmd = DeleteGroupCommand(
        group=group,
        affected_point_ids=affected_point_ids,
        restore_group_fn=restore_group_fn,
        remove_group_fn=remove_group_fn,
        set_points_group_fn=set_points_group_fn,
        description="Удалить группу Промышленная зона",
    )

    # 1. Выполняем удаление
    undo_mgr.push(cmd, execute=True)

    # Группа удалена из реестра
    assert gs.get_group(group.id) is None
    assert len(gs) == 0

    # Точки НЕ удалены! Они перешли в Ungrouped (None)
    assert len(ps) == 3
    assert ps.get_point(p1.id).group_id is None
    assert ps.get_point(p2.id).group_id is None
    assert ps.get_point(p3.id).group_id is None
    assert len(ps.get_points_by_group(None)) == 3

    # 2. Отмена удаления (Undo)
    assert undo_mgr.can_undo is True
    undo_mgr.undo()

    # Группа восстановлена с оригинальным ID и свойствами
    restored_grp = gs.get_group(group.id)
    assert restored_grp is not None
    assert restored_grp.name == "Промышленная зона"
    assert restored_grp.description == "Объекты промзоны"
    assert len(gs) == 1

    # Точки вернули свое членство в группе
    assert ps.get_point(p1.id).group_id == group.id
    assert ps.get_point(p2.id).group_id == group.id
    assert ps.get_point(p3.id).group_id is None
    assert len(ps.get_points_by_group(group.id)) == 2
    assert len(ps.get_points_by_group(None)) == 1

    # 3. Повтор удаления (Redo)
    assert undo_mgr.can_redo is True
    undo_mgr.redo()

    assert gs.get_group(group.id) is None
    assert ps.get_point(p1.id).group_id is None
    assert ps.get_point(p2.id).group_id is None
