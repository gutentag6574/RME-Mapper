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


def test_zoom_to_group_projected_and_hidden(qapp):
    """Проверка Zoom to Group в projected CRS и для скрытой группы (Point 12).

    Zoom не должен менять visibility!
    """
    canvas = MapCanvas()
    canvas.set_active_crs("EPSG:3857")

    p1 = MapPoint(id="p1", name="П1", latitude=56.0, longitude=47.0, group_id="grp-h", visible=True)
    p2 = MapPoint(id="p2", name="П2", latitude=56.5, longitude=47.5, group_id="grp-h", visible=True)

    canvas.set_group_visibility("grp-h", False)
    assert canvas.is_group_visible("grp-h") is False

    # Zoom к точкам скрытой группы не падает
    canvas.zoom_to_group([p1, p2])

    # Visibility точек и группы не изменились!
    assert p1.visible is True
    assert p2.visible is True
    assert canvas.is_group_visible("grp-h") is False


def test_group_bulk_style_workflow_integration(qapp, monkeypatch):
    """Проверка переиспользования BulkPointStyleDialog для группы (Point 13) и одного шага Undo."""
    from rme_mapper.ui.controllers.point_controller import PointController
    from rme_mapper.ui.bulk_point_style_dialog import BulkPointStyleDialog
    from rme_mapper.ui.panels.points_panel import PointsPanel
    from rme_mapper.ui.panels.properties_panel import PropertiesPanel

    ps = PointService()
    panel = PointsPanel()
    props = PropertiesPanel()
    canvas = MapCanvas()
    undo_mgr = UndoManager()

    p1 = ps.add_point(name="Точка 1", latitude=56.0, longitude=47.0, symbol="circle", size=10.0)
    p2 = ps.add_point(name="Точка 2", latitude=56.1, longitude=47.1, symbol="square", size=10.0)

    ctrl = PointController(
        parent_widget=panel,
        point_service=ps,
        points_panel=panel,
        properties_panel=props,
        map_canvas=canvas,
        get_active_crs=lambda: "EPSG:4326",
        get_active_profile=lambda: None,
        get_map_path=lambda: None,
        get_boundary_geometry=lambda: None,
        on_modified=lambda: None,
        undo_manager=undo_mgr,
    )

    # Мокаем exec() и get_style_changes() у диалога, подтверждая переиспользование BulkPointStyleDialog
    class MockBulkDialog:
        def __init__(self, parent, points):
            self.points = points
            # Проверяем, что переданы именно наши точки
            assert len(points) == 2

        def exec(self):
            return 1

        def get_style_changes(self):
            return {"size": 25.0, "symbol": "triangle"}

    monkeypatch.setattr("rme_mapper.ui.controllers.point_controller.BulkPointStyleDialog", MockBulkDialog)

    # Вызываем bulk_edit_style_workflow с передачей точек группы
    ctrl.bulk_edit_style_workflow([p1, p2])

    assert ps.get_point(p1.id).size == 25.0
    assert ps.get_point(p1.id).symbol == "triangle"
    assert ps.get_point(p2.id).size == 25.0
    assert ps.get_point(p2.id).symbol == "triangle"

    # Один шаг Undo отменяет изменения для всех точек
    assert undo_mgr.can_undo is True
    undo_mgr.undo()

    assert ps.get_point(p1.id).size == 10.0
    assert ps.get_point(p1.id).symbol == "circle"
    assert ps.get_point(p2.id).size == 10.0
    assert ps.get_point(p2.id).symbol == "square"

