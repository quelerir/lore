# SQL Tool Readability Refactor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Разнести `toast/sql_graph.py` (~450 строк, четыре ответственности) на `models.py`/`prompts.py`/`llm.py`/`sql_graph.py`, заменить строковые контракты типизированными (`Refusal`/`DbError`, enum'ы) — строго без изменения поведения.

**Architecture:** Чистый рефакторинг: сначала типы и контракт исполнителя (единственное место, где меняется внутренний интерфейс), затем механические выносы промптов и LLM-обвязки, затем узлы в класс, затем разбиение тестов. После каждой задачи все сьюты зелёные.

**Tech Stack:** Python 3.13+/pydantic/langgraph/sqlglot/pytest.

**Spec:** `docs/superpowers/specs/2026-07-17-sql-tool-readability-design.md`

## Global Constraints

- Ветка `toast-logic`; в конце — merge в `demo/sql-chat` и `backend` (Task 6).
- **Поведение не меняется**: существующие ассерты тестов не редактируются (только импорты и типы в фикстурах); промпты байт-в-байт те же; вход/выход графа, сигнатура `build_sql_graph`, внешний контракт `_project` и тексты ошибок в `Attempt.error` — без изменений.
- Команды из `backend/`: `uv run pytest tests/ -q`, `uv run ruff check .`; Studio: `cd studio && uv run pytest -q`.

---

### Task 1: `models.py` — все типы + типизированный контракт исполнителя

**Files:**
- Create: `backend/toast/models.py`
- Modify: `backend/toast/executor.py`, `backend/toast/sql_graph.py`
- Test: `backend/tests/test_sql_graph.py`, `backend/tests/test_sql_tool.py`, `backend/tests/test_executor_pool.py`, `backend/tests/test_executor.py`

**Interfaces:**
- Produces: модуль `toast.models` c `Status`/`Verdict` (StrEnum), `SelectResult`/`Attempt` (TypedDict), `Refusal(reason: str)`/`DbError(message: str)` (dataclass), `SqlCandidates`/`JudgeVerdict`/`SqlToolInput`/`SqlToolState` (pydantic), `make_attempt(sql, res) -> Attempt`, `ok_rows(attempts) -> list[dict]`. `executor.run_select(...) -> SelectResult | Refusal | DbError`.

- [ ] **Step 1: Создать `backend/toast/models.py`**

```python
"""Все типы SQL-инструмента: состояние графа, structured output, результаты.

Единое место объявления моделей. Контракты между слоями выражены типами, а
не строковыми префиксами: результат исполнителя различается isinstance'ом
(SelectResult | Refusal | DbError) — от Refusal зависит подсчёт бюджета.
"""

import logging
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, TypedDict

from pydantic import BaseModel, Field


class Status(StrEnum):
    """Итог прогона инструмента (внешний контракт: ok / no_data / error)."""

    OK = "ok"
    NO_DATA = "no_data"
    ERROR = "error"


class Verdict(StrEnum):
    """Вердикт судьи в состоянии графа."""

    SUFFICIENT = "sufficient"
    NEED_MORE = "need_more"


class SelectResult(TypedDict):
    """Результат успешного SELECT (строки уже приведены к JSON-совместимым типам)."""

    columns: list[str]
    rows: list[dict[str, Any]]
    row_count: int
    truncated: bool


@dataclass
class Refusal:
    """Отказ guardrails: SQL не дошёл до БД — бюджет НЕ тратится."""

    reason: str


@dataclass
class DbError:
    """Ошибка БД/сети/таймаута: SQL дошёл до БД — бюджет потрачен."""

    message: str


class Attempt(TypedDict):
    """Одна попытка выполнения SQL-кандидата (успех или отказ/ошибка)."""

    sql: str
    ok: bool
    error: str | None
    rows: list[dict[str, Any]]
    row_count: int
    truncated: bool


class SqlCandidates(BaseModel):
    """Батч SQL-кандидатов — схема structured output узла generate."""

    candidates: list[str]


class JudgeVerdict(BaseModel):
    """Вердикт судьи: достаточно ли строк и почему нет (structured output)."""

    sufficient: bool
    reason: str = ""


class SqlToolInput(BaseModel):
    """Входные поля инструмента (форма ввода в Studio)."""

    question: str
    chunk_id: str
    table: str
    desc_vector: str
    desc_full: str


class SqlToolState(SqlToolInput):
    """Состояние графа: вход + аккумуляторы с дефолтами.

    Дефолты полей заменяют бывший узел init: langgraph применяет их сам,
    «забытая инициализация» перестала существовать как класс ошибки
    (инцидент KeyError: 'candidates' в TypedDict-версии). Узлы возвращают
    dict-апдейты, langgraph сливает их в состояние.
    """

    sample_rows: list[dict] = Field(default_factory=list)
    candidates: list[str] = Field(default_factory=list)
    round: int = 0
    executed_count: int = 0
    attempts: list[Attempt] = Field(default_factory=list)
    verdict: str = ""
    judge_reason: str = ""
    answer: str = ""
    status: str = ""


def make_attempt(sql: str, res: Any) -> Attempt:
    """Запись попытки из результата исполнителя.

    Принимает SelectResult | Refusal | DbError, а также исключение из
    gather(return_exceptions=True) — неожиданный сбой исполнителя не должен
    ронять весь граф, но обязан попасть в лог: иначе инфраструктурные
    проблемы (DNS, сеть до БД) видны только в UI как текст попытки.
    """
    if isinstance(res, BaseException):
        logging.getLogger(__name__).warning(
            "SQL attempt failed with exception: %r (sql=%.120s)", res, sql
        )
        res = DbError(f"Ошибка выполнения: {res!r}")
    if isinstance(res, Refusal):
        return {"sql": sql, "ok": False, "error": res.reason,
                "rows": [], "row_count": 0, "truncated": False}
    if isinstance(res, DbError):
        return {"sql": sql, "ok": False, "error": res.message,
                "rows": [], "row_count": 0, "truncated": False}
    return {"sql": sql, "ok": True, "error": None,
            "rows": res["rows"], "row_count": res["row_count"],
            "truncated": res["truncated"]}


def ok_rows(attempts: list[Attempt]) -> list[dict]:
    """Плоский список строк из всех успешных попыток."""
    out: list[dict] = []
    for a in attempts:
        if a["ok"]:
            out.extend(a["rows"])
    return out
```

