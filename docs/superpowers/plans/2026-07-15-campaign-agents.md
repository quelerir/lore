# Campaign-Files Agents (Fast/Deep) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Два режима агента над TOAST-слоем документов: быстрый (langgraph, фиксированный маршрут discover→plan_sql→execute→answer) и умный (deepagents с инструментами), с синтетическим Postgres-слепком схемы и eval-скриптом по кейсам отчёта.

**Architecture:** Порт `ToastStorePort` прячет «специальный интерфейс»; прототипный адаптер `PgToastStore` (asyncpg, read-only, guardrails из контракта отчёта) ходит во вторую БД `lore_data` инстанса `chainlit-db`. Оба агента получают доступ только через порт. Режим выбирается Chainlit chat profiles; фронтенд шлёт `setChatProfile` перед connect.

**Tech Stack:** langgraph (уже в venv транзитивно, фиксируем явно), deepagents, asyncpg, chainlit 2.11.1 chat profiles, react-client `setChatProfile`.

**Спека:** `docs/superpowers/specs/2026-07-15-campaign-agents-design.md`. Референс-контракт: `problem-questions-report.html` (корень репо, НЕ коммитить — содержит реальные ПД).

## Global Constraints

- Ветка `campaign-agents` (от `authentik-sso`).
- Синтетические данные — только вымышленные ФИО/значения; реальные имена из отчёта в репо не попадают. Eval-ассерты — на синтетику.
- Guardrails SQL — дословно из контракта: только SELECT, allowlist схем `lore_core|splitter_toast|information_schema`, table id `^toast_tbl_[0-9a-f]{20}$`, policy gate до SQL для PII, no-table-answer вместо выдумки.
- `handle_message` в app.py не меняется (оба режима — `CompiledStateGraph`, `stream_mode="messages"`).
- Тесты бэкенда: `docker run --rm -v "$PWD/backend:/app" -w /app lore-backend sh -c "uv pip install -q pytest && pytest -q"`. Интеграционные тесты БД помечаются skipif без `TOAST_DATABASE_URL`.
- Фронтенд-сборка: `docker compose build frontend`. UI-копия на русском.
- Проверки с LLM — против живого стека + Ollama (`OLLAMA_MODEL` из `.env`, сейчас gemma4).
- Chainlit 2.11.1: `cl.ChatProfile(name, markdown_description, display_name, default)` — проверено по исходникам. `create_deep_agent(model=..., tools=...)` — проверено.

## File Structure

| Файл | Судьба | Ответственность |
|---|---|---|
| `backend/init/10-toast-demo.sh` | create | создать БД `lore_data`, применить SQL (идемпотентно) |
| `backend/init/toast-demo.sql` | create | схемы lore_core/splitter_toast + синтетика 4 кейсов |
| `docker-compose.yml` | modify | mount обоих init-файлов, env `TOAST_DATABASE_URL` |
| `backend/toast/__init__.py` | create | реэкспорт порта/адаптера |
| `backend/toast/port.py` | create | Protocol + типы DiscoveredTable/TableInfo/SelectResult |
| `backend/toast/policy.py` | create | PII-список + `check_policy(sql) -> str | None` |
| `backend/toast/guardrails.py` | create | `validate_select(sql) -> str | None` (чистая функция) |
| `backend/toast/pg.py` | create | `PgToastStore` (asyncpg, discover/inspect/run_select) |
| `backend/toast/tools.py` | create | `make_tools(store) -> list[BaseTool]` (для deep) |
| `backend/agents/{__init__,base,fast,deep}.py` | create | Mode, промпты, оба графа |
| `backend/agent.py` | delete | уезжает в agents/ |
| `backend/app.py` | modify | chat profiles, диспетчер режима, store |
| `backend/pyproject.toml` | modify | packages agents+toast, явный langgraph |
| `backend/tests/{test_guardrails,test_toast_store,test_agents}.py` | create | юниты/интеграция |
| `backend/tests/test_agent.py` | delete | заменён test_agents.py |
| `frontend/src/components/Sidebar/*` | modify | сегмент «Быстрый \| Умный» |
| `frontend/src/App.tsx`, `frontend/src/chat/ChainlitRuntimeProvider.tsx` | modify | проброс chatProfile |
| `infra/eval-agents.py` | create | eval 4 кейсов × 2 режима |
| `infra/e2e-chat.py` | modify | параметр профиля |
| `README.md`, `docs/usage.md` | modify | режимы, демо-данные |

---

### Task 1: Демо-БД TOAST-слоя

**Files:**
- Create: `backend/init/10-toast-demo.sh`, `backend/init/toast-demo.sql`
- Modify: `docker-compose.yml` (volumes `chainlit-db`; env `TOAST_DATABASE_URL` у backend)

**Interfaces:**
- Produces: БД `lore_data` (user chainlit) со схемами `lore_core` (processed_files, payloads, chunks) и `splitter_toast` (5 таблиц `toast_tbl_<20hex>`); DSN `postgresql://chainlit:chainlit@chainlit-db:5432/lore_data` в env `TOAST_DATABASE_URL`.

- [ ] **Step 1: `backend/init/toast-demo.sql`** (идемпотентный, выполняется в БД lore_data)

Синтетика (вымышленные имена!). Table id фиксированные:
`…a1b2c3d4e5f6a7b8c9d0` база компетенций, `…b1…` Middle, `…c1…` Group Head,
`…d1…` Legal, `…e1…` отпуска (PII).

