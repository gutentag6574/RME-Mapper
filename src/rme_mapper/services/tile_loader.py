"""Асинхронный сетевой загрузчик тайлов на базе QNetworkAccessManager (TileLoader)."""

from collections import deque
import logging
from typing import Any

from PySide6.QtCore import QObject, QTimer, QUrl, Signal
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest

from rme_mapper.services.tile_cache import TileDiskCache

logger = logging.getLogger("rme_mapper.services.tile_loader")

APP_USER_AGENT = "GeoPoint Mapper/0.11.0 (+https://github.com/gutentag6574/RME-Mapper)"
DEFAULT_MAX_CONCURRENCY = 4
OSM_MAX_CONCURRENCY = 2  # Строгое соответствие OSM Tile Usage Policy (максимум 2 параллельных потока)
REQUEST_TIMEOUT_MS = 10_000  # 10 секунд таймаут


class TileLoader(QObject):
    """Асинхронный диспетчер загрузки тайлов онлайн-карт."""

    # Сигналы
    tile_loaded = Signal(str, int, int, int, bytes)        # provider_id, z, x, y, data
    tile_failed = Signal(str, int, int, int, int, str)     # provider_id, z, x, y, status_code, error_msg
    auth_error = Signal(str, str)                          # provider_id, error_message
    loading_progress = Signal(int, int)                    # in_flight_count, queued_count

    def __init__(
        self,
        network_manager: QNetworkAccessManager | None = None,
        parent: QObject | None = None,
        max_concurrency: int = DEFAULT_MAX_CONCURRENCY,
    ) -> None:
        super().__init__(parent)
        self._nam = network_manager if network_manager is not None else QNetworkAccessManager(self)
        self._max_concurrency = max_concurrency
        self._user_agent = APP_USER_AGENT

        # Очередь ожидающих запросов: deque[tuple[provider_id, z, x, y, url]]
        self._queue: deque[tuple[str, int, int, int, str]] = deque()
        # Активные запросы: key -> QNetworkReply
        self._in_flight: dict[str, QNetworkReply] = {}
        # Количество повторных попыток: key -> int
        self._retries: dict[str, int] = {}
        # Заблокированные провайдеры (при 401 / 403)
        self._auth_failed_providers: set[str] = set()

    @property
    def max_concurrency(self) -> int:
        return self._max_concurrency

    @max_concurrency.setter
    def max_concurrency(self, val: int) -> None:
        self._max_concurrency = max(1, val)

    @property
    def in_flight_count(self) -> int:
        return len(self._in_flight)

    @property
    def queue_count(self) -> int:
        return len(self._queue)

    @staticmethod
    def _make_key(provider_id: str, z: int, x: int, y: int) -> str:
        return f"{provider_id}/{z}/{x}/{y}"

    def reset_auth_status(self, provider_id: str | None = None) -> None:
        """Сброс состояния блокировки авторизации (например, при обновлении API-ключа)."""
        if provider_id:
            self._auth_failed_providers.discard(provider_id)
        else:
            self._auth_failed_providers.clear()

    def request_tile(self, provider_id: str, z: int, x: int, y: int, url: str) -> None:
        """Добавление запроса одного тайла в очередь (с дедупликацией)."""
        if provider_id in self._auth_failed_providers:
            return

        key = self._make_key(provider_id, z, x, y)
        if key in self._in_flight:
            return

        # Проверка наличия в очереди
        for item in self._queue:
            if item[0] == provider_id and item[1] == z and item[2] == x and item[3] == y:
                return

        self._queue.append((provider_id, z, x, y, url))
        self._process_queue()

    def request_tiles(self, tiles: list[tuple[str, int, int, int, str]]) -> None:
        """Пакетное добавление запросов тайлов."""
        for provider_id, z, x, y, url in tiles:
            self.request_tile(provider_id, z, x, y, url)

    def cancel_stale_requests(self, current_z: int, allowed_range: tuple[int, int, int, int] | None = None) -> None:
        """Очистка очереди от устаревших запросов при быстром скролле или смене зума."""
        new_queue: deque[tuple[str, int, int, int, str]] = deque()
        while self._queue:
            provider_id, z, x, y, url = self._queue.popleft()
            if z != current_z:
                continue
            if allowed_range is not None:
                min_tx, min_ty, max_tx, max_ty = allowed_range
                if not (min_tx <= x <= max_tx and min_ty <= y <= max_ty):
                    continue
            new_queue.append((provider_id, z, x, y, url))
        self._queue = new_queue
        self.loading_progress.emit(len(self._in_flight), len(self._queue))

    def clear_all(self) -> None:
        """Полная отмена всех активных и ожидающих запросов."""
        self._queue.clear()
        for reply in list(self._in_flight.values()):
            try:
                reply.abort()
                reply.deleteLater()
            except Exception:
                pass
        self._in_flight.clear()
        self._retries.clear()
        self.loading_progress.emit(0, 0)

    def _get_max_concurrency_for_provider(self, provider_id: str) -> int:
        """Определение лимита параллелизма (для OpenStreetMap строго 2)."""
        if "osm" in provider_id.lower():
            return min(self._max_concurrency, OSM_MAX_CONCURRENCY)
        return self._max_concurrency

    def _process_queue(self) -> None:
        """Запуск запросов из очереди до достижения лимита параллелизма."""
        while self._queue and len(self._in_flight) < self._max_concurrency:
            item = self._queue.popleft()
            provider_id, z, x, y, url = item

            if provider_id in self._auth_failed_providers:
                continue

            limit = self._get_max_concurrency_for_provider(provider_id)
            current_provider_in_flight = sum(
                1 for k in self._in_flight if k.startswith(f"{provider_id}/")
            )
            if current_provider_in_flight >= limit:
                # Откладываем в конец очереди, чтобы дать шанс другим провайдерам
                self._queue.append(item)
                break

            key = self._make_key(provider_id, z, x, y)
            self._start_request(key, provider_id, z, x, y, url)

        self.loading_progress.emit(len(self._in_flight), len(self._queue))

    def _start_request(self, key: str, provider_id: str, z: int, x: int, y: int, url_str: str) -> None:
        """Создание и отправка сетевого запроса QNetworkRequest."""
        qurl = QUrl(url_str)
        req = QNetworkRequest(qurl)
        req.setHeader(QNetworkRequest.KnownHeaders.UserAgentHeader, self._user_agent)
        req.setAttribute(QNetworkRequest.Attribute.Http2AllowedAttribute, True)
        req.setTransferTimeout(REQUEST_TIMEOUT_MS)

        reply = self._nam.get(req)
        self._in_flight[key] = reply

        # Замыкание параметров для слота завершения
        reply.finished.connect(
            lambda r=reply, k=key, p=provider_id, tz=z, tx=x, ty=y, u=url_str: self._on_reply_finished(
                r, k, p, tz, tx, ty, u
            )
        )

    def _on_reply_finished(
        self,
        reply: QNetworkReply,
        key: str,
        provider_id: str,
        z: int,
        x: int,
        y: int,
        url_str: str,
    ) -> None:
        """Обработка ответа QNetworkReply."""
        if key in self._in_flight and self._in_flight[key] == reply:
            del self._in_flight[key]

        status_code_var = reply.attribute(QNetworkRequest.Attribute.HttpStatusCodeAttribute)
        status_code = int(status_code_var) if status_code_var is not None else 0
        error = reply.error()

        data: bytes = b""
        try:
            data = bytes(reply.readAll())
        except Exception:
            data = b""

        # 1. Ошибки авторизации 401 и 403
        if status_code in (401, 403):
            self._auth_failed_providers.add(provider_id)
            # Очищаем все запросы для этого заблокированного провайдера
            self._queue = deque(it for it in self._queue if it[0] != provider_id)
            err_msg = "Ошибка доступа: проверьте API-ключ или права доступа к провайдеру."
            logger.warning("Ошибка %d для провайдера '%s'. Загрузка приостановлена.", status_code, provider_id)
            self.auth_error.emit(provider_id, err_msg)
            self.tile_failed.emit(provider_id, z, x, y, status_code, err_msg)

        # 2. Ошибка 429 (Too Many Requests / Rate limit)
        elif status_code == 429:
            err_msg = "Превышен лимит частоты запросов к тайловому серверу (HTTP 429)."
            logger.warning(err_msg)
            self.tile_failed.emit(provider_id, z, x, y, status_code, err_msg)

        # 3. Успешная загрузка HTTP 200
        elif error == QNetworkReply.NetworkError.NoError and (status_code == 200 or (status_code == 0 and len(data) > 0)):
            if TileDiskCache.is_valid_image(data):
                self._retries.pop(key, None)
                self.tile_loaded.emit(provider_id, z, x, y, data)
            else:
                logger.debug("Ответ для тайла %s не является поддерживаемым изображением", key)
                self.tile_failed.emit(provider_id, z, x, y, status_code, "Невалидное изображение")

        # 4. Временные сетевые сбои (5xx, таймаут, разрыв соединения) -> 1 повтор
        else:
            retry_count = self._retries.get(key, 0)
            if retry_count < 1 and status_code != 404:
                self._retries[key] = retry_count + 1
                logger.debug("Повторная попытка загрузки тайла %s (попытка %d)", key, retry_count + 1)
                self._queue.append((provider_id, z, x, y, url_str))
            else:
                self._retries.pop(key, None)
                err_text = reply.errorString() or f"HTTP {status_code}"
                logger.debug("Ошибка загрузки тайла %s: %s", key, err_text)
                self.tile_failed.emit(provider_id, z, x, y, status_code, err_text)

        reply.deleteLater()
        self._process_queue()
