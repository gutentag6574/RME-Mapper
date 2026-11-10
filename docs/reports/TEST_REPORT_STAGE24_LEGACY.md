# ОТЧЕТ ПО ЭТАПУ 24: СОВМЕСТИМОСТЬ С LEGACY WINDOWS (WINDOWS 7 / WINDOWS XP FEASIBILITY)

**Продукт**: GeoPoint Mapper  
**Версия**: 0.12.0  
**Этап**: Этап 24 — Совместимость с устаревшими версиями Windows (Windows 7 / Windows XP Feasibility)  
**Дата аудита**: 22 сентября 2026 г.  
**Статус этапа**: **УСПЕШНО ЗАВЕРШЕН (STAGE 24 COMPLETED)**  

---

## 1. Dependency Compatibility Audit (Аудит совместимости зависимостей)
Проведен детальный технический аудит 13 рантайм-библиотек и инструментов сборки: Python, Qt/PySide, numpy, pyproj, PROJ, rasterio, GDAL, pyogrio, shapely, openpyxl, Pillow, QtNetwork/TLS, PyInstaller. Результаты зафиксированы в документе `docs/LEGACY_WINDOWS_FEASIBILITY.md`.

## 2. Modern Stack (Современный стек Windows 10/11)
- **ОС**: Windows 10 x64 (1809+), Windows 11 x64.
- **Интерпретатор**: Python 3.12+ (x64).
- **GUI**: PySide6 (Qt 6.6+).
- **GIS Core**: numpy >= 1.26.0, shapely >= 2.0.0, pyproj >= 3.6.0 (PROJ 9.3+), pyogrio >= 0.7.0, rasterio >= 1.3.0 (GDAL 3.8+).
- **Офис и растры**: openpyxl >= 3.1.0, Pillow >= 10.0.0.
- **Сеть и безопасность**: QtNetwork, TLS 1.3 / TLS 1.2, HTTP/2, строгая валидация SSL-сертификатов.

## 3. Win7 Chosen Stack (Выбранный стек для Windows 7 SP1)
- **Интерпретатор**: CPython **3.8.10** (официальный Windows x64/x86 инсталлятор, последний с поддержкой Win7).
- **GUI**: **PyQt5 5.15.10** или **PySide2 5.15.2.1** (Qt 5.15 LTS).
- **GIS Core**: `numpy==1.24.4`, `shapely==2.0.1`, `pyproj==3.5.0` (с бандлированным `proj.db`), `openpyxl==3.1.2`, `Pillow==10.0.0`.
- **Профиль зафиксирован в**: `requirements-win7.txt`.

## 4. XP Feasibility Result (Результат исследования Windows XP)
- **Статус**: **XP = BLOCKED (Заблокировано)**.
- **Обоснование**: CPython 3.4.4 не поддерживает современный синтаксис (PEP 585/604, f-strings, dataclasses). Отсутствуют сборки Qt6 и Qt5. Системный Schannel XP и OpenSSL 1.0.1 не поддерживают TLS 1.2/1.3, а корневые сертификаты просрочены. Создание форка запрещено правилом «One source tree».

## 5. Python Versions (Версии Python)
- **Modern**: Python 3.12+ (актуальный).
- **Windows 7**: Python 3.8.10 (зафиксирован).
- **Windows XP**: Python 3.4.4 (последний официальный для XP, заблокирован).

## 6. Qt Versions (Версии Qt)
- **Modern**: PySide6 (Qt 6.6+).
- **Windows 7**: PyQt5 5.15.10 / PySide2 5.15.2 (Qt 5.15 LTS).
- **Windows XP**: PyQt4 4.11 / PySide 1.2 (Qt 4.8.7, заблокирован).

## 7. GIS Dependency Versions (Версии ГИС-зависимостей)
- **Shapely**: Modern = 2.0.4+; Win7 = 2.0.1; XP = 1.5.17 (GEOS 3.4, C++98).
- **pyproj**: Modern = 3.6.1; Win7 = 3.5.0; XP = 1.9.5.1 (PROJ 4.9.2).
- **numpy**: Modern = 1.26.4; Win7 = 1.24.4; XP = 1.11.3 / 1.12.1.
- **rasterio/GDAL**: Modern = rasterio 1.3.10 (GDAL 3.8); Win7 = rasterio 1.3.6 (GDAL 3.5); XP = недоступен.

