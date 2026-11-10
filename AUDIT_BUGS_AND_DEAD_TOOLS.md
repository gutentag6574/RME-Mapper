# Полный отчёт по аудиту приложения GeoPoint Mapper (RME-Mapper)
**Дата аудита:** 11 ноября 2026 г.  
**Версия приложения:** 1.0.1  
**Статус проверки:** Комплексный статический и логический анализ всех подсистем (`maps/`, `services/`, `importers/`, `exporters/`, `ui/`, `models/`, `coordinates/`, `packaging/`).

---

## Резюме аудита
В ходе полного аудита исходного кода приложения выявлены:
- **5 ошибок и логических дефектов (Bugs & Unhandled Exceptions)** различной степени критичности (от краха форматирования статус-бара до искажения тайлов при экспорте).
- **7 неработающих / мёртвых инструментов и заглушек (Dead Tools & Non-working Features)**, которые либо присутствуют в коде/интерфейсе, но не имеют практического эффекта, либо теряют пользовательские данные между сессиями.
- **7 конфликтующих дубликатов ключей локализации (i18n)**, молчаливо перезаписывающих строки интерфейса.
- **2 дефекта упаковки и метаданных сборки**.

Все обнаруженные проблемы сгруппированы ниже с указанием файлов, номеров строк, сценария проявления и рекомендаций по исправлению.

---

## 1. Ошибки, исключения и логические дефекты (Bugs)

### BUG-1: Сбой форматирования строки статуса при переносе точек в группу
- **Файл:** `src/rme_mapper/ui/controllers/point_controller.py:950`
- **Критичность:** High
- **Описание:** При массовом или одиночном перемещении объектов в группу вызывается:
  ```python
  self._set_status(tr("status.points_moved_to_group", count=len(valid_points)), 3000)
  ```
  В словарях `translations_ru.py:800` и `translations_en.py:800` ключ определён как:
  `"status.points_moved_to_group": "Объектов перемещено в группу «{group}»: {count}"`
  Так как параметр `group` не передан, вызов `template.format(**kwargs)` в `TranslationService.translate_in_language` падает с `KeyError: 'group'`, перехватывается общим `except Exception` и возвращает сырой неформатированный шаблон.
- **Симптом:** В строке состояния пользователю отображается не отформатированная строка, а сырой текст: `Объектов перемещено в группу «{group}»: 3`.
- **Исправление:** Передавать имя целевой группы:
  ```python
  self._set_status(tr("status.points_moved_to_group", group=grp_name, count=len(valid_points)), 3000)
  ```

---

### BUG-2: Потеря географического охвата (`extent`) при отмене (Undo) редактирования геопривязки растра
- **Файл:** `src/rme_mapper/ui/controllers/map_controller.py:674`
- **Критичность:** High
- **Описание:** В методе `edit_georeferencing` создаётся замыкание `apply_fn(aff, cps, crs)`, которое передаётся в `EditGeoreferencingCommand`:
  ```python
  new_extent = dlg.get_extent()
  def apply_fn(aff, cps, crs):
      self._active_profile.affine_transform = list(aff)
      self._active_profile.control_points = cps
      self._active_profile.crs = crs
      self._active_profile.extent = new_extent  # <-- ОШИБКА
      self.load_georeferenced_image(self._active_profile, Path(path))
  ```
  При вызове пользователем операции «Отменить» (`Ctrl+Z` / Undo), `apply_fn` вызывается со старыми параметрами `before_affine`, `before_cps`, `before_crs`, однако `self._active_profile.extent` принудительно перезаписывается новым охватом `new_extent` из замыкания! Прежний охват `before_extent` не сохраняется и не восстанавливается.
- **Симптом:** При Undo после изменения контрольных точек растра геометрия охвата остаётся некорректной (соответствующей отменённой привязке), нарушая расчет границ карты и команду «Вписать карту» (`fit_to_view`).
- **Исправление:** Запоминать `before_extent = dict(self._active_profile.extent or {})`, расширить параметры команды `EditGeoreferencingCommand` либо вычислять актуальный `extent` прямо внутри `apply_fn` по переданным `aff` и размерам изображения.

---

