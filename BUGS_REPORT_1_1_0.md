# Отчёт об аудите багов и дефектов GeoPoint Mapper v1.1.0

**Проект:** `d:\RME-Mapper` (ветка `main`, GeoPoint Mapper `1.1.0`)  
**Примечание:** Отдельный отчёт, составленный без изменения исходного кода и без перезаписи отчёта по v1.0.1 (`AUDIT_BUGS_AND_DEAD_TOOLS.md`). Включены только проблемы, подтверждённые в коде, конфигах, сценариях сборки, логах прогонов (`scratch/*.log`) и выводе статических проверок (`audit_i18n.ps1`, `audit_i18n_deep.ps1`).

---

## Сводка по уровням критичности

| Уровень | Кол-во записей | Основные затронутые области |
| --- | ---: | --- |
| **Критический** | 4 | Восстановление снимка при запуске, таблица точек / Undo, утечка слоёв между картами, мутация кэша `MapProfile` |
| **Высокий** | 10 | `UndoManager.is_clean`, CRS/трансформации координат, `ProjError` на `EPSG:3857`, RGBA/альфа растра, `warp_image`, `TileCache`, упаковка/архивация проекта, Мастер импорта и `import_service`, экспорт карты и геопривязка |
| **Средний** | 9 | `GroupsPanel`, `ValidationTableModel`, `PointsPanel`/`PointController`, `BulkPointStyleDialog`, `ScaleOverlay`, `CrsPicker`, `OnlineBasemapDialog`, `WorkspaceLayout`, валидация стилей/координат, GPX/KML, `runtime_capabilities` |
| **Локализация и тема (i18n / Dark UI)** | 4 группы | 5 отсутствующих ключей `import.err.*`, ошибка форматирования `{error}`, 167+ зашитых кириллических строк/единиц, дефекты Dark Theme в `ThemeManager`, `ThemeStyleFilter` и панелях |
| **Сборка, упаковка и инструментарий** | 6 групп | Несуществующие `hiddenimports` в `.spec`, нерабочий Win7/PySide2-профиль, дубль и хардкод в `build_release.py`, ассоциация `.rmeproject` в `installer.iss`, пробелы `tools/*.py`, `smoke_success.txt` и предупреждения в логах |

---

## 1. Критические баги

### [CRIT-01] Сброс восстановленной из аварийного снимка карты сразу при запуске
- **Где:** `src/rme_mapper/ui/main_window.py:296-306`
- **Суть:** При старте `MainWindow.__init__` сначала вызывает `self._check_recovery_snapshot_on_startup()` (строка 296), где при согласии пользователя (`restore_recovery_snapshot()`, строка 1549) восстанавливаются карта, слои, оверлеи и точки. Однако сразу следом при запуске без аргументов командной строки (`project_path`, `map_profile`, `map_path` равны `None`) безусловно выполняется ветка `else: self._unload_map()` (строка 306).
- **Последствие:** Восстановленная карта, слои, оверлеи и аннотации немедленно выгружаются, оставляя восстановленные пользовательские точки «висеть» без карты.
- **Рекомендация:** Вызывать `_unload_map()` только в случае, если карта не была загружена восстановлением из аварийного снимка (например, проверять `if self.map_controller.active_profile is None and self.map_controller.map_path is None:`).

### [CRIT-02] Порча таблицы точек и рассинхронизация ID при Undo удаления строки
- **Где:** `src/rme_mapper/ui/panels/points_panel.py:496-528`, `src/rme_mapper/ui/controllers/point_controller.py:177-182, 219, 820`
- **Суть:** В `PointsPanel.insert_row` строка добавляется через `insertRow(target_row)` **только** при условии `if target_row >= self.points_table.rowCount():` (строки 498-499). Если отменяется удаление точки из начала или середины таблицы (`row < rowCount()`), `insertRow()` не вызывается — вместо вставки новой строки вызовы `setItem(target_row, ...)` перезаписывают уже существующую строку. При этом `PointController._cmd_add_point` вставляет `point.id` в `_table_point_ids`, из-за чего `rowCount()` и индексы таблицы рассинхронизируются с `_table_point_ids`. Дополнительно `_cmd_add_point` (строки 177-179) добавляет точку в конец внутреннего словаря `self._point_service._points`, хотя в таблице ставит её на прежний `row_index` — последующая перерисовка (`populate_points_table_batch`) сбивает порядок строк.
- **Последствие:** Тихая потеря/затирание видимых строк таблицы, смещение выделения и редактирование не той точки после `Ctrl+Z`.
- **Рекомендация:** Всегда вызывать `self.points_table.insertRow(target_row)` при `0 <= target_row <= rowCount()` и восстанавливать порядок точек в `PointService` с сохранением исходного индекса.