- [ ] **Step 2: Типизированный результат в `executor.py`**

Удалить локальный класс `SelectResult`; импорт заменить на:

```python
from toast.models import DbError, Refusal, SelectResult
```

В `run_select` (докстринг: «Возвращает SelectResult при успехе, Refusal при
отказе guardrails, DbError при ошибке БД/таймауте»):

```python
        if refusal := validate_select(sql, table):
            return Refusal(refusal)
```

и в обработчиках исключений:

```python
        except TimeoutError:
            # Клиентский command_timeout asyncpg; серверный statement_timeout
            # приходит как QueryCanceledError (подкласс PostgresError).
            return DbError(f"Ошибка SQL: превышен таймаут {STATEMENT_TIMEOUT_MS} мс")
        except asyncpg.PostgresError as e:
            return DbError(f"Ошибка SQL: {e}")
```

- [ ] **Step 3: `sql_graph.py` — импорт типов из models, бюджет через isinstance**

Удалить из `sql_graph.py` определения `SqlCandidates`, `JudgeVerdict`,
`Attempt`, `SqlToolInput`, `SqlToolState`, `_attempt`, `_ok_rows`; добавить:

```python
from toast.models import (
    Attempt, DbError, JudgeVerdict, Refusal, SqlCandidates, SqlToolInput,
    SqlToolState, Status, Verdict, make_attempt, ok_rows,
)
```

Все вызовы `_attempt(` → `make_attempt(`, `_ok_rows(` → `ok_rows(`.

В узле `execute` подсчёт бюджета — по сырым результатам:

```python
        new = [make_attempt(sql, res) for sql, res in zip(unique, results)]
        # Бюджет — только SQL, дошедшие до БД: Refusal guardrails существует,
        # чтобы модель ПЕРЕПИСАЛА запрос, и не должен съедать попытку.
        executed = sum(1 for r in results if not isinstance(r, Refusal))
```

В узле `sample`:

```python
        if isinstance(res, (Refusal, DbError)):
            reason = res.reason if isinstance(res, Refusal) else res.message
            logging.getLogger(__name__).warning("sample refused: %s", reason)
            return {"sample_rows": []}
```

(вместо `isinstance(res, str)`).

Enum'ы вместо строк в узлах и роутерах:
- judge: `"verdict": Verdict.SUFFICIENT if verdict.sufficient else Verdict.NEED_MORE`
  (и детерминированная ветка без строк: `{"verdict": Verdict.NEED_MORE}`);
