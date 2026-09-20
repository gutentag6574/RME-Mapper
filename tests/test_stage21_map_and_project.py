"""Тесты интеграции геопривязанных изображений с холстом карты и проектом .gpmap (Stage 21)."""

from pathlib import Path
from unittest.mock import MagicMock
from PIL import Image
from PySide6.QtWidgets import QApplication, QWidget
import pytest

from rme_mapper.maps.map_canvas import MapCanvas
from rme_mapper.models.georeference import ControlPoint
from rme_mapper.models.map_point import MapPoint
from rme_mapper.models.map_profile import MapProfile
from rme_mapper.services.point_service import PointService
from rme_mapper.services.project_service import ProjectService
from rme_mapper.services.undo_manager import EditGeoreferencingCommand, UndoManager
from rme_mapper.ui.controllers.map_controller import MapController
from rme_mapper.ui.panels.layers_panel import LayersPanel
from rme_mapper.ui.panels.points_panel import PointsPanel


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


@pytest.fixture
def sample_georef_png(tmp_path: Path) -> Path:
    p = tmp_path / "plan_georef.png"
    img = Image.new("RGBA", (200, 200), color=(100, 200, 100, 255))
    img.save(p, format="PNG")
    return p


class TestMapAndProjectIntegration:
    """Интеграционные тесты работы карты, точек, Undo и проектов с геопривязанным растром."""

    def test_load_georeferenced_image_in_controller(self, qapp, sample_georef_png: Path):
        """Загрузка геопривязанного изображения в MapController и проверка слоя и CRS."""
        parent = QWidget()
        canvas = MapCanvas(parent)
        point_service = PointService()
        points_panel = PointsPanel(parent)
        layers_panel = LayersPanel(parent)

        controller = MapController(
            parent_widget=parent,
            backend=MagicMock(),
            map_canvas=canvas,
            layers_panel=layers_panel,
            points_panel=points_panel,
            point_service=point_service,
            layer_service=MagicMock(),
            map_catalog_service=MagicMock(),
            on_map_loaded=MagicMock(),
            on_modified=MagicMock(),
        )

        cp1 = ControlPoint("1", pixel_x=0.0, pixel_y=0.0, target_x=100.0, target_y=200.0)
        cp2 = ControlPoint("2", pixel_x=200.0, pixel_y=0.0, target_x=300.0, target_y=200.0)
        cp3 = ControlPoint("3", pixel_x=0.0, pixel_y=200.0, target_x=100.0, target_y=0.0)

        profile = MapProfile(
            id="plan_prof",
            name="Plan Test",
            source_type="georeferenced_image",
            source_path=str(sample_georef_png),
            crs="EPSG:3857",
            affine_transform=[1.0, 0.0, 100.0, 0.0, -1.0, 200.0],
            control_points=[cp1, cp2, cp3],
            transformation_type="affine",
        )

        controller.load_georeferenced_image(profile, sample_georef_png)

        assert controller.active_crs == "EPSG:3857"
        assert controller.active_profile is not None
        assert controller.active_profile.source_type == "georeferenced_image"
        assert len(controller.loaded_layers) == 1
        assert controller.loaded_layers[0].id == "raster_base"

        # Проверяем возможность добавления пользовательских точек поверх карты
        pt = point_service.add_point(
            name="Point 1",
            latitude=150.0,
            longitude=150.0,
            source_crs="EPSG:3857",
        )
        assert pt.id is not None
        assert len(point_service.get_points()) == 1

        parent.deleteLater()

    def test_project_save_and_reopen_georeferenced_image(self, tmp_path: Path, sample_georef_png: Path):
        """Сохранение проекта .gpmap с геопривязанным изображением и его последующее открытие."""
        cp1 = ControlPoint("1", pixel_x=0.0, pixel_y=0.0, target_x=37.61, target_y=55.75)
        cp2 = ControlPoint("2", pixel_x=100.0, pixel_y=0.0, target_x=37.62, target_y=55.75)
        cp3 = ControlPoint("3", pixel_x=0.0, pixel_y=100.0, target_x=37.61, target_y=55.74)

        profile = MapProfile(
            id="prof_mow",
            name="Plan Moscow",
            source_type="georeferenced_image",
            source_path=str(sample_georef_png),
            crs="EPSG:4326",
            affine_transform=[0.0001, 0.0, 37.61, 0.0, -0.0001, 55.75],
            control_points=[cp1, cp2, cp3],
            transformation_type="affine",
        )

        pt1 = MapPoint(id="pt_1", name="Red Square", latitude=55.7539, longitude=37.6208, source_crs="EPSG:4326")
        points = [pt1]

        project_file = tmp_path / "test_georef_project.gpmap"
        project_service = ProjectService()

        # Сохранение
        project_data = project_service.build_project_data(
            map_profile=profile,
            points=points,
            groups=[],
        )
        assert project_data.map is not None
        assert project_data.map.source_type == "georeferenced_image"
        assert project_data.map.affine_transform == [0.0001, 0.0, 37.61, 0.0, -0.0001, 55.75]
        assert len(project_data.map.control_points) == 3

        project_service.save_project(project=project_data, file_path=project_file)
        assert project_file.exists()

        # Открытие и проверка восстановления
        opened_data = project_service.load_project(project_file)
        assert opened_data.map is not None
        assert opened_data.map.source_type == "georeferenced_image"
        assert opened_data.map.affine_transform == [0.0001, 0.0, 37.61, 0.0, -0.0001, 55.75]
        assert len(opened_data.map.control_points) == 3
        assert opened_data.map.control_points[0]["target_x"] == 37.61
        assert len(opened_data.points) == 1
        assert opened_data.points[0].name == "Red Square"

    def test_undo_redo_edit_georeferencing(self):
        """Проверка работы Undo/Redo для изменения геопривязки."""
        undo_mgr = UndoManager()

        cp_old = [ControlPoint("1", pixel_x=0, pixel_y=0, target_x=0, target_y=0)]
        cp_new = [
            ControlPoint("1", pixel_x=0, pixel_y=0, target_x=10, target_y=10),
            ControlPoint("2", pixel_x=10, pixel_y=10, target_x=20, target_y=20),
        ]
        transform_old = (1.0, 0.0, 0.0, 0.0, -1.0, 0.0)
        transform_new = (2.0, 0.0, 10.0, 0.0, -2.0, 10.0)

        applied_states = []

        def apply_fn(transform, points, crs):
            applied_states.append((transform, list(points), crs))

        cmd = EditGeoreferencingCommand(
            apply_fn=apply_fn,
            before_affine=transform_old,
            before_control_points=[cp.to_dict() for cp in cp_old],
            before_crs="EPSG:3857",
            after_affine=transform_new,
            after_control_points=[cp.to_dict() for cp in cp_new],
            after_crs="EPSG:4326",
        )

        undo_mgr.push(cmd, execute=True)
        assert len(applied_states) == 1
        assert applied_states[-1][0] == transform_new
        assert applied_states[-1][2] == "EPSG:4326"

        # Undo
        assert undo_mgr.can_undo
        undo_mgr.undo()
        assert len(applied_states) == 2
        assert applied_states[-1][0] == transform_old
        assert applied_states[-1][2] == "EPSG:3857"

        # Redo
        assert undo_mgr.can_redo
        undo_mgr.redo()
        assert len(applied_states) == 3
        assert applied_states[-1][0] == transform_new
        assert applied_states[-1][2] == "EPSG:4326"