### [CRIT-03] Утечка слоёв и границ старой карты при переключении карт + неполная очистка состояния холста
- **Где:** `src/rme_mapper/ui/controllers/map_controller.py:209-214, 265-279, 335-346, 422-433, 503-538, 583-655`; `src/rme_mapper/maps/map_canvas.py:1211-1224, 2271-2293, 2398-2405`; `src/rme_mapper/ui/controllers/export_controller.py:108-111`
- **Суть:**
  1. В отличие от `load_online_map` (`map_controller.py:265-279`), методы `load_map` (`422-433`, `503-538`) и `load_georeferenced_image` (`583-655`) не вызывают очистку предыдущих `_layer_items` и не сбрасывают `_boundary_bounds = None`. При этом `MapCanvas.add_raster_item` (`map_canvas.py:1213-1224`) удаляет со сцены только `layer.id` (`"raster_base"`), `_raster_item` и `_raster_window_item`. В результате векторные слои и `_boundary_bounds` прошлой GeoPackage-карты остаются на сцене поверх GeoTIFF / привязанного изображения и попадают в `ExportController.get_full_map_extent()` (`export_controller.py:108-111`).
  2. `map_controller.py:335-346` перезаписывает `_active_profile` и `_map_path` **до** проверки существования файла `if not path.is_file():`.
  3. `MapController.unload_map()` (`209-214`) не сбрасывает `self._active_crs`, оставляя СК прежней карты (`EPSG:3857` / UTM).
  4. `MapCanvas.clear_online_basemap()` (`map_canvas.py:2398-2405`) очищает тайл-менеджер и атрибуцию, но не сбрасывает `self._active_crs` и `self._scale_overlay.set_map_loaded(False)` (в отличие от `set_online_basemap`).
  5. `MapCanvas.set_error()` (`map_canvas.py:2271-2293`) вызывает `self._scene.clear()`, обнуляя только `_layer_items` и `_user_point_items`, но оставляя ссылки на уже удалённые C++/Qt-объекты в `_user_zone_items`, `_user_label_items`, `_selection_halo_items`, `_raster_item`, `_raster_window_item`, `_grid_item_group`, `_measure_*` и `_annotation_items`; текст `{message}` вставляется в HTML без экранирования.
- **Рекомендация:** Вынести полную очистку слоёв/границ/CRS/оверлеев холста в единый метод и вызывать его до загрузки любой новой карты, при выгрузке и в `set_error()` (а `{message}` экранировать через `html.escape`).

### [CRIT-04] Мутация разделяемых объектов `MapProfile` из каталога и рассинхрон команд аннотаций при смене карты
- **Где:** `src/rme_mapper/ui/controllers/project_controller.py:403, 454-458`; `src/rme_mapper/ui/audit_features.py:122-135, 152-173`
- **Суть:**
  1. При открытии проекта `project_controller.py:403` получает профиль из каталога (`target_profile = self._map_catalog_service.get_profile(...)`) без копирования и напрямую мутирует `target_profile.raster_overlays` и `target_profile.annotations` (строки 454-458). Если позже открыть этот профиль из каталога или другой проект на той же базовой карте, оверлеи и треки/аннотации предыдущего проекта перетекают в него.
  2. В `AuditFeaturesMixin.change_annotations` (`audit_features.py:122-135`) и `add_annotation_batch` (`152-173`) undo-команды захватывают ссылку `profile = self.map_controller.active_profile` без проверки `profile is None` (строка 123 упадёт с `AttributeError`) и при Undo/Redo после смены карты меняют уже закрытый профиль, перерисовывая сцену новой карты.
- **Рекомендация:** Использовать глубокую копию `MapProfile` из каталога; хранить состояние аннотаций привязанным к текущему проекту/контроллеру карты и сбрасывать стек Undo при смене карты/проекта (или привязывать команды к идентификатору активного профиля).

---

## 2. Баги высокого приоритета

### [HIGH-01] `UndoManager.is_clean` даёт ложный `True` после ветвления стека Undo
- **Где:** `src/rme_mapper/services/undo_manager.py:441-460`
- **Суть:** `is_clean` проверяет `len(self._undo_stack) == self._clean_index`. Если пользователь откатил стек Undo ниже точки сохранения (`_clean_index`) и выполнил новое действие (`push()` отрезает старую redo-ветку), `_clean_index` не сбрасывается в `-1`. Последующая отмена нового действия до прежней длины стека ошибочно возвращает `is_clean == True`.
- **Рекомендация:** При `push()`, если `len(self._undo_stack) < self._clean_index`, сбрасывать `_clean_index = -1`.

### [HIGH-02] Ошибочная проверка `is_project_active` для несохранённого проекта
- **Где:** `src/rme_mapper/ui/main_window.py:203` vs `src/rme_mapper/ui/controllers/project_controller.py:103-105`
- **Суть:** В `MainWindow` передаётся `is_project_active=lambda: bool(self.project_controller.current_project_path)`, тогда как сам `ProjectController.is_project_active` проверяет `self._project_loaded`. Пока новый проект ещё не сохранён на диск (`current_project_path is None`), закрытие или смена карты не помечает проект изменённым (`is_modified = True`).
- **Рекомендация:** Передавать `lambda: self.project_controller.is_project_active`.

