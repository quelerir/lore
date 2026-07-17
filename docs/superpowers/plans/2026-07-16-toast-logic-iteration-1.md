# Toast-логика (итерация 1) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Read-only SQL-субагент над TOAST-таблицами `loreagent_test` как инструмент `query_document_tables` в обоих режимах агента + перевод backend на OpenRouter.

**Architecture:** Детерминированный пайплайн discover → inspect → policy → plan SQL (LLM) → validate → execute, упакованный в один LangChain-инструмент. Ядро (`port`, `pg`, `guardrails`, `policy`) восстанавливается из git history (`git show 5022ddf^:<path>`) с точечными изменениями; новый модуль — только `toast/subagent.py`. Режимы fast/deep не меняются.

**Tech Stack:** Python 3.13, uv, asyncpg, langchain-openai (OpenRouter), langgraph, deepagents, pytest.

**Spec:** `docs/superpowers/specs/2026-07-16-toast-logic-design.md`

## Global Constraints

- Рабочая директория для команд: `backend/` (uv-проект там). Запуск тестов: `cd backend && uv run pytest ...`.
- Комментарии и docstrings — по-русски, в стиле существующего кода.
- Юзер БД пишущий → защита в коде: READ ONLY транзакции, `statement_timeout` 5000 мс, `MAX_ROWS = 200`.
- Реальный PII id графика отпусков: `toast_tbl_9c6dcab0dfdd486cfddf` (в старом коде был фейковый `toast_tbl_e1b2c3d4e5f6a7b8c9d0`).
- Env-переменные: `TOAST_DATABASE_URL`, `MODEL_PROVIDER` (default `openrouter`), `OPENROUTER_API_KEY`, `OPENROUTER_MODEL` (default `anthropic/claude-haiku-4.5`), `OPENROUTER_BASE_URL` (default `https://openrouter.ai/api/v1`).
- Существующие тесты (`test_agents.py`, `test_app_imports.py`, `test_auth.py`, `test_oauth.py`) должны оставаться зелёными после каждой задачи.

---

### Task 1: Ядро toast — port, guardrails, policy

Восстановить из git history контракты и валидацию; policy — с реальным PII id.

**Files:**
- Create: `backend/toast/__init__.py` (пустой)
- Create: `backend/toast/port.py`
- Create: `backend/toast/guardrails.py`
- Create: `backend/toast/policy.py`
- Modify: `backend/pyproject.toml` (packages)
- Test: `backend/tests/test_guardrails.py`

**Interfaces:**
- Produces: `ToastStorePort` (Protocol: `discover(document_hint) -> list[DiscoveredTable]`, `inspect(table_id) -> TableInfo`, `run_select(sql) -> SelectResult | str`); типы `DiscoveredTable{source_path, table_id, coordinates, summary}`, `TableInfo{table_id, columns, row_count, header_hint}`, `SelectResult{columns, rows, row_count, truncated}`; `validate_select(sql) -> str | None`; `qualify_toast_tables(sql) -> str`; `check_policy(sql) -> str | None`; `PII_TABLES`, `POLICY_REFUSAL`, `TOAST_TABLE_RE`.

- [ ] **Step 1: Написать падающий тест**

Восстановить старый тест и заменить PII id на реальный:

```bash
cd /Users/stamplevskiyd/development/lore
git show 5022ddf^:backend/tests/test_guardrails.py > backend/tests/test_guardrails.py
```

Затем в `backend/tests/test_guardrails.py` заменить тест `test_pii_table_gated` на:

```python
def test_pii_table_gated():
    # Реальный id графика отпусков 2026 из problem-questions-report.html
    sql = "SELECT vacation_start FROM splitter_toast.toast_tbl_9c6dcab0dfdd486cfddf"
    assert check_policy(sql) is not None
    assert check_policy(OK) is None
```

- [ ] **Step 2: Убедиться, что тест падает**

Run: `cd backend && uv run pytest tests/test_guardrails.py -v`
Expected: FAIL/ERROR — `ModuleNotFoundError: No module named 'toast'`

- [ ] **Step 3: Восстановить модули**

```bash
cd /Users/stamplevskiyd/development/lore
touch backend/toast/__init__.py
git show 5022ddf^:backend/toast/port.py > backend/toast/port.py
git show 5022ddf^:backend/toast/guardrails.py > backend/toast/guardrails.py
git show 5022ddf^:backend/toast/policy.py > backend/toast/policy.py
```

В `backend/toast/policy.py` заменить содержимое целиком на:

```python
"""Policy gate: PII-таблицы требуют решения authorization ДО выполнения SQL.

Итерация 1 — детерминированный block-list (БД живая, график отпусков
реальный). Полноценный authz-gate — итерация 3 спеки.
"""

PII_TABLES = frozenset({"toast_tbl_9c6dcab0dfdd486cfddf"})  # график отпусков 2026

POLICY_REFUSAL = (
    "Отказ policy gate: таблица содержит персональные данные "
    "(график отпусков). Нужно решение policy/authorization; "
    "без него SQL не выполняется."
)


def check_policy(sql: str) -> str | None:
    low = sql.lower()
    for table in PII_TABLES:
        if table in low:
            return POLICY_REFUSAL
    return None
```

