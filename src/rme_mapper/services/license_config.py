"""Конфигурация проверки лицензий клиента GeoPoint Mapper (только открытый ключ и публичный HTTPS-адрес)."""
from __future__ import annotations

from typing import Final

APP_ID: Final[str] = "geopoint-mapper"

# Публичный HTTPS-адрес подписанного списка лицензий на GitHub (настраивается через tools/configure_license.py)
LICENSE_LIST_URL: Final[str] = "https://raw.githubusercontent.com/gutentag6574/geopoint-mapper-licenses/main/licenses.json"

# Встроенный открытый ключ Ed25519 для проверки подписи списка лицензий
LICENSE_PUBLIC_KEY_PEM: Final[str] = (
    "-----BEGIN PUBLIC KEY-----\n"
    "MCowBQYDK2VwAyEAEJ/3/kfTsomRKfoxUtX7h1oeVwJIqML4BGf0sag76bg=\n"
    "-----END PUBLIC KEY-----\n"
)

# Максимально допустимая длительность автономной работы без сети (часы)
OFFLINE_LEASE_MAX_HOURS: Final[int] = 72

# Периодичность фоновой онлайн-проверки (секунды)
BACKGROUND_CHECK_INTERVAL_SEC: Final[int] = 900
