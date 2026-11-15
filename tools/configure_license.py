"""Настройка HTTPS-адреса публичного списка лицензий и открытого ключа проверки перед сборкой клиента."""
from __future__ import annotations

import argparse
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONFIG_FILE = ROOT / "src" / "rme_mapper" / "services" / "license_config.py"


def update_license_config(list_url: str, public_key_pem: str) -> Path:
    url = str(list_url or "").strip()
    if not url.startswith("https://"):
        raise ValueError("HTTPS-адрес публичного списка лицензий должен начинаться с https://")
    pem = str(public_key_pem or "").strip() + "\n"
    if "BEGIN PUBLIC KEY" not in pem or "PRIVATE KEY" in pem:
        raise ValueError("Передайте корректный открытый ключ Ed25519 (без закрытого ключа).")

    lines_escaped = "\n".join(f'    "{line}\\n"' for line in pem.strip().splitlines())
    content = (
        '"""Конфигурация проверки лицензий клиента GeoPoint Mapper (только открытый ключ и публичный HTTPS-адрес)."""\n'
        "from __future__ import annotations\n\n"
        "from typing import Final\n\n"
        'APP_ID: Final[str] = "geopoint-mapper"\n\n'
        "# Публичный HTTPS-адрес подписанного списка лицензий на GitHub (настраивается через tools/configure_license.py)\n"
        f'LICENSE_LIST_URL: Final[str] = "{url}"\n\n'
        "# Встроенный открытый ключ Ed25519 для проверки подписи списка лицензий\n"
        "LICENSE_PUBLIC_KEY_PEM: Final[str] = (\n"
        f"{lines_escaped}\n"
        ")\n\n"
        "# Максимально допустимая длительность автономной работы без сети (часы)\n"
        "OFFLINE_LEASE_MAX_HOURS: Final[int] = 72\n\n"
        "# Периодичность фоновой онлайн-проверки (секунды)\n"
        "BACKGROUND_CHECK_INTERVAL_SEC: Final[int] = 900\n"
    )
    CONFIG_FILE.write_text(content, encoding="utf-8")
    return CONFIG_FILE


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Настроить клиентский публичный ключ и HTTPS-адрес списка лицензий")
    parser.add_argument(
        "--list-url",
        required=True,
        help="Публичный HTTPS-адрес файла licenses.json (например, https://raw.githubusercontent.com/<user>/<repo>/main/licenses.json)",
    )
    parser.add_argument("--public-key", required=True, type=Path, help="Путь к public_key.pem")
    args = parser.parse_args(argv)
    pub_pem = args.public_key.read_text(encoding="utf-8")
    out = update_license_config(args.list_url, pub_pem)
    print(f"Обновлено: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
