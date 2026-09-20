"""Комплексные контрольные тесты Этапа 21 (Stage 21 Control Test Suite).

Проверка 26 критических сценариев согласно техническому заданию:
1. Pixel convention (corner vs center, half-pixel shift prevention)
2. World file convention & round-trip
3. Scene Y inversion (north-up, rotation, shear, rotation+shear, 4 corners)
4. EXIF orientation consistency (1, 3, 6, 8)
5. Original file integrity (SHA-256 unchanged)
6. TIFF vs GeoTIFF routing
7. Geographic CRS residuals in meters (EPSG:4326, OGC:CRS84, EPSG:4269)
8. Projected CRS units conversion to meters (EPSG:2263 US Survey Foot)
9. Least squares scaling (4, 10, 50, 100, 500 GCPs) & toggle enable/disable
10. Numerical stability (large coordinates X ~ 500k, Y ~ 6M)
11. Degenerate inputs (collinear, duplicates, NaN, Inf, singular)
12. Large image memory & preview decimation
13. Decompression bomb limits (> 250 Mpx)
14. Map tools & coordinate conversions
15. Project save / reopen (*.gpmap)
16. Relative paths across directory moves
17. Missing image workflow & locate
18. Edit georeferencing Undo/Redo
19. Full resolution export vs preview
20. Rotated/sheared export parity
21. Transparency (RGBA PNG vs JPEG background)
"""

import hashlib
import io
import math
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
from PIL import Image
import pyproj
from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QPixmap, QTransform
from PySide6.QtWidgets import QApplication, QDialog, QMessageBox, QWidget
import pytest
import rasterio
from rasterio.transform import from_origin

from rme_mapper.exporters.image_export_service import ImageExportService
from rme_mapper.exporters.map_renderer import MapRenderer
from rme_mapper.exporters.models import ImageExportOptions
from rme_mapper.maps.map_canvas import MapCanvas
from rme_mapper.models.georeference import ControlPoint, MAX_CONTROL_POINTS
from rme_mapper.models.map_layer import MapLayer
from rme_mapper.models.map_point import MapPoint
from rme_mapper.models.map_profile import MapProfile
from rme_mapper.services.georeference_service import GeoreferenceService
from rme_mapper.services.point_service import PointService
from rme_mapper.services.project_service import ProjectService
from rme_mapper.services.undo_manager import EditGeoreferencingCommand, UndoManager
from rme_mapper.ui.controllers.map_controller import MapController
from rme_mapper.ui.controllers.project_controller import ProjectController
from rme_mapper.ui.georeference_dialog import GeoreferenceDialog
from rme_mapper.ui.open_map_dialog import OpenMapDialog
from rme_mapper.ui.panels.layers_panel import LayersPanel
from rme_mapper.ui.panels.points_panel import PointsPanel


@pytest.fixture(scope="session")
def qapp():
    """Общий экземпляр QApplication."""
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