### BUG-3: Необработанное исключение `CRSError` при чтении сопутствующего `.prj` файла
- **Файл:** `src/rme_mapper/services/georeference_service.py:87-90`
- **Критичность:** High
- **Описание:** При импорте World File или изображения ищется парный файл проекции `.prj`:
  ```python
  prj = next((f for f in image.parent.iterdir() if f.is_file()
              and f.name.casefold() == (image.stem + ".prj").casefold()), None)
  if prj:
      crs = pyproj.CRS.from_user_input(prj.read_text(encoding="utf-8-sig")).to_string()
  ```
  Если файл `.prj` повреждён, содержит нестандартную/устаревшую WKT-строку или пуст, `pyproj.CRS.from_user_input` выбрасывает исключение `pyproj.exceptions.CRSError`. В `read_world_file` этот вызов не обёрнут в `try...except`.
- **Симптом:** Попытка открыть изображение или World File при наличии в папке битого или нестандартного `.prj` файла приводит к сбою загрузки карты и показу диалога критической ошибки вместо перехода к ручному выбору CRS.
- **Исправление:** Обернуть разбор `.prj` в `try...except Exception`:
  ```python
  if prj:
      try:
          crs = pyproj.CRS.from_user_input(prj.read_text(encoding="utf-8-sig")).to_string()
      except Exception as crs_err:
          logger.warning("Не удалось прочитать CRS из %s: %s", prj.name, crs_err)
          crs = None
  ```

---

### BUG-4: Несоответствие систем координат при экспорте онлайн-подложки в `_render_online_tiles`
- **Файл:** `src/rme_mapper/exporters/map_renderer.py:408-418`
- **Критичность:** Medium / High
- **Описание:** Вспомогательный метод `_render_online_tiles` принимает `target_extent` и передаёт его напрямую в `extent_to_tile_range`:
  ```python
  min_ex, min_ey, max_ex, max_ey = target_extent
  tile_bounds = extent_to_tile_range(min_ex, min_ey, max_ex, max_ey, zoom)
  ```
  Функция `extent_to_tile_range` строго ожидает координаты в проекции Web Mercator (`EPSG:3857`). Если экспорт карты запускается для проекта с географической CRS (например, `EPSG:4326`, где координаты в градусах, `min_ex ~ 37.0`) или в местной/зоновой проекции (например, `EPSG:32639` UTM 39N, где `min_ex ~ 500000`), вычисление тайлов ломается: `extent_to_tile_range` возвращает `None` либо диапазон тайлов в океане у нулевого меридиана.
- **Симптом:** При экспорте карты с активными онлайн-тайлами в форматах отличных от чистого Web Mercator онлайн-подложка либо полностью отсутствует на итоговом изображении, либо отрисовывается с геометрическим сдвигом.
- **Исправление:** Проверять `active_crs` перед вызовом `extent_to_tile_range` и при необходимости трансформировать `target_extent` из `active_crs` в `EPSG:3857` через `CoordinateService.transform_xy`.

---

### BUG-5: Вызов несуществующего метода `ws.close()` при ошибке экспорта в XLSX
- **Файл:** `src/rme_mapper/services/object_export_service.py:386-389`
- **Критичность:** Low
- **Описание:** В блоке обработки ошибок экспорта таблицы в Excel:
  ```python
  except Exception as e:
      if ws is not None:
          try:
              ws.close()
          except Exception:
              pass
  ```
  Объект `ws` является экземпляром `openpyxl.worksheet.worksheet.Worksheet` (или `WriteOnlyWorksheet`), у которого отсутствует метод `close()` (метод `close()` есть только у объекта книги `wb`). Вызов гарантированно бросает `AttributeError`.
- **Симптом:** Бесполезный вызов, маскируемый `except: pass`.
- **Исправление:** Удалить вызов `ws.close()`, оставив только `wb.close()`.

---

## 2. Мёртвые инструменты, неработающие функции и фичи-заглушки (Dead Tools)

