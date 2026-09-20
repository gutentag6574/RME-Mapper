"""Тесты аффинного солвера и математического аппарата геопривязки (Stage 21)."""

import math
import pytest

from rme_mapper.models.georeference import ControlPoint
from rme_mapper.services.georeference_service import GeoreferenceService


class TestAffineSolver:
    """Тестирование 2D аффинного решателя GeoreferenceService.solve_affine."""

    def test_solve_affine_exact_translation_and_scale(self):
        """Проверка аналитического решения для 3 точек: масштабирование и перенос."""
        # Модель: X = 2.0 * x + 100.0, Y = -3.0 * y + 500.0
        # a=2.0, b=0.0, c=100.0, d=0.0, e=-3.0, f=500.0
        pts = [
            ControlPoint("1", pixel_x=0.0, pixel_y=0.0, target_x=100.0, target_y=500.0),
            ControlPoint("2", pixel_x=10.0, pixel_y=0.0, target_x=120.0, target_y=500.0),
            ControlPoint("3", pixel_x=0.0, pixel_y=10.0, target_x=100.0, target_y=470.0),
        ]

        transform, updated_pts, rmse = GeoreferenceService.solve_affine(pts, crs="EPSG:3857")
        assert len(transform) == 6
        a, b, c, d, e, f = transform
        assert pytest.approx(a, rel=1e-6) == 2.0
        assert pytest.approx(b, abs=1e-6) == 0.0
        assert pytest.approx(c, rel=1e-6) == 100.0
        assert pytest.approx(d, abs=1e-6) == 0.0
        assert pytest.approx(e, rel=1e-6) == -3.0
        assert pytest.approx(f, rel=1e-6) == 500.0

        # Точное решение для 3 неколлинеарных точек дает нулевой RMSE
        assert pytest.approx(rmse, abs=1e-5) == 0.0
        for p in updated_pts:
            assert pytest.approx(p.residual_total, abs=1e-5) == 0.0

    def test_solve_affine_exact_rotation_and_shear(self):
        """Проверка аналитического решения с поворотом на 45 градусов и сдвигом."""
        angle = math.pi / 4.0
        cos_a = math.cos(angle)
        sin_a = math.sin(angle)
        # X = cos_a * x - sin_a * y + 50
        # Y = sin_a * x + cos_a * y + 80
        pts_coords = [(0.0, 0.0), (100.0, 0.0), (0.0, 50.0)]
        pts = []
        for i, (px, py) in enumerate(pts_coords, start=1):
            tx = cos_a * px - sin_a * py + 50.0
            ty = sin_a * px + cos_a * py + 80.0
            pts.append(ControlPoint(str(i), pixel_x=px, pixel_y=py, target_x=tx, target_y=ty))

        transform, updated_pts, rmse = GeoreferenceService.solve_affine(pts, crs="EPSG:3857")
        a, b, c, d, e, f = transform
        assert pytest.approx(a, rel=1e-5) == cos_a
        assert pytest.approx(b, rel=1e-5) == -sin_a
        assert pytest.approx(c, rel=1e-5) == 50.0
        assert pytest.approx(d, rel=1e-5) == sin_a
        assert pytest.approx(e, rel=1e-5) == cos_a
        assert pytest.approx(f, rel=1e-5) == 80.0
        assert pytest.approx(rmse, abs=1e-5) == 0.0

    def test_solve_affine_least_squares_overdetermined(self):
        """Проверка МНК для N > 3 точек с контролируемым шумом."""
        # Базовая модель: X = 1.0 * x + 10.0, Y = -1.0 * y + 20.0
        pts = [
            ControlPoint("1", pixel_x=0.0, pixel_y=0.0, target_x=10.0, target_y=20.0),
            ControlPoint("2", pixel_x=100.0, pixel_y=0.0, target_x=110.0, target_y=20.0),
            ControlPoint("3", pixel_x=100.0, pixel_y=100.0, target_x=110.0, target_y=-80.0),
            ControlPoint("4", pixel_x=0.0, pixel_y=100.0, target_x=10.0, target_y=-80.0),
            # Точка 5 с небольшим смещением на 0.5 метра
            ControlPoint("5", pixel_x=50.0, pixel_y=50.0, target_x=60.5, target_y=-30.0),
        ]

        transform, updated_pts, rmse = GeoreferenceService.solve_affine(pts, crs="EPSG:3857")
        a, b, c, d, e, f = transform
        assert pytest.approx(a, rel=0.05) == 1.0
        assert pytest.approx(e, rel=0.05) == -1.0
        assert rmse > 0.0  # Из-за смещения в точке 5 RMSE положительный
        assert updated_pts[4].residual_total is not None
        assert updated_pts[4].residual_total > 0.1

    def test_reject_fewer_than_3_points(self):
        """Отказ в вычислении при менее чем 3 активных точках."""
        pts = [
            ControlPoint("1", pixel_x=0.0, pixel_y=0.0, target_x=0.0, target_y=0.0),
            ControlPoint("2", pixel_x=10.0, pixel_y=10.0, target_x=10.0, target_y=10.0),
        ]
        with pytest.raises(ValueError, match="минимум 3"):
            GeoreferenceService.solve_affine(pts, crs="EPSG:3857")

    def test_reject_collinear_points_horizontal(self):
        """Отказ при коллинеарных точках (горизонтальная прямая)."""
        pts = [
            ControlPoint("1", pixel_x=0.0, pixel_y=10.0, target_x=0.0, target_y=0.0),
            ControlPoint("2", pixel_x=50.0, pixel_y=10.0, target_x=50.0, target_y=0.0),
            ControlPoint("3", pixel_x=100.0, pixel_y=10.0, target_x=100.0, target_y=0.0),
        ]
        with pytest.raises(ValueError, match="коллинеарн"):
            GeoreferenceService.solve_affine(pts, crs="EPSG:3857")

    def test_reject_collinear_points_vertical(self):
        """Отказ при коллинеарных точках (вертикальная прямая)."""
        pts = [
            ControlPoint("1", pixel_x=25.0, pixel_y=0.0, target_x=0.0, target_y=0.0),
            ControlPoint("2", pixel_x=25.0, pixel_y=50.0, target_x=0.0, target_y=50.0),
            ControlPoint("3", pixel_x=25.0, pixel_y=100.0, target_x=0.0, target_y=100.0),
        ]
        with pytest.raises(ValueError, match="коллинеарн"):
            GeoreferenceService.solve_affine(pts, crs="EPSG:3857")

    def test_reject_collinear_points_diagonal(self):
        """Отказ при коллинеарных точках (диагональ y = 2x)."""
        pts = [
            ControlPoint("1", pixel_x=10.0, pixel_y=20.0, target_x=100.0, target_y=200.0),
            ControlPoint("2", pixel_x=20.0, pixel_y=40.0, target_x=200.0, target_y=400.0),
            ControlPoint("3", pixel_x=30.0, pixel_y=60.0, target_x=300.0, target_y=600.0),
        ]
        with pytest.raises(ValueError, match="коллинеарн"):
            GeoreferenceService.solve_affine(pts, crs="EPSG:3857")

    def test_reject_duplicate_pixel_coordinates(self):
        """Отказ при наличии совпадающих пиксельных координат."""
        pts = [
            ControlPoint("1", pixel_x=10.0, pixel_y=10.0, target_x=0.0, target_y=0.0),
            ControlPoint("2", pixel_x=10.0, pixel_y=10.0, target_x=50.0, target_y=50.0),
            ControlPoint("3", pixel_x=20.0, pixel_y=30.0, target_x=100.0, target_y=100.0),
        ]
        with pytest.raises(ValueError, match="одинаковые координаты"):
            GeoreferenceService.solve_affine(pts, crs="EPSG:3857")

    def test_reject_duplicate_target_coordinates(self):
        """Отказ при наличии совпадающих целевых координат."""
        pts = [
            ControlPoint("1", pixel_x=10.0, pixel_y=10.0, target_x=500.0, target_y=500.0),
            ControlPoint("2", pixel_x=20.0, pixel_y=10.0, target_x=500.0, target_y=500.0),
            ControlPoint("3", pixel_x=10.0, pixel_y=20.0, target_x=1000.0, target_y=1000.0),
        ]
        with pytest.raises(ValueError, match="одинаковые целевые"):
            GeoreferenceService.solve_affine(pts, crs="EPSG:3857")

    def test_disabled_points_ignored(self):
        """Отключенные точки (enabled=False) исключаются из расчета трансформации."""
        pts = [
            ControlPoint("1", pixel_x=0.0, pixel_y=0.0, target_x=100.0, target_y=500.0),
            ControlPoint("2", pixel_x=10.0, pixel_y=0.0, target_x=120.0, target_y=500.0),
            ControlPoint("3", pixel_x=0.0, pixel_y=10.0, target_x=100.0, target_y=470.0),
            # 4-я точка сильно искажена, но отключена
            ControlPoint("4", pixel_x=100.0, pixel_y=100.0, target_x=999999.0, target_y=999999.0, enabled=False),
        ]

        transform, updated_pts, rmse = GeoreferenceService.solve_affine(pts, crs="EPSG:3857")
        a, b, c, d, e, f = transform
        assert pytest.approx(a, rel=1e-6) == 2.0
        assert pytest.approx(e, rel=1e-6) == -3.0
        assert pytest.approx(rmse, abs=1e-5) == 0.0
        assert updated_pts[3].residual_total is None

    def test_geodesic_residuals_in_meters_for_wgs84(self):
        """Для EPSG:4326 невязки и RMSE вычисляются в метрах (геодезическое расстояние)."""
        # Москва: ~55.75 N, 37.61 E. 1 секунда дуги долготы ~17.5 м, широты ~30.9 м
        pts = [
            ControlPoint("1", pixel_x=0.0, pixel_y=0.0, target_x=37.6173, target_y=55.7558),
            ControlPoint("2", pixel_x=100.0, pixel_y=0.0, target_x=37.6273, target_y=55.7558),
            ControlPoint("3", pixel_x=0.0, pixel_y=100.0, target_x=37.6173, target_y=55.7458),
            # 4-я точка смещена на 0.0001 градуса (~6-11 метров)
            ControlPoint("4", pixel_x=100.0, pixel_y=100.0, target_x=37.6273, target_y=55.7457),
        ]

        transform, updated_pts, rmse = GeoreferenceService.solve_affine(pts, crs="EPSG:4326")
        assert len(transform) == 6
        # RMSE должен быть в метрах, порядка нескольких метров, а не в градусах (0.0000...)
        assert rmse > 1.0  # Несколько метров
        assert rmse < 50.0  # Разумный предел в метрах

    def test_exceeding_max_points_limit(self):
        """Отказ при превышении максимального лимита контрольных точек (500)."""
        pts = [ControlPoint(str(i), pixel_x=float(i), pixel_y=float(i * 2), target_x=float(i), target_y=float(i)) for i in range(501)]
        with pytest.raises(ValueError, match="Превышен лимит"):
            GeoreferenceService.solve_affine(pts, crs="EPSG:3857")
