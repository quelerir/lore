# LangGraph Studio-раннер SQL-инструмента Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Запускать SQL-граф против живой `loreagent_test` и видеть ход выполнения в LangGraph Studio (`langgraph dev`).

**Architecture:** Отдельный опциональный uv-проект `studio/` вне `backend/`; фабрика графа `studio/graph.py` собирает `PgExecutor` + `ChatOpenAI` + `build_sql_graph` из env (Toast-DSN через `config.build_dsn`) и экспортирует переменную `graph`; `langgraph.json` указывает Studio на неё. Входная схема `SqlToolInput` даёт чистую форму ввода.

**Tech Stack:** Python 3.13, uv, langgraph, langgraph-cli[inmem], langchain-openai, asyncpg, pydantic-settings, pytest.

**Spec:** `docs/superpowers/specs/2026-07-16-sql-tool-studio-design.md`

## Global Constraints

- Backend-код меняется в `backend/`, раннер живёт в отдельной top-level `studio/` (свой uv-проект). НЕ в `backend/`.
- Backend НЕ делаем pip-пакетом — `studio/graph.py` импортирует его через `sys.path` (как `infra/eval-sql.py`).
- Фабрика читает env НАПРЯМУЮ (не `get_settings()`), Toast-DSN собирает `config.build_dsn("postgresql", …)`. Обязательны: `OPENROUTER_API_KEY`, компоненты `TOAST_DB_*`. Отсутствие → `RuntimeError`.
- Дефолты: `OPENROUTER_BASE_URL=https://openrouter.ai/api/v1`, `SQL_MODEL=anthropic/claude-sonnet-4.6`, `SQL_MAX_QUERIES=3`, `SQL_CANDIDATES_PER_ROUND=2`, `TOAST_DB_PORT=5432`.
- Входная схема: `SqlToolInput` из 5 полей (`question`, `chunk_id`, `table`, `desc_vector`, `desc_full`); `StateGraph(SqlToolState, input_schema=SqlToolInput)` (параметр именно `input_schema`).
- Backend-тесты (`cd backend && uv run pytest`) остаются зелёными. Studio-тест — в venv studio (`cd studio && uv run pytest`).
- Фикстуры для ручной проверки: юристы `toast_tbl_ec48a6d52d16ab405f95`, грейды `toast_tbl_17a7241d0a976f287103`.

---

### Task 1: Входная схема SqlToolInput в графе

Ограничивает форму ввода Studio нужными полями, не трогая выход.

**Files:**
- Modify: `backend/toast/sql_graph.py`
- Test: `backend/tests/test_sql_graph.py`

**Interfaces:**
- Produces: `SqlToolInput` (TypedDict с полями `question`, `chunk_id`, `table`, `desc_vector`, `desc_full`); `build_sql_graph` строит `StateGraph(SqlToolState, input_schema=SqlToolInput)`.

- [ ] **Step 1: Тест на входную схему**

В `backend/tests/test_sql_graph.py` добавить тест, что схема ввода описана
и граф по-прежнему возвращает полное состояние:

```python
def test_input_schema_exposes_five_fields():
    from toast.sql_graph import SqlToolInput

    keys = set(SqlToolInput.__annotations__)
    assert keys == {"question", "chunk_id", "table", "desc_vector", "desc_full"}
```

- [ ] **Step 2: Запустить — падает**

Run: `cd backend && uv run pytest tests/test_sql_graph.py::test_input_schema_exposes_five_fields -v`
Expected: FAIL — `ImportError: cannot import name 'SqlToolInput'`.

- [ ] **Step 3: Добавить схему и передать в StateGraph**

В `backend/toast/sql_graph.py` после класса `SqlToolState` добавить:

```python
class SqlToolInput(TypedDict):
    """Входные поля инструмента (форма ввода в Studio)."""

    question: str
    chunk_id: str
    table: str
    desc_vector: str
    desc_full: str
```

В `build_sql_graph` заменить строку `g = StateGraph(SqlToolState)` на:

```python
    g = StateGraph(SqlToolState, input_schema=SqlToolInput)
```

- [ ] **Step 4: Прогнать тесты графа**

Run: `cd backend && uv run pytest tests/test_sql_graph.py tests/test_sql_tool.py -v`
Expected: PASS (входная схема обратно совместима — узлы читают те же поля,
`ainvoke` возвращает полное состояние).

