"""Сервис проверки, загрузки и проверки целостности обновлений через GitHub Releases."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import logging
import os
from pathlib import Path
import re
import ssl
import subprocess
import sys
import tempfile
import threading
from typing import Any, Callable
import urllib.error
import urllib.parse
import urllib.request

from rme_mapper.app_info import APP_VERSION

logger = logging.getLogger("rme_mapper.services.update_service")

GITHUB_REPO = "gutentag6574/RME-Mapper"
RELEASES_API_URL = f"https://api.github.com/repos/{GITHUB_REPO}/releases?per_page=10"
RELEASES_LATEST_API_URL = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
RELEASES_HTML_URL = f"https://github.com/{GITHUB_REPO}/releases"
INNO_APP_ID = "{5E9A8874-C35A-4DF8-8DA1-68F485B891A4}"
MANIFEST_ASSET_NAME = "release_manifest.json"

CHECK_INTERVAL_SECONDS = 24 * 60 * 60
MAX_METADATA_BYTES = 2 * 1024 * 1024
MAX_MANIFEST_BYTES = 1024 * 1024
MAX_DOWNLOAD_BYTES = 512 * 1024 * 1024
DEFAULT_TIMEOUT_SEC = 15
DOWNLOAD_TIMEOUT_SEC = 60

INSTALL_MODE_INSTALLED = "installed"
INSTALL_MODE_PORTABLE = "portable"
INSTALL_MODE_SOURCE = "source"
INSTALL_MODE_UNKNOWN = "unknown"

_SEMVER_RE = re.compile(r"^\s*[vV]?(\d+)\.(\d+)\.(\d+)\s*$")
_SAFE_FILENAME_RE = re.compile(r"^[A-Za-z0-9._-]+$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class UpdateError(RuntimeError):
    """Структурированная ошибка проверки или загрузки обновления."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True, order=True)
class SemVer:
    """Семантическая версия вида major.minor.patch."""

    major: int
    minor: int
    patch: int

    def __str__(self) -> str:
        return f"{self.major}.{self.minor}.{self.patch}"


@dataclass(frozen=True)
class ReleaseAsset:
    """Метаданные вложения релиза GitHub."""

    name: str
    download_url: str
    size: int
    content_type: str = ""


@dataclass(frozen=True)
class UpdateInfo:
    """Описание найденного релиза и целевого пакета обновления."""

    current_version: str
    latest_version: str
    has_update: bool
    install_mode: str
    release_name: str
    html_url: str
    published_at: str
    notes: str
    target_asset: ReleaseAsset | None = None
    manifest_asset: ReleaseAsset | None = None
    expected_size: int = 0
    expected_sha256: str = ""


@dataclass(frozen=True)
class UpdateCheckResult:
    """Результат проверки наличия обновлений."""

    status: str  # "up_to_date" | "update_available" | "error"
    info: UpdateInfo | None = None
    error_code: str = ""
    error_message: str = ""
    checked_at_utc: str = ""


@dataclass(frozen=True)
class DownloadResult:
    """Результат загрузки и проверки целостности файла обновления."""

    success: bool
    file_path: Path | None = None
    sha256: str = ""
    size_bytes: int = 0
    authenticode_status: str = ""
    authenticode_publisher: str = ""
    cancelled: bool = False
    error_code: str = ""
    error_message: str = ""


def parse_semver(version_str: str) -> SemVer:
    """Строгий разбор стабильной версии (например 'v1.10.0' -> SemVer(1, 10, 0))."""
    m = _SEMVER_RE.match(str(version_str or ""))
    if not m:
        raise ValueError(f"Invalid semantic version: {version_str!r}")
    return SemVer(int(m.group(1)), int(m.group(2)), int(m.group(3)))


def compare_versions(version_a: str, version_b: str) -> int:
    """Сравнить версии: -1 (a < b), 0 (a == b), 1 (a > b)."""
    va = parse_semver(version_a)
    vb = parse_semver(version_b)
    if va < vb:
        return -1
    if va > vb:
        return 1
    return 0