### [HIGH-03] Отсутствие перепроецирования координат в `center_on_coordinates`, зонах и `PointController`
- **Где:** `src/rme_mapper/maps/map_canvas.py:1605-1628, 2160-2172`; `src/rme_mapper/ui/audit_features.py:201-202`; `src/rme_mapper/ui/controllers/point_controller.py:756-759, 847-850`
- **Суть:**
  1. `MapCanvas.center_on_coordinates` (`map_canvas.py:2160-2172`) вызывает `centerOn(QPointF(longitude, -latitude))` напрямую в градусах без трансформации из WGS84 в `self._active_crs`. В частности, `AuditFeaturesMixin.navigate_to_input` (`audit_features.py:201-202`) при поиске точки по имени/номеру уводит камеру в район `(0, 0)` метров на любых проецированных картах (`EPSG:3857`, UTM и т.п.).
  2. `_create_zone_path` / `update_point_zone` (`map_canvas.py:1605-1628`) в ветке `zone_polygon is None` строит контур в градусах долготы/широты без преобразования в `self._active_crs`.
  3. В `PointController._render_point_on_canvas` (`847-850`) и `copy_coordinates_map_xy` (`756-759`) жёстко указано `source_crs="EPSG:4326"` вместо `point.source_crs`.
- **Рекомендация:** Преобразовывать координаты через `CoordinateService.transform_xy` / `transform_polygon` в `self._active_crs` (и учитывать `point.source_crs` при работе с `PointController`).

### [HIGH-04] Необработанные исключения `ProjError` (полюса `lat = ±90°` в `EPSG:3857`) и деление на ноль при рендере тайлов
- **Где:** `src/rme_mapper/ui/controllers/point_controller.py:677, 695, 756, 847, 875, 904, 998`; `src/rme_mapper/ui/point_dialog.py:1303-1305`; `src/rme_mapper/services/annotation_service.py:12-17`; `src/rme_mapper/services/tile_render_service.py:19-33, 54`; `src/rme_mapper/maps/map_canvas.py:638-640`; `src/rme_mapper/ui/audit_features.py:208-215`
- **Суть:**
  1. Перечисленные методы `PointController` (`show_all_points`, `zoom_to_selected`, `copy_coordinates_map_xy`, `_render_point_on_canvas`, `render_points_batch`, `reproject_all_points`, `on_table_row_double_clicked`), проверка охвата в `PointDialog` (`point_dialog.py:1304`) и `annotation_path` (`annotation_service.py:12-17`) не перехватывают `ProjError` и падают, например, при отображении полярной точки `lat = ±90°` на `EPSG:3857` (хотя импорт и буфер обмена принимают `[-90, 90]`).
  2. `TileRenderService` (`tile_render_service.py:19-33`) вызывает `to_merc.transform_bounds(*extent)` без обрезки по пределам Web Mercator (`±85.0511288°`), вызывая сбой при экспорте карт в `EPSG:4326` с полярным охватом; при нулевой ширине/высоте охвата (`xmax - xmin == 0` или `ymax - ymin == 0`) делит на ноль; использует `QRectF(...).toRect()`, давая субпиксельные швы при одинаковых СК; ищет тайлы в кэше только по одному вычисленному `zoom`.
  3. `MapCanvas._finish_measurement` (`map_canvas.py:638-640`) вызывает `pyproj.Transformer.from_crs(...).transform(..., errcheck=True)` без `try/except`, пересоздавая трансформер на каждое измерение.
  4. `AuditFeaturesMixin.navigate_to_input` (`208-215`) при отсутствии загруженной карты (`active_crs` некорректен/пуст) выдаёт `"audit.search_invalid"` вместо предупреждения об отсутствии карты (и в режиме `"map"` вовсе не проверяет наличие карты).
- **Рекомендация:** Обрабатывать `ProjError` в контроллерах/диалогах с понятной диагностикой и безопасным пропуском непроецируемых точек; в `TileRenderService` ограничивать широту меркатора и проверять ненулевой размер охвата.

### [HIGH-05] Ошибка выбора RGB-каналов и искажение прозрачности в `modern_raster.py`
- **Где:** `src/rme_mapper/backends/modern_raster.py:282-291, 330`
- **Суть:** При чтении 4+-канальных растров код находит индекс альфа-канала `alpha_idx` по `ColorInterp.alpha`, но на строках `289-291` по-прежнему жёстко берёт `r, g, b = data[0], data[1], data[2]`. Если альфа-канал находится на индексе `0..2`, он попадёт в цветовые каналы. На строке `330` не-`uint8` альфа-канал нормируется на `raw_a.max()`, из-за чего полупрозрачные области с максимумом меньше диапазона типа данных становятся 100% непрозрачными.
- **Рекомендация:** Исключать `alpha_idx` при выборе R/G/B каналов (или опираться на `ColorInterp.red/green/blue`) и нормировать альфа-канал по максимуму dtype (`255` / `65535`).

