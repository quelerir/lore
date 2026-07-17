# SQL Demo + Tool Improvements Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Улучшить SQL-граф (CTE, structured output, кап контекста судьи) в ветке `toast-logic` и построить поверх неё демо-ветку `demo/sql-chat`: чат-профиль «SQL (демо)», стадии графа как вложенные `cl.Step`, сворачиваемый рендер во фронтенде.

**Architecture:** Граф (`toast/`) остаётся UI-агностичным; ход прогона конвертируется в Chainlit-шаги в новом модуле `backend/sql_demo.py` из событий `graph.astream(stream_mode=["updates","messages","values"])`. Фронтенд перестаёт сплющивать дерево tool-шагов и рендерит его рекурсивно.

**Tech Stack:** Python 3.13+/langgraph/Chainlit 2.x/sqlglot/asyncpg/pytest; React 18/TypeScript/vitest/happy-dom/@chainlit/react-client.

**Spec:** `docs/superpowers/specs/2026-07-17-sql-demo-and-improvements-design.md`

## Global Constraints

- **Toast-БД неприкосновенна**: никакого DDL/ролей/GRANT; защита только AST-guardrails + read-only транзакция.
- **Studio-совместимость**: сигнатура `build_sql_graph` и вход/выход графа не меняются; в `toast/` нет импортов Chainlit; `studio/graph.py` не трогать; smoke-тесты Studio зелёные.
- **Ветки**: задачи 1–4 — в `toast-logic`; задачи 5–10 — в `demo/sql-chat` поверх `toast-logic`; демо-ветка не мержится в main.
- Команды бэкенда выполняются из `backend/` (там свой uv-проект): `uv run pytest tests/ -q`, `uv run ruff check .`. Фронтенд: из `frontend/`: `npm test`, `npm run build`.
- Все новые докстринги и сообщения — по-русски, в стиле существующего кода.

---

### Task 1: Закоммитить незакоммиченные фиксы ревью (ветка `toast-logic`)

В рабочем дереве лежат непокоммиченные исправления прошлой сессии (AST-guardrails на sqlglot, таймауты/LIMIT в executor, ветки графа, app.py, калькулятор, тесты). Без них дальнейшие задачи не собираются.

**Files:**
- Commit only (no edits): `backend/toast/*`, `backend/tests/*`, `backend/app.py`, `backend/agents/tools.py`, `backend/pyproject.toml`, `backend/uv.lock`, `studio/pyproject.toml`, `studio/uv.lock`, `infra/eval-sql.py`, `.gitignore`

**Interfaces:**
- Produces: чистое рабочее дерево на `toast-logic`; guardrails `validate_select` на sqlglot; `parse_sql_candidates`/`_rows_context`/`JUDGE_ROWS_CAP` в `toast/sql_graph.py` — их меняют задачи 2–4.

- [ ] **Step 1: Убедиться, что тесты зелёные до коммита**

Run: `cd backend && uv run pytest tests/ -q`
Expected: `70 passed, 1 skipped`

Run: `cd studio && uv run pytest -q`
Expected: `2 passed`

- [ ] **Step 2: Коммиты по логическим кускам**

```bash
cd backend
git add toast/sql_guardrails.py toast/executor.py toast/sql_graph.py \
        pyproject.toml uv.lock tests/test_sql_guardrails.py \
        tests/test_executor_pool.py tests/test_executor.py \
        tests/test_sql_graph.py tests/test_sql_tool.py
git commit -m "fix(toast): AST guardrails via sqlglot; robust loop, timeouts, DB-side LIMIT"
git add ../studio/pyproject.toml ../studio/uv.lock
git commit -m "chore(studio): add sqlglot for backend guardrails import"
git add app.py agents/tools.py tests/test_agents.py
git commit -m "fix(app): unify user identifier on username, cap history; bound calculator pow"
git add ../infra/eval-sql.py ../.gitignore
git commit -m "chore: drop stale executor.close in eval-sql; ignore studio .langgraph_api"
```

- [ ] **Step 3: Проверить, что дерево чистое**

Run: `git status --short`
Expected: пусто (кроме несвязанных недокоммиченных файлов в корне: `pyproject.toml`, `uv.lock`, `sql_reqults.txt` — их НЕ трогать).

---

### Task 2: Guardrails — разрешить CTE (ветка `toast-logic`)

**Files:**
- Modify: `backend/toast/sql_guardrails.py` (функция `validate_select`)
- Modify: `backend/toast/sql_graph.py` (константа `GENERATE_SYS`)
- Test: `backend/tests/test_sql_guardrails.py`

**Interfaces:**
- Consumes: `validate_select(sql: str, table: str) -> str | None`, sqlglot AST.
- Produces: `validate_select` пропускает `WITH`-запросы по своей таблице; ссылки без схемы на алиасы CTE не считаются таблицами.

- [ ] **Step 1: Заменить тест на запрет CTE тремя новыми**

В `backend/tests/test_sql_guardrails.py` УДАЛИТЬ `test_cte_rejected` и добавить:

```python
def test_cte_over_own_table_allowed():
    sql = (f"WITH c AS (SELECT column_1 FROM splitter_toast.{T}) "
           "SELECT * FROM c")
    assert validate_select(sql, T) is None


def test_cte_over_foreign_table_rejected():
    sql = ("WITH x AS (SELECT * FROM public.users) "
           f"SELECT * FROM splitter_toast.{T} a JOIN x ON true")
    assert validate_select(sql, T) is not None


def test_cte_alias_only_without_real_table_rejected():
    # Все relation — алиасы CTE, ни одной настоящей таблицы.
    sql = "WITH c AS (SELECT 1) SELECT * FROM c"
    assert validate_select(sql, T) is not None
```