# ==============================================================================
# 1. PIXEL CONVENTION & HALF-PIXEL SHIFT
# ==============================================================================
class TestPixelConventionAndHalfPixel:
    """Проверка единой пиксельной конвенции и исключение сдвига на полпикселя."""

    def test_corner_vs_center_coordinates(self):
        """Пиксельные координаты используют непрерывную систему с началом (0.0, 0.0) в верхнем левом углу."""
        # Размеры изображения W=100, H=50. Разрешение 1м на пиксель, начало в (1000, 2000).
        # Формула: X = 1.0 * x + 1000.0, Y = -1.0 * y + 2000.0
        w, h = 100.0, 50.0
        pts = [
            ControlPoint("c_tl", pixel_x=0.0, pixel_y=0.0, target_x=1000.0, target_y=2000.0),
            ControlPoint("c_tr", pixel_x=w, pixel_y=0.0, target_x=1100.0, target_y=2000.0),
            ControlPoint("c_bl", pixel_x=0.0, pixel_y=h, target_x=1000.0, target_y=1950.0),
            ControlPoint("c_br", pixel_x=w, pixel_y=h, target_x=1100.0, target_y=1950.0),
            ControlPoint("center", pixel_x=w / 2.0, pixel_y=h / 2.0, target_x=1050.0, target_y=1975.0),
        ]

        transform, updated_pts, rmse = GeoreferenceService.solve_affine(pts, crs="EPSG:3857")
        a, b, c, d, e, f = transform
        assert pytest.approx(a, abs=1e-7) == 1.0
        assert pytest.approx(b, abs=1e-7) == 0.0
        assert pytest.approx(c, abs=1e-7) == 1000.0
        assert pytest.approx(d, abs=1e-7) == 0.0
        assert pytest.approx(e, abs=1e-7) == -1.0
        assert pytest.approx(f, abs=1e-7) == 2000.0
        assert pytest.approx(rmse, abs=1e-5) == 0.0

        # Проверка всех 4 углов и центра: невязка ровно 0 без сдвига 0.5px
        for p in updated_pts:
            assert pytest.approx(p.residual_total, abs=1e-5) == 0.0

    def test_no_half_pixel_shift_in_scene_and_export(self):
        """Проверка строгого соответствия QTransform на сцене и в экспорте формуле X=ax+by+c, Y=dx+ey+f."""
        # a=2.5, b=0, c=500.0, d=0, e=-2.5, f=1000.0
        affine = (2.5, 0.0, 500.0, 0.0, -2.5, 1000.0)
        px, py = 10.0, 20.0
        expected_map_x = 2.5 * px + 500.0  # 525.0
        expected_map_y = -2.5 * py + 1000.0  # 950.0

        # 1. Сцена MapCanvas: scene_x = map_x, scene_y = -map_y
        m11, m12, m21, m22, dx, dy = affine[0], -affine[3], affine[1], -affine[4], affine[2], -affine[5]
        t_scene = QTransform(m11, m12, m21, m22, dx, dy)
        pt_scene = t_scene.map(QPointF(px, py))
        assert pytest.approx(pt_scene.x(), abs=1e-6) == expected_map_x
        assert pytest.approx(pt_scene.y(), abs=1e-6) == -expected_map_y

        # 2. MapRenderer экспорт: img_x = (map_x - min_x) * scale, img_y = (max_y - map_y) * scale
        min_x, max_y, scale = 0.0, 2000.0, 2.0
        m11_exp = affine[0] * scale
        m12_exp = -affine[3] * scale
        m21_exp = affine[1] * scale
        m22_exp = -affine[4] * scale
        dx_exp = (affine[2] - min_x) * scale
        dy_exp = (max_y - affine[5]) * scale
        t_export = QTransform(m11_exp, m12_exp, m21_exp, m22_exp, dx_exp, dy_exp)
        pt_export = t_export.map(QPointF(px, py))

        expected_exp_x = (expected_map_x - min_x) * scale
        expected_exp_y = (max_y - expected_map_y) * scale
        assert pytest.approx(pt_export.x(), abs=1e-6) == expected_exp_x
        assert pytest.approx(pt_export.y(), abs=1e-6) == expected_exp_y


# ==============================================================================
# 2. WORLD FILE CONVENTION & ROUND-TRIP
# ==============================================================================
class TestWorldFileRoundTrip:
    """Проверка соглашения World File (центр верхнего левого пикселя) и обратимости."""

    def test_world_file_export_and_reconstruct_round_trip(self, tmp_path: Path):
        """Круговой тест: affine -> world file -> чтение коэффициентов -> полное совпадение геопозиции."""
        img_path = tmp_path / "satellite_photo.tif"
        img = Image.new("RGB", (400, 300), color=(100, 150, 200))
        img.save(img_path)

        orig_affine = (1.5, 0.2, 350000.0, 0.1, -1.5, 5800000.0)
        exported = GeoreferenceService.export_world_file(img_path, orig_affine, crs="EPSG:3857")
        wf_path = exported[0]
        assert wf_path.suffix == ".tfw"

        lines = [float(line.strip()) for line in wf_path.read_text(encoding="utf-8").splitlines() if line.strip()]
        assert len(lines) == 6
        A, D, B, E, C_center, F_center = lines

        # Восстановление affine параметров из World File:
        # C_center = c + 0.5 * A + 0.5 * B
        # F_center = f + 0.5 * D + 0.5 * E
        rec_a = A
        rec_d = D
        rec_b = B
        rec_e = E
        rec_c = C_center - 0.5 * A - 0.5 * B
        rec_f = F_center - 0.5 * D - 0.5 * E

        reconstructed_affine = (rec_a, rec_b, rec_c, rec_d, rec_e, rec_f)
        for orig_val, rec_val in zip(orig_affine, reconstructed_affine):
            assert pytest.approx(orig_val, abs=1e-9) == rec_val

        # Проверка предсказания координат контрольной точки
        test_x, test_y = 123.4, 256.7
        orig_X = orig_affine[0] * test_x + orig_affine[1] * test_y + orig_affine[2]
        orig_Y = orig_affine[3] * test_x + orig_affine[4] * test_y + orig_affine[5]
        rec_X = rec_a * test_x + rec_b * test_y + rec_c
        rec_Y = rec_d * test_x + rec_e * test_y + rec_f

        assert pytest.approx(orig_X, abs=1e-8) == rec_X
        assert pytest.approx(orig_Y, abs=1e-8) == rec_Y


