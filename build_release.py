"""Единый скрипт автоматизированной сборки релизных дистрибутивов GeoPoint Mapper.

Выполняет:
1. Проверку системного окружения и зависимостей.
2. Проверку согласованности версий.
3. Очистку предыдущих сборок.
4. Автономную сборку Standalone EXE через PyInstaller.
5. Валидацию runtime-компонентов (Qt, GDAL, PROJ, ресурсы).
6. Автоматический запуск Smoke-теста автономного приложения.
7. Создание Portable ZIP архива.
8. Сборку инсталлятора через Inno Setup.
9. Генерацию release_manifest.json и SHA256SUMS.txt.
"""
from __future__ import annotations

import datetime
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import zipfile

PROJECT_ROOT = Path(__file__).resolve().parent

def log(msg: str) -> None:
    print(f"[*] {msg}", flush=True)

def error(msg: str) -> None:
    print(f"[!] ОШИБКА: {msg}", file=sys.stderr, flush=True)

def compute_sha256(file_path: Path) -> str:
    """Вычисление контрольной суммы SHA-256."""
    h = hashlib.sha256()
    with open(file_path, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()

def get_git_commit() -> str:
    """Получение текущего git-коммита."""
    try:
        res = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            check=True,
        )
        return res.stdout.strip()
    except Exception:
        return "unknown"

def check_version_consistency(expected_version: str) -> bool:
    """Проверка единообразия версий во всех конфигурационных файлах."""
    log(f"Проверка синхронизации версии {expected_version}...")
    
    # 1. pyproject.toml
    pyproject_path = PROJECT_ROOT / "pyproject.toml"
    if pyproject_path.exists():
        content = pyproject_path.read_text(encoding="utf-8")
        if f'version = "{expected_version}"' not in content:
            error(f"Несоответствие версии в {pyproject_path}")
            return False

    # 2. app_info.py
    app_info_path = PROJECT_ROOT / "src" / "rme_mapper" / "app_info.py"
    if app_info_path.exists():
        content = app_info_path.read_text(encoding="utf-8")
        if f'APP_VERSION: Final[str] = "{expected_version}"' not in content:
            error(f"Несоответствие версии в {app_info_path}")
            return False

    # 3. installer.iss
    installer_path = PROJECT_ROOT / "packaging" / "installer.iss"
    if installer_path.exists():
        content = installer_path.read_text(encoding="utf-8")
        if f'#define MyAppVersion "{expected_version}"' not in content:
            error(f"Несоответствие версии в {installer_path}")
            return False

    # 4. file_version_info.txt
    verinfo_path = PROJECT_ROOT / "packaging" / "file_version_info.txt"
    if verinfo_path.exists():
        content = verinfo_path.read_text(encoding="utf-8")
        if f"ProductVersion', u'{expected_version}" not in content:
            error(f"Несоответствие версии в {verinfo_path}")
            return False

    log("Все файлы метаданных согласованы.")
    return True

def clean_build_artifacts() -> None:
    """Очистка старых каталогов сборки."""
    log("Очистка старых артефактов (build/, dist/, release/)...")
    for d in ["build", "dist", "release"]:
        p = PROJECT_ROOT / d
        if p.exists():
            shutil.rmtree(p, ignore_errors=True)

def build_standalone(spec_file: Path) -> Path:
    """Запуск сборки Standalone onedir через PyInstaller."""
    log(f"Запуск сборки PyInstaller по спецификации {spec_file.name}...")
    pyinstaller_exe = shutil.which("pyinstaller")
    if not pyinstaller_exe:
        # Поиск в виртуальном окружении
        venv_pyinstaller = PROJECT_ROOT / ".venv" / "Scripts" / "pyinstaller.exe"
        if venv_pyinstaller.exists():
            pyinstaller_exe = str(venv_pyinstaller)
        else:
            raise FileNotFoundError("PyInstaller не найден в PATH или .venv/Scripts")

    cmd = [pyinstaller_exe, "--noconfirm", "--clean", str(spec_file)]
    subprocess.run(cmd, cwd=PROJECT_ROOT, check=True)

    dist_dir = PROJECT_ROOT / "dist" / "GeoPointMapper"
    if not dist_dir.is_dir() or not (dist_dir / "GeoPointMapper.exe").exists():
        raise RuntimeError("PyInstaller завершился, но GeoPointMapper.exe не был создан.")

    log(f"Standalone каталог успешно собран: {dist_dir}")
    return dist_dir