В `backend/pyproject.toml` добавить пакет `toast`:

```toml
[tool.setuptools]
py-modules = ["app", "auth"]
packages = ["agents", "toast"]
```

- [ ] **Step 4: Убедиться, что тесты проходят**

Run: `cd backend && uv run pytest tests/test_guardrails.py -v`
Expected: PASS (все тесты)

Run: `cd backend && uv run pytest`
Expected: PASS (существующие тесты не сломаны)

- [ ] **Step 5: Commit**

```bash
git add backend/toast backend/tests/test_guardrails.py backend/pyproject.toml
git commit -m "feat(toast): restore port, guardrails, policy core with real PII table id"
```

---

### Task 2: PgToastStore — READ ONLY подключение к loreagent_test

**Files:**
- Create: `backend/toast/pg.py`
- Test: `backend/tests/test_toast_store.py` (integration, skip без `TOAST_DATABASE_URL`)

**Interfaces:**
- Consumes: `toast.guardrails.{TOAST_TABLE_RE, qualify_toast_tables, validate_select}`, `toast.policy.check_policy`, типы из `toast.port`.
- Produces: `PgToastStore(dsn)` с методами протокола `ToastStorePort` и `close()`; константы `MAX_ROWS = 200`, `STATEMENT_TIMEOUT_MS = 5000`.

- [ ] **Step 1: Восстановить модуль и добавить READ ONLY-защиту**

```bash
cd /Users/stamplevskiyd/development/lore
git show 5022ddf^:backend/toast/pg.py > backend/toast/pg.py
```

В `backend/toast/pg.py` заменить создание пула в `_acquire_pool` (юзер БД пишущий — read-only навязываем на уровне сессии, а не только транзакции `run_select`):

```python
    async def _acquire_pool(self) -> asyncpg.Pool:
        if self._pool is None:
            self._pool = await asyncpg.create_pool(
                self._dsn,
                min_size=0,
                max_size=3,
                command_timeout=STATEMENT_TIMEOUT_MS / 1000,
                server_settings={
                    # Юзер БД пишущий — read-only и таймаут навязываем сами.
                    "default_transaction_read_only": "on",
                    "statement_timeout": str(STATEMENT_TIMEOUT_MS),
                },
            )
        return self._pool
```

Остальное (трёхволновый discovery, inspect, run_select с `conn.transaction(readonly=True)`, `_plain`) — без изменений.

- [ ] **Step 2: Написать интеграционные тесты против живой БД**

Создать `backend/tests/test_toast_store.py` (ожидания — реальные таблицы из problem-questions-report.html; это диагностика против живой `loreagent_test`, без DSN пропускается):

```python
import asyncio
import os

import pytest

DSN = os.environ.get("TOAST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not DSN, reason="TOAST_DATABASE_URL not set")

# Реальные таблицы кейса «грейды контекстной рекламы» из отчёта
GRADE_BASE = "toast_tbl_17a7241d0a976f287103"
GRADE_MIDDLE = "toast_tbl_e765505051472ed91b81"
GRADE_HEAD = "toast_tbl_e04534bd1cd4501a7e85"


def _run(coro):
    return asyncio.run(coro)


def _store():
    from toast.pg import PgToastStore

    return PgToastStore(DSN)


def test_discover_finds_grade_tables():
    store = _store()

    async def run():
        try:
            return await store.discover("отдел контекстной рекламы")
        finally:
            await store.close()

    ids = {t["table_id"] for t in _run(run())}
    assert {GRADE_BASE, GRADE_MIDDLE, GRADE_HEAD} <= ids


def test_discover_empty_for_unknown_topic():
    # Negative control отчёта: таблиц про «следы»/толстовки нет
    store = _store()

    async def run():
        try:
            return await store.discover("фирменная толстовка следы начисление")
        finally:
            await store.close()

    assert _run(run()) == []


def test_inspect_returns_columns_and_rows():
    store = _store()

    async def run():
        try:
            return await store.inspect(GRADE_BASE)
        finally:
            await store.close()

    info = _run(run())
    assert "column_1" in info["columns"]
    assert info["row_count"] > 0


def test_run_select_rejects_mutation_and_allows_select():
    store = _store()

    async def run():
        try:
            bad = await store.run_select("DROP TABLE lore_core.payloads")
            ok = await store.run_select(
                f'SELECT count(*) AS n FROM splitter_toast."{GRADE_BASE}"'
            )
            return bad, ok
        finally:
            await store.close()

    bad, ok = _run(run())
    assert isinstance(bad, str) and "Отказ" in bad
    assert not isinstance(ok, str) and ok["row_count"] == 1
```

