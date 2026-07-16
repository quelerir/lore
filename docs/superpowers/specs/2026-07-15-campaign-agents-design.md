# Дизайн: анализ файлов рекламных компаний, два режима агента (Быстрый / Умный)

Дата: 2026-07-15 (переписан после получения `problem-questions-report.html`)
Статус: **реализация отложена решением пользователя 2026-07-16** — TOAST-слой
убран из кода до появления реального интерфейса; двухрежимная архитектура
осталась, инструменты заменены на простые (калькулятор,
`backend/agents/tools.py`). Прототип TOAST целиком в истории git
(коммиты до 265f0d8 в `authentik-sso`); порт/адаптер, guardrails и
eval-кейсы отсюда пригодятся при возврате.

## Контекст

Lore — ассистент по внутренним документам рекламного агентства. Новый
пайплайн раскладывает файлы (XLSX-функционал отделов, реестры сотрудников
и т.п.) в Postgres: реестр `lore_core` (`processed_files`, `payloads`,
`chunks`) и физические таблицы `splitter_toast.toast_tbl_*` («TOAST-слой»,
в проде 114 таблиц из 222 файлов). Отчёт `problem-questions-report.html`
(в корне репо) фиксирует контракт SQL-субагента, обязательные guardrails,
особенности схемы и стартовый eval-набор — этот дизайн следует ему.

Наследуется согласованный дизайн двух режимов
(`backend/docs/superpowers/specs/2026-07-10-two-agent-modes-design.md`):
chat profiles, пакет `agents/`, общий `handle_message`.

## Цель и скоуп

Архитектура + работающий прототип с полу-заглушками:

- **Быстрый режим** — `langgraph` с **фиксированным маршрутом**: жёсткая
  последовательность нод `discover → plan_sql (LLM) → execute → answer
  (LLM)`. LLM не выбирает инструменты — маршрут зашит; модель только
  пишет SELECT и формулирует ответ. Подходит маленьким моделям.
- **Умный режим** — `deepagents` со свободной оркестрацией тех же трёх
  инструментов (discover / inspect / run_select) и контрактом субагента
  в системном промпте.

**Полу-заглушки** = данные и политика, не архитектура: вместо продовой
`loreagent_test` — миниатюрный синтетический слепок той же схемы в
локальном Postgres; policy gate — конфиг-список PII-таблиц с отказом;
SQL-валидация — регэкспы контракта (без полноценного SQL-парсера).

**Вне скоупа:** подключение к реальной `loreagent_test` (отдельный
адаптер, когда появится доступ), RAG по chunks, header-recovery «по
уму» (в прототипе — подсказкой в inspect), автоматический eval в CI
(скрипт руками), UI-выбор модели.

## Архитектура

```
frontend: переключатель «Быстрый | Умный» для нового чата
    └─ setChatProfile("fast"|"deep") перед connect()   (react-client)

backend:
  app.py            @cl.set_chat_profiles (fast — дефолт) + PROFILE_TO_MODE
  agents/
    __init__.py     Mode, build_agent(mode, model=None, store=None)
    base.py         build_model(), PROFILE_TO_MODE, системные промпты
    fast.py         фикс. маршрут: discover → plan_sql → execute → answer
    deep.py         create_deep_agent(tools=make_tools(store), ...)
  toast/
    port.py         ToastStorePort (Protocol) + типы результатов
    pg.py           PgToastStore — asyncpg, read-only, guardrails
    tools.py        make_tools(store) -> 3 @tool для deep-режима
    policy.py       policy gate: PII-таблицы -> отказ до SQL
  init-sql:         backend/init/toast-demo.sql (схемы + синтетика)

infra: chainlit-db получает вторую БД lore_data (demo TOAST-слепок)
```

### Данные-заглушка (`backend/init/toast-demo.sql`)

Вторая БД `lore_data` в существующем инстансе `chainlit-db` (новый
init-скрипт в `docker-entrypoint-initdb.d`). Внутри — те же схемы и
колонки, что в проде: `lore_core.processed_files/payloads/chunks`,
`splitter_toast.toast_tbl_<20 hex>`. Синтетика воспроизводит грабли из
отчёта, чтобы eval-кейсы имели смысл:

1. «Функционал отдела контекстной рекламы» — три параллельные таблицы
   (база компетенций / Middle / Group Head), JOIN по
   `_splitter_source_row` (кейс toast-grade-001);
2. «Реестр сотрудников» — два блока: аналитика с дефектом header-as-data
   (первая запись существует только в `lore_core.chunks.display_text`
   как «Columns: …», кейс toast-roster-001) и короткий блок Legal
   (кейс toast-legal-001);
3. «График отпусков» — PII-таблица для policy gate (toast-privacy-001);
4. Никаких таблиц про «клубы» — abstention-кейс (toast-abstain-001).

Registry воспроизводит текущее состояние прода: `toast_schema`/
`toast_table` в payloads пусты, table id лежит в `payload_id`.

### Порт (`toast/port.py`)

```python
class ToastStorePort(Protocol):
    async def discover(self, document_hint: str) -> list[DiscoveredTable]: ...
        # discovery-запрос из отчёта: source_path, payload_id (=table id),
        # coordinates, table_summary (display_text чанка)
    async def inspect(self, table_id: str) -> TableInfo: ...
        # колонки, row count, header-as-data подсказка из chunks
    async def run_select(self, sql: str) -> SelectResult: ...
        # guardrails до выполнения; rows (max 200) + колонки
```

