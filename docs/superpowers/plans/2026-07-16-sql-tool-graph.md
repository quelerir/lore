# SQL-инструмент (langgraph, одна таблица) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** SQL-инструмент как langgraph-граф: вход (вопрос, chunk_id, имя таблицы + 2 описания) → генерация SQL к одной таблице в раундах×параллель → судья → суммаризатор → структурный ответ.

**Architecture:** Детерминированный `scope` (фетч реальных колонок) → LLM `generate` (батч SQL) → параллельный `execute` (read-only, ровно одна таблица) → LLM `judge` (достаточно/ещё раунд) → LLM `summarize`. Граф обёрнут в LangChain-tool. Старый toast-пайплайн (discover/inspect/policy/subagent) удаляется.

**Tech Stack:** Python 3.13, uv, langgraph, langchain-openai (OpenRouter), asyncpg, pydantic-settings, pytest.

**Spec:** `docs/superpowers/specs/2026-07-16-sql-tool-graph-design.md`

## Global Constraints

- Рабочая директория: `backend/`. Тесты: `cd backend && uv run pytest`.
- Комментарии/докстринги — по-русски, в стиле кода.
- Фиксированная схема toast-таблицы (в системный промпт): служебные колонки `_splitter_row_number` (int), `_splitter_source_row` (int), `_splitter_source_range` (text); дальше колонки данных (`column_N` или переименованные, типы text/numeric/date).
- Чанк = целая таблица; `row_filter` НЕ используется; `chunk_id` — провенанс.
- SQL: только `SELECT`, ссылка **ровно** на переданную таблицу (`splitter_toast.<table>`), JOIN к другим таблицам запрещён, read-only, `statement_timeout`, лимит строк.
- Модель: `sql_model` через OpenRouter; все три роли (generate/judge/summarize) на ней; ключ/base_url — общие openrouter.
- Бюджет: `sql_max_queries` (дефолт 3) всего; `sql_candidates_per_round` (дефолт 2) параллельно в раунде.
- Реальные табличные id для фикстур: `toast_tbl_ec48a6d52d16ab405f95` (юристы), `toast_tbl_17a7241d0a976f287103` (грейды-база), `toast_tbl_e765505051472ed91b81` (грейды-Middle).
- После каждой задачи `cd backend && uv run pytest` зелёный.

---

### Task 1: Снести старый toast-пайплайн, вернуть агент к calculator-only

Удаляем всё, что зависит от старой логики, чтобы строить новое на чистом месте. Каждый файл, импортирующий удаляемое, правится здесь же.

**Files:**
- Delete: `backend/toast/subagent.py`, `backend/toast/policy.py`, `backend/toast/port.py`, `backend/toast/pg.py`, `backend/toast/guardrails.py`
- Delete: `backend/tests/test_subagent.py`, `backend/tests/test_guardrails.py`, `backend/tests/test_toast_store.py`
- Modify: `backend/agents/tools.py`, `backend/agents/__init__.py`, `backend/app.py`, `backend/tests/test_agents.py`, `backend/tests/fakes.py`, `backend/infra/eval-agents.py` (путь: `infra/eval-agents.py` от корня)

**Interfaces:**
- Produces: `make_tools() -> list[BaseTool]` (снова только calculator); `build_agent(mode, model=None)` без параметра `store`.

- [ ] **Step 1: Удалить файлы старого пайплайна и его тесты**

```bash
cd /Users/stamplevskiyd/development/lore/backend
git rm toast/subagent.py toast/policy.py toast/port.py toast/pg.py toast/guardrails.py \
       tests/test_subagent.py tests/test_guardrails.py tests/test_toast_store.py
```

- [ ] **Step 2: Вернуть tools.py к calculator-only**

Заменить `backend/agents/tools.py` целиком на:

```python
"""Инструменты агента: пока только калькулятор.

SQL-инструмент над toast-таблицами вынесен в отдельный граф (toast/), он не
вызывается чат-агентом и подключается будущим пайплайном отдельно.
"""

import ast
import operator

from langchain_core.tools import BaseTool, tool

_BIN_OPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}
_UNARY_OPS = {ast.UAdd: operator.pos, ast.USub: operator.neg}
_MAX_POW = 10_000


def _eval_node(node: ast.expr) -> float:
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return node.value
    if isinstance(node, ast.UnaryOp) and type(node.op) in _UNARY_OPS:
        return _UNARY_OPS[type(node.op)](_eval_node(node.operand))
    if isinstance(node, ast.BinOp) and type(node.op) in _BIN_OPS:
        left, right = _eval_node(node.left), _eval_node(node.right)
        if isinstance(node.op, ast.Pow) and abs(right) > _MAX_POW:
            raise ValueError("слишком большая степень")
        return _BIN_OPS[type(node.op)](left, right)
    raise ValueError(f"недопустимая конструкция: {ast.dump(node)[:60]}")


def evaluate_expression(expression: str) -> float:
    """Безопасная арифметика через AST — никакого eval."""
    tree = ast.parse(expression.strip(), mode="eval")
    return _eval_node(tree.body)


@tool
def calculator(expression: str) -> str:
    """Вычислить арифметическое выражение.

    Поддерживает числа, + - * / // % **, скобки и унарный минус.
    Пример: "(17 + 3) * 4 / 2". Используй для любых вычислений —
    не считай в уме.
    """
    try:
        result = evaluate_expression(expression)
    except ZeroDivisionError:
        return "Ошибка: деление на ноль."
    except (ValueError, SyntaxError) as e:
        return f"Ошибка: не удалось вычислить выражение ({e})."
    if isinstance(result, float) and result.is_integer():
        result = int(result)
    return str(result)


def make_tools() -> list[BaseTool]:
    return [calculator]
```

- [ ] **Step 3: Убрать store из build_agent**

