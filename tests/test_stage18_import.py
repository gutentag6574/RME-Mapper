"""Тесты импорта файлов с колонкой группы и отката создания новых групп (Этап 18)."""

from pathlib import Path

from rme_mapper.importers.import_service import ImportService
from rme_mapper.importers.models import ImportOptions
from rme_mapper.models.object_group import ObjectGroup
from rme_mapper.services.group_service import GroupService
from rme_mapper.services.point_service import PointService
from rme_mapper.services.undo_manager import ImportPointsCommand, UndoManager


def test_import_with_group_column(tmp_path: Path):
    """Проверка распознавания колонки группы и связывания точек с группами."""
    csv_content = (
        "name,latitude,longitude,group\n"
        "Скважина 1,56.123,47.456,Север\n"
        "Скважина 2,56.124,47.457,Юг\n"
        "Скважина 3,56.125,47.458,\n"
    )
    csv_file = tmp_path / "points_with_groups.csv"
    csv_file.write_text(csv_content, encoding="utf-8")

    service = ImportService()
    opts = ImportOptions()
    opts.create_missing_groups = True

    res = service.validate_file(csv_file, opts)
    assert res.valid_rows == 3
    assert len(res.points) == 3

    # Должны быть обнаружены 2 новые группы: "Север" и "Юг"
    assert set(res.new_group_names) == {"Север", "Юг"}
    assert len(res.new_groups) == 2

    # Точки 1 и 2 имеют group_id, точка 3 - None
    assert res.points[0].group_id is not None
    assert res.points[1].group_id is not None
    assert res.points[2].group_id is None
    # ID у точек 1 и 2 разные
    assert res.points[0].group_id != res.points[1].group_id


def test_import_existing_group_matching(tmp_path: Path):
    """Проверка связывания с уже существующей группой без создания дубликата."""
    csv_content = (
        "name,lat,lon,группа\n"
        "Объект А,56.1,47.1,Центр\n"
    )
    csv_file = tmp_path / "existing_group.csv"
    csv_file.write_text(csv_content, encoding="utf-8")

    service = ImportService()
    existing_grp = ObjectGroup(id="grp-center-id", name="Центр")

    opts = ImportOptions()
    opts.group_name_to_id = {"центр": existing_grp.id}

    res = service.validate_file(csv_file, opts)
    assert res.valid_rows == 1
    # Новая группа не создана, так как "Центр" уже существует
    assert res.new_group_names == []
    # Точка привязана к существующему ID
    assert res.points[0].group_id == "grp-center-id"


def test_import_undo_redo_rolls_back_new_groups():
    """Проверка отката транзакции импорта с удалением созданных пустых групп."""
    ps = PointService()
    gs = GroupService()
    undo_mgr = UndoManager()

    # Исходно: в проекте групп нет
    assert len(gs) == 0

    new_grp1 = ObjectGroup(id="g1", name="Новая Группа 1")
    new_grp2 = ObjectGroup(id="g2", name="Новая Группа 2")

    p1 = ps.add_point(name="Точка 1", latitude=56.0, longitude=47.0, group_id="g1")
    p2 = ps.add_point(name="Точка 2", latitude=56.1, longitude=47.1, group_id="g2")

    def add_points_fn(points):
        for p in points:
            ps._points[p.id] = p

    def remove_points_fn(pids):
        for pid in pids:
            ps.remove_point(pid)

    def add_groups_fn(grps):
        for g in grps:
            gs.add_existing_group(g)

    def remove_groups_fn(gids):
        for gid in gids:
            try:
                gs.delete_group(gid)
            except KeyError:
                pass

    cmd = ImportPointsCommand(
        points=[p1, p2],
        add_fn=add_points_fn,
        remove_fn=remove_points_fn,
        created_groups=[new_grp1, new_grp2],
        add_groups_fn=add_groups_fn,
        remove_groups_fn=remove_groups_fn,
        description="Импорт 2 точек",
    )

    # 1. Выполняем команду импорта
    undo_mgr.push(cmd, execute=True)

    assert len(ps) == 2
    assert len(gs) == 2
    assert gs.get_group("g1") is not None
    assert gs.get_group("g2") is not None

    # 2. Undo - точки удаляются, и созданные пустые группы тоже удаляются в один шаг!
    assert undo_mgr.can_undo is True
    undo_mgr.undo()

    assert len(ps) == 0
    assert len(gs) == 0
    assert gs.get_group("g1") is None
    assert gs.get_group("g2") is None

    # 3. Redo - точки и группы восстанавливаются
    assert undo_mgr.can_redo is True
    undo_mgr.redo()

    assert len(ps) == 2
    assert len(gs) == 2
    assert gs.get_group("g1") is not None
    assert gs.get_group("g2") is not None