- [ ] **Step 3: Прогнать тесты**

Run: `cd backend && uv run pytest tests/test_toast_store.py -v`
Expected: SKIPPED (4 skipped — `TOAST_DATABASE_URL not set`); при наличии DSN — PASS.

Если DSN доступен локально, прогнать с ним:
`cd backend && TOAST_DATABASE_URL=<dsn> uv run pytest tests/test_toast_store.py -v` → PASS.

Run: `cd backend && uv run pytest`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add backend/toast/pg.py backend/tests/test_toast_store.py
git commit -m "feat(toast): PgToastStore with session-level read-only and statement timeout"
```

---

### Task 3: Субагент — детерминированный пайплайн

Новый модуль: логика старого fast-графа как обычная async-функция со структурированным результатом.

**Files:**
- Create: `backend/toast/subagent.py`
- Create: `backend/tests/fakes.py` (общие фейки; `ScriptedChatModel` переезжает сюда из `test_agents.py`)
- Modify: `backend/tests/test_agents.py` (импорт `ScriptedChatModel` из fakes)
- Test: `backend/tests/test_subagent.py`

**Interfaces:**
- Consumes: `ToastStorePort`, `toast.policy.{PII_TABLES, POLICY_REFUSAL}`.
- Produces: `async run_toast_subagent(model: BaseChatModel, store: ToastStorePort, question: str) -> SubagentResult`, где `SubagentResult` — TypedDict `{status: "ok"|"no_table"|"refused"|"error", rows, row_count, truncated, sql, sources: list[{source_path, table_id, coordinates}], header_hints: dict[table_id, str], message}` (поля кроме `status` — опциональные). Константа `MAX_TABLES = 5`.

- [ ] **Step 1: Вынести ScriptedChatModel в fakes**

Создать `backend/tests/fakes.py`:

```python
"""Общие фейки для тестов агентов и субагента."""

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.outputs import ChatGeneration, ChatResult


class ScriptedChatModel(BaseChatModel):
    """Отдаёт заранее заданные AIMessage (с tool_calls) по одному на вызов.

    Не реализует _stream: BaseChatModel.astream отдаст ответ одним чанком —
    именно так tool_calls доезжают до графа без потерь.
    """

    responses: list

    @property
    def _llm_type(self) -> str:
        return "scripted"

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        return ChatResult(
            generations=[ChatGeneration(message=self.responses.pop(0))]
        )

    def bind_tools(self, tools, **kwargs):
        return self  # tool_calls зашиты в responses


class FakeToastStore:
    """ToastStorePort на заранее заданных данных; пишет выполненные SQL."""

    def __init__(self, tables=None, infos=None, select_results=None):
        self.tables = tables or []
        self.infos = infos or {}
        self.select_results = list(select_results or [])
        self.executed: list[str] = []

    async def discover(self, document_hint):
        return self.tables

    async def inspect(self, table_id):
        return self.infos[table_id]

    async def run_select(self, sql):
        self.executed.append(sql)
        return self.select_results.pop(0)
```

В `backend/tests/test_agents.py` удалить класс `ScriptedChatModel` и импорты `BaseChatModel`, `ChatGeneration`, `ChatResult` (если больше не используются), добавить:

```python
from fakes import ScriptedChatModel
```

Run: `cd backend && uv run pytest tests/test_agents.py -v`
Expected: PASS

- [ ] **Step 2: Написать падающие тесты субагента**

Создать `backend/tests/test_subagent.py`:

```python
import asyncio

from langchain_core.messages import AIMessage

from fakes import FakeToastStore, ScriptedChatModel
from toast.policy import POLICY_REFUSAL

TBL_A = "toast_tbl_17a7241d0a976f287103"
TBL_B = "toast_tbl_e765505051472ed91b81"
PII = "toast_tbl_9c6dcab0dfdd486cfddf"


def _table(table_id, source="функционал Отдел контекстной рекламы.xlsx"):
    return {
        "table_id": table_id,
        "source_path": source,
        "coordinates": "A1:C10",
        "summary": "Columns: ...",
    }


def _info(table_id, header_hint=None):
    return {
        "table_id": table_id,
        "columns": ["_splitter_source_row", "column_1", "column_2"],
        "row_count": 42,
        "header_hint": header_hint,
    }


def _run(model, store, question="вопрос"):
    from toast.subagent import run_toast_subagent

    return asyncio.run(run_toast_subagent(model, store, question))