Заменить `backend/agents/__init__.py` целиком на:

```python
from langchain_core.language_models.chat_models import BaseChatModel
from langgraph.graph.state import CompiledStateGraph

from agents.base import PROFILE_TO_MODE, Mode, build_model
from agents.deep import build_deep_agent
from agents.fast import build_fast_agent
from agents.tools import make_tools

__all__ = ["Mode", "PROFILE_TO_MODE", "build_agent", "build_model"]


def build_agent(
    mode: Mode,
    model: BaseChatModel | None = None,
) -> CompiledStateGraph:
    if model is None:
        model = build_model()
    tools = make_tools()
    if mode is Mode.DEEP:
        return build_deep_agent(model, tools)
    return build_fast_agent(model, tools)
```

- [ ] **Step 4: Убрать toast-store из app.py**

В `backend/app.py` удалить импорт `from toast.pg import PgToastStore`, блок `_toast_store`/`get_toast_store`, и упростить `_build_session_agent`:

```python
def _build_session_agent() -> CompiledStateGraph:
    profile = cl.user_session.get("chat_profile")
    mode = PROFILE_TO_MODE.get(profile or "", Mode.FAST)
    return build_agent(mode)
```

Обновить описания профилей — убрать «таблицы документов» (вернуть «калькулятор»):

```python
            markdown_description=(
                "Фиксированный langgraph-маршрут с одним циклом "
                "инструментов (калькулятор). Предсказуем и быстр."
            ),
```

и для deep:

```python
            markdown_description=(
                "deepagents: сам планирует шаги и вызовы инструментов "
                "(калькулятор). Для сложных задач (медленнее)."
            ),
```

- [ ] **Step 5: Почистить тесты и фейки**

В `backend/tests/test_agents.py` удалить блок «toast-инструмент» (тесты
`test_make_tools_without_store_is_calculator_only`,
`test_make_tools_with_store_adds_toast_tool`,
`test_query_document_tables_returns_no_table_json`,
`test_query_document_tables_wraps_connection_errors`) и добавить один тест
на calculator-only:

```python
def test_make_tools_is_calculator_only():
    assert [t.name for t in make_tools()] == ["calculator"]
```

В `backend/tests/fakes.py` удалить класс `FakeToastStore` (больше не нужен),
оставить `ScriptedChatModel`.

- [ ] **Step 6: Убрать toast-кейсы из eval-agents.py**

В `infra/eval-agents.py` удалить кейсы `toast-grade-001`, `toast-mobile-001`,
`toast-abstain-001` из списка `CASES` (оставить `calc-001`, `calc-002`,
`chat-001`); вернуть комментарий итога `# 2 режима × 3 кейса = 6`; docstring
вернуть к «калькулятор».

- [ ] **Step 7: Прогнать тесты**

Run: `cd backend && uv run pytest`
Expected: PASS (toast-тесты удалены, calculator/agents/config/auth зелёные).

Run: `cd backend && uv run ruff check .`
Expected: All checks passed! (нет висячих импортов).

- [ ] **Step 8: Commit**

```bash
cd /Users/stamplevskiyd/development/lore
git add -A
git commit -m "refactor(toast): remove old pipeline, agent back to calculator-only"
```

---

### Task 2: Конфиг SQL-инструмента + build_sql_model

**Files:**
- Modify: `backend/config.py`
- Modify: `backend/agents/base.py`
- Test: `backend/tests/test_config.py`, `backend/tests/test_agents.py`

**Interfaces:**
- Produces: `Settings.sql_model: str`, `Settings.sql_max_queries: int`, `Settings.sql_candidates_per_round: int`; `build_sql_model(temperature: float = 0.0) -> BaseChatModel` в `agents.base`.

- [ ] **Step 1: Тесты конфига и модели**

В `backend/tests/test_config.py` добавить:

```python
def test_sql_settings_defaults(monkeypatch):
    for k, v in BASE.items():
        monkeypatch.setenv(k, v)
    s = Settings(_env_file=None)
    assert s.sql_max_queries == 3
    assert s.sql_candidates_per_round == 2
    assert s.sql_model  # непустой дефолт
```

В `backend/tests/test_agents.py` добавить:

```python
def test_build_sql_model_openrouter(monkeypatch):
    from langchain_openai import ChatOpenAI

    from agents.base import build_sql_model
    from config import get_settings

    monkeypatch.setenv("OPENROUTER_API_KEY", "k")
    monkeypatch.setenv("SQL_MODEL", "anthropic/claude-sonnet-4.6")
    get_settings.cache_clear()
    m = build_sql_model()
    assert isinstance(m, ChatOpenAI)
    assert "openrouter.ai" in str(m.openai_api_base)


def test_build_sql_model_requires_key(monkeypatch):
    import pytest

    from agents.base import build_sql_model
    from config import get_settings

    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    get_settings.cache_clear()
    with pytest.raises(RuntimeError):
        build_sql_model()
```

- [ ] **Step 2: Запустить — падает**

Run: `cd backend && uv run pytest tests/test_config.py::test_sql_settings_defaults "tests/test_agents.py::test_build_sql_model_openrouter" -v`
Expected: FAIL — нет полей `sql_*` / нет `build_sql_model`.

- [ ] **Step 3: Добавить поля в config.py**

В `backend/config.py`, в секцию «Модель / провайдер», после `ollama_base_url`
добавить:

```python
    # --- SQL-инструмент (отдельная «умная» модель через OpenRouter) ---
    sql_model: str = Field(
        default="anthropic/claude-sonnet-4.6", validation_alias="SQL_MODEL"
    )
    sql_max_queries: int = Field(default=3, validation_alias="SQL_MAX_QUERIES")
    sql_candidates_per_round: int = Field(
        default=2, validation_alias="SQL_CANDIDATES_PER_ROUND"
    )
```

