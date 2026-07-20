# Интеграция FileViewer (audit read API) в монолит `lore` — дизайн

Дата: 2026-07-20 · Статус: черновик на ревью

## 1. Цель

Перенести read-only «FileViewer» (на бэкенде — audit read HTTP API) из провайдера
`apache-airflow-providers-lore` в текущий монолит `lore` (Chainlit + deepagents) **копированием
и объединением в одном репозитории**, без микросервиса. Задача этапа — поднять API под
`/api/v1/audit`, пригодный для потребления существующим React-фронтом (same-origin, та же
авторизация). Сам React-раздел `/files` — отдельный последующий этап (см. §11).

Источник кода:
`/Users/stamplevskiyd/adventum/agent-lore/lore-core/airflow-providers/apache-airflow-providers-lore/airflow/providers/lore/`
(далее `SRC/`). Модуль: `SRC/audit/`.

## 2. Контекст: два стека

| | Целевой монолит `lore` | FileViewer (audit read API) |
|---|---|---|
| Роль | Chainlit-чат + агенты | Read-only фасад над артефактами сплиттера |
| Запуск | `chainlit run app.py` (Chainlit 2.11, FastAPI внутри) | библиотечный FastAPI-роутер/app |
| БД-драйвер | asyncpg (async), за PgBouncer (transaction pooling) | **psycopg3 sync**, `REPEATABLE READ READ ONLY` |
| БД | та же инстанция, схема чата + схема `lore_core` | схема `lore_core` (жёстко в SQL) |
| Auth | `@cl.header_auth_callback` → `verify_ticket` (HS256) | **нет auth** (голый роутер) |
| Airflow | нет | только в `runtime.py` (не берём) |

Ключевые подтверждённые факты:
- **БД `lore_core` — та же инстанция, что TOAST, другая схема, доступ уже есть.**
- SQL репозитория жёстко квалифицирован `lore_core.<table>` → правок схемы не требуется.
- Auth фронта: `Authorization`-заголовок с datacraft HS256-тикетом, проверяется `verify_ticket`
  (`CHAINLIT_JWT_SECRET/AUDIENCE/ISSUER`).
- Chainlit 2.11 отдаёт свой FastAPI-app как `chainlit.server.app` (`app.include_router(...)`).

## 3. Объём

**В объёме (полный read-API):**
- files / runs / chunks / diagnostics / source-context;
- payloads: таблицы (profile/query/sample) и картинки (inline/presigned);
- сравнение прогонов (`/comparisons`);
- транскрипты (поддержаны read-side: `transcript_blocks/speakers/time_regions`).

**Вне объёма:**
- любой write-API. Ревью/комментарии фронта — полностью локальные (IndexedDB), на сервер не идут
  (см. `docs/lore-file-viewer-frontend-spec.md` §10–11) → серверная запись не нужна;
- Airflow-путь сборки (`runtime.py`, хуки Postgres/S3);
- write/engine-сторона аудита (`service.py`, `repository.py`, `ruleset.py`, `rules/`,
  `suppression.py`, `persistence.py`, `airflow_adapters.py`, `engine.py`);
- сам React-раздел `/files` (последующий этап; здесь только совместимость API).

## 4. Архитектура

### 4.1. Вендоринг read-side в `backend/audit/`

Копируем **только read-side** пакета `SRC/audit/` в новый пакет `backend/audit/`.
Импорты `airflow.providers.lore.audit.*` → `audit.*`.

**Копируем:**
```
http_api/            (весь пакет: routes, contracts, limits, middleware, errors, factory, __init__)
read_service.py      AuditReadService — фасад, membership-проверки
read_repositories.py PostgresAuditReadRepository (SQL по lore_core)
read_adapters.py     Postgres table / S3 image / current-source ридеры
read_cursor.py       CursorCodec — HMAC-курсоры
read_contracts.py    DTO/Request-контракты
contracts.py         входные валидируемые модели
registration.py      парсинг регистрации payload'ов
validation.py        safe_json / redact
engine_contracts.py  (нужен registration.py; внешних импортов нет)
image_safety.py      растровая валидация
postgres_connections.py  acquire_postgres_connection (лёгкий, без правок)
```

**НЕ копируем:** `http_api/runtime.py` (Airflow), `service.py`, `repository.py`, `ruleset.py`,
`rules/`, `suppression.py`, `persistence.py`, `airflow_adapters.py`, `engine.py`, `__init__.py`
(верхнеуровневый — перепишем свой минимальный).

**Вендор-шимы** (в `backend/audit/_vendor/`) — закрывают 3 внешних касания из `splitter`:
- `RunStatus` (StrEnum: `active/success/skipped/failed/stale`) + `redact_value` —
  из `SRC/splitter/per_file.py`. Используются в `read_repositories.py`, `read_contracts.py`,
  `contracts.py`, `validation.py`.
