"""Менеджер подложки онлайн-тайлов на MapCanvas (OnlineTileManager)."""
from __future__ import annotations


from collections import OrderedDict
import logging
from typing import Any

from PySide6.QtCore import QObject, QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QBrush, QColor, QImage, QPainter, QPen, QPixmap, QTransform
from PySide6.QtWidgets import (
    QGraphicsItem,
    QGraphicsItemGroup,
    QGraphicsPixmapItem,
    QGraphicsRectItem,
    QGraphicsScene,
)

from rme_mapper.models.online_provider import OnlineTileProvider
from rme_mapper.services.tile_cache import TileDiskCache
from rme_mapper.services.tile_loader import TileLoader
from rme_mapper.services.tile_math import (
    extent_to_tile_range,
    meters_per_pixel_to_zoom,
    tile_to_scene_rect,
)

logger = logging.getLogger("rme_mapper.maps.online_tile_manager")

DEFAULT_MEM_CACHE_CAPACITY = 256
ONLINE_TILES_Z_VALUE = 5.0


class OnlineTileManager(QObject):
    """Управление загрузкой, кэшированием и отображением онлайн-тайлов в сцене MapCanvas."""

    tiles_updated = Signal()
    loading_progress = Signal(int)  # число оставшихся в очереди/загрузке тайлов
    auth_error = Signal(str)  # имя провайдера, для которого требуется/отклонен ключ
    error_occurred = Signal(str)

    def __init__(
        self,
        scene: QGraphicsScene,
        tile_cache: TileDiskCache | None = None,
        tile_loader: TileLoader | None = None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._scene = scene
        self._cache = tile_cache or TileDiskCache()
        self._loader = tile_loader or TileLoader(parent=self, tile_cache=self._cache)
        if tile_loader is not None and getattr(tile_loader, "_cache", None) is None:
            tile_loader.set_tile_cache(self._cache)

        self._provider: OnlineTileProvider | None = None
        self._api_key: str | None = None
        self._is_active: bool = False

        self._tile_group: QGraphicsItemGroup | None = None
        self._current_zoom: int = 0
        self._visible_tile_items: dict[tuple[int, int, int], QGraphicsItem] = {}
        self._needed_tiles: set[tuple[int, int, int]] = set()

        self._mem_cache: OrderedDict[tuple[str, int, int, int], QPixmap] = OrderedDict()
        self._mem_cache_capacity = DEFAULT_MEM_CACHE_CAPACITY

        self._last_scene_rect: QRectF | None = None
        self._last_meters_per_pixel: float = 1.0

        # Соединение сигналов загрузчика
        self._loader.tile_loaded.connect(self._on_tile_loaded)
        self._loader.tile_failed.connect(self._on_tile_failed)
        self._loader.auth_error.connect(self._on_auth_error)
        self._loader.loading_progress.connect(self._on_loader_progress)

    # -------------------------------------------------------------------------
    # Публичный интерфейс управления состоянием
    # -------------------------------------------------------------------------

    @property
    def is_active(self) -> bool:
        """Активна ли онлайн-подложка."""
        return self._is_active and self._provider is not None

    @property
    def provider(self) -> OnlineTileProvider | None:
        """Текущий активный провайдер тайлов."""
        return self._provider

    @property
    def current_zoom(self) -> int:
        """Текущий рассчитанный зум-уровень тайлов."""
        return self._current_zoom

    @property
    def api_key(self) -> str | None:
        """Активный API-ключ."""
        return self._api_key

    @property
    def cache(self) -> TileDiskCache:
        """Экземпляр дискового кэша."""
        return self._cache

    def set_provider(
        self,
        provider: OnlineTileProvider | None,
        api_key: str | None = None,
    ) -> None:
        """Установка или сброс активного картографического провайдера."""
        if self._provider == provider and self._api_key == api_key and self._is_active:
            return

        self.clear()

        self._provider = provider
        self._api_key = api_key
        self._is_active = provider is not None

        if self._is_active:
            self._ensure_group()
            logger.info("Онлайн-подложка активирована: %s", provider.name if provider else None)
        else:
            logger.info("Онлайн-подложка деактивирована")

    def clear(self) -> None:
        """Очистка всех отображаемых тайлов и отмена запросов."""
        self._loader.clear_all()
        self._needed_tiles.clear()

        if self._tile_group is not None:
            if self._tile_group.scene() == self._scene:
                self._scene.removeItem(self._tile_group)
            self._tile_group = None

        self._visible_tile_items.clear()
        self._last_scene_rect = None

    # -------------------------------------------------------------------------
    # Обновление вьюпорта и отрисовка
    # -------------------------------------------------------------------------

    def update_viewport(self, scene_rect: QRectF, meters_per_pixel: float) -> None:
        """Перерасчет видимых тайлов при сдвиге или масштабировании холста."""
        if not self.is_active or self._provider is None or self._scene is None:
            return

        if scene_rect.isEmpty() or not scene_rect.isValid() or meters_per_pixel <= 0:
            return

        self._last_scene_rect = scene_rect
        self._last_meters_per_pixel = meters_per_pixel

        # 1. Расчет масштаба (зума) Web Mercator
        zoom = meters_per_pixel_to_zoom(
            meters_per_pixel,
            min_zoom=self._provider.min_zoom,
            max_zoom=self._provider.max_zoom,
        )
        self._current_zoom = zoom

        # 2. Определение границ в координатах Web Mercator (метры)
        # В MapCanvas: scene_x = mercator_x, scene_y = -mercator_y
        min_x = scene_rect.left()
        max_x = scene_rect.right()
        min_y = -scene_rect.bottom()
        max_y = -scene_rect.top()

        tile_bounds = extent_to_tile_range(min_x, min_y, max_x, max_y, zoom)
        if tile_bounds is None:
            return

        min_tile_x, min_tile_y, max_tile_x, max_tile_y = tile_bounds

        # Ограничение на разумный максимум тайлов в одном экране (защита от зависаний)
        total_tiles_needed = (max_tile_x - min_tile_x + 1) * (max_tile_y - min_tile_y + 1)
        if total_tiles_needed > 250:
            logger.warning("Слишком много тайлов для вьюпорта (%d), пропуск", total_tiles_needed)
            return

        needed_keys: set[tuple[int, int, int]] = set()
        for tx in range(min_tile_x, max_tile_x + 1):
            for ty in range(min_tile_y, max_tile_y + 1):
                needed_keys.add((zoom, tx, ty))

        self._needed_tiles = needed_keys

        # 3. Отмена устаревших запросов загрузки
        self._loader.cancel_stale_requests(zoom, (min_tile_x, min_tile_y, max_tile_x, max_tile_y))

        # 4. Удаление элементов сцены, которые больше не нужны
        self._ensure_group()
        keys_to_remove = [k for k in self._visible_tile_items if k not in needed_keys]
        for k in keys_to_remove:
            item = self._visible_tile_items.pop(k)
            if self._tile_group is not None and item.scene() == self._scene:
                self._tile_group.removeFromGroup(item)
                self._scene.removeItem(item)

        # 5. Добавление/обновление нужных тайлов
        for (z, x, y) in needed_keys:
            if (z, x, y) in self._visible_tile_items:
                continue

            rect = tile_to_scene_rect(x, y, zoom)

            # Проверяем память
            pixmap = self._get_mem_cache(self._provider.id, z, x, y)
            if pixmap is not None:
                self._add_pixmap_item(z, x, y, rect, pixmap)
                continue

            # Проверяем диск
            disk_data = self._cache.get_tile(self._provider.id, z, x, y)
            if disk_data is not None:
                pix = QPixmap()
                if pix.loadFromData(disk_data):
                    self._put_mem_cache(self._provider.id, z, x, y, pix)
                    self._add_pixmap_item(z, x, y, rect, pix)

                    # Если тайл просрочен по HTTP-заголовкам / minimum TTL (7 дней для OSM),
                    # инициируем фоновый условный запрос (If-None-Match / If-Modified-Since)
                    if self._cache.is_tile_expired(self._provider.id, z, x, y):
                        url = self._provider.build_tile_url(z, x, y, api_key=self._api_key)
                        self._loader.request_tile(self._provider.id, z, x, y, url, conditional=True)
                    continue

            # Тайла нет в кэше — ставим плейсхолдер и запрашиваем по сети
            self._add_placeholder_item(z, x, y, rect)
            url = self._provider.build_tile_url(z, x, y, api_key=self._api_key)
            self._loader.request_tile(self._provider.id, z, x, y, url)

    def _ensure_group(self) -> None:
        """Создание группы элементов онлайн-тайлов при необходимости."""
        if self._tile_group is None:
            self._tile_group = QGraphicsItemGroup()
            self._tile_group.setZValue(ONLINE_TILES_Z_VALUE)
            self._scene.addItem(self._tile_group)

    def _add_pixmap_item(
        self,
        z: int,
        x: int,
        y: int,
        rect: QRectF,
        pixmap: QPixmap,
    ) -> None:
        """Создание и добавление QGraphicsPixmapItem в сцену."""
        if self._tile_group is None:
            return

        # Если уже был плейсхолдер — удаляем его
        old_item = self._visible_tile_items.pop((z, x, y), None)
        if old_item is not None and old_item.scene() == self._scene:
            self._tile_group.removeFromGroup(old_item)
            self._scene.removeItem(old_item)

        item = QGraphicsPixmapItem(pixmap)
        item.setTransformationMode(Qt.TransformationMode.SmoothTransformation)
        item.setPos(rect.left(), rect.top())

        pw = pixmap.width()
        ph = pixmap.height()
        if pw > 0 and ph > 0:
            scale_x = rect.width() / pw
            scale_y = rect.height() / ph
            transform = QTransform()
            transform.scale(scale_x, scale_y)
            item.setTransform(transform)

        item.setZValue(ONLINE_TILES_Z_VALUE)
        self._tile_group.addToGroup(item)
        self._visible_tile_items[(z, x, y)] = item

    def _add_placeholder_item(
        self,
        z: int,
        x: int,
        y: int,
        rect: QRectF,
    ) -> None:
        """Создание нейтрального плейсхолдера для незагруженного тайла."""
        if self._tile_group is None:
            return

        rect_item = QGraphicsRectItem(rect)
        rect_item.setPen(QPen(QColor(226, 232, 240, 60), 1.0, Qt.PenStyle.DotLine))
        rect_item.setBrush(QBrush(QColor(241, 245, 249, 100)))
        rect_item.setZValue(ONLINE_TILES_Z_VALUE)
        self._tile_group.addToGroup(rect_item)
        self._visible_tile_items[(z, x, y)] = rect_item

    # -------------------------------------------------------------------------
    # Слоты обработки ответов сети
    # -------------------------------------------------------------------------

    def _on_tile_loaded(
        self,
        provider_id: str,
        z: int,
        x: int,
        y: int,
        data: bytes,
    ) -> None:
        """Обработка успешной загрузки тайла по сети."""
        # 1. Сохранение в дисковый кэш
        self._cache.put_tile(provider_id, z, x, y, data)

        # 2. Декодирование в QPixmap
        pixmap = QPixmap()
        if not pixmap.loadFromData(data):
            logger.warning("Не удалось декодировать полученный тайл %s/%d/%d/%d", provider_id, z, x, y)
            return

        # 3. Сохранение в LRU память
        self._put_mem_cache(provider_id, z, x, y, pixmap)

        # 4. Если тайл сейчас нужен на экране — отображаем его
        if (
            self.is_active
            and self._provider is not None
            and self._provider.id == provider_id
            and (z, x, y) in self._needed_tiles
        ):
            rect = tile_to_scene_rect(x, y, z)
            self._add_pixmap_item(z, x, y, rect, pixmap)
            self.tiles_updated.emit()

    def _on_tile_failed(
        self,
        provider_id: str,
        z: int,
        x: int,
        y: int,
        error_msg: str,
    ) -> None:
        """Обработка ошибки загрузки тайла."""
        logger.debug("Тайл %s/%d/%d/%d не загружен: %s", provider_id, z, x, y, error_msg)

    def _on_auth_error(self, provider_id: str) -> None:
        """Обработка ошибки авторизации (401/403)."""
        provider_name = self._provider.name if self._provider else provider_id
        logger.warning("Ошибка авторизации для провайдера: %s", provider_name)
        self.auth_error.emit(provider_name)

    def _on_loader_progress(self, in_flight: int, queued: int) -> None:
        """Пересылка прогресса загрузки."""
        self.loading_progress.emit(in_flight + queued)

    # -------------------------------------------------------------------------
    # LRU кэш в оперативной памяти
    # -------------------------------------------------------------------------

    def _get_mem_cache(self, provider_id: str, z: int, x: int, y: int) -> QPixmap | None:
        key = (provider_id, z, x, y)
        if key in self._mem_cache:
            self._mem_cache.move_to_end(key)
            return self._mem_cache[key]
        return None

    def _put_mem_cache(self, provider_id: str, z: int, x: int, y: int, pixmap: QPixmap) -> None:
        key = (provider_id, z, x, y)
        self._mem_cache[key] = pixmap
        self._mem_cache.move_to_end(key)
        if len(self._mem_cache) > self._mem_cache_capacity:
            self._mem_cache.popitem(last=False)

    # -------------------------------------------------------------------------
    # Рендеринг для экспорта карты в растр
    # -------------------------------------------------------------------------

    def render_tiles_to_painter(
        self,
        painter: QPainter,
        scene_rect: QRectF,
        meters_per_pixel: float,
    ) -> None:
        """Отрисовка доступных кэшированных тайлов в указанный QPainter при экспорте."""
        if not self.is_active or self._provider is None:
            return

        zoom = meters_per_pixel_to_zoom(
            meters_per_pixel,
            min_zoom=self._provider.min_zoom,
            max_zoom=self._provider.max_zoom,
        )

        min_x = scene_rect.left()
        max_x = scene_rect.right()
        min_y = -scene_rect.bottom()
        max_y = -scene_rect.top()

        tile_bounds = extent_to_tile_range(min_x, min_y, max_x, max_y, zoom)
        if tile_bounds is None:
            return

        min_tile_x, min_tile_y, max_tile_x, max_tile_y = tile_bounds

        for tx in range(min_tile_x, max_tile_x + 1):
            for ty in range(min_tile_y, max_tile_y + 1):
                rect = tile_to_scene_rect(tx, ty, zoom)
                # Берем из памяти или диска
                pix = self._get_mem_cache(self._provider.id, zoom, tx, ty)
                if pix is None:
                    data = self._cache.get_tile(self._provider.id, zoom, tx, ty)
                    if data:
                        pix = QPixmap()
                        if pix.loadFromData(data):
                            self._put_mem_cache(self._provider.id, zoom, tx, ty, pix)

                if pix is not None and not pix.isNull():
                    painter.drawPixmap(rect.toRect(), pix)