def test_happy_path_returns_rows_sql_and_provenance():
    store = FakeToastStore(
        tables=[_table(TBL_A), _table(TBL_B)],
        infos={TBL_A: _info(TBL_A, header_hint="Columns: Вадим Шестаков ..."),
               TBL_B: _info(TBL_B)},
        select_results=[{
            "columns": ["column_1"],
            "rows": [{"column_1": "x"}],
            "row_count": 1,
            "truncated": False,
        }],
    )
    model = ScriptedChatModel(
        responses=[AIMessage(content=f"SELECT column_1 FROM {TBL_A}")]
    )
    result = _run(model, store)
    assert result["status"] == "ok"
    assert result["rows"] == [{"column_1": "x"}]
    assert result["sql"].startswith("SELECT")
    assert {s["table_id"] for s in result["sources"]} == {TBL_A, TBL_B}
    assert TBL_A in result["header_hints"]
    assert store.executed == [f"SELECT column_1 FROM {TBL_A}"]


def test_empty_discovery_returns_no_table_without_llm():
    store = FakeToastStore(tables=[])
    model = ScriptedChatModel(responses=[])  # LLM не должна вызываться
    result = _run(model, store)
    assert result["status"] == "no_table"


def test_model_no_table_verdict():
    store = FakeToastStore(tables=[_table(TBL_A)], infos={TBL_A: _info(TBL_A)})
    model = ScriptedChatModel(responses=[AIMessage(content="NO_TABLE")])
    result = _run(model, store)
    assert result["status"] == "no_table"
    assert store.executed == []


def test_all_pii_tables_refused_before_planning():
    store = FakeToastStore(tables=[_table(PII)], infos={PII: _info(PII)})
    model = ScriptedChatModel(responses=[])  # до планирования не доходит
    result = _run(model, store)
    assert result["status"] == "refused"
    assert result["message"] == POLICY_REFUSAL
    assert store.executed == []


def test_policy_refusal_from_store_not_retried():
    store = FakeToastStore(
        tables=[_table(TBL_A), _table(PII)],
        infos={TBL_A: _info(TBL_A), PII: _info(PII)},
        select_results=["Отказ policy gate: таблица содержит персональные данные"],
    )
    model = ScriptedChatModel(
        responses=[AIMessage(content=f"SELECT * FROM {PII}")]
    )
    result = _run(model, store)
    assert result["status"] == "refused"
    assert len(store.executed) == 1  # без retry


def test_sql_error_retried_once_then_ok():
    store = FakeToastStore(
        tables=[_table(TBL_A)],
        infos={TBL_A: _info(TBL_A)},
        select_results=[
            "Ошибка SQL: column \"nope\" does not exist",
            {"columns": ["column_1"], "rows": [], "row_count": 0, "truncated": False},
        ],
    )
    model = ScriptedChatModel(
        responses=[
            AIMessage(content=f"SELECT nope FROM {TBL_A}"),
            AIMessage(content=f"SELECT column_1 FROM {TBL_A}"),
        ]
    )
    result = _run(model, store)
    assert result["status"] == "ok"
    assert len(store.executed) == 2


def test_two_sql_errors_return_error_status():
    store = FakeToastStore(
        tables=[_table(TBL_A)],
        infos={TBL_A: _info(TBL_A)},
        select_results=[
            "Ошибка SQL: синтаксис",
            "Ошибка SQL: синтаксис снова",
        ],
    )
    model = ScriptedChatModel(
        responses=[
            AIMessage(content="SELECT ??"),
            AIMessage(content="SELECT ?!"),
        ]
    )
    result = _run(model, store)
    assert result["status"] == "error"
    assert "синтаксис снова" in result["message"]


def test_truncated_flag_passthrough():
    store = FakeToastStore(
        tables=[_table(TBL_A)],
        infos={TBL_A: _info(TBL_A)},
        select_results=[{
            "columns": ["column_1"],
            "rows": [{"column_1": "x"}],
            "row_count": 200,
            "truncated": True,
        }],
    )
    model = ScriptedChatModel(
        responses=[AIMessage(content=f"SELECT column_1 FROM {TBL_A}")]
    )
    result = _run(model, store)
    assert result["status"] == "ok"
    assert result["truncated"] is True
```

- [ ] **Step 3: Убедиться, что тесты падают**

Run: `cd backend && uv run pytest tests/test_subagent.py -v`
Expected: FAIL/ERROR — `ModuleNotFoundError: No module named 'toast.subagent'`

- [ ] **Step 4: Реализовать субагента**

Создать `backend/toast/subagent.py`:

```python
"""Toast-субагент: детерминированный пайплайн из problem-questions-report.html.

discover → inspect → policy → plan SQL (LLM) → validate/execute → результат.
LLM используется ровно в одной точке — планирование SELECT по уже найденной
схеме. Один retry при ошибке SQL. Дисциплина шагов зашита в код, а не в
промпт — не зависит от качества модели.
"""

import json
from typing import Any, Literal, TypedDict

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage

from toast.policy import PII_TABLES, POLICY_REFUSAL
from toast.port import ToastStorePort

MAX_TABLES = 5

