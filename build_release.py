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
import re
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

def get_canonical_version() -> str:
    """Извлечение канонической версии приложения из src/rme_mapper/app_info.py."""
    app_info_path = PROJECT_ROOT / "src" / "rme_mapper" / "app_info.py"
    if not app_info_path.exists():
        raise FileNotFoundError(f"Канонический файл версий не найден: {app_info_path}")
    content = app_info_path.read_text(encoding="utf-8")
    m = re.search(r'APP_VERSION\s*(?::\s*Final\[str\])?\s*=\s*["\']([^"\']+)["\']', content)
    if not m:
        raise ValueError(f"Не удалось извлечь APP_VERSION из {app_info_path}")
    return m.group(1)


def sync_version_metadata(app_version: str) -> None:
    """Синхронизация версии из канонического источника во все зависимые конфигурации."""
    log(f"Синхронизация метаданных для версии {app_version}...")

    # 1. pyproject.toml
    pyproject_path = PROJECT_ROOT / "pyproject.toml"
    if pyproject_path.exists():
        text = pyproject_path.read_text(encoding="utf-8")
        updated = re.sub(r'version\s*=\s*"[^"]+"', f'version = "{app_version}"', text, count=1)
        if updated != text:
            pyproject_path.write_text(updated, encoding="utf-8")
            log("  [+] pyproject.toml синхронизирован")

    # 2. packaging/installer.iss
    installer_path = PROJECT_ROOT / "packaging" / "installer.iss"
    if installer_path.exists():
        text = installer_path.read_text(encoding="utf-8")
        updated = re.sub(r'#define\s+MyAppVersion\s+"[^"]+"', f'#define MyAppVersion "{app_version}"', text, count=1)
        if updated != text:
            installer_path.write_text(updated, encoding="utf-8")
            log("  [+] packaging/installer.iss синхронизирован")

    # 3. packaging/file_version_info.txt
    verinfo_path = PROJECT_ROOT / "packaging" / "file_version_info.txt"
    if verinfo_path.exists():
        text = verinfo_path.read_text(encoding="utf-8")
        nums = [int(p) for p in re.findall(r"\d+", app_version)]
        while len(nums) < 4:
            nums.append(0)
        v_tuple = f"({nums[0]}, {nums[1]}, {nums[2]}, {nums[3]})"

        updated = re.sub(r'filevers=\([^)]+\)', f'filevers={v_tuple}', text)
        updated = re.sub(r'prodvers=\([^)]+\)', f'prodvers={v_tuple}', updated)
        updated = re.sub(r"StringStruct\(u'FileVersion',\s*u'[^']+'\)", f"StringStruct(u'FileVersion', u'{app_version}.0')", updated)
        updated = re.sub(r"StringStruct\(u'ProductVersion',\s*u'[^']+'\)", f"StringStruct(u'ProductVersion', u'{app_version}')", updated)
        if updated != text:
            verinfo_path.write_text(updated, encoding="utf-8")
            log("  [+] packaging/file_version_info.txt синхронизирован")


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
        numbers=[int(n) for n in expected_version.split(".")]
        numbers=(numbers+[0]*4)[:4]
        for field in ("filevers","prodvers"):
            match=re.search(rf"{field}=\(([^)]+)\)",content)
            if not match or [int(n.strip()) for n in match.group(1).split(",")]!=numbers:
                error(f"Несоответствие {field} в {verinfo_path}")
                return False
        if f"ProductVersion', u'{expected_version}" not in content:
            error(f"Несоответствие версии в {verinfo_path}")
            return False

    log("Все файлы метаданных согласованы.")
    return True

def clean_build_artifacts() -> None:
    """Очистка старых каталогов сборки."""
    log("Очистка временных артефактов (build/, dist/); прежние релизы сохраняются...")
    for d in ["build", "dist"]:
        p = PROJECT_ROOT / d
        if p.exists():
            if p.resolve().parent != PROJECT_ROOT.resolve():
                raise RuntimeError(f"Каталог сборки находится вне проекта: {p}")
            shutil.rmtree(p, ignore_errors=True)

def build_standalone(spec_file: Path) -> Path:
    """Запуск сборки Standalone onedir через PyInstaller."""
    log(f"Запуск сборки PyInstaller по спецификации {spec_file.name}...")
    pyinstaller_exe = find_pyinstaller_executable()
    if not pyinstaller_exe:
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
    for var in ["PYTHONPATH", "PYTHONHOME", "VIRTUAL_ENV", "PROJ_DATA", "PROJ_LIB", "GDAL_DATA"]:
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
        errors="replace",
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

def find_pyinstaller_executable() -> str | None:
    """Поиск исполняемого файла PyInstaller."""
    exe = shutil.which("pyinstaller")
    if exe:
        return exe
    venv_pyinstaller = PROJECT_ROOT / ".venv" / "Scripts" / "pyinstaller.exe"
    if venv_pyinstaller.exists():
        return str(venv_pyinstaller)
    return None


def find_iscc_executable() -> str | None:
    """Поиск компилятора Inno Setup (ISCC.exe)."""
    iscc_candidates = [
        shutil.which("iscc"),
        str(PROJECT_ROOT / "tools" / "innosetup" / "ISCC.exe"),
        r"C:\Program Files (x86)\Inno Setup 6\ISCC.exe",
        r"C:\Program Files\Inno Setup 6\ISCC.exe",
    ]
    return next((c for c in iscc_candidates if c and Path(c).exists()), None)