def format_size_human(size_bytes: int) -> str:
    """Форматировать размер файла в человекочитаемом виде."""
    if size_bytes <= 0:
        return "0 B"
    if size_bytes < 1024:
        return f"{size_bytes} B"
    kb = size_bytes / 1024.0
    if kb < 1024.0:
        return f"{kb:.1f} KB"
    mb = kb / 1024.0
    if mb < 1024.0:
        return f"{mb:.1f} MB"
    gb = mb / 1024.0
    return f"{gb:.2f} GB"


def _query_windows_inno_install_dir() -> Path | None:
    """Прочитать InstallLocation из реестра Inno Setup на Windows."""
    if sys.platform != "win32":
        return None
    try:
        import winreg
    except Exception:
        return None

    subkey = rf"Software\Microsoft\Windows\CurrentVersion\Uninstall\{INNO_APP_ID}_is1"
    for root in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        try:
            with winreg.OpenKey(root, subkey) as key:
                val, _ = winreg.QueryValueEx(key, "InstallLocation")
                if val:
                    return Path(str(val).strip()).resolve()
        except OSError:
            continue
        except Exception:
            continue
    return None


def detect_install_mode(
    executable_path: Path | None = None,
    is_frozen: bool | None = None,
    registry_install_dir: Path | None = None,
    check_registry: bool = True,
) -> str:
    """Надёжно определить режим запуска: installed (Inno Setup), portable или source."""
    frozen = getattr(sys, "frozen", False) if is_frozen is None else bool(is_frozen)
    if not frozen:
        return INSTALL_MODE_SOURCE

    exe_path = Path(executable_path or sys.executable).resolve()
    app_dir = exe_path.parent
    if not app_dir.exists() or not exe_path.name.lower().endswith(".exe"):
        return INSTALL_MODE_UNKNOWN

    try:
        has_unins = any(app_dir.glob("unins*.exe")) or (app_dir / "unins000.dat").exists()
        if has_unins:
            return INSTALL_MODE_INSTALLED
    except OSError:
        pass

    reg_dir = registry_install_dir
    if reg_dir is None and check_registry:
        reg_dir = _query_windows_inno_install_dir()
    if reg_dir is not None:
        try:
            if reg_dir.resolve() == app_dir:
                return INSTALL_MODE_INSTALLED
        except OSError:
            pass

    return INSTALL_MODE_PORTABLE


def validate_https_url(url: str) -> str:
    """Проверить, что URL использует HTTPS и не содержит управляющих символов."""
    cleaned = str(url or "").strip()
    if not cleaned or "\r" in cleaned or "\n" in cleaned:
        raise UpdateError("insecure_url", "Недопустимый URL обновления.")
    parsed = urllib.parse.urlparse(cleaned)
    if parsed.scheme.lower() != "https" or not parsed.netloc:
        raise UpdateError("insecure_url", f"Разрешены только HTTPS-ссылки: {cleaned}")
    return cleaned


def sanitize_asset_filename(filename: str) -> str:
    """Защита от path traversal в имени скачиваемого ассета."""
    raw = str(filename or "").strip()
    if "/" in raw or "\\" in raw or ".." in raw:
        raise UpdateError("invalid_asset_name", f"Небезопасное имя файла: {filename!r}")
    base = Path(raw).name
    if not base or base in (".", "..") or not _SAFE_FILENAME_RE.match(base):
        raise UpdateError("invalid_asset_name", f"Небезопасное имя файла: {filename!r}")
    return base


def build_ssl_context() -> ssl.SSLContext:
    """Создать SSL-контекст с доверенными корневыми сертификатами."""
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except Exception:
        return ssl.create_default_context()


def expected_asset_name_for_mode(version: str, install_mode: str) -> str:
    """Целевое имя ассета для конкретной версии и типа поставки."""
    ver = str(parse_semver(version))
    if install_mode == INSTALL_MODE_INSTALLED:
        return f"GeoPointMapper-{ver}-Setup-x64.exe"
    return f"GeoPointMapper-{ver}-portable.zip"


