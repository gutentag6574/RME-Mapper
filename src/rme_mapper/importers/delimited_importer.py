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
        """Автоопределение разделителя по строке файла.

        Приоритет:
        - Если в строке есть символы табуляции -> '\t'
        - Если есть точка с запятой -> ';'
        - Если есть запятая -> ','
        - По умолчанию для .txt -> '\t', для .csv -> ';'
        """
        tab_count = first_line.count("\t")
        semi_count = first_line.count(";")
        comma_count = first_line.count(",")

        if tab_count > 0 and tab_count >= semi_count and tab_count >= comma_count:
            return "\t"

        if semi_count > 0 and semi_count >= comma_count:
            return ";"

        if comma_count > 0:
            return ","

        if tab_count > 0:
            return "\t"

        if semi_count > 0:
            return ";"

        return "\t" if file_ext.lower() == ".txt" else ";"

    def read_preview_rows(
        self,
        file_path: Path,
        options: ImportOptions,
        max_rows: int = 100,
    ) -> tuple[list[list[str]], int, str | None, str | None]:
        """Чтение первых max_rows строк для предпросмотра структуры CSV/TXT."""
        if not file_path.exists():
            return [], 0, None, None

        raw_bytes = file_path.read_bytes()
        encoding = options.encoding or self.detect_encoding(raw_bytes)

        try:
            text = raw_bytes.decode(encoding)
        except Exception as e:
            logger.error("Ошибка декодирования %s в %s: %s", file_path, encoding, e)
            return [], 0, encoding, None

        lines = [line for line in io.StringIO(text, newline=None)]
        if not lines:
            return [], 0, encoding, None

        first_non_empty = ""
        for line in lines:
            if line.strip():
                first_non_empty = line.strip()
                break

        delimiter = options.delimiter or self.detect_delimiter(first_non_empty, file_path.suffix)

        preview_lines = lines[:max_rows]
        reader = csv.reader(preview_lines, delimiter=delimiter)
        preview_rows: list[list[str]] = []

        for row in reader:
            preview_rows.append([c.strip() for c in row])

        max_cols = max((len(r) for r in preview_rows), default=0)
        normalized_rows = [r + [""] * (max_cols - len(r)) for r in preview_rows]

        return normalized_rows, len(lines), encoding, delimiter

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

        text_io = io.StringIO(text, newline=None)
        lines = text_io.readlines()
        if not lines:
            return [], encoding, None, None

        target_header_row = max(1, options.header_row)
        header_line_idx = target_header_row - 1

        if header_line_idx >= len(lines):
            return [], encoding, None, None

        header_line_content = lines[header_line_idx].strip()
        delimiter = options.delimiter or self.detect_delimiter(header_line_content, file_path.suffix)

        # Читаем строки через csv.reader начиная со строки заголовка
        reader = csv.reader(lines[header_line_idx:], delimiter=delimiter)

        try:
            raw_headers = next(reader)
        except StopIteration:
            return [], encoding, delimiter, None

        headers = [
            h.strip() if h.strip() else f"Column_{i+1}"
            for i, h in enumerate(raw_headers)
        ]
        if not any(headers):
            return [], encoding, delimiter, None

        data_rows: list[tuple[int, dict[str, Any]]] = []
        curr_line_number = header_line_idx + 1  # 1-indexed номер строки заголовка

        for row in reader:
            curr_line_number += 1
            if not row:
                continue

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
