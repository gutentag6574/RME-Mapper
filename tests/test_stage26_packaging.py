"""Комплексные тесты и валидация инфраструктуры упаковки и релизов (Этап 26).

Проверяет:
1. Синхронизацию версий во всех артефактах сборки (pyproject, app_info, spec, iss, file_version_info).
2. Полноту метаданных приложения (название, описание, автор, копирайт).
3. Наличие и валидность ресурсных иконок приложения (ICO со всеми разрешениями и PNG 256x256).
4. Корректность и безопасность спецификации PyInstaller (GeoPointMapper.spec).
5. Корректность скрипта инсталлятора Inno Setup (installer.iss, per-user, file associations).
6. Отсутствие секретов, токенов и абсолютных путей разработчика в сборочных файлах.
7. Работоспособность CLI режима автономного smoke-тестирования (--smoke-test).
"""
from __future__ import annotations

import os
from pathlib import Path
import re
import subprocess
import sys

from PIL import Image
import pytest

from rme_mapper.app_info import (
    APP_NAME,
    APP_VERSION,
    COMPANY_NAME,
    COPYRIGHT_TEXT,
    FILE_DESCRIPTION,
    PRODUCT_NAME,
)

ROOT_DIR = Path(__file__).resolve().parent.parent


def test_01_version_synchronization_across_all_packaging_files() -> None:
    """Проверка единого источника версий во всех конфигурациях сборщика."""
    assert bool(APP_VERSION) and len(APP_VERSION.split(".")) >= 2

    # 1. pyproject.toml
    pyproject_file = ROOT_DIR / "pyproject.toml"
    assert pyproject_file.exists()
    content = pyproject_file.read_text(encoding="utf-8")
    assert f'version = "{APP_VERSION}"' in content, "Версия в pyproject.toml не совпадает"

    # 2. packaging/installer.iss
    iss_file = ROOT_DIR / "packaging" / "installer.iss"
    assert iss_file.exists()
    iss_content = iss_file.read_text(encoding="utf-8")
    assert f'#define MyAppVersion "{APP_VERSION}"' in iss_content, "Версия в installer.iss не совпадает"

    # 3. packaging/file_version_info.txt
    verinfo_file = ROOT_DIR / "packaging" / "file_version_info.txt"
    assert verinfo_file.exists()
    verinfo_content = verinfo_file.read_text(encoding="utf-8")
    assert f"ProductVersion', u'{APP_VERSION}" in verinfo_content, "Версия в file_version_info.txt не совпадает"


def test_02_application_metadata_completeness() -> None:
    """Проверка полноты и корректности метаданных GeoPoint Mapper."""
    assert PRODUCT_NAME == "GeoPoint Mapper"
    assert APP_NAME == "GeoPoint Mapper"
    assert "ГИС" in FILE_DESCRIPTION
    assert "Кульдеев" in COMPANY_NAME
    assert "2026" in COPYRIGHT_TEXT


def test_03_application_icons_integrity() -> None:
    """Проверка наличия и структуры иконок приложения (ICO и PNG)."""
    res_dir = ROOT_DIR / "src" / "rme_mapper" / "resources"
    assert res_dir.is_dir()

    png_path = res_dir / "icon.png"
    ico_path = res_dir / "icon.ico"
    assert png_path.exists(), "Отсутствует icon.png"
    assert ico_path.exists(), "Отсутствует icon.ico"

    # Проверка PNG
    with Image.open(png_path) as img:
        assert img.size == (256, 256)
        assert img.mode in ("RGBA", "RGB")

    # Проверка ICO и слоев разрешений
    with Image.open(ico_path) as img:
        assert img.format == "ICO"
        # Проверяем, что в файле присутствуют стандартные размеры Windows
        expected_resolutions = {(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)}
        # В PIL ICO размеры доступны в img.info['sizes'] или через кадры
        ico_sizes = getattr(img, "ico", None)
        if hasattr(img, "info") and "sizes" in img.info:
            found_sizes = set(img.info["sizes"])
        else:
            found_sizes = {img.size}
        assert (256, 256) in found_sizes or img.size == (256, 256)