- [ ] **Step 2: Убедиться, что первый тест падает**

Run: `cd backend && uv run pytest tests/test_sql_guardrails.py -q`
Expected: FAIL `test_cte_over_own_table_allowed` (сейчас CTE даёт отказ), остальные два PASS (fail-closed уже работает).

- [ ] **Step 3: Реализация в `validate_select`**

В `backend/toast/sql_guardrails.py` УДАЛИТЬ блок:

```python
    if stmt.find(exp.With, exp.CTE):
        return "Отказ: CTE (WITH) не поддерживается — перепиши подзапросом."
```

и заменить сбор таблиц:

```python
    tables = list(stmt.find_all(exp.Table))
```

на:

```python
    # Ссылки без схемы на алиасы CTE — не таблицы; всё со схемой проверяем.
    ctes = {cte.alias_or_name for cte in stmt.find_all(exp.CTE)}
    tables = [
        t for t in stmt.find_all(exp.Table)
        if t.db or t.name not in ctes
    ]
```

Обновить докстринг модуля: строку про «Строковые литералы …» дополнить предложением «CTE разрешены: алиасы WITH исключаются из проверки таблиц.»

- [ ] **Step 4: Снять запрет WITH в промпте генерации**

В `backend/toast/sql_graph.py` в `GENERATE_SYS` заменить хвост:

```python
    "Каждый элемент — ровно один SELECT: без CTE (WITH) и без точек с запятой."
```

на:

```python
    "Каждый элемент — ровно один запрос SELECT (WITH разрешён), "
    "без точки с запятой."
```

- [ ] **Step 5: Прогнать тесты и линтер**

Run: `cd backend && uv run pytest tests/ -q && uv run ruff check .`
Expected: `72 passed, 1 skipped` (было 70, −1 удалённый `test_cte_rejected`, +3 новых), `All checks passed!`

- [ ] **Step 6: Commit**

```bash
cd backend
git add toast/sql_guardrails.py toast/sql_graph.py tests/test_sql_guardrails.py
git commit -m "feat(toast): allow CTE in SQL guardrails via sqlglot alias tracking"
```

---

### Task 3: Structured output с фолбэком на парсер (ветка `toast-logic`)

**Files:**
- Modify: `backend/toast/sql_graph.py` (новая pydantic-модель `SqlCandidates`, хелпер `_generate_candidates`, узел `generate`)
- Modify: `backend/tests/fakes.py`
- Test: `backend/tests/test_sql_graph.py`

**Interfaces:**
- Consumes: `parse_sql_candidates(text, limit) -> list[str]` (остаётся фолбэком).
- Produces: `SqlCandidates(BaseModel)` с полем `candidates: list[str]`; `async _generate_candidates(model, messages, n) -> list[str]`; фейк `StructuredScriptedChatModel` в `fakes.py`.

- [ ] **Step 1: Фейки — явный отказ и структурный вариант**

В `backend/tests/fakes.py` добавить в `ScriptedChatModel`:

```python
    def with_structured_output(self, schema, **kwargs):
        # Скриптованные тесты идут через текстовый фолбэк generate:
        # bind_tools у фейка возвращает self, и без явного отказа structured-
        # путь съел бы лишний response из сценария.
        raise NotImplementedError
```

и новый класс в конец файла:

```python
class StructuredScriptedChatModel(ScriptedChatModel):
    """with_structured_output отдаёт следующий response как готовый объект схемы."""

    def with_structured_output(self, schema, **kwargs):
        model = self

        class _Structured:
            async def ainvoke(self, messages, config=None):
                return model.responses.pop(0)

        return _Structured()
```

- [ ] **Step 2: Написать падающий тест structured-пути**

В `backend/tests/test_sql_graph.py` добавить:

```python
def test_structured_output_path_used_when_supported():
    from fakes import StructuredScriptedChatModel
    from toast.sql_graph import SqlCandidates

    model = StructuredScriptedChatModel(responses=[
        SqlCandidates(candidates=["SELECT column_1 FROM %s" % LEGAL]),
        AIMessage(content="SUFFICIENT"),
        AIMessage(content="Ответ."),
    ])
    exe = FakeExecutor(results=[_rows(1)])
    out = _run(model, exe, candidates=1, max_queries=3)
    assert out["status"] == "ok"
    assert exe.calls == ["SELECT column_1 FROM %s" % LEGAL]
```

- [ ] **Step 3: Убедиться, что тест падает**

Run: `cd backend && uv run pytest tests/test_sql_graph.py::test_structured_output_path_used_when_supported -q`
Expected: FAIL — `ImportError: cannot import name 'SqlCandidates'`.

- [ ] **Step 4: Реализация в `sql_graph.py`**

Добавить импорт и модель (после существующих импортов):

```python
from pydantic import BaseModel
```

```python
class SqlCandidates(BaseModel):
    """Батч SQL-кандидатов — схема structured output узла generate."""

    candidates: list[str]
```

Добавить хелпер на уровне модуля (рядом с `parse_sql_candidates`):

```python
async def _generate_candidates(model: BaseChatModel, messages: list,
                               n: int) -> list[str]:
    """Кандидаты через structured output; при любом сбое — текстовый фолбэк.

    OpenRouter-модели поддерживают function calling неровно, а фейки тестов
    не поддерживают вовсе, поэтому parse_sql_candidates остаётся фолбэком.
    """
    try:
        structured = model.with_structured_output(
            SqlCandidates, method="function_calling"
        )
        result = await structured.ainvoke(messages, config={"tags": ["internal"]})
        return [c.strip() for c in result.candidates if c.strip()][:n]
    except Exception:
        reply = await model.ainvoke(messages, config={"tags": ["internal"]})
        return parse_sql_candidates(str(reply.content), n)
```