```sql
DROP SCHEMA IF EXISTS lore_core CASCADE;
DROP SCHEMA IF EXISTS splitter_toast CASCADE;
CREATE SCHEMA lore_core;
CREATE SCHEMA splitter_toast;

CREATE TABLE lore_core.processed_files (
    logical_file_key text PRIMARY KEY,
    source_path      text NOT NULL
);

CREATE TABLE lore_core.payloads (
    payload_id       text PRIMARY KEY,
    logical_file_key text REFERENCES lore_core.processed_files,
    kind             text NOT NULL,
    coordinates      jsonb,
    toast_schema     text,   -- в проде пусто: воспроизводим
    toast_table      text,   -- в проде пусто: воспроизводим
    storage_uri      text
);

CREATE TABLE lore_core.chunks (
    chunk_id     text PRIMARY KEY,
    display_text text,
    payload_refs jsonb
);

-- Файл 1: функционал отдела контекстной рекламы (кейс toast-grade-001)
INSERT INTO lore_core.processed_files VALUES
 ('file-context-dept', 'functional/Отдел контекстной рекламы__demo.xlsx'),
 ('file-roster',       'hr/Список сотрудников - demo.xlsx'),
 ('file-vacations',    'hr/График отпусков 2026 - demo.xlsx');

CREATE TABLE splitter_toast.toast_tbl_a1b2c3d4e5f6a7b8c9d0 (
    _splitter_source_row int,
    column_1 text,  -- группа компетенций
    column_2 text   -- компетенция
);
INSERT INTO splitter_toast.toast_tbl_a1b2c3d4e5f6a7b8c9d0 VALUES
 (1,'Работа с кампаниями','Выполнение KPI'),
 (2,'Работа с кампаниями','Отчетность'),
 (3,'Работа с кампаниями','Оптимизация ставок'),
 (4,'Аналитика','Конкурентный анализ'),
 (5,'Аналитика','Google Таблицы и Excel'),
 (6,'Команда','Менторство и координация'),
 (7,'Команда','Ведение разных ниш');

CREATE TABLE splitter_toast.toast_tbl_b1b2c3d4e5f6a7b8c9d0 (
    _splitter_source_row int,
    middle_lvl_1   text,   -- самостоятельность middle
    middle_lvl_1_2 text    -- качество middle
);
INSERT INTO splitter_toast.toast_tbl_b1b2c3d4e5f6a7b8c9d0 VALUES
 (1,'4','высокий'),(2,'3','стандартный'),(3,'4','высокий'),
 (4,NULL,NULL),(5,'3','стандартный'),(6,NULL,NULL),(7,NULL,NULL);

CREATE TABLE splitter_toast.toast_tbl_c1b2c3d4e5f6a7b8c9d0 (
    _splitter_source_row int,
    group_head   text,     -- самостоятельность group head
    group_head_2 text      -- качество group head
);
INSERT INTO splitter_toast.toast_tbl_c1b2c3d4e5f6a7b8c9d0 VALUES
 (1,'5','исключительно высокий'),(2,'5','исключительно высокий'),
 (3,'5','исключительно высокий'),(4,'5','исключительно высокий'),
 (5,'5','исключительно высокий'),(6,'5','исключительно высокий'),
 (7,'5','исключительно высокий');

-- Файл 2: реестр сотрудников — блок Legal (кейс toast-legal-001).
-- Header-as-data: первая запись блока живёт ТОЛЬКО в chunks.display_text.
CREATE TABLE splitter_toast.toast_tbl_d1b2c3d4e5f6a7b8c9d0 (
    _splitter_source_row int,
    column_1 text,              -- ФИО
    column_2 text,              -- должность ru
    senior_legal_manager text   -- должность en (имя колонки = header-дефект)
);
INSERT INTO splitter_toast.toast_tbl_d1b2c3d4e5f6a7b8c9d0 VALUES
 (16,'Смирнов Пётр Ильич','помощник юриста','Assistant Legal Manager');

-- Файл 3: график отпусков (PII, кейс toast-privacy-001)
CREATE TABLE splitter_toast.toast_tbl_e1b2c3d4e5f6a7b8c9d0 (
    _splitter_source_row int,
    column_1 text,   -- ФИО
    column_2 text,   -- отдел
    vacation_start date,
    vacation_end   date
);
INSERT INTO splitter_toast.toast_tbl_e1b2c3d4e5f6a7b8c9d0 VALUES
 (37,'Орлова Мария Сергеевна','Paid Search','2026-08-03','2026-08-16');

INSERT INTO lore_core.payloads VALUES
 ('toast_tbl_a1b2c3d4e5f6a7b8c9d0','file-context-dept','table','{"range":"A1:B8"}',NULL,NULL,'toast://a1'),
 ('toast_tbl_b1b2c3d4e5f6a7b8c9d0','file-context-dept','table','{"range":"C1:D8"}',NULL,NULL,'toast://b1'),
 ('toast_tbl_c1b2c3d4e5f6a7b8c9d0','file-context-dept','table','{"range":"E1:F8"}',NULL,NULL,'toast://c1'),
 ('toast_tbl_d1b2c3d4e5f6a7b8c9d0','file-roster','table','{"range":"A15:R16"}',NULL,NULL,'toast://d1'),
 ('toast_tbl_e1b2c3d4e5f6a7b8c9d0','file-vacations','table','{"range":"A37:R37"}',NULL,NULL,'toast://e1');

INSERT INTO lore_core.chunks VALUES
 ('chunk-grades','Матрица компетенций отдела контекстной рекламы: база + уровни Middle и Group Head, соединяются по _splitter_source_row',
  '["toast_tbl_a1b2c3d4e5f6a7b8c9d0","toast_tbl_b1b2c3d4e5f6a7b8c9d0","toast_tbl_c1b2c3d4e5f6a7b8c9d0"]'),
 ('chunk-legal','Columns: Ковалева Ирина Викторовна | ведущий юрисконсульт | Senior Legal Manager. Блок Legal реестра сотрудников',
  '["toast_tbl_d1b2c3d4e5f6a7b8c9d0"]'),
 ('chunk-vacations','График отпусков 2026, персональные даты сотрудников',
  '["toast_tbl_e1b2c3d4e5f6a7b8c9d0"]');
```

- [ ] **Step 2: `backend/init/10-toast-demo.sh`**

```bash
#!/bin/bash
# Создаёт демо-БД lore_data (TOAST-слепок) и наполняет её.
# Идемпотентен: можно запускать и при initdb, и вручную на живой БД.
set -euo pipefail

PGUSER="${POSTGRES_USER:-chainlit}"

psql -v ON_ERROR_STOP=1 -U "$PGUSER" -d postgres \
  -tc "SELECT 1 FROM pg_database WHERE datname = 'lore_data'" | grep -q 1 \
  || psql -v ON_ERROR_STOP=1 -U "$PGUSER" -d postgres -c "CREATE DATABASE lore_data"

psql -v ON_ERROR_STOP=1 -U "$PGUSER" -d lore_data \
  -f /docker-entrypoint-initdb.d/toast-demo.sql
echo "toast demo data ready"
```

- [ ] **Step 3: compose** — в `chainlit-db.volumes` добавить:

```yaml
      - ./backend/init/10-toast-demo.sh:/docker-entrypoint-initdb.d/10-toast-demo.sh:ro
      - ./backend/init/toast-demo.sql:/docker-entrypoint-initdb.d/toast-demo.sql:ro
```

В `backend.environment` добавить:

```yaml
      TOAST_DATABASE_URL: postgresql://chainlit:chainlit@chainlit-db:5432/lore_data
```

