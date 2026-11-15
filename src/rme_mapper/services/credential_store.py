"""Хранилище подписанного лицензионного разрешения в Windows Credential Manager."""
from __future__ import annotations

import ctypes
from ctypes import wintypes
import sys
from typing import Protocol


class CredentialStore(Protocol):
    """Абстракция безопасного хранилища лицензионного разрешения."""

    def read(self, target_name: str) -> bytes | None:
        ...

    def write(self, target_name: str, data: bytes) -> None:
        ...

    def delete(self, target_name: str) -> bool:
        ...


class MemoryCredentialStore:
    """Изолированное хранилище в памяти (только для модульных тестов)."""

    def __init__(self) -> None:
        self._items: dict[str, bytes] = {}

    def read(self, target_name: str) -> bytes | None:
        return self._items.get(target_name)

    def write(self, target_name: str, data: bytes) -> None:
        self._items[target_name] = bytes(data)

    def delete(self, target_name: str) -> bool:
        return self._items.pop(target_name, None) is not None


class WindowsCredentialStore:
    """Хранение данных в Windows Credential Manager через advapi32.dll."""

    CRED_TYPE_GENERIC = 1
    CRED_PERSIST_LOCAL_MACHINE = 2
    CRED_MAX_CREDENTIAL_BLOB_SIZE = 5120
    ERROR_NOT_FOUND = 1168

    def __init__(self, username: str = "GeoPointMapper") -> None:
        if sys.platform != "win32":
            raise RuntimeError("WindowsCredentialStore поддерживается только в Windows")
        self._username = username
        self._advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
        self._setup_functions()

    def _setup_functions(self) -> None:
        class _FILETIME(ctypes.Structure):
            _fields_ = [("dwLowDateTime", wintypes.DWORD), ("dwHighDateTime", wintypes.DWORD)]

        class _CREDENTIAL_ATTRIBUTEW(ctypes.Structure):
            _fields_ = [
                ("Keyword", wintypes.LPWSTR),
                ("Flags", wintypes.DWORD),
                ("ValueSize", wintypes.DWORD),
                ("Value", ctypes.POINTER(ctypes.c_ubyte)),
            ]

        class _CREDENTIALW(ctypes.Structure):
            _fields_ = [
                ("Flags", wintypes.DWORD),
                ("Type", wintypes.DWORD),
                ("TargetName", wintypes.LPWSTR),
                ("Comment", wintypes.LPWSTR),
                ("LastWritten", _FILETIME),
                ("CredentialBlobSize", wintypes.DWORD),
                ("CredentialBlob", ctypes.POINTER(ctypes.c_ubyte)),
                ("Persist", wintypes.DWORD),
                ("AttributeCount", wintypes.DWORD),
                ("Attributes", ctypes.POINTER(_CREDENTIAL_ATTRIBUTEW)),
                ("TargetAlias", wintypes.LPWSTR),
                ("UserName", wintypes.LPWSTR),
            ]

        self._CREDENTIALW = _CREDENTIALW
        self._PCREDENTIALW = ctypes.POINTER(_CREDENTIALW)

        self._CredWriteW = self._advapi32.CredWriteW
        self._CredWriteW.argtypes = [ctypes.POINTER(_CREDENTIALW), wintypes.DWORD]
        self._CredWriteW.restype = wintypes.BOOL

        self._CredReadW = self._advapi32.CredReadW
        self._CredReadW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.POINTER(self._PCREDENTIALW)]
        self._CredReadW.restype = wintypes.BOOL

        self._CredDeleteW = self._advapi32.CredDeleteW
        self._CredDeleteW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD]
        self._CredDeleteW.restype = wintypes.BOOL

        self._CredFree = self._advapi32.CredFree
        self._CredFree.argtypes = [ctypes.c_void_p]
        self._CredFree.restype = None

    def read(self, target_name: str) -> bytes | None:
        pcred = self._PCREDENTIALW()
        ok = self._CredReadW(target_name, self.CRED_TYPE_GENERIC, 0, ctypes.byref(pcred))
        if not ok:
            err = ctypes.get_last_error()
            if err == self.ERROR_NOT_FOUND:
                return None
            raise OSError(None, f"CredReadW failed ({err}): {ctypes.FormatError(err).strip()}", None, err)
        try:
            cred = pcred.contents
            size = int(cred.CredentialBlobSize)
            if size <= 0 or not cred.CredentialBlob:
                return b""
            return ctypes.string_at(cred.CredentialBlob, size)
        finally:
            self._CredFree(pcred)

    def write(self, target_name: str, data: bytes) -> None:
        raw = bytes(data)
        if len(raw) > self.CRED_MAX_CREDENTIAL_BLOB_SIZE:
            raise ValueError(f"Размер разрешения ({len(raw)} байт) превышает лимит Windows Credential Manager.")
        buf = (ctypes.c_ubyte * len(raw)).from_buffer_copy(raw) if raw else None
        cred = self._CREDENTIALW()
        cred.Flags = 0
        cred.Type = self.CRED_TYPE_GENERIC
        cred.TargetName = target_name
        cred.Comment = "GeoPoint Mapper signed license lease"
        cred.CredentialBlobSize = len(raw)
        cred.CredentialBlob = ctypes.cast(buf, ctypes.POINTER(ctypes.c_ubyte)) if buf is not None else None
        cred.Persist = self.CRED_PERSIST_LOCAL_MACHINE
        cred.AttributeCount = 0
        cred.Attributes = None
        cred.TargetAlias = None
        cred.UserName = self._username
        ok = self._CredWriteW(ctypes.byref(cred), 0)
        if not ok:
            err = ctypes.get_last_error()
            raise OSError(None, f"CredWriteW failed ({err}): {ctypes.FormatError(err).strip()}", None, err)

    def delete(self, target_name: str) -> bool:
        ok = self._CredDeleteW(target_name, self.CRED_TYPE_GENERIC, 0)
        if ok:
            return True
        err = ctypes.get_last_error()
        if err == self.ERROR_NOT_FOUND:
            return False
        raise OSError(None, f"CredDeleteW failed ({err}): {ctypes.FormatError(err).strip()}", None, err)


def create_default_credential_store() -> CredentialStore:
    if sys.platform == "win32":
        return WindowsCredentialStore()
    return MemoryCredentialStore()
