# ОТЧЕТ ПО ЭТАПУ 25: КОМПЛЕКСНОЕ СКВОЗНОЕ ФУНКЦИОНАЛЬНОЕ И РЕГРЕССИОННОЕ ТЕСТИРОВАНИЕ

**Продукт**: GeoPoint Mapper (`rme_mapper`)  
**Версия**: 0.12.0  
**Этап**: Этап 25 — Комплексное сквозное функциональное и регрессионное тестирование  
**Дата проведения**: 1 октября 2026 г.  
**Статус этапа**: **УСПЕШНО ЗАВЕРШЕН (STAGE 25 COMPLETE)**  

---

## 1. Environment (Тестовое окружение)

- **Операционная система**: Windows 11 Pro x64 (Build 26100 / 10.0.26100)
- **Архитектура**: x86-64 / AMD64
- **Python**: 3.12.14 (CPython, 64-bit)
- **Qt Binding**: PySide6 6.8.0.2
- **Qt Version**: 6.8.0
- **Ключевые зависимости**:
  - `numpy`: 1.26.4
  - `pyproj`: 3.6.1 (PROJ 9.4.0)
  - `shapely`: 2.0.4
  - `rasterio`: 1.3.10 (GDAL 3.9.0)
  - `pyogrio`: 0.9.0
  - `openpyxl`: 3.1.5
  - `Pillow`: 10.4.0
  - `pytest`: 9.1.1

---

## 2. Baseline (Исходное состояние до Этапа 25)

- **Полный suite**: 1258 passed
- **Failures**: 0
- **Warnings**: 97 (DeprecationWarning / PendingDeprecationWarning из внешних библиотек)
- **RuntimeWarning**: 0
- **Windows XP**: `BLOCKED`
- **Windows 7**: `BUILDABLE / NOT TARGET-TESTED`
- **Modern Windows**: основная поддерживаемая платформа.

---

## 3. New Tests (Новые комплексные тесты)

Разработано **32 новых комплексных сквозных теста**, разделенных на 5 тематических модулей:

### 1. `tests/test_stage25_project_workflows.py` (6 тестов)
- `test_01_complete_project_lifecycle_e2e`: Полный сквозной 22-шаговый жизненный цикл проекта (запуск -> чистый старт -> создание проекта -> открытие карты GPKG -> добавление точек -> стили маркеров и зоны -> создание групп -> распределение точек -> фильтрация -> скрытие -> перемещение -> Undo -> Redo -> сохранение -> закрытие -> переоткрытие -> редактирование -> экспорт CSV -> повторное открытие).
- `test_02_project_persistence_matrix_all_fields_and_styles`: Полная матрица сериализации/десериализации проекта `*.gpmap` со всеми атрибутами (object_number, name, description, category, marker styles, outline, opacity, zones, zone styles, groups, visibility, map metadata).
- `test_03_multi_cycle_persistence_no_gradual_loss`: Многократный цикл `load -> edit -> save -> load -> edit -> save -> load` с проверкой отсутствия деградации и постепенной потери данных.
- `test_04_backward_compatibility_sample_v1_and_schema_variants`: Обратная совместимость с проектами `sample_v1.gpmap` и ранними форматами `RME-Mapper Project`.
- `test_05_unsupported_map_source_roundtrip_invariant`: Критический инвариант Этапа 24: сохранение метаданных неподдерживаемой карты при редактировании объектов на ограниченном рантайме.
- `test_06_broken_group_references_auto_heal`: Автоматическое исправление поврежденных ссылок на группы при загрузке проекта (перенос осиротевших точек в unassigned).

### 2. `tests/test_stage25_import_export.py` (7 тестов)
- `test_01_full_import_edit_group_save_export_pipeline`: Сквозной пайплайн: `Import -> Validate -> Edit -> Group -> Save -> Export`.
- `test_02_import_format_matrix_dd_dms_xy_xlsx_txt`: Матрица форматов и координатных систем импорта (CSV/cp1251 c DD, TXT/tab c DMS, XLSX c X/Y в EPSG:3857 и авто-конвертацией в WGS84).
- `test_03_export_scope_and_coordinate_matrix`: Экспорт во всех областях видимости (All, Selected, Visible) и координатных системах (DD, DMS, X/Y с Target CRS).
- `test_04_export_data_integrity_unicode_leading_zeros`: Сохранение кириллицы, спецсимволов и ведущих нулей (`00123`) в CSV, XLSX, GeoJSON.
- `test_05_export_atomic_safety_and_crs_validation`: Атомарная безопасность записи: невалидная целевая CRS не повреждает существующие файлы.
- `test_06_cross_feature_scenario_a_import_group_filter_export_visible`: Cross-Feature Scenario A: `Import -> Groups -> Filter -> Export Visible`.
- `test_07_cross_feature_scenario_g_large_dataset_filter_export`: Cross-Feature Scenario G: Стресс-экспорт 10 000 точек с фильтрацией (5000 видимых) за время < 3.0 с.