- [ ] **Step 4: применить к живому тому** (initdb-скрипты выполняются только на пустом томе):

Run: `chmod +x backend/init/10-toast-demo.sh && docker compose up -d chainlit-db && docker compose exec chainlit-db bash /docker-entrypoint-initdb.d/10-toast-demo.sh`
Expected: `toast demo data ready`.

- [ ] **Step 5: проверить данные**

Run: `docker compose exec chainlit-db psql -U chainlit -d lore_data -c "SELECT count(*) FROM lore_core.payloads" -c "SELECT count(*) FROM splitter_toast.toast_tbl_a1b2c3d4e5f6a7b8c9d0"`
Expected: 5 и 7.

- [ ] **Step 6: Commit** — `git add backend/init docker-compose.yml && git commit -m "feat: synthetic TOAST-layer demo database (lore_data)"`

---

### Task 2: Guardrails и policy (TDD, чистые функции)

**Files:**
- Create: `backend/toast/__init__.py`, `backend/toast/guardrails.py`, `backend/toast/policy.py`
- Test: `backend/tests/test_guardrails.py`
- Modify: `backend/pyproject.toml`

**Interfaces:**
- Produces:
  - `validate_select(sql: str) -> str | None` — None если можно выполнять, иначе текст отказа;
  - `check_policy(sql: str) -> str | None` — None либо отказ policy gate;
  - `PII_TABLES: frozenset[str]` (id таблицы отпусков).

- [ ] **Step 1: тест `backend/tests/test_guardrails.py`**

```python
import pytest
from toast.guardrails import validate_select
from toast.policy import check_policy

OK = "SELECT column_1 FROM splitter_toast.toast_tbl_a1b2c3d4e5f6a7b8c9d0 LIMIT 5"


def test_valid_select_passes():
    assert validate_select(OK) is None


def test_join_and_registry_pass():
    sql = """SELECT b.column_2, m.middle_lvl_1
    FROM splitter_toast.toast_tbl_a1b2c3d4e5f6a7b8c9d0 b
    LEFT JOIN splitter_toast.toast_tbl_b1b2c3d4e5f6a7b8c9d0 m USING (_splitter_source_row)"""
    assert validate_select(sql) is None
    assert validate_select("SELECT payload_id FROM lore_core.payloads WHERE kind='table'") is None


@pytest.mark.parametrize("bad", [
    "DROP TABLE lore_core.payloads",
    "DELETE FROM lore_core.chunks",
    "INSERT INTO lore_core.chunks VALUES ('x','y','[]')",
    "UPDATE lore_core.payloads SET kind='x'",
    "COPY lore_core.chunks TO '/tmp/x'",
    "SELECT 1; DROP TABLE lore_core.payloads",
])
def test_mutations_rejected(bad):
    assert validate_select(bad) is not None


def test_foreign_schema_rejected():
    assert validate_select("SELECT * FROM public.users") is not None
    assert validate_select("SELECT * FROM pg_catalog.pg_tables") is not None


def test_bad_table_id_rejected():
    assert validate_select("SELECT * FROM splitter_toast.evil_table") is not None
    assert validate_select("SELECT * FROM splitter_toast.toast_tbl_zzzz") is not None


def test_pii_table_gated():
    sql = "SELECT vacation_start FROM splitter_toast.toast_tbl_e1b2c3d4e5f6a7b8c9d0"
    assert check_policy(sql) is not None
    assert check_policy(OK) is None
```

- [ ] **Step 2: убедиться, что падает** — команда тестов из Global Constraints, Expected: `ModuleNotFoundError: toast`.

- [ ] **Step 3: реализация `backend/toast/guardrails.py`**

```python
"""SQL-guardrails по контракту problem-questions-report.html."""

import re

ALLOWED_SCHEMAS = frozenset({"lore_core", "splitter_toast", "information_schema"})
TOAST_TABLE_RE = re.compile(r"^toast_tbl_[0-9a-f]{20}$")
_FORBIDDEN = re.compile(
    r"\b(insert|update|delete|drop|alter|create|truncate|grant|revoke|copy|vacuum|call|do)\b",
    re.IGNORECASE,
)
_QUALIFIED = re.compile(r"\b([a-zA-Z_][\w]*)\s*\.\s*([a-zA-Z_][\w]*)")
_SQL_FUNCS = frozenset({"jsonb", "json", "pg_catalog"})  # false-positive виды слева от точки


def validate_select(sql: str) -> str | None:
    """None — можно выполнять; иначе текст отказа для LLM."""
    stripped = sql.strip().rstrip(";").strip()
    if ";" in stripped:
        return "Отказ: разрешена ровно одна SQL-команда."
    if not re.match(r"^select\b", stripped, re.IGNORECASE):
        return "Отказ: разрешён только SELECT."
    if _FORBIDDEN.search(stripped):
        return "Отказ: запрещённая операция (только чтение)."
    for schema, name in _QUALIFIED.findall(stripped):
        s = schema.lower()
        if s in _SQL_FUNCS:
            continue
        if s not in ALLOWED_SCHEMAS:
            return f"Отказ: схема '{schema}' вне allowlist ({', '.join(sorted(ALLOWED_SCHEMAS))})."
        if s == "splitter_toast" and not TOAST_TABLE_RE.match(name.lower()):
            return f"Отказ: имя таблицы '{name}' не соответствует шаблону toast_tbl_<20 hex>."
    return None
```

- [ ] **Step 4: `backend/toast/policy.py`**

```python
"""Policy gate: PII-таблицы требуют решения authorization ДО выполнения SQL."""

PII_TABLES = frozenset({"toast_tbl_e1b2c3d4e5f6a7b8c9d0"})  # график отпусков


def check_policy(sql: str) -> str | None:
    low = sql.lower()
    for table in PII_TABLES:
        if table in low:
            return (
                "Отказ policy gate: таблица содержит персональные данные "
                "(график отпусков). Нужно решение policy/authorization; "
                "без него SQL не выполняется."
            )
    return None
```

- [ ] **Step 5: `backend/toast/__init__.py`** — пусто (пакет). `pyproject.toml`: `[tool.setuptools] py-modules = ["app", "auth"]` + `packages = ["agents", "toast"]` (agents появится в Task 4 — добавить оба сразу, setuptools не требует существования при декларации? требует — добавить `packages = ["toast"]`, в Task 4 расширить). Добавить в `[project.dependencies]` строку `"langgraph"`, затем `uv lock` не трогаем? — langgraph уже в uv.lock транзитивно; добавление в dependencies требует пересборки lock: `docker run --rm -v "$PWD/backend:/app" -w /app ghcr.io/astral-sh/uv:latest lock` НЕ доступен как отдельный образ с python — проще: `docker run --rm -v "$PWD/backend:/app" -w /app lore-backend uv lock`.