- [ ] **Step 4: Добавить build_sql_model в agents/base.py**

В `backend/agents/base.py` после `build_model` добавить:

```python
def build_sql_model(temperature: float = 0.0) -> BaseChatModel:
    """Модель SQL-инструмента (OpenRouter). Temperature варьируется для
    разнообразия кандидатов при генерации."""
    s = get_settings()
    if not s.openrouter_api_key:
        raise RuntimeError("OPENROUTER_API_KEY обязателен для sql_model")
    return ChatOpenAI(
        model=s.sql_model,
        base_url=s.openrouter_base_url,
        api_key=s.openrouter_api_key,
        temperature=temperature,
    )
```

- [ ] **Step 5: Прогнать тесты**

Run: `cd backend && uv run pytest`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
cd /Users/stamplevskiyd/development/lore
git add backend/config.py backend/agents/base.py backend/tests/test_config.py backend/tests/test_agents.py
git commit -m "feat(config): sql_model settings and build_sql_model"
```

---

### Task 3: Guardrails одной таблицы

**Files:**
- Create: `backend/toast/sql_guardrails.py`
- Test: `backend/tests/test_sql_guardrails.py`

**Interfaces:**
- Produces: `TOAST_TABLE_RE`; `qualify_table(sql: str, table: str) -> str` (дописывает `splitter_toast.` к голому имени переданной таблицы); `validate_select(sql: str, table: str) -> str | None` (None — можно; иначе текст отказа). Разрешена ссылка только на `splitter_toast.<table>`; любая другая таблица/схема/не-SELECT/мутация — отказ.

- [ ] **Step 1: Тесты**

Создать `backend/tests/test_sql_guardrails.py`:

```python
import pytest
from toast.sql_guardrails import qualify_table, validate_select

T = "toast_tbl_ec48a6d52d16ab405f95"
OTHER = "toast_tbl_17a7241d0a976f287103"


def test_valid_select_on_allowed_table():
    assert validate_select(f"SELECT column_1 FROM splitter_toast.{T} LIMIT 5", T) is None


def test_bare_table_name_qualified():
    assert qualify_table(f"SELECT * FROM {T}", T) == f"SELECT * FROM splitter_toast.{T}"
    # уже квалифицированное не трогаем
    q = f"SELECT * FROM splitter_toast.{T}"
    assert qualify_table(q, T) == q


def test_self_join_allowed():
    sql = (f"SELECT a.column_1 FROM splitter_toast.{T} a "
           f"JOIN splitter_toast.{T} b USING (_splitter_source_row)")
    assert validate_select(sql, T) is None


@pytest.mark.parametrize("bad", [
    "DROP TABLE splitter_toast.x",
    "DELETE FROM splitter_toast.x",
    "INSERT INTO splitter_toast.x VALUES (1)",
    "UPDATE splitter_toast.x SET a=1",
    "SELECT 1; DROP TABLE y",
])
def test_mutations_rejected(bad):
    assert validate_select(bad, T) is not None


def test_other_table_rejected():
    assert validate_select(f"SELECT * FROM splitter_toast.{OTHER}", T) is not None


def test_foreign_schema_rejected():
    assert validate_select("SELECT * FROM public.users", T) is not None
    assert validate_select(f"SELECT * FROM lore_core.chunks", T) is not None


def test_join_to_other_table_rejected():
    sql = (f"SELECT * FROM splitter_toast.{T} a "
           f"JOIN splitter_toast.{OTHER} b USING (_splitter_source_row)")
    assert validate_select(sql, T) is not None
```

- [ ] **Step 2: Запустить — падает**

Run: `cd backend && uv run pytest tests/test_sql_guardrails.py -v`
Expected: FAIL — нет модуля `toast.sql_guardrails`.

- [ ] **Step 3: Реализовать**

Создать `backend/toast/sql_guardrails.py`:

```python
"""SQL-guardrails: разрешён только SELECT ровно к одной переданной таблице."""

import re

TOAST_TABLE_RE = re.compile(r"^toast_tbl_[0-9a-f]{20}$")
_FORBIDDEN = re.compile(
    r"\b(insert|update|delete|drop|alter|create|truncate|grant|revoke|"
    r"copy|vacuum|call|do)\b",
    re.IGNORECASE,
)
# Цели FROM/JOIN: schema.table (alias.column проверке не подлежит).
_RELATION = re.compile(
    r"\b(?:from|join)\s+([a-zA-Z_]\w*)\s*\.\s*([a-zA-Z_]\w*)", re.IGNORECASE
)
_BARE = re.compile(r"(?i)\b(from|join)\s+(toast_tbl_[0-9a-f]{20})\b")


def qualify_table(sql: str, table: str) -> str:
    """Дописывает splitter_toast. к голому имени переданной таблицы."""
    return _BARE.sub(
        lambda m: f"{m.group(1)} splitter_toast.{m.group(2)}"
        if m.group(2) == table
        else m.group(0),
        sql,
    )


def validate_select(sql: str, table: str) -> str | None:
    """None — можно выполнять; иначе текст отказа для LLM."""
    if not TOAST_TABLE_RE.match(table):
        return f"Отказ: недопустимое имя таблицы '{table}'."
    stripped = sql.strip().rstrip(";").strip()
    if ";" in stripped:
        return "Отказ: разрешена ровно одна SQL-команда."
    if not re.match(r"^select\b", stripped, re.IGNORECASE):
        return "Отказ: разрешён только SELECT."
    if _FORBIDDEN.search(stripped):
        return "Отказ: запрещённая операция (только чтение)."
    relations = _RELATION.findall(stripped)
    if not relations:
        return "Отказ: не вижу FROM с явной таблицей."
    for schema, name in relations:
        if schema.lower() != "splitter_toast" or name != table:
            return (
                f"Отказ: разрешена только таблица splitter_toast.{table}, "
                f"найдено {schema}.{name}."
            )
    return None