### Guardrails (`toast/pg.py` + `toast/policy.py`) — по контракту отчёта

- только `SELECT` (одна команда, без `;` внутри), запрет DDL/DML/COPY;
- read-only транзакция + `statement_timeout`;
- allowlist схем `lore_core`, `splitter_toast`, `information_schema`;
  идентификаторы таблиц — `^toast_tbl_[0-9a-f]{20}$`;
- policy gate: обращение к таблицам из PII-списка (`policy.py`, в
  прототипе — таблица отпусков) → отказ «нужно решение
  policy/authorization», SQL не выполняется;
- лимит строк результата; ошибки Postgres возвращаются текстом
  (LLM переформулирует).

### Быстрый режим (`agents/fast.py`) — фиксированный маршрут

```
START → discover      # нода без LLM: store.discover(текст вопроса)
      → plan_sql      # LLM: вопрос + найденные таблицы (+inspect самых
                      #      релевантных) → один SELECT или "NO_TABLE"
      → execute       # нода без LLM: guardrails + run_select
      → answer        # LLM: вопрос + результат → ответ с provenance
      → END
```

- `plan_sql` вернул `NO_TABLE` или discover пуст → `answer` формулирует
  no-table-answer (abstention по контракту, не выдумывать);
- ошибка SQL → одна повторная попытка `plan_sql` с текстом ошибки
  (фиксированная, вторая ошибка → честный отказ);
- state — `TypedDict` с полями `question/tables/sql/result/answer`.

### Умный режим (`agents/deep.py`)

`create_deep_agent(tools=make_tools(store), system_prompt=DEEP_PROMPT,
model=...)`. `DEEP_PROMPT` кодирует цикл контракта (Discover → Inspect →
Plan → Validate → Answer), правила abstention, header-as-data и
обязательный provenance. Инструменты — те же операции порта.

### Выбор режима

Как в дизайне 2026-07-10: `@cl.set_chat_profiles` (`fast` — дефолт,
`deep`), `PROFILE_TO_MODE`, режим фиксируется на треде, `handle_message`
не меняется (оба режима — `CompiledStateGraph`). Фронтенд: сегмент
«Быстрый | Умный» в сайдбаре рядом с «Новый чат», действует на следующий
создаваемый чат; `setChatProfile` перед `connect()` в `SessionBridge`.

## Обработка ошибок

- Postgres `lore_data` недоступна → инструменты возвращают текст ошибки,
  агент честно сообщает (чат не падает);
- невалидный SQL от модели → guardrail-отказ текстом, одна повторная
  попытка (fast) / решение агента (deep);
- PII-таблица → отказ policy gate (см. выше);
- нет релевантных таблиц → no-table-answer.

## Тестирование

- Юниты (pytest, без LLM): guardrails `run_select` (DDL/DML/чужая
  схема/плохой table id/PII — отказ; корректный SELECT — строки);
  discover/inspect против demo-БД; сборка обоих графов; fast-граф с
  FakeModel — маршрут проходит discover→plan→execute→answer, и ветка
  NO_TABLE.
- Eval-скрипт `infra/eval-agents.py` (не CI, живой стек + Ollama):
  прогоняет кейсы отчёта, воспроизводимые на синтетике —
  toast-grade-001, toast-legal-001, toast-privacy-001 (отказ),
  toast-abstain-001 (no-table-answer) — для обоих режимов, ассерты по
  ключевым фактам/запретам из отчёта. toast-mobile-001 и
  toast-roster-001 остаются на этап реального адаптера.
- e2e `infra/e2e-chat.py` — параметр профиля, дымовой вопрос в fast.

## Результаты eval (ночная сессия, Ollama gemma4)

Итог `infra/eval-agents.py` после итераций: **fast 3/4** —
toast-legal-001 (обе записи: строка SQL + header-подсказка),
toast-privacy-001 и toast-abstain-001 (детерминированные гейты) стабильно
PASS; toast-grade-001 плавает (модель иногда пишет невалидный SQL,
одна повторная попытка не всегда спасает). **deep 0–1/4** — deepagents на
маленькой локальной модели регулярно теряет вопрос пользователя и отвечает
генериком; это подтверждает исходную мотивацию быстрого режима
(дизайн 2026-07-10). На более сильной модели deep ожидаемо лучше —
проверить, когда появится доступ.

Починено по ходу eval-итераций: стем-волна discovery (русская морфология),
автоквалификация `splitter_toast.` для голых table id, тег `internal`
против утечки сырого SQL в стрим, детерминированный policy gate до
планирования SQL, механика сбора ответа в eval (update_message, а не
new_message).

## Решения, принятые без пользователя (проверить утром)

1. Прототипный TOAST-слой — вторая БД в `chainlit-db`, а не отдельный
   контейнер/SQLite (Postgres-диалект обязателен: ILIKE, string_agg,
   to_jsonb из контракта; лишний контейнер — перебор).
2. «Фиксированный маршрут» истолкован строго: зашитая последовательность
   нод, LLM не выбирает инструменты (а не ReAct с лимитом итераций).
3. Имена профилей `fast`/`deep` (код) и «Быстрый»/«Умный» (UI).
4. Header-recovery в прототипе — подсказка в `inspect` (display_text
   чанка), без автоматического восстановления строк.
5. langgraph добавляется явной зависимостью бэкенда (сейчас транзитивная
   через deepagents), asyncpg уже есть.