PLAN_PROMPT = (
    "Ты пишешь SQL по таблицам, извлечённым из внутренних документов "
    "(Postgres). Правила: РОВНО ОДИН SELECT; только схемы lore_core и "
    "splitter_toast; параллельные таблицы одного листа соединяются по "
    "_splitter_source_row. Верни только SQL без пояснений и без markdown. "
    "Если найденные таблицы не подходят к вопросу — верни ровно NO_TABLE."
)

NO_TABLE_MESSAGE = (
    "В извлечённых таблицах нет данных для ответа на этот вопрос "
    "(no-table-answer)."
)


class SubagentResult(TypedDict, total=False):
    status: Literal["ok", "no_table", "refused", "error"]
    rows: list[dict[str, Any]]
    row_count: int
    truncated: bool
    sql: str
    sources: list[dict[str, Any]]
    header_hints: dict[str, str]
    message: str


def _sources(tables: list[dict]) -> list[dict[str, Any]]:
    return [
        {
            "source_path": t["source_path"],
            "table_id": t["table_id"],
            "coordinates": t["coordinates"],
        }
        for t in tables
    ]


async def _plan_sql(
    model: BaseChatModel, question: str, tables: list[dict], error: str | None
) -> str:
    prompt = (
        f"Вопрос: {question}\n\n"
        f"Найденные таблицы:\n{json.dumps(tables, ensure_ascii=False, default=str)}"
    )
    if error:
        prompt += f"\n\nПредыдущий SQL не выполнился: {error}\nИсправь запрос."
    # Тег internal: handle_message не выводит эти токены пользователю
    # (langgraph stream_mode="messages" отдаёт токены и из ainvoke).
    reply = await model.ainvoke(
        [SystemMessage(PLAN_PROMPT), HumanMessage(prompt)],
        config={"tags": ["internal"]},
    )
    sql = str(reply.content).strip().strip("`")
    if sql.lower().startswith("sql"):
        sql = sql[3:].strip()
    return sql


async def run_toast_subagent(
    model: BaseChatModel, store: ToastStorePort, question: str
) -> SubagentResult:
    tables = await store.discover(question)
    if not tables:
        return SubagentResult(status="no_table", message=NO_TABLE_MESSAGE)

    detailed: list[dict] = []
    for t in tables[:MAX_TABLES]:
        info = await store.inspect(t["table_id"])
        detailed.append(
            {
                **t,
                "columns": info["columns"],
                "row_count": info["row_count"],
                "header_hint": info["header_hint"],
            }
        )

    # Policy gate ДО планирования (детерминированно, не доверяем LLM):
    # если все найденные таблицы — PII, SQL не планируем вовсе.
    if all(t["table_id"] in PII_TABLES for t in detailed):
        return SubagentResult(
            status="refused", message=POLICY_REFUSAL, sources=_sources(detailed)
        )

    sql = ""
    error: str | None = None
    for _ in range(2):  # первая попытка + один retry
        sql = await _plan_sql(model, question, detailed, error)
        if sql == "NO_TABLE":
            return SubagentResult(
                status="no_table",
                message=NO_TABLE_MESSAGE,
                sources=_sources(detailed),
            )
        result = await store.run_select(sql)
        if isinstance(result, str):
            # Policy-отказ окончателен; отказы guardrails и ошибки SQL —
            # повод один раз перепланировать запрос.
            if result.startswith("Отказ policy"):
                return SubagentResult(
                    status="refused",
                    message=result,
                    sql=sql,
                    sources=_sources(detailed),
                )
            error = result
            continue
        return SubagentResult(
            status="ok",
            rows=result["rows"],
            row_count=result["row_count"],
            truncated=result["truncated"],
            sql=sql,
            sources=_sources(detailed),
            header_hints={
                t["table_id"]: t["header_hint"]
                for t in detailed
                if t.get("header_hint")
            },
        )
    return SubagentResult(
        status="error",
        message=error or "неизвестная ошибка",
        sql=sql,
        sources=_sources(detailed),
    )
```

- [ ] **Step 5: Убедиться, что тесты проходят**

Run: `cd backend && uv run pytest tests/test_subagent.py tests/test_agents.py -v`
Expected: PASS

Run: `cd backend && uv run pytest`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add backend/toast/subagent.py backend/tests/fakes.py backend/tests/test_subagent.py backend/tests/test_agents.py
git commit -m "feat(toast): deterministic subagent pipeline with single SQL retry"
```

---

### Task 4: Инструмент query_document_tables + промпты

**Files:**
- Modify: `backend/agents/tools.py`
- Modify: `backend/agents/base.py` (только SYSTEM_PROMPT/DEEP_PROMPT)
- Modify: `backend/agents/__init__.py`
- Test: `backend/tests/test_agents.py` (дополнить)

**Interfaces:**
- Consumes: `run_toast_subagent(model, store, question)` из Task 3; `ToastStorePort`.
- Produces: `make_tools(model: BaseChatModel | None = None, store: ToastStorePort | None = None) -> list[BaseTool]` — `[calculator]` без store, `[calculator, query_document_tables]` с моделью и store; `build_agent(mode, model=None, store=None)`.

