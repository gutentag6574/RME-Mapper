"""Тесты растрового бэкенда для GeoTIFF (Этап 16)."""

import os
from pathlib import Path
import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin, Affine

from rme_mapper.backends.factory import BackendFactory
from rme_mapper.backends.legacy_raster_placeholder import LegacyRasterBackend
from rme_mapper.backends.modern_raster import ModernGeoTiffBackend
from rme_mapper.backends.raster_backend import RasterDataBackend


@pytest.fixture
def temp_geotiff_1band_uint8(tmp_path: Path) -> Path:
    """Создание тестового одноканального 8-битного GeoTIFF."""
    file_path = tmp_path / "test_1band_uint8.tif"
    width, height = 50, 40
    data = np.arange(height * width, dtype=np.uint8).reshape((height, width))
    transform = from_origin(37.5, 55.8, 0.01, 0.01)

    with rasterio.open(
        file_path,
        "w",
        driver="GTiff",
        height=height,
        width=width,
        count=1,
        dtype=np.uint8,
        crs="EPSG:4326",
        transform=transform,
        nodata=0,
    ) as dst:
        dst.write(data, 1)

    return file_path


@pytest.fixture
def temp_geotiff_1band_uint16(tmp_path: Path) -> Path:
    """Создание тестового 16-битного GeoTIFF для проверки min-max stretch."""
    file_path = tmp_path / "test_1band_uint16.tif"
    width, height = 30, 30
    data = np.linspace(1000, 50000, width * height, dtype=np.uint16).reshape((height, width))
    transform = from_origin(500000, 6000000, 10.0, 10.0)

    with rasterio.open(
        file_path,
        "w",
        driver="GTiff",
        height=height,
        width=width,
        count=1,
        dtype=np.uint16,
        crs="EPSG:32637",
        transform=transform,
    ) as dst:
        dst.write(data, 1)

    return file_path


@pytest.fixture
def temp_geotiff_1band_float(tmp_path: Path) -> Path:
    """Создание тестового Float32 GeoTIFF с NaN и nodata."""
    file_path = tmp_path / "test_1band_float.tif"
    width, height = 20, 20
    data = np.full((height, width), 25.5, dtype=np.float32)
    data[0, 0] = -9999.0
    data[1, 1] = np.nan
    transform = from_origin(10.0, 50.0, 1.0, 1.0)

    with rasterio.open(
        file_path,
        "w",
        driver="GTiff",
        height=height,
        width=width,
        count=1,
        dtype=np.float32,
        crs="EPSG:4326",
        transform=transform,
        nodata=-9999.0,
    ) as dst:
        dst.write(data, 1)

    return file_path


@pytest.fixture
def temp_geotiff_3band_rgb(tmp_path: Path) -> Path:
    """Создание тестового 3-канального RGB GeoTIFF."""
    file_path = tmp_path / "test_rgb.TIFF"  # Тест регистра расширения
    width, height = 30, 20
    r = np.full((height, width), 255, dtype=np.uint8)
    g = np.full((height, width), 128, dtype=np.uint8)
    b = np.full((height, width), 64, dtype=np.uint8)
    transform = from_origin(30.0, 60.0, 0.5, 0.5)

    with rasterio.open(
        file_path,
        "w",
        driver="GTiff",
        height=height,
        width=width,
        count=3,
        dtype=np.uint8,
        crs="EPSG:4326",
        transform=transform,
    ) as dst:
        dst.write(r, 1)
        dst.write(g, 2)
        dst.write(b, 3)

    return file_path


@pytest.fixture
def temp_geotiff_4band_rgba(tmp_path: Path) -> Path:
    """Создание тестового 4-канального RGBA GeoTIFF."""
    file_path = tmp_path / "test_rgba.tif"
    width, height = 25, 25
    r = np.full((height, width), 200, dtype=np.uint8)
    g = np.full((height, width), 100, dtype=np.uint8)
    b = np.full((height, width), 50, dtype=np.uint8)
    a = np.full((height, width), 255, dtype=np.uint8)
    a[0:5, 0:5] = 0  # Прозрачный угол
    transform = from_origin(100.0, 20.0, 0.2, 0.2)

    with rasterio.open(
        file_path,
        "w",
        driver="GTiff",
        height=height,
        width=width,
        count=4,
        dtype=np.uint8,
        crs="EPSG:4326",
        transform=transform,
    ) as dst:
        dst.write(r, 1)
        dst.write(g, 2)
        dst.write(b, 3)
        dst.write(a, 4)
        dst.colorinterp = (
            rasterio.enums.ColorInterp.red,
            rasterio.enums.ColorInterp.green,
            rasterio.enums.ColorInterp.blue,
            rasterio.enums.ColorInterp.alpha,
        )

    return file_path


# =============================================================================
# Тесты Factory и интерфейса
# =============================================================================