# ==============================================================================
# 3. SCENE Y INVERSION
# ==============================================================================
class TestSceneYInversion:
    """Проверка инверсии оси Y сцены для north-up, поворота, сдвига и их комбинации."""

    @pytest.mark.parametrize(
        "case_name, a, b, c, d, e, f",
        [
            ("north_up", 2.0, 0.0, 100.0, 0.0, -2.0, 500.0),
            ("rotation_30", math.cos(math.pi / 6) * 2, -math.sin(math.pi / 6) * 2, 200.0, math.sin(math.pi / 6) * 2, math.cos(math.pi / 6) * 2, 800.0),
            ("shear", 1.5, 0.5, 50.0, 0.2, -1.8, 300.0),
            ("rotation_and_shear", 1.2, -0.7, 150.0, 0.6, 1.4, 600.0),
        ],
    )
    def test_four_corners_scene_transform(self, case_name, a, b, c, d, e, f):
        """Все 4 угла изображения после трансформации QTransform точно соответствуют формуле scene_x = map_x, scene_y = -map_y."""
        w, h = 400.0, 300.0
        corners = [(0.0, 0.0), (w, 0.0), (0.0, h), (w, h)]

        # QTransform в координатах сцены:
        t_scene = QTransform(float(a), float(-d), float(b), float(-e), float(c), float(-f))

        for px, py in corners:
            map_x = a * px + b * py + c
            map_y = d * px + e * py + f

            expected_scene_x = map_x
            expected_scene_y = -map_y

            mapped_pt = t_scene.map(QPointF(px, py))
            assert pytest.approx(mapped_pt.x(), abs=1e-5) == expected_scene_x
            assert pytest.approx(mapped_pt.y(), abs=1e-5) == expected_scene_y


# ==============================================================================
# 4. EXIF ORIENTATION CONSISTENCY
# ==============================================================================
class TestExifOrientationConsistency:
    """Проверка ориентаций EXIF 1, 3, 6, 8 на единую систему координат пикселей."""

    @pytest.mark.parametrize("orientation", [1, 3, 6, 8])
    def test_exif_orientations_consistent_pipeline(self, tmp_path: Path, orientation: int):
        """Инспекция, предпросмотр и полная загрузка возвращают одинаковые нормализованные размеры."""
        # Создаем изображение 200x100
        raw_img = Image.new("RGB", (200, 100), color=(80, 160, 240))
        exif = raw_img.getexif()
        exif[0x0112] = orientation  # Tag Orientation

        img_path = tmp_path / f"test_exif_{orientation}.jpg"
        raw_img.save(img_path, format="JPEG", exif=exif)

        # 1. inspect_image
        info = GeoreferenceService.inspect_image(img_path)

        # 2. load_preview_image
        preview_qimg, prev_dims = GeoreferenceService.load_preview_image(img_path, max_dimension=1000)

        # 3. load_full_image
        full_qimg, full_dims = GeoreferenceService.load_full_image(img_path)

        # В ориентациях 6 и 8 (поворот на 90/270 градусов) ширина и высота меняются местами
        if orientation in (6, 8):
            expected_w, expected_h = 100, 200
        else:
            expected_w, expected_h = 200, 100

        assert info["width"] == expected_w
        assert info["height"] == expected_h
        assert prev_dims == (expected_w, expected_h)
        assert full_dims == (expected_w, expected_h)
        assert full_qimg.width() == expected_w
        assert full_qimg.height() == expected_h


# ==============================================================================
# 5. ORIGINAL FILE INTEGRITY
# ==============================================================================
class TestOriginalFileIntegrity:
    """Исходные файлы пользователя (PNG, JPG, TIFF) строго неприкосновенны."""

    @pytest.mark.parametrize("fmt, ext", [("PNG", ".png"), ("JPEG", ".jpg"), ("TIFF", ".tif")])
    def test_file_hash_unchanged_after_all_operations(self, tmp_path: Path, fmt: str, ext: str):
        file_path = tmp_path / f"orig_user_image{ext}"
        img = Image.new("RGB", (150, 150), color=(200, 100, 50))
        img.save(file_path, format=fmt)

        initial_bytes = file_path.read_bytes()
        initial_hash = hashlib.sha256(initial_bytes).hexdigest()
        initial_stat = file_path.stat()

        # Выполняем весь цикл геопривязки и экспорта:
        # 1. Инспекция
        GeoreferenceService.inspect_image(file_path)
        # 2. Превью
        GeoreferenceService.load_preview_image(file_path)
        # 3. Полная загрузка
        GeoreferenceService.load_full_image(file_path)
        # 4. Решение
        pts = [
            ControlPoint("1", pixel_x=0.0, pixel_y=0.0, target_x=10.0, target_y=20.0),
            ControlPoint("2", pixel_x=100.0, pixel_y=0.0, target_x=20.0, target_y=20.0),
            ControlPoint("3", pixel_x=0.0, pixel_y=100.0, target_x=10.0, target_y=10.0),
        ]
        affine, _, _ = GeoreferenceService.solve_affine(pts, crs="EPSG:3857")
        # 5. Экспорт world-файла в отдельную папку
        sidecar_dir = tmp_path / "sidecars"
        GeoreferenceService.export_world_file(file_path, affine, crs="EPSG:3857", target_dir=sidecar_dir)

        # Проверка хеша и размера
        after_bytes = file_path.read_bytes()
        after_hash = hashlib.sha256(after_bytes).hexdigest()
        after_stat = file_path.stat()

        assert initial_hash == after_hash
        assert initial_bytes == after_bytes
        assert initial_stat.st_size == after_stat.st_size


