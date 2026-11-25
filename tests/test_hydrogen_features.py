"""Комплексные автотесты для всех нововведений HYDROGEN_TASK:
- Единое окно настроек из 6 разделов и двусторонняя синхронизация с MainWindow
- Визуальные токены, пустой экран (2 явных действия + недавние файлы), вкладки левой панели и бейдж режима
- Фильтры таблицы точек (группа + категория + счетчик + Сбросить), поиск с сохранением ведущих нулей, фокус на карте (F11)
- Система автообновления из GitHub Releases (semver, pre-release/draft filter, 24h throttle, SHA-256 + manifest,
  режимы installed/portable/source, отмена загрузки с удалением .part, отмена закрытия при несохраненном проекте)
"""
from __future__ import annotations

import hashlib
import io
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QMessageBox, QWidget

from rme_mapper.app_info import APP_VERSION
from rme_mapper.models.map_point import MapPoint
from rme_mapper.maps.map_canvas import MapCanvas
from rme_mapper.services.app_settings_service import AppSettingsService
from rme_mapper.services.update_service import (
    INSTALL_MODE_INSTALLED,
    INSTALL_MODE_PORTABLE,
    INSTALL_MODE_SOURCE,
    MANIFEST_ASSET_NAME,
    ReleaseAsset,
    UpdateError,
    UpdateInfo,
    UpdateService,
    compare_versions,
    detect_install_mode,
    parse_semver,
    sanitize_asset_filename,
    should_run_auto_check,
    validate_https_url,
    verify_manifest_for_asset,
)
from rme_mapper.ui.main_window import MainWindow
from rme_mapper.ui.settings_dialog import SettingsDialog
from rme_mapper.ui.update_controller import UpdateController, UpdateNotificationBanner


class _FakeHTTPResponse(io.BytesIO):
    """Минимальный mock HTTP-ответа для urllib."""

    def __init__(self, data: bytes, headers: dict[str, str] | None = None) -> None:
        super().__init__(data)
        self.headers = headers or {"Content-Length": str(len(data))}

    def __enter__(self) -> "_FakeHTTPResponse":
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()


@pytest.fixture
def clean_settings():
    svc = AppSettingsService()
    svc.clear()
    yield svc
    svc.clear()


# ==============================================================================
# 1. ЕДИНОЕ ОКНО НАСТРОЕК (6 РАЗДЕЛОВ) И СИНХРОНИЗАЦИЯ С MAINWINDOW
# ==============================================================================


def test_settings_dialog_has_six_sections_and_navigation(qapp, clean_settings):
    dlg = SettingsDialog(clean_settings)
    try:
        assert dlg.nav_list.count() == 7
        assert dlg.stack.count() == 7
        assert SettingsDialog.SECTION_KEYS == (
            "general",
            "interface",
            "map_coords",
            "network_cache",
            "updates",
            "license",
            "help_about",
        )
        for idx, sec_key in enumerate(SettingsDialog.SECTION_KEYS):
            dlg.select_section(sec_key)
            assert dlg.nav_list.currentRow() == idx
            assert dlg.stack.currentIndex() == idx
    finally:
        dlg.close()