### DEAD-1: Пользовательские XYZ-провайдеры карт не сохраняются между сессиями
- **Файлы:** `src/rme_mapper/ui/online_basemap_dialog.py:327-336`, `src/rme_mapper/services/app_settings_service.py:693, 703`
- **Критичность:** Medium
- **Описание:** В `AppSettingsService` полностью реализованы методы:
  - `save_custom_provider(provider_data)`
  - `delete_custom_provider(provider_id)`
  - `get_custom_providers()`
  Однако в `OnlineBasemapDialog._on_accept` созданный пользовательский провайдер `create_custom_provider` сохраняется только во временное поле экземпляра диалога `self._selected_provider` и **никогда не записывается в настройки через `save_custom_provider`**. Также при открытии диалога список пользовательских провайдеров никогда не восстанавливается из `get_custom_providers()`.
- **Симптом:** Каждый раз при перезапуске приложения или повторном открытии диалога онлайн-карт все введённые пользователем URL-шаблоны и параметры тайлов Custom XYZ бесследно теряются.
- **Исправление:** Приняв диалог с `mtype is None`, вызывать `self._settings.save_custom_provider(...)`, а в `_refresh_provider_list()` загружать сохранённые провайдеры через `self._settings.get_custom_providers()`.

---

### DEAD-2: Настройка максимального размера кэша тайлов не имеет эффекта
- **Файлы:** `src/rme_mapper/services/app_settings_service.py:628, 636`, `src/rme_mapper/maps/online_tile_manager.py:51`
- **Критичность:** Low / Medium
- **Описание:** В `AppSettingsService` присутствуют методы `get_online_cache_max_mb()` и `set_online_cache_max_mb()`. Однако `OnlineTileManager` инициализирует дисковый кэш вызовом без аргументов:
  ```python
  self._cache = tile_cache or TileDiskCache()
  ```
  Класс `TileDiskCache` по умолчанию жёстко задаёт размер 512 МБ (`DEFAULT_MAX_CACHE_SIZE_MB = 512`). Значение из `AppSettingsService` никогда не запрашивается и не передаётся в кэш.
- **Симптом:** Пользовательская настройка размера кэша (если задана в конфигурации) полностью игнорируется приложением.
- **Исправление:** Передавать сохранённое значение при инициализации:
  ```python
  max_mb = settings_service.get_online_cache_max_mb() if settings_service else 512
  self._cache = tile_cache or TileDiskCache(max_size_mb=max_mb)
  ```

---

### DEAD-3: Метод `get_last_online_provider` никогда не читается
- **Файл:** `src/rme_mapper/services/app_settings_service.py:640`
- **Критичность:** Low
- **Описание:** `MapController` при каждой смене онлайн-карты добросовестно вызывает:
  `self._settings_service.set_last_online_provider(provider.id)`
  Однако метод чтения `get_last_online_provider()` не вызывается ни в одном модуле приложения. Ни `MainWindow`, ни `OnlineBasemapDialog` не используют это значение для предварительного выбора последней подложки.
- **Симптом:** Сохранение последнего провайдера в реестр/файл настроек происходит «вхолостую».
- **Исправление:** Использовать сохранённый ID в `OnlineBasemapDialog._load_saved_values()` при отсутствии активного провайдера.

---

### DEAD-4: Механизм переключения тем (`ThemeManager`) недоступен пользователю в интерфейсе
- **Файлы:** `src/rme_mapper/ui/theme_manager.py`, `src/rme_mapper/ui/main_window.py:275-276`
- **Критичность:** Low / Medium
- **Описание:** В приложении написан полноценный менеджер тем оформления `ThemeManager` (`theme_manager.py`, 383 строки кода) с поддержкой тёмной и светлой палитр (`apply_theme`, `get_available_themes`, `current_theme`). В `MainWindow` тема инициализируется один раз при старте:
  ```python
  self._theme_manager = get_theme_manager()
  self._theme_manager.apply_theme(self)
  ```
  При этом в главном меню (меню «Вид» или «Настройки») **нет ни одного `QAction`, пункта меню или горячей клавиши для смены темы**. Пользователь не может переключить тему через графический интерфейс.
- **Симптом:** Разработанная система тем оформления является «мёртвой» фичей с точки зрения пользователя GUI.
- **Исправление:** Добавить в меню «Вид» подменю «Тема оформления» со списком доступных тем и переключателями.

---

