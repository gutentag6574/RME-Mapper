"""Тесты полноты и целостности локализации приложения (Этап 27, BUG-003).

Проверяет:
1. Отсутствие пропущенных ключей локализации во всех вызовах tr(...) в исходном коде src/rme_mapper.
2. 100% покрытие словарей TRANSLATIONS_RU и TRANSLATIONS_EN.
3. Наличие обязательных ключей, исправленных в BUG-003 (btn.save, status.*, dialog.group.*, msg.file_not_found).
4. Корректность динамического переключения языка интерфейса (RU -> EN -> RU).
"""
from __future__ import annotations

from pathlib import Path
import re

import pytest

from rme_mapper.i18n import get_language, set_language, tr
from rme_mapper.i18n.translations_en import TRANSLATIONS_EN
from rme_mapper.i18n.translations_ru import TRANSLATIONS_RU
from rme_mapper.ui.main_window import MainWindow

ROOT_DIR = Path(__file__).resolve().parent.parent
SRC_DIR = ROOT_DIR / "src" / "rme_mapper"


def _extract_all_literal_tr_keys() -> set[str]:
    """Извлечение всех строковых литералов, переданных в вызовы tr(...) в исходном коде."""
    tr_pattern = re.compile(r'\btr\(\s*["\']([^"\']+)["\']')
    found_keys = set()
    for py_file in SRC_DIR.rglob("*.py"):
        text = py_file.read_text(encoding="utf-8")
        for match in tr_pattern.findall(text):
            found_keys.add(match)
    return found_keys


def test_01_all_source_code_tr_keys_exist_in_ru_dictionary() -> None:
    """BUG-003: Все строковые ключи tr(...) из продакшн-кода обязаны присутствовать в словаре RU."""
    keys = _extract_all_literal_tr_keys()
    assert len(keys) >= 600, f"Извлечено подозрительно мало ключей: {len(keys)}"

    missing_in_ru = [k for k in sorted(keys) if k not in TRANSLATIONS_RU]
    assert not missing_in_ru, f"Ключи отсутствуют в TRANSLATIONS_RU ({len(missing_in_ru)}): {missing_in_ru}"


def test_02_all_source_code_tr_keys_exist_in_en_dictionary() -> None:
    """BUG-003: Все строковые ключи tr(...) из продакшн-кода обязаны присутствовать в словаре EN."""
    keys = _extract_all_literal_tr_keys()
    missing_in_en = [k for k in sorted(keys) if k not in TRANSLATIONS_EN]
    assert not missing_in_en, f"Ключи отсутствуют в TRANSLATIONS_EN ({len(missing_in_en)}): {missing_in_en}"


def test_03_critical_bug003_keys_presence_and_translation() -> None:
    """BUG-003: Проверка наличия и смысловой корректности исправленных ключей в RU и EN."""
    critical_keys = [
        ("btn.save", "Сохранить", "Save"),
        ("status.error", "Ошибка", "Error"),
        ("status.online_maps_unsupported", "Онлайн-карты недоступны", "Online maps are unsupported"),
        ("status.geotiff_unsupported", "GeoTIFF недоступен", "GeoTIFF is unsupported"),
        ("status.geopackage_unsupported", "GeoPackage недоступен", "GeoPackage is unsupported"),
        ("msg.file_not_found", "не найден", "not found"),
        ("dialog.group.title_create", "Создание группы", "Create Group"),
        ("dialog.group.title_edit", "Редактирование группы", "Edit Group"),
        ("dialog.group.name", "Название:", "Name:"),
        ("dialog.group.description", "Описание:", "Description:"),
        ("dialog.group.description_placeholder", "Необязательное описание", "Optional group description"),
        ("dialog.group.err_duplicate_name", "Группа с таким названием уже существует", "A group with this name already exists"),
        ("border_style.none", "Без рамки", "None"),
        ("border_style.dotted", "Точечная", "Dotted"),
        ("border_style.dashed", "Пунктирная", "Dashed"),
        ("border_style.dash_dot", "Штрих-пунктир", "Dash-dot"),
    ]

    for key, ru_substr, en_substr in critical_keys:
        assert key in TRANSLATIONS_RU, f"Ключ {key} отсутствует в TRANSLATIONS_RU"
        assert key in TRANSLATIONS_EN, f"Ключ {key} отсутствует в TRANSLATIONS_EN"
        assert ru_substr in TRANSLATIONS_RU[key], f"В RU значении ключа {key} нет '{ru_substr}': {TRANSLATIONS_RU[key]}"
        assert en_substr in TRANSLATIONS_EN[key], f"В EN значении ключа {key} нет '{en_substr}': {TRANSLATIONS_EN[key]}"


