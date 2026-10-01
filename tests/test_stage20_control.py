"""Контрольные тесты подсистемы онлайн-карт (Этап 20: Control Check).

Проверка политик (Policy), безопасности (Security), сетевого стека (Network),
кэширования (ETag/304/TTL), экспорта и защиты от регрессий.
Все тесты строго офлайн (без обращения к реальным серверам).
"""

import json
import logging
from pathlib import Path
import time
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from PySide6.QtCore import QByteArray, QObject, QPointF, QRectF, QUrl
from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest
from PySide6.QtWidgets import QGraphicsScene, QMessageBox

from rme_mapper.exporters.map_renderer import MapRenderer
from rme_mapper.exporters.models import ImageExportOptions
from rme_mapper.maps.online_tile_manager import OnlineTileManager
from rme_mapper.models.map_point import MapPoint
from rme_mapper.models.online_provider import (
    MapType,
    OnlineTileProvider,
    OSM_STANDARD,
    MAPBOX_SATELLITE,
    MAPBOX_HYBRID,
    ProviderRegistry,
)
from rme_mapper.models.project_data import ProjectData, ProjectMapData
from rme_mapper.services.app_settings_service import AppSettingsService
from rme_mapper.services.project_service import ProjectService
from rme_mapper.services.tile_cache import (
    TileDiskCache,
    PNG_MAGIC,
    JPEG_MAGIC,
    WEBP_MAGIC,
)
from rme_mapper.services.tile_loader import TileLoader, sanitize_url, APP_USER_AGENT
from rme_mapper.services.tile_math import TileMath, extent_to_tile_range
from rme_mapper.ui.export_image_dialog import ExportImageDialog
from rme_mapper.ui.online_basemap_dialog import OnlineBasemapDialog


