# Схема интеграции Audit Read API («FileViewer») в другой бэкенд

> Задача: перенести read-only «FileViewer» из провайдера `apache-airflow-providers-lore`
> в другой бэкенд на том же стеке (FastAPI + Pydantic v2 + psycopg) и связать с фронтендом.
> Источник: `lore-core/airflow-providers/apache-airflow-providers-lore/airflow/providers/lore/audit/`.

**Терминология.** Символа `FileViewer` в коде нет — это фронтовое понятие. На бэкенде ему
соответствует **read-only audit HTTP API** (`audit/http_api/`) поверх фасада `AuditReadService`.
Файловая часть (`/files`, `/runs/*`) — подмножество этого API.

---

## 1. Что это и как устроено

Библиотечный ASGI-модуль: собирает `FastAPI`-приложение с префиксом `/api/v1/audit`, отдающим
**только чтение** персистентных артефактов сплиттера (файлы, прогоны, чанки, payload'ы:
таблицы/картинки, диагностику, сравнение прогонов). Ничего не пишет, не запускает процесс сам —
только строит `app`/`router`.

Слои (сверху вниз):

```
HTTP transport (http_api/)          ← копируем и дорабатываем
├─ routes.py        FastAPI-роутер, 20+ эндпоинтов
├─ contracts.py     Pydantic-модели запросов (валидация + .to_request())
├─ limits.py        AuditHttpLimits — «потолки» сервера
├─ middleware.py    ASGI-кап на размер пути/query/body + access-log
├─ errors.py        единый безопасный конверт ошибок
├─ factory.py       create_audit_app(service, limits) → FastAPI
└─ runtime.py       create_airflow_audit_app(config, …) — сборка с Airflow-хуками

Application facade                   ← переносим как есть (ядро)
└─ read_service.py  AuditReadService — единственная публичная точка, membership-проверки

Data access                          ← переносим + адаптируем под вашу инфраструктуру
├─ read_repositories.py  PostgresAuditReadRepository (SQL по схеме lore_core)
├─ read_adapters.py      PostgresRegisteredTableReader / S3RegisteredImageReader / CurrentSourceObjectReader
├─ read_cursor.py        CursorCodec — HMAC-подписанные пагинационные курсоры
└─ read_contracts.py     DTO/Request-контракты (dataclass, ~1300 строк) — «язык» слоя
```

Поток запроса:
`HTTP → middleware (капы) → route → Pydantic-модель (contracts) → .to_request(limits) →
AuditReadService → Repository/Reader → Postgres/S3 → DTO.to_dict() → JSON`.

---

## 2. Что именно переносить

| Обязательно (ядро чтения) | Роль |
|---|---|
| `http_api/` (весь пакет) | HTTP-обвязка |
| `read_service.py` | фасад с проверками принадлежности |
| `read_repositories.py`, `read_adapters.py`, `read_cursor.py` | доступ к данным |
| `read_contracts.py` | контракты/DTO |
| `image_safety.py`, `postgres_connections.py` | утилиты (растровая валидация, обёртка коннекта) |
| `config/runtime.py` (`LoreRuntimeConfig`) | если используете `runtime.py`-путь сборки |

**Зависимость на `splitter`.** `contracts.py` и `read_contracts.py` импортируют `RunStatus`
из `airflow.providers.lore.splitter.per_file` (enum статусов прогона). Либо тянете
`splitter.per_file`, либо заменяете своим enum со значениями `.value`.

Модуль **самодостаточен**: `routes.py` не знает про Airflow. Airflow появляется только в
`runtime.py` (хуки Postgres/S3). Если целевой бэкенд не на Airflow — используете
`create_audit_app(...)` напрямую и подставляете свои реализации ридеров (см. §7, вариант B).

---

## 3. Конфигурация

Два уровня.

### A. `AuditHttpLimits` (`limits.py`) — серверные потолки, клиент может только понижать

| Поле | Дефолт | Смысл |
|---|---|---|
| `page_size_default` / `page_size_max` | 50 / 100 | размер страницы (max ≤ 10 000) |
| `max_text_bytes` | 1 000 000 | предел текста/inline-картинки (≤ 100 МБ) |
| `max_batch_size` | 100 | размер batch-запросов чанков/референсов |
| `max_filter_count` / `max_filter_values` / `max_complexity` | 8 / 32 / 100 | сложность табличных запросов |
| `timeout_ms` | 5000 | `statement_timeout` в Postgres |

### B. `LoreRuntimeConfig` (`config/runtime.py`) — если берёте `create_airflow_audit_app`

Читается из YAML `schema_version: lore/runtime/v1`, секции `splitter`, `audit`, `viewer`.
Из них строятся лимиты и коннекты:

```yaml
schema_version: lore/runtime/v1
splitter:
  postgres_conn_id: <airflow conn id>      # → пул Postgres
  s3_conn_id: <airflow conn id>            # → S3 для картинок
  storage_mode: postgres                    # единственный поддерживаемый
  storage_schema: lore_core
  # …остальные splitter-поля обязательны схемой, но для чтения не используются
viewer:
  page_size_default: 50
  page_size_max: 100
  source_context_max_chars: 1000000         # → limits.max_text_bytes
  source_url_ttl_seconds: 300               # TTL presigned-URL картинок (30–3600)
  image_preview_max_pixels: 40000000
audit: { enabled: true, ruleset_version: "…", full_on_success: true, contract_on_failed_or_skipped: true }
```

Загрузчик конфига намеренно **отклоняет ключи, похожие на секреты** (`password`, `token`,
`secret`, `dsn`, `uri`…) — секреты только через Airflow Connections, не через YAML.

Кроме конфига `create_airflow_audit_app` требует два колбэка:

- `cursor_key_loader() -> bytes` — ключ HMAC для курсоров, **≥16 байт** (иначе `invalid_config`).
  Один и тот же ключ должен жить между рестартами, иначе выданные курсоры инвалидируются.
- `source_loader(identity, *, max_bytes, timeout_ms) -> bytes` — загрузчик «текущего» исходника
  для source-context (хэш-сверка).

---

## 4. Внешние зависимости

1. **Postgres, схема `lore_core`** — источник данных. Таблицы, которые читает репозиторий:
   `processing_runs`, `processed_files`, `chunks`, `payloads`, `payload_occurrences`,
   `diagnostics` (+ CTE `file_cards`). Целевой бэкенд должен иметь доступ к той же БД/схеме
   (или её реплике). Все запросы идут в транзакции `REPEATABLE READ READ ONLY` с `statement_timeout`.
2. **S3** — только для payload'ов-картинок (inline-байты или presigned-URL). Не нужен, если
   картинки не отдавать.
3. **`source_loader`** — только для эндпоинта source-context.
4. **Python-зависимости**: `fastapi>=0.117,<0.140`, `pydantic>=2.12,<3`, `psycopg==3.3.4`
   (extras `api` + `postgres` в исходном `pyproject`). При не-Airflow сборке `starlette` идёт
   транзитивно с FastAPI.

---

## 5. Эндпоинты (полный список роутера)

`{…}` — path-параметры (≤512 байт, UTF-8).

| Метод | Путь | Назначение |
|---|---|---|
| GET | `/files` | список файлов: `search`, `statuses[]`, `page_size`, `cursor` |
| GET | `/files/detail` | карточка файла: `logical_file_key` |
| GET | `/runs` | прогоны файла: `logical_file_key`, пагинация |
| GET | `/runs/{run_id}` | детали прогона |
| GET | `/runs/{run_id}/manifest` | сводка: счётчики, хэши, capabilities, target_ids |
| GET | `/runs/{run_id}/chunks` | список чанков (превью) |
| POST | `/runs/{run_id}/chunks/query` | batch по `chunk_ids[]` (≤100) |
| GET | `/runs/{run_id}/chunks/{chunk_id}` | детали чанка (display/full/vector text-окна) |
| GET | `…/chunks/{chunk_id}/neighbors` | соседи `before`/`after` |
| GET | `/runs/{run_id}/payloads/{payload_id}` | детали payload |
| GET | `…/payloads/{payload_id}/occurrences` | вхождения |
| GET | `…/payloads/{payload_id}/image` | картинка: inline-байты (`nosniff`) или 307-redirect на presigned-URL |
| GET/POST | `…/payloads/{payload_id}/table/profile\|query\|sample` | табличные payload'ы (колонки/фильтры/сортировка) |
| GET | `/runs/{run_id}/diagnostics` | диагностика (`origins`: splitter/audit_rule) |
| POST | `/runs/{run_id}/references/resolve` | резолв ссылок payload'ов batch'ом |
| GET | `/runs/{run_id}/source-context` | сверка хэша текущего исходника |
| GET | `/comparisons` | сравнение двух прогонов |

---

## 6. Формат данных

**Вход.** Query-параметры и JSON-тела описаны Pydantic-моделями `_ClosedModel`
(`extra="forbid", frozen=True`) — любое лишнее поле → `422/invalid_request`. Целочисленные query
приходят строками и валидируются `StrictInt`-обёртками; строки ограничены по UTF-8-длине
(identity ≤512, cursor ≤4096, search ≤256).

**Выход.** Все ответы — `DTO.to_dict()`, каждый с полем `schema_version`
(напр. `audit-read/file-card/v1`, `audit-read/page/v1`). Списки — пагинированный `ReadPage`:
`{ order_key, items[], next_cursor, truncated }`. Пример `FileCard`:

```json
{ "schema_version":"audit-read/file-card/v1", "logical_file_key":"…",
  "display_name":"…", "latest_status":"succeeded", "run_count":3, "latest_run_id":"…" }
```

**Ошибки.** Единый безопасный конверт `audit-http/error/v1` (`errors.py`), сообщение обезличено
(не раскрывает детали исключения):