def test_04_live_retranslation_cycle(qapp) -> None:
    """BUG-003: Проверка сквозного переключения языка RU -> EN -> RU на живом экземпляре MainWindow."""
    win = MainWindow()
    try:
        # 1. Русский
        win.switch_language("ru")
        assert get_language() == "ru"
        assert "Файл" in win.file_menu.title()
        assert "Новый проект" in win.new_action.text()
        assert win.lang_ru_action.isChecked()

        # 2. Английский
        win.switch_language("en")
        assert get_language() == "en"
        assert "File" in win.file_menu.title()
        assert "New Project" in win.new_action.text()
        assert win.lang_en_action.isChecked()

        # 3. Возврат на русский
        win.switch_language("ru")
        assert get_language() == "ru"
        assert "Файл" in win.file_menu.title()
        assert win.lang_ru_action.isChecked()
    finally:
        win.close()


def test_05_targeted_mainwindow_map_labels_ru_en(qapp) -> None:
    """Проверка заголовков карты и меток в MainWindow на RU и EN."""
    from rme_mapper.models.map_profile import MapProfile

    win = MainWindow()
    try:
        dummy_profile = MapProfile(
            id="test_profile",
            name="TestCity",
            source_type="geopackage",
            source_path="dummy.gpkg",
            crs="EPSG:4326",
        )
        win.map_controller._active_profile = dummy_profile

        # 1. RU
        win.switch_language("ru")
        assert win.map_title_label.text().startswith("Карта: TestCity")

        # 2. EN
        win.switch_language("en")
        assert win.map_title_label.text().startswith("Map: TestCity")
        assert "Карта:" not in win.map_title_label.text()

        # 3. Online basemap status label check
        win.switch_language("ru")
        status_ru = f"{tr('status.online_map_prefix')}: OSM | EPSG:3857"
        assert status_ru.startswith("Онлайн-карта:")

        win.switch_language("en")
        status_en = f"{tr('status.online_map_prefix')}: OSM | EPSG:3857"
        assert status_en.startswith("Online Map:")
        assert "Онлайн-карта" not in status_en
    finally:
        set_language("ru")
        win.close()


def test_06_targeted_export_objects_dialog_ru_en(qapp) -> None:
    """Проверка локализации ExportObjectsDialog на RU и EN (нет хардкод-строк)."""
    from rme_mapper.ui.export_objects_dialog import ExportObjectsDialog

    # 1. RU
    set_language("ru")
    dlg_ru = ExportObjectsDialog(points=[], selected_ids=[])
    try:
        assert dlg_ru.text_options_group.title() == "Параметры формата"
        assert dlg_ru.headers_checkbox.text() == "Включать строку заголовков"
        assert dlg_ru.btn_cancel.text() == "Отмена"
        assert dlg_ru.btn_browse.text() == "Обзор..."
        assert dlg_ru.path_edit.placeholderText() == "Выберите путь для сохранения..."
    finally:
        dlg_ru.close()

    # 2. EN
    set_language("en")
    dlg_en = ExportObjectsDialog(points=[], selected_ids=[])
    try:
        assert dlg_en.text_options_group.title() == "Format Options"
        assert dlg_en.headers_checkbox.text() == "Include header row"
        assert dlg_en.btn_cancel.text() == "Cancel"
        assert dlg_en.btn_browse.text() == "Browse..."
        assert dlg_en.path_edit.placeholderText() == "Select destination path..."

        # Проверка отсутствия сырых русских строк в EN
        assert "Параметры формата" not in dlg_en.text_options_group.title()
        assert "Включать строку" not in dlg_en.headers_checkbox.text()
        assert "Отмена" not in dlg_en.btn_cancel.text()
        assert "Обзор" not in dlg_en.btn_browse.text()
    finally:
        set_language("ru")
        dlg_en.close()


def test_07_targeted_point_dialog_ru_en(qapp) -> None:
    """Проверка локализации PointDialog на RU и EN."""
    from rme_mapper.ui.point_dialog import PointDialog

    # 1. RU
    set_language("ru")
    dlg_ru = PointDialog(mode="CREATE")
    try:
        assert "Добавить" in dlg_ru.windowTitle()
        assert dlg_ru.tab_widget.tabText(0) == "Основное"
        assert dlg_ru.tab_widget.tabText(1) == "Координаты"
        assert dlg_ru.tab_widget.tabText(2) == "Оформление"
        assert dlg_ru.btn_cancel.text() == "Отмена"
    finally:
        dlg_ru.close()

    # 2. EN
    set_language("en")
    dlg_en = PointDialog(mode="CREATE")
    try:
        assert "Add" in dlg_en.windowTitle()
        assert dlg_en.tab_widget.tabText(0) == "General"
        assert dlg_en.tab_widget.tabText(1) == "Coordinates"
        assert dlg_en.tab_widget.tabText(2) == "Style"
        assert dlg_en.btn_cancel.text() == "Cancel"

        # Сырых русских строк нет
        assert "Основное" not in dlg_en.tab_widget.tabText(0)
        assert "Отмена" not in dlg_en.btn_cancel.text()
    finally:
        set_language("ru")
        dlg_en.close()


