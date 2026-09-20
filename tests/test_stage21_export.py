"""Тесты экспорта геопривязанных растровых изображений в форматы PNG/JPEG (Stage 21)."""

from pathlib import Path
from PIL import Image
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication
import pytest

from rme_mapper.exporters.image_export_service import ImageExportService
from rme_mapper.exporters.map_renderer import MapRenderer
from rme_mapper.exporters.models import ImageExportOptions
from rme_mapper.models.map_point import MapPoint


@pytest.fixture(scope="session")
def qapp():
    """Фикстура для инициализации QApplication."""
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


@pytest.fixture
def sample_raster_for_export(tmp_path: Path) -> Path:
    p = tmp_path / "export_base.png"
    # Создаем изображение 400x300 с узнаваемым цветом
    img = Image.new("RGBA", (400, 300), color=(50, 150, 250, 255))
    img.save(p, format="PNG")
    return p


class TestGeoreferencedImageExport:
    """Тестирование рендеринга и экспорта геопривязанных растров в PNG/JPEG."""

    def test_render_map_with_raster_affine(self, qapp, sample_raster_for_export: Path):
        """Рендеринг карты с геопривязанным растром и точками через MapRenderer."""
        # Растр 400x300, привязан в EPSG:3857: X от 0 до 4000, Y от 0 до 3000
        affine = (10.0, 0.0, 0.0, 0.0, -10.0, 3000.0)
        target_extent = (0.0, 0.0, 4000.0, 3000.0)

        pt = MapPoint(
            id="p1",
            name="Center Point",
            latitude=1500.0,
            longitude=2000.0,
            source_crs="EPSG:3857",
        )

        options = ImageExportOptions(
            file_path="dummy.png",
            format="PNG",
            width_px=800,
            height_px=600,
            include_points=True,
            include_grid=False,
        )

        qimage = MapRenderer.render_map(
            options=options,
            active_crs="EPSG:3857",
            target_extent=target_extent,
            points=[pt],
            raster_source=sample_raster_for_export,
            raster_affine=affine,
            is_raster_visible=True,
        )

        assert not qimage.isNull()
        assert qimage.width() == 800
        assert qimage.height() == 600

    def test_export_image_service_png_and_jpeg(self, qapp, tmp_path: Path, sample_raster_for_export: Path):
        """Экспорт через ImageExportService в PNG и JPEG."""
        affine = (5.0, 0.0, 100.0, 0.0, -5.0, 1000.0)
        target_extent = (100.0, 0.0, 2100.0, 1000.0)

        # 1. Экспорт в PNG
        out_png = tmp_path / "exported_map.png"
        opts_png = ImageExportOptions(
            file_path=str(out_png),
            format="PNG",
            width_px=1920,
            height_px=1080,
            include_points=True,
        )
        saved_png = ImageExportService.export_image(
            options=opts_png,
            active_crs="EPSG:3857",
            target_extent=target_extent,
            raster_source=sample_raster_for_export,
            raster_affine=affine,
        )
        assert saved_png.exists()
        assert saved_png.stat().st_size > 0

        # 2. Экспорт в JPEG 4K
        out_jpg = tmp_path / "exported_map_4k.jpg"
        opts_jpg = ImageExportOptions(
            file_path=str(out_jpg),
            format="JPEG",
            width_px=3840,
            height_px=2160,
            jpeg_quality=92,
            include_points=True,
        )
        saved_jpg = ImageExportService.export_image(
            options=opts_jpg,
            active_crs="EPSG:3857",
            target_extent=target_extent,
            raster_source=sample_raster_for_export,
            raster_affine=affine,
        )
        assert saved_jpg.exists()
        assert saved_jpg.stat().st_size > 0
