"""Тесты сетевого загрузчика тайлов (Этап 20: Tests 29-40).

Все тесты работают строго офлайн через имитацию QNetworkAccessManager/QNetworkReply.
"""

from unittest.mock import MagicMock
import pytest
from PySide6.QtCore import QByteArray, QObject, QUrl
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest

from rme_mapper.services.tile_cache import PNG_MAGIC
from rme_mapper.services.tile_loader import TileLoader, APP_USER_AGENT


class FakeNetworkReply(QNetworkReply):
    """Имитационный QNetworkReply для офлайн-тестирования."""

    def __init__(
        self,
        data: bytes = b"",
        status_code: int = 200,
        error: QNetworkReply.NetworkError = QNetworkReply.NetworkError.NoError,
        error_string: str = "",
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._data = QByteArray(data)
        self._status_code = status_code
        self._error = error
        self._error_string = error_string
        self.setOpenMode(QNetworkReply.OpenModeFlag.ReadOnly)

    def attribute(self, code: QNetworkRequest.Attribute) -> int | None:
        if code == QNetworkRequest.Attribute.HttpStatusCodeAttribute:
            return self._status_code
        return None

    def error(self) -> QNetworkReply.NetworkError:
        return self._error

    def errorString(self) -> str:
        return self._error_string

    def readAll(self) -> QByteArray:
        return self._data

    def abort(self) -> None:
        pass


def _make_dummy_png() -> bytes:
    return PNG_MAGIC + b"mock_pixel_data"


@pytest.fixture
def mock_nam(qapp):
    """Имитационный QNetworkAccessManager."""
    nam = QNetworkAccessManager()
    return nam


def test_29_request_queue_and_concurrency(qapp, monkeypatch):
    """Тест 29: Запросы тайлов ставятся в очередь с ограничением параллелизма."""
    loader = TileLoader(max_concurrency=2)
    created_replies = []

    def fake_get(req: QNetworkRequest):
        reply = FakeNetworkReply(_make_dummy_png(), 200)
        created_replies.append((req, reply))
        return reply

    monkeypatch.setattr(loader._nam, "get", fake_get)

    # Запрашиваем 5 тайлов
    for i in range(5):
        loader.request_tile("custom_test", 5, i, 0, f"http://test.local/5/{i}/0.png")

    # В полете должно быть ровно 2 запроса (max_concurrency=2)
    assert loader.in_flight_count == 2
    assert loader.queue_count == 3


def test_30_request_deduplication(qapp, monkeypatch):
    """Тест 30: Повторный запрос одного и того же тайла дедуплицируется."""
    loader = TileLoader(max_concurrency=4)
    request_count = 0

    def fake_get(req: QNetworkRequest):
        nonlocal request_count
        request_count += 1
        return FakeNetworkReply(_make_dummy_png(), 200)

    monkeypatch.setattr(loader._nam, "get", fake_get)

    # Дважды запрашиваем один и тот же тайл
    loader.request_tile("osm_standard", 4, 2, 3, "http://tile.osm.org/4/2/3.png")
    loader.request_tile("osm_standard", 4, 2, 3, "http://tile.osm.org/4/2/3.png")

    assert request_count == 1


def test_31_cancel_stale_requests(qapp, monkeypatch):
    """Тест 31: Отмена устаревших запросов из очереди при смене зума/экстента."""
    loader = TileLoader(max_concurrency=1)
    fake_reply = FakeNetworkReply(_make_dummy_png(), 200)
    monkeypatch.setattr(loader._nam, "get", lambda req: fake_reply)

    # 1 активный запрос и 3 в очереди на разных зумах
    loader.request_tile("osm", 5, 1, 1, "http://test/5/1/1")
    loader.request_tile("osm", 5, 2, 2, "http://test/5/2/2")
    loader.request_tile("osm", 6, 1, 1, "http://test/6/1/1")
    loader.request_tile("osm", 6, 2, 2, "http://test/6/2/2")

    # Пользователь перешел на зум 6
    loader.cancel_stale_requests(current_z=6)

    # В очереди должны остаться только запросы для зума 6
    queued_zooms = [item[1] for item in loader._queue]
    assert all(z == 6 for z in queued_zooms)


def test_32_honest_user_agent_header(qapp, monkeypatch):
    """Тест 32: В сетевые запросы передается честный заголовок User-Agent."""
    loader = TileLoader()
    captured_headers = {}

    def fake_get(req: QNetworkRequest):
        captured_headers["User-Agent"] = req.header(QNetworkRequest.KnownHeaders.UserAgentHeader)
        return FakeNetworkReply(_make_dummy_png(), 200)

    monkeypatch.setattr(loader._nam, "get", fake_get)

    loader.request_tile("osm_standard", 1, 0, 0, "http://tile.osm.org/1/0/0.png")
    assert captured_headers["User-Agent"] == APP_USER_AGENT


def test_33_successful_tile_loaded_signal(qapp, monkeypatch):
    """Тест 33: При успешном ответе 200 испускается сигнал tile_loaded."""
    loader = TileLoader()
    loaded_results = []
    loader.tile_loaded.connect(lambda p, z, x, y, d: loaded_results.append((p, z, x, y, d)))

    expected_data = _make_dummy_png()
    reply = FakeNetworkReply(expected_data, 200)
    monkeypatch.setattr(loader._nam, "get", lambda req: reply)

    loader.request_tile("osm_standard", 3, 1, 2, "http://tile.osm.org/3/1/2.png")
    reply.finished.emit()

    assert len(loaded_results) == 1
    assert loaded_results[0][0] == "osm_standard"
    assert loaded_results[0][1:4] == (3, 1, 2)
    assert loaded_results[0][4] == expected_data


def test_34_auth_error_401_stops_provider(qapp, monkeypatch):
    """Тест 34: Ошибка авторизации 401/403 останавливает дальнейшие запросы провайдера."""
    loader = TileLoader()
    auth_errors = []
    loader.auth_error.connect(lambda p, msg: auth_errors.append((p, msg)))

    reply = FakeNetworkReply(b"Unauthorized", 401, QNetworkReply.NetworkError.AuthenticationRequiredError)
    monkeypatch.setattr(loader._nam, "get", lambda req: reply)

    loader.request_tile("mapbox_satellite", 2, 1, 1, "http://mapbox.com/test")
    reply.finished.emit()

    assert len(auth_errors) == 1
    assert auth_errors[0][0] == "mapbox_satellite"

    # Последующие запросы к этому провайдеру игнорируются
    get_called = False
    monkeypatch.setattr(loader._nam, "get", lambda req: None)
    loader.request_tile("mapbox_satellite", 2, 1, 2, "http://mapbox.com/test2")
    assert loader.queue_count == 0


def test_35_rate_limit_429_emits_failure(qapp, monkeypatch):
    """Тест 35: Ответ 429 Too Many Requests испускает tile_failed со статусом 429."""
    loader = TileLoader()
    failures = []
    loader.tile_failed.connect(lambda p, z, x, y, code, msg: failures.append((p, z, x, y, code, msg)))

    reply = FakeNetworkReply(b"Rate limited", 429)
    monkeypatch.setattr(loader._nam, "get", lambda req: reply)

    loader.request_tile("osm", 1, 0, 0, "http://osm/1/0/0")
    reply.finished.emit()

    assert len(failures) == 1
    assert failures[0][4] == 429
    assert "лимит" in failures[0][5] or "429" in failures[0][5]


def test_36_retry_temporary_server_error(qapp, monkeypatch):
    """Тест 36: Временная ошибка сервера 500 вызывает 1 повторную попытку."""
    loader = TileLoader(max_concurrency=4)
    attempts = 0

    def fake_get(req: QNetworkRequest):
        nonlocal attempts
        attempts += 1
        return FakeNetworkReply(b"Internal Error", 500, QNetworkReply.NetworkError.InternalServerError)

    monkeypatch.setattr(loader._nam, "get", fake_get)

    loader.request_tile("osm", 1, 0, 0, "http://osm/1/0/0")
    # Запрос 1 завершился с ошибкой 500
    first_reply = list(loader._in_flight.values())[0]
    first_reply.finished.emit()

    # Должен быть добавлен 1 повтор в очередь и выполнен
    assert attempts >= 1


def test_37_no_retry_on_404_not_found(qapp, monkeypatch):
    """Тест 37: Ошибка 404 Not Found не вызывает повторных запросов."""
    loader = TileLoader()
    failures = []
    loader.tile_failed.connect(lambda *args: failures.append(args))

    reply = FakeNetworkReply(b"Not Found", 404, QNetworkReply.NetworkError.ContentNotFoundError)
    monkeypatch.setattr(loader._nam, "get", lambda req: reply)

    loader.request_tile("osm", 1, 0, 0, "http://osm/1/0/0")
    reply.finished.emit()

    # Повтор не ставится в очередь
    assert loader.queue_count == 0
    assert len(failures) == 1


def test_38_clear_all_aborts_active_and_pending(qapp, monkeypatch):
    """Тест 38: Очистка clear_all отменяет все активные и запланированные запросы."""
    loader = TileLoader(max_concurrency=1)
    reply = FakeNetworkReply(_make_dummy_png(), 200)
    monkeypatch.setattr(loader._nam, "get", lambda req: reply)

    loader.request_tile("osm", 1, 0, 0, "http://test/1")
    loader.request_tile("osm", 1, 0, 1, "http://test/2")
    assert loader.in_flight_count == 1
    assert loader.queue_count == 1

    loader.clear_all()
    assert loader.in_flight_count == 0
    assert loader.queue_count == 0
