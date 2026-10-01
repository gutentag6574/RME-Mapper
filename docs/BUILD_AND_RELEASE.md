# GeoPoint Mapper — Руководство по сборке и выпуску релизов

В данном документе описан регламент подготовки, сборки, валидации и выпуска автономных дистрибутивов **GeoPoint Mapper** версии **1.0.0** для операционных систем Windows (x64).

---

## 1. Целевые форматы распространения

GeoPoint Mapper поставляется в трёх автономных вариантах, создаваемых из единой кодовой базы через общий сборочный конвейер:

1. **Standalone Application Directory** (`release/standalone/GeoPointMapper/`):
   - Автономный каталог с исполняемым файлом `GeoPointMapper.exe` и подкаталогом `_internal/`.
   - Запускается напрямую без распаковки во временные директории и без прав администратора.
2. **Portable Package** (`release/portable/GeoPointMapper-1.0.0-portable.zip`):
   - ZIP-архив с предупакованным автономным приложением.
   - Готов к переносу на USB-носителях и запуску из произвольного каталога (включая пути с пробелами и кириллицей).
3. **Windows Installer** (`release/installer/GeoPointMapper-1.0.0-Setup-x64.exe`):
   - Полнофункциональный инсталлятор на базе Inno Setup.
   - Безопасная per-user установка в `%LOCALAPPDATA%\Programs\GeoPoint Mapper` (не требует UAC / прав администратора).
   - Создает ярлыки в меню «Пуск» и на Рабочем столе, регистрирует ассоциацию файлов проектов `*.gpmap`.
   - Предоставляет корректный деинсталлятор, сохраняющий пользовательские проекты и настройки.

---

## 2. Системные требования для сборки

Для воспроизводимой сборки релизов необходимы:

- **ОС сборщика**: Windows 10/11 x64 (рекомендуется Windows 11 Build 22000+).
- **Архитектура**: x86-64 / AMD64.
- **Python**: 3.12 (CPython 64-bit).
- **PyInstaller**: 6.22.3 или новее.
- **Inno Setup**: Inno Setup 6 / 7 (компилятор `ISCC.exe` доступен в `tools/innosetup/` или в системном `PATH`).
- **Зависимости приложения**: `PySide6>=6.6.0`, `pyproj>=3.6.0`, `geopandas>=1.0.0`, `rasterio>=1.3.0`, `pyogrio>=0.7.0`, `shapely>=2.0.0`, `openpyxl>=3.1.0`, `pillow>=10.4.0`.

---

## 3. Архитектура упаковки и GIS Runtime

Приложение упаковывается в режиме `onedir` через PyInstaller:

1. **PROJ Database (`proj.db`)**:
   - База данных проекций и геодезических параметров автоматически собирается из системного PROJ / pyproj и размещается в `share/proj/` внутри пакета.
   - Механизм `rme_mapper._setup_gis_environment()` динамически определяет `PROJ_DATA` относительно `sys._MEIPASS` и каталога исполняемого файла.
2. **GDAL Drivers & Metadata (`header.dxf`, CSV)**:
   - Драйверы растровых и векторных форматов упаковываются в `share/gdal/`.
   - Переменная `GDAL_DATA` автоматически устанавливается при старте.
3. **Qt Platform Plugin & Libraries**:
   - PySide6 runtime, плагин платформы `qwindows.dll`, плагины форматов изображений и сетевые модули упаковываются в `_internal/PySide6/`.
4. **SSL / TLS Сертификаты**:
   - Корневые сертификаты Mozilla CA bundle из `certifi` включаются в поставку для безопасной работы с HTTPS/WMS/XYZ тайлами онлайн-карт (`OpenStreetMap`, `Mapbox`).
5. **Безопасность настроек**:
   - `AppSettingsService` сохраняет пользовательские профили в `%APPDATA%\GeoPoint Mapper`, что исключает ошибки доступа при установке в защищенные системные каталоги.

---

## 4. Команда сборки релиза

Сборка выполняется единой командой из корня репозитория:

```cmd
build_release.bat
```

или через Python:

```cmd
python build_release.py
```

### Этапы автоматического конвейера:
1. **Валидация версий**: сверка версии `1.0.0` в `pyproject.toml`, `src/rme_mapper/app_info.py`, `GeoPointMapper.spec`, `packaging/file_version_info.txt` и `packaging/installer.iss`.
2. **Очистка**: удаление предыдущих `build/`, `dist/`, `release/`.
3. **PyInstaller Build**: генерация автономного каталога приложения `dist/GeoPointMapper/`.
4. **Валидация компонентов**: проверка через `tools/validate_release.py` наличия `GeoPointMapper.exe`, `qwindows.dll`, `proj.db`, `header.dxf`, иконок и отсутствия dev-мусора.
5. **Smoke Test**: запуск `GeoPointMapper.exe --smoke-test` в изолированном окружении без системных переменных Python.
6. **Portable ZIP**: архивация каталога в `release/portable/GeoPointMapper-1.0.0-portable.zip`.
7. **Installer Build**: компиляция инсталлятора через `ISCC.exe` в `release/installer/GeoPointMapper-1.0.0-Setup-x64.exe`.
8. **Манифест и контрольные суммы**: формирование `release/release_manifest.json` и `release/SHA256SUMS.txt`.

---

## 5. Структура каталога `release/`

После успешного выполнения сборки формируется следующая структура:

```
release/
├── installer/
│   └── GeoPointMapper-1.0.0-Setup-x64.exe
├── portable/
│   └── GeoPointMapper-1.0.0-portable.zip
├── standalone/
│   └── GeoPointMapper/
│       ├── GeoPointMapper.exe
│       └── _internal/
├── release_manifest.json
└── SHA256SUMS.txt
```

---

## 6. Валидация готовых артефактов

Ручная или автоматизированная валидация собранных дистрибутивов включает:

1. **Проверка Standalone EXE**:
   ```cmd
   release\standalone\GeoPointMapper\GeoPointMapper.exe --smoke-test
   ```
2. **Проверка Portable ZIP**:
   - Распаковать архив в путь с кириллицей и пробелами: `C:\Тест GeoPoint Mapper\Portable\`.
   - Запустить `GeoPointMapper.exe`.
   - Создать точку, сохранить проект в `.gpmap`, открыть растровый или векторный слой.
3. **Проверка Installer**:
   - Запустить тихую установку:
     ```cmd
     release\installer\GeoPointMapper-1.0.0-Setup-x64.exe /SP- /VERYSILENT /SUPPRESSMSGBOXES /CURRENTUSER /DIR="C:\TestInstall\GeoPointMapper"
     ```
   - Проверить наличие ярлыков и деинсталлятора.
   - Запустить установленное приложение:
     ```cmd
     C:\TestInstall\GeoPointMapper\GeoPointMapper.exe --smoke-test
     ```
   - Запустить тихую деинсталляцию:
     ```cmd
     C:\TestInstall\GeoPointMapper\unins000.exe /VERYSILENT /SUPPRESSMSGBOXES
     ```
   - Убедиться, что каталог приложения удален.

---

## 7. Статус Legacy Windows систем

- **Windows XP**: `BLOCKED` (запуск не поддерживается из-за архитектурных ограничений Python 3.9+ и Qt 6).
- **Windows 7**: `BUILDABLE / NOT TARGET-TESTED` (может быть собрана из отдельного профиля `requirements-win7.txt` на Python 3.8.10 + PySide2 5.15, но официальный релиз выпускается для Modern Windows x64).