### [HIGH-06] Сбои и депрекация в `raster_warp_service.py` + порча относительных путей оверлеев
- **Где:** `src/rme_mapper/services/raster_warp_service.py:11-23`; `src/rme_mapper/ui/raster_overlays.py:115`
- **Суть:**
  1. `warp_image` (`raster_warp_service.py:11-23`) использует устаревшее умножение `Affine * ...` (даёт 6 `PendingDeprecationWarning` в `scratch/audit-project-final.log`); на строке `15` падает с `TypeError: cannot unpack non-iterable NoneType object`, если передан `extent`, но `output_size is None`; на строке `13` падает с `ZeroDivisionError`, если `image.width() == 0` или `image.height() == 0`.
  2. В `raster_overlays.py:115` `record["path"] = str(path.resolve())` перезаписывает относительный путь оверлея абсолютным путём на текущей машине.
- **Рекомендация:** Заменить `Affine * ...` на актуальный API `rasterio.transform` / `affine`, проверить `output_size` и непустоту `QImage`, не перезаписывать относительные пути абсолютными без необходимости.

### [HIGH-07] Синхронный `os.walk` на каждый тайл, двойная запись тайла и отсутствие проверки `provider_id` в `TileCache`
- **Где:** `src/rme_mapper/services/tile_cache.py:97, 275, 285, 306`; `src/rme_mapper/services/tile_loader.py:390`; `src/rme_mapper/maps/online_tile_manager.py:309`
- **Суть:**
  1. Каждый загруженный тайл сохраняется дважды (`tile_loader.py:390` и `online_tile_manager.py:309`), и каждый `save_tile()` синхронно вызывает `_maybe_evict()`, обходя весь дисковый кэш (`os.walk`).
  2. Методы `get_total_size_bytes(provider_id)` (`285`) и `clear_cache(provider_id)` (`306`) не проверяют `provider_id` регулярным выражением `SAFE_PROVIDER_ID_RE` (`97`), допуская обращение к произвольному подкаталогу при некорректном идентификаторе.
- **Рекомендация:** Убрать дублирующую запись тайла, вызывать проверку квоты асинхронно / по счётчику операций и проверять `provider_id` во всех публичных методах `TileCache`.

### [HIGH-08] Дефекты упаковки архива проекта и относительных путей в `ProjectBundleService` / `ProjectService`
- **Где:** `src/rme_mapper/services/project_bundle_service.py:19, 34-46, 51`; `src/rme_mapper/services/project_service.py:453-460, 490`
- **Суть:**
  1. `ProjectBundleService` при `map_path is None` разрешает `result.map.relative_path` и пути `overlay["path"]` через `Path(...).resolve()` относительно текущего рабочего каталога (`CWD`), а не каталога проекта.
  2. В архив копируется сам файл оверлея, но **не копируются его sidecar-файлы геопривязки** (`.jgw`, `.pgw`, `.tfw`, `.wld`, `.prj`), из-за чего оверлеи на базе world-файлов теряют привязку в `overlays/{index}/{name}`.
  3. Базовая карта кладётся как `"maps/" + source.name` без проверки возможных коллизий имён.
  4. `ProjectService.build_project_data` (`453-460, 490`) строит `relative_path` только относительно `get_project_root()`, а не папки сохранения проекта (`file_path.parent`), и записывает `raster_overlays` с исходными (как правило, абсолютными) путями.
- **Рекомендация:** Разрешать относительные пути относительно каталога файла проекта, включать в бандл все сопутствующие sidecar-файлы растров и сохранять переносимые относительные пути относительно папки проекта.

### [HIGH-09] Баги Мастера импорта, парсеров CSV/XLSX и `ImportService`
- **Где:** `src/rme_mapper/ui/import_wizard.py:232, 302, 310-313, 609-614`; `src/rme_mapper/importers/delimited_importer.py:153, 165, 188`; `src/rme_mapper/importers/xlsx_importer.py:124`; `src/rme_mapper/importers/import_service.py:886-948, 1084-1092, 1104-1107, 1219-1237`
- **Суть:**
  1. **Разные имена безымянных колонок:** Мастер импорта в `_extract_headers` (`import_wizard.py:311`) генерирует `Col_{i+1}`, тогда как `DelimitedImporter` (`165`) и `XlsxImporter` (`124`) генерируют `Column_{i+1}`. При пустом заголовке в файле маппинг колонок в мастере расходится с данными при импорте.
  2. **Блокировка заголовков после 50-й строки:** `header_row_spin` допускает значения `1..100` (`232`), но `read_preview_rows(..., max_rows=50)` (`302`) загружает максимум 50 строк; при выборе строки `> 50` `_detected_headers` пуст и кнопка «Далее» блокируется.
  3. **Неполный список исключений конфликта маппинга:** В `_validate_mapping` (`import_wizard.py:609`) из проверки дубликатов колонок исключены старые необязательные поля (по `"zone_opacity"`), но забыты новые (`object_number`, `description`, `category`, `group`, `visible`, `stroke_*`, `marker_opacity`, `zone_border_*`).
  4. **CSV/TSV:** `delimited_importer.py:153` вызывает `.strip()` на строке заголовка, обрезая крайние табуляции `\t` в TSV-файлах с пустой первой/последней колонкой; дубликаты заголовков тихо затираются в `row_dict[header] = val` (`188`).
  5. **Сервис импорта:** Некорректные значения `visible` и всех новых стилей обводки/прозрачности (`import_service.py:886-947`) молча игнорируются (`except Exception: pass`) без предупреждения строки; проверка лимита `MAX_PROJECT_POINTS` (`1084-1092`) выполняется уже после сборки `result.points`; `_parse_dd_number` и `_parse_int_component` принимают `bool` как `int` и не проверяют `math.isfinite`.
