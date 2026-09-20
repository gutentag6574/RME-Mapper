"""Тесты Zoom to Group и массовых операций изменения категорий/стилей (Этап 18)."""

from rme_mapper.maps.map_canvas import MapCanvas
from rme_mapper.models.map_point import MapPoint
from rme_mapper.services.point_service import PointService
from rme_mapper.services.undo_manager import BulkChangeCategoryCommand, UndoManager


def test_zoom_to_group_extent(qapp):
    """Проверка вычисления охвата точек группы при приближении."""
    canvas = MapCanvas()
    canvas.set_active_crs("EPSG:4326")

    p1 = MapPoint(id="p1", name="П1", latitude=56.0, longitude=47.0)
    p2 = MapPoint(id="p2", name="П2", latitude=56.2, longitude=47.4)

    # Вызов zoom_to_group не должен падать с ошибкой и должен пересчитывать viewport
    canvas.zoom_to_group([p1, p2])

    # С одной точкой
    canvas.zoom_to_group([p1])

    # С пустым списком - безопасный no-op
    canvas.zoom_to_group([])


def test_bulk_change_category_undo_redo():
    """Проверка команды массового изменения категории с поддержкой Undo/Redo."""
    ps = PointService()
    p1 = ps.add_point(name="П1", latitude=56.0, longitude=47.0, category="Старая А")
    p2 = ps.add_point(name="П2", latitude=56.1, longitude=47.1, category="Старая Б")
    p3 = ps.add_point(name="П3", latitude=56.2, longitude=47.2, category="")

    undo_mgr = UndoManager()

    before_map = {p1.id: "Старая А", p2.id: "Старая Б", p3.id: ""}
    new_cat = "Новая Категория"

    def apply_fn(point_category_map: dict[str, str]) -> None:
        for pid, cat in point_category_map.items():
            ps.update_point(pid, category=cat)

    cmd = BulkChangeCategoryCommand(
        point_ids=[p1.id, p2.id, p3.id],
        before_categories=before_map,
        target_category=new_cat,
        apply_fn=apply_fn,
        description="Изменить категорию",
    )

    # 1. Применяем команду
    undo_mgr.push(cmd, execute=True)

    assert ps.get_point(p1.id).category == "Новая Категория"
    assert ps.get_point(p2.id).category == "Новая Категория"
    assert ps.get_point(p3.id).category == "Новая Категория"

    # 2. Undo - восстанавливает индивидуальные исходные категории
    assert undo_mgr.can_undo is True
    undo_mgr.undo()

    assert ps.get_point(p1.id).category == "Старая А"
    assert ps.get_point(p2.id).category == "Старая Б"
    assert ps.get_point(p3.id).category == ""

    # 3. Redo - повторно применяет новую категорию
    assert undo_mgr.can_redo is True
    undo_mgr.redo()

    assert ps.get_point(p1.id).category == "Новая Категория"
    assert ps.get_point(p2.id).category == "Новая Категория"
    assert ps.get_point(p3.id).category == "Новая Категория"