- summarize: `"status": Status.OK / Status.NO_DATA / Status.ERROR`;
- `after_judge`: `state.verdict == Verdict.SUFFICIENT`.

- [ ] **Step 4: Правка тестов (импорты и фикстуры, ассерты не трогаем)**

`backend/tests/test_sql_graph.py`:
- импорт: `from toast.models import DbError, JudgeVerdict, Refusal, SqlCandidates, SqlToolState, make_attempt` (локальные `from toast.sql_graph import ...` для этих имён убрать);
- фикстуры: `"Отказ: разрешён только SELECT."` → `Refusal("Отказ: разрешён только SELECT.")` (оба места), `"Ошибка SQL: сеть"` → `DbError("Ошибка SQL: сеть")`, `"Ошибка SQL: a"/"b"/"c"` → `DbError(...)`;
- `test_attempt_from_refusal_result_and_exception`: `_attempt("SELECT 1", "Отказ: только чтение")` → `make_attempt("SELECT 1", Refusal("Отказ: только чтение"))`; ожидаемые словари НЕ меняются.

`backend/tests/test_executor_pool.py`:
- `from toast.models import DbError` в импортах;
- таймаут-тест: `assert isinstance(res, DbError) and "таймаут" in res.message`;
- pg-error-тест: `assert isinstance(res, DbError) and res.message.startswith("Ошибка SQL:")`.

`backend/tests/test_executor.py` (live, скипается):
- `assert isinstance(bad, Refusal) and "Отказ" in bad.reason` (+ импорт).

- [ ] **Step 5: Прогнать всё**

Run: `cd backend && uv run pytest tests/ -q && uv run ruff check .`
Expected: `91 passed` (число прежнее — ассерты не менялись), `All checks passed!`

- [ ] **Step 6: Commit**

```bash
cd backend
git add toast/models.py toast/executor.py toast/sql_graph.py tests/
git commit -m "refactor(toast): models module; typed executor results replace string prefixes"
```

---

### Task 2: `prompts.py` — промпты и сборка текстов

**Files:**
- Create: `backend/toast/prompts.py`
- Modify: `backend/toast/sql_graph.py`
- Test: `backend/tests/test_sql_graph.py` (импорты)

**Interfaces:**
- Produces: `toast.prompts` c константами `FIXED_SCHEMA`, `GENERATE_SYS`, `JUDGE_SYS`, `SUMMARIZE_SYS`, `NO_DATA_MSG`, `NO_CANDIDATES_MSG`, `JUDGE_ROWS_CAP=30`, `JUDGE_CONTEXT_CHARS=8_000`, `SAMPLE_LIMIT=5`, `SAMPLE_CONTEXT_CHARS=2_000`; функциями `generate_prompt(state: SqlToolState, n: int) -> str`, `rows_context(attempts: list[Attempt]) -> str`.

- [ ] **Step 1: Создать `backend/toast/prompts.py`**

Константы переносятся из `sql_graph.py` БЕЗ изменения текста. Сборка
generate-промпта — секциями (результат байт-в-байт равен текущей
конкатенации: базовый блок и секции соединяются `"\n\n"`):