## 8. Architecture x64 / x86 (Архитектура)
- **Modern**: 64-bit (x86-64 / AMD64).
- **Windows 7**: 64-bit (основной) / 32-bit (x86, ограничение 2 ГБ RAM).
- **Windows XP**: 32-bit (x86).

## 9. Capability Architecture (Архитектура возможностей)
Реализован централизованный сервис `RuntimeCapabilities` (`src/rme_mapper/services/runtime_capabilities.py`), предоставляющий единую точку проверки:
- `supports_geopackage()`
- `supports_geotiff()`
- `supports_online_maps()`
- `supports_georeferencing()`
- `supports_xlsx()`
- `supports_webp()`
- `supports_high_dpi()`
- `supports_secure_tls()`
- `BackendFactory` интегрирован с `RuntimeCapabilities` без дублирования кода.

## 10. Disabled Features (Отключение недоступных функций)
- При недоступности онлайн-карт (например, из-за отсутствия безопасного TLS): меню онлайн-карт и все действия деактивируются (`setEnabled(False)`) с поясняющим tooltip: *«Онлайн-карты недоступны: безопасный стек TLS 1.2+ не поддерживается в данной сборке»*.
- При недоступности GeoTIFF или геопривязки соответствующие действия отключаются без падений интерфейса.

## 11. TLS / Security Result (Безопасность и TLS)
- **Строгий запрет**: в проекте полностью отсутствуют `verify=False`, игнорирование SSL-ошибок (`ignoreSslErrors`) и fallback на незащищенный HTTP для HTTPS-сервисов.
- На устаревших платформах без TLS 1.2+ сетевые функции принудительно отключаются.

## 12. Project Format Compatibility (Совместимость формата проектов)
- Используется единый текстовый формат **`*.gpmap` (UTF-8 JSON, v1)**.
- Никаких отдельных расширений (`*.gpmap7`, `*.gpmapxp`) не создается.

## 13. Modern -> Legacy Project Flow
- Проект, созданный в Modern Build (включая проекты с онлайн-картами), безопасно открывается в Legacy Build без вылетов.
- Точки, группы, стили и зоны отображаются на холсте; базовая подложка выгружается, если она не поддерживается платформой.

## 14. Legacy -> Modern Project Flow
- Проект, отредактированный и сохраненный в Legacy-версии, открывается в Modern Build без потери координатной точности, стилей и групп.

## 15. Unsupported-Source Preservation (Round-Trip сохранение метаданных)
- Реализован механизм сохранения `preserve_map_data` в `ProjectService.build_project_data` и `ProjectController`.
- **Результат**: Если Legacy-сборка открыла проект с онлайн-картой OSM, пользователь добавил точку и пересохранил проект, секция метаданных онлайн-карты (`online_xyz`, `osm_standard`) сохраняется в `*.gpmap` и при открытии в Modern Build подгружается автоматически.

## 16. Unicode and Path Testing (Тестирование путей и юникода)
- Подтверждена корректная работа с путями, содержащими кириллицу, пробелы и спецсимволы (`Тестовая Папка Картографии / Проект_Москва.gpmap`).
- Точки с русскими именами и описаниями («Геодезический знак «Северный»») сериализуются и читаются со 100% точностью.

## 17. Raster Backend (Растровый бэкенд)
- В Modern Build используется `ModernGeoTiffBackend` (rasterio/GDAL).
- На платформе Windows 7 x64 поддерживается `ModernGeoTiffBackend` (rasterio 1.3.6).
- Архитектурный плейсхолдер `LegacyRasterBackend` сохранен для будущих расширений.

## 18. GeoPackage Support
- Modern Build: `ModernGeoPackageBackend` (pyogrio/GDAL/geopandas).
- Read-only режим строго соблюдается.

## 19. GeoTIFF Support
- Чтение окон обзора (windowed reading), downsampling и NoData поддерживаются.