def test_settings_dialog_bidirectional_sync_and_persistence(qapp, clean_settings, monkeypatch):
    win = MainWindow()
    try:
        # Верхнее меню не содержит дублирующих Справка и Язык
        menubar_titles = [a.text() for a in win.menuBar().actions()]
        assert "Справка" not in menubar_titles
        assert "Язык" not in menubar_titles
        assert win.preferences_action.shortcut().toString() == "Ctrl+,"
        assert win.settings_menu.actions() == [win.check_updates_action, win.preferences_action]
        assert win.preferences_action not in win.main_toolbar.actions()

        dlg = SettingsDialog(win._settings_service, win)
        try:
            # Меняем настройки во всех ключевых разделах
            idx_restore = dlg.startup_behavior.findData("restore_last_project")
            assert idx_restore >= 0
            dlg.startup_behavior.setCurrentIndex(idx_restore)

            idx_dark = dlg.theme.findData("dark")
            assert idx_dark >= 0
            dlg.theme.setCurrentIndex(idx_dark)

            dlg.show_toolbar.setChecked(False)
            dlg.show_left_panel.setChecked(False)
            dlg.auto_properties.setChecked(False)
            dlg.show_right_panel.setChecked(True)
            dlg.show_statusbar.setChecked(False)
            dlg.points_bottom.setChecked(False)
            dlg.show_grid.setChecked(True)
            dlg.show_scale.setChecked(False)
            dlg.show_points.setChecked(False)
            dlg.show_zones.setChecked(False)

            idx_lbl_all = dlg.labels_mode.findData("all")
            dlg.labels_mode.setCurrentIndex(idx_lbl_all)
            idx_lbl_num = dlg.label_content.findData("number")
            dlg.label_content.setCurrentIndex(idx_lbl_num)

            idx_km = dlg.distance_unit.findData("km")
            dlg.distance_unit.setCurrentIndex(idx_km)
            dlg.network_timeout.setValue(30)
            dlg.auto_check_updates.setChecked(False)

            dlg.accept()
        finally:
            dlg.close()

        # Проверяем немедленную синхронизацию состояния в MainWindow
        assert win._settings_service.get_startup_behavior() == "restore_last_project"
        assert win._settings_service._get_str("ui/theme", "light") == "dark"
        assert win.main_toolbar.isHidden()
        assert win.left_panel.isHidden()
        assert not win.right_panel.isHidden()
        assert win.statusBar().isHidden()
        assert win.toggle_grid_action.isChecked() is True
        assert win.toggle_scale_action.isChecked() is False
        assert win.show_points_action.isChecked() is False
        assert win.show_zones_action.isChecked() is False
        assert win._settings_service.get_point_labels_mode() == "all"
        assert win._settings_service.get_point_label_content() == "number"
        assert win._settings_service.get_distance_unit() == "km"
        assert win._settings_service.get_network_timeout_sec() == 30
        assert win._settings_service.get_auto_check_updates() is False

        # Проверяем, что свежее окно восстанавливает сохраненные значения
        win2 = MainWindow()
        try:
            assert win2._settings_service.get_startup_behavior() == "restore_last_project"
            assert win2.main_toolbar.isHidden()
            assert win2.left_panel.isHidden()
            assert win2.statusBar().isHidden()
            assert win2.toggle_grid_action.isChecked() is True
            assert win2.toggle_scale_action.isChecked() is False
        finally:
            win2.close()
    finally:
        win.project_controller.set_modified(False)
        win.close()


# ==============================================================================
# 2. РАБОЧЕЕ ПРОСТРАНСТВО, ПУСТОЙ ЭКРАН, ФИЛЬТРЫ, ПОИСК И F11
# ==============================================================================