```python
"""Промпты SQL-инструмента и сборка текстов для LLM.

Промпт-инжиниринг живёт здесь: правки текстов не трогают логику графа.
generate_prompt собирает базовый блок + секции фидбека (ошибки, пустые
запросы, причина судьи, примеры строк); rows_context готовит строки
попыток для судьи/суммаризатора с честной пометкой о неполноте.
"""

import json

from toast.models import Attempt, SqlToolState

FIXED_SCHEMA = (
    "Таблицы извлечены из XLSX (Postgres, схема splitter_toast). У каждой "
    "первые служебные колонки: _splitter_row_number (int), "
    "_splitter_source_row (int), _splitter_source_range (text). Дальше — "
    "колонки данных: column_1, column_2, ... или переименованные "
    "(из заголовков). Используй физические имена колонок строго как в "
    "описании таблицы."
)

GENERATE_SYS = (
    FIXED_SCHEMA
    + " Составь SQL SELECT к ОДНОЙ переданной таблице, чтобы ответить на "
    "вопрос. Верни JSON-массив из нескольких РАЗНЫХ по подходу SELECT-строк "
    "(без markdown, без пояснений). Только SELECT, только эта таблица. "
    "Каждый элемент — ровно один запрос SELECT (WITH разрешён), "
    "без точки с запятой."
)
JUDGE_SYS = (
    "Ты оцениваешь, достаточно ли полученных строк, чтобы ответить на "
    "вопрос. Верни sufficient=true/false и короткую причину reason — "
    "почему строк недостаточно (она попадёт генератору SQL)."
)
SUMMARIZE_SYS = (
    "Ответь на вопрос пользователя СТРОГО по предоставленным строкам таблицы. "
    "Не выдумывай. Если данных недостаточно — так и скажи. Если показаны не "
    "все строки выборки — явно скажи, что ответ построен по неполной выборке. "
    "Кратко, по-русски."
)
NO_DATA_MSG = "В данных таблицы нет ответа на этот вопрос."
NO_CANDIDATES_MSG = "Модель не вернула ни одного SQL-кандидата."
JUDGE_ROWS_CAP = 30  # сколько строк отдаём в контекст судьи/суммаризатора
JUDGE_CONTEXT_CHARS = 8_000  # кап сериализованных строк для судьи/суммаризатора
SAMPLE_LIMIT = 5  # строк-примеров для промпта generate
SAMPLE_CONTEXT_CHARS = 2_000  # кап сериализованных примеров в промпте


def _errors_section(state: SqlToolState) -> str | None:
    errors = [a["error"] for a in state.attempts if not a["ok"] and a["error"]]
    if not errors:
        return None
    return "Прошлые ошибки SQL (исправь):\n" + "\n".join(errors[-3:])


def _empty_section(state: SqlToolState) -> str | None:
    empty = [a["sql"] for a in state.attempts if a["ok"] and a["row_count"] == 0]
    if not empty:
        return None
    return ("Эти запросы выполнились, но вернули 0 строк — "
            "нужен другой подход:\n" + "\n".join(empty[-3:]))


def _judge_section(state: SqlToolState) -> str | None:
    if not state.judge_reason:
        return None
    return (f"Прошлый результат отклонён судьёй: {state.judge_reason} — "
            "построй запрос иначе.")


def _sample_section(state: SqlToolState) -> str | None:
    if not state.sample_rows:
        return None
    sample_json = json.dumps(
        state.sample_rows, ensure_ascii=False, default=str
    )[:SAMPLE_CONTEXT_CHARS]
    return (f"Примеры строк таблицы (до {SAMPLE_LIMIT}, реальные "
            f"имена колонок и формат значений):\n{sample_json}")


def generate_prompt(state: SqlToolState, n: int) -> str:
    """Промпт узла generate: база + секции фидбека прошлых раундов."""
    base = (
        f"Вопрос: {state.question}\n"
        f"Таблица: {state.table}\n"
        f"Описание (кратко): {state.desc_vector}\n"
        f"Описание (полно): {state.desc_full}\n"
        f"Нужно вернуть до {n} разных SELECT."
    )
    sections = [_errors_section(state), _empty_section(state),
                _judge_section(state), _sample_section(state)]
    return "\n\n".join([base, *[s for s in sections if s]])


def rows_context(attempts: list[Attempt]) -> str:
    """Строки успешных попыток, сгруппированные по их SQL.

    Судья и суммаризатор видят, какой запрос что вернул, — плохой первый
    кандидат не вытесняет из контекста хороший второй безымянной смесью.
    Суммарные капы: JUDGE_ROWS_CAP строк и ~JUDGE_CONTEXT_CHARS символов;
    хотя бы одна строка отдаётся всегда.
    """
    sections: list[str] = []
    total = sum(a["row_count"] for a in attempts if a["ok"])
    shown = 0
    size = 0
    for a in attempts:
        if not a["ok"] or not a["rows"]:
            continue
        rows_out: list[dict] = []
        for row in a["rows"]:
            if shown >= JUDGE_ROWS_CAP:
                break
            piece = json.dumps(row, ensure_ascii=False, default=str)
            if shown and size + len(piece) > JUDGE_CONTEXT_CHARS:
                break
            rows_out.append(row)
            shown += 1
            size += len(piece)
        if rows_out:
            sections.append(
                f"Запрос: {a['sql']}\nСтроки: "
                + json.dumps(rows_out, ensure_ascii=False, default=str)
            )
    note = f"Показано строк: {shown} из {total}"
    if any(a["truncated"] for a in attempts):
        note += " (результат SQL дополнительно усечён лимитом исполнителя)"
    return note + ".\n" + "\n\n".join(sections)
```

- [ ] **Step 2: `sql_graph.py` использует prompts**

Удалить из `sql_graph.py` перенесённые константы и `_rows_context`;
добавить импорт:

```python
from toast.prompts import (
    GENERATE_SYS, JUDGE_SYS, NO_CANDIDATES_MSG, NO_DATA_MSG, SAMPLE_LIMIT,
    SUMMARIZE_SYS, generate_prompt, rows_context,
)
```

Узел `generate`: блоки `errors/empty/prompt/if ...` заменить на
`prompt = generate_prompt(state, n)`. Вызовы `_rows_context(state.attempts)`
→ `rows_context(state.attempts)`.

- [ ] **Step 3: Тесты**

В `test_sql_graph.py`: `from toast.sql_graph import JUDGE_CONTEXT_CHARS, _rows_context`
→ `from toast.prompts import JUDGE_CONTEXT_CHARS, rows_context` (и вызовы
`_rows_context(` → `rows_context(`); `parse_sql_candidates` пока остаётся в
`toast.sql_graph`.

Run: `cd backend && uv run pytest tests/ -q && uv run ruff check .` → `91 passed`.

- [ ] **Step 4: Commit**

```bash
cd backend
git add toast/prompts.py toast/sql_graph.py tests/test_sql_graph.py
git commit -m "refactor(toast): prompts module with sectioned prompt builder"
```

---

### Task 3: `llm.py` — structured output с фолбэками

**Files:**
- Create: `backend/toast/llm.py`
- Modify: `backend/toast/sql_graph.py`
- Test: `backend/tests/test_sql_graph.py` (импорт `parse_sql_candidates`)

**Interfaces:**
- Produces: `toast.llm` c `generate_candidates(model, messages, n) -> list[str]`, `judge_verdict(model, messages) -> JudgeVerdict`, `parse_sql_candidates(text, limit) -> list[str]`.

- [ ] **Step 1: Создать `backend/toast/llm.py`**

Перенести из `sql_graph.py` БЕЗ изменения тел: `parse_sql_candidates`,
`_generate_candidates` (→ `generate_candidates`), `_judge_verdict`
(→ `judge_verdict`), `_log_fallback`, `_SUFFICIENT_RE`, вместе с их
импортами (`json`, `logging`, `re`, `sqlglot`, `sql_exp`, `BaseChatModel`).

```python
"""LLM-обвязка SQL-инструмента: structured output с обязательными фолбэками.

OpenRouter-модели поддерживают function calling неровно, а фейки тестов не
поддерживают вовсе — поэтому у каждого structured-вызова есть текстовый
фолбэк, а причина фолбэка логируется (NotImplementedError ожидаем → debug,
остальное → warning: транзиентные ошибки не должны молча удваивать
латентность).
"""
```

(докстринги функций — как в текущем коде; у публичных имён убрать `_`).

- [ ] **Step 2: `sql_graph.py` использует llm**

Удалить перенесённое; импорт:

```python
from toast.llm import generate_candidates, judge_verdict, parse_sql_candidates
```

В узлах: `_generate_candidates(` → `generate_candidates(`,
`_judge_verdict(` → `judge_verdict(`.

- [ ] **Step 3: Тесты**

`test_sql_graph.py`: `from toast.sql_graph import parse_sql_candidates` →
`from toast.llm import parse_sql_candidates` (внутри
`test_parse_candidates_multiline_sql_fallback`).

Run: `cd backend && uv run pytest tests/ -q && uv run ruff check .` → `91 passed`.

- [ ] **Step 4: Commit**

```bash
cd backend
git add toast/llm.py toast/sql_graph.py tests/test_sql_graph.py
git commit -m "refactor(toast): llm module isolates structured-output fallbacks"
```

---

### Task 4: `SqlToolNodes` — узлы из замыканий в класс

**Files:**
- Modify: `backend/toast/sql_graph.py` (финальный вид файла целиком)

**Interfaces:**
- Consumes: `toast.models`, `toast.prompts`, `toast.llm` (Task 1–3).
- Produces: класс `SqlToolNodes(model, executor, max_queries, candidates_per_round)` с методами-узлами; `build_sql_graph(...)` — сигнатура и поведение прежние.

- [ ] **Step 1: Переписать `backend/toast/sql_graph.py` целиком**

