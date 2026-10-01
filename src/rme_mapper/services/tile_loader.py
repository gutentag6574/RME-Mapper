"""Асинхронный сетевой загрузчик тайлов на базе QNetworkAccessManager (TileLoader)."""
from __future__ import annotations


from collections import deque
import email.utils
import logging
import re
import time
from typing import Any

from PySide6.QtCore import QByteArray, QObject, QTimer, QUrl, Signal
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest

from rme_mapper.app_info import APP_NAME, APP_VERSION
from rme_mapper.services.tile_cache import TileDiskCache

logger = logging.getLogger("rme_mapper.services.tile_loader")

APP_USER_AGENT = f"{APP_NAME}/{APP_VERSION} (+https://github.com/gutentag6574/RME-Mapper)"
DEFAULT_MAX_CONCURRENCY = 4
OSM_MAX_CONCURRENCY = 2  # Строгое соответствие OSM Tile Usage Policy (максимум 2 параллельных потока)
REQUEST_TIMEOUT_MS = 10_000  # 10 секунд таймаут


def sanitize_url(url: str) -> str:
    """Маскирование конфиденциальных токенов и параметров авторизации в URL для безопасного логирования."""
    if not url:
        return ""
    res = re.sub(r"([?&]access_token=)[^&]+", r"\1[REDACTED]", url)
    res = re.sub(r"([?&]api_key=)[^&]+", r"\1[REDACTED]", res)
    res = re.sub(r"([?&]key=)[^&]+", r"\1[REDACTED]", res)
    res = re.sub(r"pk\.[a-zA-Z0-9_\.-]+", "pk.[REDACTED]", res)
    res = re.sub(r"sk\.[a-zA-Z0-9_\.-]+", "sk.[REDACTED]", res)
    return res


def _safe_header(reply: QNetworkReply, name: str) -> str | None:
    """Безопасное извлечение заголовка из ответа (совместимо со всеми типами QNetworkReply и моками)."""
    for arg in (name, name.encode("utf-8")):
        try:
            val = reply.rawHeader(arg) if hasattr(reply, "rawHeader") else None
            if val is not None:
                if isinstance(val, QByteArray):
                    res = bytes(val).decode("utf-8", "ignore").strip()
                    if res:
                        return res
                elif isinstance(val, (bytes, bytearray)):
                    res = bytes(val).decode("utf-8", "ignore").strip()
                    if res:
                        return res
                else:
                    s = str(val).strip()
                    # Если str(val) вернул строковое представление QByteArray вида b'...'
                    if s.startswith("b'") and s.endswith("'"):
                        s = s[2:-1]
                    if s:
                        return s
        except Exception:
            continue
    return None