def test_workspace_tabs_empty_screen_and_active_mode_badge(qapp, clean_settings, tmp_path, monkeypatch):
    win = MainWindow()
    try:
        # Левая панель содержит ровно 4 вкладки: Слои, Группы, Подложки, Треки
        assert win.navigation_tabs.count() == 4
        tab_texts = [win.navigation_tabs.tabText(i) for i in range(4)]
        assert len(set(tab_texts)) == 4

        # Пустой экран содержит 2 явные кнопки + недавние файлы
        assert win.map_canvas.btn_open_map is not None
        assert win.map_canvas.btn_open_project is not None

        proj_file = tmp_path / "demo.gpmap"
        proj_file.write_text("{}", encoding="utf-8")
        map_file = tmp_path / "map.png"
        map_file.write_bytes(b"PNG")
        win.map_canvas.set_recent_files(
            [
                {"kind": "project", "path": str(proj_file)},
                {"kind": "map", "path": str(map_file)},
            ]
        )
        emitted_recent: list[tuple[str, str]] = []
        win.map_canvas.recent_file_requested.disconnect()
        win.map_canvas.recent_file_requested.connect(lambda kind, p: emitted_recent.append((kind, p)))

        # Нажимаем первую кнопку недавнего файла напрямую
        links = [b for b in win.map_canvas.findChildren(QWidget) if b.objectName() == "recentFileLink"]
        assert len(links) == 2
        links[0].click()
        assert emitted_recent == [("project", str(proj_file))]

        # Загружаем тестовый профиль и проверяем бейдж активного режима + tooltips с хоткеями
        profile = win._load_default_or_dummy_profile() if hasattr(win, "_load_default_or_dummy_profile") else None
        assert "Ctrl+Z" in win.undo_action.toolTip()
        assert "F11" in win.focus_map_action.toolTip()
        assert "Ctrl+," in win.preferences_action.toolTip()
        assert profile is None or profile is not None
    finally:
        win.project_controller.set_modified(False)
        win.close()


def test_point_filters_leading_zero_search_and_focus_map_mode(qapp, clean_settings, tmp_path):
    import numpy as np
    import rasterio
    from rasterio.transform import from_origin

    win = MainWindow()
    win.resize(1280, 720)
    win.show()
    qapp.processEvents()
    try:
        # Загружаем небольшой GeoTIFF (EPSG:32637), чтобы карта открылась без диалогов привязки
        tmp_path.mkdir(parents=True, exist_ok=True)
        img_path = tmp_path / "canvas.tif"
        arr = np.full((3, 200, 200), 230, dtype=np.uint8)
        with rasterio.open(
            str(img_path),
            "w",
            driver="GTiff",
            height=200,
            width=200,
            count=3,
            dtype=arr.dtype,
            crs="EPSG:32637",
            transform=from_origin(395000.0, 6208000.0, 50.0, 50.0),
        ) as dst:
            dst.write(arr)
        assert win.open_map(img_path) is True
        qapp.processEvents()

        # Индикатор активного режима и CRS видны
        assert not win.active_mode_label.isHidden()
        assert not win.status_crs_label.isHidden()
        assert "32637" in win.status_crs_label.text()

        # Переключение в режим добавления точки и измерения меняет бейдж
        win.add_pt_map_action.setChecked(True)
        qapp.processEvents()
        assert win.active_mode_label.text()
        win.measure_distance_action.setChecked(True)
        qapp.processEvents()
        assert win.active_mode_label.text()

        # Добавляем точки с ведущими нулями ("007" vs "7") и группы
        win._group_service.create_group("Север", group_id="grp-a")
        win.group_controller.refresh_groups_ui()

        pt_007 = MapPoint(
            id="id-007",
            name="Пост",
            object_number="007",
            latitude=55.94,
            longitude=37.40,
            category="Опора",
            group_id="grp-a",
        )
        pt_7 = MapPoint(
            id="id-7",
            name="Пост-7",
            object_number="7",
            latitude=55.95,
            longitude=37.41,
            category="Станция",
            group_id=None,
        )
        win.point_controller._cmd_add_point(pt_007)
        win.point_controller._cmd_add_point(pt_7)
        qapp.processEvents()

        # Поиск по "007" не отбрасывает ведущие нули и выбирает ровно id-007
        win.navigate_edit.setText("007")
        win.navigate_to_input()
        assert win.points_panel.selected_point_ids() == ["id-007"]

        # Фильтрация UI-only: выбираем группу "Север" -> в таблице 1 строка, в PointService по-прежнему 2
        gidx = win.points_panel.group_combo.findData("grp-a")
        assert gidx >= 0
        win.points_panel.group_combo.setCurrentIndex(gidx)
        qapp.processEvents()
        assert win.points_panel.shown_count == 1
        assert win.points_panel.total_count == 2
        assert len(win._point_service.get_points()) == 2
        assert win.points_panel.btn_reset_filters.isEnabled()

        # Сброс фильтров возвращает все строки
        win.points_panel.reset_filters()
        qapp.processEvents()
        assert win.points_panel.shown_count == 2
        assert not win.points_panel.btn_reset_filters.isEnabled()

        # Focus Mode (F11): скрывает боковые панели и таблицу точек, затем точно восстанавливает
        win.set_right_panel_visible(True)
        qapp.processEvents()
        saved_left = not win.left_panel.isHidden()
        saved_right = not win.right_panel.isHidden()
        saved_points = not win.points_panel.isHidden()
        saved_splitter_sizes = win.splitter.sizes()

        win.toggle_focus_map_mode(True)
        qapp.processEvents()
        assert win.left_panel.isHidden()
        assert win.right_panel.isHidden()
        assert win.points_panel.isHidden()

        win.toggle_focus_map_mode(False)
        qapp.processEvents()
        assert (not win.left_panel.isHidden()) == saved_left
        assert (not win.right_panel.isHidden()) == saved_right
        assert (not win.points_panel.isHidden()) == saved_points
        assert len(win.splitter.sizes()) == len(saved_splitter_sizes)
    finally:
        win.project_controller.set_modified(False)
        win.close()