```python
"""SQL-инструмент как langgraph-граф над ОДНОЙ toast-таблицей.

Топология графа:

    START → sample → generate → execute(∥) → judge → summarize → END

    с тремя условными переходами:
      generate → summarize   если модель не дала ни одного кандидата
      execute  → summarize   если бюджет ИЛИ предел раундов исчерпан (минуя судью)
      judge    → generate    если строк недостаточно (ещё раунд)

Состояние — pydantic-модель с дефолтами (toast/models.py), промпты — в
toast/prompts.py, LLM-обвязка с фолбэками — в toast/llm.py. Здесь — только
узлы и топология. Обоснования решений: docs/sql-tool.md.
"""

import asyncio
import logging
from typing import Any

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from toast.llm import generate_candidates, judge_verdict
from toast.models import (
    DbError, Refusal, SqlToolInput, SqlToolState, Status, Verdict,
    make_attempt, ok_rows,
)
from toast.prompts import (
    GENERATE_SYS, JUDGE_SYS, NO_CANDIDATES_MSG, NO_DATA_MSG, SAMPLE_LIMIT,
    SUMMARIZE_SYS, generate_prompt, rows_context,
)

logger = logging.getLogger(__name__)


class SqlToolNodes:
    """Узлы и роутеры графа; зависимости — в конструкторе.

    LLM зовут только generate/judge/summarize; дисциплина шагов, бюджет и
    предел раундов зашиты в код и не зависят от качества модели.
    """

    def __init__(self, model: BaseChatModel, executor: Any,
                 max_queries: int, candidates_per_round: int) -> None:
        self.model = model
        self.executor = executor
        self.max_queries = max_queries
        self.candidates_per_round = candidates_per_round

    async def sample(self, state: SqlToolState) -> dict:
        """Детерминированные примеры строк — ВНЕ бюджета.

        Модель видит реальные имена колонок и формат значений до генерации;
        рассинхрон desc_full со схемой всплывает здесь, а не тратой бюджета.
        Сбой не фатален: пустые примеры + warning, граф продолжает.
        """
        sql = f"SELECT * FROM {state.table} LIMIT {SAMPLE_LIMIT}"
        try:
            res = await self.executor.run_select(sql, state.table)
        except Exception:
            logger.warning("sample query failed for %s", state.table,
                           exc_info=True)
            return {"sample_rows": []}
        if isinstance(res, (Refusal, DbError)):
            reason = res.reason if isinstance(res, Refusal) else res.message
            logger.warning("sample refused: %s", reason)
            return {"sample_rows": []}
        return {"sample_rows": res["rows"]}

    async def generate(self, state: SqlToolState) -> dict:
        """LLM выдаёт батч SQL-кандидатов под остаток бюджета и фидбек
        прошлых раундов (ошибки, пустые запросы, причина судьи, примеры)."""
        remaining = self.max_queries - state.executed_count
        # remaining >= 1 гарантируется маршрутизацией; max(1, …) — страховка.
        n = max(1, min(self.candidates_per_round, remaining))
        candidates = await generate_candidates(
            self.model,
            [SystemMessage(GENERATE_SYS), HumanMessage(generate_prompt(state, n))],
            n,
        )
        return {"candidates": candidates, "round": state.round + 1}

    async def execute(self, state: SqlToolState) -> dict:
        """Гоняет кандидатов раунда параллельно; копит попытки и счётчик.

        Дубликаты уже выполнявшихся SQL повторно не гоняются и бюджет не
        двигают; завершаемость держит предел раундов в after_execute.
        return_exceptions: сбой одного кандидата не роняет остальных.
        """
        tried = {a["sql"] for a in state.attempts}
        unique = [s for s in dict.fromkeys(state.candidates) if s not in tried]
        results = await asyncio.gather(
            *(self.executor.run_select(sql, state.table) for sql in unique),
            return_exceptions=True,
        )
        new = [make_attempt(sql, res) for sql, res in zip(unique, results)]
        # Бюджет — только SQL, дошедшие до БД: Refusal guardrails существует,
        # чтобы модель ПЕРЕПИСАЛА запрос, и не должен съедать попытку.
        executed = sum(1 for r in results if not isinstance(r, Refusal))
        return {
            "attempts": state.attempts + new,
            "executed_count": state.executed_count + executed,
        }

    async def judge(self, state: SqlToolState) -> dict:
        """LLM: достаточно ли строк. Без строк — need_more без вызова."""
        if not ok_rows(state.attempts):
            return {"verdict": Verdict.NEED_MORE}
        verdict = await judge_verdict(
            self.model,
            [
                SystemMessage(JUDGE_SYS),
                HumanMessage(f"Вопрос: {state.question}\n"
                             + rows_context(state.attempts)),
            ],
        )
        return {
            "verdict": Verdict.SUFFICIENT if verdict.sufficient
            else Verdict.NEED_MORE,
            "judge_reason": verdict.reason,
        }

    async def summarize(self, state: SqlToolState) -> dict:
        """Терминальный узел: ответ по строкам, либо статус no_data / error."""
        rows = ok_rows(state.attempts)
        if not rows:
            if not state.attempts:
                # Сюда попадаем только из after_generate при пустом батче.
                return {"status": Status.ERROR,
                        "answer": f"Не удалось выполнить SQL: {NO_CANDIDATES_MSG}"}
            # Хоть один успешный (но пустой) SELECT → данных нет; иначе все
            # попытки — ошибки БД → техническая ошибка.
            if any(a["ok"] for a in state.attempts):
                return {"status": Status.NO_DATA, "answer": NO_DATA_MSG}
            last = next(
                (a["error"] for a in reversed(state.attempts) if a["error"]),
                "неизвестная ошибка",
            )
            return {"status": Status.ERROR,
                    "answer": f"Не удалось выполнить SQL: {last}"}
        reply = await self.model.ainvoke(
            [
                SystemMessage(SUMMARIZE_SYS),
                HumanMessage(f"Вопрос: {state.question}\n"
                             + rows_context(state.attempts)),
            ]
        )
        return {"status": Status.OK, "answer": str(reply.content)}

    def after_generate(self, state: SqlToolState) -> str:
        """Пустой батч кандидатов → summarize (иначе цикл без прогресса)."""
        return "execute" if state.candidates else "summarize"

    def after_execute(self, state: SqlToolState) -> str:
        """Бюджет или предел раундов исчерпан → summarize; иначе judge.

        Предел раундов — страховка завершаемости: батчи из дубликатов или
        отказов guardrails бюджет не двигают.
        """
        if (state.executed_count >= self.max_queries
                or state.round >= self.max_queries):
            return "summarize"
        return "judge"

    def after_judge(self, state: SqlToolState) -> str:
        """Судья доволен → summarize; иначе → ещё раунд generate."""
        return ("summarize" if state.verdict == Verdict.SUFFICIENT
                else "generate")


def build_sql_graph(
    model: BaseChatModel,
    executor: Any,
    max_queries: int,
    candidates_per_round: int,
) -> CompiledStateGraph:
    """Собирает и компилирует граф SQL-инструмента.

    executor — объект с async `run_select(sql, table) ->
    SelectResult | Refusal | DbError`. Сигнатура стабильна (Studio, демо).
    """
    nodes = SqlToolNodes(model, executor, max_queries, candidates_per_round)
    g = StateGraph(SqlToolState, input_schema=SqlToolInput)
    g.add_node("sample", nodes.sample)
    g.add_node("generate", nodes.generate)
    g.add_node("execute", nodes.execute)
    g.add_node("judge", nodes.judge)
    g.add_node("summarize", nodes.summarize)
    g.add_edge(START, "sample")
    g.add_edge("sample", "generate")
    g.add_conditional_edges("generate", nodes.after_generate,
                            ["execute", "summarize"])
    g.add_conditional_edges("execute", nodes.after_execute,
                            ["judge", "summarize"])
    g.add_conditional_edges("judge", nodes.after_judge,
                            ["generate", "summarize"])
    g.add_edge("summarize", END)
    return g.compile()
```

