"""Сервис активации и проверки лицензий GeoPoint Mapper по подписанному списку с GitHub."""
from __future__ import annotations

import base64
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import json
import logging
import os
from pathlib import Path
import re
import ssl
import time
from typing import Any, Callable
import urllib.error
import urllib.parse
import urllib.request

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from rme_mapper.app_info import APP_VERSION
from rme_mapper.i18n import tr
from rme_mapper.services.credential_store import CredentialStore, create_default_credential_store
from rme_mapper.services.license_config import (
    APP_ID,
    LICENSE_LIST_URL,
    LICENSE_PUBLIC_KEY_PEM,
    OFFLINE_LEASE_MAX_HOURS,
)
from rme_mapper.services.update_service import build_ssl_context

logger = logging.getLogger("rme_mapper.services.license_service")

CRED_TARGET_STATE = "GeoPointMapper/LicenseState"
CRED_TARGET_WATERMARK = "GeoPointMapper/LicenseWatermark"
LIST_SCHEMA = 1
KEY_PREFIX = "GPM"
KEY_BODY_B32_LEN = 32
MAX_LIST_BYTES = 4 * 1024 * 1024
CLOCK_SKEW_TOLERANCE_SEC = 300
_LIST_SIGNATURE_DOMAIN = b"GPM-LICENSE-LIST-V1\n"
_B32_BODY_RE = re.compile(r"^[A-Z2-7]{32}$")
_SHA256_HEX_RE = re.compile(r"^[0-9a-f]{64}$")


