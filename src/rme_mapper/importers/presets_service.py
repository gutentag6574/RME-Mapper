"""Сервис сохранения и загрузки пресетов сопоставления колонок импорта."""
from __future__ import annotations


import json
import logging
from typing import Any

from rme_mapper.importers.models import CoordinateFormat, ImportPreset
from rme_mapper.services.app_settings_service import AppSettingsService

logger = logging.getLogger("rme_mapper.importers.presets")


class PresetsService:
    """Управление пользовательскими схемами сопоставления колонок."""

    def __init__(self, settings_service: AppSettingsService | None = None) -> None:
        self._settings = settings_service or AppSettingsService()

    def get_presets(self) -> list[ImportPreset]:
        """Получение списка всех сохраненных пресетов сопоставления."""
        raw_list = self._settings.get_import_presets()
        presets: list[ImportPreset] = []
        for item in raw_list:
            try:
                preset = ImportPreset(
                    name=item.get("name", ""),
                    coordinate_format=CoordinateFormat(item.get("coordinate_format", "auto")),
                    source_crs=item.get("source_crs", "EPSG:4326"),
                    column_mapping=dict(item.get("column_mapping", {})),
                    header_row=int(item.get("header_row", 1)),
                    delimiter=item.get("delimiter"),
                    encoding=item.get("encoding"),
                )
                if preset.name:
                    presets.append(preset)
            except Exception as e:
                logger.warning("Ошибка разбора пресета %s: %s", item, e)
        return presets

    def get_preset(self, name: str) -> ImportPreset | None:
        """Поиск пресета по имени."""
        for p in self.get_presets():
            if p.name == name:
                return p
        return None

    def save_preset(self, preset: ImportPreset) -> None:
        """Сохранение или обновление пресета."""
        data = {
            "name": preset.name,
            "coordinate_format": preset.coordinate_format.value,
            "source_crs": preset.source_crs,
            "column_mapping": preset.column_mapping,
            "header_row": preset.header_row,
            "delimiter": preset.delimiter,
            "encoding": preset.encoding,
        }
        self._settings.save_import_preset(preset.name, data)

    def delete_preset(self, name: str) -> bool:
        """Удаление пресета по имени."""
        return self._settings.delete_import_preset(name)