В узле `generate` заменить блок вызова модели:

```python
        # tag internal: служебные токены не показываем пользователю в UI.
        reply = await model.ainvoke(
            [SystemMessage(GENERATE_SYS), HumanMessage(prompt)],
            config={"tags": ["internal"]},
        )
        candidates = parse_sql_candidates(str(reply.content), n)
        return {"candidates": candidates, "round": state["round"] + 1}
```

на:

```python
        # tag internal: служебные токены не показываем пользователю в UI.
        candidates = await _generate_candidates(
            model, [SystemMessage(GENERATE_SYS), HumanMessage(prompt)], n
        )
        return {"candidates": candidates, "round": state["round"] + 1}
```

- [ ] **Step 5: Прогнать все тесты**

Run: `cd backend && uv run pytest tests/ -q && uv run ruff check .`
Expected: 0 failed (все старые Scripted-тесты идут через фолбэк), `All checks passed!`

- [ ] **Step 6: Commit**

```bash
cd backend
git add toast/sql_graph.py tests/fakes.py tests/test_sql_graph.py
git commit -m "feat(toast): structured output for SQL candidates with parser fallback"
```

---

### Task 4: Кап контекста судьи по размеру (ветка `toast-logic`)

**Files:**
- Modify: `backend/toast/sql_graph.py` (константа `JUDGE_CONTEXT_CHARS`, функция `_rows_context`)
- Test: `backend/tests/test_sql_graph.py`

**Interfaces:**
- Consumes: `_rows_context(attempts, rows) -> str` (текущая сигнатура сохраняется).
- Produces: то же, но с капом по символам; константа `JUDGE_CONTEXT_CHARS = 8_000`.

- [ ] **Step 1: Написать падающий тест**

В `backend/tests/test_sql_graph.py`:

```python
def test_rows_context_caps_by_size():
    from toast.sql_graph import JUDGE_CONTEXT_CHARS, _rows_context

    big = {"column_1": "x" * JUDGE_CONTEXT_CHARS}
    small = {"column_1": "y"}
    ctx = _rows_context([], [big, small])
    assert "Показано строк: 1 из 2" in ctx
    assert '"y"' not in ctx

    # Хотя бы одна строка отдаётся всегда, даже если сама больше лимита.
    ctx_one = _rows_context([], [big])
    assert "Показано строк: 1 из 1" in ctx_one
```

- [ ] **Step 2: Убедиться, что тест падает**

Run: `cd backend && uv run pytest tests/test_sql_graph.py::test_rows_context_caps_by_size -q`
Expected: FAIL — `ImportError: cannot import name 'JUDGE_CONTEXT_CHARS'`.

- [ ] **Step 3: Реализация**

В `backend/toast/sql_graph.py` рядом с `JUDGE_ROWS_CAP` добавить:

```python
JUDGE_CONTEXT_CHARS = 8_000  # кап сериализованных строк для судьи/суммаризатора
```

Заменить тело `_rows_context`:

```python
def _rows_context(attempts: list[Attempt], rows: list[dict]) -> str:
    """Строки для контекста LLM с честной пометкой о неполноте выборки.

    Два капа: не больше JUDGE_ROWS_CAP строк и не больше ~JUDGE_CONTEXT_CHARS
    символов JSON (одна «широкая» строка не должна раздувать контекст).
    Хотя бы одна строка отдаётся всегда.
    """
    shown: list[dict] = []
    size = 0
    for row in rows[:JUDGE_ROWS_CAP]:
        piece = json.dumps(row, ensure_ascii=False, default=str)
        if shown and size + len(piece) > JUDGE_CONTEXT_CHARS:
            break
        shown.append(row)
        size += len(piece)
    note = f"Показано строк: {len(shown)} из {len(rows)}"
    if any(a["truncated"] for a in attempts):
        note += " (результат SQL дополнительно усечён лимитом исполнителя)"
    return f"{note}.\nСтроки: {json.dumps(shown, ensure_ascii=False, default=str)}"
```

- [ ] **Step 4: Прогнать тесты, закоммитить**

Run: `cd backend && uv run pytest tests/ -q && uv run ruff check .`
Expected: 0 failed.

```bash
cd backend
git add toast/sql_graph.py tests/test_sql_graph.py
git commit -m "feat(toast): cap judge/summarizer row context by serialized size"
```

Run: `cd studio && uv run pytest -q` — Expected: `2 passed` (регресс Studio после задач 2–4).

---

### Task 5: Ветка демо, конфиг демо-таблицы, профиль «SQL (демо)»

**Files:**
- Branch: `git checkout -b demo/sql-chat` (от `toast-logic` после Task 4)
- Modify: `backend/config.py` (поля `sql_demo_*`)
- Modify: `backend/app.py` (функция `chat_profiles`)
- Test: `backend/tests/test_sql_demo.py` (новый файл)

**Interfaces:**
- Consumes: `Settings` / `get_settings()` из `config.py`; `toast_dsn` property.
- Produces: `Settings.sql_demo_table: str`, `Settings.sql_demo_desc_vector: str`, `Settings.sql_demo_desc_full: str`; профиль `sql` в `chat_profiles()` при наличии кредов.

- [ ] **Step 1: Создать ветку**

```bash
git checkout -b demo/sql-chat
```

- [ ] **Step 2: Написать падающие тесты**

Создать `backend/tests/test_sql_demo.py`:

```python
"""Тесты демо-режима «SQL (демо)»: конфиг, профиль, конвертация шагов."""

import asyncio
import importlib


def _app():
    return importlib.import_module("app")


def test_sql_demo_settings_defaults():
    from config import get_settings

    s = get_settings()
    assert s.sql_demo_table.startswith("toast_tbl_")
    assert s.sql_demo_desc_vector
    assert s.sql_demo_desc_full


def test_sql_profile_requires_creds(monkeypatch):
    from config import get_settings

    app = _app()
    monkeypatch.delenv("TOAST_DB_HOST", raising=False)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    get_settings.cache_clear()
    assert [p.name for p in asyncio.run(app.chat_profiles())] == ["fast", "deep"]


def test_sql_profile_registered_with_creds(monkeypatch):
    from config import get_settings

    app = _app()
    for key, value in {
        "TOAST_DB_HOST": "h", "TOAST_DB_USER": "u",
        "TOAST_DB_PASSWORD": "p", "TOAST_DB_NAME": "d",
        "OPENROUTER_API_KEY": "k",
    }.items():
        monkeypatch.setenv(key, value)
    get_settings.cache_clear()
    assert [p.name for p in asyncio.run(app.chat_profiles())] == [
        "fast", "deep", "sql",
    ]
```

- [ ] **Step 3: Убедиться, что тесты падают**

Run: `cd backend && uv run pytest tests/test_sql_demo.py -q`
Expected: FAIL — `AttributeError: 'Settings' object has no attribute 'sql_demo_table'` и/или список профилей `["fast", "deep"]` в третьем тесте.

- [ ] **Step 4: Поля в `config.py`**

После блока `# --- Toast БД для SQL-инструмента …` добавить:

```python
    # --- SQL-демо: таблица и описания для профиля «SQL (демо)» (demo-ветка) ---
    sql_demo_table: str = Field(
        default="toast_tbl_ec48a6d52d16ab405f95",
        validation_alias="SQL_DEMO_TABLE",
    )
    sql_demo_desc_vector: str = Field(
        default="юристы Adventum, ФИО и должности",
        validation_alias="SQL_DEMO_DESC_VECTOR",
    )
    sql_demo_desc_full: str = Field(
        default=(
            "Table payload: Лист1 A15:R16. Реестр юристов: ФИО, должность, email."
        ),
        validation_alias="SQL_DEMO_DESC_FULL",
    )
```

- [ ] **Step 5: Профиль в `app.py`**

Заменить тело `chat_profiles()`:

```python
@cl.set_chat_profiles
async def chat_profiles() -> list[cl.ChatProfile]:
    profiles = [
        cl.ChatProfile(
            name="fast",
            display_name="Быстрый",
            markdown_description=(
                "Фиксированный langgraph-маршрут с одним циклом "
                "инструментов (калькулятор). Предсказуем и быстр."
            ),
            default=True,
        ),
        cl.ChatProfile(
            name="deep",
            display_name="Умный",
            markdown_description=(
                "deepagents: сам планирует шаги и вызовы инструментов "
                "(калькулятор). Для сложных задач (медленнее)."
            ),
        ),
    ]
    s = get_settings()
    # Демо SQL-графа: только при полном конфиге — полурабочих режимов нет.
    if s.toast_dsn and s.openrouter_api_key:
        profiles.append(
            cl.ChatProfile(
                name="sql",
                display_name="SQL (демо)",
                markdown_description=(
                    "Каждый вопрос идёт в SQL-граф по демо-таблице; стадии "
                    "видны в «Ходе выполнения»."
                ),
            )
        )
    return profiles
```

- [ ] **Step 6: Прогнать тесты, закоммитить**

Run: `cd backend && uv run pytest tests/ -q && uv run ruff check .`
Expected: 0 failed.

```bash
cd backend
git add config.py app.py tests/test_sql_demo.py
git commit -m "feat(demo): SQL demo settings and conditional chat profile"
```

---

### Task 6: `sql_demo.step_payload` — чистая конвертация узла в шаг

**Files:**
- Create: `backend/sql_demo.py`
- Test: `backend/tests/test_sql_demo.py` (дополнить)

**Interfaces:**
- Consumes: формат `Attempt` из `toast/sql_graph.py` (`{"sql", "ok", "error", "rows", "row_count", "truncated"}`); дельты узлов графа (`generate` → `{"candidates", "round"}`, `execute` → `{"attempts", "executed_count"}`, `judge` → `{"verdict"}`).
- Produces: `step_payload(node: str, delta: dict, *, round_no: int, seen_attempts: int) -> StepDesc | None`; `StepDesc = {"name": str, "output": str, "children": list[SubStep]}`; `SubStep = {"name": str, "input": str, "output": str, "is_error": bool}`; константа `ROWS_PREVIEW = 5`.

- [ ] **Step 1: Написать падающие тесты**

Дополнить `backend/tests/test_sql_demo.py`:

```python
def _attempt(sql="SELECT 1", ok=True, error=None, rows=None, row_count=0):
    rows = rows if rows is not None else []
    return {"sql": sql, "ok": ok, "error": error, "rows": rows,
            "row_count": row_count, "truncated": False}


def test_step_payload_generate():
    from sql_demo import step_payload

    desc = step_payload(
        "generate", {"candidates": ["SELECT a", "SELECT b"], "round": 2},
        round_no=2, seen_attempts=0,
    )
    assert desc["name"] == "Генерация SQL — раунд 2"
    assert "SELECT a" in desc["output"] and "SELECT b" in desc["output"]
    assert desc["children"] == []


def test_step_payload_execute_slices_new_attempts():
    from sql_demo import step_payload

    old = _attempt(sql="SELECT old", rows=[{"a": 1}], row_count=1)
    ok = _attempt(sql="SELECT fresh", rows=[{"a": 2}], row_count=1)
    bad = _attempt(sql="SELECT bad", ok=False, error="Ошибка SQL: x")
    desc = step_payload(
        "execute", {"attempts": [old, ok, bad], "executed_count": 3},
        round_no=2, seen_attempts=1,
    )
    assert desc["name"] == "Выполнение SQL — раунд 2"
    assert [c["name"] for c in desc["children"]] == ["Попытка 2", "Попытка 3"]
    assert desc["children"][0]["input"] == "SELECT fresh"
    assert desc["children"][0]["is_error"] is False
    assert desc["children"][1]["is_error"] is True
    assert "Ошибка SQL: x" in desc["children"][1]["output"]


def test_step_payload_preview_truncates_rows():
    from sql_demo import ROWS_PREVIEW, step_payload

    rows = [{"n": i} for i in range(ROWS_PREVIEW + 3)]
    att = _attempt(rows=rows, row_count=len(rows))
    desc = step_payload("execute", {"attempts": [att]},
                        round_no=1, seen_attempts=0)
    out = desc["children"][0]["output"]
    assert f"всего строк: {ROWS_PREVIEW + 3}" in out
    assert '"n": 0' in out


def test_step_payload_zero_rows_and_judge_and_skips():
    from sql_demo import step_payload

    empty = _attempt(rows=[], row_count=0)
    desc = step_payload("execute", {"attempts": [empty]},
                        round_no=1, seen_attempts=0)
    assert desc["children"][0]["output"] == "0 строк"

    judge = step_payload("judge", {"verdict": "need_more"},
                         round_no=1, seen_attempts=0)
    assert judge["name"] == "Оценка достаточности"
    assert judge["output"] == "need_more"

    assert step_payload("init", {}, round_no=0, seen_attempts=0) is None
    assert step_payload("summarize", {"answer": "x"},
                        round_no=1, seen_attempts=0) is None
```

- [ ] **Step 2: Убедиться, что тесты падают**

Run: `cd backend && uv run pytest tests/test_sql_demo.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'sql_demo'`.

- [ ] **Step 3: Реализация — создать `backend/sql_demo.py`**

```python
"""Демо-режим «SQL (демо)»: конвертация хода SQL-графа в Chainlit-шаги.

Граф (toast/) про Chainlit не знает: он отдаёт события через
astream(stream_mode=["updates", "messages", "values"]), а этот модуль
превращает их в cl.Step (стадии + вложенные попытки) и стрим токенов ответа.
Живёт только в демо-ветке; в прод не мержится.
"""

import json
from typing import TypedDict

ROWS_PREVIEW = 5  # сколько строк показываем в output попытки


class SubStep(TypedDict):
    """Вложенный шаг одной SQL-попытки."""

    name: str
    input: str
    output: str
    is_error: bool


class StepDesc(TypedDict):
    """Описание Chainlit-шага стадии графа."""

    name: str
    output: str
    children: list[SubStep]


def _attempt_preview(attempt: dict) -> str:
    """Короткий output попытки: ошибка, «0 строк» или превью строк."""
    if not attempt["ok"]:
        return attempt["error"] or "ошибка"
    if attempt["row_count"] == 0:
        return "0 строк"
    preview = json.dumps(attempt["rows"][:ROWS_PREVIEW],
                         ensure_ascii=False, default=str)
    if attempt["row_count"] > ROWS_PREVIEW:
        preview += f"\n… всего строк: {attempt['row_count']}"
    return preview


def step_payload(node: str, delta: dict, *, round_no: int,
                 seen_attempts: int) -> StepDesc | None:
    """Описание шага для завершившегося узла графа; None — узел не показываем.

    init не несёт информации; summarize уходит токенами в само сообщение.
    seen_attempts — сколько попыток уже показано прошлыми раундами: дельта
    узла execute содержит НАКОПЛЕННЫЙ список attempts.
    """
    if node == "generate":
        cands = delta.get("candidates", [])
        return {
            "name": f"Генерация SQL — раунд {round_no}",
            "output": "\n\n".join(cands) if cands else "(нет кандидатов)",
            "children": [],
        }
    if node == "execute":
        new = delta.get("attempts", [])[seen_attempts:]
        return {
            "name": f"Выполнение SQL — раунд {round_no}",
            "output": f"попыток: {len(new)}",
            "children": [
                {
                    "name": f"Попытка {seen_attempts + i + 1}",
                    "input": a["sql"],
                    "output": _attempt_preview(a),
                    "is_error": not a["ok"],
                }
                for i, a in enumerate(new)
            ],
        }
    if node == "judge":
        return {
            "name": "Оценка достаточности",
            "output": delta.get("verdict", ""),
            "children": [],
        }
    return None
```

- [ ] **Step 4: Прогнать тесты, закоммитить**

Run: `cd backend && uv run pytest tests/test_sql_demo.py -q && uv run ruff check .`
Expected: все PASS.

```bash
cd backend
git add sql_demo.py tests/test_sql_demo.py
git commit -m "feat(demo): pure node-to-step conversion for SQL graph progress"
```

---

### Task 7: `handle_sql_message` и маршрутизация в `app.py`

**Files:**
- Modify: `backend/sql_demo.py` (добавить `build_demo_graph`, `handle_sql_message`)
- Modify: `backend/app.py` (`on_chat_start`, `on_chat_resume`, `on_message`, импорты)
- Test: `backend/tests/test_app_imports.py` (регресс импорта), ручная проверка в Task 10

**Interfaces:**
- Consumes: `step_payload` из Task 6; `build_sql_graph`, `PgExecutor`, `build_sql_model`, `get_settings` (существующие); `SqlToolInput` поля (`question/chunk_id/table/desc_vector/desc_full`).
- Produces: `build_demo_graph() -> CompiledStateGraph`; `async handle_sql_message(graph, question: str, out: cl.Message) -> None`; сессионный ключ `"sql_graph"`.