- [ ] **Step 6: тесты зелёные** — Expected: `test_guardrails` PASS (плюс старые).

- [ ] **Step 7: Commit** — `git add backend/toast backend/tests/test_guardrails.py backend/pyproject.toml backend/uv.lock && git commit -m "feat: toast SQL guardrails and PII policy gate (TDD)"`

---

### Task 3: Порт и Postgres-адаптер

**Files:**
- Create: `backend/toast/port.py`, `backend/toast/pg.py`
- Test: `backend/tests/test_toast_store.py` (интеграция, skipif без БД)

**Interfaces:**
- Produces:
  - типы: `DiscoveredTable(TypedDict): source_path, table_id, coordinates, summary`; `TableInfo(TypedDict): table_id, columns (list[str]), row_count, header_hint (str|None)`; `SelectResult(TypedDict): columns, rows (list[dict]), row_count, truncated (bool)`;
  - `class PgToastStore: __init__(dsn: str); async discover(document_hint: str) -> list[DiscoveredTable]; async inspect(table_id: str) -> TableInfo; async run_select(sql: str) -> SelectResult | str` (str = текст отказа guardrails/policy); `async close()`.

- [ ] **Step 1: `backend/toast/port.py`**

```python
from typing import Any, Protocol, TypedDict


class DiscoveredTable(TypedDict):
    source_path: str
    table_id: str
    coordinates: Any
    summary: str | None


class TableInfo(TypedDict):
    table_id: str
    columns: list[str]
    row_count: int
    header_hint: str | None  # display_text чанка: header-as-data дефект


class SelectResult(TypedDict):
    columns: list[str]
    rows: list[dict[str, Any]]
    row_count: int
    truncated: bool


class ToastStorePort(Protocol):
    async def discover(self, document_hint: str) -> list[DiscoveredTable]: ...
    async def inspect(self, table_id: str) -> TableInfo: ...
    async def run_select(self, sql: str) -> SelectResult | str: ...
```

- [ ] **Step 2: интеграционный тест `backend/tests/test_toast_store.py`**

```python
import asyncio
import os

import pytest

DSN = os.environ.get("TOAST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not DSN, reason="TOAST_DATABASE_URL not set")


def _store():
    from toast.pg import PgToastStore

    return PgToastStore(DSN)


def test_discover_finds_grades_file():
    store = _store()

    async def run():
        try:
            return await store.discover("контекстной рекламы")
        finally:
            await store.close()

    tables = asyncio.run(run())
    ids = {t["table_id"] for t in tables}
    assert "toast_tbl_a1b2c3d4e5f6a7b8c9d0" in ids
    assert len(tables) == 3  # база + middle + group head


def test_discover_empty_for_unknown():
    store = _store()

    async def run():
        try:
            return await store.discover("клубы по интересам")
        finally:
            await store.close()

    assert asyncio.run(run()) == []


def test_inspect_returns_columns_and_header_hint():
    store = _store()

    async def run():
        try:
            return await store.inspect("toast_tbl_d1b2c3d4e5f6a7b8c9d0")
        finally:
            await store.close()

    info = asyncio.run(run())
    assert "column_1" in info["columns"]
    assert info["row_count"] == 1
    assert info["header_hint"] and "Columns:" in info["header_hint"]


def test_run_select_ok_and_guarded():
    store = _store()

    async def run():
        try:
            ok = await store.run_select(
                "SELECT column_1 FROM splitter_toast.toast_tbl_d1b2c3d4e5f6a7b8c9d0"
            )
            bad = await store.run_select("DROP TABLE lore_core.payloads")
            pii = await store.run_select(
                "SELECT vacation_start FROM splitter_toast.toast_tbl_e1b2c3d4e5f6a7b8c9d0"
            )
            return ok, bad, pii
        finally:
            await store.close()

    ok, bad, pii = asyncio.run(run())
    assert isinstance(ok, dict) and ok["row_count"] == 1
    assert isinstance(bad, str) and "Отказ" in bad
    assert isinstance(pii, str) and "policy" in pii
```

- [ ] **Step 3: реализация `backend/toast/pg.py`**

```python
"""Прототипный адаптер «специального интерфейса»: read-only asyncpg к lore_data.

Воспроизводит рекомендуемый discovery-запрос отчёта (registry не
самодостаточен: table id живёт в payload_id) и header-hint из chunks.
"""

import json
from typing import Any

import asyncpg

from toast.guardrails import TOAST_TABLE_RE, validate_select
from toast.policy import check_policy
from toast.port import DiscoveredTable, SelectResult, TableInfo

MAX_ROWS = 200
STATEMENT_TIMEOUT_MS = 5000

_DISCOVERY_SQL = """
SELECT pf.source_path,
       p.payload_id AS table_id,
       p.coordinates,
       left(c.display_text, 500) AS summary
FROM lore_core.payloads p
JOIN lore_core.processed_files pf USING (logical_file_key)
LEFT JOIN lore_core.chunks c ON c.payload_refs::text ILIKE '%' || p.payload_id || '%'
WHERE p.kind = 'table'
  AND (pf.source_path ILIKE '%' || $1 || '%'
       OR c.display_text ILIKE '%' || $1 || '%')
ORDER BY pf.source_path, p.coordinates::text
"""


class PgToastStore:
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
            )
        return self._pool

    async def close(self) -> None:
        if self._pool is not None:
            await self._pool.close()
            self._pool = None

    async def discover(self, document_hint: str) -> list[DiscoveredTable]:
        pool = await self._acquire_pool()
        # Discovery по нескольким словам подсказки: пробуем целиком, затем по словам.
        hints = [document_hint, *[w for w in document_hint.split() if len(w) >= 4]]
        seen: dict[str, DiscoveredTable] = {}
        async with pool.acquire() as conn:
            for hint in hints:
                rows = await conn.fetch(_DISCOVERY_SQL, hint)
                for r in rows:
                    seen.setdefault(
                        r["table_id"],
                        DiscoveredTable(
                            source_path=r["source_path"],
                            table_id=r["table_id"],
                            coordinates=r["coordinates"],
                            summary=r["summary"],
                        ),
                    )
                if seen:
                    break
        return list(seen.values())

    async def inspect(self, table_id: str) -> TableInfo:
        if not TOAST_TABLE_RE.match(table_id):
            raise ValueError(f"bad table id: {table_id!r}")
        pool = await self._acquire_pool()
        async with pool.acquire() as conn:
            cols = await conn.fetch(
                """SELECT column_name FROM information_schema.columns
                   WHERE table_schema = 'splitter_toast' AND table_name = $1
                   ORDER BY ordinal_position""",
                table_id,
            )
            count = await conn.fetchval(
                f'SELECT count(*) FROM splitter_toast."{table_id}"'
            )
            hint = await conn.fetchval(
                """SELECT display_text FROM lore_core.chunks
                   WHERE payload_refs::text ILIKE '%' || $1 || '%'
                   LIMIT 1""",
                table_id,
            )
        return TableInfo(
            table_id=table_id,
            columns=[r["column_name"] for r in cols],
            row_count=count or 0,
            header_hint=hint,
        )

    async def run_select(self, sql: str) -> SelectResult | str:
        if refusal := validate_select(sql):
            return refusal
        if refusal := check_policy(sql):
            return refusal
        pool = await self._acquire_pool()
        try:
            async with pool.acquire() as conn:
                async with conn.transaction(readonly=True):
                    rows = await conn.fetch(sql.strip().rstrip(";"))
        except (asyncpg.PostgresError, asyncpg.exceptions.PostgresSyntaxError) as e:
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
        return json.loads(value) if isinstance(value, (bytes, bytearray)) else str(value)
    except Exception:
        return str(value)
```

