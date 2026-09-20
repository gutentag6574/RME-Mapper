"""Тесты безопасности обработки изображений и неразрушающего подхода (Stage 21)."""

import hashlib
from pathlib import Path
from unittest.mock import patch
from PIL import Image
from PySide6.QtGui import QImage
import pytest

from rme_mapper.services.georeference_service import GeoreferenceService


class TestImageSafetyAndNonDestructive:
    """Тестирование безопасности чтения растров и неразрушающего подхода к файлам пользователя."""

    @pytest.fixture
    def sample_png(self, tmp_path: Path) -> Path:
        """Создание валидного тестового PNG изображения."""
        img_path = tmp_path / "test_map.png"
        img = Image.new("RGBA", (200, 150), color=(100, 150, 200, 255))
        img.save(img_path, format="PNG")
        return img_path

    def test_non_destructive_philosophy(self, sample_png: Path):
        """Проверка, что исходный файл изображения никогда не модифицируется."""
        initial_bytes = sample_png.read_bytes()
        initial_hash = hashlib.sha256(initial_bytes).hexdigest()
        initial_stat = sample_png.stat()

        # 1. Инспекция
        info = GeoreferenceService.inspect_image(sample_png)
        assert info["width"] == 200
        assert info["height"] == 150

        # 2. Загрузка предпросмотра
        preview_qimg, full_size = GeoreferenceService.load_preview_image(sample_png, max_dimension=100)
        assert full_size == (200, 150)
        assert isinstance(preview_qimg, QImage)
        assert max(preview_qimg.width(), preview_qimg.height()) <= 100

        # 3. Полная загрузка
        full_qimg, full_dims = GeoreferenceService.load_full_image(sample_png)
        assert isinstance(full_qimg, QImage)
        assert full_qimg.width() == 200
        assert full_qimg.height() == 150
        assert full_dims == (200, 150)

        # 4. Экспорт world-файла
        affine = (1.0, 0.0, 100.0, 0.0, -1.0, 200.0)
        exported_files = GeoreferenceService.export_world_file(sample_png, affine, crs="EPSG:3857")
        assert len(exported_files) == 2
        wf_path, prj_path = exported_files[0], exported_files[1]
        assert wf_path.exists()
        assert prj_path.exists()
        assert wf_path.suffix == ".pgw"

        # 5. Проверка неизменности исходного файла
        current_bytes = sample_png.read_bytes()
        current_hash = hashlib.sha256(current_bytes).hexdigest()
        current_stat = sample_png.stat()

        assert initial_hash == current_hash
        assert initial_bytes == current_bytes
        assert initial_stat.st_size == current_stat.st_size

    def test_decompression_bomb_rejection(self, sample_png: Path):
        """Защита от 'бомб декомпрессии' (растров свыше 250 мегапикселей)."""
        # Эмулируем изображение с экстремальными габаритами
        with patch("PIL.Image.open") as mock_open:
            mock_img = Image.new("RGB", (1, 1))
            mock_img._size = (30000, 20000)  # 600,000,000 пикселей > 250_000_000
            mock_open.return_value.__enter__.return_value = mock_img

            with pytest.raises(ValueError, match="превышает.*предел"):
                GeoreferenceService.inspect_image(sample_png)

            with pytest.raises(ValueError, match="превышает.*предел"):
                GeoreferenceService.load_preview_image(sample_png)

            with pytest.raises(ValueError, match="превышает.*предел"):
                GeoreferenceService.load_full_image(sample_png)

    def test_corrupted_file_handling(self, tmp_path: Path):
        """Корректная обработка поврежденных или некорректных файлов."""
        bad_file = tmp_path / "corrupt.png"
        bad_file.write_bytes(b"This is definitely not a valid image file content.")

        with pytest.raises(ValueError, match="Не удалось открыть"):
            GeoreferenceService.inspect_image(bad_file)

        with pytest.raises(ValueError, match="Не удалось"):
            GeoreferenceService.load_preview_image(bad_file)

        with pytest.raises(ValueError, match="Не удалось"):
            GeoreferenceService.load_full_image(bad_file)

    def test_world_file_content_and_prj(self, sample_png: Path):
        """Проверка формата сгенерированного ESRI World File и .prj."""
        affine = (2.5, 0.0, 500000.0, 0.0, -2.5, 6000000.0)
        exported = GeoreferenceService.export_world_file(sample_png, affine, crs="EPSG:3857")
        wf_path, prj_path = exported[0], exported[1]

        lines = wf_path.read_text(encoding="utf-8").strip().splitlines()
        assert len(lines) == 6
        # A, D, B, E, Center_X, Center_Y
        assert float(lines[0]) == 2.5
        assert float(lines[1]) == 0.0
        assert float(lines[2]) == 0.0
        assert float(lines[3]) == -2.5
        assert float(lines[4]) == 500001.25  # 500000 + 2.5/2
        assert float(lines[5]) == 5999998.75  # 6000000 - 2.5/2

        prj_content = prj_path.read_text(encoding="utf-8")
        assert len(prj_content) > 10