- [ ] **Step 2: Прогнать всё**

Run: `cd backend && uv run pytest tests/ -q && uv run ruff check .` → `91 passed`.
Run: `cd ../studio && uv run pytest -q` → `2 passed`.

- [ ] **Step 3: Commit**

```bash
cd backend
git add toast/sql_graph.py
git commit -m "refactor(toast): nodes as class, build_sql_graph is pure topology"
```

---

### Task 5: Разбиение тестов графа по темам

**Files:**
- Create: `backend/tests/graph_utils.py`, `backend/tests/test_graph_flow.py`, `backend/tests/test_graph_budget.py`, `backend/tests/test_graph_llm.py`, `backend/tests/test_graph_context.py`
- Delete: `backend/tests/test_sql_graph.py`
- Modify: `backend/tests/test_sql_tool.py` (импорт хелперов)

**Interfaces:**
- Produces: `tests/graph_utils.py` c `LEGAL`, `FakeExecutor`, `_rows(n)`, `_sample()`, `_inp()`, `_run(model, executor, **cfg)`, `_ok_attempt(sql, rows)`, `_fail_attempt(...)` — тела БЕЗ изменений переносятся из `test_sql_graph.py`.

- [ ] **Step 1: Создать `graph_utils.py` и четыре файла**

Тесты переносятся БЕЗ изменения тел, только импорты
(`from graph_utils import ...`). Распределение:

- `test_graph_flow.py`: `test_round1_sufficient_ok`, `test_retry_then_sufficient`, `test_candidates_run_in_parallel_batch`, `test_sample_failure_is_not_fatal`, `test_no_candidates_terminates_with_error`, `test_executor_exception_becomes_failed_attempt`, `test_all_sql_errors_status_error`, `test_input_schema_exposes_five_fields`, `test_state_has_defaults_instead_of_init`;
- `test_graph_budget.py`: `test_budget_exhausted_no_data`, `test_duplicate_candidates_stopped_by_round_cap`, `test_guardrails_refusal_does_not_consume_budget`, `test_round_cap_stops_refusal_only_batches`, `test_sample_not_counted_in_budget`;
- `test_graph_llm.py`: `test_structured_output_path_used_when_supported`, `test_judge_reason_feeds_next_generate_prompt`, `test_insufficient_verdict_means_need_more`, `test_parse_candidates_multiline_sql_fallback`, `test_attempt_from_refusal_result_and_exception`;
- `test_graph_context.py`: `test_rows_context_groups_by_attempt`, `test_rows_context_caps_by_size`.

`test_sql_tool.py`: `from test_sql_graph import ...` → `from graph_utils import FakeExecutor, _rows, _sample`.

- [ ] **Step 2: Прогнать всё**

Run: `cd backend && uv run pytest tests/ -q && uv run ruff check .`
Expected: `91 passed` (число тестов то же — только раскладка).

- [ ] **Step 3: Commit**

```bash
cd backend
git add tests/
git commit -m "test(toast): split graph tests by theme; shared fixtures module"
```

---

### Task 6: Документация, merge в demo и backend

**Files:**
- Modify: `docs/sql-tool.md`

- [ ] **Step 1: Правки `docs/sql-tool.md`**

1. Во вводном абзаце: `backend/toast/` расшифровать как «граф
   (`sql_graph.py`), типы (`models.py`), промпты (`prompts.py`),
   LLM-обвязка (`llm.py`), guardrails, исполнитель».
2. Раздел про исполнителя (слой 3 / раздел 7): контракт — «`run_select`
   возвращает `SelectResult | Refusal | DbError`; `Refusal` (отказ
   guardrails) не списывает бюджет, `DbError` — списывает; различение —
   типами, а не строковым префиксом».
3. Раздел 6 (бюджет): упомянуть, что Refusal/DbError — типы из
   `models.py`, подсчёт по `isinstance`.

- [ ] **Step 2: Финальная верификация и push toast-logic**

Run: `cd backend && uv run pytest tests/ -q && uv run ruff check .` → чисто.
Run: `cd ../studio && uv run pytest -q` → `2 passed`.

```bash
git add docs/sql-tool.md
git commit -m "docs: module layout and typed executor contract in SQL tool reference"
git push origin toast-logic
```

- [ ] **Step 3: Merge в `demo/sql-chat`**

```bash
git checkout demo/sql-chat && git merge --no-edit toast-logic
cd backend && uv run pytest tests/ -q   # включая test_sql_demo
cd .. && git push origin demo/sql-chat
```

Ожидаемые точки внимания: `sql_demo.py` импортирует только
`build_sql_graph` (цел); `tests/test_sql_demo.py` самодостаточен.
Если merge затронет `tests/test_sql_graph.py` (удалён у нас, изменён в
demo-истории) — конфликт разрешается удалением файла
(`git rm tests/test_sql_graph.py`), его тесты уже живут в новых файлах.

- [ ] **Step 4: Merge в `backend`**

```bash
git checkout backend && git merge --no-edit toast-logic
cd backend && uv run pytest tests/ -q && uv run ruff check .
cd ../frontend && export PATH="$HOME/.nvm/versions/node/v22.23.1/bin:$PATH" && npm test && npm run build
cd .. && git push origin backend
git checkout toast-logic
```

---

## Final Verification

- [ ] Все три ветки: backend pytest + ruff чисто; studio 2 passed
- [ ] Число тестов не уменьшилось; ассерты поведения не менялись
- [ ] `git diff toast-logic@{до рефакторинга} -- docs/sql-tool.md` — только имена файлов и контракт исполнителя
- [ ] Ветки запушены