class LicenseError(RuntimeError):
    """Структурированная ошибка загрузки или проверки лицензии."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class VerifiedLicenseEntry:
    key_hash: str
    expires_at: str | None


@dataclass(frozen=True)
class VerifiedLicenseList:
    app_id: str
    list_version: int
    generated_at: str
    entries_by_hash: dict[str, VerifiedLicenseEntry]
    raw_bytes: bytes


@dataclass(frozen=True)
class LicenseCheckResult:
    authorized: bool
    status: str
    message: str = ""
    key_mask: str = ""
    license_expires_at: str | None = None
    last_verified_at: str | None = None
    list_version: int = 0
    offline_remaining_seconds: int = 0
    online_checked: bool = False
    error_code: str = ""


def utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def to_iso(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).replace(microsecond=0).isoformat()


def parse_iso(value: str) -> datetime:
    text = str(value or "").strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def normalize_license_key(raw_key: str) -> str:
    """Нормализовать введённый ключ к формату GPM-XXXX-... (160 бит Base32)."""
    cleaned = re.sub(r"[\s\-_]+", "", str(raw_key or "").strip().upper())
    body = cleaned[len(KEY_PREFIX) :] if cleaned.startswith(KEY_PREFIX) else cleaned
    if not _B32_BODY_RE.match(body):
        raise ValueError("Некорректный формат лицензионного ключа.")
    groups = [body[i : i + 4] for i in range(0, KEY_BODY_B32_LEN, 4)]
    return f"{KEY_PREFIX}-" + "-".join(groups)


def is_valid_key_format(raw_key: str) -> bool:
    try:
        normalize_license_key(raw_key)
        return True
    except ValueError:
        return False


def hash_license_key(raw_key: str, app_id: str = APP_ID) -> str:
    """Вычислить доменно-разделённый SHA-256 хэш канонического ключа."""
    canonical = normalize_license_key(raw_key)
    msg = f"GPM-KEY-V1:{app_id}:{canonical}".encode("utf-8")
    return hashlib.sha256(msg).hexdigest()


def mask_license_key(raw_key: str) -> str:
    """Сформировать безопасную маску ключа."""
    canonical = normalize_license_key(raw_key)
    body = canonical[len(KEY_PREFIX) + 1 :].replace("-", "")
    return f"{KEY_PREFIX}-{body[:4]}-••••-••••-{body[-4:]}"


def default_license_cache_path() -> Path:
    """Путь к локальному кэшу последнего проверенного подписанного списка."""
    env_cache = os.environ.get("RME_MAPPER_CACHE_DIR", "").strip()
    if env_cache:
        return Path(env_cache).resolve() / "license_cache.json"
    if os.name == "nt":
        base = Path(os.environ.get("LOCALAPPDATA") or (Path.home() / "AppData" / "Local"))
        return base.resolve() / "GeoPointMapper" / "license_cache.json"
    return (Path.home() / ".cache" / "geopoint-mapper" / "license_cache.json").resolve()


def _canonical_list_bytes(data: dict[str, Any]) -> bytes:
    clean = {
        "schema": data["schema"],
        "app_id": data["app_id"],
        "list_version": data["list_version"],
        "generated_at": data["generated_at"],
        "licenses": data["licenses"],
    }
    raw_json = json.dumps(clean, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return _LIST_SIGNATURE_DOMAIN + raw_json.encode("utf-8")


def _load_public_key(public_key_pem: str | bytes) -> Ed25519PublicKey:
    data = public_key_pem.encode("utf-8") if isinstance(public_key_pem, str) else bytes(public_key_pem)
    key = serialization.load_pem_public_key(data)
    if not isinstance(key, Ed25519PublicKey):
        raise ValueError("Ожидался открытый ключ Ed25519.")
    return key


def parse_and_verify_signed_list(
    raw_bytes: bytes,
    *,
    public_key_pem: str,
    expected_app_id: str = APP_ID,
    min_list_version: int = 0,
) -> VerifiedLicenseList:
    """Разобрать и проверить Ed25519-подпись, app_id и монотонную версию списка."""
    try:
        data = json.loads(raw_bytes.decode("utf-8"))
    except Exception as exc:
        raise LicenseError("signature_invalid", tr("license.err.invalid_list_format")) from exc

    if not isinstance(data, dict):
        raise LicenseError("signature_invalid", tr("license.err.invalid_list_format"))

    if data.get("schema") != LIST_SCHEMA or data.get("app_id") != expected_app_id:
        raise LicenseError("signature_invalid", tr("license.err.invalid_app_or_schema"))

    list_ver = data.get("list_version")
    if not isinstance(list_ver, int) or isinstance(list_ver, bool) or list_ver < 1:
        raise LicenseError("signature_invalid", tr("license.err.invalid_list_format"))

    gen_at = data.get("generated_at")
    if not isinstance(gen_at, str) or not gen_at.strip():
        raise LicenseError("signature_invalid", tr("license.err.invalid_list_format"))
    try:
        parse_iso(gen_at)
    except Exception as exc:
        raise LicenseError("signature_invalid", tr("license.err.invalid_list_format")) from exc

    licenses_raw = data.get("licenses")
    if not isinstance(licenses_raw, list):
        raise LicenseError("signature_invalid", tr("license.err.invalid_list_format"))

    entries: dict[str, VerifiedLicenseEntry] = {}
    for item in licenses_raw:
        if not isinstance(item, dict):
            raise LicenseError("signature_invalid", tr("license.err.invalid_list_format"))
        kh = item.get("key_hash")
        if not isinstance(kh, str) or not _SHA256_HEX_RE.match(kh):
            raise LicenseError("signature_invalid", tr("license.err.invalid_list_format"))
        exp = item.get("expires_at")
        if exp is not None:
            if not isinstance(exp, str):
                raise LicenseError("signature_invalid", tr("license.err.invalid_list_format"))
            try:
                parse_iso(exp)
            except Exception as exc:
                raise LicenseError("signature_invalid", tr("license.err.invalid_list_format")) from exc
        entries[kh] = VerifiedLicenseEntry(key_hash=kh, expires_at=exp)

    sig_b64 = data.get("signature")
    if not isinstance(sig_b64, str) or not sig_b64.strip():
        raise LicenseError("signature_invalid", tr("license.err.signature_invalid"))
    try:
        sig_bytes = base64.b64decode(sig_b64.encode("ascii"), validate=True)
    except Exception as exc:
        raise LicenseError("signature_invalid", tr("license.err.signature_invalid")) from exc
    if len(sig_bytes) != 64:
        raise LicenseError("signature_invalid", tr("license.err.signature_invalid"))

    try:
        pub = _load_public_key(public_key_pem)
        pub.verify(sig_bytes, _canonical_list_bytes(data))
    except (InvalidSignature, ValueError) as exc:
        raise LicenseError("signature_invalid", tr("license.err.signature_invalid")) from exc

    if list_ver < int(min_list_version):
        raise LicenseError(
            "rollback_detected",
            tr("license.err.rollback_detected", got=list_ver, expected=min_list_version),
        )

    return VerifiedLicenseList(
        app_id=str(data["app_id"]),
        list_version=list_ver,
        generated_at=gen_at,
        entries_by_hash=entries,
        raw_bytes=bytes(raw_bytes),
    )


def _with_cache_buster(url: str, now: datetime) -> str:
    parsed = urllib.parse.urlparse(url)
    qs = urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
    qs = [(k, v) for k, v in qs if k != "_t"]
    qs.append(("_t", str(int(now.timestamp()))))
    new_query = urllib.parse.urlencode(qs)
    return urllib.parse.urlunparse(parsed._replace(query=new_query))


def fetch_signed_list_bytes(
    list_url: str,
    *,
    timeout_sec: float = 10.0,
    url_opener: Callable[..., Any] | None = None,
    cache_bust: bool = True,
    now: datetime | None = None,
) -> bytes:
    """Скачать публичный файл списка лицензий по HTTPS без учётной записи GitHub."""
    cleaned = str(list_url or "").strip()
    parsed = urllib.parse.urlparse(cleaned)
    if parsed.scheme.lower() != "https" or not parsed.netloc:
        raise LicenseError("network_error", tr("license.err.invalid_url"))

    target_url = _with_cache_buster(cleaned, now or utc_now()) if cache_bust else cleaned
    req = urllib.request.Request(
        target_url,
        method="GET",
        headers={
            "User-Agent": f"GeoPointMapper/{APP_VERSION}",
            "Accept": "application/json",
            "Cache-Control": "no-cache, no-store",
            "Pragma": "no-cache",
        },
    )
    opener = url_opener or urllib.request.urlopen
    ctx = build_ssl_context()
    try:
        try:
            resp_ctx = opener(req, timeout=timeout_sec, context=ctx)
        except TypeError:
            resp_ctx = opener(req, timeout=timeout_sec)
        with resp_ctx as resp:
            raw = resp.read(MAX_LIST_BYTES + 1)
    except urllib.error.HTTPError as exc:
        raise LicenseError("network_error", tr("license.err.github_http", code=exc.code)) from exc
    except (urllib.error.URLError, TimeoutError, ssl.SSLError, OSError) as exc:
        raise LicenseError("network_error", tr("license.err.network_unavailable")) from exc

    if len(raw) > MAX_LIST_BYTES:
        raise LicenseError("signature_invalid", tr("license.err.invalid_list_format"))
    return bytes(raw)


class LicenseService:
    """Клиентский сервис активации, кэша на 72 часа и защиты от отката/подмены."""

    def __init__(
        self,
        *,
        list_url: str = LICENSE_LIST_URL,
        public_key_pem: str = LICENSE_PUBLIC_KEY_PEM,
        app_id: str = APP_ID,
        offline_max_hours: int = OFFLINE_LEASE_MAX_HOURS,
        credential_store: CredentialStore | None = None,
        cache_path: Path | None = None,
        now_provider: Callable[[], datetime] | None = None,
        url_opener: Callable[..., Any] | None = None,
        cache_bust: bool = True,
        timeout_sec: float = 10.0,
    ) -> None:
        self._list_url = str(list_url).strip()
        self._public_key_pem = str(public_key_pem)
        self._app_id = str(app_id)
        self._offline_max_hours = max(1, int(offline_max_hours))
        self._store = credential_store or create_default_credential_store()
        self._cache_path = Path(cache_path) if cache_path is not None else default_license_cache_path()
        self._now = now_provider or utc_now
        self._url_opener = url_opener
        self._cache_bust = cache_bust
        self._timeout_sec = float(timeout_sec)

    def _read_json_cred(self, target: str) -> dict[str, Any] | None:
        raw = self._store.read(target)
        if not raw:
            return None
        try:
            data = json.loads(raw.decode("utf-8"))
        except Exception:
            return None
        return data if isinstance(data, dict) else None

    def _write_json_cred(self, target: str, payload: dict[str, Any]) -> None:
        raw = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        self._store.write(target, raw)

    def _get_watermark(self) -> int:
        data = self._read_json_cred(CRED_TARGET_WATERMARK)
        if not data or data.get("app_id") != self._app_id:
            return 0
        ver = data.get("min_list_version", 0)
        return int(ver) if isinstance(ver, int) and not isinstance(ver, bool) and ver >= 0 else 0

    def _update_watermark(self, list_version: int) -> None:
        current = self._get_watermark()
        new_ver = max(current, int(list_version))
        self._write_json_cred(
            CRED_TARGET_WATERMARK,
            {"schema": 1, "app_id": self._app_id, "min_list_version": new_ver},
        )

    def _read_state(self) -> dict[str, Any] | None:
        data = self._read_json_cred(CRED_TARGET_STATE)
        if not data:
            return None
        if data.get("schema") != 1 or data.get("app_id") != self._app_id:
            return None
        kh = data.get("key_hash")
        if not isinstance(kh, str) or not _SHA256_HEX_RE.match(kh):
            return None
        return data

    def _write_state(self, state: dict[str, Any]) -> None:
        self._write_json_cred(CRED_TARGET_STATE, state)

    def reset_activation(self) -> None:
        """Сбросить текущую активацию (водяной знак версии списка сохраняется)."""
        try:
            self._store.delete(CRED_TARGET_STATE)
        except OSError:
            pass
        try:
            if self._cache_path.exists():
                self._cache_path.unlink()
        except OSError:
            pass

    def _write_cache_bytes(self, raw_bytes: bytes) -> None:
        try:
            self._cache_path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self._cache_path.with_suffix(self._cache_path.suffix + ".tmp")
            tmp.write_bytes(raw_bytes)
            tmp.replace(self._cache_path)
        except OSError as exc:
            logger.debug("Не удалось записать локальный кэш списка лицензий: %s", exc)

    def _download_and_verify(self, now: datetime) -> VerifiedLicenseList:
        watermark = self._get_watermark()
        raw = fetch_signed_list_bytes(
            self._list_url,
            timeout_sec=self._timeout_sec,
            url_opener=self._url_opener,
            cache_bust=self._cache_bust,
            now=now,
        )
        verified = parse_and_verify_signed_list(
            raw,
            public_key_pem=self._public_key_pem,
            expected_app_id=self._app_id,
            min_list_version=watermark,
        )
        self._update_watermark(verified.list_version)
        self._write_cache_bytes(verified.raw_bytes)
        return verified

    @staticmethod
    def _find_entry(verified: VerifiedLicenseList, key_hash: str) -> VerifiedLicenseEntry | None:
        for kh, entry in verified.entries_by_hash.items():
            if hmac.compare_digest(kh, key_hash):
                return entry
        return None

    def _offline_remaining_sec(self, last_verified_iso: str, license_expires_iso: str | None, now: datetime) -> tuple[int, str]:
        """Рассчитать остаток 72-часового окна и проверить, не истекла ли лицензия или часы."""
        try:
            last_dt = parse_iso(last_verified_iso)
        except Exception:
            return 0, "invalid_state"

        if now < last_dt - timedelta(seconds=CLOCK_SKEW_TOLERANCE_SEC):
            return 0, "clock_skew"

        if license_expires_iso:
            try:
                lic_exp_dt = parse_iso(license_expires_iso)
            except Exception:
                return 0, "invalid_state"
            if now >= lic_exp_dt:
                return 0, "expired"

        deadline = last_dt + timedelta(hours=self._offline_max_hours)
        if license_expires_iso:
            deadline = min(deadline, parse_iso(license_expires_iso))

        remaining = int((deadline - now).total_seconds())
        if remaining <= 0:
            return 0, "offline_expired"
        return remaining, "ok"

    def activate(self, raw_key: str) -> LicenseCheckResult:
        """Выполнить первичную онлайн-активацию по ключу (без сети недоступна)."""
        try:
            canonical = normalize_license_key(raw_key)
        except ValueError:
            return LicenseCheckResult(
                authorized=False,
                status="key_invalid",
                error_code="key_invalid",
                message=tr("license.err.key_invalid_format"),
            )

        now = self._now()
        try:
            verified = self._download_and_verify(now)
        except LicenseError as exc:
            return LicenseCheckResult(
                authorized=False,
                status=exc.code,
                error_code=exc.code,
                message=exc.message,
            )
        except OSError as exc:
            return LicenseCheckResult(
                authorized=False,
                status="storage_error",
                error_code="storage_error",
                message=tr("license.err.storage_failed", detail=str(exc)),
            )

        key_hash = hash_license_key(canonical, self._app_id)
        key_mask = mask_license_key(canonical)
        entry = self._find_entry(verified, key_hash)
        if entry is None:
            return LicenseCheckResult(
                authorized=False,
                status="key_invalid",
                error_code="key_invalid",
                message=tr("license.err.key_not_found"),
                list_version=verified.list_version,
                online_checked=True,
            )

        if entry.expires_at and parse_iso(entry.expires_at) <= now:
            return LicenseCheckResult(
                authorized=False,
                status="expired",
                error_code="key_expired",
                message=tr("license.err.key_expired"),
                key_mask=key_mask,
                license_expires_at=entry.expires_at,
                list_version=verified.list_version,
                online_checked=True,
            )

        now_iso = to_iso(now)
        state = {
            "schema": 1,
            "app_id": self._app_id,
            "key_hash": key_hash,
            "key_mask": key_mask,
            "activated_at": now_iso,
            "last_verified_at": now_iso,
            "license_expires_at": entry.expires_at,
            "list_version": verified.list_version,
        }
        try:
            self._write_state(state)
        except OSError as exc:
            return LicenseCheckResult(
                authorized=False,
                status="storage_error",
                error_code="storage_error",
                message=tr("license.err.storage_failed", detail=str(exc)),
            )

        remaining, _ = self._offline_remaining_sec(now_iso, entry.expires_at, now)
        return LicenseCheckResult(
            authorized=True,
            status="active",
            message=tr("license.status.active"),
            key_mask=key_mask,
            license_expires_at=entry.expires_at,
            last_verified_at=now_iso,
            list_version=verified.list_version,
            offline_remaining_seconds=remaining,
            online_checked=True,
        )

    def _evaluate_offline_cache(self, state: dict[str, Any], now: datetime) -> LicenseCheckResult:
        """Проверить локально сохранённое состояние + подписанный кэш без продления срока 72 ч."""
        key_hash = str(state["key_hash"])
        key_mask = str(state.get("key_mask", ""))
        last_verified_at = str(state.get("last_verified_at", ""))
        license_expires_at = state.get("license_expires_at")
        state_ver = int(state.get("list_version", 0))

        remaining, reason = self._offline_remaining_sec(last_verified_at, license_expires_at, now)
        if reason == "expired":
            self.reset_activation()
            return LicenseCheckResult(
                authorized=False,
                status="expired",
                error_code="key_expired",
                message=tr("license.err.key_expired"),
                key_mask=key_mask,
                license_expires_at=license_expires_at,
                last_verified_at=last_verified_at,
                list_version=state_ver,
            )
        if reason != "ok":
            return LicenseCheckResult(
                authorized=False,
                status="offline_expired",
                error_code="offline_expired",
                message=tr("license.err.offline_expired"),
                key_mask=key_mask,
                license_expires_at=license_expires_at,
                last_verified_at=last_verified_at,
                list_version=state_ver,
            )

        # Если локальный подписанный кэш присутствует — проверяем его подпись, версию и наличие ключа
        if self._cache_path.exists():
            try:
                raw_cache = self._cache_path.read_bytes()
                watermark = max(state_ver, self._get_watermark())
                cached_list = parse_and_verify_signed_list(
                    raw_cache,
                    public_key_pem=self._public_key_pem,
                    expected_app_id=self._app_id,
                    min_list_version=watermark,
                )
            except LicenseError as exc:
                return LicenseCheckResult(
                    authorized=False,
                    status=exc.code,
                    error_code=exc.code,
                    message=exc.message,
                    key_mask=key_mask,
                    license_expires_at=license_expires_at,
                    last_verified_at=last_verified_at,
                    list_version=state_ver,
                )

            entry = self._find_entry(cached_list, key_hash)
            if entry is None:
                self.reset_activation()
                return LicenseCheckResult(
                    authorized=False,
                    status="revoked",
                    error_code="key_revoked",
                    message=tr("license.err.key_revoked"),
                    key_mask=key_mask,
                    last_verified_at=last_verified_at,
                    list_version=cached_list.list_version,
                )
            if entry.expires_at and parse_iso(entry.expires_at) <= now:
                self.reset_activation()
                return LicenseCheckResult(
                    authorized=False,
                    status="expired",
                    error_code="key_expired",
                    message=tr("license.err.key_expired"),
                    key_mask=key_mask,
                    license_expires_at=entry.expires_at,
                    last_verified_at=last_verified_at,
                    list_version=cached_list.list_version,
                )
            state_ver = cached_list.list_version

        hours_left = max(1, remaining // 3600)
        return LicenseCheckResult(
            authorized=True,
            status="active_offline",
            message=tr("license.status.offline_grace", hours=hours_left),
            key_mask=key_mask,
            license_expires_at=license_expires_at,
            last_verified_at=last_verified_at,
            list_version=state_ver,
            offline_remaining_seconds=remaining,
            online_checked=False,
        )

    def check_startup_access(self) -> LicenseCheckResult:
        """Проверить разрешение при запуске до открытия рабочего окна."""
        try:
            state = self._read_state()
        except OSError as exc:
            return LicenseCheckResult(
                authorized=False,
                status="storage_error",
                error_code="storage_error",
                message=tr("license.err.storage_failed", detail=str(exc)),
            )

        if state is None:
            return LicenseCheckResult(
                authorized=False,
                status="unactivated",
                error_code="unactivated",
                message=tr("license.err.activation_required"),
            )

        now = self._now()
        offline_res = self._evaluate_offline_cache(state, now)
        if offline_res.authorized:
            return offline_res

        # Если срок лицензии уже истёк локально или ключ отозван — сразу блокируем;
        # если истекло 72ч-окно без сети или повреждён кэш — пробуем онлайн-проверку.
        if offline_res.status in ("expired", "revoked"):
            return offline_res

        return self.verify_online()

    def verify_online(self) -> LicenseCheckResult:
        """Скачать свежий список с GitHub, проверить подпись/версию и обновить состояние."""
        try:
            state = self._read_state()
        except OSError as exc:
            return LicenseCheckResult(
                authorized=False,
                status="storage_error",
                error_code="storage_error",
                message=tr("license.err.storage_failed", detail=str(exc)),
            )

        if state is None:
            return LicenseCheckResult(
                authorized=False,
                status="unactivated",
                error_code="unactivated",
                message=tr("license.err.activation_required"),
            )

        now = self._now()
        key_hash = str(state["key_hash"])
        key_mask = str(state.get("key_mask", ""))
        last_verified_at = str(state.get("last_verified_at", ""))
        license_expires_at = state.get("license_expires_at")
        prev_ver = int(state.get("list_version", 0))

        try:
            verified = self._download_and_verify(now)
        except LicenseError as exc:
            # Отклоняем недоступный, подменённый или устаревший список; срок 72 ч НЕ продлевается.
            offline_res = self._evaluate_offline_cache(state, now)
            if offline_res.authorized:
                return LicenseCheckResult(
                    authorized=True,
                    status="active_offline",
                    message=exc.message,
                    key_mask=key_mask,
                    license_expires_at=license_expires_at,
                    last_verified_at=last_verified_at,
                    list_version=prev_ver,
                    offline_remaining_seconds=offline_res.offline_remaining_seconds,
                    online_checked=False,
                    error_code=exc.code,
                )
            return LicenseCheckResult(
                authorized=False,
                status=offline_res.status if offline_res.status == "expired" else exc.code,
                error_code=exc.code,
                message=exc.message,
                key_mask=key_mask,
                license_expires_at=license_expires_at,
                last_verified_at=last_verified_at,
                list_version=prev_ver,
                online_checked=False,
            )
        except OSError as exc:
            return LicenseCheckResult(
                authorized=False,
                status="storage_error",
                error_code="storage_error",
                message=tr("license.err.storage_failed", detail=str(exc)),
                key_mask=key_mask,
            )

        entry = self._find_entry(verified, key_hash)
        if entry is None:
            self.reset_activation()
            return LicenseCheckResult(
                authorized=False,
                status="revoked",
                error_code="key_revoked",
                message=tr("license.err.key_revoked"),
                key_mask=key_mask,
                last_verified_at=last_verified_at,
                list_version=verified.list_version,
                online_checked=True,
            )

        if entry.expires_at and parse_iso(entry.expires_at) <= now:
            self.reset_activation()
            return LicenseCheckResult(
                authorized=False,
                status="expired",
                error_code="key_expired",
                message=tr("license.err.key_expired"),
                key_mask=key_mask,
                license_expires_at=entry.expires_at,
                last_verified_at=last_verified_at,
                list_version=verified.list_version,
                online_checked=True,
            )

        now_iso = to_iso(now)
        updated_state = {
            **state,
            "last_verified_at": now_iso,
            "license_expires_at": entry.expires_at,
            "list_version": verified.list_version,
        }
        try:
            self._write_state(updated_state)
        except OSError as exc:
            return LicenseCheckResult(
                authorized=False,
                status="storage_error",
                error_code="storage_error",
                message=tr("license.err.storage_failed", detail=str(exc)),
                key_mask=key_mask,
            )

        remaining, _ = self._offline_remaining_sec(now_iso, entry.expires_at, now)
        return LicenseCheckResult(
            authorized=True,
            status="active",
            message=tr("license.status.active"),
            key_mask=key_mask,
            license_expires_at=entry.expires_at,
            last_verified_at=now_iso,
            list_version=verified.list_version,
            offline_remaining_seconds=remaining,
            online_checked=True,
        )

    def get_status_snapshot(self) -> LicenseCheckResult:
        """Текущее локальное состояние лицензии для отображения в «Настройки → Лицензия»."""
        try:
            state = self._read_state()
        except OSError as exc:
            return LicenseCheckResult(
                authorized=False,
                status="storage_error",
                error_code="storage_error",
                message=tr("license.err.storage_failed", detail=str(exc)),
            )
        if state is None:
            return LicenseCheckResult(
                authorized=False,
                status="unactivated",
                error_code="unactivated",
                message=tr("license.err.activation_required"),
            )
        return self._evaluate_offline_cache(state, self._now())
