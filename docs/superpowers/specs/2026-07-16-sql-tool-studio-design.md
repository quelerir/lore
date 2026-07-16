# Запуск SQL-инструмента в LangGraph Studio на реальной БД

Дата: 2026-07-16. Статус: утверждён.

## Цель

Запускать SQL-граф (`toast/sql_graph.py`) против живой `loreagent_test` и
визуально видеть ход выполнения: подсветку узлов, состояние на каждом шаге,
входы/выходы, реран. Инструмент — LangGraph Studio (`langgraph dev`).

## Решения обсуждения

| Вопрос | Решение |
| --- | --- |
| Визуализация | LangGraph Studio (локальный сервер `langgraph dev`, UI на smith.langchain.com указывает на localhost; вход — бесплатный аккаунт LangSmith; граф и БД остаются локально) |
| Источник кред | Фабрика читает env НАПРЯМУЮ (не через `get_settings()`), чтобы не тянуть обязательные поля чат-стека (DATABASE_URL/JWT) |
| Форма ввода | Отдельная входная схема `SqlToolInput` (5 полей) — Studio покажет чистую форму |

## Компоненты

### `backend/toast/studio.py` (новый)

Фабрика графа для Studio. Читает из окружения:
`TOAST_DATABASE_URL`, `OPENROUTER_API_KEY` (обязательны),
`OPENROUTER_BASE_URL` (дефолт `https://openrouter.ai/api/v1`),
`SQL_MODEL` (дефолт `anthropic/claude-sonnet-4.6`),
`SQL_MAX_QUERIES` (дефолт 3), `SQL_CANDIDATES_PER_ROUND` (дефолт 2).

Строит `PgExecutor(dsn)` + `ChatOpenAI(...)` + `build_sql_graph(...)` и
экспортирует модульную переменную `graph`. Пул БД ленивый — при импорте I/O
нет. Отсутствие обязательных env → `RuntimeError` с внятным текстом (Studio
покажет ошибку загрузки графа).

### Входная схема `SqlToolInput` (в `toast/sql_graph.py`)

TypedDict из 5 входных полей (`question`, `chunk_id`, `table`, `desc_vector`,
`desc_full`). `build_sql_graph` создаёт `StateGraph(SqlToolState,
input=SqlToolInput)`. Это ограничивает форму ввода Studio нужными полями и НЕ
ограничивает выход (`ainvoke` возвращает полное состояние) — `run_sql_tool`,
`make_sql_tool` и тесты не ломаются.

### `backend/langgraph.json` (новый)

```json
{
  "dependencies": ["."],
  "graphs": { "sql_tool": "./toast/studio.py:graph" },
  "env": ".env"
}
```

### Зависимость и креды

- Dev-зависимость: `langgraph-cli[inmem]`.
- `backend/.env` (gitignored) — пользователь кладёт `TOAST_DATABASE_URL`,
  `OPENROUTER_API_KEY`, при желании `SQL_MODEL`. Пример — `backend/.env.example`.
- `backend/.gitignore` дополняется `.env`.

### Документация

Секция в `docs/usage.md`: `cd backend && uv run langgraph dev`, вход в Studio,
готовые фикстуры-входы из отчёта (юристы `toast_tbl_ec48a6d52d16ab405f95`,
грейды `toast_tbl_17a7241d0a976f287103`).

## Тестирование

- `backend/tests/test_studio.py`: при заданных env (`monkeypatch`) модуль
  `toast.studio` импортируется и `graph` компилируется без I/O; без обязательных
  env — `RuntimeError`. (Импорт с перезагрузкой модуля через `importlib`.)
- Существующие тесты графа/инструмента остаются зелёными (входная схема
  обратно совместима).
- Ручное: `langgraph dev` + прогон фикстуры юристов → путь
  scope→generate→execute→judge→summarize, `answer` с «Каневский».

## Вне scope (YAGNI)

- Терминальный astream-раннер и статичная mermaid-диаграмма не делаются.
- Прод-интеграция Studio не трогается — это dev-инструмент.