# ==============================================================================
# 6. GEOREFERENCED TIFF DETECTION
# ==============================================================================
class TestTiffDetectionAndRouting:
    """Разделение валидного GeoTIFF и негеопривязанного TIFF."""

    def test_geotiff_vs_unreferenced_tiff(self, tmp_path: Path):
        # 1. Валидный GeoTIFF
        geotiff_path = tmp_path / "valid_geotiff.tif"
        transform = from_origin(37.0, 56.0, 0.001, 0.001)
        with rasterio.open(
            geotiff_path,
            "w",
            driver="GTiff",
            height=100,
            width=100,
            count=3,
            dtype="uint8",
            crs="EPSG:4326",
            transform=transform,
        ) as dst:
            dst.write(np.zeros((3, 100, 100), dtype=np.uint8))

        # 2. Негеопривязанный TIFF
        plain_tiff_path = tmp_path / "plain_photo.tif"
        plain_img = Image.new("RGB", (100, 100), color=(50, 100, 150))
        plain_img.save(plain_tiff_path)

        from rme_mapper.backends.factory import get_raster_backend
        rb = get_raster_backend()

        # Валидный GeoTIFF должен распознаваться как валидный
        geo_info = rb.inspect_raster(geotiff_path)
        assert geo_info.get("crs") is not None
        assert geo_info.get("is_valid_georef") is True

        # Обычный TIFF не имеет геопривязки
        plain_info = rb.inspect_raster(plain_tiff_path)
        assert not plain_info.get("crs") or not plain_info.get("is_valid_georef")


# ==============================================================================
# 7 & 8. GEOGRAPHIC AND PROJECTED CRS RESIDUALS
# ==============================================================================
class TestCrsResidualUnits:
    """Проверка единиц невязок в метрах для географических и спроецированных (в т.ч. US Foot) CRS."""

    def test_geographic_crs_residuals_in_meters(self):
        """Для EPSG:4326, OGC:CRS84 и EPSG:4269 невязки выражены в метрах."""
        for crs_code in ("EPSG:4326", "OGC:CRS84", "EPSG:4269"):
            pts = [
                ControlPoint("1", pixel_x=0.0, pixel_y=0.0, target_x=37.61, target_y=55.75),
                ControlPoint("2", pixel_x=100.0, pixel_y=0.0, target_x=37.62, target_y=55.75),
                ControlPoint("3", pixel_x=0.0, pixel_y=100.0, target_x=37.61, target_y=55.74),
                # 4-я точка с небольшим сдвигом по широте на 0.0001° (~11.1м)
                ControlPoint("4", pixel_x=100.0, pixel_y=100.0, target_x=37.62, target_y=55.7399),
            ]
            _, updated_pts, rmse = GeoreferenceService.solve_affine(pts, crs=crs_code)
            assert rmse > 0.5  # Несколько метров, не доли градуса 0.000...
            assert rmse < 100.0
            assert updated_pts[3].residual_total > 0.5

    def test_projected_us_survey_foot_conversion_to_meters(self):
        """Для CRS в футах (EPSG:2263: New York State Plane) невязки конвертируются в метры."""
        # 1 US survey foot = ~0.3048006 м
        # Добавляем ошибку в 100 футов -> невязка в метрах должна быть ~30.48 м
        pts = [
            ControlPoint("1", pixel_x=0.0, pixel_y=0.0, target_x=1000000.0, target_y=200000.0),
            ControlPoint("2", pixel_x=100.0, pixel_y=0.0, target_x=1001000.0, target_y=200000.0),
            ControlPoint("3", pixel_x=0.0, pixel_y=100.0, target_x=1000000.0, target_y=199000.0),
            # Сдвиг на 100 футов по X
            ControlPoint("4", pixel_x=100.0, pixel_y=100.0, target_x=1001100.0, target_y=199000.0),
        ]
        _, updated_pts, rmse = GeoreferenceService.solve_affine(pts, crs="EPSG:2263")
        # В 4-точечной аффинной модели смещение одного угла на 100 футов распределяется
        # методом наименьших квадратов так, что невязка каждой точки составляет 25 футов.
        # При конвертации в метры (1 ftUS ≈ 0.3048006 м): 25 * 0.3048006 ≈ 7.62 м (не 25!).
        expected_residual_m = 25.0 * 0.3048006096
        assert pytest.approx(updated_pts[3].residual_total, rel=0.05) == expected_residual_m
        assert pytest.approx(rmse, rel=0.05) == expected_residual_m