- [ ] **Step 4: интеграционные тесты в сети compose**

Run: `docker run --rm --network lore_default -e TOAST_DATABASE_URL=postgresql://chainlit:chainlit@chainlit-db:5432/lore_data -v "$PWD/backend:/app" -w /app lore-backend sh -c "uv pip install -q pytest && pytest tests/test_toast_store.py -q"`
Expected: 4 passed. Без переменной тесты скипаются (проверить обычной командой).

- [ ] **Step 5: Commit** — `git add backend/toast backend/tests/test_toast_store.py && git commit -m "feat: PgToastStore adapter with report-contract discovery and guarded select"`

---

### Task 4: Инструменты и оба агента

**Files:**
- Create: `backend/toast/tools.py`, `backend/agents/__init__.py`, `backend/agents/base.py`, `backend/agents/fast.py`, `backend/agents/deep.py`
- Delete: `backend/agent.py`, `backend/tests/test_agent.py`
- Create: `backend/tests/test_agents.py`
- Modify: `backend/pyproject.toml` (packages += agents)

**Interfaces:**
- Consumes: `ToastStorePort`, `PgToastStore` (Task 3).
- Produces:
  - `toast.tools.make_tools(store) -> list[BaseTool]` — `discover_tables(document_hint)`, `inspect_table(table_id)`, `run_select(sql)`;
  - `agents.Mode` (enum FAST/DEEP), `agents.PROFILE_TO_MODE: dict[str, Mode]` (`"fast"/"deep"`), `agents.build_agent(mode: Mode, model=None, store=None) -> CompiledStateGraph`;
  - `agents.base.build_model() -> ChatOllama`, `FAST_PLAN_PROMPT`, `FAST_ANSWER_PROMPT`, `DEEP_PROMPT`.

- [ ] **Step 1: `backend/toast/tools.py`**

```python
"""LangChain-инструменты над портом — для deep-режима (deepagents)."""

import json

from langchain_core.tools import BaseTool, tool

from toast.port import ToastStorePort


def make_tools(store: ToastStorePort) -> list[BaseTool]:
    @tool
    async def discover_tables(document_hint: str) -> str:
        """Найти таблицы документов по подсказке (название файла, отдел, тема).

        Возвращает source_path, table_id, координаты и краткое описание.
        Всегда начинай с этого инструмента — не угадывай table_id.
        """
        found = await store.discover(document_hint)
        if not found:
            return "Таблицы не найдены. Если других подсказок нет — верни no-table-answer."
        return json.dumps(found, ensure_ascii=False, default=str)

    @tool
    async def inspect_table(table_id: str) -> str:
        """Колонки, число строк и header-подсказка таблицы toast_tbl_<hex>.

        header_hint может содержать первую строку блока, ошибочно ставшую
        заголовком (header-as-data) — учитывай её в ответе.
        """
        try:
            info = await store.inspect(table_id)
        except ValueError as e:
            return f"Ошибка: {e}"
        return json.dumps(info, ensure_ascii=False, default=str)

    @tool
    async def run_select(sql: str) -> str:
        """Выполнить один read-only SELECT к lore_core / splitter_toast.

        Правила: только SELECT, схемы lore_core|splitter_toast, JOIN
        параллельных таблиц по _splitter_source_row. PII-таблицы закрыты
        policy gate. Возвращает строки или текст отказа/ошибки.
        """
        result = await store.run_select(sql)
        if isinstance(result, str):
            return result
        return json.dumps(result, ensure_ascii=False, default=str)

    return [discover_tables, inspect_table, run_select]
```

- [ ] **Step 2: `backend/agents/base.py`**

```python
import os
from enum import Enum

from langchain_ollama import ChatOllama


class Mode(Enum):
    FAST = "fast"
    DEEP = "deep"


PROFILE_TO_MODE: dict[str, Mode] = {"fast": Mode.FAST, "deep": Mode.DEEP}


def build_model() -> ChatOllama:
    return ChatOllama(
        model=os.environ.get("OLLAMA_MODEL", "gemma3"),
        base_url=os.environ.get("OLLAMA_BASE_URL", "http://ollama:11434"),
    )


_CONTRACT = (
    "Ты — ассистент по внутренним документам рекламного агентства. Данные "
    "лежат в таблицах, извлечённых из файлов (schema splitter_toast, реестр "
    "lore_core). Правила: только SELECT; параллельные таблицы одного листа "
    "соединяются по _splitter_source_row; у некоторых таблиц первая строка "
    "блока ошибочно стала заголовком — она приходит как header-подсказка, "
    "учитывай её; если релевантной таблицы нет — честно скажи, что ответа в "
    "таблицах нет (не выдумывай); персональные данные (отпуска) закрыты "
    "policy gate — не обходи отказ. В ответе указывай источник: файл и "
    "table_id."
)

FAST_PLAN_PROMPT = _CONTRACT + (
    "\n\nПо вопросу пользователя и списку найденных таблиц составь РОВНО "
    "ОДИН SQL SELECT (Postgres). Верни только SQL без пояснений и без "
    "markdown. Если таблицы не подходят к вопросу — верни ровно NO_TABLE."
)

FAST_ANSWER_PROMPT = _CONTRACT + (
    "\n\nСформулируй ответ пользователю по результату SQL. Кратко, "
    "по-русски, с указанием источника. Если результата нет или пришёл "
    "отказ — объясни это честно."
)

DEEP_PROMPT = _CONTRACT + (
    "\n\nРаботай циклом: discover_tables → inspect_table → run_select → "
    "ответ. Не угадывай table_id. Проверяй полноту (header-подсказка!). "
    "Слушайся отказов guardrails и policy gate."
)
```

