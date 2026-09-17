"""Модели данных подсистемы импорта точек.

Содержит чистые структуры данных без зависимостей от графического интерфейса Qt.
"""

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

from rme_mapper.models.map_point import MapPoint


class CoordinateFormat(str, Enum):
    """Формат координат для разбора файла."""
    AUTO = "auto"
    DD = "dd"
    DMS = "dms"


@dataclass
class ImportOptions:
    """Параметры импорта файла с точками."""
    coordinate_format: CoordinateFormat = CoordinateFormat.AUTO
    source_crs: str = "EPSG:4326"
    sheet_name: str | None = None
    delimiter: str | None = None
    encoding: str | None = None
    boundary_geometry: Any = None


@dataclass
class ImportRowError:
    """Информация об ошибке валидации конкретной строки файла."""
    row_number: int
    field: str
    code: str
    params: dict[str, Any] = field(default_factory=dict)
    raw_value: Any = None

    def localized_message(self, lang: str | None = None) -> str:
        """Формирование локализованного текста ошибки через TranslationService."""
        try:
            from rme_mapper.i18n import get_translation_service
            ts = get_translation_service()
            if lang:
                return ts.translate_in_language(lang, self.code, **self.params)
            return ts.translate(self.code, **self.params)
        except Exception:
            return f"Error ({self.code}): {self.params}"

    def __str__(self) -> str:
        return self.localized_message()


@dataclass
class ImportRowWarning:
    """Информация о предупреждении при валидации строки файла."""
    row_number: int
    field: str
    code: str
    params: dict[str, Any] = field(default_factory=dict)
    raw_value: Any = None

    def localized_message(self, lang: str | None = None) -> str:
        """Формирование локализованного текста предупреждения через TranslationService."""
        try:
            from rme_mapper.i18n import get_translation_service
            ts = get_translation_service()
            if lang:
                return ts.translate_in_language(lang, self.code, **self.params)
            return ts.translate(self.code, **self.params)
        except Exception:
            return f"Warning ({self.code}): {self.params}"

    def __str__(self) -> str:
        return self.localized_message()


@dataclass
class ImportRow:
    """Результат разбора и валидации одной строки файла."""
    row_number: int
    raw_data: dict[str, Any]
    point: MapPoint | None = None
    is_valid: bool = True
    errors: list[ImportRowError] = field(default_factory=list)
    warnings: list[ImportRowWarning] = field(default_factory=list)


@dataclass
class ImportResult:
    """Итоговый отчет о результатах анализа и валидации файла импорта."""
    file_path: Path
    detected_format: CoordinateFormat = CoordinateFormat.AUTO
    detected_encoding: str | None = None
    detected_delimiter: str | None = None
    sheet_name: str | None = None
    total_rows: int = 0
    valid_rows: int = 0
    invalid_rows: int = 0
    points: list[MapPoint] = field(default_factory=list)
    errors: list[ImportRowError] = field(default_factory=list)
    warnings: list[ImportRowWarning] = field(default_factory=list)
    rows: list[ImportRow] = field(default_factory=list)