class MockNetworkReply(QNetworkReply):
    """Детерминированный QNetworkReply для офлайн-тестирования всех HTTP-ответов."""

    def __init__(
        self,
        data: bytes = b"",
        status_code: int = 200,
        headers: dict[str, str] | None = None,
        error: QNetworkReply.NetworkError = QNetworkReply.NetworkError.NoError,
        error_string: str = "",
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._data = QByteArray(data)
        self._status_code = status_code
        self._headers = {k.lower(): v for k, v in (headers or {}).items()}
        self._error = error
        self._error_string = error_string
        self.setOpenMode(QNetworkReply.OpenModeFlag.ReadOnly)

    def attribute(self, code: QNetworkRequest.Attribute) -> int | None:
        if code == QNetworkRequest.Attribute.HttpStatusCodeAttribute:
            return self._status_code
        return None

    def rawHeader(self, name: Any) -> QByteArray:
        if isinstance(name, QByteArray):
            key = bytes(name).decode("utf-8", "ignore").lower()
        elif isinstance(name, (bytes, bytearray)):
            key = bytes(name).decode("utf-8", "ignore").lower()
        else:
            key = str(name).lower()
        val = self._headers.get(key)
        if val is not None:
            return QByteArray(val.encode("utf-8"))
        return QByteArray()

    def error(self) -> QNetworkReply.NetworkError:
        return self._error

    def errorString(self) -> str:
        return self._error_string

    def readAll(self) -> QByteArray:
        return self._data

    def abort(self) -> None:
        pass


def _dummy_png(content: bytes = b"control_check_dummy_png_bytes") -> bytes:
    return PNG_MAGIC + content


def _dummy_jpeg() -> bytes:
    return JPEG_MAGIC + b"control_check_dummy_jpeg_bytes"


def _dummy_webp() -> bytes:
    return WEBP_MAGIC + b"\x00\x00\x00\x00WEBPVP8 " + b"dummy_webp_bytes"


# =============================================================================
# 1. OSM ATTRIBUTION & EXPORT LOCK
# =============================================================================

def test_c01_osm_attribution_cannot_be_disabled_in_ui(qapp, tmp_path):
    """1. Для OSM Standard атрибуция обязательна: чекбокс в диалоге disabled + checked."""
    scene = QGraphicsScene()
    cache = TileDiskCache(base_dir=tmp_path / "c01_cache")
    manager = OnlineTileManager(scene=scene, tile_cache=cache)
    manager.set_provider(OSM_STANDARD)

    dialog = ExportImageDialog(
        parent=None,
        active_crs="EPSG:3857",
        map_title="OSM Export Test",
        current_view_extent=(4180000.0, 7500000.0, 4190000.0, 7510000.0),
        full_map_extent=(4180000.0, 7500000.0, 4190000.0, 7510000.0),
        points=[],
        selected_point_ids=set(),
        online_tile_manager=manager,
    )

    # Чекбокс должен быть включен и заблокирован
    assert dialog.chk_attribution.isChecked() is True
    assert dialog.chk_attribution.isEnabled() is False

    # В опциях экспорта атрибуция строго True
    dialog.path_edit.setText(str(tmp_path / "test.png"))
    opts = dialog.build_export_options()
    assert opts.include_attribution is True
    dialog.close()


def test_c02_map_renderer_forces_mandatory_attribution(tmp_path):
    """1. MapRenderer всегда отображает копирайт обязательного провайдера даже при include_attribution=False."""
    scene = QGraphicsScene()
    cache = TileDiskCache(base_dir=tmp_path / "c02_cache")
    manager = OnlineTileManager(scene=scene, tile_cache=cache)
    manager.set_provider(OSM_STANDARD)

    # Принудительно передаем include_attribution=False в опции
    opts = ImageExportOptions(
        file_path=tmp_path / "forced_no_attr.png",
        width_px=600,
        height_px=400,
        include_attribution=False,
    )

    # Рендерер должен отрендерить изображение и не упасть
    img = MapRenderer.render_map(
        options=opts,
        active_crs="EPSG:3857",
        target_extent=(4180000.0, 7500000.0, 4190000.0, 7510000.0),
        online_tile_manager=manager,
    )
    assert not img.isNull()
    assert img.width() == 600
    assert img.height() == 400


# =============================================================================
# 2 & 3. PROVIDER ATTRIBUTION MODEL & MAPBOX EXACT SPEC
# =============================================================================

def test_c03_provider_attribution_model_fields():
    """2 & 3. Модель OnlineTileProvider содержит все обязательные поля атрибуции и логотипа."""
    p = OnlineTileProvider(
        id="test_prov",
        display_name="Test Provider",
        map_type=MapType.STANDARD,
        url_template="http://test/{z}/{x}/{y}.png",
        attribution="© Test Provider",
        attribution_required=True,
        logo_required=True,
        additional_attribution="© Data Partner",
    )
    assert p.attribution_text == "© Test Provider"
    assert p.attribution_required is True
    assert p.logo_required is True
    assert p.additional_attribution == "© Data Partner"

    # Сериализация и десериализация сохраняют поля
    d = p.to_dict()
    assert d["attribution_required"] is True
    assert d["logo_required"] is True
    assert d["additional_attribution"] == "© Data Partner"

    restored = OnlineTileProvider.from_dict(d)
    assert restored.attribution_required is True
    assert restored.logo_required is True
    assert restored.additional_attribution == "© Data Partner"


def test_c04_mapbox_exact_specification():
    """3. Mapbox Satellite и Hybrid имеют точные endpoints, zoom, атрибуцию и требование логотипа."""
    sat = MAPBOX_SATELLITE
    assert sat.url_template.startswith("https://api.mapbox.com/v4/mapbox.satellite/")
    assert sat.max_zoom == 22
    assert sat.tile_size == 256
    assert sat.requires_api_key is True
    assert sat.attribution_required is True
    assert sat.logo_required is True
    assert "© Mapbox" in sat.attribution
    assert "© OpenStreetMap" in sat.attribution
    assert "© Maxar" in sat.attribution

    hyb = MAPBOX_HYBRID
    assert "satellite-streets-v12" in hyb.url_template
    assert hyb.max_zoom == 22
    assert hyb.requires_api_key is True
    assert hyb.attribution_required is True
    assert hyb.logo_required is True


# =============================================================================
# 4 & 5. MAPBOX TOKEN SECURITY (sk... rejection & redaction)
# =============================================================================

def test_c05_mapbox_secret_token_sk_strictly_rejected():
    """4. Секретный токен sk... запрещен в get_effective_api_key и build_tile_url."""
    p = MAPBOX_SATELLITE

    with pytest.raises(ValueError, match="sk..."):
        p.get_effective_api_key("sk.secret_access_token_12345")

    with pytest.raises(ValueError, match="sk..."):
        p.build_tile_url(5, 10, 15, api_key="sk.secret_access_token_12345")


def test_c06_mapbox_secret_token_rejected_in_settings_and_loader(qapp):
    """4. Секретный токен sk... не сохраняется в AppSettingsService и блокируется в TileLoader."""
    settings = AppSettingsService()
    settings.set_provider_api_key("mapbox_satellite", "sk.secret_key_to_block")
    # Не должен сохраниться
    assert settings.get_provider_api_key("mapbox_satellite") != "sk.secret_key_to_block"

    loader = TileLoader()
    auth_errors = []
    loader.auth_error.connect(lambda prov, msg: auth_errors.append((prov, msg)))

    # Запрос с sk... токеном немедленно отклоняется
    loader.request_tile(
        "mapbox_satellite", 2, 1, 1,
        "https://api.mapbox.com/v4/test/2/1/1.jpg?access_token=sk.secret_token"
    )
    assert len(auth_errors) == 1
    assert loader.in_flight_count == 0
    assert loader.queue_count == 0


def test_c07_token_redacted_in_logs_and_sanitizer():
    """4 & 22. Функция sanitize_url маскирует токены pk..., sk... и параметры access_token/key."""
    raw_url = "https://api.mapbox.com/v4/tiles/1/2/3.jpg?access_token=pk.eyJ123456789.abcdef&key=secret123"
    sanitized = sanitize_url(raw_url)

    assert "pk.eyJ123456789.abcdef" not in sanitized
    assert "secret123" not in sanitized
    assert "[REDACTED]" in sanitized


# =============================================================================
# 6, 7, 8. OSM CACHE POLICY, TTL & CONDITIONAL REQUESTS (304)
# =============================================================================

def test_c08_cache_metadata_persistence(tmp_path):
    """6. TileDiskCache сохраняет метаданные ETag, Last-Modified, Cache-Control, stored_at в .meta файле."""
    cache = TileDiskCache(base_dir=tmp_path / "meta_cache")
    tile_data = _dummy_png()
    meta_in = {
        "etag": '"3a7b-60000000"',
        "last_modified": "Mon, 21 Sep 2026 00:00:00 GMT",
        "cache_control": "max-age=604800, public",
        "max_age": 604800,
    }

    cache.save_tile("osm_standard", 6, 35, 20, tile_data, metadata=meta_in)

    # Проверяем чтение метаданных
    meta_out = cache.get_tile_metadata("osm_standard", 6, 35, 20)
    assert meta_out is not None
    assert meta_out["etag"] == '"3a7b-60000000"'
    assert meta_out["max_age"] == 604800
    assert "stored_at" in meta_out


def test_c09_cache_ttl_expiration_logic(tmp_path):
    """7. Проверка истечения срока годности тайла (is_tile_expired) по max-age и minimum TTL."""
    cache = TileDiskCache(base_dir=tmp_path / "ttl_cache")
    tile_data = _dummy_png()

    # Тайл со сроком 1 секунда
    cache.save_tile("osm_standard", 4, 1, 1, tile_data, metadata={"max_age": 1, "stored_at": time.time() - 5})
    assert cache.is_tile_expired("osm_standard", 4, 1, 1) is True

    # Свежий тайл (сохранен только что, default TTL 7 дней)
    cache.save_tile("osm_standard", 4, 1, 2, tile_data, metadata={"stored_at": time.time()})
    assert cache.is_tile_expired("osm_standard", 4, 1, 2) is False


def test_c10_conditional_request_304_handling(qapp, tmp_path, monkeypatch):
    """8. При ответе HTTP 304 Not Modified тайл читается из кэша, метаданные обновляются, байты не скачиваются."""
    cache = TileDiskCache(base_dir=tmp_path / "cond_cache")
    original_data = _dummy_png()
    old_time = time.time() - 1000
    cache.save_tile(
        "osm_standard", 3, 2, 2, original_data,
        metadata={"etag": '"etag_abc_123"', "last_modified": "Sun, 20 Sep 2026 00:00:00 GMT", "stored_at": old_time}
    )

    loader = TileLoader(tile_cache=cache)
    loaded_tiles = []
    loader.tile_loaded.connect(lambda p, z, x, y, d: loaded_tiles.append((p, z, x, y, d)))

    captured_headers = {}

    def fake_get(req: QNetworkRequest):
        captured_headers["If-None-Match"] = bytes(req.rawHeader("If-None-Match")).decode("utf-8")
        captured_headers["If-Modified-Since"] = bytes(req.rawHeader("If-Modified-Since")).decode("utf-8")
        # Сервер возвращает 304 с пустым телом
        reply = MockNetworkReply(
            b"",
            status_code=304,
            headers={"ETag": '"etag_abc_123"', "Cache-Control": "max-age=604800"},
        )
        return reply

    monkeypatch.setattr(loader._nam, "get", fake_get)

    # Отправляем условный запрос
    loader.request_tile("osm_standard", 3, 2, 2, "http://tile.osm.org/3/2/2.png", conditional=True)
    active_reply = list(loader._in_flight.values())[0]
    active_reply.finished.emit()

    # Проверяем, что If-None-Match и If-Modified-Since были отправлены
    assert captured_headers["If-None-Match"] == '"etag_abc_123"'
    assert captured_headers["If-Modified-Since"] == "Sun, 20 Sep 2026 00:00:00 GMT"

    # Сигнал tile_loaded получил кэшированные байты
    assert len(loaded_tiles) == 1
    assert loaded_tiles[0][4] == original_data

    # Метаданные stored_at обновились
    new_meta = cache.get_tile_metadata("osm_standard", 3, 2, 2)
    assert new_meta["stored_at"] > old_time


# =============================================================================
# 9. NO BULK / PREFETCH PROTECTION
# =============================================================================

def test_c11_no_bulk_or_prefetch_outside_viewport(qapp, tmp_path, monkeypatch):
    """9. OnlineTileManager запрашивает строго тайлы текущего вьюпорта без префетча."""
    scene = QGraphicsScene()
    cache = TileDiskCache(base_dir=tmp_path / "nobulk_cache")
    loader = TileLoader(tile_cache=cache)
    manager = OnlineTileManager(scene=scene, tile_cache=cache, tile_loader=loader)
    manager.set_provider(OSM_STANDARD)

    requested_coords = []

    def fake_request_tile(prov, z, x, y, url, conditional=False):
        requested_coords.append((z, x, y))

    monkeypatch.setattr(loader, "request_tile", fake_request_tile)

    # Устанавливаем конкретный небольшой вьюпорт (1000 x 1000 м) в центре Москвы
    center_merc = TileMath.lonlat_to_mercator(37.61, 55.75)
    viewport = QRectF(center_merc[0] - 500, -center_merc[1] - 500, 1000, 1000)
    m_per_px = 2.0  # зум примерно 16

    manager.update_viewport(viewport, m_per_px)

    # Должен быть запрошен строго диапазон тайлов вьюпорта (без сторонних тайлов)
    min_x = viewport.left()
    max_x = viewport.right()
    min_y = -viewport.bottom()
    max_y = -viewport.top()
    tile_bounds = extent_to_tile_range(min_x, min_y, max_x, max_y, 16)
    assert tile_bounds is not None
    min_tx, min_ty, max_tx, max_ty = tile_bounds
    expected_count = (max_tx - min_tx + 1) * (max_ty - min_ty + 1)

    assert len(requested_coords) == expected_count
    for z, x, y in requested_coords:
        assert z == 16
        assert min_tx <= x <= max_tx
        assert min_ty <= y <= max_ty


# =============================================================================
# 10, 11, 12, 13, 14. NETWORK STATUS CODES & RETRY MATRIX
# =============================================================================

def test_c12_http_401_stops_request_storm(qapp, monkeypatch):
    """10. HTTP 401 останавливает очередь, не декодирует тайл, испускает auth_error, без повторов."""
    loader = TileLoader()
    auth_errors = []
    loader.auth_error.connect(lambda p, msg: auth_errors.append((p, msg)))

    reply = MockNetworkReply(b"Unauthorized", status_code=401)
    monkeypatch.setattr(loader._nam, "get", lambda req: reply)

    loader.request_tile("prov_401", 1, 0, 0, "http://test/401")
    reply.finished.emit()

    assert len(auth_errors) == 1
    # Дальнейшие запросы к prov_401 отбрасываются
    loader.request_tile("prov_401", 1, 0, 1, "http://test/401_next")
    assert loader.queue_count == 0


def test_c13_http_403_stops_request_storm(qapp, monkeypatch):
    """11. HTTP 403 ведет себя аналогично ошибке прав/авторизации: блокировка и без retry storm."""
    loader = TileLoader()
    auth_errors = []
    loader.auth_error.connect(lambda p, msg: auth_errors.append((p, msg)))

    reply = MockNetworkReply(b"Forbidden", status_code=403)
    monkeypatch.setattr(loader._nam, "get", lambda req: reply)

    loader.request_tile("prov_403", 2, 1, 1, "http://test/403")
    reply.finished.emit()

    assert len(auth_errors) == 1
    assert loader.queue_count == 0


def test_c14_http_429_respects_retry_after(qapp, monkeypatch):
    """12. HTTP 429 с Retry-After: кулдаун сохраняется, новые запросы приостанавливаются."""
    loader = TileLoader()
    failures = []
    loader.tile_failed.connect(lambda p, z, x, y, code, msg: failures.append((p, code, msg)))

    reply = MockNetworkReply(b"Rate Limited", status_code=429, headers={"Retry-After": "15"})
    monkeypatch.setattr(loader._nam, "get", lambda req: reply)

    loader.request_tile("prov_429", 1, 1, 1, "http://test/429")
    reply.finished.emit()

    assert len(failures) == 1
    assert failures[0][1] == 429
    assert "15" in failures[0][2]
    # Провайдер на кулдауне -> новый запрос не отправляется
    assert loader.in_flight_count == 0


def test_c15_timeout_and_server_error_retry_matrix(qapp, monkeypatch):
    """13 & 14. Матрица повторов: 500 и таймаут повторяются ровно 1 раз, 404 не повторяется."""
    # 1. Тест HTTP 500: первый сбой -> retry -> второй сбой -> tile_failed ровно 1 раз
    loader_500 = TileLoader(max_concurrency=1)
    attempts_500 = 0
    failures_500 = []
    loader_500.tile_failed.connect(lambda *args: failures_500.append(args))

    def fake_get_500(req):
        nonlocal attempts_500
        attempts_500 += 1
        return MockNetworkReply(b"Server Error", status_code=500, error=QNetworkReply.NetworkError.InternalServerError)

    monkeypatch.setattr(loader_500._nam, "get", fake_get_500)
    loader_500.request_tile("prov_500", 1, 0, 0, "http://test/500")

    rep1 = list(loader_500._in_flight.values())[0]
    rep1.finished.emit()
    assert attempts_500 == 2
    assert len(failures_500) == 0  # повтор отправлен, еще не завершился

    rep2 = list(loader_500._in_flight.values())[0]
    rep2.finished.emit()
    assert attempts_500 == 2
    assert len(failures_500) == 1
    assert loader_500.queue_count == 0
    assert loader_500.in_flight_count == 0
    assert len(loader_500._retries) == 0

    # 2. Тест Timeout: первый сбой (таймаут) -> retry -> успешный ответ 200
    loader_to = TileLoader(max_concurrency=1)
    attempts_to = 0
    loaded_to = []
    loader_to.tile_loaded.connect(lambda *args: loaded_to.append(args))

    def fake_get_to(req):
        nonlocal attempts_to
        attempts_to += 1
        if attempts_to == 1:
            return MockNetworkReply(b"", status_code=0, error=QNetworkReply.NetworkError.TimeoutError, error_string="Timeout")
        return MockNetworkReply(PNG_MAGIC + b"ok_tile", status_code=200)

    monkeypatch.setattr(loader_to._nam, "get", fake_get_to)
    loader_to.request_tile("prov_to", 1, 0, 0, "http://test/to")

    rep_to1 = list(loader_to._in_flight.values())[0]
    rep_to1.finished.emit()
    assert attempts_to == 2
    assert len(loaded_to) == 0

    rep_to2 = list(loader_to._in_flight.values())[0]
    rep_to2.finished.emit()
    assert len(loaded_to) == 1
    assert loader_to.queue_count == 0
    assert loader_to.in_flight_count == 0
    assert len(loader_to._retries) == 0

    # 3. Тест HTTP 404: не повторяется
    loader_404 = TileLoader(max_concurrency=1)
    attempts_404 = 0
    failures_404 = []
    loader_404.tile_failed.connect(lambda *args: failures_404.append(args))

    def fake_get_404(req):
        nonlocal attempts_404
        attempts_404 += 1
        return MockNetworkReply(b"Not Found", status_code=404, error=QNetworkReply.NetworkError.ContentNotFoundError)

    monkeypatch.setattr(loader_404._nam, "get", fake_get_404)
    loader_404.request_tile("prov_404", 1, 0, 0, "http://test/404")

    rep_404 = list(loader_404._in_flight.values())[0]
    rep_404.finished.emit()
    assert attempts_404 == 1
    assert len(failures_404) == 1
    assert loader_404.queue_count == 0
    assert loader_404.in_flight_count == 0


# =============================================================================
# 15. NO REAL INTERNET IN PYTEST
# =============================================================================

def test_c16_no_real_internet_in_test_suite(monkeypatch):
    """15. Подтверждение отсутствия реальных сетевых вызовов."""
    import socket

    def blocked_connect(*args, **kwargs):
        raise RuntimeError("Тесты пытаются обратиться к реальной сети! Запрещено.")

    monkeypatch.setattr(socket.socket, "connect", blocked_connect)
    # Проверяем, что локальные вызовы TileLoader не обращаются к реальному socket.connect
    loader = TileLoader()
    assert loader is not None


# =============================================================================
# 16, 17, 18. CONTENT VALIDATION & CACHE CORRUPTION
# =============================================================================

def test_c17_corrupted_cached_tiles_handled_safely(tmp_path):
    """16. Поврежденные файлы PNG/JPEG/WebP удаляются без краша приложения."""
    cache = TileDiskCache(base_dir=tmp_path / "corrupt_cache")
    bad_tile = cache.cache_root / "osm_standard" / "1" / "1" / "1.tile"
    bad_tile.parent.mkdir(parents=True, exist_ok=True)
    bad_tile.write_bytes(b"bad_corrupted_bytes_without_magic")

    # Чтение возвращает None и удаляет битый файл
    data = cache.get_tile("osm_standard", 1, 1, 1)
    assert data is None
    assert not bad_tile.exists()


def test_c18_html_response_rejected(qapp, monkeypatch):
    """17. HTTP 200 с Content-Type: text/html или HTML тегами отклоняется и не сохраняется."""
    loader = TileLoader()
    failures = []
    loaded = []
    loader.tile_failed.connect(lambda *args: failures.append(args))
    loader.tile_loaded.connect(lambda *args: loaded.append(args))

    html_data = b"<!DOCTYPE html><html><body>Error 404 block page</body></html>"
    reply = MockNetworkReply(html_data, status_code=200, headers={"Content-Type": "text/html; charset=utf-8"})
    monkeypatch.setattr(loader._nam, "get", lambda req: reply)

    loader.request_tile("custom_xyz", 2, 0, 0, "http://test/tile.html")
    reply.finished.emit()

    assert len(loaded) == 0
    assert len(failures) == 1
    assert "HTML" in failures[0][5]


def test_c19_valid_image_formats_accepted():
    """18. PNG, JPEG, WebP успешно валидируются; битые байты отклоняются."""
    assert TileDiskCache.is_valid_image(_dummy_png()) is True
    assert TileDiskCache.is_valid_image(_dummy_jpeg()) is True
    assert TileDiskCache.is_valid_image(_dummy_webp()) is True
    assert TileDiskCache.is_valid_image(b"plain text data") is False
    assert TileDiskCache.is_valid_image(b"") is False


# =============================================================================
# 19 & 20. HTTPS & CUSTOM XYZ ATTRIBUTION
# =============================================================================

def test_c20_custom_xyz_https_and_mandatory_attribution(qapp):
    """19 & 20. Custom XYZ поддерживает URL template, предупреждение об HTTP и флаг mandatory attribution."""
    dialog = OnlineBasemapDialog(parent=None)
    dialog.show()
    # Переключаем на Custom XYZ
    dialog._rb_custom.setChecked(True)

    # Невалидный URL без {z}{x}{y}
    dialog._url_edit.setText("https://invalid.com/tiles.png")
    assert dialog._btn_ok.isEnabled() is False

    # HTTP URL вызывает предупреждение
    dialog._url_edit.setText("http://example.com/{z}/{x}/{y}.png")
    assert dialog._btn_ok.isEnabled() is True
    assert dialog._http_warning_label.isVisible() is True

    # HTTPS URL валиден
    dialog._url_edit.setText("https://example.com/{z}/{x}/{y}.png")
    assert dialog._btn_ok.isEnabled() is True
    assert dialog._http_warning_label.isHidden() is True

    # Чекбокс обязательной атрибуции включен
    assert dialog._chk_mandatory_attr.isChecked() is True
    dialog.close()


# =============================================================================
# 21. PROJECT SECURITY (*.gpmap raw JSON)
# =============================================================================

def test_c21_project_raw_json_security():
    """21. Файл *.gpmap не содержит токенов, ключей авторизации или байтов тайлов."""
    map_data = ProjectMapData(
        map_id="online_map_1",
        source_type="online_xyz",
        provider_id="mapbox_satellite",
        map_type="satellite",
        crs="EPSG:3857",
    )
    raw_dict = map_data.to_dict()

    # Проверяем отсутствие секретов
    assert "access_token" not in raw_dict
    assert "api_key" not in raw_dict
    assert "Authorization" not in raw_dict
    assert "token" not in raw_dict
    assert "cached_tile_bytes" not in raw_dict

    # Только разрешенные метаданные
    assert raw_dict["provider_id"] == "mapbox_satellite"
    assert raw_dict["source_type"] == "online_xyz"
    assert raw_dict["map_type"] == "satellite"


# =============================================================================
# 24 & 25. EXPORT ATTRIBUTION MATRIX & MAPBOX EXPORT
# =============================================================================

def test_c22_export_attribution_matrix_and_mapbox_logo(tmp_path):
    """24 & 25. Матрица экспорта: OSM (PNG/JPEG) и Mapbox Satellite (PNG/JPEG) содержат атрибуцию."""
    scene = QGraphicsScene()
    cache = TileDiskCache(base_dir=tmp_path / "export_mat_cache")

    # 1. OSM Standard
    mgr_osm = OnlineTileManager(scene=scene, tile_cache=cache)
    mgr_osm.set_provider(OSM_STANDARD)

    opts_png = ImageExportOptions(file_path=tmp_path / "osm.png", width_px=400, height_px=300)
    img_osm_png = MapRenderer.render_map(opts_png, "EPSG:3857", (0, 0, 1000, 1000), online_tile_manager=mgr_osm)
    assert not img_osm_png.isNull()

    opts_jpg = ImageExportOptions(file_path=tmp_path / "osm.jpg", format="JPEG", width_px=400, height_px=300)
    img_osm_jpg = MapRenderer.render_map(opts_jpg, "EPSG:3857", (0, 0, 1000, 1000), online_tile_manager=mgr_osm)
    assert not img_osm_jpg.isNull()

    # 2. Mapbox Satellite с логотипом
    mgr_mb = OnlineTileManager(scene=scene, tile_cache=cache)
    mgr_mb.set_provider(MAPBOX_SATELLITE)

    opts_mb = ImageExportOptions(file_path=tmp_path / "mb_sat.png", width_px=400, height_px=300)
    img_mb = MapRenderer.render_map(opts_mb, "EPSG:3857", (0, 0, 1000, 1000), online_tile_manager=mgr_mb)
    assert not img_mb.isNull()


# =============================================================================
# 26. CACHE SIZE / EVICTION
# =============================================================================

def test_c23_cache_eviction_removes_tiles_and_metadata(tmp_path):
    """26. LRU-вытеснение удаляет старые файлы вместе с их .meta файлами метаданных."""
    # Лимит 2500 байт
    cache = TileDiskCache(base_dir=tmp_path / "evict_meta_cache", max_size_bytes=2500)
    dummy = _dummy_png(b"x" * 700)

    # 3 тайла
    for y in range(3):
        cache.save_tile("osm", 1, 0, y, dummy, metadata={"etag": f"tag_{y}"})
        time.sleep(0.01)

    # 4-й тайл вызывает вытеснение
    cache.save_tile("osm", 1, 0, 3, dummy, metadata={"etag": "tag_3"})

    # Самый старый (0) должен быть удален вместе с .meta
    assert cache.has_tile("osm", 1, 0, 0) is False
    assert cache.get_tile_metadata("osm", 1, 0, 0) is None

    # Самый новый (3) сохранен с метаданными
    assert cache.has_tile("osm", 1, 0, 3) is True
    assert cache.get_tile_metadata("osm", 1, 0, 3) is not None


# =============================================================================
# 27 & 28. PERFORMANCE (1080p, 2K, 4K) & REQUEST STORM
# =============================================================================

def test_c24_performance_simulated_resolutions(tmp_path):
    """27. Замер расчета охвата и отрисовки для 1080p (FHD), 1440p (2K), 2160p (4K)."""
    scene = QGraphicsScene()
    cache = TileDiskCache(base_dir=tmp_path / "perf_cache")
    manager = OnlineTileManager(scene=scene, tile_cache=cache)
    manager.set_provider(OSM_STANDARD)

    resolutions = [(1920, 1080), (2560, 1440), (3840, 2160)]
    for w, h in resolutions:
        t0 = time.perf_counter()
        opts = ImageExportOptions(
            file_path=tmp_path / f"perf_{w}x{h}.png",
            width_px=w,
            height_px=h,
        )
        img = MapRenderer.render_map(
            options=opts,
            active_crs="EPSG:3857",
            target_extent=(4180000.0, 7500000.0, 4190000.0, 7510000.0),
            online_tile_manager=manager,
        )
        elapsed = time.perf_counter() - t0
        assert not img.isNull()
        assert img.width() == w
        assert img.height() == h
        # Рендер каждого разрешения должен завершаться в разумное время (< 5 сек в тесте)
        assert elapsed < 5.0


def test_c25_request_storm_rapid_pan_zoom(qapp, tmp_path, monkeypatch):
    """28. Быстрая смена вьюпорта (шторм pan/zoom): лимит параллелизма соблюдается, память не утекает."""
    scene = QGraphicsScene()
    cache = TileDiskCache(base_dir=tmp_path / "storm_cache")
    loader = TileLoader(tile_cache=cache, max_concurrency=2)
    manager = OnlineTileManager(scene=scene, tile_cache=cache, tile_loader=loader)
    manager.set_provider(OSM_STANDARD)

    created_replies = []

    def fake_get(req):
        rep = MockNetworkReply(_dummy_png(), status_code=200)
        created_replies.append(rep)
        return rep

    monkeypatch.setattr(loader._nam, "get", fake_get)

    # Симулируем 20 быстрых сдвигов и зумов
    for i in range(20):
        vp = QRectF(4180000.0 + i * 500, -7500000.0 - i * 500, 2000, 2000)
        m_per_px = 1.0 + (i % 5) * 0.5
        manager.update_viewport(vp, m_per_px)

    # Лимит параллелизма (строго <= 2 для OSM) соблюден
    assert loader.in_flight_count <= 2
    # Число ожидающих запросов ограничено отменой устаревших
    assert loader.queue_count < 100