### DEAD-5: Мёртвый метод `render_tiles_to_painter` в `OnlineTileManager`
- **Файл:** `src/rme_mapper/maps/online_tile_manager.py:377-417`
- **Критичность:** Low
- **Описание:** Метод `render_tiles_to_painter` (40 строк кода) был написан для экспорта тайлов в QPainter, но фактически не используется — экспорт тайлов полностью дублируется и выполняется внутри `MapRenderer._render_online_tiles`.
- **Симптом:** Неиспользуемый дублирующий код.
- **Исправление:** Либо удалить устаревший метод, либо переиспользовать его в `MapRenderer._render_online_tiles` во избежание дублирования логики рендеринга.

---

### DEAD-6: Метод-заглушка `_add_layer_checkbox` в `MainWindow`
- **Файл:** `src/rme_mapper/ui/main_window.py:1745-1746`
- **Критичность:** Low
- **Описание:** В `MainWindow` объявлен метод:
  ```python
  def _add_layer_checkbox(self, layer: MapLayer) -> None:
      pass
  ```
  Метод представляет собой пустую заглушку `pass`, оставшуюся от старой архитектуры до выноса логики в `layers_panel.py`.
- **Исправление:** Удалить рудиментарный метод.

---

### DEAD-7: Неиспользуемый метод `build_profile` в `OpenMapDialog`
- **Файл:** `src/rme_mapper/ui/open_map_dialog.py:797-800`
- **Критичность:** Low
- **Описание:** Метод:
  ```python
  def build_profile(self) -> MapProfile | None:
      self._on_accept_clicked()
      return self._selected_profile
  ```
  Не вызывается ни в одном тесте и ни в одном контроллере приложения. Вызов `_on_accept_clicked()` вызывает побочный эффект в виде закрытия (`accept()`) диалога.
- **Исправление:** Либо удалить метод, либо задокументировать как устаревший.

---

## 3. Дефекты локализации и конфликты ключей (i18n)

### I18N-1: 7 дублирующихся ключей в словарях `translations_ru.py` и `translations_en.py`
- **Файлы:** `src/rme_mapper/i18n/translations_ru.py`, `src/rme_mapper/i18n/translations_en.py`
- **Критичность:** Medium
- **Описание:** В словарях переводов присутствуют дублирующиеся ключи. В Python словарь при инициализации сохраняет только последнее значение, silently затирая предыдущее:
  1. `"points.count_total"` (строка 112: `"Точек: {count}"` затирается строкой 810: `"Всего: {count}"`)
  2. `"points.count_filtered"` (строка 113: `"Показано: {shown} из {total}"` затирается строкой 809: `"Показано {shown} из {total}"`)
  3. `"menu.point_labels_content"` (строка 667: `"Содержимое"` затирается строкой 757: `"Содержимое подписей"`)
  4. `"label_content.name"` (строка 668: `"Название"` затирается строкой 758: `"Только название"`)
  5. `"label_content.number"` (строка 669: `"Номер"` затирается строкой 759: `"Только номер объекта"`)
  6. `"label_content.number_name"` (строка 670: `"Номер + название"` затирается строкой 760: `"Номер и название"`)
  7. `"action.change_category"` (строка 675: `"Изменить категорию выбранных..."` затирается строкой 775: `"Изменить категорию..."`)
- **Симптом:** Неявная перезапись строковых констант. Например, строка счётчика точек в панели неожиданно меняется с «Точек: N» на «Всего: N».
- **Исправление:** Удалить дублирующиеся ключи и оставить единственные канонические определения.

---

### I18N-2: Мёртвый неиспользуемый ключ `points.counter_filtered`
- **Файлы:** `src/rme_mapper/i18n/translations_ru.py:808`, `translations_en.py:808`
- **Критичность:** Low
- **Описание:** Ключ `"points.counter_filtered"` добавлен в словари, но в коде везде используется ключ `"points.count_filtered"`.
- **Исправление:** Удалить неиспользуемый ключ.

---

## 4. Дефекты упаковки, сборки и метаданных

