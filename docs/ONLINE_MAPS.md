# Онлайн-карты: Standard / Satellite / Hybrid (Online Basemaps) — GeoPoint Mapper

Документация по поддержке онлайн-тайловых картографических подложек (XYZ Tiles) и политики провайдеров (**Этап 20: Control Check**).

---

## 1. Сводная матрица статусов встроенных провайдеров (Readiness Status)

| Провайдер ID | Название | Тип | Статус готовности | API Ключ | Атрибуция | Логотип | Max Zoom |
|---|---|---|---|---|---|---|---|
| `osm_standard` | OpenStreetMap Standard | Standard | **PRODUCTION READY** | Не требуется | Обязательная (© OpenStreetMap contributors) | Не требуется | 19 |
| `mapbox_satellite` | Mapbox Satellite | Satellite | **CONFIGURED BUT NOT VERIFIED** | Public token (`pk...`) | Обязательная (© Mapbox © OpenStreetMap © Maxar) | Обязателен | 22 |
| `mapbox_hybrid` | Mapbox Satellite Streets | Hybrid | **CONFIGURED BUT NOT VERIFIED** | Public token (`pk...`) | Обязательная (© Mapbox © OpenStreetMap) | Обязателен | 22 |
| `custom_*` | Custom XYZ Server | Custom | **PRODUCTION READY** | Опционально | Настраивается (по умолчанию обязательна) | По требованию | 0..22 |

> [!NOTE]
> Статус `CONFIGURED BUT NOT VERIFIED` означает, что интеграция Mapbox полностью реализована, архитектурно и юридически подготовлена (включая принудительную атрибуцию, логотип и фильтрацию токенов), но в окружении сборки отсутствует публичный токен пользователя для постоянной верификации «живого» API.

---

## 2. Политики встроенных провайдеров

