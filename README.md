# RME-Mapper

Настольное приложение для Windows для нанесения и привязки географических координат на карты Республики Марий Эл.

## Требования

- Python 3.12+
- Windows 10/11
- Зависимости: PySide6, pyproj, geopandas, shapely, pandas, openpyxl, pytest

## Установка и настройка

1. Создайте виртуальное окружение:
   ```bash
   python -m venv .venv
   ```

2. Активируйте виртуальное окружение:
   - В PowerShell:
     ```powershell
     .\.venv\Scripts\Activate.ps1
     ```
   - В CMD:
     ```cmd
     .\.venv\Scripts\activate.bat
     ```

3. Установите зависимости:
   ```bash
   pip install -r requirements.txt
   ```
   Либо в режиме разработки:
   ```bash
   pip install -e ".[dev]"
   ```

## Запуск приложения

Из корневой папки проекта:

```bash
python -m rme_mapper.main
```

или с явным указанием `PYTHONPATH`:

```powershell
$env:PYTHONPATH="src"; python -m rme_mapper.main
```

Если используется локальное окружение `.venv`:

```powershell
$env:PYTHONPATH="src"; .\.venv\Scripts\python.exe -m rme_mapper.main
```

## Запуск тестов

Для запуска тестов используйте `pytest`:

```powershell
.\.venv\Scripts\pytest
```

## Архитектура проекта (Этап 1)

```text
src/
└── rme_mapper/
    ├── __init__.py          # Инициализация пакета и переменных PROJ/GDAL
    ├── main.py              # Точка входа в приложение
    ├── ui/                  # Пользовательский интерфейс (PySide6)
    │   ├── __init__.py
    │   └── main_window.py   # Главное окно (меню, панели, статусбар)
    ├── models/              # Модели данных (точки, проекты, слои)
    ├── maps/                # Управление картами и слоями
    ├── coordinates/         # Парсинг и валидация координат
    ├── points/              # Стилизация и визуализация точек
    ├── importers/           # Импорт координат (XLSX, CSV, TXT)
    ├── exporters/           # Экспорт карт и отчетов (PNG, JPG)
    └── services/            # Сервисы трансформации CRS и ГИС-расчетов
tests/
    ├── __init__.py
    └── test_smoke.py        # Smoke-тесты компонентов и окна
```