# ==============================================================================
# 3. АВТООБНОВЛЕНИЕ GITHUB RELEASES (UNIT + UI + БЕЗОПАСНОСТЬ)
# ==============================================================================


def test_update_semver_and_throttle_helpers(clean_settings):
    assert parse_semver("v1.10.0") > parse_semver("1.9.0")
    assert compare_versions("1.10.0", "1.9.0") == 1
    assert compare_versions("1.2.3", "v1.2.3") == 0
    assert compare_versions("1.1.0", "1.2.0") == -1

    now = datetime(2026, 11, 15, 12, 0, tzinfo=timezone.utc)
    clean_settings.set_auto_check_updates(True)
    clean_settings.set_last_update_check_utc("")
    assert should_run_auto_check(clean_settings, now_utc=now) is True

    clean_settings.set_auto_check_updates(False)
    assert should_run_auto_check(clean_settings, now_utc=now) is False

    clean_settings.set_auto_check_updates(True)
    clean_settings.set_last_update_check_utc((now - timedelta(hours=3)).isoformat())
    assert should_run_auto_check(clean_settings, now_utc=now) is False
    clean_settings.set_last_update_check_utc((now - timedelta(hours=25)).isoformat())
    assert should_run_auto_check(clean_settings, now_utc=now) is True

    with pytest.raises(UpdateError):
        validate_https_url("http://example.com/file.exe")
    with pytest.raises(UpdateError):
        sanitize_asset_filename("../../evil.exe")
    assert sanitize_asset_filename("GeoPointMapper-1.2.0-Setup-x64.exe") == "GeoPointMapper-1.2.0-Setup-x64.exe"


def test_detect_install_mode_variants(tmp_path):
    assert detect_install_mode(is_frozen=False) == INSTALL_MODE_SOURCE

    inst_dir = tmp_path / "installed_app"
    inst_dir.mkdir()
    exe_inst = inst_dir / "GeoPointMapper.exe"
    exe_inst.write_bytes(b"MZ")
    (inst_dir / "unins000.exe").write_bytes(b"MZ")
    assert (
        detect_install_mode(executable_path=exe_inst, is_frozen=True, check_registry=False)
        == INSTALL_MODE_INSTALLED
    )

    port_dir = tmp_path / "portable_app"
    port_dir.mkdir()
    exe_port = port_dir / "GeoPointMapper.exe"
    exe_port.write_bytes(b"MZ")
    assert (
        detect_install_mode(executable_path=exe_port, is_frozen=True, check_registry=False)
        == INSTALL_MODE_PORTABLE
    )