class TileLoader(QObject):
    """Асинхронный диспетчер загрузки тайлов онлайн-карт с поддержкой HTTP-кэширования и защиты токенов."""

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
        tile_cache: TileDiskCache | None = None,
    ) -> None:
        super().__init__(parent)
        self._nam = network_manager if network_manager is not None else QNetworkAccessManager(self)
        self._max_concurrency = max_concurrency
        self._user_agent = APP_USER_AGENT
        self._cache = tile_cache

        # Очередь ожидающих запросов: deque[tuple[provider_id, z, x, y, url]] (строго 5 элементов для совместимости)
        self._queue: deque[tuple[str, int, int, int, str]] = deque()
        # Множество ключей условных запросов (conditional: If-None-Match / If-Modified-Since)
        self._conditional_requests: set[str] = set()
        # Активные запросы: key -> QNetworkReply
        self._in_flight: dict[str, QNetworkReply] = {}
        # Количество повторных попыток: key -> int
        self._retries: dict[str, int] = {}
        # Заблокированные провайдеры (при 401 / 403)
        self._auth_failed_providers: set[str] = set()
        # Временный кулдаун провайдеров (при 429 Retry-After): provider_id -> timestamp окончания
        self._provider_cooldowns: dict[str, float] = {}

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

    def set_tile_cache(self, cache: TileDiskCache | None) -> None:
        """Привязка дискового кэша для поддержки условных запросов (ETag / 304)."""
        self._cache = cache

    @staticmethod
    def _make_key(provider_id: str, z: int, x: int, y: int) -> str:
        return f"{provider_id}/{z}/{x}/{y}"

    def reset_auth_status(self, provider_id: str | None = None) -> None:
        """Сброс состояния блокировки авторизации (например, при обновлении API-ключа)."""
        if provider_id:
            self._auth_failed_providers.discard(provider_id)
            self._provider_cooldowns.pop(provider_id, None)
        else:
            self._auth_failed_providers.clear()
            self._provider_cooldowns.clear()

    def request_tile(
        self,
        provider_id: str,
        z: int,
        x: int,
        y: int,
        url: str,
        conditional: bool = False,
    ) -> None:
        """Добавление запроса одного тайла в очередь (с дедупликацией и проверкой безопасности)."""
        # 1. Строгая проверка токена безопасности: sk... токены запрещены в клиентском приложении
        if "sk." in url:
            err_msg = "Секретные токены Mapbox (sk...) запрещены. Используйте только публичный токен (pk...)."
            logger.warning("Попытка использования secret token для провайдера '%s' отклонена.", provider_id)
            self._auth_failed_providers.add(provider_id)
            self.auth_error.emit(provider_id, err_msg)
            self.tile_failed.emit(provider_id, z, x, y, 401, err_msg)
            return

        if provider_id in self._auth_failed_providers:
            return

        # Проверка кулдауна 429
        if provider_id in self._provider_cooldowns:
            if time.time() < self._provider_cooldowns[provider_id]:
                return
            else:
                del self._provider_cooldowns[provider_id]

        key = self._make_key(provider_id, z, x, y)
        if key in self._in_flight:
            return

        # Проверка наличия в очереди
        for item in self._queue:
            if item[0] == provider_id and item[1] == z and item[2] == x and item[3] == y:
                return

        if conditional:
            self._conditional_requests.add(key)
        else:
            self._conditional_requests.discard(key)

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
        self._conditional_requests.clear()
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
        now = time.time()
        while self._queue and len(self._in_flight) < self._max_concurrency:
            item = self._queue.popleft()
            provider_id, z, x, y, url = item

            if provider_id in self._auth_failed_providers:
                continue

            if provider_id in self._provider_cooldowns:
                if now < self._provider_cooldowns[provider_id]:
                    # Провайдер еще на кулдауне (HTTP 429)
                    self._queue.append(item)
                    break
                else:
                    del self._provider_cooldowns[provider_id]

            limit = self._get_max_concurrency_for_provider(provider_id)
            current_provider_in_flight = sum(
                1 for k in self._in_flight if k.startswith(f"{provider_id}/")
            )
            if current_provider_in_flight >= limit:
                # Откладываем в конец очереди, чтобы дать шанс другим провайдерам
                self._queue.append(item)
                break

            key = self._make_key(provider_id, z, x, y)
            is_conditional = (key in self._conditional_requests)
            self._conditional_requests.discard(key)
            self._start_request(key, provider_id, z, x, y, url, conditional=is_conditional)

        self.loading_progress.emit(len(self._in_flight), len(self._queue))

    def _start_request(
        self,
        key: str,
        provider_id: str,
        z: int,
        x: int,
        y: int,
        url_str: str,
        conditional: bool = False,
    ) -> None:
        """Создание и отправка сетевого запроса QNetworkRequest."""
        qurl = QUrl(url_str)
        req = QNetworkRequest(qurl)
        req.setHeader(QNetworkRequest.KnownHeaders.UserAgentHeader, self._user_agent)
        req.setAttribute(QNetworkRequest.Attribute.Http2AllowedAttribute, True)
        req.setTransferTimeout(REQUEST_TIMEOUT_MS)

        # Поддержка условных запросов If-None-Match / If-Modified-Since
        if conditional and self._cache is not None:
            meta = self._cache.get_tile_metadata(provider_id, z, x, y)
            if meta:
                etag = meta.get("etag")
                if etag:
                    req.setRawHeader(b"If-None-Match", str(etag).encode("utf-8"))
                last_mod = meta.get("last_modified")
                if last_mod:
                    req.setRawHeader(b"If-Modified-Since", str(last_mod).encode("utf-8"))

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

        # Безопасное извлечение HTTP-заголовков
        etag = _safe_header(reply, "ETag")
        last_modified = _safe_header(reply, "Last-Modified")
        cache_control = _safe_header(reply, "Cache-Control")
        expires = _safe_header(reply, "Expires")
        content_type = (_safe_header(reply, "Content-Type") or "").lower()
        retry_after_raw = _safe_header(reply, "Retry-After")

        max_age = None
        if cache_control:
            m = re.search(r"max-age=(\d+)", cache_control)
            if m:
                try:
                    max_age = int(m.group(1))
                except ValueError:
                    pass

        metadata = {
            "etag": etag,
            "last_modified": last_modified,
            "cache_control": cache_control,
            "expires": expires,
            "max_age": max_age,
        }

        data: bytes = b""
        try:
            data = bytes(reply.readAll())
        except Exception:
            data = b""

        # 1. HTTP 304 Not Modified -> используем существующий кэш и обновляем метаданные
        if status_code == 304:
            self._retries.pop(key, None)
            if self._cache is not None:
                self._cache.touch_tile_metadata(provider_id, z, x, y, metadata)
                cached = self._cache.get_tile(provider_id, z, x, y)
                if cached is not None:
                    self.tile_loaded.emit(provider_id, z, x, y, cached)
                    reply.deleteLater()
                    self._process_queue()
                    return

        # 2. Ошибки авторизации 401 и 403
        if status_code in (401, 403):
            self._auth_failed_providers.add(provider_id)
            # Очищаем все запросы для этого заблокированного провайдера
            self._queue = deque(it for it in self._queue if it[0] != provider_id)
            err_msg = "Ошибка доступа: проверьте API-ключ или права доступа к провайдеру."
            logger.warning("Ошибка %d для провайдера '%s'. Загрузка приостановлена.", status_code, provider_id)
            self.auth_error.emit(provider_id, err_msg)
            self.tile_failed.emit(provider_id, z, x, y, status_code, err_msg)

        # 3. Ошибка 429 (Too Many Requests / Rate limit) с учетом Retry-After
        elif status_code == 429:
            cooldown = 30.0
            if retry_after_raw:
                try:
                    cooldown = float(int(retry_after_raw))
                except ValueError:
                    try:
                        exp_dt = email.utils.parsedate_to_datetime(retry_after_raw)
                        if exp_dt:
                            cooldown = max(5.0, exp_dt.timestamp() - time.time())
                    except Exception:
                        pass
            cooldown = max(5.0, min(cooldown, 300.0))
            self._provider_cooldowns[provider_id] = time.time() + cooldown
            err_msg = f"Превышен лимит частоты запросов к серверу (HTTP 429). Кулдаун {int(cooldown)} сек."
            logger.warning("Провайдер '%s': %s", provider_id, err_msg)
            self.tile_failed.emit(provider_id, z, x, y, status_code, err_msg)

        # 4. Отклонение ответов text/html даже со статусом 200 (страницы ошибок провайдеров/провайдеров-заглушек)
        elif "text/html" in content_type:
            logger.debug("Ответ для тайла %s содержит text/html вместо изображения", sanitize_url(key))
            self.tile_failed.emit(provider_id, z, x, y, status_code or 200, "Ответ содержит HTML вместо изображения")

        # 5. Успешная загрузка HTTP 200
        elif error == QNetworkReply.NetworkError.NoError and (status_code == 200 or (status_code == 0 and len(data) > 0)):
            if TileDiskCache.is_valid_image(data):
                self._retries.pop(key, None)
                if self._cache is not None:
                    self._cache.save_tile(provider_id, z, x, y, data, metadata=metadata)
                self.tile_loaded.emit(provider_id, z, x, y, data)
            else:
                logger.debug("Ответ для тайла %s не является поддерживаемым изображением", sanitize_url(key))
                self.tile_failed.emit(provider_id, z, x, y, status_code, "Невалидное изображение")

        # 6. Временные сетевые сбои (5xx, таймаут, разрыв соединения) -> 1 контролируемый повтор
        else:
            retry_count = self._retries.get(key, 0)
            if retry_count < 1 and status_code not in (404, 401, 403, 429):
                self._retries[key] = retry_count + 1
                logger.debug("Повторная попытка загрузки тайла %s (попытка %d)", sanitize_url(key), retry_count + 1)
                self._conditional_requests.discard(key)
                self._queue.append((provider_id, z, x, y, url_str))
            else:
                self._retries.pop(key, None)
                err_text = reply.errorString() or f"HTTP {status_code}"
                err_text = sanitize_url(err_text)
                logger.debug("Ошибка загрузки тайла %s: %s", sanitize_url(key), err_text)
                self.tile_failed.emit(provider_id, z, x, y, status_code, err_text)

        reply.deleteLater()
        self._process_queue()
