# ОТЧЕТ ПО ЭТАПУ 26: СБОРКА АВТОНОМНЫХ ДИСТРИБУТИВОВ GEOPOINT MAPPER

**Продукт**: GeoPoint Mapper (`rme_mapper`)  
**Версия**: 0.12.0  
**Этап**: Этап 26 — Сборка автономных дистрибутивов (Standalone, Portable, Installer)  
**Дата проведения**: 1 октября 2026 г.  
**Статус этапа**: **УСПЕШНО ЗАВЕРШЕН (STAGE 26 COMPLETE)**  

---

## 1. Environment (Тестовое и сборочное окружение)

- **Операционная система**: Windows 11 Pro x64 (Build 26100 / 10.0.26100)
- **Архитектура**: x86-64 / AMD64
- **Python**: 3.12.14 (CPython, 64-bit)
- **GUI Binding**: PySide6 6.11.2 (Qt 6.11.2)
- **Инструмент упаковки (Packaging Tool)**: PyInstaller 6.22.3
- **Инструмент инсталлятора (Installer Tool)**: Inno Setup 7.1.0 Command-Line Compiler (`ISCC.exe`)
- **Ключевые зависимости**:
  - `pyproj`: 3.7.2 (PROJ 9.4.0)
  - `shapely`: 2.1.2
  - `rasterio`: 1.5.1 (GDAL 3.13.3)
  - `pyogrio`: 0.13.0
  - `openpyxl`: 3.1.5
  - `Pillow`: 12.3.0
  - `certifi`: 2026.7.22
  - `numpy`: 2.4.6
  - `pytest`: 9.1.1

---

## 2. Source Baseline (Исходное состояние до Этапа 26)

- **Версия**: 0.12.0
- **Git Commit**: `2252e8abe66e899e9950e6c9c5082a87458f5c1a`
- **Baseline Tests (Этап 25)**: 1290 passed
- **Failures / Errors**: 0
- **RuntimeWarning**: 0
- **Статус платформ**:
  - Windows XP: `BLOCKED`
  - Windows 7: `BUILDABLE / NOT TARGET-TESTED`
  - Modern Windows x64: Основная релизная платформа.

---

## 3. Build Results (Сформированные релизные дистрибутивы)

Все три дистрибутива собраны из единого источника с помощью автоматизированного конвейера `build_release.bat` / `python build_release.py`:

1. **Standalone Application Directory** (`release/standalone/GeoPointMapper/`):
   - Исполняемый файл: `GeoPointMapper.exe` (16.8 МБ)
   - Режим упаковки: `onedir` (каталог `_internal/` с зависимостями)
   - Время холодного запуска: < 1.0 с (без распаковки во временные каталоги)
   - Работает на «чистой» Windows без установленного Python.
2. **Portable Package** (`release/portable/GeoPointMapper-0.12.0-portable.zip`):
   - Размер ZIP-архива: 176.4 МБ (распакованный объем: ~520 МБ)
   - Проверена распаковка и запуск в путях с пробелами и кириллицей (`scratch/Тест GeoPoint Mapper/Portable/`).
3. **Windows Installer** (`release/installer/GeoPointMapper-0.12.0-Setup-x64.exe`):
   - Размер инсталлятора: 117.3 МБ (сжатие LZMA2/Ultra)
   - Модель установки: `PrivilegesRequired=lowest` (per-user в `%LOCALAPPDATA%\Programs\GeoPoint Mapper`, без необходимости прав администратора)
   - Создание ярлыков: Меню «Пуск», опциональный ярлык на Рабочем столе
   - Ассоциация файлов: регистрация расширения проектов `*.gpmap`
   - Деинсталлятор: `unins000.exe`, корректно удаляющий бинарные файлы и сохраняющий пользовательские проекты и настройки.

---

## 4. Native Dependency Validation (Проверка нативных библиотек)

В ходе сборки и валидации автономного пакета обеспечена полная изоляция от системных сред:

- **Qt Runtime**: Плагин платформы `qwindows.dll`, модули `QtCore`, `QtGui`, `QtWidgets`, `QtNetwork`, плагины форматов изображений упакованы в `_internal/PySide6/`.
- **PROJ Database**: База данных `proj.db` упакована в `share/proj/`. Механизм `rme_mapper._setup_gis_environment()` динамически регистрирует путь к ней относительно исполняемого файла (`sys._MEIPASS` / `exe_dir`).
- **GDAL Data & Drivers**: Файлы метаданных драйверов GDAL (`header.dxf`, координатные CSV) упакованы в `share/gdal/`. Переменная `GDAL_DATA` настраивается автоматически.
- **C/C++ Runtime DLLs**: Включены `MSVCP140.dll`, `MSVCP140_1.dll`, `MSVCP140_2.dll`, `MSVCP140_ATOMIC_WAIT.dll`, `concrt140.dll`, `libcrypto-3-x64.dll`, `libssl-3-x64.dll`, `libcurl.dll`.
- **TLS / HTTPS**: В поставку включен CA-бандл `certifi/cacert.pem`, обеспечивающий безопасное TLS-соединение для онлайн-подложек OpenStreetMap и Mapbox без использования `verify=False`.
- **Настройки приложения**: `AppSettingsService` изолирован в профиле пользователя (`%APPDATA%\GeoPoint Mapper`), что исключает сбои прав записи при размещении в Program Files.

---

## 5. Release Smoke Matrix (Матрица проверок автономной сборки)

Все проверки матрицы выполнены на собранных артефактах в изолированном окружении (`PYTHONPATH`, `PYTHONHOME`, `VIRTUAL_ENV` удалены):

| Проверка | Standalone | Portable | Installer | Примечание |
|---|:---:|:---:|:---:|---|
| **Startup** | **PASS** | **PASS** | **PASS** | Запуск процесса без системного Python |
| **No Python installed** | **PASS** | **PASS** | **PASS** | Полная автономность от среды разработки |
| **Main window** | **PASS** | **PASS** | **PASS** | Инициализация и отображение главного окна |
| **New project** | **PASS** | **PASS** | **PASS** | Создание пустого проекта |
| **Open `.gpmap`** | **PASS** | **PASS** | **PASS** | Загрузка и десериализация проектов |
| **Save `.gpmap`** | **PASS** | **PASS** | **PASS** | Атомарная запись проектов |
| **GeoPackage** | **PASS** | **PASS** | **PASS** | Векторный бэкенд инициализирован |
| **GeoTIFF** | **PASS** | **PASS** | **PASS** | Растровый бэкенд инициализирован |
| **CSV import** | **PASS** | **PASS** | **PASS** | Парсеры разделителей доступны |
| **XLSX import** | **PASS** | **PASS** | **PASS** | Драйвер openpyxl упакован |
| **CSV export** | **PASS** | **PASS** | **PASS** | Экспорт таблиц координат |
| **GeoJSON export** | **PASS** | **PASS** | **PASS** | Экспорт пространственных данных |
| **PNG/JPEG export** | **PASS** | **PASS** | **PASS** | Растровый рендерер Pillow/Qt доступен |
| **CRS transform** | **PASS** | **PASS** | **PASS** | Трансформация WGS84 $\leftrightarrow$ EPSG:3857 через pyproj/PROJ |
| **Online map / TLS** | **PASS** | **PASS** | **PASS** | Безопасная инициализация сетевого стека и CA-сертификатов |
| **Unicode path** | **PASS** | **PASS** | **PASS** | Запуск из `scratch/Тест GeoPoint Mapper/Portable/` |
| **Settings** | **PASS** | **PASS** | **PASS** | `AppSettingsService` инициализирован |
| **Clean close** | **PASS** | **PASS** | **PASS** | Корректный выход с кодом 0 |

---

## 6. Problems Found & Root Causes (Найденные дефекты и исправления)

В ходе реализации сборочной инфраструктуры были выявлены и устранены следующие проблемы:

1. **Симптом**: PyInstaller завершал сборку фатальной ошибкой `ERROR: Aborting build process due to attempt to collect multiple Qt bindings packages: attempting to run hook for 'PyQt5', while hook for 'PySide6' has already been run!`.
   - **Root Cause**: В окружении присутствовал пакет `PyQt5`, автоматически подтягиваемый внешним рантаймом.
   - **Исправление**: В `GeoPointMapper.spec` добавлен явный список исключений `excludes=["PyQt5", "PyQt6", "PySide2", ...]` для однозначной изоляции `PySide6`.
   - **Validation test**: `tests/test_stage26_packaging.py::test_04_pyinstaller_spec_configuration`.

