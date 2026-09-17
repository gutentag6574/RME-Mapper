"""Парсер табличных файлов формата Microsoft Excel (*.xlsx).

Использует библиотеку openpyxl в режиме строгого чтения данных (read_only=True, data_only=True)
без исполнения макросов, формул или внешних ссылок.
"""

from pathlib import Path
from typing import Any
import logging
import openpyxl

from rme_mapper.importers.base import BaseImporter
from rme_mapper.importers.models import ImportOptions

logger = logging.getLogger("rme_mapper.importers.xlsx")


class XlsxImporter(BaseImporter):
    """Импортер табличных данных из файлов формата Excel (*.xlsx)."""

    def can_handle(self, file_path: Path) -> bool:
        """Проверка расширения файла (*.xlsx)."""
        return file_path.suffix.lower() == ".xlsx"

    def get_sheet_names(self, file_path: Path) -> list[str]:
        """Получение списка рабочих листов книги без полной загрузки данных."""
        if not file_path.exists() or not self.can_handle(file_path):
            return []
        try:
            wb = openpyxl.load_workbook(str(file_path), read_only=True, keep_links=False)
            names = list(wb.sheetnames)
            wb.close()
            return names
        except Exception as e:
            logger.error("Ошибка чтения списка листов Excel %s: %s", file_path, e)
            return []

    def read_preview_rows(
        self,
        file_path: Path,
        options: ImportOptions,
        max_rows: int = 100,
    ) -> tuple[list[list[str]], int, str | None, str | None]:
        """Чтение первых max_rows строк для предпросмотра структуры таблицы."""
        if not file_path.exists():
            return [], 0, None, None

        try:
            wb = openpyxl.load_workbook(str(file_path), read_only=True, data_only=True)
        except Exception as e:
            logger.error("Ошибка предпросмотра Excel %s: %s", file_path, e)
            return [], 0, None, None

        try:
            sheet_name = options.sheet_name
            if sheet_name and sheet_name in wb.sheetnames:
                ws = wb[sheet_name]
            else:
                ws = wb.active

            if not ws:
                return [], 0, None, None

            preview_rows: list[list[str]] = []
            total_count = 0

            for row in ws.iter_rows(values_only=True):
                total_count += 1
                if len(preview_rows) < max_rows:
                    row_strs = [str(c).strip() if c is not None else "" for c in (row or [])]
                    preview_rows.append(row_strs)

            # Выравниваем длину строк по максимальной длине
            max_cols = max((len(r) for r in preview_rows), default=0)
            normalized_rows = [r + [""] * (max_cols - len(r)) for r in preview_rows]

            return normalized_rows, total_count, None, None
        finally:
            wb.close()

    def read_rows(
        self,
        file_path: Path,
        options: ImportOptions,
    ) -> tuple[list[tuple[int, dict[str, Any]]], str | None, str | None, str | None]:
        """Чтение строк из первого или указанного листа книги Excel."""
        if not file_path.exists():
            raise FileNotFoundError(f"Файл не найден: {file_path}")

        try:
            wb = openpyxl.load_workbook(str(file_path), read_only=True, data_only=True)
        except Exception as e:
            logger.error("Ошибка открытия книги Excel %s: %s", file_path, e)
            raise ValueError(f"Не удалось открыть файл Excel: {e}")

        try:
            sheet_name = options.sheet_name
            if sheet_name and sheet_name in wb.sheetnames:
                ws = wb[sheet_name]
            else:
                ws = wb.active
                sheet_name = ws.title if ws else None

            if not ws:
                return [], None, None, sheet_name

            target_header_row = max(1, options.header_row)

            # Читаем строки через iter_rows
            headers: list[str] = []
            data_rows: list[tuple[int, dict[str, Any]]] = []

            for row_idx, row in enumerate(ws.iter_rows(values_only=True), start=1):
                if row_idx < target_header_row:
                    # Пропускаем строки до строки заголовка
                    continue

                if row_idx == target_header_row:
                    # Это строка заголовков
                    if row:
                        headers = [
                            str(c).strip() if (c is not None and str(c).strip() != "") else f"Column_{col_i+1}"
                            for col_i, c in enumerate(row)
                        ]
                    continue

                # Строки данных (row_idx > target_header_row)
                if not headers:
                    continue

                if not row:
                    continue

                row_dict: dict[str, Any] = {}
                is_row_empty = True

                for col_idx, header in enumerate(headers):
                    val = row[col_idx] if col_idx < len(row) else None
                    if val is not None and str(val).strip() != "":
                        is_row_empty = False
                        if isinstance(val, str):
                            val = val.strip()
                        row_dict[header] = val
                    else:
                        row_dict[header] = ""

                if not is_row_empty:
                    data_rows.append((row_idx, row_dict))

            return data_rows, None, None, sheet_name
        finally:
            wb.close()