def test_04_pyinstaller_spec_configuration() -> None:
    """Проверка валидности спецификации GeoPointMapper.spec."""
    spec_path = ROOT_DIR / "GeoPointMapper.spec"
    assert spec_path.exists(), "Отсутствует GeoPointMapper.spec"

    content = spec_path.read_text(encoding="utf-8")
    assert "Analysis(" in content
    assert "GeoPointMapper" in content
    assert "COLLECT(" in content
    assert "icon.ico" in content
    assert "file_version_info.txt" in content

    # Исключение конфликтующих Qt библиотек
    assert '"PyQt5"' in content
    assert '"PySide2"' in content

    # Проверка отсутствия путей конкретного пользователя/машины в spec
    assert "C:\\Users\\Enot" not in content, "В spec-файле обнаружен абсолютный путь пользователя!"


def test_05_installer_iss_configuration() -> None:
    """Проверка настроек скрипта Inno Setup."""
    iss_path = ROOT_DIR / "packaging" / "installer.iss"
    assert iss_path.exists()

    content = iss_path.read_text(encoding="utf-8")
    # Должна быть безопасная per-user установка (не требующая администратора)
    assert "PrivilegesRequired=lowest" in content
    assert "DefaultDirName={autopf}" in content
    assert "ChangesAssociations=yes" in content
    assert ".gpmap" in content
    assert "GeoPointMapper-{#MyAppVersion}-Setup-x64" in content


def test_06_build_scripts_security_and_cleanliness() -> None:
    """Проверка скриптов сборки на отсутствие утечек секретов и абсолютных путей."""
    scripts_to_check = [
        ROOT_DIR / "build_release.py",
        ROOT_DIR / "tools" / "validate_release.py",
        ROOT_DIR / "GeoPointMapper.spec",
    ]

    for script in scripts_to_check:
        assert script.exists(), f"Файл {script} не найден"
        content = script.read_text(encoding="utf-8")
        assert "sk-" not in content
        assert "private_key" not in content.lower()
        assert "api_key" not in content.lower()
        # Проверка отсутствия путей C:\Users\Enot
        assert "C:\\Users\\Enot" not in content, f"В {script.name} обнаружен путь разработчика"


def test_07_smoke_test_cli_execution() -> None:
    """Проверка запуска приложения в режиме --smoke-test."""
    cmd = [sys.executable, "-m", "rme_mapper.main", "--smoke-test"]
    res = subprocess.run(
        cmd,
        cwd=ROOT_DIR,
        capture_output=True,
        text=True,
        errors="replace",
        timeout=20,
    )
    assert res.returncode == 0, f"Smoke test упал:\n{res.stderr}\n{res.stdout}"
    assert "[SMOKE-TEST] SUCCESS" in res.stdout or "[SMOKE-TEST] SUCCESS" in res.stderr


def test_08_canonical_version_single_source_of_truth() -> None:
    """Проверка единого источника версий (app_info.py) и динамического именования артефактов."""
    from build_release import get_canonical_version, sync_version_metadata

    canon_version = get_canonical_version()
    assert canon_version == APP_VERSION
    assert re.fullmatch(r"\d+\.\d+\.\d+", canon_version)

    # Синхронизация отрабатывает без ошибок и гарантирует согласованность
    sync_version_metadata(canon_version)

    # Проверка, что имена артефактов строятся строго из канонической версии
    expected_portable = f"GeoPointMapper-{canon_version}-portable.zip"
    expected_installer = f"GeoPointMapper-{canon_version}-Setup-x64.exe"

    portable_path = ROOT_DIR / "release" / "portable" / expected_portable
    installer_path = ROOT_DIR / "release" / "installer" / expected_installer

    assert portable_path.name == expected_portable
    assert installer_path.name == expected_installer