def test_01_backend_factory_raster_capabilities():
    """Проверка регистрации и методов возможностей фабрики."""
    assert BackendFactory.supports_geotiff() is True
    assert BackendFactory.supports_source_type("geotiff") is True
    assert BackendFactory.supports_source_type("geopackage") is True
    assert BackendFactory.supports_source_type("unsupported") is False

    backend = BackendFactory.get_raster_backend()
    assert isinstance(backend, RasterDataBackend)
    assert isinstance(backend, ModernGeoTiffBackend)


def test_02_legacy_raster_backend_raises():
    """Проверка выброса NotImplementedError в заглушке LegacyRasterBackend."""
    legacy = LegacyRasterBackend()
    assert isinstance(legacy, RasterDataBackend)
    dummy_path = Path("dummy.tif")

    with pytest.raises(NotImplementedError):
        legacy.inspect_raster(dummy_path)

    with pytest.raises(NotImplementedError):
        legacy.get_crs(dummy_path)

    with pytest.raises(NotImplementedError):
        legacy.read_preview(dummy_path)

    with pytest.raises(NotImplementedError):
        legacy.read_window(dummy_path, (0, 0, 1, 1), 100, 100)

    # close() не должен падать
    legacy.close(dummy_path)


# =============================================================================
# Тесты инспекции и метаданных
# =============================================================================

def test_03_inspect_raster_1band_uint8(temp_geotiff_1band_uint8: Path):
    """Проверка инспекции метаданных одноканального растра."""
    backend = ModernGeoTiffBackend()
    info = backend.inspect_raster(temp_geotiff_1band_uint8)

    assert info["crs"] == "EPSG:4326"
    assert info["width"] == 50
    assert info["height"] == 40
    assert info["band_count"] == 1
    assert info["dtype"] == "uint8"
    assert info["nodata"] == 0.0

    ext = info["extent"]
    assert pytest.approx(ext["xmin"], rel=1e-5) == 37.5
    assert pytest.approx(ext["xmax"], rel=1e-5) == 37.5 + 50 * 0.01
    assert pytest.approx(ext["ymax"], rel=1e-5) == 55.8
    assert pytest.approx(ext["ymin"], rel=1e-5) == 55.8 - 40 * 0.01

    assert len(info["transform"]) == 6
    backend.close(temp_geotiff_1band_uint8)


def test_04_convenience_accessors(temp_geotiff_1band_uint8: Path):
    """Проверка вспомогательных методов get_crs, get_extent, get_size и т.д."""
    backend = ModernGeoTiffBackend()
    assert backend.get_crs(temp_geotiff_1band_uint8) == "EPSG:4326"
    assert backend.get_size(temp_geotiff_1band_uint8) == (50, 40)
    assert backend.get_band_count(temp_geotiff_1band_uint8) == 1
    assert backend.get_nodata(temp_geotiff_1band_uint8) == 0.0

    ext = backend.get_extent(temp_geotiff_1band_uint8)
    assert pytest.approx(ext["xmin"], rel=1e-5) == 37.5
    backend.close(temp_geotiff_1band_uint8)


# =============================================================================
# Тесты чтения каналов и нормализации
# =============================================================================

def test_05_read_preview_1band_uint8_and_nodata(temp_geotiff_1band_uint8: Path):
    """Проверка чтения превью 1-band uint8 с установкой nodata в альфу."""
    backend = ModernGeoTiffBackend()
    rgba, meta = backend.read_preview(temp_geotiff_1band_uint8)

    assert rgba.shape == (40, 50, 4)
    assert rgba.dtype == np.uint8

    # Пиксель (0, 0) имел значение data=0 (nodata=0) -> должен быть прозрачным (alpha=0)
    assert rgba[0, 0, 3] == 0

    # Пиксель (0, 1) имел значение data=1 -> непрозрачный (alpha=255)
    assert rgba[0, 1, 3] == 255
    # Grayscale дублируется в RGB
    assert rgba[0, 1, 0] == 1
    assert rgba[0, 1, 1] == 1
    assert rgba[0, 1, 2] == 1

    backend.close(temp_geotiff_1band_uint8)


def test_06_read_preview_1band_uint16_stretch(temp_geotiff_1band_uint16: Path):
    """Проверка min-max растяжки для 16-битного растра."""
    backend = ModernGeoTiffBackend()
    rgba, meta = backend.read_preview(temp_geotiff_1band_uint16)

    assert rgba.shape == (30, 30, 4)
    assert rgba.dtype == np.uint8

    # Мин значение растягивается к ~0, макс значение к ~255
    assert rgba[0, 0, 0] == 0
    assert rgba[-1, -1, 0] == 255
    assert rgba[0, 0, 3] == 255  # Без nodata - все непрозрачные

    backend.close(temp_geotiff_1band_uint16)