### PKG-1: Рассинхронизация версии в `packaging/file_version_info.txt`
- **Файл:** `packaging/file_version_info.txt:8-9, 25, 30`
- **Критичность:** Low / Medium
- **Описание:** В файле метаданных Windows Version Info:
  - `filevers=(1, 0, 0, 0)`  <-- ОШИБКА (версия 1.0.0.0)
  - `prodvers=(1, 0, 1, 0)`  <-- Версия 1.0.1.0
  - `FileVersion: 1.0.1.0`
  - `ProductVersion: 1.0.1`
  - `pyproject.toml: 1.0.1`
  - `app_info.py: 1.0.1`
  Поле `filevers` не было синхронизировано и отстало на версию `1.0.0.0`.
- **Симптом:** В свойствах скомпилированного Windows-файла (`.exe`) в проводнике бинарная версия файла отображается как `1.0.0.0`, в то время как продуктовая версия — `1.0.1`.
- **Исправление:** Заменить строку 8 на `filevers=(1, 0, 1, 0)`.

---

### PKG-2: Нарушение структуры докстринга в `GeoreferenceService.export_world_file`
- **Файл:** `src/rme_mapper/services/georeference_service.py:358-360`
- **Критичность:** Low
- **Описание:** В коде функции:
  ```python
  def export_world_file(
      image_path: Path | str,
      affine_coeffs: tuple[float, float, float, float, float, float],
      crs_str: str | None = None,
      target_dir: Path | str | None = None,
      crs: str | None = None,
  ) -> list[Path]:
      if crs is not None:
          crs_str = crs
      """Экспорт коэффициентов аффинной трансформации..."""
  ```
  Исполняемый оператор `if crs is not None:` расположен **перед** тройными кавычками описания функции. По правилам Python строковый литерал считается докстрингом (`__doc__`) только если он является первой инструкцией в теле функции.
- **Симптом:** У метода `export_world_file.__doc__ == None`. В IDE, `help()` и автодокументации описание функции не отображается.
- **Исправление:** Переместить `if crs is not None: crs_str = crs` ниже закрывающих кавычек докстринга.

---

## Сводная таблица найденных замечаний

| ID | Тип | Критичность | Файл | Краткое описание |
|---|---|---|---|---|
| **BUG-1** | Bug | **High** | `point_controller.py:950` | `KeyError: 'group'` при показе статуса переноса точек в группу |
| **BUG-2** | Bug | **High** | `map_controller.py:674` | Потеря `extent` при Undo редактирования геопривязки |
| **BUG-3** | Bug | **High** | `georeference_service.py:89` | Необработанный `CRSError` при битом или нестандартном `.prj` |
| **BUG-4** | Bug | **Medium/High** | `map_renderer.py:417` | Несоответствие проекций тайлов при экспорте карты |
| **BUG-5** | Bug | **Low** | `object_export_service.py:386` | Несуществующий метод `ws.close()` у Worksheet openpyxl |
| **DEAD-1** | Dead tool | **Medium** | `online_basemap_dialog.py:327` | Пользовательские XYZ тайлы не сохраняются между сессиями |
| **DEAD-2** | Dead tool | **Medium** | `app_settings_service.py:628` | Настройка максимального размера кэша тайлов игнорируется |
| **DEAD-3** | Dead tool | **Low** | `app_settings_service.py:640` | Метод `get_last_online_provider` никогда не читается |
| **DEAD-4** | Dead tool | **Low/Medium** | `main_window.py:275` | В интерфейсе нет инструментов переключения темы оформления |
| **DEAD-5** | Dead code | **Low** | `online_tile_manager.py:377` | Мёртвый метод `render_tiles_to_painter` |
| **DEAD-6** | Dead code | **Low** | `main_window.py:1745` | Метод-заглушка `_add_layer_checkbox` |
| **DEAD-7** | Dead code | **Low** | `open_map_dialog.py:797` | Неиспользуемый метод `build_profile` |
| **I18N-1** | i18n | **Medium** | `translations_ru.py`, `_en.py` | 7 дублирующихся ключей, затирающих исходные переводы |
| **I18N-2** | i18n | **Low** | `translations_ru.py:808` | Неиспользуемый ключ `points.counter_filtered` |
| **PKG-1** | Packaging | **Low/Medium** | `file_version_info.txt:8` | Рассинхронизация `filevers=(1, 0, 0, 0)` с версией 1.0.1 |
| **PKG-2** | Code structure | **Low** | `georeference_service.py:358` | Код перед докстрингом в `export_world_file` обнуляет `__doc__` |

