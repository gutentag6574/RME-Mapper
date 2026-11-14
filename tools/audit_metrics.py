"""Детерминированный расчет метрик статического аудита и локализации GeoPoint Mapper."""
from __future__ import annotations

import ast
from pathlib import Path
import re
import string
import sys

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = PROJECT_ROOT / "src" / "rme_mapper"


def _find_duplicate_dict_keys(py_file: Path) -> list[str]:
    """Поиск дублирующихся строковых ключей в словарях переводов через AST."""
    tree = ast.parse(py_file.read_text(encoding="utf-8"), filename=str(py_file))
    seen: set[str] = set()
    duplicates: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Dict):
            for key_node in node.keys:
                if isinstance(key_node, ast.Constant) and isinstance(key_node.value, str):
                    k = key_node.value
                    if k in seen:
                        duplicates.append(k)
                    seen.add(k)
    return duplicates


def _find_placeholder_mismatches(ru_dict: dict[str, str], en_dict: dict[str, str]) -> list[str]:
    """Проверка совпадения именованных плейсхолдеров форматирования между RU и EN."""
    fmt = string.Formatter()
    mismatches: list[str] = []
    for key in sorted(set(ru_dict.keys()) & set(en_dict.keys())):
        ru_fields = {f for _, f, _, _ in fmt.parse(ru_dict[key]) if f is not None}
        en_fields = {f for _, f, _, _ in fmt.parse(en_dict[key]) if f is not None}
        if ru_fields != en_fields:
            mismatches.append(key)
    return mismatches


def count_localization_metrics() -> dict[str, int | bool]:
    """Детерминированный подсчет ключей локализации."""
    # Регулярные выражения для всех строковых литералов-ключей (включая дефисы '-')
    # в вызовах tr(...), ImportRowError(..., code=...) и ValidationError(...)
    tr_pattern = re.compile(r'\btr\(\s*["\']([a-zA-Z0-9_.-]+)["\']')
    code_pattern = re.compile(r'\bcode\s*=\s*["\']([a-zA-Z0-9_.-]+)["\']')
    val_pattern = re.compile(r'\bValidationError\(\s*["\']([a-zA-Z0-9_.-]+)["\']')

    source_tr_keys: set[str] = set()
    total_tr_call_sites = 0

    # Сканируем весь продакшн-код в src/rme_mapper, исключая сами словари переводов
    for py_file in sorted(SRC_DIR.rglob("*.py")):
        if py_file.name in ("translations_ru.py", "translations_en.py"):
            continue
        text = py_file.read_text(encoding="utf-8")
        tr_matches = tr_pattern.findall(text)
        total_tr_call_sites += len(tr_matches)
        for k in tr_matches:
            source_tr_keys.add(k)
        for k in code_pattern.findall(text):
            source_tr_keys.add(k)
        for k in val_pattern.findall(text):
            source_tr_keys.add(k)

    # Загружаем словари переводов
    from rme_mapper.i18n.translations_ru import TRANSLATIONS_RU
    from rme_mapper.i18n.translations_en import TRANSLATIONS_EN

    dict_ru_keys = set(TRANSLATIONS_RU.keys())
    dict_en_keys = set(TRANSLATIONS_EN.keys())

    missing_in_ru = source_tr_keys - dict_ru_keys
    missing_in_en = source_tr_keys - dict_en_keys
    parity = (dict_ru_keys == dict_en_keys)

    ru_path = SRC_DIR / "i18n" / "translations_ru.py"
    en_path = SRC_DIR / "i18n" / "translations_en.py"
    dup_ru = _find_duplicate_dict_keys(ru_path)
    dup_en = _find_duplicate_dict_keys(en_path)
    placeholder_mismatches = _find_placeholder_mismatches(TRANSLATIONS_RU, TRANSLATIONS_EN)

    return {
        "unique_source_tr_keys": len(source_tr_keys),
        "total_source_tr_call_sites": total_tr_call_sites,
        "dict_ru_keys_count": len(dict_ru_keys),
        "dict_en_keys_count": len(dict_en_keys),
        "missing_in_ru_count": len(missing_in_ru),
        "missing_in_en_count": len(missing_in_en),
        "dictionaries_parity": parity,
        "duplicate_ru_keys_count": len(dup_ru),
        "duplicate_en_keys_count": len(dup_en),
        "placeholder_mismatch_count": len(placeholder_mismatches),
    }


def main() -> int:
    metrics = count_localization_metrics()
    print("=== GeoPoint Mapper Localization & Audit Metrics ===")
    print(f"Unique keys used in source code via tr/code/ValidationError: {metrics['unique_source_tr_keys']}")
    print(f"Total call sites of tr(...) in source code: {metrics['total_source_tr_call_sites']}")
    print(f"Defined keys in translations_ru: {metrics['dict_ru_keys_count']}")
    print(f"Defined keys in translations_en: {metrics['dict_en_keys_count']}")
    print(f"Missing in RU: {metrics['missing_in_ru_count']}")
    print(f"Missing in EN: {metrics['missing_in_en_count']}")
    print(f"Dictionaries parity (RU == EN): {metrics['dictionaries_parity']}")
    print(f"Duplicate keys in RU: {metrics['duplicate_ru_keys_count']}")
    print(f"Duplicate keys in EN: {metrics['duplicate_en_keys_count']}")
    print(f"Placeholder mismatches (RU vs EN): {metrics['placeholder_mismatch_count']}")

    assert metrics["missing_in_ru_count"] == 0, "Missing keys in RU dictionary!"
    assert metrics["missing_in_en_count"] == 0, "Missing keys in EN dictionary!"
    assert metrics["dictionaries_parity"] is True, "RU and EN dictionaries out of parity!"
    assert metrics["duplicate_ru_keys_count"] == 0, "Duplicate keys in RU dictionary!"
    assert metrics["duplicate_en_keys_count"] == 0, "Duplicate keys in EN dictionary!"
    assert metrics["placeholder_mismatch_count"] == 0, "Placeholder mismatch between RU and EN dictionaries!"
    return 0


if __name__ == "__main__":
    sys.exit(main())