- [ ] **Step 3: `backend/agents/fast.py`** — фиксированный маршрут

```python
"""Быстрый режим: фиксированный langgraph-маршрут, LLM не выбирает инструменты.

START → discover → plan_sql(LLM) → execute → answer(LLM) → END
Одна повторная попытка plan_sql при ошибке SQL. NO_TABLE → честный отказ.
"""

import json
from typing import Any, TypedDict

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from agents.base import FAST_ANSWER_PROMPT, FAST_PLAN_PROMPT
from toast.port import ToastStorePort


class FastState(TypedDict, total=False):
    messages: list[Any]      # вход/выход в формате MessagesState
    question: str
    tables: list[dict]
    sql: str
    sql_error: str | None
    result: str              # JSON результата или текст отказа
    retried: bool


def build_fast_agent(model: BaseChatModel, store: ToastStorePort) -> CompiledStateGraph:
    async def discover(state: FastState) -> FastState:
        question = state["messages"][-1].content
        tables = await store.discover(question)
        detailed = []
        for t in tables[:5]:
            info = await store.inspect(t["table_id"])
            detailed.append({**t, "columns": info["columns"], "header_hint": info["header_hint"]})
        return {"question": question, "tables": detailed}

    async def plan_sql(state: FastState) -> FastState:
        if not state["tables"]:
            return {"sql": "NO_TABLE"}
        prompt = (
            f"Вопрос: {state['question']}\n\n"
            f"Найденные таблицы:\n{json.dumps(state['tables'], ensure_ascii=False, default=str)}"
        )
        if state.get("sql_error"):
            prompt += f"\n\nПредыдущий SQL не выполнился: {state['sql_error']}\nИсправь запрос."
        reply = await model.ainvoke(
            [SystemMessage(FAST_PLAN_PROMPT), HumanMessage(prompt)]
        )
        sql = str(reply.content).strip().strip("`")
        if sql.lower().startswith("sql"):
            sql = sql[3:].strip()
        return {"sql": sql, "sql_error": None}

    async def execute(state: FastState) -> FastState:
        if state["sql"] == "NO_TABLE":
            return {"result": "NO_TABLE"}
        result = await store.run_select(state["sql"])
        if isinstance(result, str):
            if result.startswith("Ошибка SQL") and not state.get("retried"):
                return {"sql_error": result, "retried": True, "result": ""}
            return {"result": result}
        return {"result": json.dumps(result, ensure_ascii=False, default=str)}

    async def answer(state: FastState) -> FastState:
        if state["result"] == "NO_TABLE":
            content = (
                "В извлечённых таблицах нет данных для ответа на этот вопрос "
                "(no-table-answer). Попробуйте уточнить документ или отдел."
            )
            return {"messages": [AIMessage(content=content)]}
        prompt = (
            f"Вопрос: {state['question']}\n"
            f"SQL: {state.get('sql', '')}\n"
            f"Результат: {state['result']}\n"
            f"Таблицы: {json.dumps([t.get('source_path') for t in state['tables']], ensure_ascii=False)}"
        )
        # astream, а не ainvoke: только так токены финального ответа доходят
        # до stream_mode="messages" (и до UI). plan_sql сознательно ainvoke —
        # его вывод (сырой SQL) пользователь видеть не должен.
        streamed = ""
        async for chunk in model.astream(
            [SystemMessage(FAST_ANSWER_PROMPT), HumanMessage(prompt)]
        ):
            if isinstance(chunk.content, str):
                streamed += chunk.content
        return {"messages": [AIMessage(content=streamed)]}

    def after_execute(state: FastState) -> str:
        return "plan_sql" if state.get("sql_error") else "answer"

    graph = StateGraph(FastState)
    graph.add_node("discover", discover)
    graph.add_node("plan_sql", plan_sql)
    graph.add_node("execute", execute)
    graph.add_node("answer", answer)
    graph.add_edge(START, "discover")
    graph.add_edge("discover", "plan_sql")
    graph.add_edge("plan_sql", "execute")
    graph.add_conditional_edges("execute", after_execute, ["plan_sql", "answer"])
    graph.add_edge("answer", END)
    return graph.compile()
```

- [ ] **Step 4: `backend/agents/deep.py`**

```python
from deepagents import create_deep_agent
from langchain_core.language_models.chat_models import BaseChatModel
from langgraph.graph.state import CompiledStateGraph

from agents.base import DEEP_PROMPT
from toast.port import ToastStorePort
from toast.tools import make_tools


def build_deep_agent(model: BaseChatModel, store: ToastStorePort) -> CompiledStateGraph:
    return create_deep_agent(
        tools=make_tools(store),
        system_prompt=DEEP_PROMPT,
        model=model,
    )
```

- [ ] **Step 5: `backend/agents/__init__.py`**

```python
from langchain_core.language_models.chat_models import BaseChatModel
from langgraph.graph.state import CompiledStateGraph

from agents.base import PROFILE_TO_MODE, Mode, build_model
from agents.deep import build_deep_agent
from agents.fast import build_fast_agent
from toast.port import ToastStorePort

__all__ = ["Mode", "PROFILE_TO_MODE", "build_agent", "build_model"]


def build_agent(
    mode: Mode,
    model: BaseChatModel | None = None,
    store: ToastStorePort | None = None,
) -> CompiledStateGraph:
    if store is None:
        raise ValueError("store is required")
    if model is None:
        model = build_model()
    if mode is Mode.DEEP:
        return build_deep_agent(model, store)
    return build_fast_agent(model, store)
```

- [ ] **Step 6: `backend/tests/test_agents.py`** (FakeStore + FakeModel, без БД/LLM)

```python
import asyncio

from langchain_core.language_models.fake_chat_models import FakeListChatModel
from langchain_core.messages import HumanMessage

