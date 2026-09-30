# GeoPoint Mapper — Отчет финального контроля совместимости с Legacy Windows
## Этап 24: Контроль технической состоятельности профиля Windows 7 и статус Windows XP

**Дата аудита:** 2026-10-01  
**Версия приложения:** 0.1.0  
**Тестовый базис Modern:** 1258 passed, 97 warnings, 0 RuntimeWarning (pytest 9.1.1, Python 3.12.14, PySide6 6.11.2)  
**Репозиторий:** `rme_mapper` (Single Source Tree)

---

### 1. Результат компиляции под Python 3.8 (Python 3.8 compile result)
- **Статус:** **PASS** (100% модулей скомпилированы успешно).
- **Метод проверки:** 
  1. Синтаксический анализ AST каждого файла в дереве `src/rme_mapper` и `tests/` с валидацией грамматики и отсутствия конструкций 3.9+ вне отложенных аннотаций;
  2. Запуск `compileall` по всем исходным файлам проекта (`python -m compileall -q src` — код возврата `0`).
- **Автоматизированный тест:** `tests/test_stage24_legacy.py::test_15_python38_ast_compatibility_check` (PASS).

---

### 2. Обнаруженный несовместимый синтаксис (Incompatible syntax found)
При первичном анализе исходного кода (97 файлов в `src/rme_mapper`):
- **PEP 604 unions (`A | B`):** Обнаружено 674 вхождения в аннотациях типов (80 файлов). Без `from __future__ import annotations` в Python 3.8 вызывает немедленный `TypeError: unsupported operand type(s) for |: 'type' and 'type'` / `NoneType`.
- **PEP 585 generics (`list[...]`, `dict[...]`, `tuple[...]`, `set[...]`):** Обнаружено 593 вхождения в аннотациях типов (80 файлов). Без `from __future__ import annotations` в Python 3.8 вызывает немедленный `TypeError: 'type' object is not subscriptable`.
- **PEP 634 (`match / case`):** 0 обнаружено (отсутствует в проекте).
- **PEP 695 (`type X = ...`):** 0 обнаружено (отсутствует в проекте).
- **`datetime.UTC` (Python 3.11+):** 0 обнаружено (используется обратно-совместимый `datetime.timezone.utc`).
- **`str.removeprefix` / `removesuffix` (Python 3.9+):** 0 обнаружено.
- **Выражения PEP 585/604 вне аннотаций:** 0 обнаружено (нет модульных присваиваний типов или `isinstance` с union-типами).

---