def verify_manifest_for_asset(
    manifest_data: dict[str, Any],
    expected_version: str,
    expected_asset_name: str,
) -> tuple[str, int]:
    """Проверить release_manifest.json и извлечь (sha256, size_bytes) целевого артефакта."""
    if not isinstance(manifest_data, dict):
        raise UpdateError("invalid_manifest", "Манифест релиза имеет некорректный формат JSON.")

    expected_ver_norm = str(parse_semver(expected_version))
    raw_manifest_ver = str(manifest_data.get("version", "")).strip()
    try:
        manifest_ver_norm = str(parse_semver(raw_manifest_ver))
    except ValueError:
        raise UpdateError("invalid_manifest", f"Некорректная версия в манифесте: {raw_manifest_ver!r}")

    if manifest_ver_norm != expected_ver_norm:
        raise UpdateError(
            "manifest_version_mismatch",
            f"Версия манифеста ({manifest_ver_norm}) не совпадает с версией релиза ({expected_ver_norm}).",
        )

    arch = str(manifest_data.get("architecture", "")).lower()
    if arch and "x64" not in arch and "amd64" not in arch:
        raise UpdateError("platform_mismatch", f"Неподдерживаемая архитектура в манифесте: {arch}")

    artifacts = manifest_data.get("artifacts")
    if not isinstance(artifacts, list):
        raise UpdateError("invalid_manifest", "В манифесте отсутствует список артефактов.")

    for art in artifacts:
        if not isinstance(art, dict):
            continue
        if art.get("name") == expected_asset_name:
            sha256 = str(art.get("sha256", "")).strip().lower()
            size_bytes = art.get("size_bytes")
            if not _SHA256_RE.match(sha256):
                raise UpdateError("invalid_manifest", f"Некорректный SHA-256 для {expected_asset_name}.")
            if not isinstance(size_bytes, int) or isinstance(size_bytes, bool) or size_bytes <= 0 or size_bytes > MAX_DOWNLOAD_BYTES:
                raise UpdateError("invalid_manifest", f"Некорректный размер файла для {expected_asset_name}.")
            return sha256, size_bytes

    raise UpdateError("missing_manifest_asset", f"В манифесте не найден артефакт {expected_asset_name}.")


def check_authenticode_signature(file_path: Path) -> tuple[bool, str, str]:
    """Проверить цифровую подпись Authenticode на Windows, если она присутствует.

    Возвращает (ok_to_run, status, publisher_subject).
    - Если подпись отсутствует ('NotSigned'), возвращает (True, 'unsigned', ''),
      так как сборка без коммерческого сертификата защищена SHA-256 из release_manifest.json.
    - Если подпись присутствует и валидна ('Valid'), возвращает (True, 'valid', subject).
    - Если подпись присутствует, но невалидна или недоверена, возвращает (False, status, subject).
    """
    if sys.platform != "win32":
        return True, "unsupported_os", ""

    resolved = Path(file_path).resolve()
    if not resolved.exists():
        return False, "missing_file", ""

    env = os.environ.copy()
    env["RME_SIG_TARGET"] = str(resolved)
    ps_cmd = (
        "$sig = Get-AuthenticodeSignature -LiteralPath $env:RME_SIG_TARGET; "
        "[PSCustomObject]@{"
        "Status=$sig.Status.ToString();"
        "Subject=$(if ($sig.SignerCertificate) { $sig.SignerCertificate.Subject } else { '' })"
        "} | ConvertTo-Json -Compress"
    )
    try:
        res = subprocess.run(
            ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps_cmd],
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=15,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        if res.returncode != 0 or not res.stdout.strip():
            logger.warning("Не удалось проверить Authenticode: %s", res.stderr.strip())
            return False, "check_failed", ""
        data = json.loads(res.stdout.strip())
        status = str(data.get("Status", "")).strip()
        subject = str(data.get("Subject", "")).strip()
        if status == "NotSigned" and not subject:
            return True, "unsigned", ""
        if status == "Valid" and subject:
            return True, "valid", subject
        return False, status or "invalid", subject
    except Exception as e:
        logger.warning("Ошибка проверки Authenticode: %s", e)
        return False, "check_error", ""