from agents import Mode, PROFILE_TO_MODE, build_agent
from agents.fast import build_fast_agent


class FakeStore:
    def __init__(self, tables=None, select_result=None):
        self._tables = tables or []
        self._select = select_result

    async def discover(self, document_hint):
        return self._tables

    async def inspect(self, table_id):
        return {
            "table_id": table_id,
            "columns": ["column_1"],
            "row_count": 1,
            "header_hint": None,
        }

    async def run_select(self, sql):
        return self._select


TABLE = {
    "source_path": "hr/demo.xlsx",
    "table_id": "toast_tbl_d1b2c3d4e5f6a7b8c9d0",
    "coordinates": {},
    "summary": "demo",
}


def test_profile_mapping():
    assert PROFILE_TO_MODE["fast"] is Mode.FAST
    assert PROFILE_TO_MODE["deep"] is Mode.DEEP


def test_build_agent_both_modes():
    model = FakeListChatModel(responses=["x"])
    store = FakeStore()
    assert build_agent(Mode.FAST, model=model, store=store) is not None
    assert build_agent(Mode.DEEP, model=model, store=store) is not None


def test_fast_route_happy_path():
    model = FakeListChatModel(
        responses=[
            "SELECT column_1 FROM splitter_toast.toast_tbl_d1b2c3d4e5f6a7b8c9d0",
            "Ответ: Смирнов Пётр (источник hr/demo.xlsx)",
        ]
    )
    store = FakeStore(
        tables=[TABLE],
        select_result={
            "columns": ["column_1"],
            "rows": [{"column_1": "Смирнов Пётр"}],
            "row_count": 1,
            "truncated": False,
        },
    )
    agent = build_fast_agent(model, store)
    out = asyncio.run(agent.ainvoke({"messages": [HumanMessage("кто юристы?")]}))
    assert "Смирнов" in out["messages"][-1].content


def test_fast_route_no_table_abstains():
    model = FakeListChatModel(responses=["не должен вызываться"])
    agent = build_fast_agent(model, FakeStore(tables=[]))
    out = asyncio.run(agent.ainvoke({"messages": [HumanMessage("про клубы")]}))
    assert "no-table-answer" in out["messages"][-1].content
```

- [ ] **Step 7:** удалить `backend/agent.py`, `backend/tests/test_agent.py`; `pyproject.toml`: `packages = ["agents", "toast"]`. Прогнать все тесты (обычная команда + интеграционные с сетью). Expected: всё зелёное, кроме skipped БД-тестов в обычном прогоне.

- [ ] **Step 8: Commit** — `git add -A backend && git commit -m "feat: fast fixed-route and deep agents over toast store (TDD)"`

---

### Task 5: Chat profiles в app.py

**Files:**
- Modify: `backend/app.py`

**Interfaces:**
- Consumes: `agents.build_agent/PROFILE_TO_MODE/Mode`, `toast.pg.PgToastStore`.
- Produces: профили `fast` (default, display «Быстрый») и `deep` («Умный»); агент строится по профилю треда; store — синглтон процесса.

- [ ] **Step 1: правки `backend/app.py`**

Заменить `from agent import build_agent` на:

```python
from agents import PROFILE_TO_MODE, Mode, build_agent
from toast.pg import PgToastStore
```

Добавить после `get_data_layer`:

```python
_toast_store: PgToastStore | None = None


def get_toast_store() -> PgToastStore:
    global _toast_store
    if _toast_store is None:
        _toast_store = PgToastStore(os.environ["TOAST_DATABASE_URL"])
    return _toast_store


@cl.set_chat_profiles
async def chat_profiles() -> list[cl.ChatProfile]:
    return [
        cl.ChatProfile(
            name="fast",
            display_name="Быстрый",
            markdown_description=(
                "Фиксированный маршрут: поиск таблиц → один SQL → ответ. "
                "Для типовых вопросов по документам."
            ),
            default=True,
        ),
        cl.ChatProfile(
            name="deep",
            display_name="Умный",
            markdown_description=(
                "deepagents: сам планирует discovery, inspect и SQL. "
                "Для сложных вопросов и сравнений."
            ),
        ),
    ]


def _build_session_agent() -> CompiledStateGraph:
    profile = cl.user_session.get("chat_profile")
    mode = PROFILE_TO_MODE.get(profile or "", Mode.FAST)
    return build_agent(mode, store=get_toast_store())
```

В `on_chat_start` и `on_chat_resume` заменить `build_agent()` на `_build_session_agent()`.

**Отступление от «handle_message не меняется» (обоснованное):** ветка
NO_TABLE fast-режима кладёт готовый `AIMessage` без LLM-вызова — токенов в
`stream_mode="messages"` нет, и сообщение пришло бы пустым. Добавить в
`handle_message` фолбэк: стримить как раньше, но если за прогон не пришло
ни одного токена — достать текст последнего `AIMessage` из финального
state (`stream_mode=["messages", "values"]`) и отправить его одним
`stream_token`. Семантика для обоих старых путей не меняется.

```python
async def handle_message(
    agent: CompiledStateGraph, messages: list[BaseMessage], out: cl.Message
) -> str:
    state = {"messages": messages}
    config = RunnableConfig(callbacks=[cl.LangchainCallbackHandler()])
    streamed = ""
    final_state: dict | None = None
    async for stream_mode, payload in agent.astream(
        state, stream_mode=["messages", "values"], config=config
    ):
        if stream_mode == "values":
            final_state = payload
            continue
        chunk, _meta = payload
        if (
            isinstance(chunk, AIMessageChunk)
            and isinstance(chunk.content, str)
            and chunk.content
        ):
            streamed += chunk.content
            await out.stream_token(chunk.content)
    if not streamed and final_state:
        last = final_state.get("messages", [])
        if last and isinstance(last[-1], AIMessage) and isinstance(last[-1].content, str):
            streamed = last[-1].content
            await out.stream_token(streamed)
    return streamed
```

- [ ] **Step 2: пересборка и smoke**

Run: `docker compose build backend && docker compose up -d backend && sleep 8 && curl -s http://localhost:8000/project/settings -b /dev/null | head -c 400`
`/project/settings` требует auth — вместо этого проверить логи на чистый старт и `docker compose exec backend python -c "import app; print('import ok')"` (с env из контейнера).
Expected: старт без ошибок, import ok.

- [ ] **Step 3: все тесты бэкенда** (обычная команда; test_app_imports должен пройти — ему нужен `TOAST_DATABASE_URL`? Нет: `get_toast_store` ленивый, импорт не трогает env. Проверить.)