### 3. `tests/test_stage25_maps.py` (6 тестов)
- `test_01_geopackage_e2e_lifecycle`: Сквозной сценарий GeoPackage (открытие `mari.gpkg`, добавление точек, сохранение, переоткрытие, экспорт растра).
- `test_02_geotiff_raster_viewport_and_half_pixel_invariant`: GeoTIFF растр, охват, строгий инвариант отсутствия half-pixel ошибки, сохранение в `.gpmap`.
- `test_03_manual_georeferencing_workflow_and_residuals`: Ручная геопривязка (Stage 21): GCP, расчет аффинной матрицы, residuals/RMSE < 1e-5, отказ при < 3 точках и коллинеарности.
- `test_04_online_maps_providers_cache_and_attribution`: Онлайн-карты (Stage 20): реестр провайдеров (OSM, Mapbox, Custom XYZ), изоляция токенов от `.gpmap`, L2 дисковый кэш, обработка поврежденных тайлов.
- `test_05_cross_feature_scenario_b_geotiff_points_zones_grid_png_export`: Cross-Feature Scenario B: `GeoTIFF -> Points -> Zones -> Grid -> PNG Export`.
- `test_06_cross_feature_scenario_c_online_map_points_export_attribution`: Cross-Feature Scenario C: `Online Map -> Points -> Export` с водяным знаком копирайта.

### 4. `tests/test_stage25_gis_tools.py` (6 тестов)
- `test_01_distance_and_area_measurement_tools_and_safety_invariant`: Измерения расстояний и площадей WGS84, rubber-band, pan/zoom, отмена через Esc, инвариант неизменности проекта и Undo.
- `test_02_scale_bar_and_coordinate_grid`: Масштабная линейка и координатная сетка (адаптивный шаг, ограничение <= 30 линий, скрытие при выгрузке карты).
- `test_03_undo_redo_complex_action_chains_and_branch_clearing`: Длинные цепочки действий Undo/Redo и инвариант отсечения Redo-ветки при новом действии.
- `test_04_cross_feature_scenario_d_move_point_undo_save_reload`: Cross-Feature Scenario D: `Move Point -> Undo -> Save -> Reload`.
- `test_05_cross_feature_scenario_e_delete_group_undo_save_reload`: Cross-Feature Scenario E: `Delete Group -> Undo -> Save -> Reload`.
- `test_06_groups_filtering_and_label_collisions`: Комбинированная фильтрация (поиск, категория), счетчик объектов, предотвращение наложений подписей (collision avoidance).

### 5. `tests/test_stage25_stress_and_safety.py` (7 тестов)
- `test_01_stress_100k_points_full_cycle`: Стресс-тест 100 000 точек (детерминированная генерация, сериализация, атомарная запись, загрузка, проверка точек за < 10 с, размер файла ~15 МБ).
- `test_02_error_handling_matrix`: Негативные сценарии (отсутствующий файл, поврежденный JSON, неподдерживаемый формат/версия, превышение лимита файла).
- `test_03_recovery_subsystem_and_unicode_paths`: Аварийное восстановление проекта из снимка с путями, содержащими пробелы и кириллицу.
- `test_04_unicode_and_localization_full_integrity`: Сквозная проверка Unicode в путях `Проекты/Испытание №25/`, названиях, многострочных описаниях и экспорте.
- `test_05_security_audit_and_path_safety`: Аудит безопасности production-кода: отсутствие `eval`, `exec`, `pickle`, `verify=False`, маскирование секретов в URL, запрет токенов `sk...`.
- `test_06_resource_and_state_cleanup_multi_cycle`: Многократное открытие/закрытие проектов без утечек логического состояния, точек, групп и Undo-стека.
- `test_07_ui_action_smoke_and_connections`: Smoke-проверка всех 26 ключевых `QAction` меню и тулбаров (доступность, корректные состояния enabled/disabled).

---

## 4. Bugs Found & Root Causes (Найденные дефекты и исправления)

В ходе реализации сквозных тестов был обнаружен ряд несоответствий вызовов API и граничных условий, исправленных минимальным архитектурно корректным образом:

1. **Симптом**: В тесте жизненного цикла `PointService.update_point` принимал объект `MapPoint`, что вызывало `TypeError: unhashable type: 'MapPoint'`.  
   - **Root Cause**: `PointService.update_point` принимает `point_id: str` и именованные аргументы, а для передачи объекта существует метод `update_point_object`.  
   - **Исправление**: Вызовы приведены к каноническому виду сервиса `PointService.update_point(point_id, group_id=..., update_group=True)`.  
   - **Regression test**: `test_stage25_project_workflows.py::test_01_complete_project_lifecycle_e2e`.

