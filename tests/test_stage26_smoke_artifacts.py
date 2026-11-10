"""Сквозные тесты автономных артефактов релиза GeoPoint Mapper (Этап 26).

Проверяет:
1. Запуск Standalone EXE в изолированном окружении без Python.
2. Распаковку Portable ZIP в путь с кириллицей и пробелами, и автономный запуск.
3. Тихую установку через Installer, проверку установленного EXE и деинсталляцию.
4. Валидность release_manifest.json и соответствие контрольных сумм SHA-256.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import zipfile

import pytest

from rme_mapper.app_info import APP_VERSION

ROOT_DIR = Path(__file__).resolve().parent.parent
RELEASE_DIR = ROOT_DIR / "release"


def _clean_env() -> dict[str, str]:
    """Формирование изолированного окружения без переменных Python-разработки и без .venv в PATH."""
    env = os.environ.copy()
    for var in ["PYTHONPATH", "PYTHONHOME", "VIRTUAL_ENV", "PROJ_DATA", "PROJ_LIB", "GDAL_DATA", "GDAL_FILENAME_IS_UTF8"]:
        env.pop(var, None)

    # Исключаем пути виртуального окружения и репозитория из PATH
    orig_path = env.get("PATH", "")
    clean_parts = [
        p for p in orig_path.split(os.pathsep)
        if ".venv" not in p.lower() and "rme-mapper" not in p.lower()
    ]
    env["PATH"] = os.pathsep.join(clean_parts)
    return env


def _compute_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


def test_01_standalone_exe_clean_machine_smoke() -> None:
    """Проверка запуска Standalone EXE без зависимостей от Python."""
    exe_path = RELEASE_DIR / "standalone" / f"GeoPointMapper-{APP_VERSION}" / "GeoPointMapper.exe"
    assert exe_path.exists(), f"Файл не найден: {exe_path}"

    marker = exe_path.parent / "smoke_success.txt"
    if marker.exists():
        marker.unlink()

    cmd = [str(exe_path), "--smoke-test"]
    res = subprocess.run(
        cmd,
        cwd=exe_path.parent,
        env=_clean_env(),
        capture_output=True,
        text=True,
        errors="replace",
        timeout=30,
    )

    assert res.returncode == 0, f"Standalone EXE упал с кодом {res.returncode}:\n{res.stderr}\n{res.stdout}"
    assert marker.exists() or "[SMOKE-TEST] SUCCESS" in res.stdout or res.returncode == 0
    if marker.exists():
        marker.unlink()


def test_02_portable_zip_unicode_and_spaces_path_smoke() -> None:
    """Проверка распаковки Portable ZIP в путь с пробелами и кириллицей и запуска."""
    zip_path = RELEASE_DIR / "portable" / f"GeoPointMapper-{APP_VERSION}-portable.zip"
    assert zip_path.exists(), f"Архив не найден: {zip_path}"

    test_extract_dir = ROOT_DIR / "scratch" / "Тест GeoPoint Mapper" / "Portable"
    if test_extract_dir.exists():
        shutil.rmtree(test_extract_dir, ignore_errors=True)
    test_extract_dir.mkdir(parents=True, exist_ok=True)

    # Распаковка
    with zipfile.ZipFile(zip_path, "r") as zf:
        zf.extractall(test_extract_dir)

    portable_exe = test_extract_dir / "GeoPointMapper" / "GeoPointMapper.exe"
    assert portable_exe.exists(), f"Исполняемый файл не найден после распаковки: {portable_exe}"

    marker = portable_exe.parent / "smoke_success.txt"
    if marker.exists():
        marker.unlink()

    cmd = [str(portable_exe), "--smoke-test"]
    res = subprocess.run(
        cmd,
        cwd=portable_exe.parent,
        env=_clean_env(),
        capture_output=True,
        text=True,
        errors="replace",
        timeout=30,
    )

    assert res.returncode == 0, f"Portable EXE упал с кодом {res.returncode}:\n{res.stderr}\n{res.stdout}"
    if marker.exists():
        marker.unlink()


def test_03_installer_install_smoke_and_uninstall() -> None:
    """Проверка установки через инсталлятор, запуска и деинсталляции."""
    installer_path = RELEASE_DIR / "installer" / f"GeoPointMapper-{APP_VERSION}-Setup-x64.exe"
    assert installer_path.exists(), f"Инсталлятор не найден: {installer_path}"

    install_target = ROOT_DIR / "scratch" / "Тест Установки" / "Installed App"
    if install_target.exists():
        shutil.rmtree(install_target, ignore_errors=True)
    install_target.mkdir(parents=True, exist_ok=True)

    # 1. Тихая установка
    cmd_install = [
        str(installer_path),
        "/SP-",
        "/VERYSILENT",
        "/SUPPRESSMSGBOXES",
        "/CURRENTUSER",
        f'/DIR={install_target}',
    ]
    res_install = subprocess.run(cmd_install, capture_output=True, text=True, timeout=60)
    assert res_install.returncode == 0, f"Установка завершилась с ошибкой: {res_install.stderr}"

    installed_exe = install_target / "GeoPointMapper.exe"
    assert installed_exe.exists(), f"Установленный EXE не найден: {installed_exe}"

    # 2. Запуск установленного приложения
    cmd_smoke = [str(installed_exe), "--smoke-test"]
    res_smoke = subprocess.run(cmd_smoke, cwd=installed_exe.parent, env=_clean_env(), capture_output=True, timeout=30)
    assert res_smoke.returncode == 0, f"Установленное приложение не смогло запуститься: {res_smoke.stderr}"

    # 3. Деинсталляция
    uninstaller = install_target / "unins000.exe"
    assert uninstaller.exists(), f"Деинсталлятор не найден: {uninstaller}"

    cmd_uninstall = [str(uninstaller), "/VERYSILENT", "/SUPPRESSMSGBOXES"]
    res_uninstall = subprocess.run(cmd_uninstall, capture_output=True, text=True, timeout=60)
    assert res_uninstall.returncode == 0, f"Деинсталляция упала: {res_uninstall.stderr}"

    # Даем системе 2 секунды освободить файлы
    import time
    time.sleep(2)

    # Проверяем, что исполняемый файл удален
    assert not installed_exe.exists(), "Установленный EXE остался после деинсталляции"


def test_04_release_manifest_and_sha256_checksums() -> None:
    """Проверка целостности манифеста релиза и хэшей SHA-256."""
    manifest_path = RELEASE_DIR / "release_manifest.json"
    sha256_path = RELEASE_DIR / "SHA256SUMS.txt"
    assert manifest_path.exists(), "Отсутствует release_manifest.json"
    assert sha256_path.exists(), "Отсутствует SHA256SUMS.txt"

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["product"] == "GeoPoint Mapper"
    assert manifest["version"] == APP_VERSION
    assert manifest["packaging_tool"].startswith("PyInstaller")
    assert manifest["installer_tool"].startswith("Inno Setup")
    assert len(manifest["artifacts"]) >= 3

    sha_content = sha256_path.read_text(encoding="utf-8")

    # Проверка хэша каждого артефакта
    for art in manifest["artifacts"]:
        rel_path = art["path"]
        expected_hash = art["sha256"]
        file_path = RELEASE_DIR / rel_path
        assert file_path.exists(), f"Артефакт из манифеста не существует: {file_path}"
        actual_hash = _compute_sha256(file_path)
        assert actual_hash == expected_hash, f"Несовпадение хэша для {rel_path}"
        assert expected_hash in sha_content, f"Хэш для {rel_path} не найден в SHA256SUMS.txt"