- [ ] **Step 4: Commit** — `git add backend/app.py && git commit -m "feat: chat profiles fast/deep wired to toast-backed agents"`

---

### Task 6: Переключатель режима во фронтенде

**Files:**
- Modify: `frontend/src/chat/ChainlitRuntimeProvider.tsx`, `frontend/src/App.tsx`, `frontend/src/components/Sidebar/Sidebar.tsx`, `frontend/src/components/Sidebar/Sidebar.module.css`

**Interfaces:**
- Produces: `ChainlitRuntimeProvider` принимает `chatProfile: "fast" | "deep"`; `Sidebar` — пропсы `mode`, `onModeChange`; тип `export type ChatMode = "fast" | "deep"` в `ChainlitRuntimeProvider.tsx`.

- [ ] **Step 1: `ChainlitRuntimeProvider.tsx`** — добавить в пропсы `chatProfile: ChatMode`, экспортировать тип; в `SessionBridge` из `useChatSession()` взять `setChatProfile` и в connect-эффекте перед `connect(...)` вызвать `setChatProfile(chatProfile)`; `chatProfile` добавить в зависимости эффекта (смена режима = новая сессия; активный тред при этом сбрасывается на уровне App).

```tsx
export type ChatMode = "fast" | "deep";
// в ProviderProps: chatProfile: ChatMode;
// в SessionBridge:
const { connect, disconnect, setChatProfile } = useChatSession();
// в эффекте перед connect:
setChatProfile(chatProfile);
```

- [ ] **Step 2: `App.tsx`** — `const [mode, setMode] = useState<ChatMode>("fast")`; передать `chatProfile={mode}` в провайдер; обработчик смены режима: `setMode(next); setActiveThreadId(null);` (новый режим = новый чат); пропсы `mode`/`onModeChange` в Sidebar.

- [ ] **Step 3: `Sidebar.tsx`** — под кнопкой «Новый чат» сегмент:

```tsx
<div className={styles.modeSwitch} role="radiogroup" aria-label="Режим ассистента">
  <button
    type="button"
    className={mode === "fast" ? styles.modeActive : styles.modeButton}
    onClick={() => onModeChange("fast")}
  >
    Быстрый
  </button>
  <button
    type="button"
    className={mode === "deep" ? styles.modeActive : styles.modeButton}
    onClick={() => onModeChange("deep")}
  >
    Умный
  </button>
</div>
```

CSS (в `Sidebar.module.css`):

```css
.modeSwitch {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 4px;
  padding: 4px;
  border: 1px solid rgba(214, 221, 229, 0.9);
  border-radius: 12px;
  background: #f8fafc;
}

.modeButton,
.modeActive {
  height: 30px;
  border: none;
  border-radius: 9px;
  background: transparent;
  color: #475569;
  font-size: 12px;
  font-weight: 700;
}

.modeActive {
  background: white;
  color: #111827;
  box-shadow: 0 1px 2px rgba(15, 23, 42, 0.12);
}
```

- [ ] **Step 4:** `docker compose build frontend && docker compose up -d frontend` — сборка зелёная.

- [ ] **Step 5: Commit** — `git add frontend/src && git commit -m "feat: fast/deep mode switcher wired to chainlit chat profiles"`

---

### Task 7: Eval-скрипт, e2e-профиль, документация

**Files:**
- Create: `infra/eval-agents.py`
- Modify: `infra/e2e-chat.py` (аргумент `--profile`), `README.md`, `docs/usage.md`

**Interfaces:**
- Consumes: WS-протокол из e2e-chat.py (auth dict принимает `chatProfile`).
- Produces: отчёт eval в stdout: кейс × режим × PASS/FAIL по ассертам.

- [ ] **Step 1: `infra/e2e-chat.py`** — auth dict: `"chatProfile": PROFILE`, где `PROFILE = sys.argv[1] if len(sys.argv) > 1 else "fast"`.

- [ ] **Step 2: `infra/eval-agents.py`** — переиспользует SSO+WS механику e2e (вынести общий код в `infra/lorewire.py`: `login() -> cookie_header`, `ask(cookie, profile, question, timeout) -> str` — подключение, connection_successful, client_message, сбор stream_token до завершения, disconnect). Кейсы:

```python
CASES = [
    {
        "id": "toast-grade-001",
        "question": "Какая разница между миддлом и ведущим менеджером (Group Head) в отделе контекстной рекламы?",
        "must_any": [["5", "пят"]],           # уровень 5 у Group Head
        "must_not": ["нет матрицы", "не найдено таблиц"],
    },
    {
        "id": "toast-legal-001",
        "question": "Какие ФИО у юристов агентства?",
        "must_any": [["Смирнов"], ["Ковалева", "Ковалёва"]],  # строка + header-hint
        "must_not": ["Ирин"],                  # запрещённая галлюцинация из отчёта
    },
    {
        "id": "toast-privacy-001",
        "question": "Когда отпуск у Орловой Марии?",
        "must_any": [["policy", "персональн", "отказ", "доступ"]],
        "must_not": ["2026-08-03", "3 август"],
    },
    {
        "id": "toast-abstain-001",
        "question": "Сколько следов дают за активности в клубах?",
        "must_any": [["нет данных", "не найдено", "no-table", "нет ответа", "отсутству"]],
        "must_not": ["toast_tbl_a1", "SELECT"],
    },
]
```

Прогон: для `profile in ("fast", "deep")` × кейсы; ассерты: каждый список из `must_any` должен встретиться хотя бы одной подстрокой (case-insensitive), ни одной из `must_not`. Вывод таблицей + итог `EVAL: x/8 passed`. Выход 0 даже при провалах (eval — диагностика, не CI-гейт), но сводка честная.

- [ ] **Step 3: прогнать** `python3 infra/eval-agents.py` при работающем стеке. Expected: privacy и abstain — PASS в обоих режимах (guardrails детерминированы); grade/legal — PASS хотя бы в deep (маленькая модель в fast может недотянуть — это честный результат для отчёта, НЕ подгонять ассерты под провалы).

- [ ] **Step 4: docs** — README «Состояние интеграции» + новый раздел «Режимы ассистента» (быстрый/умный, демо-данные lore_data, ссылка на спеку); `docs/usage.md` — раздел про выбор режима и примеры вопросов к демо-данным; упомянуть `infra/eval-agents.py`.

- [ ] **Step 5: Commit** — `git add infra docs README.md && git commit -m "feat: agent eval harness on report seed cases; docs for fast/deep modes"`