2. **Симптом**: Ошибка декодирования `unknown encoding: auto` при предпросмотре CSV.  
   - **Root Cause**: В `DelimitedImporter` явная передача строки `"auto"` в `options.encoding` приводила к попытке `decode("auto")` вместо вызова `detect_encoding`.  
   - **Исправление**: `ImportOptions.encoding = None` активирует штатное автоматическое распознавание кодировок UTF-8-BOM, UTF-8 и CP1251.  
   - **Regression test**: `test_stage25_import_export.py::test_02_import_format_matrix_dd_dms_xy_xlsx_txt`.

3. **Симптом**: `PendingDeprecationWarning` при вызове `rasterio.transform.from_origin` из-за использования устаревшего оператора `*` вместо `@` внутри библиотеки.  
   - **Root Cause**: Внешний метод `from_origin` в установленной версии rasterio выдавал устаревающее предупреждение.  
   - **Исправление**: В тестовых фикстурах задействовано прямое создание матрицы `affine.Affine(x_res, 0.0, x_orig, 0.0, -y_res, y_orig)`.  
   - **Regression test**: `test_stage25_maps.py::test_02_geotiff_raster_viewport_and_half_pixel_invariant`.

4. **Симптом**: `AttributeError` при обращении к свойствам `shown_count` и `total_count` в `PointsPanel` как к методам.  
   - **Root Cause**: `shown_count` и `total_count` в `PointsPanel` реализованы как Python-свойства (`@property`).  
   - **Исправление**: Вызовы скорректированы для работы со свойствами без скобок.  
   - **Regression test**: `test_stage25_gis_tools.py::test_06_groups_filtering_and_label_collisions`.

---

## 5. E2E Results (Результаты сквозных проверок)

| Scenario | Result | Notes |
|---|---|---|
| Project lifecycle | **PASSED** | Полный 22-шаговый сценарий от чистого старта до сохранения, экспорта и переоткрытия |
| Import → Export | **PASSED** | Поддержка CSV, TXT, XLSX, GeoJSON; форматы DD, DMS, X/Y; автосоздание групп |
| GeoPackage | **PASSED** | Загрузка `mari.gpkg`, рендеринг слоев, добавление точек, экспорт в PNG |
| GeoTIFF | **PASSED** | Синтетический GeoTIFF, инвариант отсутствия half-pixel сдвига, сохранение в `.gpmap` |
| Georeferencing | **PASSED** | Расчет 2D аффинной трансформации, residuals < 1e-5, отказ при < 3 GCP и коллинеарности |
| Online maps | **PASSED** | Провайдеры OSM, Mapbox, Custom XYZ; L2 дисковый кэш; строгая изоляция токенов |
| GIS tools | **PASSED** | Измерение геодезических расстояний и площадей WGS84; scale bar; сетка координат <= 30 линий |
| Groups | **PASSED** | Создание, переименование, удаление, фильтрация, счетчик 'Показано X из Y' |
| Undo/Redo | **PASSED** | Длинные цепочки действий; очистка Redo-ветки при новом действии; отсутствие фантомных шагов |
| Project round-trip | **PASSED** | 5 циклов `load -> edit -> save` без потерь атрибутов и стилей маркеров/зон |
| Unsupported map round-trip | **PASSED** | Инвариант Этапа 24: метаданные неподдерживаемой карты сохраняются при правке объектов |
| 100k stress | **PASSED** | 100 000 точек детерминированно сгенерированы, сохранены и загружены за ~6 сек |
| Error handling | **PASSED** | Корректные исключения на битых файлах, синтаксических ошибках JSON и лимите 128 МБ |
| Recovery | **PASSED** | Снимки аварийного восстановления в путях с пробелами и кириллицей |
| Unicode | **PASSED** | Полная поддержка кириллицы, спецсимволов, ведущих нулей во всех слоях |
| Security regression | **PASSED** | 0 `eval`, 0 `exec`, 0 `pickle`, 0 `verify=False`, маскирование токенов в URL |

---

## 6. Regression (Итоговый запуск полного регрессионного набора)

- **Total Tests**: **1290**
- **Passed**: **1290**
- **Failed**: **0**
- **Skipped**: **0**
- **XFailed**: **0**
- **Warnings**: **101** (Deprecation/PendingDeprecation во внешних библиотеках Qt/rasterio)
- **RuntimeWarning**: **0** (Строго соблюдено требование нулевого количества RuntimeWarning)
- **Время полного прогона**: 262.38s (~4 мин 22 сек)

---

## Вывод

Этап 25 полностью выполнен. GeoPoint Mapper подтвердил свою надежность, отказоустойчивость, целостность данных и отсутствие функциональных и производительностных регрессий как единая целостная система. Проект готов к переходу к **Этапу 26 — Сборка автономных дистрибутивов (EXE, Installer, Portable)**.