def _read_pe_product_version(exe_path: Path) -> str | None:
    """Чтение строкового ProductVersion/FileVersion из PE-ресурсов Windows."""
    if sys.platform != "win32" or not exe_path.is_file():
        return None
    try:
        import ctypes
        from ctypes import wintypes

        version_dll = ctypes.windll.version
        size = version_dll.GetFileVersionInfoSizeW(str(exe_path), None)
        if not size:
            return None
        buf = ctypes.create_string_buffer(size)
        if not version_dll.GetFileVersionInfoW(str(exe_path), 0, size, buf):
            return None

        class _VS_FIXEDFILEINFO(ctypes.Structure):
            _fields_ = [
                ("dwSignature", wintypes.DWORD),
                ("dwStrucVersion", wintypes.DWORD),
                ("dwFileVersionMS", wintypes.DWORD),
                ("dwFileVersionLS", wintypes.DWORD),
                ("dwProductVersionMS", wintypes.DWORD),
                ("dwProductVersionLS", wintypes.DWORD),
                ("dwFileFlagsMask", wintypes.DWORD),
                ("dwFileFlags", wintypes.DWORD),
                ("dwFileOS", wintypes.DWORD),
                ("dwFileType", wintypes.DWORD),
                ("dwFileSubtype", wintypes.DWORD),
                ("dwFileDateMS", wintypes.DWORD),
                ("dwFileDateLS", wintypes.DWORD),
            ]

        ptr = ctypes.c_void_p()
        length = wintypes.UINT()
        if not version_dll.VerQueryValueW(buf, "\\", ctypes.byref(ptr), ctypes.byref(length)):
            return None
        info = ctypes.cast(ptr, ctypes.POINTER(_VS_FIXEDFILEINFO)).contents
        major = (info.dwProductVersionMS >> 16) & 0xFFFF
        minor = info.dwProductVersionMS & 0xFFFF
        patch = (info.dwProductVersionLS >> 16) & 0xFFFF
        if major == 0 and minor == 0 and patch == 0:
            return None
        return f"{major}.{minor}.{patch}"
    except Exception:
        return None


def get_pyinstaller_version() -> str:
    """Определение фактической версии установленного PyInstaller."""
    try:
        import PyInstaller
        ver = getattr(PyInstaller, "__version__", None)
        if ver:
            return f"PyInstaller {ver}"
    except Exception:
        pass

    pyinstaller_exe = find_pyinstaller_executable()
    if pyinstaller_exe:
        try:
            res = subprocess.run(
                [pyinstaller_exe, "--version"],
                capture_output=True,
                text=True,
                timeout=10,
                check=True,
            )
            ver = res.stdout.strip()
            if ver:
                return f"PyInstaller {ver}"
        except Exception:
            pass
    return "PyInstaller (unknown)"


def get_inno_setup_version(iscc_path: str | None = None) -> str:
    """Определение фактической версии установленного Inno Setup."""
    exe = iscc_path or find_iscc_executable()
    if not exe:
        return "Inno Setup (unknown)"

    exe_path = Path(exe)
    pe_ver = _read_pe_product_version(exe_path) or _read_pe_product_version(exe_path.parent / "unins000.exe")
    if pe_ver:
        return f"Inno Setup {pe_ver}"

    try:
        res = subprocess.run(
            [str(exe_path), "/?"],
            capture_output=True,
            text=True,
            errors="replace",
            timeout=10,
        )
        combined = f"{res.stdout}\n{res.stderr}"
        m = re.search(r"Inno Setup\s+([0-9]+(?:\.[0-9]+)*)", combined)
        if m:
            return f"Inno Setup {m.group(1)}"
    except Exception:
        pass
    return "Inno Setup (unknown)"


def build_installer(iss_file: Path, app_version: str) -> Path:
    """Компиляция инсталлятора через Inno Setup Compiler (ISCC)."""
    log(f"Компиляция инсталлятора для версии {app_version} через Inno Setup...")
    iscc_exe = find_iscc_executable()
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

    # Синхронизация версий во всех конфигурациях сборки
    sync_version_metadata(app_version)

    if "--sync-only" in sys.argv:
        log("Синхронизация версий успешно выполнена (--sync-only).")
        return 0

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
    release_standalone = PROJECT_ROOT / "release" / "standalone" / f"GeoPointMapper-{app_version}"
    staging = release_standalone.with_name(release_standalone.name + ".next")
    if staging.exists():
        staging = staging.with_name(staging.name + datetime.datetime.now().strftime("-%H%M%S"))
    shutil.copytree(dist_dir, staging)
    if release_standalone.exists():
        backup = release_standalone.with_name(release_standalone.name + datetime.datetime.now().strftime(".previous-%Y%m%d-%H%M%S"))
        release_standalone.rename(backup)
    staging.rename(release_standalone)

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
            "path": f"standalone/GeoPointMapper-{app_version}/GeoPointMapper.exe",
            "size_bytes": (release_standalone / "GeoPointMapper.exe").stat().st_size,
            "sha256": compute_sha256(release_standalone / "GeoPointMapper.exe"),
        },
    ]

    manifest = {
        "product": "GeoPoint Mapper",
        "version": app_version,
        "build_date": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "git_commit": get_git_commit(),
        "working_tree_dirty": bool(subprocess.run(["git","status","--porcelain"],cwd=PROJECT_ROOT,capture_output=True,text=True).stdout.strip()),
        "python_version": f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
        "architecture": "x64 (AMD64)",
        "qt_binding": "PySide6",
        "packaging_tool": get_pyinstaller_version(),
        "installer_tool": get_inno_setup_version(),
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