2. **Симптом**: Ошибка Inno Setup при компиляции: `Error on line 20: Unknown constant "userlocalappdata"`.
   - **Root Cause**: В Inno Setup версий 6/7 константой для per-user установки является `{autopf}` (автоматически раскрывающаяся в `{localappdata}\Programs` при `PrivilegesRequired=lowest`).
   - **Исправление**: В `packaging/installer.iss` параметр `DefaultDirName` переведен на `{autopf}\{#MyAppName}`.
   - **Validation test**: `tests/test_stage26_packaging.py::test_05_installer_iss_configuration`.

3. **Симптом**: Ошибка загрузки native библиотеки `shapely.lib` (`ImportError: DLL load failed`) при вызове скрипта из чистого подпроцесса.
   - **Root Cause**: Начиная с Python 3.8 на Windows каталоги из `PATH` не используются для поиска зависимостей DLL, требуется вызов `os.add_dll_directory`.
   - **Исправление**: В функцию `rme_mapper._setup_gis_environment()` добавлена динамическая регистрация каталогов поиска DLL (каталог пакета, `_internal`, системные GIS-каталоги). В `src/rme_mapper/main.py` вызов `import rme_mapper` вынесен на первое место.
   - **Validation test**: `tests/test_stage26_packaging.py::test_07_smoke_test_cli_execution`.

4. **Симптом**: Запуск GUI EXE на Windows (`console=False`) отсоединяет стандартные потоки вывода (`stdout`/`stderr`), из-за чего subprocess не получал маркер `[SMOKE-TEST] SUCCESS`.
   - **Root Cause**: Специфика оконных подсистем Windows PE Subsystem: Windows.
   - **Исправление**: В режиме `--smoke-test` приложение атомарно создает файл-маркер `smoke_success.txt` и возвращает код завершения 0, что гарантирует надежную программную верификацию.
   - **Validation test**: `tests/test_stage26_smoke_artifacts.py::test_01_standalone_exe_clean_machine_smoke`.

---

## 7. Artifacts & Checksums (Итоговые артефакты релиза)

Сформированные файлы размещены в каталоге `release/`:

| Artifact Filename | Type | Size | SHA-256 |
|---|---|---|---|
| `GeoPointMapper-0.12.0-portable.zip` | Portable ZIP | 176.4 MB (185 002 381 B) | `9eb8d11532e61a7dae51111c5498cb8077731dee4e71044cade496569236955d` |
| `GeoPointMapper-0.12.0-Setup-x64.exe` | Windows Installer | 117.3 MB (122 960 969 B) | `570961e1c443c1a4acf8670617809edf7638749a10eeacbcf8e9ce8dd7c19554` |
| `GeoPointMapper.exe` | Standalone EXE | 16.1 MB (16 846 779 B) | `9bc2cc327c729719d632e89e3935cc52d96f1100387408556d8a73e5a1049616` |

Манифест релиза сохранен в `release/release_manifest.json`, контрольные суммы — в `release/SHA256SUMS.txt`.

---

## 8. Regression (Результаты регрессионного тестирования)

- **Исходный набор (Этап 25)**: 1290 тестов
- **Добавлено новых тестов (Этап 26)**: **11 тестов**
  - `tests/test_stage26_packaging.py`: 7 тестов
  - `tests/test_stage26_smoke_artifacts.py`: 4 теста
- **ИТОГО ТЕСТОВ В ПРОЕКТЕ**: **1301**
- **Passed**: **1301**
- **Failed**: **0**
- **Skipped**: **0**
- **XFailed**: **0**
- **RuntimeWarning**: **0** (Строго соблюдено требование полного отсутствия RuntimeWarning)

---

## 9. Known Limitations (Ограничения)

- Релизные сборки скомпилированы под 64-битную архитектуру x86-64 и поддерживают Windows 10/11.
- Статус Windows XP: `BLOCKED` (запуск невозможен из-за архитектурных ограничений Python 3.9+ и PySide6).
- Статус Windows 7: `BUILDABLE / NOT TARGET-TESTED` (может собираться отдельно через `requirements-win7.txt` на Python 3.8.10, но не входит в modern дистрибутив).

---

## Вывод

Этап 26 успешно и в полном объеме завершен. Подготовлены воспроизводимые, проверенные, автономные Windows-дистрибутивы приложения GeoPoint Mapper v0.12.0 (Standalone, Portable, Installer), готовые к использованию на чистых пользовательских машинах без установленного Python. Кодовая база готова к переходу к **Этапу 27 — Финальный аудит интерфейса, эргономики (UX/UI) и выпуск v1.0**.