- [ ] **Step 1: Дополнить `backend/sql_demo.py`**

В начало файла добавить импорты (после докстринга, вместе с существующим `import json`):

```python
import json
from typing import TypedDict

import chainlit as cl
from langchain_core.messages import AIMessageChunk
from langgraph.graph.state import CompiledStateGraph

from agents.base import build_sql_model
from config import get_settings
from toast.executor import PgExecutor
from toast.sql_graph import build_sql_graph
```

В конец файла добавить:

```python
def build_demo_graph() -> CompiledStateGraph:
    """Граф демо-режима: та же сборка, что в Studio, DSN и лимиты из настроек."""
    s = get_settings()
    if s.toast_dsn is None:  # профиль регистрируется только с кредами
        raise RuntimeError("SQL-демо требует TOAST_DB_* в окружении")
    return build_sql_graph(
        build_sql_model(),
        PgExecutor(s.toast_dsn),
        max_queries=s.sql_max_queries,
        candidates_per_round=s.sql_candidates_per_round,
    )


async def handle_sql_message(graph: CompiledStateGraph, question: str,
                             out: cl.Message) -> None:
    """Один прогон графа: стадии → cl.Step, токены summarize → сообщение out.

    stream_mode: updates — завершившиеся узлы (→ шаги), messages — токены
    LLM (незатегированный summarize стримится в ответ), values — финальное
    состояние (ответ для no_data/error, где LLM не вызывается).
    """
    s = get_settings()
    inputs = {
        "question": question,
        "chunk_id": "demo",
        "table": s.sql_demo_table,
        "desc_vector": s.sql_demo_desc_vector,
        "desc_full": s.sql_demo_desc_full,
    }
    streamed = ""
    final_state: dict | None = None
    round_no = 0
    seen_attempts = 0
    async for mode, payload in graph.astream(
        inputs, stream_mode=["updates", "messages", "values"]
    ):
        if mode == "values":
            final_state = payload
            continue
        if mode == "messages":
            chunk, meta = payload
            if "internal" in (meta.get("tags") or []):
                continue
            if (
                isinstance(chunk, AIMessageChunk)
                and isinstance(chunk.content, str)
                and chunk.content
            ):
                streamed += chunk.content
                await out.stream_token(chunk.content)
            continue
        for node, delta in payload.items():
            if node == "generate":
                round_no = delta.get("round", round_no + 1)
            desc = step_payload(node, delta, round_no=round_no,
                                seen_attempts=seen_attempts)
            if node == "execute":
                seen_attempts = len(delta.get("attempts", []))
            if desc is None:
                continue
            async with cl.Step(name=desc["name"], type="tool") as step:
                step.output = desc["output"]
                for child in desc["children"]:
                    async with cl.Step(name=child["name"], type="tool") as sub:
                        sub.input = child["input"]
                        sub.output = child["output"]
                        sub.is_error = child["is_error"]
    # no_data/error не зовут LLM — токенов не было, берём ответ из состояния.
    if not streamed and final_state and final_state.get("answer"):
        await out.stream_token(final_state["answer"])
```

- [ ] **Step 2: Маршрутизация в `app.py`**

Импорт (после `from auth import verify_ticket`):

```python
from sql_demo import build_demo_graph, handle_sql_message
```

Добавить `import logging` в начало импортов и логгер после констант:

```python
logger = logging.getLogger(__name__)
```

`on_chat_start` заменить на:

```python
@cl.on_chat_start
async def on_chat_start() -> None:
    if cl.user_session.get("chat_profile") == "sql":
        cl.user_session.set("sql_graph", build_demo_graph())
        return
    cl.user_session.set("agent", _build_session_agent())
    cl.user_session.set("history", [])
```

В `on_chat_resume` первой строкой тела добавить:

```python
    if cl.user_session.get("chat_profile") == "sql":
        # Граф без памяти диалога: история сообщений/шагов и так в data layer.
        cl.user_session.set("sql_graph", build_demo_graph())
        return
```

В `on_message` первой строкой тела добавить блок:

```python
    sql_graph = cl.user_session.get("sql_graph")
    if sql_graph is not None:
        out = cl.Message(content="")
        await out.send()
        try:
            await handle_sql_message(sql_graph, message.content, out)
        except Exception:
            logger.exception("SQL demo run failed")
            await out.stream_token(
                "Не удалось выполнить прогон SQL-графа. Попробуйте ещё раз."
            )
        await out.update()
        return
```

- [ ] **Step 3: Прогнать тесты и линтер**

Run: `cd backend && uv run pytest tests/ -q && uv run ruff check .`
Expected: 0 failed (test_app_imports подтверждает, что app.py импортируется с новым модулем).

- [ ] **Step 4: Commit**

```bash
cd backend
git add sql_demo.py app.py
git commit -m "feat(demo): sql chat profile handler streaming graph stages as steps"
```

---

### Task 8: Фронтенд — иерархический сбор шагов

**Files:**
- Modify: `frontend/src/chat/executionSteps.ts`
- Test: `frontend/src/chat/executionSteps.test.ts`

**Interfaces:**
- Consumes: `IStep` из `@chainlit/react-client` (поля `type`, `steps`).
- Produces: `collectToolStepsByMessage(steps: IStep[]): Map<string, IStep[]>` — та же сигнатура, но в значениях только ВЕРХНЕУРОВНЕВЫЕ tool-шаги; их дети доступны через `step.steps`.

- [ ] **Step 1: Написать падающий тест**

В `frontend/src/chat/executionSteps.test.ts` добавить в `describe`:

```typescript
  it("вложенные tool-шаги остаются детьми и не дублируются на верхнем уровне", () => {
    const tree: IStep[] = [
      step({
        id: "run1",
        type: "run",
        steps: [
          step({ id: "a1", type: "assistant_message", output: "ответ" }),
          step({
            id: "stage1",
            name: "Выполнение SQL — раунд 1",
            type: "tool",
            steps: [
              step({ id: "att1", name: "Попытка 1", type: "tool" }),
              step({ id: "att2", name: "Попытка 2", type: "tool" }),
            ],
          }),
        ],
      }),
    ];
    const map = collectToolStepsByMessage(tree);
    expect(map.get("a1")!.map((s) => s.id)).toEqual(["stage1"]);
    expect(map.get("a1")![0].steps!.map((s) => s.id)).toEqual(["att1", "att2"]);
  });
```

- [ ] **Step 2: Убедиться, что тест падает**

Run: `cd frontend && npm test`
Expected: FAIL — верхний уровень содержит `["stage1", "att1", "att2"]` (текущее сплющивание).

- [ ] **Step 3: Реализация**

В `frontend/src/chat/executionSteps.ts` заменить `gatherTools`:

```typescript
// Собирает верхнеуровневые tool-шаги поддерева: в tool-узлы не спускаемся,
// их дети остаются доступными через step.steps (иерархия для рендера).
function gatherTools(nodes: IStep[], out: IStep[]): void {
  for (const node of nodes) {
    if (node.type === "tool") {
      out.push(node);
      continue;
    }
    if (node.steps?.length) gatherTools(node.steps, out);
  }
}
```

(Вызовы не меняются — меняется только поведение обхода.)

- [ ] **Step 4: Прогнать тесты, закоммитить**

Run: `cd frontend && npm test`
Expected: все PASS (существующие тесты не меняются: у калькулятора нет вложенных tool-детей).

```bash
cd frontend
git add src/chat/executionSteps.ts src/chat/executionSteps.test.ts
git commit -m "feat(demo): preserve tool step hierarchy for nested stage rendering"
```

---

### Task 9: Фронтенд — рекурсивный сворачиваемый рендер

**Files:**
- Modify: `frontend/src/components/ExecutionSteps/ExecutionSteps.tsx`
- Modify: `frontend/src/components/ExecutionSteps/ExecutionSteps.module.css`
- Test: `frontend/src/components/ExecutionSteps/ExecutionSteps.test.tsx` (новый)

**Interfaces:**
- Consumes: `Map`-значения из Task 8 (верхнеуровневые tool-шаги с детьми в `step.steps`); поля `IStep`: `name`, `input`, `output`, `isError`, `streaming`, `end`.
- Produces: тот же компонент `ExecutionSteps({ steps, running })` — контракт для `AssistantMessage.tsx` не меняется.

- [ ] **Step 1: Написать падающий рендер-тест**

Создать `frontend/src/components/ExecutionSteps/ExecutionSteps.test.tsx`:

```tsx
/** @vitest-environment happy-dom */
import { describe, expect, it } from "vitest";
import { act } from "react";
import { createRoot } from "react-dom/client";
import type { IStep } from "@chainlit/react-client";
import ExecutionSteps from "./ExecutionSteps";

const step = (over: Partial<IStep>): IStep =>
  ({
    id: "s",
    name: "step",
    type: "tool",
    output: "",
    createdAt: "2026-07-17T09:00:00Z",
    end: "2026-07-17T09:00:01Z",
    ...over,
  }) as IStep;

describe("ExecutionSteps", () => {
  it("рендерит двухуровневое дерево сворачиваемых стадий", async () => {
    const stage = step({
      id: "stage1",
      name: "Выполнение SQL — раунд 1",
      steps: [
        step({ id: "att1", name: "Попытка 1", input: "SELECT 1", output: "[]" }),
        step({ id: "att2", name: "Попытка 2", isError: true, output: "Ошибка" }),
      ],
    });
    const host = document.createElement("div");
    document.body.appendChild(host);
    const root = createRoot(host);
    await act(async () => {
      root.render(<ExecutionSteps steps={[stage]} running={false} />);
    });
    expect(host.textContent).toContain("Выполнение SQL — раунд 1");
    expect(host.textContent).toContain("Попытка 1");
    expect(host.textContent).toContain("Попытка 2");
    // details: панель + стадия + 2 попытки
    expect(host.querySelectorAll("details").length).toBe(4);
  });
});
```

- [ ] **Step 2: Убедиться, что тест падает**

Run: `cd frontend && npm test`
Expected: FAIL — сейчас details ровно 1 (панель), вложенных нет.

- [ ] **Step 3: Реализация — заменить `ExecutionSteps.tsx` целиком**

```tsx
import type { IStep } from "@chainlit/react-client";
import styles from "./ExecutionSteps.module.css";

interface Props {
  steps: IStep[];
  running: boolean;
}

function statusMark(step: IStep): string {
  if (step.isError) return "✗";
  if (step.streaming || !step.end) return "…";
  return "✓";
}

function StepItem({ step }: { step: IStep }) {
  const children = (step.steps ?? []).filter((s) => s.type === "tool");
  const isRunning = Boolean(step.streaming) || !step.end;
  return (
    <li className={step.isError ? styles.itemError : styles.item}>
      <details open={isRunning}>
        <summary className={styles.stepSummary}>
          <span className={styles.mark}>{statusMark(step)}</span>
          {step.name}
        </summary>
        {step.input ? <pre className={styles.io}>{step.input}</pre> : null}
        {step.output || step.streaming ? (
          <pre className={styles.io}>
            {step.output || (step.streaming ? "…" : "")}
          </pre>
        ) : null}
        {children.length ? (
          <ol className={styles.list}>
            {children.map((child) => (
              <StepItem key={child.id} step={child} />
            ))}
          </ol>
        ) : null}
      </details>
    </li>
  );
}

export default function ExecutionSteps({ steps, running }: Props) {
  if (!steps.length) return null;

  return (
    <details className={styles.box} open={running}>
      <summary className={styles.summary}>
        Ход выполнения
        <span className={styles.count}>{steps.length}</span>
      </summary>
      <ol className={styles.list}>
        {steps.map((step) => (
          <StepItem key={step.id} step={step} />
        ))}
      </ol>
    </details>
  );
}
```