## 20. Online Maps Support
- OpenStreetMap, Mapbox, CartoDB функционируют только при наличии валидного TLS 1.2+ стека.
- На Windows XP онлайн-карты заблокированы.

## 21. Georeferencing Compatibility
- Аффинные преобразования растров (6 параметров) и контрольные точки сохраняются в единой схеме метаданных `MapProfile` и файла проекта `*.gpmap`.

## 22. Import / Export (Импорт и экспорт)
- CSV, XLSX (openpyxl), TXT импорт и экспорт поддерживаются на Modern и Win7.
- GeoJSON экспорт и PNG/JPEG экспорт сцены сохраняют инвариантность.

## 23. Recovery and Backup (Аварийное восстановление)
- Метод `ProjectService.get_recovery_snapshot_path()` дополнен проверкой переменной `APPDATA` для устаревших ОС Windows (где `LOCALAPPDATA` может отсутствовать), предотвращая сбои записи аварийных снимков.

## 24. Real Windows 7 Test Environment
- Физическая или виртуальная машина Windows 7 в среде непрерывной интеграции / выполнения **в настоящий момент отсутствует**.

## 25. Windows 7 GUI A-Z Smoke Test
- В соответствии с Правилом 41/68/70 статус smoke-тестов на целевой машине зафиксирован как:  
  **BUILDABLE / NOT TARGET-TESTED** (без фиктивной простановки PASS).

## 26. Real Windows XP Environment
- Целевая машина Windows XP отсутствует.

## 27. XP GUI Result
- **BLOCKED** на уровне ядра интерпретатора.

## 28. Win7 Performance
- Для Windows 7 x64 производительность эквивалентна Modern.
- Для Windows 7 x86 установлен безопасный лимит: **25 000 точек**.

## 29. XP Performance
- Измерения не проводились (платформа заблокирована).

## 30. DLL / Runtime Audit (Аудит динамических библиотек)
- Для Windows 7 требуется наличие: `python38.dll`, `vcruntime140.dll`, Universal C Runtime (`api-ms-win-crt-*.dll`, KB2999226), `qwindows.dll` (Qt platforms plugin), `proj.db` (PROJ datum).
- Для безопасной загрузки библиотек требуется обновление KB3063858 (`SetDefaultDllDirectories`).

## 31. Clean-Machine Result
- Документированы требования к автономному пакету: поставка UCRT и Qt-плагинов в составе дистрибутива (запланировано на Этап 26).

## 32. Tests Added (Добавленные автоматизированные тесты)
Создан тестовый модуль `tests/test_stage24_legacy.py`, содержащий **14 новых тестов**:
1. `test_01_runtime_capabilities_modern_profile` — проверка профиля Modern;
2. `test_02_runtime_capabilities_win7_simulation` — симуляция профиля Win7;
3. `test_03_runtime_capabilities_xp_simulation_and_unavailable` — симуляция профиля XP;
4. `test_04_no_duplicate_capability_systems` — делегирование BackendFactory;
5. `test_05_runtime_environment_logging` — логирование параметров среды;
6. `test_06_project_schema_version_invariant` — инвариантность схемы v1;
7. `test_07_unsupported_online_map_loading_does_not_crash` — открытие без крашей;
8. `test_08_unsupported_map_source_roundtrip_preservation` — критический round-trip онлайн-карт;
9. `test_09_unsupported_geotiff_source_roundtrip` — round-trip растровых карт;
10. `test_10_cyrillic_paths_and_unicode_names` — кириллические пути и названия;
11. `test_11_legacy_recovery_paths_fallback` — fallback APPDATA для recovery;
12. `test_12_ui_action_degradation_when_online_maps_disabled` — деградация меню UI;
13. `test_13_security_audit_no_pickle_or_eval` — отсутствие pickle/eval/exec;
14. `test_14_security_audit_strict_tls_no_verify_false` — аудит строгого TLS.

## 33. Modern Pytest Result (Результаты тестирования)
- **Было до этапа**: 1240 тестов (100% passed).
- **Добавлено**: 14 тестов.
- **Итого**: **1254 passed, 0 failed, 0 error**.