```

- [ ] **Step 4: Прогнать тесты**

Run: `cd backend && uv run pytest tests/test_sql_guardrails.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
cd /Users/stamplevskiyd/development/lore
git add backend/toast/sql_guardrails.py backend/tests/test_sql_guardrails.py
git commit -m "feat(toast): single-table SQL guardrails"
```

---

### Task 4: Исполнитель (read-only, фетч колонок, SELECT)

**Files:**
- Create: `backend/toast/executor.py`
- Test: `backend/tests/test_executor.py` (интеграция, skip без `TOAST_DATABASE_URL`)

**Interfaces:**
- Consumes: `toast.sql_guardrails.{qualify_table, validate_select, TOAST_TABLE_RE}`.
- Produces: `SelectResult` (TypedDict `{columns, rows, row_count, truncated}`); класс `PgExecutor(dsn)` с `async fetch_columns(table) -> list[str]`, `async run_select(sql, table) -> SelectResult | str`, `async close()`; константы `MAX_ROWS = 200`, `STATEMENT_TIMEOUT_MS = 5000`.

- [ ] **Step 1: Реализовать исполнитель**

Создать `backend/toast/executor.py`:

```python
"""Read-only исполнитель одной toast-таблицы: фетч колонок + guarded SELECT."""

import json
from typing import Any, TypedDict

import asyncpg

from toast.sql_guardrails import TOAST_TABLE_RE, qualify_table, validate_select

MAX_ROWS = 200
STATEMENT_TIMEOUT_MS = 5000


class SelectResult(TypedDict):
    columns: list[str]
    rows: list[dict[str, Any]]
    row_count: int
    truncated: bool


class PgExecutor:
    def __init__(self, dsn: str) -> None:
        self._dsn = dsn
        self._pool: asyncpg.Pool | None = None

    async def _acquire_pool(self) -> asyncpg.Pool:
        if self._pool is None:
            self._pool = await asyncpg.create_pool(
                self._dsn,
                min_size=0,
                max_size=3,
                command_timeout=STATEMENT_TIMEOUT_MS / 1000,
                server_settings={
                    "default_transaction_read_only": "on",
                    "statement_timeout": str(STATEMENT_TIMEOUT_MS),
                },
            )
        return self._pool

    async def close(self) -> None:
        if self._pool is not None:
            await self._pool.close()
            self._pool = None

    async def fetch_columns(self, table: str) -> list[str]:
        if not TOAST_TABLE_RE.match(table):
            raise ValueError(f"bad table id: {table!r}")
        pool = await self._acquire_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """SELECT column_name FROM information_schema.columns
                   WHERE table_schema = 'splitter_toast' AND table_name = $1
                   ORDER BY ordinal_position""",
                table,
            )
        return [r["column_name"] for r in rows]

    async def run_select(self, sql: str, table: str) -> SelectResult | str:
        sql = qualify_table(sql, table)
        if refusal := validate_select(sql, table):
            return refusal
        pool = await self._acquire_pool()
        try:
            async with pool.acquire() as conn:
                async with conn.transaction(readonly=True):
                    rows = await conn.fetch(sql.strip().rstrip(";"))
        except asyncpg.PostgresError as e:
            return f"Ошибка SQL: {e}"
        truncated = len(rows) > MAX_ROWS
        rows = rows[:MAX_ROWS]
        columns = list(rows[0].keys()) if rows else []
        return SelectResult(
            columns=columns,
            rows=[{k: _plain(v) for k, v in dict(r).items()} for r in rows],
            row_count=len(rows),
            truncated=truncated,
        )


def _plain(value: Any) -> Any:
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    try:
        return (
            json.loads(value)
            if isinstance(value, (bytes, bytearray))
            else str(value)
        )
    except Exception:
        return str(value)
```

- [ ] **Step 2: Интеграционные тесты (skip без DSN)**

Создать `backend/tests/test_executor.py`:

```python
import asyncio
import os

import pytest