```json
{ "schema_version":"audit-http/error/v1", "code":"not_found", "message":"…", "resource":"file" }
```

Коды → статусы: `invalid_request/invalid_cursor/bounds_exceeded`→400, `not_found`→404,
`membership_mismatch/registration_invalid`→409, `capability_unavailable`→503,
`dependency_timeout`→504, `read_failed`→500.

---

## 7. Подключение к целевому FastAPI-бэкенду

### Вариант A — вы на Airflow-провайдере (минимум работы)

```python
app = create_airflow_audit_app(
    config,                       # LoreRuntimeConfig из YAML
    cursor_key_loader=load_key,   # bytes ≥16, стабильный между рестартами
    source_loader=load_source,    # для source-context
    # postgres_hook_factory / s3_hook_factory — опц., по умолчанию Airflow-хуки
)
```

Вернётся самостоятельный `FastAPI`. Чтобы встроить в существующее приложение — берите
**роутер**, а не app:

```python
app.include_router(create_audit_router(service, limits))
install_safe_error_handlers(app)
app.add_middleware(AuditHttpMiddleware)
```

### Вариант B — без Airflow (свой Postgres/S3)

```python
repository = PostgresAuditReadRepository(conn_pool, CursorCodec(key), statement_timeout_ms=…)
service = AuditReadService(
    repository,
    manifest_target_cap=…,
    table_reader=PostgresRegisteredTableReader(conn_pool, codec),
    image_reader=S3RegisteredImageReader(s3_hook, …),   # или свой Protocol-совместимый
    source_reader=CurrentSourceObjectReader(loader),
)
app = create_audit_app(service, AuditHttpLimits(...))
```

`conn_pool` должен быть совместим с `postgres_connections.acquire_postgres_connection`
(контекст-менеджер, отдающий psycopg-соединение). `S3RegisteredImageReader` требует хук с
`generate_presigned_url` и `get_bytes`/`get_key` — если ваш S3-клиент другой, оборачиваете в
адаптер или пишете свой `RegisteredImageReader` (Protocol из `read_service.py`).

Все три ридера — **опциональны**: если не передать, соответствующая capability отдаёт
`capability_unavailable`, а базовое чтение файлов/прогонов/чанков продолжает работать.

---

## 8. Безопасность и границы (сохранить при доработке)

- `AuditHttpMiddleware` рубит по размеру **до** роутинга: path ≤2КБ, query ≤8КБ, body ≤1МБ;
  GET/HEAD/OPTIONS с телом → 400. Логирует обезличенный access-record с `correlation_id`.
- `AuditReadService` на каждом методе проверяет **membership** (например, что чанк принадлежит
  запрошенному run_id) → `409 membership_mismatch`.
- Табличные ридеры — строгий **allowlist колонок** из регистрации; SQL строится через
  `psycopg.sql.Identifier` (без конкатенации).
- Картинки валидируются как безопасный растр + сверка размера/SHA-256; отдаются с
  `X-Content-Type-Options: nosniff`.
- **Аутентификации/авторизации в модуле нет** — это read-only-фасад. AuthN/AuthZ (и, вероятно,
  per-tenant фильтрацию) добавляете на стороне целевого бэкенда как отдельный middleware/зависимость
  поверх роутера.

---

## 9. Что нужно решить перед кодом (для спеки целевого сервиса)

1. **Airflow или нет** в целевом бэкенде → выбор варианта A/B и способ получения коннектов Postgres/S3.
2. **Доступ к схеме `lore_core`**: та же БД, реплика, или данные надо реплицировать? Читатель
   ожидает именно эти таблицы.
3. **Объём переноса**: только файлы+прогоны+чанки, или таблицы/картинки/сравнение тоже
   (тянет S3 и табличный ридер).
4. **AuthN/AuthZ и мультиарендность** — как фронт аутентифицируется и нужно ли ограничивать
   видимость файлов по пользователю/проекту.
5. **`RunStatus`**: тянуть `splitter.per_file` или заменить своим enum.
6. **cursor key** — где хранить стабильный HMAC-ключ курсоров в вашей инфраструктуре.

---

## Ссылки на исходники

Все пути относительно
`lore-core/airflow-providers/apache-airflow-providers-lore/airflow/providers/lore/`:

- `audit/http_api/` — routes, contracts, limits, middleware, errors, factory, runtime
- `audit/read_service.py` — `AuditReadService`
- `audit/read_repositories.py` — `PostgresAuditReadRepository`, токены регистрации
- `audit/read_adapters.py` — табличный/картиночный/source-ридеры
- `audit/read_cursor.py` — `CursorCodec`
- `audit/read_contracts.py` — DTO/Request-контракты
- `audit/image_safety.py`, `audit/postgres_connections.py` — утилиты
- `config/runtime.py` — `LoreRuntimeConfig`
- Тесты: `tests/test_audit_http_{routes,contracts,integration,security}.py`
