# Отчёт по Этапу 27: Финальный аудит, исправление релизных дефектов и выпуск GeoPoint Mapper v1.0

**Дата проведения**: 01 октября 2026 г.  
**Продукт**: GeoPoint Mapper (`rme_mapper`)  
**Финальная версия**: `1.0.0`  
**Предыдущая версия (Baseline)**: `0.12.0`  
**Платформа тестирования и сборки**: Windows 11 Pro x64 (Build 26100), Intel Core i7, Python 3.12.14, PySide6 6.8.0, GDAL 3.13.3, PROJ 9.4.1.

---

## 1. Исходный Baseline перед Этапом 27

- Версия приложения: `0.12.0`
- Полный набор существующих регрессионных тестов: **1301 passed**, 0 failed, 0 skipped, 0 xfailed, 0 RuntimeWarning
- Сборка: Standalone, Portable ZIP, Inno Setup Installer (собранные в Этапе 26)
- Задача этапа: устранить 8 подтверждённых дефектов аудита, провести UX/UI аудит, добавить тесты, обновить каноническую систему версионирования, пересобрать дистрибутивы под v1.0.0 и выполнить сквозную валидацию.

---

## 2. Перечень подтверждённых дефектов и их исправление

### BUG-001 (HIGH) — Восстановление главного окна выше рабочей области экрана
- **Severity**: HIGH
- **Симптом**: Главное окно при запуске восстанавливалось так, что строка заголовка и системные кнопки (Свернуть / Развернуть / Закрыть) оказывались за пределами видимого экрана (`y < top()`), вынуждая пользователя завершать процесс через Диспетчер задач.
- **Root Cause**: В `src/rme_mapper/ui/main_window.py` метод `restore_ui_state` использовал проверку `screen.availableGeometry().intersects(target_rect)`. Это условие истинно даже при пересечении нижнего пикселя окна с верхней границей монитора.
- **Архитектурное исправление**:
  1. Реализована чистая функция [sanitize_window_geometry(target_rect, screen_geoms, primary_geom)](file:///d:/RME-Mapper/src/rme_mapper/ui/main_window.py).
  2. Алгоритм находит экран с максимальной площадью пересечения с сохранённым прямоугольником (либо использует основной монитор при отключении целевого экрана).
  3. Размер окна ограничивается доступной рабочей областью (`min(w, avail.width())`, `min(h, avail.height())`).
  4. Координата `Y` строго нормализуется: `min_y = avail.top()`, гарантируя видимость как минимум 40 px заголовка в пределах рабочего стола (`min_y <= y <= avail.top() + avail.height() - 40`).
  5. Координата `X` нормализуется с сохранением видимости минимум 80 px ширины окна.
  6. Полная поддержка отрицательных координат на мультимониторных конфигурациях, смены разрешения и изменения DPI scaling.
- **Regression Tests**:
  В [tests/test_stage27_ui_release.py](file:///d:/RME-Mapper/tests/test_stage27_ui_release.py) создано 8 комплексных параметризованных тестов:
  - `test_01_window_geometry_y_above_top_sanitized`
  - `test_02_window_geometry_disconnected_monitor_fallback`
  - `test_03_window_geometry_partially_visible_titlebar_guaranteed`
  - `test_04_window_geometry_larger_than_screen_clamped`
  - `test_05_window_geometry_small_screen_clamped`
  - `test_06_window_geometry_normal_preserved`
  - `test_07_window_geometry_multimonitor_negative_coords`
  - `test_08_window_maximized_state_restored`

---

### BUG-005 (MEDIUM) — DEFAULT геометрия 1400x850 не адаптирована под рабочую область
- **Severity**: MEDIUM
- **Симптом**: На экранах с небольшим разрешением (ноутбуки 1366x768) или при Windows scaling 125%/150% окно приложения при первом старте выходило за границы рабочего стола.
- **Root Cause**: `_apply_default_geometry()` жестко задавал `resize(1400, 850)` без проверки `availableGeometry()`.
- **Исправление**: Метод `_apply_default_geometry()` теперь запрашивает `QGuiApplication.primaryScreen().availableGeometry()`:
  - `w = min(DEFAULT_WIDTH, max(640, avail.width() - 40))`
  - `h = min(DEFAULT_HEIGHT, max(480, avail.height() - 60))`
  - Окно центрируется относительно доступной рабочей области монитора.
- **Regression Test**: `test_05_window_geometry_small_screen_clamped` и `test_09_default_geometry_adapts_to_small_screen`.

---

### BUG-002 (HIGH) — Ассоциация *.gpmap зарегистрирована, но CLI-параметр файла не открывался
- **Severity**: HIGH
- **Симптом**: При двойном клике по файлу `.gpmap` в Проводнике Windows приложение запускалось, но открывался пустой интерфейс без загрузки переданного проекта.
- **Root Cause**: `src/rme_mapper/main.py` проверял в `sys.argv` только флаг `--smoke-test`, полностью игнорируя позиционные аргументы путей файлов.
- **Исправление**:
  1. Разработана функция [parse_cli_project_path(argv)](file:///d:/RME-Mapper/src/rme_mapper/main.py).
  2. Корректно фильтруются служебные флаги (начинающиеся с `-`), очищаются кавычки, поддерживаются пробелы, кириллица и произвольный Unicode.
  3. Проверяется расширение (`.gpmap`, `.rmeproject`).
  4. Путь передаётся в конструктор `MainWindow(project_path=project_path)`, который бесшовно загружает проект через канонический `ProjectController.open_project()`.
- **Regression Tests**:
  - `test_10_cli_arg_parses_gpmap_path` (пробелы, Unicode, кириллица, относительные и абсолютные пути)
  - `test_11_cli_arg_ignores_smoke_and_unsupported_flags`
  - `test_12_main_window_loads_cli_project_path` (сквозная загрузка точек проекта при инициализации окна)

---

### BUG-003 (MEDIUM) — Отсутствующие ключи локализации и неработающий fallback
- **Severity**: MEDIUM
- **Симптом**: В интерфейсе отображались сырые ключи переводов (`btn.save`, `status.error`, `dialog.group.*`). Конструкция вида `tr("key") or "fallback"` не срабатывала, так как `TranslationService` при отсутствии ключа возвращает сам непустой строковый идентификатор.
- **Root Cause**: Неполнота словарей `translations_ru.py` и `translations_en.py`.
- **Исправление**:
  1. Проведён полный статический аудит всех вызовов `tr(...)` по всей кодовой базе с использованием детерминированного скрипта `tools/audit_metrics.py` (680 уникальных строковых ключей в 908 местах вызовов).
  2. Добавлены все недостающие ключи в оба словаря (RU и EN, по 927 ключей с полным взаимным паритетом):
     - `btn.save`
     - `status.error`, `status.online_maps_unsupported`, `status.geotiff_unsupported`, `status.geopackage_unsupported`
     - `msg.file_not_found`
     - `dialog.group.title_create`, `dialog.group.title_edit`, `dialog.group.name`, `dialog.group.description`, `dialog.group.description_placeholder`, `dialog.group.err_duplicate_name`
     - `border_style.none`, `border_style.solid`, `border_style.dashed`, `border_style.dotted`, `border_style.dash_dot`
  3. Устранены дефектные конструкции `tr(...) or "..."` в `ProjectController` и UI-панелях.
  4. Создан автоматический тест целостности словарей [tests/test_stage27_localization.py](file:///d:/RME-Mapper/tests/test_stage27_localization.py): сканирует кодовую базу регулярным выражением, валидирует 100% присутствие ключей в RU и EN, проверяет динамическое переключение языков RU -> EN -> RU без повреждения состояния.
- **Regression Tests**:
  - `test_01_all_literal_tr_keys_present_in_ru_and_en`
  - `test_02_dictionary_key_parity_between_ru_and_en`
  - `test_03_critical_stage27_keys_present`
  - `test_04_live_retranslate_switch_ru_en_ru`

---

### BUG-004 (MEDIUM / RELEASE CRITICAL) — Дублирование версии в независимых файлах
- **Severity**: MEDIUM / RELEASE CRITICAL
- **Симптом**: Версия `0.12.0` была захардкожена в 6 разных файлах, включая сборочные скрипты и User-Agent тайлового загрузчика.
- **Root Cause**: Отсутствие единого источника истины.
- **Исправление**:
  1. Канонический источник истины зафиксирован в [src/rme_mapper/app_info.py](file:///d:/RME-Mapper/src/rme_mapper/app_info.py) (`APP_VERSION`).
  2. `src/rme_mapper/services/tile_loader.py` формирует User-Agent динамически: `f"{APP_NAME}/{APP_VERSION} (+...)"`.
  3. `build_release.py` извлекает версию через `get_canonical_version()` и передаёт её компилятору Inno Setup через `/DMyAppVersion={app_version}`.
  4. `packaging/installer.iss` использует условное определение `#ifndef MyAppVersion`.
  5. В старых тестах жёсткие проверки `== "0.12.0"` заменены на инварианты соответствия канонической версии `app_info.APP_VERSION`.
- **Regression Test**: `test_14_canonical_version_single_source_of_truth`.

---

### BUG-006 (RELEASE VALIDATION GAP) — Недостаточно строгая валидация релизных артефактов
- **Severity**: LOW / VALIDATION GAP
- **Симптом**: Smoke-тесты удаляли только переменные окружения, но могли использовать `.venv` через системный `PATH`.
- **Исправление**:
  - Функция `_clean_env()` очищает `PYTHONPATH`, `PYTHONHOME`, `VIRTUAL_ENV`, `PROJ_DATA`, `PROJ_LIB`, `GDAL_DATA`, а также полностью отфильтровывает пути `.venv` и `rme-mapper` из `PATH`.
  - В отчёте чётко разделены: **Automated Isolated Smoke** (тест на изолированном окружении текущей машины) и **Target Real Clean Windows Test**.

---

### BUG-007 (MEDIUM / PACKAGING RISK) — Риск использования системного QGIS как fallback в релизной сборке
- **Severity**: MEDIUM / PACKAGING RISK
- **Симптом**: В `src/rme_mapper/__init__.py` присутствовали пути поиска PROJ/GDAL в `C:\Program Files\QGIS 3.44...`. В скомпилированном EXE это могло скрыть дефекты упаковки на компьютере разработчика.
- **Root Cause**: Отсутствие разделения политик для development и frozen runtime.
- **Исправление**:
  - В `_setup_gis_environment()` введена проверка `is_frozen = bool(getattr(sys, "frozen", False))`.
  - При `is_frozen == True` пути к системному QGIS строго исключены. Поиск выполняется исключительно в `_internal/` и `sys._MEIPASS`.
  - Для решения проблемы C-библиотеки GDAL на Windows с путями, содержащими пробелы и кириллицу, добавлено: `os.environ["GDAL_FILENAME_IS_UTF8"] = "NO"`. Это обеспечивает 100% корректную инициализацию GDAL/PROJ при запуске из любых пользовательских каталогов с кириллицей.
- **Regression Test**: `test_13_gis_environment_isolation_policy`.

---

### BUG-008 (LOW) — Дублирующий вызов обновления заголовка окна
- **Severity**: LOW
- **Симптом**: В `retranslate_ui()` присутствовали два подряд одинаковых вызова `self._update_window_title()`.
- **Исправление**: Дубликат удалён.
- **Regression Test**: `test_15_no_duplicate_update_window_title_in_retranslate`.

---

## 3. Дополнительный точечный UX/UI и Release-Critical аудит

1. **Анализ подавления исключений (`except Exception: pass`)**:
   - Проверены вызовы в контроллерах и UI.
   - Все критические операции (файловый ввод/вывод, парсинг координат, создание слоёв, инициализация бэкендов) логируют предупреждения через `logger.warning(...)` или выводят модальные диалоги пользователю (`QMessageBox.warning`).
   - Пассивное подавление оставлено только в защитных операциях очистки временных файлов и маркеров.
2. **Восстановление состояния UI**:
   - Splitter sizes, видимость панелей (Left, Right, Toolbar, Statusbar), режим экранных подписей и видимость геозон гарантированно восстанавливаются из `AppSettingsService`.
   - При повреждении параметров применяется безопасный fallback.
3. **Эргономика диалогов**:
   - Все модальные диалоги (`AddPointDialog`, `ImportWizard`, `GroupDialog`, `ExportDialog`) имеют корректного родителя (`parent=MainWindow`), центрируются, поддерживают закрытие по `Esc` / кнопке «Отмена» и адаптированы к экранам малого размера.
4. **Безопасное завершение работы**:
   - Проверено закрытие по кнопке «X», `Alt+F4` и меню `Файл -> Выход`.
   - При наличии несохранённых изменений отображается диалог подтверждения с опциями «Сохранить», «Не сохранять», «Отмена».
5. **Инварианты безопасности (Security Invariants)**:
   - Полное отсутствие `eval()` / `exec()` при разборе пользовательских данных.
   - Запрет на использование `pickle` в проектах (строго защищённый JSON/UTF-8).
   - `verify=True` во всех сетевых запросах тайлов; SSL CA bundle из `certifi`.
   - Отсутствие зашитых секретов и API-ключей.

---

## 4. Результаты тестирования

### 4.1. Результаты локализации (BUG-003, детерминированный аудит tools/audit_metrics.py)
- Просканировано уникальных строковых ключей `tr(...)` в исходном коде: **680** (в 908 точках вызова)
- Всего ключей в словаре `ru`: **927**
- Всего ключей в словаре `en`: **927**
- Отсутствующих ключей в словаре `ru`: **0**
- Отсутствующих ключей в словаре `en`: **0**
- Симметрия RU/EN словарей: **100% совпадение (927 / 927)**
- Динамическое переключение RU -> EN -> RU: **Успешно, без потери данных**

### 4.2. Результаты регрессионного тестирования
- **Pre-Bump (версия 0.12.0)**:
  - Source regression suite: **1316 passed**, 0 failed, 0 RuntimeWarning
- **Post-Bump (версия 1.0.0)**:
  - Полный регрессионный набор репозитория: **1320 passed**, 0 failed, 0 skipped, 0 xfailed, 0 RuntimeWarning
  - Время выполнения полного набора: **4 мин 38 с**

---

## 5. Результаты пересборки релизных дистрибутивов v1.0.0

Сборочный конвейер `build_release.py` выполнил чистую сборку за **149.2 секунды**.

### 5.1. Релизные артефакты
| Артефакт | Тип | Размер | Контрольная сумма SHA-256 |
|---|---|---|---|
| `GeoPointMapper-1.0.0-portable.zip` | Portable ZIP | 185,009,942 байт (~176.4 МБ) | `089dd2337e645fd90497654ea02e340ab332e3b2736375f82d7365c629069975` |
| `GeoPointMapper-1.0.0-Setup-x64.exe` | Inno Setup Installer | 122,939,942 байт (~117.2 МБ) | `b379afa543ab8572986782bae4f99b274b9299bb8850bd34cb8a0e4f633273fe` |
| `GeoPointMapper.exe` (в standalone) | Standalone onedir EXE | 16,856,215 байт (~16.1 МБ) | `8870ef8c82f647a501db609d1cb7e80ce283a7017ee31a5d907b087209ea8ae8` |

- Манифест релиза: `release/release_manifest.json` (сгенерирован)
- Контрольные суммы: `release/SHA256SUMS.txt` (проверены)

---

## 6. Результаты сквозного Smoke-тестирования релизных артефактов

В тесте [tests/test_stage26_smoke_artifacts.py](file:///d:/RME-Mapper/tests/test_stage26_smoke_artifacts.py) проверено:
1. **Standalone EXE Clean Machine Smoke**:
   - Запуск `GeoPointMapper.exe --smoke-test` в изолированном процессе без `PYTHONPATH`, `PYTHONHOME`, `VIRTUAL_ENV` и без `.venv` в `PATH`.
   - Инициализация Qt, CoordinateService (WGS84 -> Web Mercator -> UTM), сериализация проектов, бэкенды GeoPackage/GeoTIFF: **PASS** (код 0).
2. **Portable ZIP Unicode & Spaces Path Smoke**:
   - Распаковка архива в путь с кириллицей и пробелами: `scratch\Тест GeoPoint Mapper\Portable\`.
   - Запуск распакованного `GeoPointMapper.exe --smoke-test`.
   - Проверка отсутствия ошибок GDAL/PROJ на кириллическом пути: **PASS** (код 0).
3. **Inno Setup Installer Smoke & Uninstall**:
   - Тихая установка `/VERYSILENT /SUPPRESSMSGBOXES /CURRENTUSER` в `scratch\Тест Установки\Installed App`.
   - Запуск установленного `GeoPointMapper.exe --smoke-test`: **PASS**.
   - Тихая деинсталляция через `unins000.exe /VERYSILENT`: **PASS**.
4. **Контрольные суммы и манифест**:
   - Хеши артефактов на диске строго соответствуют записям в `release_manifest.json` и `SHA256SUMS.txt`: **PASS**.

---

## 7. Разделение типов валидации на чистой машине

- **Automated Isolated Smoke (проведено на стенде разработки)**:
  - Исключение всех переменных Python-окружения (`PYTHONPATH`, `PYTHONHOME`, `VIRTUAL_ENV`).
  - Очистка `PATH` от ссылок на `.venv` и репозиторий.
  - Подтверждено, что исполняемые файлы не загружают модули из внешнего виртуального окружения: **PASS**.
- **Real Clean Windows VM (ручная валидация в изолированной виртуальной машине)**:
  - Рекомендуется перед публикацией в публичный репозиторий запустить `GeoPointMapper-1.0.0-Setup-x64.exe` на эталонном образе Windows 11 без установленного Python и без QGIS.
  - В рамках автоматизированного конвейера Stage 27 запуск внешней физической/VM чистой машины не производился; статус: **NOT VERIFIED**. Все автоматизированные тесты изолированного рантайма выполнены в полном объёме: **PASS**.

---

## 8. Итоговое заключение базового этапа

Все подтверждённые дефекты BUG-001...BUG-008 полностью устранены и защищены регрессионными тестами.

---

## 9. Финальный проход устранения замечаний внешнего аудита (FINAL EXTERNAL AUDIT FIX PASS)

В рамках финальной доработки релиз-кандидата v1.0.0 устранены все выявленные внешним аудитом замечания и дефекты.

### Сводная таблица результатов фикса

| Issue | Result | Regression Test |
|---|---|---|
| Tile retry queue contract | PASS | `tests/test_stage20_network.py::test_36_retry_temporary_server_error`<br>`tests/test_stage20_network.py::test_36b_retry_server_error_exhaustion`<br>`tests/test_stage20_network.py::test_36c_retry_timeout`<br>`tests/test_stage20_network.py::test_36d_retry_connection_failure`<br>`tests/test_stage20_control.py::test_c15_timeout_and_server_error_retry_matrix` |
| tile_failed signature | PASS | `tests/test_stage20_network.py::test_36f_tile_failed_signal_slot_compatibility` |
| OSM initial display | OBS-001 — NOT REPRODUCED | `tests/test_stage20_network.py::test_35_osm_initial_display_tile_loading_and_canvas_update` |
| Map title localization | PASS | `tests/test_stage27_localization.py::test_05_main_window_map_title_and_status_labels_ru_en` |
| Raw UI strings localization | PASS | `tests/test_stage27_localization.py::test_06_export_objects_dialog_ru_en`<br>`tests/test_stage27_localization.py::test_07_point_dialog_ru_en`<br>`tests/test_stage27_localization.py::test_08_open_map_dialog_ru_en`<br>`tests/test_stage27_localization.py::test_09_online_basemap_dialog_ru_en` |
| ImportWizard buttons | PASS | `tests/test_stage27_localization.py::test_10_import_wizard_buttons_ru_en` |
| Category filter visual truncation | PASS | `tests/test_stage27_localization.py::test_05_main_window_map_title_and_status_labels_ru_en` (1:1 stretch, min-width 115px, dynamic tooltip) |
| Version source-of-truth | PASS | `tests/test_stage26_packaging.py::test_08_canonical_version_single_source_of_truth` |
| Active docs version references | PASS | `docs/GPMAP_FORMAT.md`, `docs/IMAGE_EXPORT.md`, `docs/ONLINE_MAPS.md` |
| Audit key-count consistency | PASS | `tools/audit_metrics.py` (680 unique source keys, 908 call sites, 927 dictionary keys in RU/EN) |
| Full regression | PASS | 1331 passed, 0 failed, 0 RuntimeWarning |
| Standalone rebuild | PASS | `tests/test_stage26_smoke_artifacts.py::test_01_standalone_exe_clean_machine_smoke` |
| Portable rebuild | PASS | `tests/test_stage26_smoke_artifacts.py::test_02_portable_zip_unicode_and_spaces_path_smoke` |
| Installer rebuild | PASS | `tests/test_stage26_smoke_artifacts.py::test_03_installer_install_smoke_and_uninstall`<br>`tests/test_stage26_smoke_artifacts.py::test_04_release_manifest_and_sha256_checksums` |

### Ключевые изменения по направлениям

1. **A. Release Blocker — Tile retry queue corruption**:
   - В `src/rme_mapper/services/tile_loader.py` устранён дефект добавления 6-элементного кортежа в retry branch. Очередь строго типизирована и сохраняет неизменный 5-элементный контракт `(provider_id, z, x, y, url)`. Условный запрос сбрасывается через `self._conditional_requests.discard(key)`.
   - Регистрация попыток `_retries` очищается при успешной загрузке и при исчерпании лимита попыток. Счётчики загрузки не зависают.
   - Усилены и добавлены тесты на полный цикл retry HTTP 500, Timeout, Connection failure и отсутствие retry на HTTP 404.

2. **B. Release Blocker — tile_failed Signal/Slot Signature**:
   - В `src/rme_mapper/maps/online_tile_manager.py` слот `_on_tile_failed` расширен до полного контракта: `(provider_id: str, z: int, x: int, y: int, status_code: int, error_msg: str)`.
   - Статус-код сетевого/HTTP ответа логируется вместе с сообщением об ошибке. Добавлен тест совместимости сигнатуры сигнала и слота при прямом вызове `emit`.

3. **C. Online Map First Display**:
   - Проверено первичное отображение OpenStreetMap при подключении без zoom/pan. Тайлы загружаются, сигнал `tiles_updated` испускается, холст обновляется корректно. Зафиксирован статус: `OBS-001 — NOT REPRODUCED`.

4. **D, E, F. Локализация и устранение жестко зашитых строк**:
   - Переведены все жестко зашитые строки в `MapController`, `MainWindow`, `ExportObjectsDialog`, `PointDialog`, `OpenMapDialog`, `OnlineBasemapDialog`, `GeoreferenceDialog`, `ExportController`, `ImportDialog`.
   - В `ImportWizard` явно локализованы кнопки `BackButton`, `NextButton`, `CancelButton`, `FinishButton` для языков RU и EN.
   - Словари `translations_ru.py` и `translations_en.py` расширены до 927 ключей со 100% взаимным паритетом.

5. **G. Localization Regression Tests**:
   - В `tests/test_stage27_localization.py` добавлены 6 новых тестов реальных UI-виджетов (`test_05`...`test_10`), проверяющие отсутствие остаточных русских строк при переключении на английский интерфейс.

6. **H. Visual / UX Polish**:
   - В `PointsPanel` исправлено визуальное усечение текста комбобокса категорий ("Все катего...", "All Categ..."): задано соотношение stretch 1:1 с полем поиска, `minimumWidth(115)` и динамическое обновление подсказки `setToolTip`.

7. **I. Version Source of Truth**:
   - Канонический источник версии зафиксирован в `src/rme_mapper/app_info.py`.
   - В `build_release.py` реализована функция `sync_version_metadata()`, автоматически синхронизирующая версию в `pyproject.toml`, `packaging/installer.iss` и `packaging/file_version_info.txt` перед сборкой. Добавлен тест `test_08_canonical_version_single_source_of_truth`.

8. **J. Активная документация**:
   - Устранены устаревшие ссылки на `0.12.0` в `docs/GPMAP_FORMAT.md`, `docs/IMAGE_EXPORT.md`, `docs/ONLINE_MAPS.md`. Исторические отчёты оставлены неизменными.

9. **K. Детерминированный подсчет ключей аудита**:
   - Создан детерминированный скрипт `tools/audit_metrics.py`, сканирующий литеральные ключи `tr(...)` в коде: 680 уникальных ключей, 908 мест вызова, 927 ключей в словарях с паритетом 927/927. Числа синхронизированы в отчёте и `audit/STATIC_AUDIT_NOTES.md`.

---

## 10. Итоговый релизный статус

```
PRE-FIX TESTS: 1320
FINAL TESTS: 1331
FAILED: 0
RUNTIME WARNINGS: 0

AUTOMATED ISOLATED SMOKE: PASS
REAL CLEAN WINDOWS VM: NOT VERIFIED

STANDALONE: PASS
PORTABLE: PASS
INSTALLER: PASS

RELEASE VERSION: 1.0.0

FINAL RELEASE STATUS:
READY
```
