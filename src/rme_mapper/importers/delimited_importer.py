"""Парсер текстовых файлов с разделителями (*.csv, *.txt).

Поддерживает разделители (запятая, точка с запятой, табуляция),
автоопределение кодировок (UTF-8, UTF-8-BOM, CP1251) и пропуск пустых строк.
"""

import csv
import io
import logging
from pathlib import Path
from typing import Any

from rme_mapper.importers.base import BaseImporter
from rme_mapper.importers.models import ImportOptions

logger = logging.getLogger("rme_mapper.importers.delimited")


class DelimitedImporter(BaseImporter):
    """Импортер текстовых файлов табличного формата с разделителями."""

    SUPPORTED_EXTENSIONS = {".csv", ".txt"}

    def can_handle(self, file_path: Path) -> bool:
        """Проверка поддерживаемых расширений (.csv, .txt)."""
        return file_path.suffix.lower() in self.SUPPORTED_EXTENSIONS

    @staticmethod
    def detect_encoding(raw_bytes: bytes) -> str:
        """Определение кодировки байтов: UTF-8-BOM, UTF-8 или CP1251."""
        if raw_bytes.startswith(b"\xef\xbb\xbf"):
            return "utf-8-sig"

        try:
            raw_bytes.decode("utf-8")
            return "utf-8"
        except UnicodeDecodeError:
            pass

        try:
            raw_bytes.decode("cp1251")
            return "cp1251"
        except UnicodeDecodeError:
            pass

        return "utf-8"

    @staticmethod
    def detect_delimiter(first_line: str, file_ext: str) -> str:
        """Автоопределение разделителя по первой строке файла.

        Приоритет:
        - Если в строке есть символы табуляции -> '\t'
        - Если есть точка с запятой (стандарт для европейских/русских CSV с десятичной запятой) -> ';'
        - Если есть запятая -> ','
        - По умолчанию для .txt -> '\t', для .csv -> ';'
        """
        tab_count = first_line.count("\t")
        semi_count = first_line.count(";")
        comma_count = first_line.count(",")

        # Если есть табуляция, в первую очередь предполагаем TSV/TXT
        if tab_count > 0 and tab_count >= semi_count and tab_count >= comma_count:
            return "\t"

        # Точка с запятой имеет приоритет над запятой (исключает ложный выбор при десятичных запятых)
        if semi_count > 0 and semi_count >= comma_count:
            return ";"

        if comma_count > 0:
            return ","

        if tab_count > 0:
            return "\t"

        if semi_count > 0:
            return ";"

        return "\t" if file_ext.lower() == ".txt" else ";"

    def read_rows(
        self,
        file_path: Path,
        options: ImportOptions,
    ) -> tuple[list[tuple[int, dict[str, Any]]], str | None, str | None, str | None]:
        """Чтение строк из текстового файла с разделителями."""
        if not file_path.exists():
            raise FileNotFoundError(f"Файл не найден: {file_path}")

        raw_bytes = file_path.read_bytes()
        encoding = options.encoding or self.detect_encoding(raw_bytes)

        try:
            text = raw_bytes.decode(encoding)
        except Exception as e:
            logger.error("Ошибка декодирования файла %s с кодировкой %s: %s", file_path, encoding, e)
            raise ValueError(f"Не удалось прочитать файл в кодировке {encoding}: {e}")

        # Нормализация переводов строк
        text_io = io.StringIO(text, newline=None)

        # 1. Поиск первой непустой строки для определения разделителя и заголовков
        lines = text_io.readlines()
        if not lines:
            return [], encoding, None, None

        header_line_idx = -1
        first_line_content = ""
        for idx, line in enumerate(lines):
            stripped = line.strip()
            if stripped:
                header_line_idx = idx
                first_line_content = stripped
                break

        if header_line_idx == -1:
            return [], encoding, None, None

        delimiter = options.delimiter or self.detect_delimiter(first_line_content, file_path.suffix)

        # 2. Чтение через csv.reader
        # Передаем строки начиная со строки заголовка
        reader = csv.reader(lines[header_line_idx:], delimiter=delimiter)

        try:
            raw_headers = next(reader)
        except StopIteration:
            return [], encoding, delimiter, None

        headers = [h.strip() for h in raw_headers]
        if not any(headers):
            return [], encoding, delimiter, None

        data_rows: list[tuple[int, dict[str, Any]]] = []
        curr_line_number = header_line_idx + 1  # 1-indexed номер строки заголовка

        for row in reader:
            curr_line_number += 1
            if not row:
                continue

            # Проверяем, есть ли хоть одно непустое значение
            row_dict: dict[str, Any] = {}
            is_empty = True

            for col_idx, header in enumerate(headers):
                if not header:
                    continue
                val = row[col_idx].strip() if col_idx < len(row) else ""
                if val:
                    is_empty = False
                row_dict[header] = val

            if not is_empty:
                data_rows.append((curr_line_number, row_dict))

        return data_rows, encoding, delimiter, None