- **Рекомендация:** Унифицировать именование `Column_{i+1}`, подгружать предпросмотр минимум до `header_row_spin.value()`, дополнить списки полей и валидацию в `ImportService`.

### [HIGH-10] Дефекты экспорта карты/объектов и диалогов открытия/геопривязки
- **Где:** `src/rme_mapper/exporters/map_renderer.py:239-269`; `src/rme_mapper/exporters/decorations.py:171-177, 300-317, 499-503`; `src/rme_mapper/ui/controllers/export_controller.py:122`; `src/rme_mapper/ui/export_image_dialog.py:545, 670, 722, 837`; `src/rme_mapper/ui/export_objects_dialog.py:425-426`; `src/rme_mapper/ui/open_map_dialog.py:414-422, 764-767`; `src/rme_mapper/ui/georeference_dialog.py:726-736`
- **Суть:**
  1. `MapRenderer` (`map_renderer.py:239-268`): сбой чтения любого растрового оверлея (`try...finally` без `except`) или аннотации прерывает весь экспорт карты; перо аннотации `QPen(..., 2)` игнорирует `scale_factor` (линии слишком тонкие при 300 DPI).
  2. `decorations.py`: легенда в позиции `top_right` (`171-177`) перекрывает стрелку севера; шкала `NICE_INTERVALS` (`300-317`) ограничена сверху и не покрывает континентальные масштабы; в подписи Mapbox (`502`) проверка `not display_text.startswith("mapbox")` чувствительна к регистру после `.lower()`, порождая `"mapbox | © Mapbox"`.
  3. `ExportController` (`122`) берёт `item.boundingRect()` вместо `sceneBoundingRect()` (ср. строку 114).
  4. `ExportImageDialog`: имя файла по умолчанию из `_default_map_title` (`545, 837`) не очищается от запрещённых символов Windows (`<>:"/\|?*`); в предпросмотре `round(540 * (options.height_px / options.width_px))` (`670`) может округлиться в `0`; при ошибке предпросмотра (`722`) ключ `export.err_failed` вызывается без `error=`, оставляя буквальный `{error}` в сообщении.
  5. `ExportObjectsDialog` (`425-426`): проверка `if not target_path.suffix:` не добавляет расширение `.csv`/`.xlsx`, если в имени файла уже есть точка (например `points.v2`).
  6. `GeoreferenceDialog` (`726-736`): `_on_table_cell_changed` записывает распарсенное `val` в `pt.pixel_x` / `pixel_y` / `target_x` / `target_y` **до** проверки `if not math.isfinite(val):`, оставляя `NaN`/`Inf` в модели точки.
  7. `OpenMapDialog`: наличие world-файла `.tfw` рядом с GeoTIFF перехватывается веткой `414-422` до `inspect_raster`, принудительно открывая диалог ручной геопривязки; в `764-767` обрезка суффикса ` (name)` из результата `_format_crs_string` работает только для `EPSG:` и `OGC:CRS84`, оставляя невалидной любую другую СК (`ESRI:...`, PROJ-строку).
- **Рекомендация:** Изолировать отрисовку оверлеев/аннотаций в `try/except`, исправить коллизию легенды, санитизировать имена файлов, валидировать конечность значений до мутации `ControlPoint` и проверять world-файлы с учётом метаданных GeoTIFF.

---

## 3. Баги среднего приоритета

### [MED-01] `AttributeError` в контекстном меню `GroupsPanel` и пропуск предупреждений в поиске `ValidationTableModel`
- **Где:** `src/rme_mapper/ui/panels/groups_panel.py:178, 273`; `src/rme_mapper/ui/models/validation_table_model.py:75-78`
- **Суть:**
  - В `GroupsPanel.__init__` поле `self._total_count` не инициализируется (на строке 178 используется `getattr(self, "_total_count", 0)`), но `_show_context_menu` (`273`) обращается к `self._total_count` напрямую — правый клик по системному узлу до обновления счётчиков вызывает `AttributeError`.
  - В `ValidationTableModel` ветка `elif row.warnings:` игнорирует предупреждения при текстовом поиске, если в той же строке есть ошибки `row.errors`.