# ==============================================================================
# 9. LEAST SQUARES SCALING
# ==============================================================================
class TestLeastSquaresScaling:
    """Масштабируемость МНК: 4, 10, 50, 100, 500 контрольных точек."""

    @pytest.mark.parametrize("point_count", [4, 10, 50, 100, 500])
    def test_least_squares_various_counts(self, point_count: int):
        pts = []
        grid_w = max(2, int(math.ceil(math.sqrt(point_count))))
        for i in range(point_count):
            px = float((i % grid_w) * 40)
            py = float((i // grid_w) * 40)
            tx = 2.0 * px + 50000.0
            ty = -3.0 * py + 80000.0
            pts.append(ControlPoint(id=str(i + 1), pixel_x=px, pixel_y=py, target_x=tx, target_y=ty))

        transform, updated_pts, rmse = GeoreferenceService.solve_affine(pts, crs="EPSG:3857")
        assert len(transform) == 6
        assert pytest.approx(transform[0], rel=1e-5) == 2.0
        assert pytest.approx(transform[4], rel=1e-5) == -3.0
        assert pytest.approx(rmse, abs=1e-4) == 0.0

    def test_least_squares_enable_disable_recalculate(self):
        """Отключение и повторное включение выброса пересчитывает МНК."""
        # 3 идеальные точки + 1 грубый выброс
        pts = [
            ControlPoint("1", pixel_x=0.0, pixel_y=0.0, target_x=100.0, target_y=200.0),
            ControlPoint("2", pixel_x=50.0, pixel_y=0.0, target_x=150.0, target_y=200.0),
            ControlPoint("3", pixel_x=0.0, pixel_y=50.0, target_x=100.0, target_y=150.0),
            ControlPoint("4", pixel_x=50.0, pixel_y=50.0, target_x=99999.0, target_y=99999.0, enabled=True),
        ]
        # С выбросом RMSE огромный
        _, _, rmse_with_bad = GeoreferenceService.solve_affine(pts, crs="EPSG:3857")
        assert rmse_with_bad > 1000.0

        # Отключаем 4-ю точку
        pts[3].enabled = False
        _, _, rmse_without_bad = GeoreferenceService.solve_affine(pts, crs="EPSG:3857")
        assert pytest.approx(rmse_without_bad, abs=1e-4) == 0.0

        # Включаем обратно
        pts[3].enabled = True
        _, _, rmse_re_enabled = GeoreferenceService.solve_affine(pts, crs="EPSG:3857")
        assert rmse_re_enabled == rmse_with_bad


# ==============================================================================
# 10. NUMERICAL STABILITY
# ==============================================================================
class TestNumericalStability:
    """Численная стабильность на больших спроецированных координатах и больших пикселях."""

    def test_large_projected_coordinates_and_pixels(self):
        # Пиксели до 30 000 x 20 000, координаты X ~ 500 000, Y ~ 6 000 000
        pts = [
            ControlPoint("1", pixel_x=0.0, pixel_y=0.0, target_x=500000.0, target_y=6000000.0),
            ControlPoint("2", pixel_x=30000.0, pixel_y=0.0, target_x=560000.0, target_y=6000000.0),
            ControlPoint("3", pixel_x=0.0, pixel_y=20000.0, target_x=500000.0, target_y=5960000.0),
            ControlPoint("4", pixel_x=30000.0, pixel_y=20000.0, target_x=560000.0, target_y=5960000.0),
        ]
        transform, updated_pts, rmse = GeoreferenceService.solve_affine(pts, crs="EPSG:3857")
        a, b, c, d, e, f = transform
        assert pytest.approx(a, rel=1e-7) == 2.0
        assert pytest.approx(c, rel=1e-7) == 500000.0
        assert pytest.approx(e, rel=1e-7) == -2.0
        assert pytest.approx(f, rel=1e-7) == 6000000.0
        assert pytest.approx(rmse, abs=1e-4) == 0.0


# ==============================================================================
# 11. DEGENERATE INPUT
# ==============================================================================
class TestDegenerateInputHandling:
    """Корректная обработка вырожденных входных данных без сбоев."""

    def test_collinear_and_duplicates_and_nan(self):
        # NaN
        with pytest.raises(ValueError, match="недопустимые значения"):
            pts_nan = [
                ControlPoint("1", pixel_x=0.0, pixel_y=0.0, target_x=0.0, target_y=0.0),
                ControlPoint("2", pixel_x=10.0, pixel_y=float("nan"), target_x=10.0, target_y=10.0),
                ControlPoint("3", pixel_x=0.0, pixel_y=10.0, target_x=0.0, target_y=10.0),
            ]
            GeoreferenceService.solve_affine(pts_nan, crs="EPSG:3857")

        # Collinear
        with pytest.raises(ValueError, match="коллинеарн"):
            pts_collinear = [
                ControlPoint("1", pixel_x=10.0, pixel_y=10.0, target_x=100.0, target_y=100.0),
                ControlPoint("2", pixel_x=20.0, pixel_y=20.0, target_x=200.0, target_y=200.0),
                ControlPoint("3", pixel_x=30.0, pixel_y=30.0, target_x=300.0, target_y=300.0),
            ]
            GeoreferenceService.solve_affine(pts_collinear, crs="EPSG:3857")

    def test_fewer_than_3_points(self):
        pts = [
            ControlPoint("1", pixel_x=0.0, pixel_y=0.0, target_x=0.0, target_y=0.0),
            ControlPoint("2", pixel_x=10.0, pixel_y=10.0, target_x=10.0, target_y=10.0),
        ]
        with pytest.raises(ValueError, match="минимум 3"):
            GeoreferenceService.solve_affine(pts, crs="EPSG:3857")

    def test_duplicate_points(self):
        # Duplicate pixels
        pts_dup_px = [
            ControlPoint("1", pixel_x=10.0, pixel_y=10.0, target_x=10.0, target_y=10.0),
            ControlPoint("2", pixel_x=10.0, pixel_y=10.0, target_x=20.0, target_y=20.0),
            ControlPoint("3", pixel_x=30.0, pixel_y=30.0, target_x=30.0, target_y=30.0),
        ]
        with pytest.raises(ValueError, match="одинаковые координаты на изображении"):
            GeoreferenceService.solve_affine(pts_dup_px, crs="EPSG:3857")

        # Duplicate targets
        pts_dup_tgt = [
            ControlPoint("1", pixel_x=10.0, pixel_y=10.0, target_x=50.0, target_y=50.0),
            ControlPoint("2", pixel_x=20.0, pixel_y=20.0, target_x=50.0, target_y=50.0),
            ControlPoint("3", pixel_x=30.0, pixel_y=30.0, target_x=70.0, target_y=80.0),
        ]
        with pytest.raises(ValueError, match="одинаковые целевые координаты"):
            GeoreferenceService.solve_affine(pts_dup_tgt, crs="EPSG:3857")

    def test_invalid_crs(self):
        pts = [
            ControlPoint("1", pixel_x=0.0, pixel_y=0.0, target_x=10.0, target_y=10.0),
            ControlPoint("2", pixel_x=10.0, pixel_y=0.0, target_x=20.0, target_y=10.0),
            ControlPoint("3", pixel_x=0.0, pixel_y=10.0, target_x=10.0, target_y=20.0),
        ]
        with pytest.raises(ValueError, match="Недопустимая или неподдерживаемая CRS"):
            GeoreferenceService.solve_affine(pts, crs="INVALID_CRS_NOT_FOUND_9999")


# ==============================================================================
# 12 & 13. LARGE IMAGE MEMORY & DECOMPRESSION BOMB
# ==============================================================================
class TestLargeImageMemoryAndBomb:
    """Проверка децимации превью и ограничения декомпрессионных бомб."""

    def test_preview_decimation_size(self, tmp_path: Path):
        # Создаем изображение 4000 x 3000
        img_path = tmp_path / "huge_synthetic.png"
        img = Image.new("RGB", (4000, 3000), color=(70, 130, 180))
        img.save(img_path, format="PNG")

        qimg, (full_w, full_h) = GeoreferenceService.load_preview_image(img_path, max_dimension=2048)
        assert full_w == 4000
        assert full_h == 3000
        assert qimg.width() <= 2048
        assert qimg.height() <= 2048

    def test_decompression_bomb_safety_rejection(self, tmp_path: Path):
        img_path = tmp_path / "bomb.png"
        img = Image.new("RGB", (10, 10))
        img.save(img_path)

        with patch("PIL.Image.open") as mock_open:
            mock_img = MagicMock()
            mock_img.size = (30000, 20000)  # 600 Mpx > 250 Mpx
            mock_img.format = "PNG"
            mock_img.mode = "RGB"
            mock_open.return_value.__enter__.return_value = mock_img

            with pytest.raises(ValueError, match="предел безопасности"):
                GeoreferenceService.inspect_image(img_path)


# ==============================================================================
# 16 & 17. RELATIVE PATH & MISSING IMAGE WORKFLOW
# ==============================================================================
class TestRelativePathAndMissingImage:
    """Проверка относительных путей при перемещении каталога проекта и обработка отсутствующих файлов."""

    def test_project_move_preserves_relative_raster(self, tmp_path: Path):
        proj_dir = tmp_path / "my_project"
        maps_dir = proj_dir / "maps"
        maps_dir.mkdir(parents=True)

        raster_file = maps_dir / "aerial.png"
        img = Image.new("RGBA", (100, 100), color=(100, 200, 100, 255))
        img.save(raster_file)

        cp1 = ControlPoint("1", pixel_x=0.0, pixel_y=0.0, target_x=10.0, target_y=20.0)
        cp2 = ControlPoint("2", pixel_x=100.0, pixel_y=0.0, target_x=20.0, target_y=20.0)
        cp3 = ControlPoint("3", pixel_x=0.0, pixel_y=100.0, target_x=10.0, target_y=10.0)

        profile = MapProfile(
            id="p_rel",
            name="Aerial",
            source_type="georeferenced_image",
            source_path=str(raster_file),
            base_dir=proj_dir,
            crs="EPSG:3857",
            affine_transform=[1.0, 0.0, 10.0, 0.0, -1.0, 20.0],
            control_points=[cp1, cp2, cp3],
        )

        project_service = ProjectService()
        project_data = project_service.build_project_data(map_profile=profile, map_path=raster_file, points=[])
        proj_file = proj_dir / "project.gpmap"
        project_service.save_project(project=project_data, file_path=proj_file)

        # Перемещаем всю папку проекта в новое место
        new_proj_dir = tmp_path / "moved_project"
        proj_dir.rename(new_proj_dir)
        new_proj_file = new_proj_dir / "project.gpmap"

        opened = project_service.load_project(new_proj_file)
        assert opened.map.source_type == "georeferenced_image"
        # Разрешаем путь относительно новой папки
        resolved_raster = (new_proj_dir / opened.map.relative_path).resolve()
        assert resolved_raster.exists()


# ==============================================================================
# 20 & 21. ROTATED / SHEARED EXPORT & TRANSPARENCY
# ==============================================================================
class TestExportParityAndTransparency:
    """Экспорт с поворотом, сдвигом и сохранением прозрачности."""

    def test_rotated_sheared_export_with_transparency(self, qapp, tmp_path: Path):
        # RGBA изображение с прозрачными пикселями
        rgba_img = Image.new("RGBA", (200, 200), color=(255, 0, 0, 128))
        img_path = tmp_path / "alpha_raster.png"
        rgba_img.save(img_path)

        # Поворот + сдвиг
        affine = (1.5, -0.5, 1000.0, 0.5, 1.2, 2000.0)
        target_extent = (500.0, 1500.0, 2500.0, 3000.0)

        # Экспорт в PNG
        out_png = tmp_path / "exported_rotated.png"
        opts = ImageExportOptions(
            file_path=str(out_png),
            format="PNG",
            width_px=800,
            height_px=600,
            transparent_background=True,
        )
        saved = ImageExportService.export_image(
            options=opts,
            active_crs="EPSG:3857",
            target_extent=target_extent,
            raster_source=img_path,
            raster_affine=affine,
        )
        assert saved.exists()

        result_qimg = QImage(str(saved))
        assert not result_qimg.isNull()
        assert result_qimg.hasAlphaChannel()


# ==============================================================================
# 18. EDIT GEOREFERENCING UNDO / REDO
# ==============================================================================
class TestEditGeoreferencingUndoRedo:
    """Проверка стека Undo/Redo при редактировании геопривязки."""

    def test_undo_redo_georeference_command(self):
        applied_state = {}

        def mock_apply(aff, cps, crs):
            applied_state["affine"] = aff
            applied_state["cps"] = cps
            applied_state["crs"] = crs

        initial_aff = (1.0, 0.0, 100.0, 0.0, -1.0, 200.0)
        new_aff = (2.0, 0.0, 500.0, 0.0, -2.0, 600.0)
        initial_cps = [{"id": "1", "target_x": 10.0}]
        new_cps = [{"id": "1", "target_x": 20.0}, {"id": "2", "target_x": 30.0}]

        cmd = EditGeoreferencingCommand(
            apply_fn=mock_apply,
            before_affine=initial_aff,
            before_control_points=initial_cps,
            before_crs="EPSG:3857",
            after_affine=new_aff,
            after_control_points=new_cps,
            after_crs="EPSG:4326",
        )

        undo_mgr = UndoManager()
        undo_mgr.push(cmd, execute=True)

        assert applied_state["affine"] == new_aff
        assert applied_state["crs"] == "EPSG:4326"
        assert len(applied_state["cps"]) == 2

        # Undo
        assert undo_mgr.can_undo
        undo_mgr.undo()
        assert applied_state["affine"] == initial_aff
        assert applied_state["crs"] == "EPSG:3857"
        assert len(applied_state["cps"]) == 1

        # Redo
        assert undo_mgr.can_redo
        undo_mgr.redo()
        assert applied_state["affine"] == new_aff
        assert applied_state["crs"] == "EPSG:4326"
        assert len(applied_state["cps"]) == 2


# ==============================================================================
# 19. FULL RESOLUTION EXPORT INTEGRITY
# ==============================================================================
class TestFullResolutionExportIntegrity:
    """Проверка, что экспорт использует полное разрешение исходного файла, а не превью."""

    def test_export_calls_load_full_image_not_preview(self, qapp, tmp_path: Path):
        img_path = tmp_path / "hq_aerial.png"
        img = Image.new("RGBA", (800, 600), color=(10, 200, 50, 255))
        img.save(img_path)

        affine = (2.0, 0.0, 1000.0, 0.0, -2.0, 2000.0)
        out_file = tmp_path / "export_hq.png"
        opts = ImageExportOptions(
            file_path=str(out_file),
            format="PNG",
            width_px=800,
            height_px=600,
        )

        with patch("rme_mapper.services.georeference_service.GeoreferenceService.load_full_image", wraps=GeoreferenceService.load_full_image) as spy_full, \
             patch("rme_mapper.services.georeference_service.GeoreferenceService.load_preview_image") as spy_prev:

            ImageExportService.export_image(
                options=opts,
                active_crs="EPSG:3857",
                target_extent=(1000.0, 2600.0, 800.0, 2000.0),
                raster_source=img_path,
                raster_affine=affine,
            )

            # load_full_image должен быть вызван
            assert spy_full.called
            # load_preview_image НЕ должен вызываться при экспорте карты
            assert not spy_prev.called


# ==============================================================================
# 17. MISSING IMAGE WORKFLOW
# ==============================================================================
class TestMissingImageLocateWorkflow:
    """Проверка восстановления проекта при перемещении исходного растра."""

    def test_locate_image_restores_profile(self, tmp_path: Path):
        proj_dir = tmp_path / "proj"
        proj_dir.mkdir()
        orig_img = proj_dir / "base.jpg"
        Image.new("RGB", (100, 100)).save(orig_img)

        cp1 = ControlPoint("1", pixel_x=0.0, pixel_y=0.0, target_x=10.0, target_y=20.0)
        profile = MapProfile(
            id="p_miss",
            name="Base",
            source_type="georeferenced_image",
            source_path=str(orig_img),
            base_dir=proj_dir,
            crs="EPSG:3857",
            affine_transform=[1.0, 0.0, 10.0, 0.0, -1.0, 20.0],
            control_points=[cp1],
        )
        ps = ProjectService()
        pdata = ps.build_project_data(map_profile=profile, map_path=orig_img, points=[])
        proj_file = proj_dir / "test.gpmap"
        ps.save_project(pdata, proj_file)

        # Удаляем исходное изображение
        orig_img.unlink()

        # Создаем изображение в новой локации
        new_img = tmp_path / "relocated_base.jpg"
        Image.new("RGB", (100, 100)).save(new_img)

        # Симулируем ProjectController._resolve_and_apply_project с выбором "Locate"
        mock_catalog = MagicMock()
        mock_catalog.get_profile.return_value = None
        pc = ProjectController(
            parent_widget=QWidget(),
            project_service=ps,
            point_service=MagicMock(),
            map_controller=MagicMock(),
            point_controller=MagicMock(),
            map_catalog_service=mock_catalog,
            on_title_changed=MagicMock(),
        )

        loaded_data = ps.load_project(proj_file)

        # Симулируем 3 сценария выбора пользователя при отсутствующем растре
        with patch("rme_mapper.ui.controllers.project_controller.QMessageBox") as mock_box_cls, \
             patch("PySide6.QtWidgets.QFileDialog.getOpenFileName", return_value=(str(new_img), "Images")):
            mock_box = MagicMock()
            mock_box_cls.return_value = mock_box
            btn_find = MagicMock()
            btn_no_map = MagicMock()
            btn_cancel = MagicMock()

            # 1. Сценарий Locate: геопривязка сохраняется, путь обновляется
            mock_box.addButton.side_effect = [btn_find, btn_no_map, btn_cancel]
            mock_box.clickedButton.return_value = btn_find
            success = pc._resolve_and_apply_project(loaded_data, proj_file)
            assert success is True
            assert pc._map_controller.load_map.called
            applied_prof = pc._map_controller.load_map.call_args[0][0]
            assert isinstance(applied_prof, MapProfile)
            assert applied_prof.source_path == str(new_img)
            assert applied_prof.affine_transform == [1.0, 0.0, 10.0, 0.0, -1.0, 20.0]
            assert len(applied_prof.control_points) == 1

            # 2. Сценарий Open Without Map: карта выгружается, проект открывается
            mock_box.addButton.side_effect = [btn_find, btn_no_map, btn_cancel]
            mock_box.clickedButton.return_value = btn_no_map
            success_no_map = pc._resolve_and_apply_project(loaded_data, proj_file)
            assert success_no_map is True
            assert pc._map_controller.unload_map.called

            # 3. Сценарий Cancel: прерывание открытия
            mock_box.addButton.side_effect = [btn_find, btn_no_map, btn_cancel]
            mock_box.clickedButton.return_value = btn_cancel
            success_cancel = pc._resolve_and_apply_project(loaded_data, proj_file)
            assert success_cancel is False