def _parse_iso_utc(iso_str: str) -> datetime | None:
    text = str(iso_str or "").strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def should_run_auto_check(
    settings_service: Any,
    now_utc: datetime | None = None,
    min_interval_seconds: int = CHECK_INTERVAL_SECONDS,
) -> bool:
    """Определить, нужно ли запускать фоновую автопроверку обновлений (не чаще 1 раза в сутки)."""
    if settings_service is None:
        return False
    if hasattr(settings_service, "get_auto_check_updates") and not settings_service.get_auto_check_updates(True):
        return False

    last_raw = ""
    if hasattr(settings_service, "get_last_update_check_utc"):
        last_raw = settings_service.get_last_update_check_utc()
    last_dt = _parse_iso_utc(last_raw)
    if last_dt is None:
        return True

    current = now_utc or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    elapsed = (current - last_dt).total_seconds()
    return elapsed >= float(min_interval_seconds)


class UpdateService:
    """Сервис получения сведений о релизах, загрузки и валидации обновлений."""

    def __init__(
        self,
        repo: str = GITHUB_REPO,
        current_version: str = APP_VERSION,
        install_mode: str | None = None,
        urlopen_func: Callable[..., Any] | None = None,
        allow_insecure_urls_for_tests: bool = False,
        temp_root: Path | None = None,
    ) -> None:
        self._repo = repo
        self._current_version = current_version
        self._install_mode = install_mode
        self._urlopen = urlopen_func or urllib.request.urlopen
        self._allow_insecure = allow_insecure_urls_for_tests
        self._temp_root = temp_root

        self._lock = threading.Lock()
        self._checking = False
        self._downloading = False
        self._cancel_event = threading.Event()

    @property
    def is_checking(self) -> bool:
        with self._lock:
            return self._checking

    @property
    def is_downloading(self) -> bool:
        with self._lock:
            return self._downloading

    def cancel_download(self) -> None:
        """Запросить отмену активной загрузки."""
        self._cancel_event.set()

    def get_install_mode(self) -> str:
        if self._install_mode is not None:
            return self._install_mode
        return detect_install_mode()

    def _open_url(self, url: str, timeout_sec: int, accept: str = "application/vnd.github+json") -> Any:
        if not self._allow_insecure:
            url = validate_https_url(url)
        headers = {
            "User-Agent": f"GeoPointMapper/{self._current_version}",
            "Accept": accept,
        }
        req = urllib.request.Request(url, headers=headers)
        if self._urlopen is urllib.request.urlopen:
            ctx = build_ssl_context()
            return self._urlopen(req, timeout=timeout_sec, context=ctx)
        return self._urlopen(req, timeout=timeout_sec)

    def _read_bounded_json(self, url: str, timeout_sec: int, max_bytes: int) -> Any:
        with self._open_url(url, timeout_sec=timeout_sec, accept="application/vnd.github+json, application/json") as resp:
            content_len = None
            if hasattr(resp, "headers") and resp.headers is not None:
                raw_len = resp.headers.get("Content-Length")
                if raw_len and str(raw_len).isdigit():
                    content_len = int(raw_len)
            if content_len is not None and content_len > max_bytes:
                raise UpdateError("response_too_large", "Ответ сервера превышает допустимый размер.")
            chunks: list[bytes] = []
            total = 0
            while True:
                buf = resp.read(65536)
                if not buf:
                    break
                total += len(buf)
                if total > max_bytes:
                    raise UpdateError("response_too_large", "Ответ сервера превышает допустимый размер.")
                chunks.append(buf)
            raw_text = b"".join(chunks).decode("utf-8", errors="replace")
            try:
                return json.loads(raw_text)
            except json.JSONDecodeError as e:
                raise UpdateError("invalid_json", f"Некорректный JSON ответа: {e}") from e

    def select_latest_stable_release(self, payload: Any) -> dict[str, Any]:
        """Выбрать новейший стабильный (не draft, не prerelease) релиз из ответа API."""
        candidates = payload if isinstance(payload, list) else ([payload] if isinstance(payload, dict) else [])
        best_release: dict[str, Any] | None = None
        best_ver: SemVer | None = None

        for rel in candidates:
            if not isinstance(rel, dict):
                continue
            if rel.get("draft") or rel.get("prerelease"):
                continue
            tag = str(rel.get("tag_name") or "")
            try:
                ver = parse_semver(tag)
            except ValueError:
                continue
            if best_ver is None or ver > best_ver:
                best_ver = ver
                best_release = rel

        if best_release is None:
            raise UpdateError("no_stable_release", "На сервере нет подходящего стабильного релиза.")
        return best_release

    def check_for_updates(self, timeout_sec: int = DEFAULT_TIMEOUT_SEC) -> UpdateCheckResult:
        """Синхронно проверить наличие новой стабильной версии и проверить ассеты/манифест."""
        with self._lock:
            if self._checking:
                return UpdateCheckResult(
                    status="error",
                    error_code="already_checking",
                    error_message="Проверка обновлений уже выполняется.",
                )
            self._checking = True

        now_iso = datetime.now(timezone.utc).isoformat()
        try:
            api_url = f"https://api.github.com/repos/{self._repo}/releases?per_page=10"
            payload = self._read_bounded_json(api_url, timeout_sec=timeout_sec, max_bytes=MAX_METADATA_BYTES)
            rel = self.select_latest_stable_release(payload)

            latest_ver = parse_semver(str(rel.get("tag_name", "")))
            current_ver = parse_semver(self._current_version)
            has_update = latest_ver > current_ver

            install_mode = self.get_install_mode()
            html_url = str(rel.get("html_url") or RELEASES_HTML_URL)
            if not self._allow_insecure:
                try:
                    html_url = validate_https_url(html_url)
                except UpdateError:
                    html_url = RELEASES_HTML_URL

            assets_raw = rel.get("assets") or []
            assets_by_name: dict[str, ReleaseAsset] = {}
            for a in assets_raw:
                if not isinstance(a, dict):
                    continue
                try:
                    safe_name = sanitize_asset_filename(str(a.get("name", "")))
                    dl_url = str(a.get("browser_download_url", ""))
                    if not self._allow_insecure:
                        dl_url = validate_https_url(dl_url)
                    size = int(a.get("size", 0) or 0)
                    assets_by_name[safe_name] = ReleaseAsset(
                        name=safe_name,
                        download_url=dl_url,
                        size=size,
                        content_type=str(a.get("content_type", "")),
                    )
                except (UpdateError, ValueError, TypeError):
                    continue

            latest_str = str(latest_ver)
            if not has_update:
                info = UpdateInfo(
                    current_version=str(current_ver),
                    latest_version=latest_str,
                    has_update=False,
                    install_mode=install_mode,
                    release_name=str(rel.get("name") or f"v{latest_str}"),
                    html_url=html_url,
                    published_at=str(rel.get("published_at") or ""),
                    notes=str(rel.get("body") or ""),
                )
                return UpdateCheckResult(status="up_to_date", info=info, checked_at_utc=now_iso)

            target_asset: ReleaseAsset | None = None
            manifest_asset: ReleaseAsset | None = assets_by_name.get(MANIFEST_ASSET_NAME)
            expected_sha256 = ""
            expected_size = 0

            if install_mode in (INSTALL_MODE_INSTALLED, INSTALL_MODE_PORTABLE):
                expected_name = expected_asset_name_for_mode(latest_str, install_mode)
                target_asset = assets_by_name.get(expected_name)
                if target_asset is None:
                    raise UpdateError(
                        "missing_asset",
                        f"В релизе v{latest_str} отсутствует обязательный файл {expected_name}.",
                    )
                if manifest_asset is None:
                    raise UpdateError(
                        "missing_manifest",
                        f"В релизе v{latest_str} отсутствует {MANIFEST_ASSET_NAME} для проверки целостности.",
                    )
                manifest_json = self._read_bounded_json(
                    manifest_asset.download_url,
                    timeout_sec=timeout_sec,
                    max_bytes=MAX_MANIFEST_BYTES,
                )
                expected_sha256, expected_size = verify_manifest_for_asset(
                    manifest_json,
                    expected_version=latest_str,
                    expected_asset_name=expected_name,
                )

            info = UpdateInfo(
                current_version=str(current_ver),
                latest_version=latest_str,
                has_update=True,
                install_mode=install_mode,
                release_name=str(rel.get("name") or f"v{latest_str}"),
                html_url=html_url,
                published_at=str(rel.get("published_at") or ""),
                notes=str(rel.get("body") or ""),
                target_asset=target_asset,
                manifest_asset=manifest_asset,
                expected_size=expected_size or (target_asset.size if target_asset else 0),
                expected_sha256=expected_sha256,
            )
            return UpdateCheckResult(status="update_available", info=info, checked_at_utc=now_iso)

        except UpdateError as e:
            return UpdateCheckResult(
                status="error",
                error_code=e.code,
                error_message=e.message,
                checked_at_utc=now_iso,
            )
        except urllib.error.HTTPError as e:
            return UpdateCheckResult(
                status="error",
                error_code=f"http_{e.code}",
                error_message=f"Сервер GitHub вернул ошибку HTTP {e.code}.",
                checked_at_utc=now_iso,
            )
        except (urllib.error.URLError, TimeoutError, ssl.SSLError, OSError) as e:
            return UpdateCheckResult(
                status="error",
                error_code="network_error",
                error_message=f"Ошибка сети при проверке обновлений: {e}",
                checked_at_utc=now_iso,
            )
        except Exception as e:
            logger.exception("Непредвиденная ошибка проверки обновлений")
            return UpdateCheckResult(
                status="error",
                error_code="unexpected_error",
                error_message=str(e),
                checked_at_utc=now_iso,
            )
        finally:
            with self._lock:
                self._checking = False

    def _resolve_target_path(self, safe_filename: str, install_mode: str) -> Path:
        if self._temp_root is not None:
            base = Path(self._temp_root)
            base.mkdir(parents=True, exist_ok=True)
            return (base / safe_name_with_pid(safe_filename)).resolve() if install_mode == INSTALL_MODE_INSTALLED else (base / safe_filename).resolve()

        if install_mode == INSTALL_MODE_PORTABLE:
            downloads = Path.home() / "Downloads"
            if downloads.exists() and downloads.is_dir():
                return (downloads / safe_filename).resolve()

        update_dir = Path(tempfile.gettempdir()) / "GeoPointMapper_Updates"
        update_dir.mkdir(parents=True, exist_ok=True)
        return (update_dir / safe_filename).resolve()

    def download_and_verify(
        self,
        info: UpdateInfo,
        progress_callback: Callable[[int, int], None] | None = None,
        timeout_sec: int = DOWNLOAD_TIMEOUT_SEC,
        verify_authenticode: bool = True,
    ) -> DownloadResult:
        """Загрузить ассет в безопасный каталог, проверить размер, SHA-256 и подпись Authenticode."""
        if info.target_asset is None:
            return DownloadResult(
                success=False,
                error_code="no_target_asset",
                error_message="Для данного типа установки отсутствует файл загрузки.",
            )
        if not info.expected_sha256 or not _SHA256_RE.match(info.expected_sha256):
            return DownloadResult(
                success=False,
                error_code="missing_sha256",
                error_message="Отсутствует ожидаемая контрольная сумма SHA-256.",
            )

        with self._lock:
            if self._downloading:
                return DownloadResult(
                    success=False,
                    error_code="already_downloading",
                    error_message="Загрузка обновления уже выполняется.",
                )
            self._downloading = True
            self._cancel_event.clear()

        dest_path: Path | None = None
        part_path: Path | None = None
        try:
            safe_name = sanitize_asset_filename(info.target_asset.name)
            dl_url = info.target_asset.download_url
            if not self._allow_insecure:
                dl_url = validate_https_url(dl_url)

            dest_path = self._resolve_target_path(safe_name, info.install_mode)
            part_path = dest_path.with_name(f".{dest_path.name}.{os.getpid()}.part")
            if part_path.exists():
                part_path.unlink()

            expected_size = info.expected_size or info.target_asset.size
            if expected_size > MAX_DOWNLOAD_BYTES:
                raise UpdateError("file_too_large", "Размер файла обновления превышает лимит безопасности.")

            hasher = hashlib.sha256()
            received = 0
            with self._open_url(dl_url, timeout_sec=timeout_sec, accept="application/octet-stream") as resp:
                with open(part_path, "wb") as out:
                    while True:
                        if self._cancel_event.is_set():
                            raise UpdateError("cancelled", "Загрузка отменена пользователем.")
                        chunk = resp.read(65536)
                        if not chunk:
                            break
                        received += len(chunk)
                        if received > MAX_DOWNLOAD_BYTES:
                            raise UpdateError("file_too_large", "Превышен максимальный размер файла.")
                        if expected_size > 0 and received > expected_size:
                            raise UpdateError("size_mismatch", "Размер загружаемого файла превышает заявленный в манифесте.")
                        out.write(chunk)
                        hasher.update(chunk)
                        if progress_callback is not None:
                            progress_callback(received, expected_size)

            if self._cancel_event.is_set():
                raise UpdateError("cancelled", "Загрузка отменена пользователем.")

            if expected_size > 0 and received != expected_size:
                raise UpdateError(
                    "size_mismatch",
                    f"Несоответствие размера файла: получено {received} Б, ожидалось {expected_size} Б.",
                )

            actual_sha256 = hasher.hexdigest().lower()
            if actual_sha256 != info.expected_sha256.lower():
                raise UpdateError(
                    "sha256_mismatch",
                    "Контрольная сумма SHA-256 загруженного файла не совпадает с release_manifest.json.",
                )

            auth_status = ""
            auth_pub = ""
            if verify_authenticode and safe_name.lower().endswith(".exe"):
                ok_sig, auth_status, auth_pub = check_authenticode_signature(part_path)
                if not ok_sig:
                    raise UpdateError(
                        "signature_invalid",
                        f"Некорректная цифровая подпись Authenticode ({auth_status}). Запуск заблокирован.",
                    )

            if dest_path.exists():
                try:
                    dest_path.unlink()
                except OSError:
                    dest_path = dest_path.with_name(f"{dest_path.stem}-{os.getpid()}{dest_path.suffix}")
            part_path.replace(dest_path)
            part_path = None

            return DownloadResult(
                success=True,
                file_path=dest_path,
                sha256=actual_sha256,
                size_bytes=received,
                authenticode_status=auth_status,
                authenticode_publisher=auth_pub,
            )

        except UpdateError as e:
            _safe_unlink(part_path)
            if e.code in ("sha256_mismatch", "size_mismatch", "signature_invalid", "file_too_large"):
                _safe_unlink(dest_path)
            return DownloadResult(
                success=False,
                cancelled=(e.code == "cancelled"),
                error_code=e.code,
                error_message=e.message,
            )
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, ssl.SSLError, OSError) as e:
            _safe_unlink(part_path)
            return DownloadResult(
                success=False,
                error_code="download_network_error",
                error_message=f"Сбой загрузки обновления: {e}",
            )
        except Exception as e:
            _safe_unlink(part_path)
            logger.exception("Непредвиденная ошибка загрузки обновления")
            return DownloadResult(
                success=False,
                error_code="download_unexpected_error",
                error_message=str(e),
            )
        finally:
            with self._lock:
                self._downloading = False