def test_07_read_preview_1band_float_nan_and_nodata(temp_geotiff_1band_float: Path):
    """Проверка обработки NaN и nodata в растре с плавающей точкой."""
    backend = ModernGeoTiffBackend()
    rgba, meta = backend.read_preview(temp_geotiff_1band_float)

    assert rgba.shape == (20, 20, 4)
    # (0, 0) - nodata (-9999) -> прозрачный
    assert rgba[0, 0, 3] == 0
    # (1, 1) - NaN -> прозрачный
    assert rgba[1, 1, 3] == 0
    # Валидный пиксель -> непрозрачный
    assert rgba[5, 5, 3] == 255

    backend.close(temp_geotiff_1band_float)


def test_08_read_preview_3band_rgb(temp_geotiff_3band_rgb: Path):
    """Проверка чтения 3-канального RGB растра с расширением .TIFF."""
    backend = ModernGeoTiffBackend()
    rgba, meta = backend.read_preview(temp_geotiff_3band_rgb)

    assert rgba.shape == (20, 30, 4)
    assert rgba[0, 0, 0] == 255  # Red
    assert rgba[0, 0, 1] == 128  # Green
    assert rgba[0, 0, 2] == 64   # Blue
    assert rgba[0, 0, 3] == 255  # Alpha

    backend.close(temp_geotiff_3band_rgb)


def test_09_read_preview_4band_rgba(temp_geotiff_4band_rgba: Path):
    """Проверка 4-канального растра с каналом прозрачности."""
    backend = ModernGeoTiffBackend()
    rgba, meta = backend.read_preview(temp_geotiff_4band_rgba)

    assert rgba.shape == (25, 25, 4)
    assert rgba[0, 0, 0] == 200
    assert rgba[0, 0, 1] == 100
    assert rgba[0, 0, 2] == 50
    # Прозрачный угол
    assert rgba[0, 0, 3] == 0
    # Непрозрачная область
    assert rgba[10, 10, 3] == 255

    backend.close(temp_geotiff_4band_rgba)


# =============================================================================
# Тесты безопасности памяти и оконного чтения
# =============================================================================

def test_10_read_preview_decimation(tmp_path: Path):
    """Проверка децимации при чтении превью, если размер превышает лимит."""
    file_path = tmp_path / "large_preview_test.tif"
    width, height = 200, 100
    data = np.zeros((height, width), dtype=np.uint8)
    transform = from_origin(0, 0, 1, 1)

    with rasterio.open(
        file_path, "w", driver="GTiff", height=height, width=width, count=1, dtype=np.uint8, crs="EPSG:4326", transform=transform
    ) as dst:
        dst.write(data, 1)

    backend = ModernGeoTiffBackend()
    # Задаем искусственно малый лимит max_preview_dimension=50
    rgba, meta = backend.read_preview(file_path, max_preview_dimension=50)

    # Максимальный размер должен быть ограничем 50
    assert max(rgba.shape[:2]) == 50
    assert rgba.shape == (25, 50, 4)
    backend.close(file_path)


def test_11_read_window(temp_geotiff_1band_uint8: Path):
    """Проверка оконного чтения фрагмента растра."""
    backend = ModernGeoTiffBackend()
    # Запрашиваем центр растра
    target_extent = (37.6, 55.5, 37.8, 55.7)
    rgba, meta = backend.read_window(temp_geotiff_1band_uint8, target_extent, out_width=100, out_height=80)

    assert rgba.shape == (80, 100, 4)
    assert rgba.dtype == np.uint8
    assert "transform" in meta

    # Повторный запрос того же окна проверяет попадание в LRU кэш
    rgba2, meta2 = backend.read_window(temp_geotiff_1band_uint8, target_extent, out_width=100, out_height=80)
    np.testing.assert_array_equal(rgba, rgba2)

    backend.close(temp_geotiff_1band_uint8)


def test_12_close_releases_windows_file_lock(tmp_path: Path):
    """Проверка освобождения дескриптора файла после close() на Windows."""
    file_path = tmp_path / "lock_test.tif"
    width, height = 10, 10
    data = np.zeros((height, width), dtype=np.uint8)
    transform = from_origin(0, 0, 1, 1)

    with rasterio.open(
        file_path, "w", driver="GTiff", height=height, width=width, count=1, dtype=np.uint8, crs="EPSG:4326", transform=transform
    ) as dst:
        dst.write(data, 1)

    backend = ModernGeoTiffBackend()
    backend.inspect_raster(file_path)
    backend.read_preview(file_path)

    # До вызова close() файл может удерживаться открытым
    backend.close(file_path)

    # На Windows удаление заблокированного файла выбрасывает PermissionError
    # После close() удаление должно пройти успешно
    file_path.unlink()
    assert not file_path.exists()