- [ ] **Step 4: CSS — добавить классы, убрать неиспользуемый**

В `ExecutionSteps.module.css` УДАЛИТЬ блок `.name { … }` (класс больше не используется) и добавить:

```css
.stepSummary {
  display: flex;
  align-items: center;
  gap: 6px;
  cursor: pointer;
  font-weight: 600;
  color: #2b3443;
  user-select: none;
}

.mark {
  font-size: 11px;
  color: #5b6675;
}
```

- [ ] **Step 5: Прогнать тесты и сборку, закоммитить**

Run: `cd frontend && npm test && npm run build`
Expected: все PASS, сборка без ошибок TypeScript.

```bash
cd frontend
git add src/components/ExecutionSteps/
git commit -m "feat(demo): recursive collapsible rendering of execution steps"
```

---

### Task 10: Режим «SQL (демо)» во фронтенде + инструкция запуска

**Files:**
- Modify: `frontend/src/chat/ChainlitRuntimeProvider.tsx:20` (тип `ChatMode`)
- Modify: `frontend/src/components/Sidebar/Sidebar.tsx:63-83` (кнопка режима)
- Create: `docs/sql-demo.md`

**Interfaces:**
- Consumes: `ChatMode` уже прокинут через `App.tsx` → `ChainlitRuntimeProvider` (проп `chatProfile`) → chainlit-сессия; имя профиля обязано совпадать с бэкендом: `"sql"`.
- Produces: третий режим UI; инструкция ручного прогона.

- [ ] **Step 1: Расширить тип**

В `frontend/src/chat/ChainlitRuntimeProvider.tsx` заменить:

```typescript
export type ChatMode = "fast" | "deep";
```

на:

```typescript
export type ChatMode = "fast" | "deep" | "sql";
```

- [ ] **Step 2: Кнопка в Sidebar**

В `frontend/src/components/Sidebar/Sidebar.tsx` после кнопки «Умный» (перед закрывающим `</div>` блока `modeSwitch`) добавить:

```tsx
          <button
            type="button"
            className={mode === "sql" ? styles.modeActive : styles.modeButton}
            onClick={() => onModeChange("sql")}
          >
            SQL (демо)
          </button>
```

- [ ] **Step 3: Сборка и тесты**

Run: `cd frontend && npm test && npm run build`
Expected: PASS, сборка чистая.

- [ ] **Step 4: Инструкция ручного прогона — создать `docs/sql-demo.md`**

```markdown
# Демо SQL-графа в чате (ветка demo/sql-chat)

Ветка демонстрационная, в main не мержится.

## Запуск

1. Бэкенд (нужны env: `CHAINLIT_DB_*`, `CHAINLIT_JWT_*`, `OPENROUTER_API_KEY`,
   `TOAST_DB_*`; опционально `SQL_DEMO_TABLE` / `SQL_DEMO_DESC_VECTOR` /
   `SQL_DEMO_DESC_FULL` для смены демо-таблицы):

       cd backend && uv run chainlit run app.py

2. Фронтенд:

       cd frontend && npm run dev

## Сценарий показа

1. Войти, в сайдбаре выбрать режим «SQL (демо)» (создастся новый чат).
2. Спросить: «Какие ФИО у юристов и их должности?»
3. Под ответом раскрыть «Ход выполнения»: стадии «Генерация SQL — раунд N» →
   «Выполнение SQL — раунд N» (внутри попытки с SQL и превью строк) →
   «Оценка достаточности». Все уровни сворачиваемые.
4. Спросить что-то не по таблице («Какая погода?») — граф ответит
   «В данных таблицы нет ответа…», попытки с 0 строк видны в стадиях.
5. Открыть старый тред из списка — стадии воспроизводятся из истории.

Без `TOAST_DB_*`/`OPENROUTER_API_KEY` профиль «SQL (демо)» на бэкенде не
регистрируется; кнопка в сайдбаре тогда создаст сессию с дефолтным профилем —
это ожидаемо для демо-ветки.
```

- [ ] **Step 5: Ручная проверка по `docs/sql-demo.md`**

Пройти сценарий показа целиком (пункты 1–5). Ожидаемо: стадии появляются живьём по мере работы графа, попытки вложены в «Выполнение SQL», ошибки красные, resume воспроизводит шаги.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/chat/ChainlitRuntimeProvider.tsx \
        frontend/src/components/Sidebar/Sidebar.tsx docs/sql-demo.md
git commit -m "feat(demo): SQL demo chat mode in sidebar and run instructions"
```

---

## Final Verification

- [ ] `cd backend && uv run pytest tests/ -q` — 0 failed
- [ ] `cd backend && uv run ruff check .` — чисто
- [ ] `cd studio && uv run pytest -q` — 2 passed (Studio-совместимость)
- [ ] `cd frontend && npm test && npm run build` — чисто
- [ ] Ветка `toast-logic` содержит задачи 1–4, ветка `demo/sql-chat` — 5–10
- [ ] Ручной сценарий из `docs/sql-demo.md` пройден
