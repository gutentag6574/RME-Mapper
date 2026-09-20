"""Тесты моделей данных геопривязки (Stage 21)."""

import pytest

from rme_mapper.models.georeference import ControlPoint, MAX_CONTROL_POINTS
from rme_mapper.models.map_profile import MapProfile
from rme_mapper.models.project_data import ProjectMapData


class TestGeorefModels:
    """Тестирование моделей ControlPoint, MapProfile и ProjectMapData для геопривязки."""

    def test_control_point_defaults(self):
        """Проверка значений по умолчанию и инициализации ControlPoint."""
        cp = ControlPoint(
            id="cp_1",
            pixel_x=100.5,
            pixel_y=200.5,
            target_x=37.6173,
            target_y=55.7558,
        )
        assert cp.id == "cp_1"
        assert cp.pixel_x == 100.5
        assert cp.pixel_y == 200.5
        assert cp.target_x == 37.6173
        assert cp.target_y == 55.7558
        assert cp.enabled is True
        assert cp.residual_x is None
        assert cp.residual_y is None
        assert cp.residual_total is None

    def test_control_point_serialization(self):
        """Проверка сериализации to_dict и десериализации from_dict."""
        cp = ControlPoint(
            id="cp_test",
            pixel_x=50.0,
            pixel_y=75.0,
            target_x=1000.0,
            target_y=2000.0,
            enabled=False,
            residual_x=0.12,
            residual_y=-0.34,
            residual_total=0.36,
        )
        d = cp.to_dict()
        assert d["id"] == "cp_test"
        assert d["pixel_x"] == 50.0
        assert d["pixel_y"] == 75.0
        assert d["target_x"] == 1000.0
        assert d["target_y"] == 2000.0
        assert d["enabled"] is False
        assert d["residual_x"] == 0.12
        assert d["residual_y"] == -0.34
        assert d["residual_total"] == 0.36

        restored = ControlPoint.from_dict(d)
        assert restored.id == cp.id
        assert restored.pixel_x == cp.pixel_x
        assert restored.pixel_y == cp.pixel_y
        assert restored.target_x == cp.target_x
        assert restored.target_y == cp.target_y
        assert restored.enabled is False
        assert restored.residual_x == 0.12
        assert restored.residual_y == -0.34
        assert restored.residual_total == 0.36

    def test_map_profile_georeferenced_image_fields(self):
        """Проверка сохранения и восстановления полей геопривязки в MapProfile."""
        cp1 = ControlPoint(id="1", pixel_x=0, pixel_y=0, target_x=10, target_y=20)
        cp2 = ControlPoint(id="2", pixel_x=10, pixel_y=0, target_x=20, target_y=20)
        cp3 = ControlPoint(id="3", pixel_x=0, pixel_y=10, target_x=10, target_y=10)

        profile = MapProfile(
            id="prof_1",
            name="Test Georef Image",
            source_type="georeferenced_image",
            source_path="images/plan.png",
            crs="EPSG:3857",
            affine_transform=[1.0, 0.0, 100.0, 0.0, -1.0, 200.0],
            control_points=[cp1, cp2, cp3],
            transformation_type="affine",
        )

        d = profile.to_dict()
        assert d["source"]["type"] == "georeferenced_image"
        assert d["source"]["affine_transform"] == [1.0, 0.0, 100.0, 0.0, -1.0, 200.0]
        assert d["source"]["transformation_type"] == "affine"
        assert len(d["source"]["control_points"]) == 3
        assert d["source"]["control_points"][0]["id"] == "1"

        restored = MapProfile.from_dict(d)
        assert restored.source_type == "georeferenced_image"
        assert tuple(restored.affine_transform) == (1.0, 0.0, 100.0, 0.0, -1.0, 200.0)
        assert restored.transformation_type == "affine"
        assert len(restored.control_points) == 3
        assert isinstance(restored.control_points[0], ControlPoint)
        assert restored.control_points[0].pixel_x == 0.0

    def test_project_map_data_georeferenced_image_fields(self):
        """Проверка сохранения и восстановления полей геопривязки в ProjectMapData."""
        cp = ControlPoint(id="p1", pixel_x=12.0, pixel_y=34.0, target_x=56.0, target_y=78.0)
        pmd = ProjectMapData(
            map_id="map_1",
            source_type="georeferenced_image",
            relative_path="map.jpg",
            crs="EPSG:4326",
            affine_transform=[0.5, 0.0, 10.0, 0.0, -0.5, 50.0],
            control_points=[cp.to_dict()],
            transformation_type="affine",
        )
        d = pmd.to_dict()
        assert d["source_type"] == "georeferenced_image"
        assert d["affine_transform"] == [0.5, 0.0, 10.0, 0.0, -0.5, 50.0]
        assert len(d["control_points"]) == 1

        restored = ProjectMapData.from_dict(d)
        assert restored.source_type == "georeferenced_image"
        assert restored.affine_transform == [0.5, 0.0, 10.0, 0.0, -0.5, 50.0]
        assert len(restored.control_points) == 1
        assert restored.control_points[0]["pixel_x"] == 12.0

    def test_max_control_points_constant(self):
        """Проверка константы максимального количества контрольных точек."""
        assert MAX_CONTROL_POINTS == 500
