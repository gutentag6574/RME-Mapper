"""Дисковый кэш тайлов онлайн-карт (TileDiskCache) с LRU-очисткой и валидацией."""

import logging
import os
from pathlib import Path
import re
from typing import Any

from PySide6.QtCore import QStandardPaths

logger = logging.getLogger("rme_mapper.services.tile_cache")

# Сигнатуры допустимых форматов растровых изображений
PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
JPEG_MAGIC = b"\xff\xd8\xff"
WEBP_MAGIC = b"RIFF"

# Регулярное выражение для безопасных идентификаторов провайдеров (защита от path traversal)
SAFE_PROVIDER_ID_RE = re.compile(r"^[a-zA-Z0-9_-]+$")

# Значения по умолчанию
DEFAULT_MAX_CACHE_SIZE_BYTES = 256 * 1024 * 1024  # 256 MB
EVICTION_TARGET_RATIO = 0.80  # Снижаем до 80% от лимита при вытеснении


class TileDiskCache:
    """Управление локальным файловым кэшем тайлов онлайн-подложек."""

    def __init__(
        self,
        base_dir: Path | str | None = None,
        max_size_bytes: int = DEFAULT_MAX_CACHE_SIZE_BYTES,
        cache_dir: Path | str | None = None,
    ) -> None:
        target_dir = base_dir or cache_dir
        if target_dir:
            self._cache_root = Path(target_dir)
        else:
            std_loc = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.CacheLocation)
            if std_loc:
                self._cache_root = Path(std_loc) / "GeoPointMapper" / "online_tiles"
            else:
                self._cache_root = Path.home() / ".cache" / "geopoint_mapper" / "online_tiles"

        self._max_size_bytes = max_size_bytes
        self._cache_root.mkdir(parents=True, exist_ok=True)

    @property
    def cache_root(self) -> Path:
        return self._cache_root

    @property
    def max_size_bytes(self) -> int:
        return self._max_size_bytes

    @max_size_bytes.setter
    def max_size_bytes(self, val: int) -> None:
        self._max_size_bytes = max(10 * 1024 * 1024, val)

    @staticmethod
    def is_valid_image(data: bytes) -> bool:
        """Проверка магических байтов: отклонение невалидных данных и текстовых HTML-страниц ошибок."""
        if not data or len(data) < 8:
            return False
        if data.startswith(PNG_MAGIC):
            return True
        if data.startswith(JPEG_MAGIC):
            return True
        if data.startswith(WEBP_MAGIC) and b"WEBP" in data[:16]:
            return True
        return False

    def _get_tile_path(self, provider_id: str, z: int, x: int, y: int) -> Path:
        """Построение безопасного пути к файлу тайла с валидацией входных параметров."""
        clean_id = (provider_id or "").strip()
        if not SAFE_PROVIDER_ID_RE.match(clean_id):
            raise ValueError(f"Недопустимый идентификатор провайдера для кэша: '{clean_id}'")

        if z < 0 or x < 0 or y < 0:
            raise ValueError(f"Отрицательные координаты тайла недопустимы: z={z}, x={x}, y={y}")

        tile_dir = self._cache_root / clean_id / str(z) / str(x)
        return tile_dir / f"{y}.tile"

    def has_tile(self, provider_id: str, z: int, x: int, y: int) -> bool:
        """Проверка наличия валидного тайла в кэше."""
        try:
            path = self._get_tile_path(provider_id, z, x, y)
            return path.is_file() and path.stat().st_size > 0
        except Exception:
            return False

    def get_tile(self, provider_id: str, z: int, x: int, y: int) -> bytes | None:
        """Получение байтов тайла из кэша.

        При успешном чтении обновляет mtime (для LRU).
        Если файл поврежден или не является изображением — удаляет его и возвращает None.
        """
        path = self._get_tile_path(provider_id, z, x, y)
        try:
            if not path.is_file():
                return None

            data = path.read_bytes()
            if not self.is_valid_image(data):
                logger.warning("Поврежденный тайл в кэше %s: невалидная сигнатура. Удаление.", path)
                try:
                    path.unlink()
                except OSError:
                    pass
                return None

            # Обновление времени доступа для LRU
            try:
                os.utime(path, None)
            except OSError:
                pass

            return data
        except OSError as e:
            logger.debug("Ошибка чтения тайла из кэша (%s/%s/%s/%s): %s", provider_id, z, x, y, e)
            return None

    def save_tile(self, provider_id: str, z: int, x: int, y: int, data: bytes) -> bool:
        """Сохранение байтов тайла в кэш с валидацией и контролем размера."""
        if not self.is_valid_image(data):
            logger.debug("Отказ сохранения тайла: данные не являются поддерживаемым изображением")
            return False

        path = self._get_tile_path(provider_id, z, x, y)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)

            # Атомарная запись через временный файл
            tmp_path = path.with_name(f"{path.name}.tmp_{os.getpid()}")
            tmp_path.write_bytes(data)
            tmp_path.replace(path)

            # Проверка лимита размера кэша
            self._maybe_evict()
            return True
        except Exception as e:
            logger.warning("Ошибка записи тайла в кэш: %s", e)
            return False

    put_tile = save_tile

    def get_total_size_bytes(self, provider_id: str | None = None) -> int:
        """Подсчет суммарного объема кэша в байтах."""
        target_dir = self._cache_root / provider_id if provider_id else self._cache_root
        if not target_dir.exists():
            return 0

        total = 0
        try:
            for root, _, files in os.walk(target_dir):
                for f in files:
                    fp = Path(root) / f
                    try:
                        total += fp.stat().st_size
                    except OSError:
                        pass
        except Exception as e:
            logger.debug("Ошибка расчета размера кэша: %s", e)
        return total

    def clear_cache(self, provider_id: str | None = None) -> None:
        """Очистка кэша (для конкретного провайдера или всего кэша онлайн-карт)."""
        import shutil

        target_dir = self._cache_root / provider_id if provider_id else self._cache_root
        if not target_dir.exists():
            return

        try:
            if provider_id:
                shutil.rmtree(target_dir, ignore_errors=True)
            else:
                for item in self._cache_root.iterdir():
                    if item.is_dir():
                        shutil.rmtree(item, ignore_errors=True)
                    elif item.is_file():
                        try:
                            item.unlink()
                        except OSError:
                            pass
            logger.info("Кэш онлайн-карт успешно очищен: %s", target_dir)
        except Exception as e:
            logger.warning("Ошибка при очистке кэша %s: %s", target_dir, e)

    def _maybe_evict(self) -> None:
        """Вытеснение старых файлов по принципу LRU (по mtime) при превышении лимита размера."""
        current_size = self.get_total_size_bytes()
        if current_size <= self._max_size_bytes:
            return

        logger.info("Превышен лимит кэша (%d > %d байт). Запуск LRU-очистки...", current_size, self._max_size_bytes)
        target_size = int(self._max_size_bytes * EVICTION_TARGET_RATIO)

        # Собираем все файлы кэша с их размером и временем последней модификации
        file_entries: list[tuple[float, int, Path]] = []
        for root, _, files in os.walk(self._cache_root):
            for f in files:
                p = Path(root) / f
                try:
                    stat = p.stat()
                    file_entries.append((stat.st_mtime, stat.st_size, p))
                except OSError:
                    pass

        # Сортируем от самых старых к самым новым
        file_entries.sort(key=lambda item: item[0])

        removed_bytes = 0
        for _, fsize, fpath in file_entries:
            if current_size - removed_bytes <= target_size:
                break
            try:
                fpath.unlink()
                removed_bytes += fsize
            except OSError:
                pass

        logger.info("LRU-очистка завершена: удалено %d байт", removed_bytes)

    @staticmethod
    def format_size(size_bytes: int, lang: str = "ru") -> str:
        """Форматирование размера кэша для отображения в интерфейсе (КБ, МБ, ГБ)."""
        if size_bytes < 1024:
            unit = "B" if lang == "en" else "Б"
            return f"{size_bytes} {unit}"
        elif size_bytes < 1024 * 1024:
            kb = size_bytes / 1024.0
            unit = "KB" if lang == "en" else "КБ"
            return f"{kb:.1f} {unit}"
        elif size_bytes < 1024 * 1024 * 1024:
            mb = size_bytes / (1024.0 * 1024.0)
            unit = "MB" if lang == "en" else "МБ"
            return f"{mb:.1f} {unit}"
        else:
            gb = size_bytes / (1024.0 * 1024.0 * 1024.0)
            unit = "GB" if lang == "en" else "ГБ"
            return f"{gb:.2f} {unit}"