def safe_name_with_pid(name: str) -> str:
    return name


def _safe_unlink(path: Path | None) -> None:
    if path is None:
        return
    try:
        if path.exists():
            path.unlink()
    except OSError:
        pass


def build_installer_relaunch_script(
    installer_path: Path,
    current_pid: int,
    relaunch_exe: Path,
    install_dir: Path | None = None,
    silent: bool = True,
) -> str:
    """Сформировать PowerShell-скрипт безопасного ожидания выхода, установки и перезапуска."""
    inst = str(installer_path.resolve()).replace("'", "''")
    exe = str(relaunch_exe.resolve()).replace("'", "''")
    work_dir = str(relaunch_exe.resolve().parent).replace("'", "''")
    dir_arg = ""
    if install_dir is not None:
        resolved_dir = str(install_dir.resolve()).replace("'", "''")
        dir_arg = f", '\"/DIR={resolved_dir}\"'"
    silent_args = (
        "'/SP-', '/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART', '/CURRENTUSER', '/CLOSEAPPLICATIONS'"
        if silent
        else "'/CLOSEAPPLICATIONS'"
    )
    return (
        f"$parentPid = {int(current_pid)}\n"
        f"$installerPath = '{inst}'\n"
        f"$relaunchExe = '{exe}'\n"
        f"$workDir = '{work_dir}'\n"
        "$deadline = (Get-Date).AddSeconds(25)\n"
        "while ((Get-Date) -lt $deadline) {\n"
        "    if (-not (Get-Process -Id $parentPid -ErrorAction SilentlyContinue)) { break }\n"
        "    Start-Sleep -Milliseconds 250\n"
        "}\n"
        "Start-Sleep -Milliseconds 350\n"
        f"$argList = @({silent_args}{dir_arg})\n"
        "$proc = Start-Process -FilePath $installerPath -ArgumentList $argList -Wait -PassThru\n"
        "if ($proc -and $proc.ExitCode -eq 0 -and (Test-Path -LiteralPath $relaunchExe)) {\n"
        "    Start-Process -FilePath $relaunchExe -WorkingDirectory $workDir\n"
        "}\n"
        "Remove-Item -LiteralPath $installerPath -Force -ErrorAction SilentlyContinue\n"
        "Remove-Item -LiteralPath $PSCommandPath -Force -ErrorAction SilentlyContinue\n"
    )