### 2.1. OpenStreetMap Standard (`osm_standard`)
- **Официальный Endpoint**: `https://tile.openstreetmap.org/{z}/{x}/{y}.png`
- **Документация ToS**: [OSM Tile Usage Policy](https://operations.osmfoundation.org/policies/tiles/)
- **Требования к атрибуции**:
  - Атрибуция является **строго обязательной** (`attribution_required = True`).
  - Текст копирайта: `© OpenStreetMap contributors`.
  - В графическом интерфейсе и при экспорте (PNG / JPEG) отключение копирайта заблокировано (чекбокс заблокирован в состоянии Checked).
- **Требования к логотипу**: Отдельный логотип не требуется (`logo_required = False`), достаточен текстовый копирайт со ссылкой.
- **Тип API-ключа**: Не требуется (публичный свободный доступ для умеренного использования).
- **Поведение кэша (HTTP Semantics)**:
  - Метаданные ответа (`ETag`, `Last-Modified`, `Cache-Control`, `Expires`, `stored_at`) сохраняются в файле `.meta` рядом с каждым тайлом.
  - Минимальный TTL при отсутствии заголовков экспирации: **7 дней** (`604800` секунд).
  - Поддержка условных запросов: при истечении TTL отправляются заголовки `If-None-Match` и `If-Modified-Since`.
  - При ответе `HTTP 304 Not Modified` байты повторно не скачиваются, обновляются метаданные `stored_at`, а тайл читается из кэша.
  - Бессрочный (permanent) кэш без валидации строго исключен.
- **Ограничение частоты (Rate Limiting)**:
  - Максимум **2 параллельных потока** загрузки (`OSM_MAX_CONCURRENCY = 2`).
  - Запрещен любой prefetch / bulk download / фоновое сканирование регионов. Запрашивается только видимый экран.
  - Заголовок `User-Agent`: `GeoPoint Mapper/0.12.0 (+https://github.com/gutentag6574/RME-Mapper)`
  - При `HTTP 429`: соблюдается `Retry-After` или устанавливается безопасный кулдаун.
- **Автономный режим (Offline)**: Ранее сохраненные в кэше тайлы отображаются мгновенно; незагруженные тайлы показывают сетку-заглушку.
- **Дата проверки политики**: 2026-09-21.
- **Статус**: **PRODUCTION READY**.

---

### 2.2. Mapbox Satellite (`mapbox_satellite`)
- **Официальный Endpoint**: `https://api.mapbox.com/v4/mapbox.satellite/{z}/{x}/{y}.jpg?access_token={api_key}`
- **Документация ToS**: [Mapbox Raster Tiles API](https://docs.mapbox.com/api/maps/raster-tiles/) и [Mapbox Attribution Guidelines](https://docs.mapbox.com/help/getting-started/attribution/)
- **Требования к атрибуции**:
  - Обязательная атрибуция (`attribution_required = True`).
  - Текст: `© Mapbox © OpenStreetMap © Maxar`.
  - Пользователь не может отключить атрибуцию при экспорте.
- **Требования к логотипу**:
  - Обязателен логотип / водяной знак Mapbox (`logo_required = True`).
  - В рендерере отображается маркировка `mapbox | ...`.
- **Безопасность токенов**:
  - **РАЗРЕШЕН ТОЛЬКО ПУБЛИЧНЫЙ ТОКЕН** (`pk....`, client/public scope: `styles:tiles`).
  - **СЕКРЕТНЫЕ ТОКЕНЫ (`sk....`) СТРОГО ЗАПРЕЩЕНЫ**: приложение блокирует их ввод, не отправляет по сети и не сохраняет в настройках.
  - Токены маскируются в логах (`redaction`), не попадают в файлы проекта `*.gpmap` и не используются в именах каталогов кэша.
  - Хранилище `QSettings` документировано как пользовательские локальные настройки (не secure secret vault).
- **Поведение кэша**: Локальный кэш тайлов ограничен лимитом (по умолчанию 500 МБ) с вытеснением по LRU.
- **Дата проверки политики**: 2026-09-21.
- **Статус**: **CONFIGURED BUT NOT VERIFIED**.

---

### 2.3. Mapbox Satellite Streets (Hybrid) (`mapbox_hybrid`)
- **Официальный Endpoint**: `https://api.mapbox.com/styles/v1/mapbox/satellite-streets-v12/tiles/256/{z}/{x}/{y}?access_token={api_key}`
- **Документация ToS**: [Mapbox Styles API](https://docs.mapbox.com/api/maps/styles/)
- **Требования к атрибуции**:
  - Обязательная атрибуция (`attribution_required = True`): `© Mapbox © OpenStreetMap`.
  - Обязательный логотип Mapbox (`logo_required = True`).
- **Безопасность токенов**: Только публичный `pk....`, секретный `sk....` запрещен.
- **Дата проверки политики**: 2026-09-21.
- **Статус**: **CONFIGURED BUT NOT VERIFIED**.

---

### 2.4. Пользовательский XYZ-сервер (Custom XYZ)
- **Шаблон URL**: Обязательно содержит плейсхолдеры `{z}`, `{x}`, `{y}`.
- **Протокол**: Рекомендуется `https://`. При указании `http://` отображается предупреждение о безопасности.
- **Безопасность ID**: Защита от Path Traversal (`SAFE_PROVIDER_ID_RE`).
- **Атрибуция**: Поле «Атрибуция» и флаг обязательности (по умолчанию включен).
- **Статус**: **PRODUCTION READY**.

---

## 3. Матрица обработки сетевых кодов (Retry Matrix)

| Код HTTP | Поведение загрузчика | Повторы (Retry) | Статус провайдера |
|---|---|---|---|
| `200 OK` | Валидация magic bytes (PNG/JPEG/WebP); отказ от `text/html`; сохранение данных и метаданных. | 0 | Активен |
| `304 Not Modified` | Обновление `stored_at` и метаданных; чтение тайла из дискового кэша без повторного скачивания. | 0 | Активен |
| `401 Unauthorized` | Остановка очереди провайдера, маскирование токена, сигнал `auth_error`. | **0 (No retry)** | Заблокирован |
| `403 Forbidden` | Остановка очереди провайдера, сигнал `auth_error`. | **0 (No retry)** | Заблокирован |
| `404 Not Found` | Сигнал `tile_failed`, отказ от тайла. | **0 (No retry)** | Активен |
| `429 Rate Limit` | Чтение `Retry-After` (секунды или дата) / дефолтный кулдаун 30 сек; приостановка запросов к провайдеру на время кулдауна. | **0 (Пауза)** | Кулдаун |
| `500, 502, 503` | Временный сбой сервера. | **Максимум 1 повтор** | Активен |
| `Timeout / NetworkError` | Истечение таймаута соединения (10 сек). | **Максимум 1 повтор** | Активен |