### [MED-02] Дубликат метода, пропуски обновления UI и баг счётчика в `PointsPanel`, `PointController` и `BulkPointStyleDialog`
- **Где:** `src/rme_mapper/ui/panels/points_panel.py:608-616, 708-728, 785-817`; `src/rme_mapper/ui/controllers/point_controller.py:708-730, 934, 975, 1061`; `src/rme_mapper/ui/bulk_point_style_dialog.py:50, 70, 336, 424-425`
- **Суть:**
  - `PointsPanel.update_point_group_id` определён дважды (`608-616` и `720-728`).
  - `PointsPanel.remove_rows_by_point_ids` (`708-718`) не обновляет порядковые номера в столбце 0 (в отличие от `remove_row`).
  - `PointsPanel.select_point_ids` (`785-817`) выделяет в том числе скрытые фильтрацией строки.
  - `PointController`: в групповом контекстном меню (`1061`) всегда отображается `"action.hide_object"`, даже если все выбранные точки скрыты; в одиночном меню смешиваются кликнутая строка и текущее выделение таблицы; `move_points_to_group_workflow` (`934`) и `bulk_change_category_workflow` (`975`) не обновляют `properties_panel`; `copy_coordinates_dd` (`727-730`) каждый раз создаёт `AppSettingsService()`; `copy_selected_coordinates` (`708-723`) аннотирован `-> None`, но возвращает строку.
  - `BulkPointStyleDialog`: конструктор вычисляет `count = point_count if point_count is not None else len(self._points)` (`50`), но `_setup_ui` (`70`) и `retranslate_ui` (`424-425`) берут `len(self._points)` (при вызове без списка точек отображается `0`); валидация радиуса (`336`) не проверяет `math.isfinite`.

### [MED-03] Дефекты рендера `ndarray` и `ScaleOverlay` в `maps/`
- **Где:** `src/rme_mapper/maps/map_canvas.py:1238-1241`; `src/rme_mapper/maps/scale_overlay.py:69-94, 131`
- **Суть:**
  - В `MapCanvas.add_raster_item` (`1238-1241`) переменная числа каналов `c` вычисляется, но игнорируется — для любого числа каналов всегда передаются `w * 4` и `QImage.Format.Format_RGBA8888`.
  - В `ScaleOverlay`: при `distance_m == 0.0` масштабирование даёт `"≈1:1"` (`max(1, round(rounded))`); в `_update_geometry` (`81`) создаётся неиспользуемая переменная `font`, а ширина текста `_ratio_text` не учитывается при расчёте виджета, из-за чего подпись обрезается при узком отрезке линейки (50 px).

### [MED-04] Логические баги в `CrsPicker`, `ClipboardCoordinatesDialog`, `OnlineBasemapDialog`, `WorkspaceLayout`, `SettingsDialog`, `PointDialog`, `AuditFeaturesMixin`
- **Где:**
  - `src/rme_mapper/ui/crs_picker.py:41, 85`: выбор первого элемента списка избранного `"Выберите СК"` с `itemData == ""` затирает введённую СК пустой строкой; поиск `"мск"` преобразуется в `"msk"` при запросе только к базе `EPSG` (где российских локальных МСК нет).
  - `src/rme_mapper/ui/clipboard_coordinates_dialog.py:20, 24, 56, 109`: начальный `CrsPicker("", self)` провоцирует сбой `Transformer.from_crs("", ...)` в `validate_rows()` при открытии диалога; проверка `MAX_PROJECT_POINTS` (`20`) срабатывает на число непустых строк до отсеивания ошибочных.
  - `src/rme_mapper/ui/online_basemap_dialog.py:381, 393`: для встроенных провайдеров (`mtype is not None`) очистка поля API-ключа не удаляет сохранённый ранее ключ (`if key:` на строке 393); для пользовательского XYZ имя параметра ключа ограничивается `"access_token"` / `"key"`.
  - `src/rme_mapper/ui/workspace_layout.py:35-37, 60-66`: при расположении таблицы точек снизу (`points_bottom=True`) сплиттер `workspace_splitter` содержит 3 виджета, но `_read_workspace_sizes()` требует `len(sizes) == 2` и при запуске всегда сбрасывает размеры на `[600, 230]`.
  - `src/rme_mapper/ui/settings_dialog.py:73, 102-104`: при невалидном цвете `accept()` возвращает фокус на поле без уведомления пользователя; по умолчанию допускается `radius_m = 0` при включённой зоне.
  - `src/rme_mapper/ui/point_dialog.py:1091, 1277`: предпросмотр валидирует `0..255` только для цвета заливки, но не для обводки; отключение зоны (`else:`) перезаписывает радиус на `0.0`.
  - `src/rme_mapper/ui/audit_features.py:71, 229, 235`: `field_import_action.triggered` подключён напрямую к `import_field_file(self, path=None)`, куда Qt передаёт `bool checked` вместо пути.