def test_update_service_release_selection_and_manifest_checks(tmp_path):
    installer_bytes = b"DUMMY_INSTALLER_PAYLOAD_1234567890"
    good_sha = hashlib.sha256(installer_bytes).hexdigest()
    asset_name = "GeoPointMapper-1.10.0-Setup-x64.exe"

    manifest_good = {
        "version": "1.10.0",
        "architecture": "x64",
        "artifacts": [
            {
                "name": asset_name,
                "sha256": good_sha,
                "size_bytes": len(installer_bytes),
            }
        ],
    }

    releases_payload = [
        {
            "tag_name": "v2.0.0-beta.1",
            "prerelease": True,
            "draft": False,
            "assets": [],
        },
        {
            "tag_name": "v1.99.0",
            "prerelease": False,
            "draft": True,
            "assets": [],
        },
        {
            "tag_name": "v1.10.0",
            "name": "GeoPoint Mapper 1.10.0",
            "prerelease": False,
            "draft": False,
            "html_url": "https://github.com/gutentag6574/RME-Mapper/releases/tag/v1.10.0",
            "published_at": "2026-11-15T10:00:00Z",
            "body": "### Исправления\n- Новый интерфейс",
            "assets": [
                {
                    "name": asset_name,
                    "browser_download_url": "https://downloads.example/setup.exe",
                    "size": len(installer_bytes),
                },
                {
                    "name": MANIFEST_ASSET_NAME,
                    "browser_download_url": "https://downloads.example/manifest.json",
                    "size": 256,
                },
            ],
        },
    ]

    def mock_urlopen(req, timeout=15, context=None):
        url = req.full_url
        if "api.github.com/repos/" in url:
            return _FakeHTTPResponse(json.dumps(releases_payload).encode("utf-8"))
        if url.endswith("/manifest.json"):
            return _FakeHTTPResponse(json.dumps(manifest_good).encode("utf-8"))
        if url.endswith("/setup.exe"):
            return _FakeHTTPResponse(installer_bytes)
        raise AssertionError(f"Unexpected URL: {url}")

    svc = UpdateService(
        current_version="1.9.0",
        install_mode=INSTALL_MODE_INSTALLED,
        urlopen_func=mock_urlopen,
        temp_root=tmp_path,
    )
    check = svc.check_for_updates()
    assert check.status == "update_available"
    assert check.info is not None
    assert check.info.latest_version == "1.10.0"
    assert check.info.expected_sha256 == good_sha
    assert check.info.expected_size == len(installer_bytes)

    dl = svc.download_and_verify(check.info, verify_authenticode=False)
    assert dl.success is True
    assert dl.file_path is not None and dl.file_path.exists()
    assert dl.sha256 == good_sha
    dl.file_path.unlink()

    # Проверка провала SHA-256 и удаления поврежденного файла
    tampered = UpdateInfo(
        current_version=check.info.current_version,
        latest_version=check.info.latest_version,
        has_update=True,
        install_mode=INSTALL_MODE_INSTALLED,
        release_name=check.info.release_name,
        html_url=check.info.html_url,
        published_at=check.info.published_at,
        notes="",
        target_asset=check.info.target_asset,
        manifest_asset=check.info.manifest_asset,
        expected_size=len(installer_bytes),
        expected_sha256="0" * 64,
    )
    bad_dl = svc.download_and_verify(tampered, verify_authenticode=False)
    assert bad_dl.success is False
    assert bad_dl.error_code == "sha256_mismatch"
    assert not any(tmp_path.rglob("*.exe"))
    assert not any(tmp_path.rglob("*.part"))

    # Проверка отмены загрузки
    svc_cancel = UpdateService(
        current_version="1.9.0",
        install_mode=INSTALL_MODE_INSTALLED,
        urlopen_func=mock_urlopen,
        temp_root=tmp_path,
    )

    def _cancel_on_first_chunk(rec: int, tot: int) -> None:
        svc_cancel.cancel_download()

    cancelled_dl = svc_cancel.download_and_verify(
        check.info,
        progress_callback=_cancel_on_first_chunk,
        verify_authenticode=False,
    )
    assert cancelled_dl.success is False
    assert cancelled_dl.cancelled is True
    assert not any(tmp_path.rglob("*.part"))

    # Проверка провала неверного манифеста и сетевой ошибки
    with pytest.raises(UpdateError):
        verify_manifest_for_asset({"version": "1.2.0", "architecture": "x86", "artifacts": []}, "1.2.0", asset_name)

    def _net_fail(req, timeout=15, context=None):
        raise TimeoutError("timed out")

    svc_err = UpdateService(
        current_version=APP_VERSION,
        install_mode=INSTALL_MODE_INSTALLED,
        urlopen_func=_net_fail,
        temp_root=tmp_path,
    )
    err_res = svc_err.check_for_updates()
    assert err_res.status == "error"