def test_08_targeted_open_map_dialog_ru_en(qapp) -> None:
    """Проверка локализации OpenMapDialog на RU и EN."""
    from rme_mapper.ui.open_map_dialog import OpenMapDialog

    # 1. RU
    set_language("ru")
    dlg_ru = OpenMapDialog()
    try:
        assert "Открыть карту" in dlg_ru.windowTitle()
        assert dlg_ru.btn_cancel.text() == "Отмена"
        assert dlg_ru.btn_open.text() == "Открыть карту"
        assert dlg_ru.mode_group.title() == "Источник карты"
    finally:
        dlg_ru.close()

    # 2. EN
    set_language("en")
    dlg_en = OpenMapDialog()
    try:
        assert "Open Map" in dlg_en.windowTitle()
        assert dlg_en.btn_cancel.text() == "Cancel"
        assert dlg_en.btn_open.text() == "Open Map"
        assert dlg_en.mode_group.title() == "Map Source"

        # Сырых русских строк нет
        assert "Открыть карту" not in dlg_en.windowTitle()
        assert "Отмена" not in dlg_en.btn_cancel.text()
        assert "Источник карты" not in dlg_en.mode_group.title()
    finally:
        set_language("ru")
        dlg_en.close()


def test_09_targeted_online_basemap_dialog_ru_en(qapp) -> None:
    """Проверка локализации OnlineBasemapDialog на RU и EN."""
    from rme_mapper.ui.online_basemap_dialog import OnlineBasemapDialog

    # 1. RU
    set_language("ru")
    dlg_ru = OnlineBasemapDialog()
    try:
        assert "онлайн-подложки" in dlg_ru.windowTitle().lower()
        assert "обязательная атрибуция" in dlg_ru._chk_mandatory_attr.text().lower()
        assert dlg_ru._btn_ok.text() == "Подключить"
    finally:
        dlg_ru.close()

    # 2. EN
    set_language("en")
    dlg_en = OnlineBasemapDialog()
    try:
        assert "online basemap" in dlg_en.windowTitle().lower()
        assert "mandatory attribution" in dlg_en._chk_mandatory_attr.text().lower()
        assert dlg_en._btn_ok.text() == "Connect"

        # Сырых русских строк нет
        assert "подложки" not in dlg_en.windowTitle().lower()
        assert "атрибуция" not in dlg_en._chk_mandatory_attr.text().lower()
    finally:
        set_language("ru")
        dlg_en.close()


def test_10_targeted_import_wizard_buttons_ru_en(qapp) -> None:
    """BUG-003 & Final fix pass: Проверка кнопок мастера импорта на RU и EN."""
    from PySide6.QtWidgets import QWizard
    from rme_mapper.ui.import_wizard import ImportWizard

    # 1. RU кнопки
    set_language("ru")
    wiz_ru = ImportWizard()
    try:
        assert wiz_ru.buttonText(QWizard.WizardButton.BackButton) == "Назад"
        assert wiz_ru.buttonText(QWizard.WizardButton.NextButton) == "Далее"
        assert wiz_ru.buttonText(QWizard.WizardButton.CancelButton) == "Отмена"
        assert wiz_ru.buttonText(QWizard.WizardButton.FinishButton) == "Импортировать"
    finally:
        wiz_ru.close()

    # 2. EN кнопки
    set_language("en")
    wiz_en = ImportWizard()
    try:
        assert wiz_en.buttonText(QWizard.WizardButton.BackButton) == "Back"
        assert wiz_en.buttonText(QWizard.WizardButton.NextButton) == "Next"
        assert wiz_en.buttonText(QWizard.WizardButton.CancelButton) == "Cancel"
        assert wiz_en.buttonText(QWizard.WizardButton.FinishButton) == "Import"

        # Русских надписей на кнопках в EN быть не должно
        assert wiz_en.buttonText(QWizard.WizardButton.BackButton) != "Назад"
        assert wiz_en.buttonText(QWizard.WizardButton.NextButton) != "Далее"
        assert wiz_en.buttonText(QWizard.WizardButton.CancelButton) != "Отмена"
    finally:
        set_language("ru")
        wiz_en.close()