Run: `cd backend && uv run pytest`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
cd /Users/stamplevskiyd/development/lore
git add backend/toast/sql_graph.py backend/tests/test_sql_graph.py
git commit -m "feat(toast): SqlToolInput schema for clean Studio input form"
```

---

### Task 2: Директория studio/ — uv-проект и фабрика графа

**Files:**
- Create: `studio/pyproject.toml`
- Create: `studio/graph.py`
- Create: `studio/langgraph.json`
- Create: `studio/.gitignore`
- Create: `studio/.env.example`
- Create: `studio/test_graph_smoke.py`

**Interfaces:**
- Consumes: `backend/config.build_dsn`, `backend/toast/executor.PgExecutor`, `backend/toast/sql_graph.build_sql_graph`.
- Produces: `studio/graph.py` с модульной переменной `graph` (CompiledStateGraph); фабрика `_build_studio_graph()`.

- [ ] **Step 1: uv-проект studio**

Создать `studio/pyproject.toml`:

```toml
[project]
name = "lore-studio"
version = "0.1.0"
description = "LangGraph Studio runner for the SQL tool (dev-only, optional)"
requires-python = ">=3.13"
dependencies = [
    "langgraph-cli[inmem]",
    "langgraph",
    "langchain-openai",
    "langchain-core",
    "asyncpg",
    "pydantic-settings",
]

[tool.pytest.ini_options]
testpaths = ["."]
```

- [ ] **Step 2: Фабрика графа**

Создать `studio/graph.py`:

```python
"""Фабрика SQL-графа для LangGraph Studio (dev-only).

Backend не установлен пакетом — подключаем по sys.path. Креды и настройки
читаются из окружения (langgraph.json грузит studio/.env), Toast-DSN собирается
через config.build_dsn. Экспортирует переменную `graph` для langgraph.json.
"""

import os
import sys

_BACKEND = os.path.join(os.path.dirname(__file__), "..", "backend")
if _BACKEND not in sys.path:
    sys.path.insert(0, _BACKEND)

from langchain_openai import ChatOpenAI  # noqa: E402

from config import build_dsn  # noqa: E402
from toast.executor import PgExecutor  # noqa: E402
from toast.sql_graph import build_sql_graph  # noqa: E402


def _require(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"Studio: переменная окружения {name} обязательна")
    return value


def _toast_dsn() -> str:
    host = _require("TOAST_DB_HOST")
    user = _require("TOAST_DB_USER")
    password = _require("TOAST_DB_PASSWORD")
    name = _require("TOAST_DB_NAME")
    port = int(os.environ.get("TOAST_DB_PORT", "5432"))
    return build_dsn("postgresql", user, password, host, port, name)


def _build_studio_graph():
    api_key = _require("OPENROUTER_API_KEY")
    model = ChatOpenAI(
        model=os.environ.get("SQL_MODEL", "anthropic/claude-sonnet-4.6"),
        base_url=os.environ.get(
            "OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1"
        ),
        api_key=api_key,
    )
    executor = PgExecutor(_toast_dsn())
    return build_sql_graph(
        model,
        executor,
        max_queries=int(os.environ.get("SQL_MAX_QUERIES", "3")),
        candidates_per_round=int(os.environ.get("SQL_CANDIDATES_PER_ROUND", "2")),
    )


graph = _build_studio_graph()
```

- [ ] **Step 3: langgraph.json**

Создать `studio/langgraph.json`:

```json
{
  "dependencies": ["."],
  "graphs": { "sql_tool": "./graph.py:graph" },
  "env": ".env"
}
```

- [ ] **Step 4: .gitignore и .env.example**

Создать `studio/.gitignore`:

```gitignore
.env
.venv
```

Создать `studio/.env.example`:

```dotenv
# Скопируй в studio/.env и заполни. Файл .env в git не попадает.
OPENROUTER_API_KEY=
# SQL_MODEL=anthropic/claude-sonnet-4.6

# Toast БД (loreagent_test), read-only:
TOAST_DB_HOST=
TOAST_DB_PORT=5432
TOAST_DB_USER=
TOAST_DB_PASSWORD=
TOAST_DB_NAME=
```

- [ ] **Step 5: Smoke-тест фабрики**

Создать `studio/test_graph_smoke.py`:

```python
import importlib
import sys

import pytest

ENV = {
    "OPENROUTER_API_KEY": "k",
    "TOAST_DB_HOST": "localhost",
    "TOAST_DB_USER": "u",
    "TOAST_DB_PASSWORD": "p",
    "TOAST_DB_NAME": "db",
}


