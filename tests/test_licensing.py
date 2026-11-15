"""Комплексные автотесты бессерверной системы лицензирования GeoPoint Mapper."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import io
import json
from pathlib import Path
import sys
from typing import Any
import urllib.error
import zipfile

import pytest
from PySide6.QtWidgets import QApplication, QDialog, QMessageBox

try:
    from license_manager.crypto import (
        APP_ID,
        hash_license_key,
        mask_license_key,
        sign_license_list,
        verify_license_list_signature,
    )
    from license_manager.gui import LicenseManagerWindow
    from license_manager.storage import OwnerLicenseStorage
    _HAS_OWNER_TOOL = True
except ImportError:  # pragma: no cover - когда репозиторий клонирован без license_manager
    _HAS_OWNER_TOOL = False

_REQUIRES_OWNER_TOOL = pytest.mark.skipif(
    not _HAS_OWNER_TOOL,
    reason="license_manager не входит в публичный репозиторий",
)
from rme_mapper.services.app_settings_service import AppSettingsService
from rme_mapper.services.credential_store import MemoryCredentialStore
from rme_mapper.services.license_service import LicenseService
from rme_mapper.ui.activation_dialog import ActivationDialog
from rme_mapper.ui.license_controller import LicenseController, save_modified_project_before_lockout
from rme_mapper.ui.main_window import MainWindow
from rme_mapper.ui.settings_dialog import SettingsDialog


class _FakeClock:
    def __init__(self, start: datetime | None = None) -> None:
        self.now = start or datetime(2026, 11, 15, 12, 0, 0, tzinfo=timezone.utc)

    def __call__(self) -> datetime:
        return self.now

    def advance(self, **kwargs: Any) -> datetime:
        self.now = self.now + timedelta(**kwargs)
        return self.now


class _FakeHTTPResp(io.BytesIO):
    def __enter__(self) -> "_FakeHTTPResp":
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()


class _FakeGitHubHost:
    def __init__(self) -> None:
        self.payload_bytes: bytes = b"{}"
        self.fail_network: bool = False

    def set_file(self, path: Path) -> None:
        self.payload_bytes = path.read_bytes()

    def set_json(self, doc: dict[str, Any]) -> None:
        self.payload_bytes = json.dumps(doc).encode("utf-8")

    def open(self, req: Any, timeout: float = 10.0, context: Any = None) -> _FakeHTTPResp:
        if self.fail_network:
            raise urllib.error.URLError("GitHub unreachable")
        return _FakeHTTPResp(self.payload_bytes)


def _make_client_service(
    owner: OwnerLicenseStorage,
    host: _FakeGitHubHost,
    tmp_path: Path,
    clock: _FakeClock,
    store: MemoryCredentialStore | None = None,
) -> tuple[LicenseService, MemoryCredentialStore]:
    cred_store = store or MemoryCredentialStore()
    svc = LicenseService(
        list_url="https://raw.githubusercontent.com/test/geopoint-mapper-licenses/main/licenses.json",
        public_key_pem=owner.get_public_key_pem(),
        credential_store=cred_store,
        cache_path=tmp_path / "client_cache" / "license_cache.json",
        now_provider=clock,
        url_opener=host.open,
    )
    return svc, cred_store


@_REQUIRES_OWNER_TOOL
def test_owner_storage_entropy_privacy_versioning_and_backup(tmp_path: Path):
    clock = _FakeClock()
    owner = OwnerLicenseStorage(data_dir=tmp_path / "owner")
    try:
        assert owner.private_key_path.exists()
        assert owner.public_key_path.exists()
        assert owner.get_state()["dirty_since_export"] is False

        rec1, plain1 = owner.create_key(
            recipient="Иван Петров (ООО Гео)",
            expires_at=clock.now + timedelta(days=30),
            notes="Тестовый клиент №1",
            now=clock.now,
        )
        rec2, plain2 = owner.create_key(
            recipient="Анна Сидорова",
            expires_at=None,
            notes="Бессрочная лицензия",
            now=clock.now,
        )
        assert plain1 != plain2
        assert plain1.startswith("GPM-")
        # 32 символа Base32 после GPM = 160 бит энтропии (>= 128 бит)
        body = plain1.removeprefix("GPM-").replace("-", "")
        assert len(body) == 32
        assert owner.get_state()["dirty_since_export"] is True

        # В локальной БД хранятся только хэш и маска, а не полный ключ
        db_bytes = owner.db_path.read_bytes()
        assert plain1.encode("utf-8") not in db_bytes
        assert plain2.encode("utf-8") not in db_bytes
        assert rec1["key_mask"] == mask_license_key(plain1)

        out1, doc1 = owner.export_signed_list(tmp_path / "pub" / "licenses.json", now=clock.now)
        assert doc1["list_version"] == 1
        assert doc1["app_id"] == APP_ID
        assert len(doc1["licenses"]) == 2
        assert owner.get_state()["dirty_since_export"] is False

        # В публичном файле нет полных ключей, имён получателей, заметок, масок и закрытого ключа
        raw_text = out1.read_text(encoding="utf-8")
        for forbidden in (plain1, plain2, "Иван Петров", "Анна Сидорова", "Тестовый клиент", rec1["key_mask"], "PRIVATE KEY"):
            assert forbidden not in raw_text
        for entry in doc1["licenses"]:
            assert set(entry.keys()) == {"key_hash", "expires_at"}

        verified = verify_license_list_signature(doc1, owner.get_public_key_pem())
        assert verified["list_version"] == 1

        # Отзыв первого ключа -> dirty=True -> экспорт v2 без первого ключа
        assert owner.revoke_key(rec1["id"], now=clock.now + timedelta(minutes=5)) is True
        assert owner.get_state()["dirty_since_export"] is True

        out2, doc2 = owner.export_signed_list(out1, now=clock.now + timedelta(minutes=6))
        assert doc2["list_version"] == 2
        hashes_v2 = {e["key_hash"] for e in doc2["licenses"]}
        assert hash_license_key(plain1) not in hashes_v2
        assert hash_license_key(plain2) in hashes_v2
        assert owner.get_state()["dirty_since_export"] is False

        # Резервная копия БД и ключей
        bak = owner.create_backup_zip(tmp_path / "backup.zip")
        with zipfile.ZipFile(bak, "r") as zf:
            assert set(zf.namelist()) == {"owner_licenses.db", "private_key.pem", "public_key.pem"}
    finally:
        owner.close()


@_REQUIRES_OWNER_TOOL
def test_full_client_cycle_activation_restart_and_revocation(tmp_path: Path):
    clock = _FakeClock()
    owner = OwnerLicenseStorage(data_dir=tmp_path / "owner")
    host = _FakeGitHubHost()
    try:
        rec, plain_key = owner.create_key(
            recipient="Тест Цикл",
            expires_at=clock.now + timedelta(days=90),
            now=clock.now,
        )
        list_path, _ = owner.export_signed_list(tmp_path / "licenses.json", now=clock.now)
        host.set_file(list_path)

        svc, store = _make_client_service(owner, host, tmp_path, clock)

        # Чистая установка: доступ запрещён
        st0 = svc.check_startup_access()
        assert st0.authorized is False
        assert st0.status == "unactivated"

        # Активация по валидному ключу
        res_act = svc.activate(plain_key.lower().replace("-", " "))
        assert res_act.authorized is True
        assert res_act.status == "active"
        assert res_act.key_mask == rec["key_mask"]
        assert res_act.list_version == 1

        # Повторный запуск тем же хранилищем (имитация перезапуска)
        svc2, _ = _make_client_service(owner, host, tmp_path, clock, store=store)
        st_restart = svc2.check_startup_access()
        assert st_restart.authorized is True
        assert st_restart.key_mask == rec["key_mask"]

        # Владелец отзывает ключ и публикует v2
        clock.advance(minutes=10)
        assert owner.revoke_key(rec["id"], now=clock.now) is True
        list_path_v2, doc2 = owner.export_signed_list(list_path, now=clock.now)
        assert doc2["list_version"] == 2
        host.set_file(list_path_v2)

        # На следующей онлайн-проверке активированная копия сбрасывает активацию и блокируется
        res_rev = svc2.verify_online()
        assert res_rev.authorized is False
        assert res_rev.status == "revoked"
        assert svc2.check_startup_access().authorized is False

        # Новая активация отозванным ключом отклоняется
        res_react = svc2.activate(plain_key)
        assert res_react.authorized is False
        assert res_react.status == "key_invalid"
    finally:
        owner.close()


@_REQUIRES_OWNER_TOOL
def test_offline_72h_grace_and_non_extension_by_cache_reads(tmp_path: Path):
    clock = _FakeClock()
    owner = OwnerLicenseStorage(data_dir=tmp_path / "owner")
    host = _FakeGitHubHost()
    try:
        _, plain_key = owner.create_key(
            recipient="Офлайн Тест",
            expires_at=clock.now + timedelta(days=30),
            now=clock.now,
        )
        list_path, _ = owner.export_signed_list(tmp_path / "licenses.json", now=clock.now)
        host.set_file(list_path)
        svc, _ = _make_client_service(owner, host, tmp_path, clock)

        # Без сети первичная активация недоступна
        host.fail_network = True
        first_offline = svc.activate(plain_key)
        assert first_offline.authorized is False
        assert first_offline.status == "network_error"

        # Активируем онлайн
        host.fail_network = False
        assert svc.activate(plain_key).authorized is True

        # Отключаем сеть и многократно запускаем/читаем кэш в пределах 72 часов
        host.fail_network = True
        for h in (24, 24, 23):
            clock.advance(hours=h)
            st = svc.check_startup_access()
            assert st.authorized is True
            assert st.status == "active_offline"
            # Фоновая проверка без сети не продлевает 72-часовой период
            bg = svc.verify_online()
            assert bg.authorized is True
            assert bg.online_checked is False

        # После 72 часов (71 + 2 = 73 часа от активации) без сети доступ прекращается
        clock.advance(hours=2)
        expired_grace = svc.check_startup_access()
        assert expired_grace.authorized is False
        assert expired_grace.status == "network_error"

        # Восстанавливаем сеть -> снова подтверждается онлайн
        host.fail_network = False
        recovered = svc.check_startup_access()
        assert recovered.authorized is True
        assert recovered.status == "active"
    finally:
        owner.close()


@_REQUIRES_OWNER_TOOL
def test_expired_key_spoofed_signature_and_rollback_protection(tmp_path: Path):
    clock = _FakeClock()
    owner = OwnerLicenseStorage(data_dir=tmp_path / "owner")
    host = _FakeGitHubHost()
    try:
        _, key_short = owner.create_key(
            recipient="Короткий срок",
            expires_at=clock.now + timedelta(hours=5),
            now=clock.now,
        )
        _, key_long = owner.create_key(
            recipient="Длинный срок",
            expires_at=clock.now + timedelta(days=365),
            now=clock.now,
        )
        p1, doc1 = owner.export_signed_list(tmp_path / "v1.json", now=clock.now)
        p2, doc2 = owner.export_signed_list(tmp_path / "v2.json", now=clock.now + timedelta(seconds=1))
        assert doc1["list_version"] == 1
        assert doc2["list_version"] == 2

        svc, store = _make_client_service(owner, host, tmp_path, clock)

        # 1. Подменённая подпись отклоняется
        tampered = json.loads(p2.read_text(encoding="utf-8"))
        tampered["licenses"].append({"key_hash": "0" * 64, "expires_at": None})
        host.set_json(tampered)
        res_tamper = svc.activate(key_long)
        assert res_tamper.authorized is False
        assert res_tamper.status == "signature_invalid"

        # 2. Активация подлинным списком v2
        host.set_file(p2)
        assert svc.activate(key_long).authorized is True

        # 3. Откат версии списка (подлинный старый v1 после v2) отклоняется
        host.set_file(p1)
        res_rb = svc.verify_online()
        assert res_rb.online_checked is False
        assert res_rb.error_code == "rollback_detected"

        # Даже после сброса активации водяной знак не даёт активироваться по старому v1
        svc.reset_activation()
        res_rb_act = svc.activate(key_long)
        assert res_rb_act.authorized is False
        assert res_rb_act.status == "rollback_detected"

        # 4. Истёкшая лицензия отклоняется с явным статусом expired
        host.set_file(p2)
        clock.advance(hours=6)
        res_exp = svc.activate(key_short)
        assert res_exp.authorized is False
        assert res_exp.status == "expired"
        assert res_exp.error_code == "key_expired"

        # 5. Неверный ключ отличается от ошибки подписи и сети
        res_bad = svc.activate("not-a-valid-key")
        assert res_bad.authorized is False
        assert res_bad.status == "key_invalid"
    finally:
        owner.close()


def test_clean_startup_and_cli_project_blocked_without_license(qapp, tmp_path: Path, monkeypatch):
    from rme_mapper import main as app_main

    proj_file = tmp_path / "sample.gpmap"
    proj_file.write_text("{}", encoding="utf-8")

    opened_windows: list[Any] = []
    monkeypatch.setattr(app_main, "MainWindow", lambda *a, **kw: opened_windows.append((a, kw)))
    monkeypatch.setattr(
        app_main,
        "LicenseService",
        lambda: LicenseService(
            credential_store=MemoryCredentialStore(),
            cache_path=tmp_path / "empty_cache.json",
        ),
    )
    monkeypatch.setattr(app_main, "show_blocking_activation", lambda *a, **kw: (False, None))
    monkeypatch.setattr(sys, "argv", ["GeoPointMapper.exe", str(proj_file)])

    code = app_main.main()
    assert code == 0
    assert opened_windows == []


@_REQUIRES_OWNER_TOOL
def test_activation_dialog_settings_license_page_and_unsaved_project_save(qapp, tmp_path: Path, monkeypatch):
    clock = _FakeClock()
    owner = OwnerLicenseStorage(data_dir=tmp_path / "owner")
    host = _FakeGitHubHost()
    try:
        rec, plain_key = owner.create_key(
            recipient="UI Тест",
            expires_at=clock.now + timedelta(days=60),
            now=clock.now,
        )
        list_path, _ = owner.export_signed_list(tmp_path / "licenses.json", now=clock.now)
        host.set_file(list_path)
        svc, _ = _make_client_service(owner, host, tmp_path, clock)

        # 1. Окно активации: ошибка без сети, затем успешная активация
        host.fail_network = True
        dlg = ActivationDialog(svc)
        dlg.key_edit.setText(plain_key)
        res_err = svc.activate(plain_key)
        dlg._on_activation_finished(res_err)
        assert dlg.result() != QDialog.DialogCode.Accepted
        assert dlg.status_label.text() != ""

        host.fail_network = False
        res_ok = svc.activate(plain_key)
        dlg._on_activation_finished(res_ok)
        assert dlg.result() == QDialog.DialogCode.Accepted
        dlg.close()

        # 2. Главное окно с LicenseController и SettingsDialog -> «Лицензия»
        win = MainWindow(license_service=svc)
        ctrl = LicenseController(svc, main_window=win)
        win.set_license_controller(ctrl)
        try:
            settings_dlg = SettingsDialog(AppSettingsService(), parent=win, initial_section="license")
            try:
                assert settings_dlg.lbl_license_key_mask.text() == rec["key_mask"]
                assert "Активна" in settings_dlg.lbl_license_status.text()
                assert settings_dlg.btn_license_recheck.text() == "Проверить сейчас"
                settings_dlg._on_license_recheck_clicked()
                assert not settings_dlg.lbl_license_feedback.isHidden()
                assert settings_dlg.lbl_license_feedback.text()
            finally:
                settings_dlg.close()

            # 3. Отзыв во время работы с изменённым проектом: даём сохранить и переходим к активации
            win.project_controller.set_modified(True)
            saved_called = {"count": 0}

            def _fake_save() -> bool:
                saved_called["count"] += 1
                win.project_controller.set_modified(False)
                return True

            monkeypatch.setattr(win, "save_project_before_license_lock", _fake_save)
            monkeypatch.setattr(QMessageBox, "exec", lambda self: self.setResult(0) or 0)

            # Имитируем нажатие «Сохранить проект» в диалоге save_modified_project_before_lockout
            orig_add_button = QMessageBox.addButton
            captured_save_btns: list[Any] = []

            def _capture_add_button(self, text_or_btn, role=None):
                btn = orig_add_button(self, text_or_btn, role) if role is not None else orig_add_button(self, text_or_btn)
                if role == QMessageBox.ButtonRole.AcceptRole:
                    captured_save_btns.append((self, btn))
                return btn

            monkeypatch.setattr(QMessageBox, "addButton", _capture_add_button)
            monkeypatch.setattr(QMessageBox, "clickedButton", lambda self: dict(captured_save_btns).get(self))

            owner.revoke_key(rec["id"], now=clock.now + timedelta(minutes=1))
            list_v2, _ = owner.export_signed_list(list_path, now=clock.now + timedelta(minutes=1))
            host.set_file(list_v2)

            rev_res = svc.verify_online()
            assert rev_res.authorized is False
            save_modified_project_before_lockout(win, rev_res)
            assert saved_called["count"] == 1
            assert win.project_controller.is_modified is False
        finally:
            ctrl.stop()
            win.close()
    finally:
        owner.close()


@_REQUIRES_OWNER_TOOL
def test_owner_gui_and_configure_license_tool(qapp, tmp_path: Path, monkeypatch):
    from tools.configure_license import update_license_config

    owner = OwnerLicenseStorage(data_dir=tmp_path / "owner_gui")
    win = LicenseManagerWindow(storage=owner)
    try:
        assert win.btn_generate.text() == "Сгенерировать"
        assert win.btn_copy.text() == "Скопировать"
        assert win.btn_revoke.text() == "Отозвать"
        assert win.btn_export.text() == "Экспортировать подписанный список"

        rec, plain = owner.create_key(recipient="GUI Получатель", now=_FakeClock()())
        win._last_issued_plain_key = plain
        win._last_issued_key_id = rec["id"]
        win.refresh_all()
        assert win.table.rowCount() == 1
        assert "требуют публикации" in win.lbl_dirty.text()

        copied: list[str] = []
        clipboard = QApplication.clipboard()
        orig_set_text = clipboard.setText
        monkeypatch.setattr(clipboard, "setText", lambda text, *a, **kw: (copied.append(text), orig_set_text(text, *a, **kw))[1])
        win.copy_selected_or_issued_key()
        assert copied == [plain]

        out_path, doc = owner.export_signed_list(tmp_path / "exported_licenses.json")
        win.refresh_all()
        assert doc["list_version"] == 1
        assert "требуют публикации" not in win.lbl_dirty.text()
    finally:
        win.close()
        owner.close()

    with pytest.raises(ValueError):
        update_license_config("http://insecure.example/licenses.json", "PUBLIC KEY")
    with pytest.raises(ValueError):
        update_license_config("https://raw.githubusercontent.com/u/r/main/licenses.json", "BEGIN PRIVATE KEY")