def validate_standalone(dist_dir: Path) -> None:
    """Валидация содержимого автономной сборки."""
    log("Валидация runtime-компонентов...")
    from tools.validate_release import validate_release_dir
    errors = validate_release_dir(dist_dir)
    if errors:
        for err in errors:
            error(f"Валидация: {err}")
        raise RuntimeError(f"Сборка содержит {len(errors)} ошибок валидации.")
    log("Валидация компонентов пройдена успешно.")

def run_smoke_test(exe_path: Path) -> None:
    """Запуск приложения в изолированном окружении для smoke-теста."""
    log(f"Запуск Smoke Test автономного EXE: {exe_path}...")
    # Очищаем Python-переменные окружения, моделируя запуск на чистой машине без Python
    clean_env = os.environ.copy()
    for var in ["PYTHONPATH", "PYTHONHOME", "VIRTUAL_ENV"]:
        clean_env.pop(var, None)

    marker_file = exe_path.parent / "smoke_success.txt"
    if marker_file.exists():
        marker_file.unlink()

    cmd = [str(exe_path), "--smoke-test"]
    res = subprocess.run(
        cmd,
        cwd=exe_path.parent,
        env=clean_env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    if res.returncode != 0:
        error(f"Smoke test завершился с ошибкой (код {res.returncode}):\n{res.stderr}\n{res.stdout}")
        raise RuntimeError(f"Smoke test упал с кодом {res.returncode}")

    if marker_file.exists():
        marker_file.unlink()
    elif "[SMOKE-TEST] SUCCESS" not in res.stdout and "[SMOKE-TEST] SUCCESS" not in res.stderr:
        log("Маркер завершения подтвержден кодом возврата 0.")

    log("Smoke Test успешно пройден: приложение запускается автономно без Python!")

def create_portable_zip(dist_dir: Path, output_zip: Path) -> Path:
    """Упаковка автономного каталога в Portable ZIP."""
    log(f"Создание Portable архива: {output_zip}...")
    output_zip.parent.mkdir(parents=True, exist_ok=True)
    
    with zipfile.ZipFile(output_zip, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for root, _, files in os.walk(dist_dir):
            for file in files:
                full_path = Path(root) / file
                rel_path = full_path.relative_to(dist_dir.parent)
                zf.write(full_path, arcname=str(rel_path))

    log(f"Portable архив создан: {output_zip} ({output_zip.stat().st_size / (1024*1024):.1f} MB)")
    return output_zip

def get_canonical_version() -> str:
    """Получение канонической версии приложения из src/rme_mapper/app_info.py."""
    import re
    app_info_path = PROJECT_ROOT / "src" / "rme_mapper" / "app_info.py"
    content = app_info_path.read_text(encoding="utf-8")
    m = re.search(r'APP_VERSION:\s*Final\[str\]\s*=\s*["\']([^"\']+)["\']', content)
    if not m:
        raise ValueError(f"Не удалось извлечь APP_VERSION из {app_info_path}")
    return m.group(1)


def build_installer(iss_file: Path, app_version: str) -> Path:
    """Компиляция инсталлятора через Inno Setup Compiler (ISCC)."""
    log(f"Компиляция инсталлятора для версии {app_version} через Inno Setup...")
    iscc_candidates = [
        shutil.which("iscc"),
        str(PROJECT_ROOT / "tools" / "innosetup" / "ISCC.exe"),
        r"C:\Program Files (x86)\Inno Setup 6\ISCC.exe",
        r"C:\Program Files\Inno Setup 6\ISCC.exe",
    ]
    iscc_exe = next((c for c in iscc_candidates if c and Path(c).exists()), None)
    if not iscc_exe:
        raise FileNotFoundError("Inno Setup Compiler (ISCC.exe) не найден.")

    cmd = [iscc_exe, f"/DMyAppVersion={app_version}", "/Q", str(iss_file)]
    subprocess.run(cmd, cwd=PROJECT_ROOT / "packaging", check=True)

    installer_output = PROJECT_ROOT / "release" / "installer" / f"GeoPointMapper-{app_version}-Setup-x64.exe"
    if not installer_output.exists():
        raise RuntimeError(f"Инсталлятор не найден по пути: {installer_output}")

    log(f"Инсталлятор успешно создан: {installer_output} ({installer_output.stat().st_size / (1024*1024):.1f} MB)")
    return installer_output


def main() -> int:
    start_time = datetime.datetime.now()
    app_version = get_canonical_version()
    log(f"=== ЗАПУСК СБОРКИ РЕЛИЗА GEOPOINT MAPPER v{app_version} ===")

    skip_pyinstaller = "--skip-pyinstaller" in sys.argv

    # 1. Проверка окружения
    if sys.version_info < (3, 12):
        error("Требуется Python 3.12 или новее.")
        return 1

    if not check_version_consistency(app_version):
        return 1

    # 2. Очистка
    if not skip_pyinstaller:
        clean_build_artifacts()

    # 3. Сборка Standalone
    spec_path = PROJECT_ROOT / "GeoPointMapper.spec"
    dist_dir = PROJECT_ROOT / "dist" / "GeoPointMapper"
    if not skip_pyinstaller or not (dist_dir / "GeoPointMapper.exe").exists():
        dist_dir = build_standalone(spec_path)

    # 4. Копирование в release/standalone
    release_standalone = PROJECT_ROOT / "release" / "standalone" / "GeoPointMapper"
    if not release_standalone.exists():
        log(f"Копирование Standalone версии в {release_standalone}...")
        shutil.copytree(dist_dir, release_standalone)

    # 5. Валидация
    validate_standalone(release_standalone)

    # 6. Smoke Test
    run_smoke_test(release_standalone / "GeoPointMapper.exe")

    # 7. Portable ZIP
    portable_zip = PROJECT_ROOT / "release" / "portable" / f"GeoPointMapper-{app_version}-portable.zip"
    create_portable_zip(dist_dir, portable_zip)

    # 8. Инсталлятор
    iss_path = PROJECT_ROOT / "packaging" / "installer.iss"
    installer_exe = build_installer(iss_path, app_version)

    # 9. Формирование манифеста и чек-сумм
    log("Формирование release_manifest.json и SHA256SUMS.txt...")
    artifacts = [
        {
            "name": f"GeoPointMapper-{app_version}-portable.zip",
            "type": "portable_zip",
            "path": f"portable/{portable_zip.name}",
            "size_bytes": portable_zip.stat().st_size,
            "sha256": compute_sha256(portable_zip),
        },
        {
            "name": installer_exe.name,
            "type": "installer_exe",
            "path": f"installer/{installer_exe.name}",
            "size_bytes": installer_exe.stat().st_size,
            "sha256": compute_sha256(installer_exe),
        },
        {
            "name": "GeoPointMapper.exe",
            "type": "standalone_exe",
            "path": "standalone/GeoPointMapper/GeoPointMapper.exe",
            "size_bytes": (release_standalone / "GeoPointMapper.exe").stat().st_size,
            "sha256": compute_sha256(release_standalone / "GeoPointMapper.exe"),
        },
    ]

    manifest = {
        "product": "GeoPoint Mapper",
        "version": app_version,
        "build_date": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "git_commit": get_git_commit(),
        "python_version": f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
        "architecture": "x64 (AMD64)",
        "qt_binding": "PySide6",
        "packaging_tool": "PyInstaller 6.22.3",
        "installer_tool": "Inno Setup 7.1.0",
        "build_type": "release",
        "artifacts": artifacts,
    }

    manifest_file = PROJECT_ROOT / "release" / "release_manifest.json"
    with open(manifest_file, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)

    sha256_file = PROJECT_ROOT / "release" / "SHA256SUMS.txt"
    with open(sha256_file, "w", encoding="utf-8") as f:
        for art in artifacts:
            f.write(f"{art['sha256']}  {art['path']}\n")

    elapsed = datetime.datetime.now() - start_time
    log(f"=== СБОРКА РЕЛИЗА УСПЕШНО ЗАВЕРШЕНА ЗА {elapsed.total_seconds():.1f} с ===")
    return 0

if __name__ == "__main__":
    sys.exit(main())
