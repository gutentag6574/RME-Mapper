"""Базовый абстрактный класс для парсеров файлов импорта."""

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

from rme_mapper.importers.models import ImportOptions


class BaseImporter(ABC):
    """Абстрактный базовый класс парсера табличных файлов с координатами."""

    @abstractmethod
    def can_handle(self, file_path: Path) -> bool:
        """Проверка, поддерживается ли данный формат файла парсером."""
        raise NotImplementedError

    @abstractmethod
    def read_rows(
        self,
        file_path: Path,
        options: ImportOptions,
    ) -> tuple[list[tuple[int, dict[str, Any]]], str | None, str | None, str | None]:
        """Чтение строк из файла.

        Возвращает:
            tuple[
                list[tuple[int, dict[str, Any]]]: список пар (номер_строки_файла, словарь_значений_колонок),
                str | None: определенная кодировка (для текстовых файлов),
                str | None: определенный разделитель (для delimited файлов),
                str | None: имя рабочего листа (для таблиц XLSX),
            ]
        """
        raise NotImplementedError

    def get_sheet_names(self, file_path: Path) -> list[str]:
        """Получение списка имен листов книги (для форматов таблиц, например XLSX)."""
        return []

    def read_preview_rows(
        self,
        file_path: Path,
        options: ImportOptions,
        max_rows: int = 100,
    ) -> tuple[list[list[str]], int, str | None, str | None]:
        """Чтение сырых строк файла для предварительного просмотра структуры.

        Возвращает:
            tuple[
                list[list[str]]: строки таблицы (списки строковых значений ячеек),
                int: приблизительное или точное общее число строк,
                str | None: определенная/использованная кодировка,
                str | None: определенный/использованный разделитель,
            ]
        """
        return [], 0, None, None