- [ ] **Step 1: Написать падающие тесты**

Добавить в `backend/tests/test_agents.py`:

```python
def test_make_tools_without_store_is_calculator_only():
    names = [t.name for t in make_tools()]
    assert names == ["calculator"]


def test_make_tools_with_store_adds_toast_tool():
    from fakes import FakeToastStore

    model = FakeListChatModel(responses=["x"])
    names = [t.name for t in make_tools(model, FakeToastStore())]
    assert names == ["calculator", "query_document_tables"]


def test_query_document_tables_returns_no_table_json():
    import json

    from fakes import FakeToastStore

    model = FakeListChatModel(responses=["x"])
    tools = make_tools(model, FakeToastStore(tables=[]))
    toast_tool = tools[1]
    raw = asyncio.run(toast_tool.ainvoke({"question": "про клубы"}))
    assert json.loads(raw)["status"] == "no_table"


def test_query_document_tables_wraps_connection_errors():
    import json

    class BrokenStore:
        async def discover(self, document_hint):
            raise OSError("connection refused")

    model = FakeListChatModel(responses=["x"])
    tools = make_tools(model, BrokenStore())
    raw = asyncio.run(tools[1].ainvoke({"question": "вопрос"}))
    assert json.loads(raw)["status"] == "error"
```

- [ ] **Step 2: Убедиться, что тесты падают**

Run: `cd backend && uv run pytest tests/test_agents.py -v`
Expected: FAIL — `make_tools() takes 0 positional arguments` / нет инструмента `query_document_tables`

- [ ] **Step 3: Реализовать**

В `backend/agents/tools.py` заменить `make_tools` и добавить фабрику (импорты дополнить):

```python
import json

from langchain_core.language_models.chat_models import BaseChatModel

from toast.port import ToastStorePort
from toast.subagent import run_toast_subagent


def _make_query_document_tables(
    model: BaseChatModel, store: ToastStorePort
) -> BaseTool:
    @tool
    async def query_document_tables(question: str) -> str:
        """Найти ответ на вопрос в таблицах из внутренних документов.

        Используй для вопросов о сотрудниках, отделах, грейдах,
        компетенциях и содержимом рабочих файлов. Передавай вопрос
        целиком. Возвращает JSON: status (ok|no_table|refused|error),
        rows, sql, sources (файл и таблица — укажи их в ответе),
        header_hints (записи, потерянные при извлечении — тоже источник
        данных, не теряй их).
        """
        # Ошибки соединения с БД не PostgresError и не ловятся в store —
        # спека требует status=error, а не исключение из инструмента.
        try:
            result = await run_toast_subagent(model, store, question)
        except Exception as e:  # noqa: BLE001 — граница инструмента
            result = {"status": "error", "message": f"техническая ошибка: {e}"}
        return json.dumps(result, ensure_ascii=False, default=str)

    return query_document_tables


def make_tools(
    model: BaseChatModel | None = None,
    store: ToastStorePort | None = None,
) -> list[BaseTool]:
    tools: list[BaseTool] = [calculator]
    if model is not None and store is not None:
        tools.append(_make_query_document_tables(model, store))
    return tools
```

В `backend/agents/base.py` заменить промпты:

```python
SYSTEM_PROMPT = (
    "Ты — ассистент datacraft. Отвечай на вопросы пользователя ясно и "
    "кратко, по-русски. Для любых вычислений используй инструмент "
    "calculator — не считай в уме. Для вопросов о сотрудниках, отделах, "
    "грейдах, компетенциях и внутренних документах используй инструмент "
    "query_document_tables. Работа с его результатом: указывай источник "
    "(source_path и table_id); rows и header_hints — два РАЗНЫХ источника "
    "записей, перечисляй записи из обоих (ничего не теряй); при "
    "status=no_table честно скажи, что ответа в таблицах нет — не "
    "выдумывай; при status=refused передай отказ policy gate, не обходи "
    "его; при truncated=true упомяни, что результат неполный."
)

DEEP_PROMPT = SYSTEM_PROMPT + (
    " Если задача сложная — разбей её на шаги и решай последовательно."
)
```

В `backend/agents/__init__.py` заменить `build_agent`:

```python
from toast.port import ToastStorePort


def build_agent(
    mode: Mode,
    model: BaseChatModel | None = None,
    store: ToastStorePort | None = None,
) -> CompiledStateGraph:
    if model is None:
        model = build_model()
    tools = make_tools(model, store)
    if mode is Mode.DEEP:
        return build_deep_agent(model, tools)
    return build_fast_agent(model, tools)
```

- [ ] **Step 4: Убедиться, что тесты проходят**

Run: `cd backend && uv run pytest`
Expected: PASS (в т.ч. старые тесты fast-графа — make_tools() без аргументов по-прежнему валиден)

- [ ] **Step 5: Commit**