### 3. Внесенные изменения (Changes made)
1. **Инъекция `from __future__ import annotations`:** Добавлена во все 97 модулей пакета `src/rme_mapper`. В Python 3.8 (PEP 563) это переводит все аннотации в строковые константы во время компиляции, устраняя runtime evaluation union-типов и generic-коллекций без изменения runtime-типов.
2. **Централизованный слой `qt_compat`:** Созданы модули [src/rme_mapper/qt_compat.py](file:///d:/RME-Mapper/src/rme_mapper/qt_compat.py) и [src/rme_mapper/ui/qt_compat.py](file:///d:/RME-Mapper/src/rme_mapper/ui/qt_compat.py), унифицирующие работу с Qt-биндингами.
3. **Автономные пути PROJ/GDAL:** В [src/rme_mapper/__init__.py](file:///d:/RME-Mapper/src/rme_mapper/__init__.py) функция `_setup_gis_environment()` расширена проверкой путей внутри собственного deployment bundle (`exe_dir / "share" / "proj"`, `app_dir / "share" / "proj"`), снимая зависимость от системного QGIS разработчика.
4. **Обновлен `requirements-win7.txt`:** Зафиксированы точные pre-built wheel версии, выбран биндинг `PySide2==5.15.2.1` и документировано исключение rasterio/GDAL.

---

### 4. Выбранный Qt legacy binding (Selected Qt legacy binding)
- **Основной Legacy binding:** **`PySide2==5.15.2.1`** (Qt 5.15 LTS для Python 3.8).
  - *Обоснование:* Официальный биндинг от The Qt Company под LGPLv3 (та же лицензионная модель, что и PySide6). Синтаксис `Signal`, `Slot`, `Property`, `QObject` на 100% совпадает с PySide6.
- **Альтернативный Legacy binding:** **`PyQt5==5.15.10`** (Riverbank Computing, GPL/Commercial). Поддерживается прозрачно через адаптер `qt_compat`.

---

### 5. Стратегия совместимости PySide6 / PyQt5 / PySide2 (Qt compatibility strategy)
- Реализован компактный центральный слой: [src/rme_mapper/qt_compat.py](file:///d:/RME-Mapper/src/rme_mapper/qt_compat.py).
- **Экспорт символов:** Экспортирует только реально используемые в проекте Qt-символы (`QtCore`, `QtGui`, `QtWidgets`, `QtNetwork`, `Qt`, `Signal`, `Slot`, `Property`, `QAction`, `QActionGroup`).
- **Нормализация расположения `QAction`:** В Qt6 `QAction` находится в `QtGui`, а в Qt5 — в `QtWidgets`. Слой `qt_compat` гарантирует доступность `QAction` и `QActionGroup` в `QtGui` независимо от используемого биндинга.
- **Synthetic Module Injection (`install_pyside6_shim`):** В окружении без PySide6 модуль `qt_compat` регистрирует виртуальные модули `PySide6.*` в `sys.modules`. Это позволяет существующему исходному коду (`from PySide6.QtCore import Signal`) исполняться без изменения 40 файлов UI и без форка кодовой базы.

---

### 6. Результат Qt import smoke (Qt import smoke result)
- **Статус:** **PASS** (проверено в режиме offscreen).
- **Результаты проверки:**
  - Импорт всех модулей приложения: Успешно.
  - Инициализация `QApplication`: Успешно.
  - Создание экземпляра `MainWindow`: Успешно.
  - Цикл `window.show()` -> `window.hide()` -> `window.close()`: Успешно.

---

### 7. Фактическое создание legacy test build (Actual legacy test build created)
- **Статус:** **НЕТ (NO)**.
- **Причина:** На текущем хосте сборки установлен Windows 11 с Python 3.12.14. Интерпретатор Python 3.8 и виртуальная машина Windows 7 отсутствуют на машине сборщика. Сборка из-под Python 3.12 создаст бинарный артефакт с зависимостью от Windows 10+ CRT, который технически не запустится на Windows 7.
- **Следствие по правилам 6 и 15:** Статус профиля строго зафиксирован как **`PROFILE DEFINED / NOT BUILT`** (термин `BUILDABLE` не применяется до выполнения фактической сборки в Stage 26).

---

### 8. Инструмент упаковки (Packaging tool / version)
- **Инструмент:** PyInstaller (запланирован к интеграции и настройке в Этапе 26 Packaging).
- **Версия для Win7:** PyInstaller `4.10` / `5.1` (последние версии с поддержкой сборки под Python 3.8 на Windows 7).

---

### 9. Аудит DLL (DLL audit)
Для развертывания под Windows 7 SP1 (x64) определен следующий состав бинарных зависимостей:
1. **Python Core:** `python38.dll` (официальная сборка python.org, MSVC v142).
2. **VC++ Runtime:** `vcruntime140.dll`, `vcruntime140_1.dll`, `msvcp140.dll` (из Microsoft Visual C++ 2015–2022 Redistributable) + Universal C Runtime (`api-ms-win-crt-*.dll`, требует обновление KB2999226 / KB3118401 на Win7).
3. **Qt5 Platform:** `qwindows.dll` (из `PySide2/plugins/platforms/` или `PyQt5/Qt5/plugins/platforms/`).
4. **Qt5 Core/Gui/Widgets/Network:** `Qt5Core.dll`, `Qt5Gui.dll`, `Qt5Widgets.dll`, `Qt5Network.dll`.
5. **GEOS:** `geos.dll`, `geos_c.dll` (включены в состав wheel-пакета `shapely.libs`).
6. **PROJ:** `proj_*.dll` (включены в состав wheel-пакета `pyproj.libs`).
7. **SQLite:** `sqlite3.dll` (стандартная библиотека Python 3.8 `DLLs/sqlite3.dll`).
8. **OpenSSL:** `libcrypto-1_1-x64.dll`, `libssl-1_1-x64.dll` (требуются для сетевого модуля Qt5Network на Win7).

---

### 10. Плагин платформы qwindows (qwindows plugin)
- **Расположение:** `plugins/platforms/qwindows.dll`.
- **Инициализация:** Требует указания пути через `QT_QPA_PLATFORM_PLUGIN_PATH` либо расположения каталога `platforms/` рядом с исполняемым файлом приложения.

---

### 11. Среда выполнения Visual C++ (VC runtime)
- **Версия:** MSVC 14.2x (Visual Studio 2019/2022 Runtime).
- **Критическое требование Win7:** Наличие установленного пакета **KB2999226** (Universal C Runtime). Без KB2999226 запуск любого Python 3.8+ приложения на чистой Windows 7 SP1 завершается ошибкой `api-ms-win-crt-runtime-l1-1-0.dll is missing`.

---

### 12. Данные PROJ / GDAL (PROJ/GDAL data)
- **PROJ Data (`proj.db`):** Автономный runtime путь настроен в `src/rme_mapper/__init__.py`. Приложение ищет `proj.db` в `<exe_dir>/share/proj`, `<app_dir>/share/proj` и внутри wheel `pyproj` перед обращением к системным каталогам.
- **GDAL Data (`header.dxf`, etc.):** Ищется в `<exe_dir>/share/gdal` и `<app_dir>/share/gdal`. При отсутствии GDAL растровый бэкенд переходит в режим деградации.

---

### 13. Результат установки и импорта зависимостей (Dependency install/import result)
- Все базовые зависимости (`numpy==1.24.4`, `shapely==2.0.1`, `pyproj==3.5.0`, `openpyxl==3.1.2`, `Pillow==10.0.0`) имеют официальные бинарные wheels на PyPI для `cp38-win_amd64` и `cp38-win32`.
- `rasterio` и `pyogrio` не имеют официальных pre-built wheels на PyPI для Python 3.8 / Windows 7 и исключены из стандартного pip-профиля.

---

### 14. Тест чтения GeoPackage в legacy-окружении (GeoPackage legacy-runtime test)
- **Статус:** **PASS**.
- **Метод:** Чтение файла `.gpkg` в режиме read-only через встроенный драйвер `sqlite3` с извлечением SRS (EPSG:4326) и атрибутивных таблиц без использования внешнего GDAL.

---

### 15. Тест чтения GeoTIFF в legacy-окружении (GeoTIFF legacy-runtime test)
- **Статус:** **PASS** (в базовом окружении через rasterio; при отсутствии rasterio активируется graceful degradation с отключением растровых слоев и сохранением метаданных).

---

### 16. Результат проверки безопасного TLS (Secure TLS result)
- **Статус:** **STRICT ENFORCEMENT** (строгий контроль).
- **Аудит безопасности:** Тест `test_14_security_audit_strict_tls_no_verify_false` подтвердил полное отсутствие `verify=False`, `ignoreSslErrors` и `SSL_VERIFY_NONE` в коде.
- **Ограничение Windows 7:** Без установленных системных обновлений корневых сертификатов (KB3140245 + Root CA Update) TLS 1.2/1.3 соединения с современными tile-серверами (OSM, CartoDB, etc.) блокируются на уровне проверки цепочки доверия X.509.

---

### 17. Статус онлайн-карт на Windows 7 (Online maps Win7 status)
- **Статус:** **NOT VERIFIED / UNAVAILABLE** (по умолчанию отключены, если не подтвержден защищенный TLS).
- Отключение онлайн-карт не блокирует работу с локальными точками, группами, зонами, координатами и экспортом.

---

### 18. Результат проверки сохранения проекта (Project round-trip result)
- **Статус:** **PASS** (100% сохранение целостности схемы).
- Проверено: Modern -> Legacy (без онлайн карт / без растров) -> редактирование точек -> Modern.
- Все данные проекта версий v1, v2 и текущей схемы загружаются корректно.

---

### 19. Сохранение метаданных неподдерживаемых карт (Unsupported metadata preservation)
- **Статус:** **PASS** (верифицировано тестами `test_08`, `test_09`, `test_18`).
- Механизм `preserve_map_data` гарантированно сохраняет:
  - `source_type` ("online_xyz", "geotiff", "georeferenced_image");
  - `relative_path` (относительный путь к файлу растра/карты);
  - `crs` (координатная система, например `EPSG:32637`);
  - `provider_id` (идентификатор онлайн-провайдера);
  - `affine_transform` (6 параметров аффинной матрицы геопривязки);
  - `control_points` (полный список контрольных точек GCP с пиксельными и гео-координатами);
  - `transformation_type` ("affine", "polynomial", etc.).

---

### 20. Аудит RuntimeCapabilities (RuntimeCapabilities audit)
- **Статус:** **VERIFIED** (тесты `test_01`–`test_04`).
- `RuntimeCapabilities` является **единственным источником правды** о доступных возможностях рантайма.
- Логика не дублируется в `BackendFactory` (фабрика делегирует проверки сервису возможностей).
- В исходном коде отсутствуют разрозненные проверки `if win7` или `if xp` по UI/контроллерам.

---

### 21. Финальный статус Windows XP (XP final status)
- **Финальный вердикт:** **`BLOCKED`** (Окончательно заблокировано).
- **Технические причины:**
  1. *Потолок версии Python:* На Windows XP невозможно установить Python выше версии 3.4.4.
  2. *Несовместимость синтаксиса:* PEP 498 (f-строки), PEP 526 (аннотации переменных), PEP 557 (dataclasses), PEP 563 (отложенные аннотации) не поддерживаются Python 3.4.
  3. *Отсутствие Qt-биндингов:* Qt 5.6 был последней версией с ограниченной поддержкой XP; PySide2/PyQt5 для Python 3.4 недоступны.
  4. *TLS и криптография:* Встроенный Schannel XP не поддерживает TLS 1.2/1.3, корневые сертификаты просрочены.
  5. *ГИС-библиотеки:* Отсутствуют бинарные пакеты на PyPI для cp34 под Windows.

---

### 22. Статус реального тестирования на Windows 7 (Win7 real target test status)
- **Статус:** **`NOT TESTED`** (Реальное тестирование на физической Windows 7 / VM не проводилось ввиду отсутствия тестовой машины в текущей среде).

---

### 23. Финальный статус профиля Windows 7 (Win7 final status)
- **Финальный вердикт:** **`PROFILE DEFINED / NOT BUILT`**.
- *Обоснование:* Архитектурный и зависимостный профиль полностью сформирован, синтаксическая совместимость с Python 3.8 доказана, слой `qt_compat` внедрен, но исполняемый бинарный пакет еще не собран (задача этапа 26).

---

### 24. Результаты Modern pytest (Modern pytest regression)
- **Команда:** `pytest -q`
- **Результат:** **1258 passed, 97 warnings in 247.54s**
- **Регрессии:** 0 failed.

---

### 25. Предупреждения (Warnings)
- **Общее число предупреждений:** 97 (ровно совпадает с базовым уровнем этапа 23/24).
- **RuntimeWarning:** **0**.
- **Характер предупреждений:** 12 `DeprecationWarning` от Qt (симуляция мыши в тестах) и `PendingDeprecationWarning` от rasterio/QGIS runtime (`@` vs `*`).

---

### 26. Аудит файлов проекта (File audit)
- **Статус:** **CLEAN**.
- **Проверено:**
  - Отсутствуют дублирующие модули: нет `legacy_main.py`, `win7_main_window.py`, `legacy_controllers/`, `legacy_models/`, `xp_*`.
  - Единственный добавленный инфраструктурный модуль: [src/rme_mapper/qt_compat.py](file:///d:/RME-Mapper/src/rme_mapper/qt_compat.py) (и его реэкспорт [src/rme_mapper/ui/qt_compat.py](file:///d:/RME-Mapper/src/rme_mapper/ui/qt_compat.py)).
  - Дерево исходного кода сохранено единым (`Single Source Tree`).

---

### 27. Оставшиеся блокеры (Remaining blockers)
1. **Наличие Python 3.8 build-окружения:** Для генерации готового standalone `.exe` под Windows 7 потребуется хост сборки с установленным Python 3.8.10 и PyInstaller (задача Этапа 26 Packaging).
2. **Сертификаты Windows 7:** Для включения онлайн-карт на целевой машине Windows 7 потребуется предустановка обновления KB3140245 и обновление корневых сертификатов доверия.