def launch_installer_and_relaunch(
    installer_path: Path,
    relaunch_exe: Path | None = None,
    current_pid: int | None = None,
    install_dir: Path | None = None,
    silent: bool = True,
) -> Path:
    """Запустить отложенный процесс установки Inno Setup и вернуть путь к helper-скрипту."""
    inst = Path(installer_path).resolve()
    if not inst.exists() or inst.suffix.lower() != ".exe":
        raise UpdateError("invalid_installer", f"Установщик не найден: {inst}")

    ok_sig, auth_status, _ = check_authenticode_signature(inst)
    if not ok_sig:
        raise UpdateError("signature_invalid", f"Проверка цифровой подписи не пройдена ({auth_status}).")

    target_exe = Path(relaunch_exe or sys.executable).resolve()
    resolved_install_dir = Path(install_dir).resolve() if install_dir is not None else target_exe.parent
    pid = os.getpid() if current_pid is None else int(current_pid)
    script_text = build_installer_relaunch_script(
        installer_path=inst,
        current_pid=pid,
        relaunch_exe=target_exe,
        install_dir=resolved_install_dir,
        silent=silent,
    )
    script_dir = Path(tempfile.gettempdir()) / "GeoPointMapper_Updates"
    script_dir.mkdir(parents=True, exist_ok=True)
    script_path = script_dir / f"apply_update_{pid}.ps1"
    script_path.write_text(script_text, encoding="utf-8-sig")

    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    subprocess.Popen(
        [
            "powershell.exe",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-WindowStyle",
            "Hidden",
            "-File",
            str(script_path),
        ],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=flags,
        close_fds=True,
    )
    return script_path
