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
