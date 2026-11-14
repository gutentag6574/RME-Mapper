"""Скрипт валидации автономной сборки GeoPoint Mapper.

Проверяет структуру и целостность собранного пакета перед публикацией релиза.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import sys

def validate_release_dir(bundle_dir: Path) -> list[str]:
    """Проверка структуры автономного каталога приложения."""
    errors = []

    if not bundle_dir.is_dir():
        return [f"Каталог сборки не существует: {bundle_dir}"]

    # 1. Основной исполняемый файл
    exe_path = bundle_dir / "GeoPointMapper.exe"
    if not exe_path.exists():
        errors.append(f"Отсутствует основной исполняемый файл: {exe_path}")

    # Unversioned Windows ICU must come from the OS, not an unrelated build tool.
    if list(bundle_dir.rglob("icuuc.dll")):
        errors.append("Сторонняя icuuc.dll перекрывает системную ICU Windows и может блокировать загрузку QtWidgets")

    # 2. Qt Platform Plugin (qwindows.dll)
    qt_platform_found = any(
        (bundle_dir / p).exists()
        for p in [
            "PySide6/plugins/platforms/qwindows.dll",
            "_internal/PySide6/plugins/platforms/qwindows.dll",
            "platforms/qwindows.dll",
            "_internal/platforms/qwindows.dll",
        ]
    )
    if not qt_platform_found:
        # Проверяем рекурсивный поиск qwindows.dll
        matches = list(bundle_dir.rglob("qwindows.dll"))
        if not matches:
            errors.append("Отсутствует критический Qt плагин платформы: qwindows.dll")

    # 3. PROJ база данных (proj.db)
    proj_db_found = any(
        (bundle_dir / p).exists()
        for p in [
            "share/proj/proj.db",
            "_internal/share/proj/proj.db",
            "proj/proj.db",
            "_internal/proj/proj.db",
        ]
    )
    if not proj_db_found:
        matches = list(bundle_dir.rglob("proj.db"))
        if not matches:
            errors.append("Отсутствует обязательная база геодезических данных PROJ: proj.db")

    # 4. GDAL ресурсы (header.dxf)
    gdal_data_found = any(
        (bundle_dir / p).exists()
        for p in [
            "share/gdal/header.dxf",
            "_internal/share/gdal/header.dxf",
            "gdal/header.dxf",
            "_internal/gdal/header.dxf",
        ]
    )
    if not gdal_data_found:
        matches = list(bundle_dir.rglob("header.dxf"))
        if not matches:
            errors.append("Отсутствуют критические данные драйверов GDAL: header.dxf")

    # 5. Ресурсы приложения (иконки)
    icon_found = any(
        (bundle_dir / p).exists()
        for p in [
            "rme_mapper/resources/icon.ico",
            "_internal/rme_mapper/resources/icon.ico",
            "rme_mapper/resources/icon.png",
            "_internal/rme_mapper/resources/icon.png",
        ]
    )
    if not icon_found:
        matches = list(bundle_dir.rglob("icon.ico")) + list(bundle_dir.rglob("icon.png"))
        if not matches:
            errors.append("Отсутствуют официальные ресурсы/иконки приложения")

    # 6. Отсутствие запрещенных файлов разработки
    forbidden_patterns = [
        "**/.git",
        "**/.venv",
        "**/.pytest_cache",
        "**/__pycache__",
        "**/*.pyc",
        "**/tests",
        "**/scratch",
    ]
    for pattern in forbidden_patterns:
        found = list(bundle_dir.glob(pattern))
        if found:
            errors.append(f"Обнаружены запрещенные файлы разработки ({pattern}): {found[:3]}")

    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description="Валидация автономной сборки GeoPoint Mapper")
    parser.add_argument("bundle_dir", nargs="?", default="dist/GeoPointMapper", help="Путь к папке сборки")
    args = parser.parse_args()

    bundle_path = Path(args.bundle_dir).resolve()
    print(f"[*] Проверка каталога сборки: {bundle_path}")

    errors = validate_release_dir(bundle_path)
    if errors:
        print(f"[!] ОБНАРУЖЕНЫ ОШИБКИ ВАЛИДАЦИИ ({len(errors)}):", file=sys.stderr)
        for err in errors:
            print(f"    - {err}", file=sys.stderr)
        return 1

    print("[+] Валидация успешна: все обязательные runtime-компоненты на месте, запрещенные dev-файлы отсутствуют.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