- `ImageToastStorageResult`, `TableToastStorageResult` — из `SRC/splitter/storage/contracts.py`
  (файл самодостаточен; переносим целиком либо два dataclass'а). Нужны `registration.py`.

Итог: замкнутый копипаст без Airflow и без пакета `splitter`.

> **Задача при реализации:** перепроверить транзитивное замыкание импортов после копирования
> (`python -c "import audit.http_api"` из `backend/`) — список выше выведен по grep'у, но
> закрытие должно подтвердиться сборкой.

### 4.2. Точка монтирования — подход A

В `backend/app.py` (или отдельный `backend/audit_mount.py`, импортируемый из `app.py`):

```python
from chainlit.server import app as chainlit_app
from audit.http_api.factory import create_audit_app  # или create_audit_router
from audit.http_api.routes import create_audit_router
from audit.http_api.errors import install_safe_error_handlers
from audit.http_api.middleware import AuditHttpMiddleware

router = create_audit_router(service, limits)          # префикс /api/v1/audit — в роутере
chainlit_app.include_router(router, dependencies=[Depends(require_audit_identity)])
install_safe_error_handlers(chainlit_app)
chainlit_app.add_middleware(AuditHttpMiddleware)
```

- Сохраняет entrypoint `chainlit run app.py` → минимум изменений в Dockerfile/compose.
- Sync-роуты (`def`, не `async def`) FastAPI сам уносит в threadpool — event-loop Chainlit
  не блокируется синхронным psycopg.
- **Проверить при реализации:** порядок middleware в стеке Chainlit (GZip/Safari-WS уже висят),
  и что `install_safe_error_handlers` на общем app не перехватывает ошибки чата. При конфликте —
  собрать суб-app через `create_audit_app(...)` и примонтировать через `chainlit_app.mount(
  "/api/v1/audit", audit_subapp)` (тогда middleware/handlers изолированы в суб-app).

Отклонённая альтернатива B (свой FastAPI + `mount_chainlit(app, "app.py", "/chainlit")`) —
даёт глобальный контроль CORS/auth, но меняет entrypoint, Dockerfile (`uvicorn`) и compose.
Оверкилл для текущей задачи; держим в резерве, если понадобится глобальный middleware.

### 4.3. Доступ к БД `lore_core` (sync psycopg за PgBouncer)

FileViewer открывает `REPEATABLE READ READ ONLY` + `statement_timeout`. TOAST-инстанс — за
**PgBouncer в transaction-pooling** (asyncpg там ходит с `statement_cache_size=0`).

- Строим отдельный **sync psycopg-пул** к тому же DSN, что TOAST (host/port/user/pass/name),
  схема `lore_core` уже зашита в SQL — `search_path` менять не нужно.
- **Обязательно `prepare_threshold=None`** (отключить server-side prepared statements) — иначе
  psycopg за transaction-pooling PgBouncer упадёт так же, как упал бы asyncpg с prepared.
  Проверить против того же пулера на этапе 1.
- Адаптер под `acquire_postgres_connection`: нужен объект с методом `.acquire()`, возвращающим
  контекст-менеджер с psycopg-соединением. Оборачиваем `psycopg_pool.ConnectionPool.connection()`:

```python
class _AuditPool:
    def __init__(self, pool): self._pool = pool
    def acquire(self): return self._pool.connection()  # context manager → psycopg conn
```

- Конфиг: новые `AUDIT_DB_*` в `config.py` c фолбэком на `TOAST_DB_*` (та же инстанция).
  Отдельный DSN — на случай выделенной реплики/пользователя read-only.
- Новая зависимость: `psycopg[binary,pool]==3.3.4` рядом с asyncpg.

### 4.4. Ридеры и capabilities (S3 — опционально)

`AuditReadService` принимает три опциональных ридера. Не передан — соответствующая capability
отдаёт `capability_unavailable`, базовое чтение работает.

- **table_reader** — `PostgresRegisteredTableReader(pool, codec)` над тем же psycopg-пулом. Включаем.
- **source_reader** — `CurrentSourceObjectReader(loader)`; `loader` — загрузчик «текущего» исходника
  для source-context. Включаем, если есть доступ к объектам источника; иначе source-context отдаёт
  `capability_unavailable` (фронт показывает «источник недоступен», §7/§13 ТЗ).
- **image_reader** — **опционально**. Нативный `S3RegisteredImageReader` требует хук с
  `generate_presigned_url` + `get_bytes`/`get_key`. Так как Airflow нет — пишем адаптер над boto3,
  реализующий тот же `RegisteredImageReader`-Protocol. Включаем **только когда есть S3-креды**;
  без них `/payloads/{id}/image` → `capability_unavailable` (фронт сохраняет метаданные картинки).
  Конфиг `AUDIT_S3_*` — все поля опциональны; отсутствие = ридер не создаётся.

### 4.5. Auth — переиспользуем механизм фронта

Фронт уже шлёт `Authorization: Bearer <datacraft HS256 ticket>`, который на чате валидирует
`@cl.header_auth_callback` → `verify_ticket`. Для audit-роутера — **та же зависимость**:

```python
def require_audit_identity(authorization: str = Header(...)) -> dict[str, str]:
    token = authorization.removeprefix("Bearer ").strip()
    try:
        return verify_ticket(token)          # тот же CHAINLIT_JWT_SECRET/AUDIENCE/ISSUER
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401)  # вне безопасного конверта audit — это транспортный слой
```

- Вешаем как `dependencies=[Depends(require_audit_identity)]` на `include_router`.
- Тенант-фильтрации нет (по решению): любой залогиненный видит все файлы. `membership`-проверки
  модуля (run/chunk-scoped) остаются как есть.
- 401 отдаём до входа в роутер аудита, поэтому он вне `audit-http/error/v1`-конверта — это
  ожидаемо (транспортная авторизация, не доменная ошибка чтения).

### 4.6. Конфиг, курсоры, лимиты, ошибки

- **Cursor key:** `AUDIT_CURSOR_KEY` — HMAC ≥16 байт, **стабильный между рестартами** (иначе
  выданные курсоры инвалидируются). Из env/секрета; в dev — дефолт в `.env.example`.
- **`AuditHttpLimits`:** дефолты модуля; при необходимости пара полей (`page_size_*`,
  `max_text_bytes`, `timeout_ms`) выносится в `Settings`.
- **Middleware `AuditHttpMiddleware`:** капы path≤2КБ/query≤8КБ/body≤1МБ до роутинга + access-log
  с `correlation_id`. Сохраняем.
- **Ошибки:** единый конверт `audit-http/error/v1` через `install_safe_error_handlers`.
- Всё регистрируем в `backend/config.py` рядом с существующим реестром переменных.

## 5. Зависимости и версии

- Добавляем: `psycopg[binary,pool]==3.3.4`; `boto3` (для image-адаптера, опционально).
- FastAPI/Pydantic v2/Starlette приходят транзитивно с Chainlit 2.11. Модуль объявляет
  `fastapi>=0.117,<0.140` — **берём версию, которую тянет Chainlit** (верхний пин модуля — по сути
  баг, ослабляем). Проверить, что фактическая версия ≥0.117; если Chainlit тянет старее — поднять.
- Python 3.13 (Dockerfile) / 3.14 (текущий venv) — модуль совместим.

## 6. Инфраструктура (docker-compose)

- **БД:** отдельный сервис не нужен — `lore_core` в той же инстанции, что TOAST. Пробрасываем
  `AUDIT_DB_*` (или переиспользуем `TOAST_DB_*`) в сервис `backend`.
- **S3/MinIO:** добавляем сервис MinIO для dev **только когда включаем картинки** (этап 3).
  Прод — реальный S3 через `AUDIT_S3_*`.
- **Env:** `AUDIT_CURSOR_KEY`, `AUDIT_DB_*` (опц.), `AUDIT_S3_*` (опц.) — в `.env.example`.

## 7. Совместимость с фронтом и известные разрывы контракта

API живёт под `/api/v1/audit`, same-origin с чатом → CORS не нужен. DTO оставляем **реальными**
(`audit-read/*`); фронт адаптируется под них. Из сверки `docs/lore-file-viewer-frontend-spec.md`
с кодом:

**7.1. Маппинг кодов ошибок (фронт адаптируется).** Бэкенд отдаёт lowercase-конверт; ТЗ ждёт
UPPERCASE-семантику. Часть «ошибок» ТЗ — это на деле DTO-флаги:

| Frontend (ТЗ §16) | Backend | Механизм |
|---|---|---|
| `NOT_FOUND` | `not_found` | error-конверт |
| `NOT_AVAILABLE` | `capability_unavailable` | error-конверт |
| `PAYLOAD_NOT_REGISTERED` | `registration_invalid` | error-конверт |
| `TOO_LARGE` | `bounds_exceeded` | error-конверт |
| `UPSTREAM_TIMEOUT` | `dependency_timeout` | error-конверт |
| `INVALID_CURSOR` | `invalid_cursor` | error-конверт |
| `TRUNCATED` | — | флаг `truncated` в `ReadPage` (не ошибка) |
| `SOURCE_VERSION_MISMATCH` | — | поле source-context (`match/mismatch/unavailable`), не ошибка |

Плюс backend-коды без прямого экрана в ТЗ: `invalid_request`, `membership_mismatch`,
`read_failed`, внутренний `kind_mismatch`. Таблица маппинга — часть контракта, фиксируется в спеке
фронта.

**7.2. Разрыв в списочной панели `/files`.** ТЗ §4.1 хочет счётчики (таблиц/картинок/диагностик)
и фильтры (pipeline, период, has-tables/has-images, «аномальное число чанков»), сортировки (по
проблемам/чанкам/статусу). Реальность: `FileCard` = `{logical_file_key, display_name,
latest_status, run_count, latest_run_id}`; `FileListQuery` серверно умеет только `search` +
`statuses[]`. Решение:
- **Этап 1 — как есть.** Фронт-панель работает на `search + statuses`; счётчики комментариев и
  AI-замечаний считает локально (они и так в IndexedDB); серверные фасеты деградируют изящно.
- Богатые фасеты/счётчики/сортировки — **отдельный последующий этап**, расширяющий vendored-SQL и
  DTO `FileCard`/`FileListRequest`. Концепты «pipeline» и «аномальное число чанков» требуют проверки
  наличия в схеме `lore_core` (могут отсутствовать — тогда вне объёма).

## 8. Тестирование

- Переносим `SRC/audit/tests/test_audit_http_{routes,contracts,integration,security}.py`,
  адаптируем фикстуры под новый psycopg-пул/адаптер.
- Добавляем smoke-тест: смонтированный роутер отвечает под `/api/v1/audit/...`, auth-гейт
  возвращает 401 без тикета и 200 с валидным.
- Интеграционный тест против реальной `lore_core` (или её слепка) — проверка `prepare_threshold`
  совместимости с PgBouncer.

## 9. Фазировка (в рамках API-only)

1. **Ядро.** Вендоринг + шимы + монтаж (A) + psycopg/PgBouncer-пул + auth-гейт + files/runs/chunks/
   diagnostics/source-context против `lore_core`. Тесты routes/contracts/security + smoke. API живой.
2. **Таблицы + сравнения.** `PostgresRegisteredTableReader` + `/comparisons`. Без S3.
3. **Картинки.** boto3 image-адаптер + MinIO (dev)/S3 (прод), `AUDIT_S3_*`. Включение capability.
4. *(вне этого этапа)* React-раздел `/files` по `docs/lore-file-viewer-frontend-spec.md`.

## 10. Открытые пункты на время реализации

1. **S3-креды/бакет** для картинок — запрашиваются; до получения image-capability выключена
   (опциональна по дизайну).
2. **`source_loader`** для source-context — есть ли доступ к объектам «текущего» исходника; иначе
   capability выключена.
3. Подтвердить транзитивное замыкание импортов после копирования (сборкой).
4. Подтвердить `prepare_threshold=None` достаточно для PgBouncer transaction-pooling.
5. Подтвердить фактическую версию FastAPI, которую тянет Chainlit 2.11 (≥0.117).

## 11. Целевой layout (после интеграции)

```
backend/
  app.py                 + монтаж audit-роутера (подход A) + require_audit_identity
  config.py              + AUDIT_DB_* / AUDIT_S3_* / AUDIT_CURSOR_KEY
  audit/                 ← вендоренный read-side
    __init__.py          (минимальный, свой)
    http_api/            routes, contracts, limits, middleware, errors, factory, __init__
    read_service.py, read_repositories.py, read_adapters.py, read_cursor.py, read_contracts.py
    contracts.py, registration.py, validation.py, engine_contracts.py
    image_safety.py, postgres_connections.py
    pool.py              ← новый: _AuditPool + фабрика psycopg-пула (prepare_threshold=None)
    s3_image_reader.py   ← новый: boto3-адаптер под RegisteredImageReader (этап 3)
    _vendor/
      run_status.py      RunStatus + redact_value
      storage_contracts.py  ImageToastStorageResult, TableToastStorageResult
  tests/
    test_audit_*.py      ← перенесённые + smoke
docker-compose.yml       + (этап 3) minio; проброс AUDIT_* env
```

## 12. Риски

- **PgBouncer × psycopg prepared statements** — главный технический риск; митигируется
  `prepare_threshold=None` + интеграционный тест на этапе 1.
- **Middleware/handlers на общем Chainlit-app** — возможный конфликт; митигируется fallback'ом на
  примонтированный суб-app (§4.2).
- **Разрыв контракта списочной панели** — не блокирует этап 1; расширение API вынесено в
  отдельный этап (§7.2).
- **Версия FastAPI** — потенциальный конфликт пинов; проверяется на сборке (§5).
```