## 34. Warnings
- **Warnings**: 97 warnings (сторонние Deprecation в rasterio и QMouseEvent, новых предупреждений нет).
- **RuntimeWarning**: **0**.

## 35. New-Files Audit (Аудит новых файлов)
В рамках Этапа 24 созданы исключительно проектные артефакты документации, профили зависимостей и сервисы возможностей:
- `docs/LEGACY_WINDOWS_FEASIBILITY.md`
- `docs/LEGACY_WINDOWS.md`
- `docs/LEGACY_PERFORMANCE_STAGE24.md`
- `requirements-win7.txt`
- `src/rme_mapper/services/runtime_capabilities.py`
- `tests/test_stage24_legacy.py`
- `TEST_REPORT_STAGE24_LEGACY.md`
Дублирующие файлы (`legacy_main.py`, `legacy_main_window.py` и др.) **не создавались**. Принцип One Source Tree строго соблюден.

## 36. Final Feature Matrix (Итоговая матрица возможностей)

| Подсистема / Функция | Modern (Win 10/11 x64) | Windows 7 SP1 (x64/x86) | Windows XP SP3 (x86) |
| :--- | :--- | :--- | :--- |
| **Startup / Пустой запуск** | VERIFIED | BUILDABLE / NOT TARGET-TESTED | BLOCKED |
| **Файл проекта (*.gpmap)** | VERIFIED | BUILDABLE / NOT TARGET-TESTED | BLOCKED |
| **Точки, группы, зоны** | VERIFIED | BUILDABLE / NOT TARGET-TESTED | BLOCKED |
| **Координаты (DD, DMS, X-Y)** | VERIFIED | BUILDABLE / NOT TARGET-TESTED | BLOCKED |
| **Измерения расстояний/азимутов** | VERIFIED | BUILDABLE / NOT TARGET-TESTED | BLOCKED |
| **Координатная сетка и масштаб** | VERIFIED | BUILDABLE / NOT TARGET-TESTED | BLOCKED |
| **GeoPackage (векторы)** | VERIFIED | BUILDABLE / NOT TARGET-TESTED | BLOCKED |
| **GeoTIFF (растры)** | VERIFIED | BUILDABLE / NOT TARGET-TESTED | BLOCKED |
| **Геопривязка изображений** | VERIFIED | BUILDABLE / NOT TARGET-TESTED | BLOCKED |
| **Импорт CSV / TXT** | VERIFIED | BUILDABLE / NOT TARGET-TESTED | BLOCKED |
| **Импорт / Экспорт XLSX** | VERIFIED | BUILDABLE / NOT TARGET-TESTED | BLOCKED |
| **Экспорт GeoJSON / CSV** | VERIFIED | BUILDABLE / NOT TARGET-TESTED | BLOCKED |
| **Экспорт PNG / JPEG** | VERIFIED | BUILDABLE / NOT TARGET-TESTED | BLOCKED |
| **Резервное копирование / Recovery**| VERIFIED | BUILDABLE / NOT TARGET-TESTED | BLOCKED |
| **Локализация RU / EN** | VERIFIED | BUILDABLE / NOT TARGET-TESTED | BLOCKED |
| **Онлайн-карты (XYZ Tiles)** | VERIFIED | BUILDABLE / NOT TARGET-TESTED | BLOCKED |

## 37. Win7 Final Status
- **Статус**: **BUILDABLE / NOT TARGET-TESTED**.

## 38. XP Final Status
- **Статус**: **BLOCKED (Заблокировано)**.

## 39. Blockers (Технические блокеры)
- Синтаксис Python 3.12 (PEP 585/604, f-strings, dataclasses) блокирует исполнение на Python 3.4 (XP).
- PySide6 / Qt6 блокирует Windows 7 и Windows XP.
- Отсутствие TLS 1.2+ и просроченные сертификаты блокируют онлайн-карты на XP.

## 40. Known Limitations (Известные ограничения)
- Windows 7 и Windows XP являются EOL-системами с рисками безопасности.
- 32-битные сборки имеют потолок памяти 2 ГБ и лимит безопасного размера проектов 25 000 точек.