def _reload_graph(monkeypatch, env):
    for k in ("OPENROUTER_API_KEY", "TOAST_DB_HOST", "TOAST_DB_USER",
              "TOAST_DB_PASSWORD", "TOAST_DB_NAME", "TOAST_DB_PORT"):
        monkeypatch.delenv(k, raising=False)
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    sys.modules.pop("graph", None)
    return importlib.import_module("graph")


def test_graph_compiles_with_env(monkeypatch):
    mod = _reload_graph(monkeypatch, ENV)
    # graph скомпилирован без I/O (пул asyncpg ленивый)
    assert mod.graph is not None
    assert hasattr(mod.graph, "ainvoke")


def test_missing_env_raises(monkeypatch):
    with pytest.raises(RuntimeError):
        _reload_graph(monkeypatch, {"OPENROUTER_API_KEY": "k"})  # нет TOAST_DB_*
```

- [ ] **Step 6: Прогнать smoke-тест в venv studio**

Run: `cd studio && uv run pytest -v`
Expected: PASS (2 теста). Первый импорт создаст `studio/.venv` и установит
зависимости (langgraph, langchain-openai, asyncpg, pydantic-settings).

- [ ] **Step 7: Проверить backend не сломан**

Run: `cd backend && uv run pytest`
Expected: PASS (Task 1 не тронул поведение).

- [ ] **Step 8: Commit**

```bash
cd /Users/stamplevskiyd/development/lore
git add studio/pyproject.toml studio/graph.py studio/langgraph.json \
        studio/.gitignore studio/.env.example studio/test_graph_smoke.py studio/uv.lock
git commit -m "feat(studio): LangGraph Studio runner project for the SQL tool"
```

---

### Task 3: README запуска

**Files:**
- Create: `studio/README.md`

**Interfaces:** —

- [ ] **Step 1: Инструкция запуска**

Создать `studio/README.md`:

```markdown
# LangGraph Studio-раннер SQL-инструмента

Опциональный dev-инструмент: запускает SQL-граф (`backend/toast/sql_graph.py`)
против живой `loreagent_test` и показывает ход выполнения в LangGraph Studio.

## Запуск

1. Скопируй креды: `cp .env.example .env` и заполни `OPENROUTER_API_KEY` и
   компоненты `TOAST_DB_*`.
2. Подними сервер и Studio:

   ```bash
   cd studio
   uv run langgraph dev
   ```

   Откроется Studio (нужен бесплатный вход в LangSmith; граф и БД остаются
   локально). Сервер графа — на `http://127.0.0.1:2024`.

3. В форме ввода графа `sql_tool` заполни поля и запусти. Видно подсветку
   узлов scope→generate→execute→judge→summarize и состояние на каждом шаге.

## Готовые входы (из отчёта)

Юристы:
- `question`: Какие ФИО у юристов и их должности?
- `chunk_id`: `e6d9b7ff6df20d08b9c1c543760530ce`
- `table`: `toast_tbl_ec48a6d52d16ab405f95`
- `desc_vector`: юристы Adventum, ФИО и должности
- `desc_full`: Table payload: Лист1 A15:R16. Реестр юристов: ФИО, должность, email.

Грейды:
- `question`: Какие компетенции базовой матрицы отдела контекстной рекламы?
- `chunk_id`: `grade-base`
- `table`: `toast_tbl_17a7241d0a976f287103`
- `desc_vector`: грейды контекстной рекламы, компетенции
- `desc_full`: Table payload: Junior-Group head. Базовая матрица компетенций.

## Тест

```bash
cd studio && uv run pytest
```
```

- [ ] **Step 2: Commit**

```bash
cd /Users/stamplevskiyd/development/lore
git add studio/README.md
git commit -m "docs(studio): how to run the SQL tool in LangGraph Studio"
```

---

## Верификация плана целиком

1. `cd backend && uv run pytest` — backend зелёный (входная схема совместима).
2. `cd studio && uv run pytest` — smoke-тесты фабрики зелёные.
3. С кредами в `studio/.env`: `cd studio && uv run langgraph dev` поднимает
   Studio; прогон фикстуры юристов даёт путь scope→…→summarize и `answer`
   с «Каневский».
4. `git status` — `studio/.env` не отслеживается (в `.gitignore`).