```bash
git add backend/agents/tools.py backend/agents/base.py backend/agents/__init__.py backend/tests/test_agents.py
git commit -m "feat(agents): query_document_tables tool wired into both modes"
```

---

### Task 5: OpenRouter как основной model provider

**Files:**
- Modify: `backend/agents/base.py` (build_model)
- Modify: `backend/pyproject.toml` (+ `langchain-openai`)
- Test: `backend/tests/test_agents.py` (дополнить)

**Interfaces:**
- Produces: `build_model() -> BaseChatModel` — `ChatOpenAI` при `MODEL_PROVIDER=openrouter` (default), `ChatOllama` при `MODEL_PROVIDER=ollama`.

- [ ] **Step 1: Установить зависимость**

Run: `cd backend && uv add langchain-openai`
Expected: `pyproject.toml` и `uv.lock` обновлены без ошибок.

- [ ] **Step 2: Написать падающий тест**

Добавить в `backend/tests/test_agents.py`:

```python
def test_build_model_provider_switch(monkeypatch):
    from langchain_ollama import ChatOllama
    from langchain_openai import ChatOpenAI

    from agents.base import build_model

    monkeypatch.setenv("MODEL_PROVIDER", "openrouter")
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    model = build_model()
    assert isinstance(model, ChatOpenAI)
    assert "openrouter.ai" in str(model.openai_api_base)

    monkeypatch.setenv("MODEL_PROVIDER", "ollama")
    assert isinstance(build_model(), ChatOllama)
```

Run: `cd backend && uv run pytest tests/test_agents.py::test_build_model_provider_switch -v`
Expected: FAIL — `build_model` возвращает `ChatOllama` при `MODEL_PROVIDER=openrouter`

- [ ] **Step 3: Реализовать**

В `backend/agents/base.py` заменить импорты и `build_model`:

```python
import os
from enum import Enum

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_ollama import ChatOllama
from langchain_openai import ChatOpenAI
```

```python
def build_model() -> BaseChatModel:
    """OpenRouter по умолчанию; MODEL_PROVIDER=ollama — локальный фолбэк."""
    if os.environ.get("MODEL_PROVIDER", "openrouter") == "ollama":
        return ChatOllama(
            model=os.environ.get("OLLAMA_MODEL", "gemma3"),
            base_url=os.environ.get("OLLAMA_BASE_URL", "http://ollama:11434"),
        )
    return ChatOpenAI(
        model=os.environ.get("OPENROUTER_MODEL", "anthropic/claude-haiku-4.5"),
        base_url=os.environ.get(
            "OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1"
        ),
        api_key=os.environ["OPENROUTER_API_KEY"],
    )
```

- [ ] **Step 4: Убедиться, что тесты проходят**

Run: `cd backend && uv run pytest`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/agents/base.py backend/pyproject.toml backend/uv.lock
git commit -m "feat(agents): OpenRouter as default model provider, ollama fallback via env"
```

---

### Task 6: Wiring — app.py, docker-compose, профили

**Files:**
- Modify: `backend/app.py`
- Modify: `docker-compose.yml`
- Test: существующий `backend/tests/test_app_imports.py` (без изменений — smoke)

**Interfaces:**
- Consumes: `PgToastStore(dsn)` из Task 2, `build_agent(mode, store=...)` из Task 4.

- [ ] **Step 1: Подключить store в app.py**

В `backend/app.py` добавить после блока data layer (импорт `PgToastStore` — к остальным импортам):

```python
from toast.pg import PgToastStore
```

```python
_toast_store: Optional[PgToastStore] = None


def get_toast_store() -> Optional[PgToastStore]:
    """Ленивый синглтон подключения к TOAST-таблицам loreagent_test.

    Без TOAST_DATABASE_URL сервис работает как раньше (только calculator).
    """
    global _toast_store
    dsn = os.environ.get("TOAST_DATABASE_URL")
    if not dsn:
        return None
    if _toast_store is None:
        _toast_store = PgToastStore(dsn)
    return _toast_store
```

Заменить `_build_session_agent`:

```python
def _build_session_agent() -> CompiledStateGraph:
    profile = cl.user_session.get("chat_profile")
    mode = PROFILE_TO_MODE.get(profile or "", Mode.FAST)
    return build_agent(mode, store=get_toast_store())
```

Обновить описания профилей в `chat_profiles` (инструментов теперь два):

```python
        cl.ChatProfile(
            name="fast",
            display_name="Быстрый",
            markdown_description=(
                "Фиксированный langgraph-маршрут с одним циклом "
                "инструментов (калькулятор, таблицы документов). "
                "Предсказуем и быстр."
            ),
            default=True,
        ),
        cl.ChatProfile(
            name="deep",
            display_name="Умный",
            markdown_description=(
                "deepagents: сам планирует шаги и вызовы инструментов "
                "(калькулятор, таблицы документов). Для сложных задач "
                "(медленнее)."
            ),
        ),
