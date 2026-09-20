"""Диалог выбора и настройки онлайн-картографической подложки (OnlineBasemapDialog)."""

import logging
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QVBoxLayout,
    QWidget,
)

from rme_mapper.i18n import tr
from rme_mapper.models.online_provider import (
    MapType,
    OnlineTileProvider,
    ProviderRegistry,
)
from rme_mapper.services.tile_cache import TileDiskCache

logger = logging.getLogger("rme_mapper.ui.online_basemap_dialog")


class OnlineBasemapDialog(QDialog):
    """Диалог выбора типа онлайн-карты, провайдера, ввода API-ключа и управления кэшем."""

    def __init__(
        self,
        parent: QWidget | None = None,
        settings_service: Any = None,
        current_provider: OnlineTileProvider | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("onlineBasemapDialog")
        self.setWindowTitle(tr("dialog.online_map.title"))
        self.resize(480, 420)

        self._settings = settings_service
        self._cache = TileDiskCache()
        self._selected_provider: OnlineTileProvider | None = current_provider

        self._setup_ui()
        self._load_saved_values(current_provider)

    def _setup_ui(self) -> None:
        main_layout = QVBoxLayout(self)
        main_layout.setSpacing(12)

        # 1. Группа выбора типа карты (Standard / Satellite / Hybrid / Custom)
        type_group_box = QGroupBox(tr("dialog.online_map.map_type"), self)
        type_layout = QHBoxLayout(type_group_box)

        self._type_btn_group = QButtonGroup(self)
        self._rb_standard = QRadioButton(tr("dialog.online_map.type_standard"), self)
        self._rb_satellite = QRadioButton(tr("dialog.online_map.type_satellite"), self)
        self._rb_hybrid = QRadioButton(tr("dialog.online_map.type_hybrid"), self)
        self._rb_custom = QRadioButton(tr("dialog.online_map.custom_xyz"), self)

        self._type_btn_group.addButton(self._rb_standard, 0)
        self._type_btn_group.addButton(self._rb_satellite, 1)
        self._type_btn_group.addButton(self._rb_hybrid, 2)
        self._type_btn_group.addButton(self._rb_custom, 3)

        type_layout.addWidget(self._rb_standard)
        type_layout.addWidget(self._rb_satellite)
        type_layout.addWidget(self._rb_hybrid)
        type_layout.addWidget(self._rb_custom)

        self._rb_standard.setChecked(True)
        self._type_btn_group.idToggled.connect(self._on_type_changed)
        main_layout.addWidget(type_group_box)

        # 2. Форма параметров провайдера
        form_group_box = QGroupBox(tr("dialog.online_map.provider"), self)
        form_layout = QFormLayout(form_group_box)
        form_layout.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        self._provider_combo = QComboBox(self)
        self._provider_combo.currentIndexChanged.connect(self._on_provider_combo_changed)
        form_layout.addRow(tr("dialog.online_map.provider"), self._provider_combo)

        # Поле URL-шаблона для Custom XYZ
        self._url_edit = QLineEdit(self)
        self._url_edit.setPlaceholderText("https://example.com/tiles/{z}/{x}/{y}.png")
        self._url_edit.textChanged.connect(self._validate_dialog)
        form_layout.addRow(tr("dialog.online_map.url_template"), self._url_edit)

        self._http_warning_label = QLabel(self)
        self._http_warning_label.setStyleSheet("color: #D97706; font-size: 11px;")
        self._http_warning_label.setWordWrap(True)
        self._http_warning_label.hide()
        form_layout.addRow("", self._http_warning_label)

        # Поле ввода API-ключа (токена)
        key_layout = QVBoxLayout()
        self._key_edit = QLineEdit(self)
        self._key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self._key_edit.setPlaceholderText("pk.eyJ1...")
        self._key_edit.textChanged.connect(self._validate_dialog)
        key_layout.addWidget(self._key_edit)

        key_opts_layout = QHBoxLayout()
        self._show_key_cb = QCheckBox(tr("properties.show_password") if tr("properties.show_password") != "properties.show_password" else "Показать ключ", self)
        self._show_key_cb.toggled.connect(
            lambda checked: self._key_edit.setEchoMode(
                QLineEdit.EchoMode.Normal if checked else QLineEdit.EchoMode.Password
            )
        )
        key_opts_layout.addWidget(self._show_key_cb)

        self._key_tip_label = QLabel(tr("dialog.online_map.api_key_tip"), self)
        self._key_tip_label.setStyleSheet("color: #64748B; font-size: 11px;")
        key_opts_layout.addWidget(self._key_tip_label)
        key_opts_layout.addStretch()
        key_layout.addLayout(key_opts_layout)

        form_layout.addRow(tr("dialog.online_map.api_key"), key_layout)

        # Атрибуция
        self._attr_edit = QLineEdit(self)
        self._attr_edit.setPlaceholderText("© Provider Name")
        form_layout.addRow(tr("dialog.online_map.attribution"), self._attr_edit)

        self._chk_mandatory_attr = QCheckBox("Обязательная атрибуция (нельзя отключить при экспорте)", self)
        self._chk_mandatory_attr.setChecked(True)
        form_layout.addRow("", self._chk_mandatory_attr)

        main_layout.addWidget(form_group_box)

        # 3. Блок информации и очистки дискового кэша
        cache_group = QGroupBox("Дисковый кэш тайлов", self)
        cache_layout = QHBoxLayout(cache_group)

        self._cache_size_label = QLabel(self)
        self._update_cache_size_display()
        cache_layout.addWidget(self._cache_size_label)
        cache_layout.addStretch()

        self._btn_clear_cache = QPushButton(tr("action.clear_tile_cache"), self)
        self._btn_clear_cache.clicked.connect(self._on_clear_cache_clicked)
        cache_layout.addWidget(self._btn_clear_cache)

        main_layout.addWidget(cache_group)

        # 4. Кнопки Подключить / Отмена
        self._button_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
            self,
        )
        self._btn_ok = self._button_box.button(QDialogButtonBox.StandardButton.Ok)
        self._btn_ok.setText(tr("dialog.online_map.btn_load"))
        self._btn_cancel = self._button_box.button(QDialogButtonBox.StandardButton.Cancel)
        self._btn_cancel.setText(tr("btn.cancel"))

        self._button_box.accepted.connect(self._on_accept)
        self._button_box.rejected.connect(self.reject)
        main_layout.addWidget(self._button_box)

        self._refresh_provider_list()

    def _update_cache_size_display(self) -> None:
        size_bytes = self._cache.get_total_size_bytes()
        self._cache_size_label.setText(f"Размер кэша: {TileDiskCache.format_size(size_bytes)}")

    def _on_clear_cache_clicked(self) -> None:
        size_bytes = self._cache.get_total_size_bytes()
        formatted = TileDiskCache.format_size(size_bytes)
        reply = QMessageBox.question(
            self,
            tr("action.clear_tile_cache"),
            tr("dialog.online_map.clear_cache_confirm", size=formatted),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            self._cache.clear_cache()
            self._update_cache_size_display()
            logger.info("Кэш онлайн-карт очищен пользователем из диалога.")

    def _on_type_changed(self, btn_id: int, checked: bool) -> None:
        if not checked:
            return
        self._refresh_provider_list()

    def _get_current_map_type(self) -> MapType | None:
        if self._rb_standard.isChecked():
            return MapType.STANDARD
        elif self._rb_satellite.isChecked():
            return MapType.SATELLITE
        elif self._rb_hybrid.isChecked():
            return MapType.HYBRID
        return None  # Custom

    def _refresh_provider_list(self) -> None:
        self._provider_combo.blockSignals(True)
        self._provider_combo.clear()

        mtype = self._get_current_map_type()
        is_custom = (mtype is None)

        if is_custom:
            self._provider_combo.addItem(tr("dialog.online_map.custom_xyz"), "custom")
            self._provider_combo.setEnabled(False)
            self._url_edit.setEnabled(True)
            self._attr_edit.setEnabled(True)
        else:
            self._provider_combo.setEnabled(True)
            self._url_edit.setEnabled(False)
            self._attr_edit.setEnabled(False)
            providers = ProviderRegistry.list_providers(map_type=mtype)
            for p in providers:
                self._provider_combo.addItem(p.name, p.id)

        self._provider_combo.blockSignals(False)
        self._on_provider_combo_changed(self._provider_combo.currentIndex())

    def _on_provider_combo_changed(self, index: int) -> None:
        mtype = self._get_current_map_type()
        if mtype is None:
            # Custom
            self._url_edit.setEnabled(True)
            self._attr_edit.setEnabled(True)
            self._key_edit.setEnabled(True)
            self._key_tip_label.setText(tr("dialog.online_map.api_key_tip"))
        else:
            pid = self._provider_combo.currentData()
            provider = ProviderRegistry.get_provider(str(pid)) if pid else None
            if provider:
                self._url_edit.setText(provider.url_template)
                self._attr_edit.setText(provider.attribution)
                self._key_edit.setEnabled(provider.requires_api_key)

                if provider.requires_api_key:
                    saved_key = ""
                    if self._settings:
                        saved_key = self._settings.get_provider_api_key(provider.id)
                    if not saved_key:
                        saved_key = provider.get_effective_api_key() or ""
                    self._key_edit.setText(saved_key)
                    self._key_tip_label.setText(tr("dialog.online_map.key_required"))
                else:
                    self._key_edit.clear()
                    self._key_tip_label.setText("Ключ не требуется")

        self._validate_dialog()

    def _validate_dialog(self) -> None:
        mtype = self._get_current_map_type()
        key = self._key_edit.text().strip()

        # Проверка на запрет секретных токенов Mapbox sk...
        if key.startswith("sk."):
            self._btn_ok.setEnabled(False)
            self._key_tip_label.setText("<span style='color: #EF4444; font-weight: bold;'>Секретные токены (sk...) запрещены! Используйте публичный токен (pk...).</span>")
            return

        if mtype is None:
            # Custom XYZ
            url = self._url_edit.text().strip()
            valid = OnlineTileProvider.validate_url_template(url)
            if url.lower().startswith("http://"):
                self._http_warning_label.setText("Внимание: используется незащищенное HTTP-соединение. Рекомендуется HTTPS.")
                self._http_warning_label.show()
            else:
                self._http_warning_label.hide()
            self._btn_ok.setEnabled(valid)
        else:
            self._http_warning_label.hide()
            pid = self._provider_combo.currentData()
            provider = ProviderRegistry.get_provider(str(pid)) if pid else None
            if provider and provider.requires_api_key:
                has_key = bool(key)
                self._btn_ok.setEnabled(has_key)
                self._key_tip_label.setText(tr("dialog.online_map.key_required"))
            else:
                self._btn_ok.setEnabled(True)
                self._key_tip_label.setText("Ключ не требуется")

    def _load_saved_values(self, current_provider: OnlineTileProvider | None) -> None:
        if current_provider:
            if current_provider.map_type == MapType.STANDARD:
                self._rb_standard.setChecked(True)
            elif current_provider.map_type == MapType.SATELLITE:
                self._rb_satellite.setChecked(True)
            elif current_provider.map_type == MapType.HYBRID:
                self._rb_hybrid.setChecked(True)
            else:
                self._rb_custom.setChecked(True)

            idx = self._provider_combo.findData(current_provider.id)
            if idx >= 0:
                self._provider_combo.setCurrentIndex(idx)
            else:
                self._url_edit.setText(current_provider.url_template)
                self._attr_edit.setText(current_provider.attribution)

    def _on_accept(self) -> None:
        mtype = self._get_current_map_type()
        key = self._key_edit.text().strip() or None

        # Защита от секретных токенов sk...
        if key and key.startswith("sk."):
            QMessageBox.critical(
                self,
                tr("dialog.online_map.title"),
                "Секретные токены Mapbox (sk...) запрещены в целях безопасности. Используйте только публичный токен (pk...).",
            )
            return

        if mtype is None:
            url = self._url_edit.text().strip()
            attr = self._attr_edit.text().strip() or "Custom XYZ"
            attr_req = self._chk_mandatory_attr.isChecked()
            provider = ProviderRegistry.create_custom_provider(
                id=f"custom_{abs(hash(url)) % 1000000}",
                name="Пользовательская карта",
                url_template=url,
                attribution=attr,
                attribution_required=attr_req,
                api_key_param_name="access_token" if "access_token" in url else "key",
            )
            self._selected_provider = provider
            self._api_key = key
        else:
            pid = str(self._provider_combo.currentData())
            provider = ProviderRegistry.get_provider(pid)
            if provider is None:
                self.reject()
                return
            if key and self._settings:
                self._settings.set_provider_api_key(provider.id, key)
            self._selected_provider = provider
            self._api_key = key

        self.accept()

    def get_selected_provider(self) -> OnlineTileProvider | None:
        """Получение выбранного провайдера."""
        return self._selected_provider

    def get_api_key(self) -> str | None:
        """Получение введенного API-ключа."""
        return getattr(self, "_api_key", None)

    @property
    def combo_provider(self) -> QComboBox:
        """Доступ к выпадающему списку провайдеров."""
        return self._provider_combo

    def _reload_providers(self) -> None:
        """Обновление списка провайдеров."""
        self._refresh_provider_list()
