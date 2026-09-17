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

            rows_iter = ws.iter_rows(values_only=True)

            # 1. Поиск строки заголовков
            headers: list[str] = []
            header_row_idx = 1
            for row_idx, row in enumerate(rows_iter, start=1):
                if not row:
                    continue
                # Проверяем, есть ли хоть одна непустая ячейка
                non_empty = [c for c in row if c is not None and str(c).strip() != ""]
                if non_empty:
                    headers = [str(c).strip() if c is not None else "" for c in row]
                    header_row_idx = row_idx
                    break

            if not headers:
                return [], None, None, sheet_name

            # 2. Чтение данных
            data_rows: list[tuple[int, dict[str, Any]]] = []
            curr_row_idx = header_row_idx

            for row in rows_iter:
                curr_row_idx += 1
                if not row:
                    continue

                # Формируем словарь значений для строки
                row_dict: dict[str, Any] = {}
                is_row_empty = True

                for col_idx, header in enumerate(headers):
                    if not header:
                        continue
                    val = row[col_idx] if col_idx < len(row) else None
                    if val is not None and str(val).strip() != "":
                        is_row_empty = False
                        # Очищаем строковые значения от краевых пробелов
                        if isinstance(val, str):
                            val = val.strip()
                        row_dict[header] = val
                    else:
                        row_dict[header] = ""

                # Полностью пустые строки пропускаем
                if not is_row_empty:
                    data_rows.append((curr_row_idx, row_dict))

            return data_rows, None, None, sheet_name
        finally:
            wb.close()
