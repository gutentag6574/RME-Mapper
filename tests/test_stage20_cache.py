"""Тесты дискового кэша тайлов (Этап 20: Tests 19-28)."""

import time
import pytest
from pathlib import Path

from rme_mapper.services.tile_cache import TileDiskCache, PNG_MAGIC, JPEG_MAGIC


@pytest.fixture
def temp_cache(tmp_path: Path) -> TileDiskCache:
    """Изолированный тестовый кэш во временной директории."""
    return TileDiskCache(base_dir=tmp_path / "test_tiles", max_size_bytes=100 * 1024)  # 100 KB limit for test


def _make_dummy_png(content: bytes = b"test_tile_content") -> bytes:
    """Генерация фиктивных данных с валидной сигнатурой PNG."""
    return PNG_MAGIC + content


def test_19_cache_miss(temp_cache: TileDiskCache):
    """Тест 19: Cache miss возвращает None и не вызывает ошибок."""
    assert temp_cache.has_tile("osm_standard", 1, 2, 3) is False
    assert temp_cache.get_tile("osm_standard", 1, 2, 3) is None


def test_20_cache_write_and_read(temp_cache: TileDiskCache):
    """Тест 20: Запись тайла и его последующее успешное чтение (Cache Hit)."""
    data = _make_dummy_png(b"pixel_data_123")
    saved = temp_cache.save_tile("osm_standard", 5, 10, 15, data)
    assert saved is True
    assert temp_cache.has_tile("osm_standard", 5, 10, 15) is True

    loaded = temp_cache.get_tile("osm_standard", 5, 10, 15)
    assert loaded == data


def test_21_corrupted_data_rejected(temp_cache: TileDiskCache):
    """Тест 21: Невалидные данные (HTML-страницы ошибок, мусор) отклоняются при записи."""
    html_error = b"<html><body>404 Not Found</body></html>"
    saved = temp_cache.save_tile("osm_standard", 2, 2, 2, html_error)
    assert saved is False
    assert temp_cache.has_tile("osm_standard", 2, 2, 2) is False


def test_22_corrupted_file_on_disk_removed(temp_cache: TileDiskCache, tmp_path: Path):
    """Тест 22: Поврежденный файл на диске удаляется при попытке чтения."""
    bad_file = temp_cache.cache_root / "osm_standard" / "3" / "4" / "5.tile"
    bad_file.parent.mkdir(parents=True, exist_ok=True)
    bad_file.write_bytes(b"corrupted_garbage_bytes")

    assert bad_file.exists()
    loaded = temp_cache.get_tile("osm_standard", 3, 4, 5)
    assert loaded is None
    # Файл должен быть автоматически удален
    assert not bad_file.exists()


def test_23_provider_separation(temp_cache: TileDiskCache):
    """Тест 23: Изоляция кэша разных провайдеров."""
    data1 = _make_dummy_png(b"osm")
    data2 = _make_dummy_png(b"mapbox")

    temp_cache.save_tile("osm_standard", 4, 1, 1, data1)
    temp_cache.save_tile("mapbox_sat", 4, 1, 1, data2)

    assert temp_cache.get_tile("osm_standard", 4, 1, 1) == data1
    assert temp_cache.get_tile("mapbox_sat", 4, 1, 1) == data2


def test_24_z_x_y_directory_structure(temp_cache: TileDiskCache):
    """Тест 24: Соответствие структуры папок формату <provider>/<z>/<x>/<y>.tile."""
    data = _make_dummy_png(b"deep")
    temp_cache.save_tile("osm_standard", 12, 345, 678, data)

    expected_path = temp_cache.cache_root / "osm_standard" / "12" / "345" / "678.tile"
    assert expected_path.is_file()


def test_25_size_accounting(temp_cache: TileDiskCache):
    """Тест 25: Точный подсчет суммарного объема файлов кэша."""
    assert temp_cache.get_total_size_bytes() == 0

    data = _make_dummy_png(b"x" * 1000)
    temp_cache.save_tile("osm_standard", 1, 1, 1, data)
    size1 = temp_cache.get_total_size_bytes()
    assert size1 == len(data)

    temp_cache.save_tile("osm_standard", 1, 1, 2, data)
    assert temp_cache.get_total_size_bytes() == 2 * len(data)


def test_26_lru_eviction(tmp_path: Path):
    """Тест 26: LRU-вытеснение старых тайлов при превышении максимального объема."""
    # Создаем кэш с лимитом 3000 байт
    cache = TileDiskCache(base_dir=tmp_path / "lru_cache", max_size_bytes=3000)
    data = _make_dummy_png(b"a" * 800)  # ~808 байт

    # Сохраняем тайл 1
    cache.save_tile("osm", 1, 0, 0, data)
    time.sleep(0.01)

    # Сохраняем тайл 2
    cache.save_tile("osm", 1, 0, 1, data)
    time.sleep(0.01)

    # Сохраняем тайл 3
    cache.save_tile("osm", 1, 0, 2, data)
    time.sleep(0.01)

    # Сейчас размер ~ 2424 байт (меньше 3000)
    assert cache.has_tile("osm", 1, 0, 0) is True

    # Сохраняем тайл 4 — суммарный объем превысит 3000 байт -> сработает вытеснение
    cache.save_tile("osm", 1, 0, 3, data)

    # Самый старый тайл (1, 0, 0) должен быть вытеснен
    assert cache.has_tile("osm", 1, 0, 0) is False
    # Самый свежий тайл (1, 0, 3) сохранен
    assert cache.has_tile("osm", 1, 0, 3) is True


def test_27_clear_cache(temp_cache: TileDiskCache):
    """Тест 27: Полная и выборочная очистка кэша."""
    data = _make_dummy_png(b"sample")
    temp_cache.save_tile("osm_standard", 1, 0, 0, data)
    temp_cache.save_tile("mapbox", 1, 0, 0, data)

    # Очищаем только osm_standard
    temp_cache.clear_cache("osm_standard")
    assert temp_cache.has_tile("osm_standard", 1, 0, 0) is False
    assert temp_cache.has_tile("mapbox", 1, 0, 0) is True

    # Очищаем все
    temp_cache.clear_cache()
    assert temp_cache.has_tile("mapbox", 1, 0, 0) is False
    assert temp_cache.get_total_size_bytes() == 0


def test_28_path_traversal_blocked(temp_cache: TileDiskCache):
    """Тест 28: Попытки инъекции путей (../) в provider_id или отрицательные индексы блокируются."""
    with pytest.raises(ValueError):
        temp_cache.get_tile("../evil", 1, 2, 3)

    with pytest.raises(ValueError):
        temp_cache.save_tile("provider/hack", 1, 2, 3, _make_dummy_png())

    with pytest.raises(ValueError):
        temp_cache.get_tile("osm", -1, 2, 3)