```

- [ ] **Step 2: Добавить env в docker-compose**

В `docker-compose.yml`, в `backend.environment`, после строк `OLLAMA_*` добавить:

```yaml
      # Модельный провайдер: openrouter (default) или ollama (фолбэк).
      MODEL_PROVIDER: ${MODEL_PROVIDER:-openrouter}
      OPENROUTER_API_KEY: ${OPENROUTER_API_KEY:-}
      OPENROUTER_MODEL: ${OPENROUTER_MODEL:-anthropic/claude-haiku-4.5}
      OPENROUTER_BASE_URL: ${OPENROUTER_BASE_URL:-https://openrouter.ai/api/v1}
      # Read-only доступ к TOAST-таблицам (loreagent_test). Пусто — сервис
      # работает без инструмента таблиц.
      TOAST_DATABASE_URL: ${TOAST_DATABASE_URL:-}
```

- [ ] **Step 3: Проверить**

Run: `cd backend && uv run pytest`
Expected: PASS (test_app_imports проверяет, что app.py импортируется)

Run: `docker compose config -q`
Expected: exit 0 (compose валиден)

- [ ] **Step 4: Commit**

```bash
git add backend/app.py docker-compose.yml
git commit -m "feat(app): toast store lifecycle and env wiring for OpenRouter + loreagent_test"
```

---

### Task 7: Eval-кейсы отчёта

**Files:**
- Modify: `infra/eval-agents.py`

**Interfaces:**
- Consumes: работающий стек (`docker compose up`) с `TOAST_DATABASE_URL` и `OPENROUTER_API_KEY`.

- [ ] **Step 1: Добавить toast-кейсы**

В `infra/eval-agents.py` дополнить `CASES` (после `chat-001`) кейсами итерации 1 из eval-набора отчёта:

```python
    {
        # toast-grade-001: multi-table JOIN по _splitter_source_row
        "id": "toast-grade-001",
        "question": (
            "Какая разница между миддлом и ведущим менеджером (Group Head) "
            "в отделе контекстной рекламы?"
        ),
        "must_any": [
            ["5"],  # уровень Group Head почти по всему профилю
            ["конкурентн", "менторств", "маркетплейс", "коллтрекинг", "google ads"],
        ],
        "must_not": ["матрицы нет", "нет формальной грейдовой"],
    },
    {
        # toast-mobile-001: discovery файла + агрегация одной таблицы
        "id": "toast-mobile-001",
        "question": "Чем занимается отдел mobile marketing? Что в него входит?",
        "must_any": [
            ["appsflyer", "adjust", "appmetrica", "mmp"],
            ["in-app", "источник", "закупк"],
        ],
        "must_not": ["нет данных об отделе", "документа с описанием отдела нет"],
    },
    {
        # toast-abstain-001: no-table-answer, не выдумывать SQL
        "id": "toast-abstain-001",
        "question": (
            "Сколько следов дают за активности и как получить "
            "фирменную толстовку A.Store?"
        ),
        "must_any": [["нет", "не найд", "отсутств", "no-table"]],
        "must_not": [],
    },
```

Обновить docstring модуля (первые строки файла):

```python
"""Eval двух режимов агента (калькулятор + таблицы документов).

Запуск при работающем стеке (нужны OPENROUTER_API_KEY и
TOAST_DATABASE_URL в окружении backend):

    python3 infra/eval-agents.py

Диагностика, не CI-гейт: exit 0 всегда, сводка честная.
"""
```

И комментарий к итоговой строке: `# 2 режима × 6 кейсов = 12`.

- [ ] **Step 2: Синтаксическая проверка**

Run: `python3 -m py_compile infra/eval-agents.py`
Expected: exit 0

- [ ] **Step 3: Прогнать eval (если стек поднят и есть доступы)**

Run: `python3 infra/eval-agents.py`
Expected: сводка `EVAL: N/12 passed`; целевые кейсы итерации 1 (grade, mobile, abstain) — PASS хотя бы в fast. Это диагностика — при FAIL зафиксировать вывод в PR/заметке, не блокировать коммит.

- [ ] **Step 4: Commit**

```bash
git add infra/eval-agents.py
git commit -m "test(eval): toast cases grade/mobile/abstain from problem report"
```

---

## Верификация итерации целиком

После Task 7, при поднятом стеке с реальными `TOAST_DATABASE_URL` и `OPENROUTER_API_KEY`:

1. `cd backend && uv run pytest` — все юнит-тесты зелёные.
2. `cd backend && TOAST_DATABASE_URL=<dsn> uv run pytest tests/test_toast_store.py -v` — интеграция с живой БД зелёная.
3. `python3 infra/eval-agents.py` — кейсы toast-grade-001, toast-mobile-001, toast-abstain-001 проходят.
4. Ручная проверка в UI: вопрос про грейды контекстной рекламы → ответ с источником (файл + table_id); вопрос про толстовку → честный отказ.