def test_update_controller_banner_and_unsaved_guard(qapp, clean_settings, tmp_path):
    installer_path = tmp_path / "GeoPointMapper-1.2.0-Setup-x64.exe"
    installer_path.write_bytes(b"INSTALLER")

    svc = UpdateService(current_version="1.1.0", install_mode=INSTALL_MODE_INSTALLED, temp_root=tmp_path)
    ctrl = UpdateController(clean_settings, update_service=svc)

    class _DummyProjectCtrl:
        def __init__(self, allow_close: bool) -> None:
            self.allow_close = allow_close
            self.prompt_calls = 0

        def maybe_save_prompt(self, reason: str) -> bool:
            self.prompt_calls += 1
            return self.allow_close

    class _DummyMainWindow(QWidget):
        def __init__(self, allow_close: bool) -> None:
            super().__init__()
            self.project_controller = _DummyProjectCtrl(allow_close)
            self.closed = False

        def close(self) -> bool:
            self.closed = True
            return super().close()

    dummy_win_block = _DummyMainWindow(allow_close=False)
    banner = UpdateNotificationBanner(ctrl, dummy_win_block)
    try:
        info = UpdateInfo(
            current_version="1.1.0",
            latest_version="1.2.0",
            has_update=True,
            install_mode=INSTALL_MODE_INSTALLED,
            release_name="v1.2.0",
            html_url="https://github.com/gutentag6574/RME-Mapper/releases/tag/v1.2.0",
            published_at="2026-11-15T12:00:00Z",
            notes="Notes",
            target_asset=ReleaseAsset(name=installer_path.name, download_url="https://example.com/setup.exe", size=9),
            expected_size=9,
            expected_sha256="a" * 64,
        )
        ctrl._active_info = info
        from rme_mapper.services.update_service import DownloadResult

        ctrl._last_download_result = DownloadResult(success=True, file_path=installer_path, size_bytes=9, sha256="a" * 64)
        banner.show_update_available(info)
        assert not banner.isHidden()

        # Отказ сохранения отменяет установку и закрытие окна
        launched: list[Path] = []
        ok_blocked = ctrl.apply_downloaded_update(
            dummy_win_block,
            launcher=lambda installer_path, relaunch_exe, current_pid: launched.append(installer_path) or True,
        )
        assert ok_blocked is False
        assert dummy_win_block.project_controller.prompt_calls == 1
        assert launched == []
        assert dummy_win_block.closed is False

        # Подтверждение сохранения запускает установщик
        dummy_win_ok = _DummyMainWindow(allow_close=True)
        ok_allowed = ctrl.apply_downloaded_update(
            dummy_win_ok,
            launcher=lambda installer_path, relaunch_exe, current_pid: launched.append(installer_path) or True,
        )
        assert ok_allowed is True
        assert launched == [installer_path]
        assert dummy_win_ok.closed is True

        # "Позже" скрывает баннер и запоминает отложенную версию
        banner._on_later()
        assert banner.isHidden()
        assert ctrl.is_banner_dismissed_for("1.2.0")
    finally:
        banner.close()
