"""Тесты для управления членством точек в группах и команд перемещения (Этап 18)."""

from rme_mapper.services.point_service import PointService
from rme_mapper.services.undo_manager import AssignPointsToGroupCommand, UndoManager


def test_point_service_membership():
    """Проверка методов работы с group_id в PointService."""
    ps = PointService()
    p1 = ps.add_point(name="П1", latitude=56.0, longitude=47.0)
    p2 = ps.add_point(name="П2", latitude=56.1, longitude=47.1, group_id="grp-1")
    p3 = ps.add_point(name="П3", latitude=56.2, longitude=47.2, group_id="grp-1")

    # Проверка получения точек по группе
    assert [p.id for p in ps.get_points_by_group(None)] == [p1.id]
    assert [p.id for p in ps.get_points_by_group("grp-1")] == [p2.id, p3.id]
    assert ps.get_points_by_group("grp-unknown") == []

    # Изменение группы одной точки
    ps.set_point_group(p1.id, "grp-1")
    assert ps.get_point(p1.id).group_id == "grp-1"
    assert len(ps.get_points_by_group("grp-1")) == 3
    assert len(ps.get_points_by_group(None)) == 0

    # Массовое изменение группы
    ps.set_points_group([p1.id, p2.id], "grp-2")
    assert ps.get_point(p1.id).group_id == "grp-2"
    assert ps.get_point(p2.id).group_id == "grp-2"
    assert ps.get_point(p3.id).group_id == "grp-1"


def test_assign_points_to_group_undo_redo():
    """Проверка отката и повтора перемещения точек с поддержкой индивидуальных предыдущих групп."""
    ps = PointService()
    p1 = ps.add_point(name="П1", latitude=56.0, longitude=47.0, group_id=None)
    p2 = ps.add_point(name="П2", latitude=56.1, longitude=47.1, group_id="grp-A")
    p3 = ps.add_point(name="П3", latitude=56.2, longitude=47.2, group_id="grp-B")

    undo_mgr = UndoManager()

    # Запоминаем предыдущие группы для команды
    before_map = {p1.id: None, p2.id: "grp-A", p3.id: "grp-B"}
    target_group = "grp-TARGET"

    def apply_fn(point_group_map: dict[str, str | None]) -> None:
        for pid, gid in point_group_map.items():
            ps.set_point_group(pid, gid)

    cmd = AssignPointsToGroupCommand(
        point_ids=[p1.id, p2.id, p3.id],
        before_groups=before_map,
        target_group=target_group,
        apply_fn=apply_fn,
        description="Переместить в группу TARGET",
    )

    # Выполняем команду
    undo_mgr.push(cmd, execute=True)

    assert ps.get_point(p1.id).group_id == "grp-TARGET"
    assert ps.get_point(p2.id).group_id == "grp-TARGET"
    assert ps.get_point(p3.id).group_id == "grp-TARGET"

    # Отмена (Undo) - каждый объект должен вернуться в свою индивидуальную исходную группу
    assert undo_mgr.can_undo is True
    undo_mgr.undo()

    assert ps.get_point(p1.id).group_id is None
    assert ps.get_point(p2.id).group_id == "grp-A"
    assert ps.get_point(p3.id).group_id == "grp-B"

    # Повтор (Redo)
    assert undo_mgr.can_redo is True
    undo_mgr.redo()

    assert ps.get_point(p1.id).group_id == "grp-TARGET"
    assert ps.get_point(p2.id).group_id == "grp-TARGET"
    assert ps.get_point(p3.id).group_id == "grp-TARGET"


def test_category_and_group_independence():
    """Проверка, что Категория и Группа независимы (Point 3).

    Смена группы не меняет category.
    Смена category не меняет group_id.
    """
    ps = PointService()
    pt = ps.add_point(
        name="Точка 1",
        latitude=56.0,
        longitude=47.0,
        category="Местообитание",
        group_id="grp-plot1",
    )

    # 1. Меняем группу -> категория остается неизменной
    ps.set_point_group(pt.id, "grp-plot2")
    assert pt.group_id == "grp-plot2"
    assert pt.category == "Местообитание"

    # 2. Меняем категорию -> группа остается неизменной
    ps.update_point(pt.id, category="Наблюдение")
    assert pt.category == "Наблюдение"
    assert pt.group_id == "grp-plot2"

    # 3. Сбрасываем группу в Ungrouped -> категория сохраняется
    ps.set_point_group(pt.id, None)
    assert pt.group_id is None
    assert pt.category == "Наблюдение"


def test_assign_points_to_ungrouped_undo_redo():
    """Проверка перемещения точек в Ungrouped (None) с поддержкой Undo/Redo."""
    ps = PointService()
    p1 = ps.add_point(name="П1", latitude=56.0, longitude=47.0, group_id="grp-A")
    p2 = ps.add_point(name="П2", latitude=56.1, longitude=47.1, group_id="grp-B")

    undo_mgr = UndoManager()
    before_map = {p1.id: "grp-A", p2.id: "grp-B"}

    def apply_fn(point_group_map: dict[str, str | None]) -> None:
        for pid, gid in point_group_map.items():
            ps.set_point_group(pid, gid)

    cmd = AssignPointsToGroupCommand(
        previous_groups=before_map,
        target_group_id=None,
        apply_fn=apply_fn,
        description="Переместить в Без группы",
    )

    undo_mgr.push(cmd, execute=True)
    assert ps.get_point(p1.id).group_id is None
    assert ps.get_point(p2.id).group_id is None

    undo_mgr.undo()
    assert ps.get_point(p1.id).group_id == "grp-A"
    assert ps.get_point(p2.id).group_id == "grp-B"

    undo_mgr.redo()
    assert ps.get_point(p1.id).group_id is None
    assert ps.get_point(p2.id).group_id is None

