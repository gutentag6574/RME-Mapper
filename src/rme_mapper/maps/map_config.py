"""Централизованная конфигурация путей к картографическим данным."""

from pathlib import Path


def get_project_root() -> Path:
    """Определение корневой директории проекта RME-Mapper."""
    # maps/map_config.py -> maps -> rme_mapper -> src -> RME-Mapper (корень)
    current = Path(__file__).resolve()
    for parent in current.parents:
        if (parent / "maps").is_dir() and (parent / "src").is_dir():
            return parent
    # Резервный вариант: 4 уровня вверх от данного файла
    return current.parent.parent.parent.parent


def get_default_geopackage_path() -> Path:
    """Получение пути к эталонному файлу GeoPackage Республики Марий Эл."""
    root = get_project_root()
    return root / "maps" / "test_map" / "prepared" / "mari.gpkg"