def test_import_create_missing_groups_off(tmp_path: Path):
    """Проверка импорта при выключенной опции создания недостающих групп (Point 21).

    При create_missing_groups=False точка с неизвестной группой переходит в Ungrouped (None).
    """
    csv_content = (
        "name,latitude,longitude,group\n"
        "Точка 1,56.0,47.0,Неизвестная Группа\n"
    )
    csv_file = tmp_path / "missing_groups_off.csv"
    csv_file.write_text(csv_content, encoding="utf-8")

    opts = ImportOptions(
        create_missing_groups=False,
        group_name_to_id={},
    )

    service = ImportService()
    result = service.validate_file(csv_file, opts)

    assert result.valid_rows == 1
    point = result.points[0]
    # При create_missing_groups=False группа не создается, group_id = None
    assert point.group_id is None
    assert len(result.new_groups) == 0


def test_import_group_name_collision_case_insensitive(tmp_path: Path):
    """Проверка коллизии названий: 'Forest' и существующая 'forest' не создают дубликат (Point 23)."""
    csv_content = (
        "name,latitude,longitude,group\n"
        "Объект 1,56.0,47.0,Forest\n"
        "Объект 2,56.1,47.1,forest\n"
    )
    csv_file = tmp_path / "case_collision.csv"
    csv_file.write_text(csv_content, encoding="utf-8")

    # Существующая группа "forest" с id="grp-forest"
    opts = ImportOptions(
        create_missing_groups=True,
        group_name_to_id={"forest": "grp-forest"},
    )

    service = ImportService()
    result = service.validate_file(csv_file, opts)

    assert result.valid_rows == 2
    p1 = result.points[0]
    p2 = result.points[1]

    # Обе точки ссылаются на существующую группу
    assert p1.group_id == "grp-forest"
    assert p2.group_id == "grp-forest"
    # Никаких новых групп не создано
    assert len(result.new_groups) == 0


def test_import_undo_preserves_pre_existing_groups():
    """Проверка транзакции импорта (Point 22): при Undo существующие группы не удаляются!"""
    gs = GroupService()
    ps = PointService()
    undo_mgr = UndoManager()

    existing_grp = gs.create_group("Существующая группа", group_id="grp-existing")
    new_grp = ObjectGroup(id="grp-new", name="Новая группа", visible=True)
    p_imported = ps.add_point(name="Импорт 1", latitude=56.0, longitude=47.0, group_id="grp-new")

    def add_points_fn(points):
        for p in points:
            ps._points[p.id] = p

    def remove_points_fn(pids):
        for pid in pids:
            ps.remove_point(pid)

    def add_groups_fn(grps):
        for g in grps:
            gs.add_existing_group(g)

    def remove_groups_fn(gids):
        for gid in gids:
            try:
                gs.delete_group(gid)
            except KeyError:
                pass

    cmd = ImportPointsCommand(
        points=[p_imported],
        add_fn=add_points_fn,
        remove_fn=remove_points_fn,
        created_groups=[new_grp],
        add_groups_fn=add_groups_fn,
        remove_groups_fn=remove_groups_fn,
        description="Импорт с новой группой",
    )

    undo_mgr.push(cmd, execute=True)
    assert len(gs) == 2
    assert gs.get_group("grp-existing") is not None
    assert gs.get_group("grp-new") is not None

    # Undo
    undo_mgr.undo()

    # Новая группа удалена, а существовавшая до импорта ОБЯЗАНА остаться!
    assert gs.get_group("grp-new") is None
    assert gs.get_group("grp-existing") is not None
    assert len(gs) == 1
    assert len(ps) == 0