DSN = os.environ.get("TOAST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not DSN, reason="TOAST_DATABASE_URL not set")

LEGAL = "toast_tbl_ec48a6d52d16ab405f95"


def _run(coro):
    return asyncio.run(coro)


def _exe():
    from toast.executor import PgExecutor

    return PgExecutor(DSN)


def test_fetch_columns_includes_service_and_renamed():
    exe = _exe()

    async def run():
        try:
            return await exe.fetch_columns(LEGAL)
        finally:
            await exe.close()

    cols = _run(run())
    assert "_splitter_source_row" in cols
    assert "senior_legal_manager" in cols  # переименованная колонка из отчёта


def test_run_select_ok_and_mutation_rejected():
    exe = _exe()

    async def run():
        try:
            ok = await exe.run_select(
                f'SELECT column_1 FROM splitter_toast."{LEGAL}"', LEGAL
            )
            bad = await exe.run_select("DROP TABLE splitter_toast.x", LEGAL)
            return ok, bad
        finally:
            await exe.close()

    ok, bad = _run(run())
    assert not isinstance(ok, str) and ok["row_count"] >= 1
    assert isinstance(bad, str) and "Отказ" in bad
```

- [ ] **Step 3: Прогнать**

Run: `cd backend && uv run pytest tests/test_executor.py -v`
Expected: SKIPPED без DSN; при наличии DSN — PASS.

Run: `cd backend && uv run pytest`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
cd /Users/stamplevskiyd/development/lore
git add backend/toast/executor.py backend/tests/test_executor.py
git commit -m "feat(toast): read-only single-table executor with column fetch"
```

---

### Task 5: Граф SQL-инструмента

**Files:**
- Create: `backend/toast/sql_graph.py`
- Test: `backend/tests/test_sql_graph.py`

**Interfaces:**
- Consumes: `PgExecutor` (Task 4), `BaseChatModel`; настройки `sql_max_queries`, `sql_candidates_per_round`.
- Produces: `SqlToolState` (TypedDict); `build_sql_graph(model, executor, max_queries, candidates_per_round) -> CompiledStateGraph`; результат графа содержит `status: "ok"|"no_data"|"error"`, `answer: str`, `attempts: list[dict]`. Хелпер `parse_sql_candidates(text: str, limit: int) -> list[str]`.

- [ ] **Step 1: Тесты графа на фейках**

Создать `backend/tests/test_sql_graph.py`:

```python
import asyncio

from langchain_core.messages import AIMessage

from fakes import ScriptedChatModel

LEGAL = "toast_tbl_ec48a6d52d16ab405f95"


class FakeExecutor:
    def __init__(self, columns, results):
        self._columns = columns
        self._results = list(results)  # по одному на каждый вызов run_select
        self.calls = []

    async def fetch_columns(self, table):
        return self._columns

    async def run_select(self, sql, table):
        self.calls.append(sql)
        return self._results.pop(0)


def _rows(n):
    return {"columns": ["column_1"], "rows": [{"column_1": "x"}] * n,
            "row_count": n, "truncated": False}


def _inp(question="ФИО юристов"):
    return {
        "question": question,
        "chunk_id": "c1",
        "table": LEGAL,
        "desc_vector": "юристы",
        "desc_full": "Таблица юристов Adventum",
    }


def _run(model, executor, **cfg):
    from toast.sql_graph import build_sql_graph

    graph = build_sql_graph(model, executor,
                            max_queries=cfg.get("max_queries", 3),
                            candidates_per_round=cfg.get("candidates", 2))
    return asyncio.run(graph.ainvoke(_inp()))


def test_round1_sufficient_ok():
    # generate -> ["SELECT ...","SELECT ..."]; judge -> SUFFICIENT; summarize -> текст
    model = ScriptedChatModel(responses=[
        AIMessage(content='["SELECT column_1 FROM %s", "SELECT column_2 FROM %s"]' % (LEGAL, LEGAL)),
        AIMessage(content="SUFFICIENT"),
        AIMessage(content="Юрист: Каневский Георгий."),
    ])
    exe = FakeExecutor(["_splitter_source_row", "column_1", "column_2"],
                       results=[_rows(1), _rows(1)])
    out = _run(model, exe)
    assert out["status"] == "ok"
    assert "Каневский" in out["answer"]
    assert len(exe.calls) == 2  # оба кандидата раунда выполнены (параллельно)


def test_retry_then_sufficient():
    # Раунд 1 даёт строки, но судья (LLM) считает их не по теме -> ещё раунд.
    # Судья зовёт модель ТОЛЬКО когда есть успешные строки — здесь так в обоих
    # раундах, поэтому оба вердикта скриптуются.
    model = ScriptedChatModel(responses=[
        AIMessage(content='["SELECT column_2 FROM %s"]' % LEGAL),   # раунд 1
        AIMessage(content="NEED_MORE"),                             # судья -> ещё
        AIMessage(content='["SELECT column_1 FROM %s"]' % LEGAL),   # раунд 2
        AIMessage(content="SUFFICIENT"),
        AIMessage(content="Ответ по данным."),
    ])
    exe = FakeExecutor(["column_1", "column_2"], results=[_rows(1), _rows(1)])
    out = _run(model, exe, candidates=1, max_queries=3)
    assert out["status"] == "ok"
    assert len(exe.calls) == 2


def test_budget_exhausted_no_data():
    # Все кандидаты возвращают 0 строк. Судья при пустом результате НЕ зовёт
    # модель (короткое замыкание в need_more), поэтому скриптуем только 3
    # ответа generate. Бюджет исчерпан -> no_data.
    model = ScriptedChatModel(responses=[
        AIMessage(content='["SELECT column_1 FROM %s"]' % LEGAL),
        AIMessage(content='["SELECT column_1 FROM %s"]' % LEGAL),
        AIMessage(content='["SELECT column_1 FROM %s"]' % LEGAL),
    ])
    exe = FakeExecutor(["column_1"], results=[_rows(0), _rows(0), _rows(0)])
    out = _run(model, exe, candidates=1, max_queries=3)
    assert out["status"] == "no_data"
    assert len(exe.calls) == 3


def test_all_sql_errors_status_error():
    model = ScriptedChatModel(responses=[
        AIMessage(content='["SELECT bad FROM %s"]' % LEGAL),
        AIMessage(content='["SELECT worse FROM %s"]' % LEGAL),
        AIMessage(content='["SELECT nope FROM %s"]' % LEGAL),
    ])
    exe = FakeExecutor(["column_1"],
                       results=["Ошибка SQL: a", "Ошибка SQL: b", "Ошибка SQL: c"])
    out = _run(model, exe, candidates=1, max_queries=3)
    assert out["status"] == "error"


def test_candidates_run_in_parallel_batch():
    model = ScriptedChatModel(responses=[
        AIMessage(content='["SELECT column_1 FROM %s","SELECT column_2 FROM %s"]' % (LEGAL, LEGAL)),
        AIMessage(content="SUFFICIENT"),
        AIMessage(content="ok"),
    ])
    exe = FakeExecutor(["column_1", "column_2"], results=[_rows(1), _rows(1)])
    out = _run(model, exe, candidates=2, max_queries=3)
    assert out["status"] == "ok"
    assert len(exe.calls) == 2
```

- [ ] **Step 2: Запустить — падает**

Run: `cd backend && uv run pytest tests/test_sql_graph.py -v`
Expected: FAIL — нет модуля `toast.sql_graph`.

- [ ] **Step 3: Реализовать граф**

Создать `backend/toast/sql_graph.py`:

```python
"""SQL-инструмент как langgraph-граф над одной таблицей.

scope -> generate -> execute(∥) -> judge -> (retry | summarize) -> END
LLM: generate (батч SQL), judge (достаточно/ещё раунд), summarize (ответ).
Детерминированные части: фетч колонок, параллельное выполнение, учёт бюджета.
"""

import asyncio
import json
from typing import Any, TypedDict

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

FIXED_SCHEMA = (
    "Таблицы извлечены из XLSX (Postgres, схема splitter_toast). У каждой "
    "первые служебные колонки: _splitter_row_number (int), "
    "_splitter_source_row (int), _splitter_source_range (text). Дальше — "
    "колонки данных: column_1, column_2, ... или переименованные "
    "(из заголовков). Используй ТОЛЬКО реальные имена колонок из списка ниже."
)

GENERATE_SYS = (
    FIXED_SCHEMA
    + " Составь SQL SELECT к ОДНОЙ переданной таблице, чтобы ответить на "
    "вопрос. Верни JSON-массив из нескольких РАЗНЫХ по подходу SELECT-строк "
    "(без markdown, без пояснений). Только SELECT, только эта таблица."
)
JUDGE_SYS = (
    "Ты оцениваешь, достаточно ли полученных строк, чтобы ответить на вопрос. "
    "Ответь ровно одним словом: SUFFICIENT или NEED_MORE."
)
SUMMARIZE_SYS = (
    "Ответь на вопрос пользователя СТРОГО по предоставленным строкам таблицы. "
    "Не выдумывай. Если данных недостаточно — так и скажи. Кратко, по-русски."
)
NO_DATA_MSG = "В данных таблицы нет ответа на этот вопрос."
JUDGE_ROWS_CAP = 30  # строк в контекст судьи/суммаризатора


class SqlToolState(TypedDict, total=False):
    question: str
    chunk_id: str
    table: str
    desc_vector: str
    desc_full: str
    columns: list[str]
    candidates: list[str]
    round: int
    executed_count: int
    attempts: list[dict[str, Any]]
    verdict: str
    answer: str
    status: str


def parse_sql_candidates(text: str, limit: int) -> list[str]:
    """Достаёт список SELECT-строк из ответа модели (JSON-массив или строки)."""
    cleaned = text.strip().strip("`").strip()
    if cleaned.lower().startswith("json"):
        cleaned = cleaned[4:].strip()
    try:
        data = json.loads(cleaned)
        if isinstance(data, list):
            out = [str(x).strip() for x in data if str(x).strip()]
            return out[:limit]
    except json.JSONDecodeError:
        pass
    lines = [ln.strip() for ln in cleaned.splitlines()
             if ln.strip().lower().startswith("select")]
    return lines[:limit] or ([cleaned] if cleaned.lower().startswith("select") else [])


def _ok_rows(attempts: list[dict]) -> list[dict]:
    out: list[dict] = []
    for a in attempts:
        if a["ok"]:
            out.extend(a["rows"])
    return out


def build_sql_graph(
    model: BaseChatModel,
    executor: Any,
    max_queries: int,
    candidates_per_round: int,
) -> CompiledStateGraph:
    async def scope(state: SqlToolState) -> SqlToolState:
        columns = await executor.fetch_columns(state["table"])
        return {"columns": columns, "attempts": [], "executed_count": 0, "round": 0}

    async def generate(state: SqlToolState) -> SqlToolState:
        remaining = max_queries - state["executed_count"]
        n = max(1, min(candidates_per_round, remaining))
        errors = [a["error"] for a in state["attempts"] if not a["ok"]]
        prompt = (
            f"Вопрос: {state['question']}\n"
            f"Таблица: {state['table']}\n"
            f"Описание (кратко): {state['desc_vector']}\n"
            f"Описание (полно): {state['desc_full']}\n"
            f"Реальные колонки: {', '.join(state['columns'])}\n"
            f"Нужно вернуть до {n} разных SELECT."
        )
        if errors:
            prompt += "\n\nПрошлые ошибки SQL (исправь):\n" + "\n".join(errors[-3:])
        reply = await model.ainvoke(
            [SystemMessage(GENERATE_SYS), HumanMessage(prompt)],
            config={"tags": ["internal"]},
        )
        candidates = parse_sql_candidates(str(reply.content), n)
        return {"candidates": candidates, "round": state["round"] + 1}

    async def execute(state: SqlToolState) -> SqlToolState:
        table = state["table"]
        cands = state["candidates"]
        results = await asyncio.gather(
            *(executor.run_select(sql, table) for sql in cands)
        )
        new: list[dict] = []
        for sql, res in zip(cands, results):
            if isinstance(res, str):
                new.append({"sql": sql, "ok": False, "error": res,
                            "rows": [], "row_count": 0, "truncated": False})
            else:
                new.append({"sql": sql, "ok": True, "error": None,
                            "rows": res["rows"], "row_count": res["row_count"],
                            "truncated": res["truncated"]})
        return {
            "attempts": state["attempts"] + new,
            "executed_count": state["executed_count"] + len(cands),
        }

    async def judge(state: SqlToolState) -> SqlToolState:
        rows = _ok_rows(state["attempts"])
        if not rows:
            return {"verdict": "need_more"}  # нечего оценивать — без LLM
        reply = await model.ainvoke(
            [
                SystemMessage(JUDGE_SYS),
                HumanMessage(
                    f"Вопрос: {state['question']}\n"
                    f"Строки: {json.dumps(rows[:JUDGE_ROWS_CAP], ensure_ascii=False, default=str)}"
                ),
            ],
            config={"tags": ["internal"]},
        )
        verdict = "sufficient" if "suffic" in str(reply.content).lower() else "need_more"
        return {"verdict": verdict}

    async def summarize(state: SqlToolState) -> SqlToolState:
        rows = _ok_rows(state["attempts"])
        if not rows:
            any_ok = any(a["ok"] for a in state["attempts"])
            if any_ok:
                return {"status": "no_data", "answer": NO_DATA_MSG}
            last = next((a["error"] for a in reversed(state["attempts"]) if a["error"]),
                        "неизвестная ошибка")
            return {"status": "error", "answer": f"Не удалось выполнить SQL: {last}"}
        reply = await model.ainvoke(
            [
                SystemMessage(SUMMARIZE_SYS),
                HumanMessage(
                    f"Вопрос: {state['question']}\n"
                    f"Строки: {json.dumps(rows[:JUDGE_ROWS_CAP], ensure_ascii=False, default=str)}"
                ),
            ]
        )
        return {"status": "ok", "answer": str(reply.content)}

    def route(state: SqlToolState) -> str:
        if state.get("verdict") == "sufficient":
            return "summarize"
        if state["executed_count"] >= max_queries:
            return "summarize"
        return "generate"

    g = StateGraph(SqlToolState)
    g.add_node("scope", scope)
    g.add_node("generate", generate)
    g.add_node("execute", execute)
    g.add_node("judge", judge)
    g.add_node("summarize", summarize)
    g.add_edge(START, "scope")
    g.add_edge("scope", "generate")
    g.add_edge("generate", "execute")
    g.add_edge("execute", "judge")
    g.add_conditional_edges("judge", route, ["generate", "summarize"])
    g.add_edge("summarize", END)
    return g.compile()
```

- [ ] **Step 4: Прогнать тесты графа**

Run: `cd backend && uv run pytest tests/test_sql_graph.py -v`
Expected: PASS (5 тестов)

Run: `cd backend && uv run pytest`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
cd /Users/stamplevskiyd/development/lore
git add backend/toast/sql_graph.py backend/tests/test_sql_graph.py
git commit -m "feat(toast): SQL tool langgraph (scope/generate/execute/judge/summarize)"
```

---

### Task 6: Обёртка в tool + eval на захардкоженных фикстурах

**Files:**
- Create: `backend/toast/sql_tool.py`
- Create: `infra/eval-sql.py`
- Test: `backend/tests/test_sql_tool.py`

**Interfaces:**
- Consumes: `build_sql_graph` (Task 5), `PgExecutor` (Task 4), `build_sql_model` (Task 2), настройки.
- Produces: `async run_sql_tool(inputs: dict, model, executor, max_queries, candidates_per_round) -> dict` (проекция состояния графа в контракт `{status, answer, chunk_id, table, sql_attempts, rows_used}`); `make_sql_tool(executor, model, max_queries, candidates_per_round) -> BaseTool` (StructuredTool `query_table`).

- [ ] **Step 1: Тест проекции результата**

Создать `backend/tests/test_sql_tool.py`:

```python
import asyncio

from langchain_core.messages import AIMessage

from fakes import ScriptedChatModel
from test_sql_graph import FakeExecutor, _rows  # переиспользуем фейки

LEGAL = "toast_tbl_ec48a6d52d16ab405f95"


def test_run_sql_tool_projects_contract():
    from toast.sql_tool import run_sql_tool

    model = ScriptedChatModel(responses=[
        AIMessage(content='["SELECT column_1 FROM %s"]' % LEGAL),
        AIMessage(content="SUFFICIENT"),
        AIMessage(content="Каневский Георгий."),
    ])
    exe = FakeExecutor(["column_1"], results=[_rows(1)])
    inputs = {"question": "ФИО юристов", "chunk_id": "c1", "table": LEGAL,
              "desc_vector": "юристы", "desc_full": "Таблица юристов"}
    out = asyncio.run(run_sql_tool(inputs, model, exe, max_queries=3,
                                   candidates_per_round=1))
    assert out["status"] == "ok"
    assert out["chunk_id"] == "c1"
    assert out["table"] == LEGAL
    assert out["rows_used"] == 1
    assert out["sql_attempts"] and out["sql_attempts"][0]["ok"] is True
    assert "sql" in out["sql_attempts"][0]
```

- [ ] **Step 2: Запустить — падает**

Run: `cd backend && uv run pytest tests/test_sql_tool.py -v`
Expected: FAIL — нет модуля `toast.sql_tool`.

- [ ] **Step 3: Реализовать обёртку**

Создать `backend/toast/sql_tool.py`:

```python
"""Обёртка SQL-графа: прямой вызов run_sql_tool + LangChain StructuredTool."""

from typing import Any

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.tools import BaseTool, StructuredTool

from toast.sql_graph import build_sql_graph


def _project(inputs: dict, state: dict) -> dict:
    attempts = state.get("attempts", [])
    rows_used = sum(a["row_count"] for a in attempts if a["ok"])
    return {
        "status": state.get("status", "error"),
        "answer": state.get("answer", ""),
        "chunk_id": inputs["chunk_id"],
        "table": inputs["table"],
        "sql_attempts": [
            {"sql": a["sql"], "ok": a["ok"], "error": a["error"],
             "row_count": a["row_count"]}
            for a in attempts
        ],
        "rows_used": rows_used,
    }


async def run_sql_tool(
    inputs: dict,
    model: BaseChatModel,
    executor: Any,
    max_queries: int,
    candidates_per_round: int,
) -> dict:
    graph = build_sql_graph(model, executor, max_queries, candidates_per_round)
    state = await graph.ainvoke(inputs)
    return _project(inputs, state)


def make_sql_tool(
    executor: Any,
    model: BaseChatModel,
    max_queries: int,
    candidates_per_round: int,
) -> BaseTool:
    async def _call(
        question: str,
        chunk_id: str,
        table: str,
        desc_vector: str,
        desc_full: str,
    ) -> dict:
        inputs = {
            "question": question, "chunk_id": chunk_id, "table": table,
            "desc_vector": desc_vector, "desc_full": desc_full,
        }
        return await run_sql_tool(inputs, model, executor,
                                  max_queries, candidates_per_round)

    return StructuredTool.from_function(
        coroutine=_call,
        name="query_table",
        description=(
            "Ответить на вопрос по одной toast-таблице. Вход: question, "
            "chunk_id, table (toast_tbl_<hex>), desc_vector, desc_full. "
            "Возвращает {status, answer, sql_attempts, rows_used}."
        ),
    )
```

- [ ] **Step 4: Прогнать unit-тест**

Run: `cd backend && uv run pytest tests/test_sql_tool.py -v`
Expected: PASS

Run: `cd backend && uv run pytest`
Expected: PASS

- [ ] **Step 5: Eval-харнесс на захардкоженных фикстурах**

Создать `infra/eval-sql.py`:

```python
#!/usr/bin/env python3
"""Eval SQL-инструмента на захардкоженных чанках/таблицах из отчёта.

Нужны TOAST_DATABASE_URL и OPENROUTER_API_KEY в окружении. Диагностика,
не CI-гейт: exit 0 всегда.

Запуск: cd backend && uv run python ../infra/eval-sql.py
"""

import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from agents.base import build_sql_model  # noqa: E402
from config import get_settings  # noqa: E402
from toast.executor import PgExecutor  # noqa: E402
from toast.sql_tool import run_sql_tool  # noqa: E402

# desc_full — реальный display_text из sqls/second_sql.csv (сокращённо).
CASES = [
    {
        "id": "sql-legal-001",
        "question": "Какие ФИО у юристов и их должности?",
        "chunk_id": "e6d9b7ff6df20d08b9c1c543760530ce",
        "table": "toast_tbl_ec48a6d52d16ab405f95",
        "desc_vector": "юристы Adventum, ФИО и должности",
        "desc_full": "Table payload: Лист1 A15:R16. Реестр юристов: ФИО, должность, email.",
        "must_any": [["каневск"]],
        "must_not": ["ирин"],
    },
    {
        "id": "sql-grade-001",
        "question": "Какие компетенции базовой матрицы отдела контекстной рекламы?",
        "chunk_id": "grade-base",
        "table": "toast_tbl_17a7241d0a976f287103",
        "desc_vector": "грейды контекстной рекламы, компетенции",
        "desc_full": "Table payload: Junior-Group head. Базовая матрица компетенций.",
        "must_any": [["компетен", "kpi", "отчет", "анализ"]],
        "must_not": [],
    },
]


def check(answer: str, case: dict) -> tuple[bool, list[str]]:
    low = answer.lower()
    problems = []
    for group in case["must_any"]:
        if not any(n.lower() in low for n in group):
            problems.append(f"нет ни одного из {group}")
    for banned in case["must_not"]:
        if banned.lower() in low:
            problems.append(f"запрещённое вхождение: {banned!r}")
    return (not problems, problems)


async def main() -> None:
    s = get_settings()
    dsn = os.environ.get("TOAST_DATABASE_URL")
    if not dsn or not s.openrouter_api_key:
        print("SKIP: нужны TOAST_DATABASE_URL и OPENROUTER_API_KEY")
        return
    exe = PgExecutor(dsn)
    model = build_sql_model()
    passed = 0
    try:
        for case in CASES:
            inputs = {k: case[k] for k in
                      ("question", "chunk_id", "table", "desc_vector", "desc_full")}
            out = await run_sql_tool(inputs, model, exe,
                                     s.sql_max_queries, s.sql_candidates_per_round)
            ok, problems = check(out.get("answer", ""), case)
            passed += ok
            print(f"[{'PASS' if ok else 'FAIL'}] {case['id']} status={out['status']} "
                  f"rows={out['rows_used']}")
            if not ok:
                print("      проблемы:", problems)
                print("      ответ:", out.get("answer", "")[:300])
    finally:
        await exe.close()
    print(f"\nEVAL SQL: {passed}/{len(CASES)} passed")


if __name__ == "__main__":
    asyncio.run(main())
    sys.exit(0)
```

- [ ] **Step 6: Синтаксическая проверка eval**

Run: `python3 -m py_compile infra/eval-sql.py`
Expected: exit 0

- [ ] **Step 7: Прогон eval (если есть DSN и ключ)**

Run: `cd backend && uv run python ../infra/eval-sql.py`
Expected: при наличии доступов — сводка `EVAL SQL: N/2 passed`, кейс
`sql-legal-001` возвращает «Каневский» (Суворова недоступна — header-as-data,
известное ограничение); без доступов — `SKIP`. Диагностика, не гейт.

- [ ] **Step 8: Commit**

```bash
cd /Users/stamplevskiyd/development/lore
git add backend/toast/sql_tool.py backend/tests/test_sql_tool.py infra/eval-sql.py
git commit -m "feat(toast): query_table tool wrapper + hardcoded-fixture eval"
```

---

## Верификация плана целиком

1. `cd backend && uv run pytest` — все юнит-тесты зелёные (guardrails, graph, tool, config, agents, auth).
2. `cd backend && uv run ruff check .` — чисто.
3. `grep -rn "subagent\|PgToastStore\|query_document_tables" backend --include="*.py" | grep -v __pycache__` — пусто (старое удалено).
4. С доступами: `cd backend && TOAST_DATABASE_URL=<dsn> uv run pytest tests/test_executor.py -v` — PASS; `uv run python ../infra/eval-sql.py` — `sql-legal-001` PASS.