### [MED-05] Баги моделей, валидации, импорта GPX/KML, drag-and-drop и `runtime_capabilities`
- **Где:**
  - `src/rme_mapper/models/online_provider.py:124-126, 270`: дублирующийся ключ `"api_key_param_name"` в `to_dict()`; `create_custom_provider` заменяет не-ASCII символы на `_`, превращая разные кириллические названия равной длины в одинаковый ID `custom_____`.
  - `src/rme_mapper/models/map_profile.py:146-162`: `control_points` внутри `source` превращаются в `ControlPoint`, а на верхнем уровне остаются `dict`.
  - `src/rme_mapper/models/point_style.py:81-82, 202-203, 227-228, 247-248`: `float("nan")` проходит `validate_size`, `validate_stroke_width`, `validate_border_width`, а `validate_opacity(float("nan"))` падает с необработанным `ValueError` из `round()` вместо `ValidationError`.
  - `src/rme_mapper/coordinates/validator.py:147, 184-187`: отсутствует `math.isfinite` для секунд DMS (`"nan"` проходит проверки `< 0` и `>= 60.0`).
  - `src/rme_mapper/services/field_import_service.py:41, 46, 51, 56, 61`: в GPX чтение `attrib['lon']`/`attrib['lat']` без защиты падает с `KeyError`; в KML `split()[0].split(',')` ломается на пробелах после запятых (`"37.6, 55.7"`); безымянные линии нумеруются от `len(points)+1`, давая `"1"`.
  - `src/rme_mapper/services/runtime_capabilities.py:184-186, 200-210, 260-266`: `supports_webp()` вызывает `QImageReader.supportedImageFormats()` при старте (`main.py:60`) **до** инициализации `QApplication` (`main.py:64`); `supports_source_type()` возвращает `False` для неизвестных типов; `log_runtime_environment()` проверяет `PySide6` раньше `PyQt5`, маскируя `PyQt5` при наличии шима.
  - `src/rme_mapper/ui/main_window.py:1678, 1726`: в обработке drag-and-drop не допускается расширение `.tsv`, хотя `DelimitedImporter` его поддерживает.

---

## 4. Локализация (i18n) и проблемы Тёмной темы

### 4.1. Пропущенные ключи и ошибки форматирования
Проверка `audit_i18n.ps1` показала паритет словарей `TRANSLATIONS_RU` и `TRANSLATIONS_EN` (по `1015` ключей, `0` дубликатов словарных ключей, `0` расхождений плейсхолдеров), однако выявлены **5 используемых кодов ошибок**, отсутствующих в обоих словарях (`src/rme_mapper/importers/import_service.py`):
- `import.err.max_project_points_exceeded` (строка `1089`)
- `import.err.missing_lat_deg` (строка `1129`)
- `import.err.missing_lat_dir` (строка `1131`)
- `import.err.missing_lon_deg` (строка `1133`)
- `import.err.missing_lon_dir` (строка `1135`)

При отображении пользователю `TranslationService.translate` выводит вместо локализованного текста сырой идентификатор ключа.

Также обнаружена ошибка вызова с плейсхолдером:
- `src/rme_mapper/ui/export_image_dialog.py:722`: `f"{tr('export.err_failed')}\n{e}"` — ключ `export.err_failed` ожидает `{error}`, поэтому пользователь видит буквально строку `{error}`.

### 4.2. Хардкод русского текста, единиц измерения и английских заголовков
Проверка `audit_i18n_deep.ps1` зафиксировала **167 вызовов с зашитой кириллицей** в коде UI, валидаторов, моделей и сервисов, которые не переводятся при выборе английского языка (`EN`). Наиболее заметные очаги:
- **Строка состояния и предупреждения главного окна:** `src/rme_mapper/ui/main_window.py:1577-1584` (жёстко зашиты единицы `"м"`, игнорируется настройка `coordinates/precision`, а условие `is_geo = "4326" in crs or "CRS84" in crs.upper()` печатает `"м"` даже для других географических СК вроде `EPSG:4284` / `EPSG:4269`), а также строки `1792-1814`, `1823`, `1838`, `1863`, `1888`.
- **Контроллеры и холст:** `map_controller.py:481, 533, 563, 672`; `point_controller.py:1104` (пункт `"Яндекс Карты"` вместо ключа `"audit.open_yandex"`); `map_canvas.py:2283` (`"Ошибка загрузки карты"`).
- **Панели и стили:** `properties_panel.py:24-28` (словарь `SYMBOL_DISPLAY_NAMES` на русском), `313, 321, 340` (`" px"`); `point_style.py:118-120` (`"Red (красный)"` и т.п.).
- **Диалоги и импорт:** `bulk_point_style_dialog.py:329, 343`; `open_map_dialog.py:404, 449, 459, 772`; `georeference_dialog.py:428, 550, 553, 811, 840-848, 894` (русские строки и `" м"` / `"(м)"` даже для градусных СК); `import_service.py:1019` (`f"Точка {auto_point_counter}"`), `1224, 1228`; `clipboard_coordinates_dialog.py:38, 64, 70` (непереведённые `"OK"`, `"Longitude"`, `"Latitude"`, `"X / Easting / Lon"`); `online_basemap_dialog.py:369` (`"Custom XYZ"`).
- **Исключения моделей, валидаторов и сервисов, попадающие в UI:** `coordinates/validator.py:140, 145, 153, 174-176, 218-220`; `coordinates/converter.py:35`; `models/object_group.py:23-46, 72`; `models/map_profile.py:120, 124`; `models/georeference.py:67`; `models/project_data.py:315, 326, 331`; `services/georeference_service.py:44-300`; `services/geodesic_service.py:67-154`; `services/group_service.py:44, 77`; `services/object_export_service.py:230, 284`.

