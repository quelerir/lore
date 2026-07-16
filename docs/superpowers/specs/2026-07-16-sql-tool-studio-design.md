# Запуск SQL-инструмента в LangGraph Studio на реальной БД

Дата: 2026-07-16. Статус: утверждён.

**Зависимость:** опирается на
`2026-07-16-db-config-split-design.md` (Toast БД задаётся компонентами
`TOAST_DB_*`, DSN собирает `config.build_dsn`). DB-split делается первым.

## Цель

Запускать SQL-граф (`backend/toast/sql_graph.py`) против живой `loreagent_test`
и визуально видеть ход выполнения: подсветку узлов, состояние на каждом шаге,
входы/выходы, реран. Инструмент — LangGraph Studio (`langgraph dev`).

## Решения обсуждения

| Вопрос | Решение |
| --- | --- |
| Визуализация | LangGraph Studio (локальный сервер `langgraph dev`, UI на smith.langchain.com указывает на localhost; вход — бесплатный аккаунт LangSmith; граф и БД остаются локально) |
| Размещение | Отдельная top-level директория `studio/` (свой uv-проект) — НЕ в `backend/`. Строго опциональная часть проекта |
| Источник кред | Фабрика читает env НАПРЯМУЮ + собирает Toast-DSN через `config.build_dsn` (не через `get_settings()`, чтобы не тянуть обязательные Chainlit-компоненты) |
| Форма ввода | Отдельная входная схема `SqlToolInput` (5 полей) — Studio покажет чистую форму |

## Размещение: отдельная директория `studio/`

Раннер живёт вне `backend/` и `frontend/` — самостоятельный опциональный
uv-проект. Импортирует backend-код (`toast.*`, `config`) через `sys.path`
(как `infra/eval-sql.py`).

```
studio/
  pyproject.toml     # uv-проект: langgraph-cli[inmem] + langgraph, langchain-openai, asyncpg
  langgraph.json
  graph.py           # фабрика: sys.path→backend, сборка графа, export `graph`
  .env.example
  .gitignore         # .env
  README.md          # как запускать
```

## Компоненты

### `studio/graph.py` (новый) — фабрика графа

Добавляет backend в `sys.path`, импортирует `build_sql_graph`, `PgExecutor`,
`build_dsn`. Читает из окружения:
`OPENROUTER_API_KEY` (обязателен), Toast-компоненты `TOAST_DB_*` (обязательны
для DSN), `OPENROUTER_BASE_URL` (дефолт `https://openrouter.ai/api/v1`),
`SQL_MODEL` (дефолт `anthropic/claude-sonnet-4.6`),
`SQL_MAX_QUERIES` (дефолт 3), `SQL_CANDIDATES_PER_ROUND` (дефолт 2).

Собирает Toast-DSN через `config.build_dsn("postgresql", …)`, строит
`PgExecutor(dsn)` + `ChatOpenAI(...)` + `build_sql_graph(...)`, экспортирует
модульную переменную `graph`. Пул БД ленивый — при импорте I/O нет. Отсутствие
обязательных env → `RuntimeError` с внятным текстом (Studio покажет ошибку
загрузки графа).

### Входная схема `SqlToolInput` (в `backend/toast/sql_graph.py`)

TypedDict из 5 входных полей (`question`, `chunk_id`, `table`, `desc_vector`,
`desc_full`). `build_sql_graph` создаёт `StateGraph(SqlToolState,
input=SqlToolInput)`. Это ограничивает форму ввода Studio нужными полями и НЕ
ограничивает выход (`ainvoke` возвращает полное состояние) — `run_sql_tool`,
`make_sql_tool` и тесты не ломаются.

### `studio/langgraph.json` (новый)

```json
{
  "dependencies": ["."],
  "graphs": { "sql_tool": "./graph.py:graph" },
  "env": ".env"
}
```

### `studio/pyproject.toml` (новый)

Минимальный uv-проект. Зависимости: `langgraph-cli[inmem]`, а также рантайм
графа: `langgraph`, `langchain-openai`, `langchain-core`, `asyncpg`,
`pydantic-settings` (для импорта `config`). Backend подключается по `sys.path`,
не как пакет.

### Креды

- `studio/.env` (gitignored) — пользователь кладёт `OPENROUTER_API_KEY` и
  Toast-компоненты `TOAST_DB_HOST/PORT/USER/PASSWORD/NAME`, при желании
  `SQL_MODEL`. Пример — `studio/.env.example`.

### Документация

`studio/README.md`: `cd studio && uv run langgraph dev`, вход в Studio, готовые
фикстуры-входы из отчёта (юристы `toast_tbl_ec48a6d52d16ab405f95`,
грейды `toast_tbl_17a7241d0a976f287103`).

## Тестирование

- `studio/test_graph_smoke.py` (pytest в venv studio): при заданных env
  (`monkeypatch`) модуль `graph` импортируется и компилируется без I/O; без
  обязательных env — `RuntimeError`. Запуск: `cd studio && uv run pytest`.
- Backend-тесты графа/инструмента остаются зелёными (входная схема обратно
  совместима) — проверяется в цикле реализации.
- Ручное: `langgraph dev` + прогон фикстуры юристов → путь
  scope→generate→execute→judge→summarize, `answer` с «Каневский».

## Вне scope (YAGNI)

- Терминальный astream-раннер и статичная mermaid-диаграмма не делаются.
- Прод-интеграция Studio не трогается — это dev-инструмент.
- Backend НЕ делаем pip-устанавливаемым пакетом — импорт через `sys.path`.
