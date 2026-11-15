"""Единое диалоговое окно настроек GeoPoint Mapper с боковой навигацией."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QColor, QDesktopServices
from PySide6.QtWidgets import (
    QCheckBox,
    QColorDialog,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from rme_mapper.app_info import APP_NAME, APP_VERSION
from rme_mapper.i18n import tr
from rme_mapper.services.license_service import LicenseCheckResult, LicenseService
from rme_mapper.services.tile_cache import TileDiskCache
from rme_mapper.services.update_service import (
    INSTALL_MODE_INSTALLED,
    INSTALL_MODE_PORTABLE,
    INSTALL_MODE_SOURCE,
    RELEASES_HTML_URL,
    DownloadResult,
    UpdateCheckResult,
    detect_install_mode,
    format_size_human,
)
from rme_mapper.ui.update_controller import (
    ReleaseNotesDialog,
    format_utc_local_display,
    install_mode_display_name,
)


def _scroll_wrap(widget: QWidget, parent: QWidget | None = None) -> QScrollArea:
    widget.setObjectName("settingsPage")
    scroll = QScrollArea(parent)
    scroll.setObjectName("settingsScroll")
    scroll.setWidgetResizable(True)
    scroll.setFrameShape(QFrame.Shape.NoFrame)
    if scroll.viewport() is not None:
        scroll.viewport().setObjectName("settingsScrollViewport")
    scroll.setWidget(widget)
    return scroll


class SettingsDialog(QDialog):
    """Единый 7-раздельный диалог настроек с двусторонней синхронизацией."""

    SECTION_KEYS = (
        "general",
        "interface",
        "map_coords",
        "network_cache",
        "updates",
        "license",
        "help_about",
    )

    def __init__(
        self,
        settings: Any,
        parent: Any = None,
        initial_section: str = "general",
    ) -> None:
        super().__init__(parent)
        self.s = settings
        self._parent_window = parent
        self.setWindowTitle(tr("menu.settings"))
        self.resize(780, 560)
        self.setMinimumSize(640, 440)

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(12)

        body = QHBoxLayout()
        body.setSpacing(14)

        self.nav_list = QListWidget(self)
        self.nav_list.setObjectName("settingsNavList")
        self.nav_list.setFixedWidth(205)
        self.stack = QStackedWidget(self)

        section_titles = [
            tr("settings.section.general"),
            tr("settings.section.interface"),
            tr("settings.section.map_coords"),
            tr("settings.section.network_cache"),
            tr("settings.section.updates"),
            tr("settings.section.license"),
            tr("settings.section.help_about"),
        ]
        for key, title in zip(self.SECTION_KEYS, section_titles):
            item = QListWidgetItem(title)
            item.setData(Qt.ItemDataRole.UserRole, key)
            self.nav_list.addItem(item)

        body.addWidget(self.nav_list)
        body.addWidget(self.stack, 1)
        root.addLayout(body, 1)

        self._build_general_page()
        self._build_interface_page()
        self._build_map_coords_page()
        self._build_network_cache_page()
        self._build_updates_page()
        self._build_license_page()
        self._build_help_about_page()

        self.nav_list.currentRowChanged.connect(self.stack.setCurrentIndex)
        self.select_section(initial_section)

        self.button_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Apply
            | QDialogButtonBox.StandardButton.Cancel,
            self,
        )
        self.button_box.accepted.connect(self.accept)
        self.button_box.rejected.connect(self.reject)
        ok_btn = self.button_box.button(QDialogButtonBox.StandardButton.Ok)
        if ok_btn is not None:
            ok_btn.setText(tr("common.ok"))
        cancel_btn = self.button_box.button(QDialogButtonBox.StandardButton.Cancel)
        if cancel_btn is not None:
            cancel_btn.setText(tr("common.cancel"))
        apply_btn = self.button_box.button(QDialogButtonBox.StandardButton.Apply)
        if apply_btn is not None:
            apply_btn.setText(tr("common.apply"))
            apply_btn.clicked.connect(self._on_apply_clicked)
        root.addWidget(self.button_box)

        self._bind_update_signals()
        self._refresh_update_ui()

    def select_section(self, section_key: str) -> None:
        """Перейти к указанному разделу настроек."""
        try:
            idx = self.SECTION_KEYS.index(section_key)
        except ValueError:
            idx = 0
        self.nav_list.setCurrentRow(idx)
        self.stack.setCurrentIndex(idx)

    # ------------------------------------------------------------------
    # 1. Общие
    # ------------------------------------------------------------------
    def _build_general_page(self) -> None:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(4, 4, 12, 4)
        layout.setSpacing(12)

        grp_main = QGroupBox(tr("settings.section.general"), page)
        form = QFormLayout(grp_main)
        form.setSpacing(10)

        self.language = QComboBox(grp_main)
        self.language.addItem("Русский (RU)", "ru")
        self.language.addItem("English (EN)", "en")
        cur_lang = self.s.get_language() if hasattr(self.s, "get_language") else self.s._get_str("ui/language", "ru")
        self.language.setCurrentIndex(max(0, self.language.findData(cur_lang)))
        form.addRow(tr("menu.language"), self.language)

        self.startup_behavior = QComboBox(grp_main)
        self.startup_behavior.addItem(tr("settings.startup_empty"), "empty")
        self.startup_behavior.addItem(tr("settings.startup_restore_last"), "restore_last_project")
        cur_startup = (
            self.s.get_startup_behavior("empty")
            if hasattr(self.s, "get_startup_behavior")
            else self.s._get_str("general/startup_behavior", "empty")
        )
        self.startup_behavior.setCurrentIndex(max(0, self.startup_behavior.findData(cur_startup)))
        form.addRow(tr("settings.startup_behavior"), self.startup_behavior)
        layout.addWidget(grp_main)

        grp_rec = QGroupBox(tr("audit.recovery"), page)
        rec_form = QFormLayout(grp_rec)
        rec_form.setSpacing(10)

        self.recovery = QCheckBox(tr("audit.recovery"), grp_rec)
        self.recovery.setChecked(self.s._get_bool("recovery/enabled", True))
        rec_form.addRow(self.recovery)

        self.interval = QSpinBox(grp_rec)
        self.interval.setRange(1, 300)
        self.interval.setValue(self.s.get_integer("recovery/seconds", 3, 1, 300))
        rec_form.addRow(tr("audit.recovery_seconds"), self.interval)
        layout.addWidget(grp_rec)

        layout.addStretch(1)
        self.stack.addWidget(_scroll_wrap(page, self))

    # ------------------------------------------------------------------
    # 2. Интерфейс
    # ------------------------------------------------------------------
    def _build_interface_page(self) -> None:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(4, 4, 12, 4)
        layout.setSpacing(12)

        grp_theme = QGroupBox(tr("settings.group.appearance"), page)
        form = QFormLayout(grp_theme)
        form.setSpacing(10)

        self.theme = QComboBox(grp_theme)
        self.theme.addItem(tr("ux.theme_light"), "light")
        self.theme.addItem(tr("ux.theme_dark"), "dark")
        self.theme.addItem(tr("ux.theme_system"), "system")
        cur_theme = self.s._get_str("ui/theme", "light")
        self.theme.setCurrentIndex(max(0, self.theme.findData(cur_theme)))
        form.addRow(tr("ux.theme"), self.theme)
        layout.addWidget(grp_theme)

        grp_panels = QGroupBox(tr("settings.group.panels"), page)
        panels_layout = QVBoxLayout(grp_panels)
        panels_layout.setSpacing(8)

        w = self._parent_window
        self.show_toolbar = QCheckBox(tr("action.view_toolbar"), grp_panels)
        tb_vis = w.toggle_toolbar_action.isChecked() if w is not None and hasattr(w, "toggle_toolbar_action") else self.s.get_toolbar_visible()
        self.show_toolbar.setChecked(bool(tb_vis))
        panels_layout.addWidget(self.show_toolbar)

        self.show_left_panel = QCheckBox(tr("action.view_layers_points"), grp_panels)
        lp_vis = w.toggle_layers_points_action.isChecked() if w is not None and hasattr(w, "toggle_layers_points_action") else self.s.get_left_panel_visible()
        self.show_left_panel.setChecked(bool(lp_vis))
        panels_layout.addWidget(self.show_left_panel)

        self.show_right_panel = QCheckBox(tr("action.view_properties"), grp_panels)
        rp_vis = w.toggle_properties_action.isChecked() if w is not None and hasattr(w, "toggle_properties_action") else self.s.get_right_panel_visible()
        self.show_right_panel.setChecked(bool(rp_vis))
        panels_layout.addWidget(self.show_right_panel)

        self.show_statusbar = QCheckBox(tr("action.view_statusbar"), grp_panels)
        sb_vis = w.toggle_statusbar_action.isChecked() if w is not None and hasattr(w, "toggle_statusbar_action") else self.s.get_statusbar_visible()
        self.show_statusbar.setChecked(bool(sb_vis))
        panels_layout.addWidget(self.show_statusbar)

        self.points_bottom = QCheckBox(tr("ux.bottom_points"), grp_panels)
        pb_val = w.bottom_points_action.isChecked() if w is not None and hasattr(w, "bottom_points_action") else self.s._get_bool("ui/points_bottom", True)
        self.points_bottom.setChecked(bool(pb_val))
        panels_layout.addWidget(self.points_bottom)

        self.auto_properties = QCheckBox(tr("ux.auto_properties"), grp_panels)
        ap_val = w.auto_properties_action.isChecked() if w is not None and hasattr(w, "auto_properties_action") else self.s._get_bool("ui/auto_properties", True)
        self.auto_properties.setChecked(bool(ap_val))
        panels_layout.addWidget(self.auto_properties)

        layout.addWidget(grp_panels)
        layout.addStretch(1)
        self.stack.addWidget(_scroll_wrap(page, self))

    # ------------------------------------------------------------------
    # 3. Карта и координаты
    # ------------------------------------------------------------------
    def _build_map_coords_page(self) -> None:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(4, 4, 12, 4)
        layout.setSpacing(12)

        w = self._parent_window

        grp_layers = QGroupBox(tr("settings.group.map_layers"), page)
        layers_form = QFormLayout(grp_layers)
        layers_form.setSpacing(8)

        self.show_grid = QCheckBox(tr("settings.show_grid"), grp_layers)
        grid_val = w.toggle_grid_action.isChecked() if w is not None and hasattr(w, "toggle_grid_action") else self.s.get_show_coordinate_grid()
        self.show_grid.setChecked(bool(grid_val))
        layers_form.addRow(self.show_grid)

        self.show_scale = QCheckBox(tr("settings.show_scale"), grp_layers)
        scale_val = w.toggle_scale_action.isChecked() if w is not None and hasattr(w, "toggle_scale_action") else self.s.get_show_scale_indicator()
        self.show_scale.setChecked(bool(scale_val))
        layers_form.addRow(self.show_scale)

        self.show_points = QCheckBox(tr("settings.show_points"), grp_layers)
        pts_val = w.show_points_action.isChecked() if w is not None and hasattr(w, "show_points_action") else self.s.get_show_points_visible()
        self.show_points.setChecked(bool(pts_val))
        layers_form.addRow(self.show_points)

        self.show_zones = QCheckBox(tr("settings.show_zones"), grp_layers)
        zones_val = w.show_zones_action.isChecked() if w is not None and hasattr(w, "show_zones_action") else self.s.get_show_zones_visible()
        self.show_zones.setChecked(bool(zones_val))
        layers_form.addRow(self.show_zones)

        self.labels_mode = QComboBox(grp_layers)
        self.labels_mode.addItem(tr("action.labels_hidden"), "hidden")
        self.labels_mode.addItem(tr("action.labels_selected"), "selected")
        self.labels_mode.addItem(tr("action.labels_all"), "all")
        cur_lbl_mode = self.s.get_point_labels_mode() if hasattr(self.s, "get_point_labels_mode") else "selected"
        self.labels_mode.setCurrentIndex(max(0, self.labels_mode.findData(cur_lbl_mode)))
        layers_form.addRow(tr("settings.point_labels_mode"), self.labels_mode)

        self.label_content = QComboBox(grp_layers)
        self.label_content.addItem(tr("label_content.name"), "name")
        self.label_content.addItem(tr("label_content.number"), "number")
        self.label_content.addItem(tr("label_content.number_name"), "number_name")
        cur_lbl_content = self.s.get_point_label_content() if hasattr(self.s, "get_point_label_content") else "number_name"
        self.label_content.setCurrentIndex(max(0, self.label_content.findData(cur_lbl_content)))
        layers_form.addRow(tr("settings.point_labels_content"), self.label_content)

        layout.addWidget(grp_layers)

        grp_pts = QGroupBox(tr("settings.group.point_defaults"), page)
        points = QFormLayout(grp_pts)
        points.setSpacing(8)
        defaults = self.s.get_point_defaults() if hasattr(self.s, "get_point_defaults") else {}

        self.shape = QComboBox(grp_pts)
        for name in ("circle", "square", "triangle"):
            self.shape.addItem(tr(f"shape.{name}"), name)
        self.shape.setCurrentIndex(max(0, self.shape.findData(defaults.get("symbol", "circle"))))
        points.addRow(tr("audit.shape"), self.shape)

        self.size = QDoubleSpinBox(grp_pts)
        self.size.setRange(2, 64)
        self.size.setValue(float(defaults.get("size", 12)))
        points.addRow(tr("audit.marker_size"), self.size)

        color_row = QHBoxLayout()
        self.color = QLineEdit(defaults.get("color", "#dc1e1e"), grp_pts)
        color_row.addWidget(self.color, 1)
        pick = QPushButton(tr("audit.choose_color"), grp_pts)
        pick.clicked.connect(self.pick_color)
        color_row.addWidget(pick)
        points.addRow(tr("audit.marker_color"), color_row)

        self.zone = QCheckBox(tr("audit.zone_enabled"), grp_pts)
        self.zone.setChecked(bool(defaults.get("zone_enabled", False)))
        points.addRow(self.zone)

        self.radius = QDoubleSpinBox(grp_pts)
        self.radius.setRange(0.1, 10000000)
        self.radius.setValue(float(defaults.get("radius_m", 100)))
        points.addRow(tr("audit.radius_m"), self.radius)
        layout.addWidget(grp_pts)

        grp_coords = QGroupBox(tr("settings.group.coordinates"), page)
        coords = QFormLayout(grp_coords)
        coords.setSpacing(8)

        self.format = QComboBox(grp_coords)
        for name in ("DD", "DMS", "DMM"):
            self.format.addItem(name, name)
        self.format.setCurrentIndex(max(0, self.format.findData(self.s._get_str("coordinates/format", "DD"))))
        coords.addRow(tr("audit.coordinate_format"), self.format)

        self.precision = QSpinBox(grp_coords)
        self.precision.setRange(0, 10)
        self.precision.setValue(self.s.get_integer("coordinates/precision", 6, 0, 10))
        coords.addRow(tr("audit.precision"), self.precision)

        self.separator = QComboBox(grp_coords)
        for name, value in ((tr("sep.comma_space"), ", "), (tr("sep.semicolon"), "; "), (tr("sep.space"), " ")):
            self.separator.addItem(name, value)
        self.separator.setCurrentIndex(max(0, self.separator.findData(self.s._get_str("coordinates/separator", ", "))))
        coords.addRow(tr("audit.separator"), self.separator)

        self.distance_unit = QComboBox(grp_coords)
        self.distance_unit.addItem(tr("settings.unit_auto"), "auto")
        self.distance_unit.addItem(tr("settings.unit_m"), "m")
        self.distance_unit.addItem(tr("settings.unit_km"), "km")
        cur_unit = self.s.get_distance_unit("auto") if hasattr(self.s, "get_distance_unit") else "auto"
        self.distance_unit.setCurrentIndex(max(0, self.distance_unit.findData(cur_unit)))
        coords.addRow(tr("settings.distance_unit"), self.distance_unit)

        layout.addWidget(grp_coords)
        layout.addStretch(1)
        self.stack.addWidget(_scroll_wrap(page, self))

    # ------------------------------------------------------------------
    # 4. Интернет и кэш
    # ------------------------------------------------------------------
    def _build_network_cache_page(self) -> None:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(4, 4, 12, 4)
        layout.setSpacing(12)

        grp_net = QGroupBox(tr("settings.section.network_cache"), page)
        form = QFormLayout(grp_net)
        form.setSpacing(10)

        self.cache = QSpinBox(grp_net)
        self.cache.setRange(16, 10240)
        self.cache.setValue(self.s.get_online_cache_max_mb())
        form.addRow(tr("audit.cache_mb"), self.cache)

        self.network_timeout = QSpinBox(grp_net)
        self.network_timeout.setRange(5, 120)
        cur_timeout = self.s.get_network_timeout_sec(15) if hasattr(self.s, "get_network_timeout_sec") else 15
        self.network_timeout.setValue(cur_timeout)
        form.addRow(tr("settings.network_timeout"), self.network_timeout)

        self.antialias = QCheckBox(tr("audit.antialias"), grp_net)
        self.antialias.setChecked(self.s._get_bool("map/antialias", True))
        form.addRow(self.antialias)

        self.cache_usage_label = QLabel("", grp_net)
        self._refresh_cache_usage_label()
        form.addRow(self.cache_usage_label)

        actions_row = QHBoxLayout()
        actions_row.setSpacing(8)
        self.btn_clear_cache = QPushButton(tr("action.clear_tile_cache"), grp_net)
        self.btn_clear_cache.clicked.connect(self._on_clear_cache_clicked)
        actions_row.addWidget(self.btn_clear_cache)

        self.btn_online_basemaps = QPushButton(tr("settings.online_basemaps_btn"), grp_net)
        self.btn_online_basemaps.clicked.connect(self._on_open_online_basemaps)
        if self._parent_window is None or not hasattr(self._parent_window, "open_online_basemap_dialog"):
            self.btn_online_basemaps.setEnabled(False)
        actions_row.addWidget(self.btn_online_basemaps)
        actions_row.addStretch(1)
        form.addRow(actions_row)

        layout.addWidget(grp_net)
        layout.addStretch(1)
        self.stack.addWidget(_scroll_wrap(page, self))

    def _refresh_cache_usage_label(self) -> None:
        try:
            cache_dir = TileDiskCache.get_default_cache_dir()
            size_bytes = TileDiskCache(cache_dir=cache_dir).get_cache_size_bytes()
            formatted = TileDiskCache.format_size(size_bytes)
        except Exception:
            formatted = "0 B"
        self.cache_usage_label.setText(tr("settings.cache_usage", size=formatted))

    def _on_clear_cache_clicked(self) -> None:
        if self._parent_window is not None and hasattr(self._parent_window, "clear_online_tile_cache"):
            self._parent_window.clear_online_tile_cache()
        else:
            TileDiskCache(cache_dir=TileDiskCache.get_default_cache_dir()).clear_cache()
        self._refresh_cache_usage_label()

    def _on_open_online_basemaps(self) -> None:
        if self._parent_window is not None and hasattr(self._parent_window, "open_online_basemap_dialog"):
            self._parent_window.open_online_basemap_dialog()

    # ------------------------------------------------------------------
    # 5. Обновления
    # ------------------------------------------------------------------
    def _build_updates_page(self) -> None:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(4, 4, 12, 4)
        layout.setSpacing(12)

        grp = QGroupBox(tr("settings.section.updates"), page)
        v = QVBoxLayout(grp)
        v.setSpacing(10)

        self.lbl_installed_version = QLabel(tr("updates.installed_version", version=APP_VERSION), grp)
        self.lbl_installed_version.setStyleSheet("font-weight: 600;")
        v.addWidget(self.lbl_installed_version)

        uc = getattr(self._parent_window, "update_controller", None)
        mode = uc.service.get_install_mode() if uc is not None else detect_install_mode()
        self.lbl_install_mode = QLabel(
            tr("updates.install_mode_label", mode=install_mode_display_name(mode)), grp
        )
        v.addWidget(self.lbl_install_mode)

        last_utc = self.s.get_last_update_success_utc() if hasattr(self.s, "get_last_update_success_utc") else ""
        self.lbl_last_check = QLabel(
            tr("updates.last_check_label", when=format_utc_local_display(last_utc)), grp
        )
        v.addWidget(self.lbl_last_check)

        self.auto_check_updates = QCheckBox(tr("updates.auto_check"), grp)
        auto_chk = self.s.get_auto_check_updates(True) if hasattr(self.s, "get_auto_check_updates") else True
        self.auto_check_updates.setChecked(bool(auto_chk))
        v.addWidget(self.auto_check_updates)

        self.lbl_update_status = QLabel("", grp)
        self.lbl_update_status.setWordWrap(True)
        v.addWidget(self.lbl_update_status)

        self.update_progress_bar = QProgressBar(grp)
        self.update_progress_bar.setVisible(False)
        v.addWidget(self.update_progress_bar)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)
        self.btn_check_updates = QPushButton(tr("updates.check_now"), grp)
        self.btn_check_updates.setObjectName("primaryAccentBtn")
        self.btn_check_updates.clicked.connect(self._on_check_updates_clicked)
        btn_row.addWidget(self.btn_check_updates)

        self.btn_update_action = QPushButton(tr("updates.btn_update"), grp)
        self.btn_update_action.setVisible(False)
        self.btn_update_action.clicked.connect(self._on_update_action_clicked)
        btn_row.addWidget(self.btn_update_action)

        self.btn_cancel_download = QPushButton(tr("updates.btn_cancel"), grp)
        self.btn_cancel_download.setVisible(False)
        self.btn_cancel_download.clicked.connect(self._on_cancel_download_clicked)
        btn_row.addWidget(self.btn_cancel_download)

        self.btn_release_notes = QPushButton(tr("updates.btn_release_notes"), grp)
        self.btn_release_notes.setVisible(False)
        self.btn_release_notes.clicked.connect(self._on_release_notes_clicked)
        btn_row.addWidget(self.btn_release_notes)

        btn_row.addStretch(1)
        v.addLayout(btn_row)

        layout.addWidget(grp)
        layout.addStretch(1)
        self.stack.addWidget(_scroll_wrap(page, self))

    def _bind_update_signals(self) -> None:
        uc = getattr(self._parent_window, "update_controller", None)
        if uc is None:
            return
        uc.state_changed.connect(self._refresh_update_ui)
        uc.download_progress.connect(self._on_update_download_progress)
        uc.check_finished.connect(self._on_update_check_finished_in_dialog)

    def _on_check_updates_clicked(self) -> None:
        uc = getattr(self._parent_window, "update_controller", None)
        if uc is not None:
            uc.start_check(manual=True)
            self._refresh_update_ui()

    def _on_update_action_clicked(self) -> None:
        uc = getattr(self._parent_window, "update_controller", None)
        if uc is None or uc.active_info is None:
            return
        dl = uc.last_download_result
        if dl is not None and dl.success:
            if uc.active_info.install_mode == INSTALL_MODE_INSTALLED:
                self.accept()
            uc.apply_downloaded_update(self._parent_window)
            return
        if uc.active_info.install_mode not in (INSTALL_MODE_INSTALLED, INSTALL_MODE_PORTABLE):
            QDesktopServices.openUrl(QUrl(uc.active_info.html_url or RELEASES_HTML_URL))
            return
        uc.start_download(uc.active_info)

    def _on_cancel_download_clicked(self) -> None:
        uc = getattr(self._parent_window, "update_controller", None)
        if uc is not None:
            uc.cancel_download()

    def _on_release_notes_clicked(self) -> None:
        uc = getattr(self._parent_window, "update_controller", None)
        if uc is not None and uc.active_info is not None:
            ReleaseNotesDialog(uc.active_info, self).exec()

    def _on_update_download_progress(self, received: int, total: int) -> None:
        if total > 0:
            pct = max(0, min(100, int((received * 100) / total)))
            self.update_progress_bar.setRange(0, 100)
            self.update_progress_bar.setValue(pct)
            self.lbl_update_status.setText(
                tr("updates.downloading", percent=pct, received=format_size_human(received), total=format_size_human(total))
            )
        else:
            self.update_progress_bar.setRange(0, 0)

    def _on_update_check_finished_in_dialog(self, result: UpdateCheckResult, manual: bool) -> None:
        self._refresh_update_ui()
        if manual and result.status == "error" and self.isVisible():
            box = QMessageBox(self)
            box.setIcon(QMessageBox.Icon.Warning)
            box.setWindowTitle(tr("updates.retry_dialog_title"))
            box.setText(tr("updates.error_prefix", message=result.error_message))
            retry_btn = box.addButton(tr("updates.btn_retry"), QMessageBox.ButtonRole.AcceptRole)
            box.addButton(QMessageBox.StandardButton.Close)
            box.exec()
            if box.clickedButton() == retry_btn:
                self._on_check_updates_clicked()

    def _refresh_update_ui(self) -> None:
        if not hasattr(self, "lbl_update_status"):
            return
        last_utc = self.s.get_last_update_success_utc() if hasattr(self.s, "get_last_update_success_utc") else ""
        self.lbl_last_check.setText(tr("updates.last_check_label", when=format_utc_local_display(last_utc)))

        uc = getattr(self._parent_window, "update_controller", None)
        if uc is None:
            self.btn_check_updates.setEnabled(False)
            return

        if uc.is_downloading:
            self.btn_check_updates.setEnabled(False)
            self.btn_update_action.setVisible(False)
            self.btn_cancel_download.setVisible(True)
            self.update_progress_bar.setVisible(True)
            return

        self.update_progress_bar.setVisible(False)
        self.btn_cancel_download.setVisible(False)
        self.btn_check_updates.setEnabled(not uc.is_checking)

        if uc.is_checking:
            self.lbl_update_status.setText(tr("updates.checking"))
            self.btn_update_action.setVisible(False)
            self.btn_release_notes.setVisible(False)
            return

        dl: DownloadResult | None = uc.last_download_result
        info = uc.active_info
        if dl is not None and info is not None:
            if dl.success and dl.file_path is not None:
                if info.install_mode == INSTALL_MODE_PORTABLE:
                    self.lbl_update_status.setText(
                        tr("updates.ready_portable", version=info.latest_version, path=str(dl.file_path))
                    )
                    self.btn_update_action.setText(tr("updates.btn_open_downloads"))
                else:
                    self.lbl_update_status.setText(tr("updates.ready_installer", version=info.latest_version))
                    self.btn_update_action.setText(tr("updates.btn_install_restart"))
                self.btn_update_action.setVisible(True)
                self.btn_release_notes.setVisible(True)
                return
            if dl.cancelled:
                self.lbl_update_status.setText(tr("updates.cancelled"))
                self.btn_update_action.setText(tr("updates.btn_update"))
                self.btn_update_action.setVisible(True)
                self.btn_release_notes.setVisible(True)
                return
            self.lbl_update_status.setText(tr("updates.error_prefix", message=dl.error_message))
            self.btn_update_action.setText(tr("updates.btn_retry"))
            self.btn_update_action.setVisible(True)
            self.btn_release_notes.setVisible(True)
            return

        res: UpdateCheckResult | None = uc.last_check_result
        if res is None:
            self.lbl_update_status.setText("")
            self.btn_update_action.setVisible(False)
            self.btn_release_notes.setVisible(False)
            return

        if res.status == "up_to_date":
            ver = res.info.current_version if res.info else APP_VERSION
            self.lbl_update_status.setText(tr("updates.up_to_date", version=ver))
            self.btn_update_action.setVisible(False)
            self.btn_release_notes.setVisible(False)
        elif res.status == "update_available" and res.info is not None:
            info = res.info
            if info.install_mode == INSTALL_MODE_SOURCE:
                self.lbl_update_status.setText(
                    tr("updates.available_source", latest=info.latest_version, current=info.current_version)
                )
                self.btn_update_action.setText("GitHub Releases")
            else:
                self.lbl_update_status.setText(
                    tr(
                        "updates.available_banner",
                        latest=info.latest_version,
                        current=info.current_version,
                        size=format_size_human(info.expected_size),
                    )
                )
                self.btn_update_action.setText(tr("updates.btn_update"))
            self.btn_update_action.setVisible(True)
            self.btn_release_notes.setVisible(True)
        else:
            self.lbl_update_status.setText(tr("updates.error_prefix", message=res.error_message))
            self.btn_update_action.setVisible(False)
            self.btn_release_notes.setVisible(False)

    # ------------------------------------------------------------------
    # 6. Лицензия
    # ------------------------------------------------------------------
    def _get_license_service_and_controller(self) -> tuple[LicenseService, Any | None]:
        w = self._parent_window
        ctrl = getattr(w, "license_controller", None) if w is not None else None
        if ctrl is not None and getattr(ctrl, "service", None) is not None:
            return ctrl.service, ctrl
        svc = getattr(w, "license_service", None) if w is not None else None
        if isinstance(svc, LicenseService):
            return svc, ctrl
        return LicenseService(), ctrl

    def _build_license_page(self) -> None:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(4, 4, 12, 4)
        layout.setSpacing(12)

        grp_status = QGroupBox(tr("license.settings.group_status"), page)
        form = QFormLayout(grp_status)
        form.setSpacing(8)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        self.lbl_license_status = QLabel("", grp_status)
        self.lbl_license_status.setObjectName("lblLicenseStatus")
        self.lbl_license_status.setWordWrap(True)
        self.lbl_license_status.setStyleSheet("font-weight: 700;")

        self.lbl_license_key_mask = QLabel("", grp_status)
        self.lbl_license_key_mask.setObjectName("lblLicenseKeyMask")
        self.lbl_license_key_mask.setWordWrap(False)
        self.lbl_license_key_mask.setMinimumWidth(280)
        self.lbl_license_key_mask.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.lbl_license_key_mask.setStyleSheet("font-family: Consolas, 'Cascadia Mono', monospace;")

        self.lbl_license_expires = QLabel("", grp_status)
        self.lbl_license_expires.setObjectName("lblLicenseExpires")
        self.lbl_license_expires.setWordWrap(True)

        self.lbl_license_last_verified = QLabel("", grp_status)
        self.lbl_license_last_verified.setObjectName("lblLicenseLastVerified")
        self.lbl_license_last_verified.setWordWrap(True)

        self.lbl_license_list_version = QLabel("", grp_status)
        self.lbl_license_list_version.setObjectName("lblLicenseListVersion")
        self.lbl_license_list_version.setWordWrap(True)

        form.addRow(tr("license.settings.status_label"), self.lbl_license_status)
        form.addRow(tr("license.settings.key_mask_label"), self.lbl_license_key_mask)
        form.addRow(tr("license.settings.license_expires_label"), self.lbl_license_expires)
        form.addRow(tr("license.settings.last_verified_label"), self.lbl_license_last_verified)
        form.addRow(tr("license.settings.list_version_label"), self.lbl_license_list_version)
        layout.addWidget(grp_status)

        grp_actions = QGroupBox(tr("license.settings.group_actions"), page)
        act_lay = QVBoxLayout(grp_actions)
        act_lay.setSpacing(10)

        hint = QLabel(tr("license.settings.hint"), grp_actions)
        hint.setWordWrap(True)
        act_lay.addWidget(hint)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)
        self.btn_license_recheck = QPushButton(tr("license.settings.btn_check_now"), grp_actions)
        self.btn_license_recheck.setObjectName("btnLicenseRecheck")
        self.btn_license_recheck.clicked.connect(self._on_license_recheck_clicked)
        btn_row.addWidget(self.btn_license_recheck)

        self.btn_license_deactivate = QPushButton(tr("license.settings.btn_deactivate"), grp_actions)
        self.btn_license_deactivate.setObjectName("btnLicenseDeactivate")
        self.btn_license_deactivate.clicked.connect(self._on_license_deactivate_clicked)
        btn_row.addWidget(self.btn_license_deactivate)
        btn_row.addStretch(1)
        act_lay.addLayout(btn_row)

        self.lbl_license_feedback = QLabel("", grp_actions)
        self.lbl_license_feedback.setObjectName("lblLicenseFeedback")
        self.lbl_license_feedback.setWordWrap(True)
        self.lbl_license_feedback.setVisible(False)
        act_lay.addWidget(self.lbl_license_feedback)

        layout.addWidget(grp_actions)
        layout.addStretch(1)
        self.stack.addWidget(_scroll_wrap(page, self))
        self._refresh_license_status_ui()

    def _refresh_license_status_ui(self, res: LicenseCheckResult | None = None) -> None:
        svc, ctrl = self._get_license_service_and_controller()
        if res is None:
            local_res = svc.get_status_snapshot()
            ctrl_res = getattr(ctrl, "latest_result", None) if ctrl is not None else None
            if ctrl_res is not None and ctrl_res.authorized == local_res.authorized:
                res = ctrl_res
            else:
                res = local_res

        hours_left = max(1, res.offline_remaining_seconds // 3600) if res.offline_remaining_seconds > 0 else 0
        if res.status == "active":
            status_text = tr("license.settings.status_active")
        elif res.status == "active_offline":
            status_text = tr("license.settings.status_offline_hours", hours=hours_left)
        elif res.status == "revoked":
            status_text = tr("license.settings.status_revoked")
        elif res.status in ("expired", "offline_expired"):
            status_text = tr("license.settings.status_expired")
        elif res.status == "unactivated":
            status_text = tr("license.settings.status_unlicensed")
        else:
            status_text = tr("license.settings.status_active") if res.authorized else (res.message or res.status)
        self.lbl_license_status.setText(status_text)

        dash = tr("license.settings.not_available")
        self.lbl_license_key_mask.setText(res.key_mask or dash)
        self.lbl_license_expires.setText(
            format_utc_local_display(res.license_expires_at)
            if res.license_expires_at
            else (tr("license.settings.no_expiry") if res.authorized else dash)
        )
        self.lbl_license_last_verified.setText(
            format_utc_local_display(res.last_verified_at) if res.last_verified_at else dash
        )
        self.lbl_license_list_version.setText(f"v{res.list_version}" if res.list_version > 0 else dash)
        self.btn_license_deactivate.setEnabled(bool(res.key_mask or res.authorized))

    def _on_license_recheck_clicked(self) -> None:
        svc, ctrl = self._get_license_service_and_controller()
        self.btn_license_recheck.setEnabled(False)
        try:
            res = ctrl.check_now_sync() if ctrl is not None else svc.verify_online()
            self._refresh_license_status_ui(res)
            if res.authorized and res.online_checked:
                self.lbl_license_feedback.setText(
                    tr("license.settings.recheck_ok", version=res.list_version)
                )
            else:
                self.lbl_license_feedback.setText(res.message or tr("license.settings.offline_warning", message=""))
            self.lbl_license_feedback.setVisible(True)
        finally:
            self.btn_license_recheck.setEnabled(True)

    def _on_license_deactivate_clicked(self) -> None:
        svc, ctrl = self._get_license_service_and_controller()
        if ctrl is not None:
            ctrl.reset_activation_flow(parent=self)
            self._refresh_license_status_ui()
            return

        answer = QMessageBox.question(
            self,
            tr("license.reset_confirm_title"),
            tr("license.reset_confirm_body"),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        svc.reset_activation()
        self._refresh_license_status_ui(svc.get_status_snapshot())
        self.lbl_license_feedback.setText(tr("license.reset_done_msg"))
        self.lbl_license_feedback.setVisible(True)

    # ------------------------------------------------------------------
    # 7. Справка и о программе
    # ------------------------------------------------------------------
    def _build_help_about_page(self) -> None:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(4, 4, 12, 4)
        layout.setSpacing(12)

        grp_docs = QGroupBox(tr("settings.group.documentation"), page)
        docs_layout = QVBoxLayout(grp_docs)
        docs_layout.setSpacing(8)

        summary_lbl = QLabel(f"{APP_NAME} — {APP_VERSION}", grp_docs)
        summary_lbl.setStyleSheet("font-weight: 700; font-size: 14px;")
        docs_layout.addWidget(summary_lbl)

        btns_row = QHBoxLayout()
        btns_row.setSpacing(8)

        self.btn_quick_start = QPushButton(tr("action.quick_start"), grp_docs)
        self.btn_quick_start.clicked.connect(self._on_quick_start_clicked)
        btns_row.addWidget(self.btn_quick_start)

        self.btn_about = QPushButton(tr("action.about"), grp_docs)
        self.btn_about.clicked.connect(self._on_about_clicked)
        btns_row.addWidget(self.btn_about)

        self.btn_open_docs = QPushButton(tr("settings.open_docs_folder"), grp_docs)
        self.btn_open_docs.clicked.connect(self._on_open_docs_clicked)
        btns_row.addWidget(self.btn_open_docs)
        btns_row.addStretch(1)
        docs_layout.addLayout(btns_row)
        layout.addWidget(grp_docs)

        grp_keys = QGroupBox(tr("settings.group.shortcuts"), page)
        keys_layout = QVBoxLayout(grp_keys)

        shortcuts_data = [
            (tr("action.new_project"), "Ctrl+N"),
            (tr("action.open_project"), "Ctrl+O"),
            (tr("action.save"), "Ctrl+S"),
            (tr("action.save_as"), "Ctrl+Shift+S"),
            (tr("action.open_map"), "Ctrl+M"),
            (tr("action.undo"), "Ctrl+Z"),
            (tr("action.redo"), "Ctrl+Y"),
            (tr("action.add_point"), "Ctrl+P"),
            (tr("action.fit_map"), "Ctrl+0"),
            (tr("action.focus_map"), "F11"),
            (tr("action.measure_distance"), "Ctrl+Shift+M"),
            (tr("action.measure_area"), "Ctrl+Shift+G"),
            (tr("action.export_map_image"), "Ctrl+Shift+E"),
            (tr("audit.preferences"), "Ctrl+,"),
        ]
        table = QTableWidget(len(shortcuts_data), 2, grp_keys)
        table.setHorizontalHeaderLabels(
            [tr("settings.shortcuts_col_action"), tr("settings.shortcuts_col_key")]
        )
        table.verticalHeader().setVisible(False)
        table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        for row_idx, (act_name, key_seq) in enumerate(shortcuts_data):
            table.setItem(row_idx, 0, QTableWidgetItem(act_name))
            table.setItem(row_idx, 1, QTableWidgetItem(key_seq))
        table.setMinimumHeight(210)
        keys_layout.addWidget(table)
        layout.addWidget(grp_keys)

        self.stack.addWidget(_scroll_wrap(page, self))

    def _on_quick_start_clicked(self) -> None:
        if self._parent_window is not None and hasattr(self._parent_window, "show_quick_start"):
            self._parent_window.show_quick_start()

    def _on_about_clicked(self) -> None:
        if self._parent_window is not None and hasattr(self._parent_window, "show_about_dialog"):
            self._parent_window.show_about_dialog()

    def _on_open_docs_clicked(self) -> None:
        docs_dir = Path(__file__).resolve().parents[3] / "docs"
        if docs_dir.exists():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(docs_dir)))
        else:
            QDesktopServices.openUrl(QUrl(RELEASES_HTML_URL))

    # ------------------------------------------------------------------
    # Вспомогательные методы и применение настроек
    # ------------------------------------------------------------------
    def pick_color(self) -> None:
        color = QColorDialog.getColor(QColor(self.color.text()), self)
        if color.isValid():
            self.color.setText(color.name())

    def _validate_and_save(self) -> bool:
        if not QColor(self.color.text()).isValid():
            QMessageBox.warning(self, tr("common.warning"), tr("import.err.invalid_color"))
            self.select_section("map_coords")
            self.color.setFocus()
            return False
        if self.zone.isChecked() and self.radius.value() <= 0:
            QMessageBox.warning(self, tr("common.warning"), tr("import.err.radius_required_when_zone_enabled"))
            self.select_section("map_coords")
            self.radius.setFocus()
            return False

        s = self.s
        # Общие
        if hasattr(s, "set_startup_behavior"):
            s.set_startup_behavior(self.startup_behavior.currentData())
        s._set_bool("recovery/enabled", self.recovery.isChecked())
        s._set_str("recovery/seconds", str(self.interval.value()))

        # Интерфейс
        s._set_str("ui/theme", str(self.theme.currentData()))
        if hasattr(s, "set_toolbar_visible"):
            s.set_toolbar_visible(self.show_toolbar.isChecked())
        if hasattr(s, "set_left_panel_visible"):
            s.set_left_panel_visible(self.show_left_panel.isChecked())
        if hasattr(s, "set_right_panel_visible"):
            s.set_right_panel_visible(self.show_right_panel.isChecked())
        if hasattr(s, "set_statusbar_visible"):
            s.set_statusbar_visible(self.show_statusbar.isChecked())
        s._set_bool("ui/points_bottom", self.points_bottom.isChecked())
        s._set_bool("ui/auto_properties", self.auto_properties.isChecked())

        # Карта и координаты
        if hasattr(s, "set_show_coordinate_grid"):
            s.set_show_coordinate_grid(self.show_grid.isChecked())
        if hasattr(s, "set_show_scale_indicator"):
            s.set_show_scale_indicator(self.show_scale.isChecked())
        if hasattr(s, "set_show_points_visible"):
            s.set_show_points_visible(self.show_points.isChecked())
        if hasattr(s, "set_show_zones_visible"):
            s.set_show_zones_visible(self.show_zones.isChecked())
        if hasattr(s, "set_point_labels_mode"):
            s.set_point_labels_mode(str(self.labels_mode.currentData()))
        if hasattr(s, "set_point_label_content"):
            s.set_point_label_content(str(self.label_content.currentData()))

        s._set_str(
            "points/defaults",
            json.dumps(
                {
                    "symbol": self.shape.currentData(),
                    "size": self.size.value(),
                    "color": QColor(self.color.text()).name(),
                    "zone_enabled": self.zone.isChecked(),
                    "radius_m": self.radius.value(),
                }
            ),
        )
        s._set_str("coordinates/format", str(self.format.currentData()))
        s._set_str("coordinates/precision", str(self.precision.value()))
        s._set_str("coordinates/separator", str(self.separator.currentData()))
        if hasattr(s, "set_distance_unit"):
            s.set_distance_unit(str(self.distance_unit.currentData()))

        # Интернет и кэш
        s.set_online_cache_max_mb(self.cache.value())
        s._set_bool("map/antialias", self.antialias.isChecked())
        if hasattr(s, "set_network_timeout_sec"):
            s.set_network_timeout_sec(self.network_timeout.value())

        # Обновления
        if hasattr(s, "set_auto_check_updates"):
            s.set_auto_check_updates(self.auto_check_updates.isChecked())

        # Синхронизация с главным окном
        w = self._parent_window
        if w is not None:
            if hasattr(w, "sync_from_settings_dialog"):
                w.sync_from_settings_dialog(self)
            elif hasattr(w, "apply_preferences"):
                w.apply_preferences()
        return True

    def _on_apply_clicked(self) -> None:
        self._validate_and_save()

    def accept(self) -> None:
        if not self._validate_and_save():
            return
        super().accept()