### 4.3. Дефекты Тёмной темы (Dark Theme)
- **`src/rme_mapper/ui/theme_manager.py:192, 196, 207, 260, 267, 288, 307-310, 337-338`:** Внутрь шаблонного QSS `build_stylesheet(c)` зашиты цвета светлой темы вместо токенов палитры: `#F1F5F9` для сетки и разделителей `QTableWidget`, `#F8FAFC` для фона холста `QGraphicsView#mapCanvas`, `#BFDBFE`/`#DBEAFE` для `#btnAddPoint`/`#btnCreateGroup`, `#CBD5E1`/`#94A3B8` для скроллбаров. У `QTreeWidget` не задан `color`, а `QCheckBox::indicator:checked` переопределён без галочки (превращается в сплошной синий квадрат).
- **`src/rme_mapper/ui/theme_manager.py:390-393`:** Подписка на смену системной темы вызывает `self.apply_theme(app, ...)`, даже если исходная тема была применена не к `app`; активность тёмного режима для фильтра стилей определяется хрупкой проверкой `"#111827" in qss`.
- **`src/rme_mapper/ui/theme_style_filter.py:33-53`:** `ThemeStyleFilter` заменяет только `background`, `background-color` и `color` для ограниченной таблицы 6-значных HEX-цветов, оставляя светлые границы (`#E2E8F0`, `#D9DDE3`), 3-значный HEX, `rgb(...)` и именованные цвета.
- **Жёсткие цвета в виджетах и моделях:**
  - `points_panel.py:573`: `QColor("#000000")` для текста видимых строк таблицы (чёрный текст на тёмном фоне в Dark Mode).
  - `groups_panel.py:242`: `QColor("#1E293B")` для текста видимых групп.
  - `raw_preview_model.py:63`: светло-голубая подсветка заголовка `QColor(225, 240, 255)`.
  - `properties_panel.py:94, 115, 128, 149, 197`: тёмный текст `#1E293B`/`#334155`/`#475569` и граница `#E2E8F0`.
  - `import_dialog.py:258, 264, 266`: `Qt.GlobalColor.darkGreen` / `red` / `darkYellow`.
  - `audit_features.py:42`: `#D9DDE3` у рамки плавающей панели измерений `#measurementHUD`.

---

## 5. Сборка, упаковка, окружение, инструментарий и артефакты

1. **Несуществующие `hiddenimports` в `GeoPointMapper.spec:94-96`:**  
   Указаны модули `rme_mapper.backends.geopackage`, `rme_mapper.backends.geotiff`, `rme_mapper.backends.online_xyz`, которых нет в `src/rme_mapper/backends/` (фактический состав: `__init__.py`, `base.py`, `factory.py`, `legacy_placeholder.py`, `legacy_raster_placeholder.py`, `modern.py`, `modern_raster.py`, `raster_backend.py`).
2. **Сломанная совместимость с Windows 7 / `PySide2` (`src/rme_mapper/main.py:14-19`, `requirements-win7.txt`, `pyproject.toml:10`, `build_release.py:296`, `GeoPointMapper.spec:109, 137-139`):**  
   Точка входа `main.py` импортирует `PySide6.QtWidgets` напрямую и не подключает шим `qt_compat`; `requirements-win7.txt` заявляет `Python 3.8.10` + `PySide2==5.15.2.1` и не содержит `pandas`, тогда как `pyproject.toml` и `build_release.py` требуют `Python >= 3.12`, а `.spec` требует `pandas` и явно исключает `PySide2`/`PyQt5`/`PyQt6`.
3. **Дефекты в `build_release.py:57-66, 246-254, 373-374`:**  
   Функция `get_canonical_version()` определена дважды (второе определение затеняет первое, теряя проверку наличия `app_info.py` и fallback-парсинг); в итоговом `manifest` строки `"PyInstaller 6.22.3"` и `"Inno Setup 7.1.1"` зашиты константами вместо чтения версий реально установленных инструментов.
4. **Неполные файловые ассоциации в `packaging/installer.iss:58-62`:**  
   Инсталлятор регистрирует ассоциацию только для `.gpmap`, пропуская формат `.rmeproject` (хотя `main.py:45` обрабатывает оба расширения).
5. **Пробелы вспомогательных утилит `tools/audit_metrics.py` и `tools/validate_release.py`:**
   - `audit_metrics.py:15` не учитывает ключи локализации с дефисами `-`, игнорирует error codes формата `code="import.err..."`, не проверяет совпадение плейсхолдеров и дубликаты ключей в словарях.
   - `validate_release.py:95-96` проверяет исключение `"tests"` и `"scratch"` без масок `**/`, отслеживая только каталоги верхнего уровня.
6. **Артефакты в корне репозитория и предупреждения в логах:**
   - `main.py:120` при `--smoke-test` создаёт `smoke_success.txt` в текущем рабочем каталоге; файл `d:\RME-Mapper\smoke_success.txt` остался в корне репозитория (не исключён в `.gitignore`).
   - В `scratch/audit-project-final.log:21-26` зафиксированы два пустых сообщения `Error in sys.excepthook:\n\nOriginal exception was:` и 6 предупреждений `PendingDeprecationWarning` из `raster_warp_service.py`.

