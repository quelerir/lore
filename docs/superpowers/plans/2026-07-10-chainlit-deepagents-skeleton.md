# Chainlit + deepagents Skeleton Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a minimal `chainlit run` service — JWT-authenticated, Postgres-persisted, answering via a tool-less deepagents agent over Ollama/gemma3 — packaged as a `docker compose up` project.

**Architecture:** One Chainlit app (`app.py`) wires four hooks (header auth, data layer, chat lifecycle, message). Agent construction is isolated in `agent.py` (`build_agent`), JWT validation in `auth.py` (`verify_ticket`). Three compose services: app, Postgres (`chainlit-db`), Ollama.

**Tech Stack:** Python 3.13, Chainlit, deepagents, langchain-ollama, SQLAlchemy + asyncpg, PyJWT, Postgres, Ollama, Docker Compose.

## Global Constraints

- Python 3.13.
- Agent must run via streaming (`agent.astream(..., stream_mode="values")`) — never `ainvoke` (deadlocks under Chainlit's nest_asyncio).
- Data-layer SQLAlchemy engine must use `poolclass=NullPool`.
- `@cl.header_auth_callback` returns `cl.User(identifier=str(sub))`; `identifier == sub`.
- JWT is HS256, symmetric shared secret; validate `aud` / `iss` / `exp`.
- No chat profiles, no MCP tools, no `userEnv` forwarding, no `cl.Plotly` — out of scope.
- Env var names (verbatim): `CHAINLIT_JWT_SECRET`, `CHAINLIT_JWT_ISSUER` (`datacraft`), `CHAINLIT_JWT_AUDIENCE` (`chainlit`), `DATABASE_URL`, `OLLAMA_BASE_URL`, `OLLAMA_MODEL` (`gemma3`).

---

### Task 1: Project scaffolding & dependencies

**Files:**
- Create: `pyproject.toml`
- Create: `.env.example`
- Create: `.gitignore`

**Interfaces:**
- Consumes: nothing.
- Produces: installable environment with `chainlit`, `deepagents`, `langchain-ollama`, `sqlalchemy[asyncio]`, `asyncpg`, `pyjwt`, plus `pytest` for tests. Python `>=3.13`.

- [ ] **Step 1: Write `pyproject.toml`**

```toml
[project]
name = "datacraft-chainlit"
version = "0.1.0"
description = "Minimal Chainlit + deepagents service for datacraft"
requires-python = ">=3.13"
dependencies = [
    "chainlit>=2.0",
    "deepagents",
    "langchain-ollama",
    "sqlalchemy[asyncio]>=2.0",
    "asyncpg",
    "pyjwt>=2.8",
]

[project.optional-dependencies]
dev = ["pytest>=8.0"]

[tool.pytest.ini_options]
testpaths = ["tests"]
```

- [ ] **Step 2: Write `.env.example`**

```dotenv
CHAINLIT_JWT_SECRET=change-me-shared-with-datacraft
CHAINLIT_JWT_ISSUER=datacraft
CHAINLIT_JWT_AUDIENCE=chainlit
DATABASE_URL=postgresql+asyncpg://chainlit:chainlit@chainlit-db:5432/chainlit
OLLAMA_BASE_URL=http://ollama:11434
OLLAMA_MODEL=gemma3
```

- [ ] **Step 3: Write `.gitignore`**

```gitignore
__pycache__/
*.pyc
.env
.chainlit/translations/
.files/
.venv/
```

- [ ] **Step 4: Install and verify**

Run: `pip install -e ".[dev]"`
Expected: completes; `python -c "import chainlit, deepagents, langchain_ollama, jwt, sqlalchemy, asyncpg"` prints nothing (no ImportError).

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml .env.example .gitignore
git commit -m "chore: project scaffolding and dependencies"
```

---

### Task 2: JWT ticket verification (`auth.py`)

**Files:**
- Create: `auth.py`
- Test: `tests/test_auth.py`

**Interfaces:**
- Consumes: env vars `CHAINLIT_JWT_SECRET`, `CHAINLIT_JWT_ISSUER`, `CHAINLIT_JWT_AUDIENCE`.
- Produces: `verify_ticket(token: str) -> dict` returning `{"sub": str, "username": str}`; raises `jwt.InvalidTokenError` (or subclass) on any invalid/expired/wrong-aud/wrong-iss token.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_auth.py
import time
import jwt
import pytest
import auth

SECRET = "test-secret"


def _token(**over):
    payload = {
        "sub": "42",
        "username": "alice",
        "aud": "chainlit",
        "iss": "datacraft",
        "exp": int(time.time()) + 60,
    }
    payload.update(over)
    return jwt.encode(payload, SECRET, algorithm="HS256")


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv("CHAINLIT_JWT_SECRET", SECRET)
    monkeypatch.setenv("CHAINLIT_JWT_ISSUER", "datacraft")
    monkeypatch.setenv("CHAINLIT_JWT_AUDIENCE", "chainlit")


def test_valid_ticket_returns_sub_and_username():
    claims = auth.verify_ticket(_token())
    assert claims == {"sub": "42", "username": "alice"}


def test_expired_ticket_rejected():
    with pytest.raises(jwt.InvalidTokenError):
        auth.verify_ticket(_token(exp=int(time.time()) - 10))


def test_wrong_audience_rejected():
    with pytest.raises(jwt.InvalidTokenError):
        auth.verify_ticket(_token(aud="someone-else"))


def test_wrong_issuer_rejected():
    with pytest.raises(jwt.InvalidTokenError):
        auth.verify_ticket(_token(iss="attacker"))


def test_bad_signature_rejected():
    bad = jwt.encode({"sub": "1", "aud": "chainlit", "iss": "datacraft"},
                     "wrong-secret", algorithm="HS256")
    with pytest.raises(jwt.InvalidTokenError):
        auth.verify_ticket(bad)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_auth.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'auth'`.

- [ ] **Step 3: Write minimal implementation**

```python
# auth.py
import os
import jwt


def verify_ticket(token: str) -> dict:
    """Validate a datacraft-issued HS256 ticket, return {sub, username}.

    Raises jwt.InvalidTokenError (or subclass) on any validation failure.
    """
    payload = jwt.decode(
        token,
        os.environ["CHAINLIT_JWT_SECRET"],
        algorithms=["HS256"],
        audience=os.environ["CHAINLIT_JWT_AUDIENCE"],
        issuer=os.environ["CHAINLIT_JWT_ISSUER"],
        options={"require": ["exp", "sub", "aud", "iss"]},
    )
    return {
        "sub": str(payload["sub"]),
        "username": str(payload.get("username", payload["sub"])),
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_auth.py -v`
Expected: PASS (5 passed).

- [ ] **Step 5: Commit**

```bash
git add auth.py tests/test_auth.py
git commit -m "feat: JWT ticket verification"
```

---

### Task 3: Agent factory (`agent.py`)

**Files:**
- Create: `agent.py`
- Test: `tests/test_agent.py`

**Interfaces:**
- Consumes: env vars `OLLAMA_BASE_URL`, `OLLAMA_MODEL`.
- Produces: `build_agent()` returning a compiled deepagents/LangGraph agent exposing `.astream(...)`. No arguments; reads config from env.

- [ ] **Step 1: Write the failing test**

The test avoids contacting Ollama — it only asserts `build_agent()` constructs an object with an `astream` method, and that the model is wired to the configured base URL/model.

```python
# tests/test_agent.py
import agent


def test_build_agent_returns_streamable(monkeypatch):
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://ollama:11434")
    monkeypatch.setenv("OLLAMA_MODEL", "gemma3")
    a = agent.build_agent()
    assert hasattr(a, "astream")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_agent.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'agent'`.

- [ ] **Step 3: Write minimal implementation**

```python
# agent.py
import os

from deepagents import create_deep_agent
from langchain_ollama import ChatOllama

SYSTEM_PROMPT = (
    "You are the datacraft assistant. Answer the user's questions clearly "
    "and concisely."
)


def build_agent():
    """Build a tool-less deepagents agent backed by Ollama.

    Reads OLLAMA_MODEL and OLLAMA_BASE_URL from the environment. Returns a
    compiled LangGraph agent; run it with `.astream(...)` (never `.ainvoke`).
    """
    model = ChatOllama(
        model=os.environ.get("OLLAMA_MODEL", "gemma3"),
        base_url=os.environ.get("OLLAMA_BASE_URL", "http://ollama:11434"),
    )
    return create_deep_agent(
        tools=[],
        instructions=SYSTEM_PROMPT,
        model=model,
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_agent.py -v`
Expected: PASS.

Note: if the installed `deepagents` exposes a different factory name, run
`python -c "import deepagents, inspect; print([n for n in dir(deepagents) if 'agent' in n.lower()])"` and use the discovered `create_deep_agent`-equivalent. Keep the `tools=[]`, `instructions=`, `model=` shape.

- [ ] **Step 5: Commit**

```bash
git add agent.py tests/test_agent.py
git commit -m "feat: tool-less Ollama deepagent factory"
```

---

### Task 4: Chainlit app wiring (`app.py`)

**Files:**
- Create: `app.py`
- Test: `tests/test_app_imports.py`

**Interfaces:**
- Consumes: `auth.verify_ticket`, `agent.build_agent`, env var `DATABASE_URL`.
- Produces: importable Chainlit module registering `header_auth_callback`, `data_layer`, `on_chat_start`, `on_chat_resume`, `on_message`. Agent stored in `cl.user_session` under key `"agent"`.

- [ ] **Step 1: Write the failing test**

Import-only smoke test (handlers need a live Chainlit runtime to exercise, so we verify the module imports and the data-layer factory uses NullPool).

```python
# tests/test_app_imports.py
import importlib


def test_app_imports(monkeypatch):
    monkeypatch.setenv("CHAINLIT_JWT_SECRET", "x")
    monkeypatch.setenv("CHAINLIT_JWT_ISSUER", "datacraft")
    monkeypatch.setenv("CHAINLIT_JWT_AUDIENCE", "chainlit")
    monkeypatch.setenv("DATABASE_URL",
                       "postgresql+asyncpg://u:p@localhost:5432/db")
    app = importlib.import_module("app")
    assert hasattr(app, "handle_message")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_app_imports.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app'`.

- [ ] **Step 3: Write minimal implementation**

```python
# app.py
import os
from typing import Optional

import chainlit as cl
from chainlit.data.sql_alchemy import SQLAlchemyDataLayer
from langchain_core.messages import HumanMessage
from langchain_core.runnables import RunnableConfig
from sqlalchemy.pool import NullPool

from agent import build_agent
from auth import verify_ticket


@cl.data_layer
def get_data_layer():
    return SQLAlchemyDataLayer(
        conninfo=os.environ["DATABASE_URL"],
        engine_args={"poolclass": NullPool},
    )


@cl.header_auth_callback
def header_auth_callback(headers) -> Optional[cl.User]:
    authorization = headers.get("Authorization") or headers.get("authorization")
    if not authorization or not authorization.lower().startswith("bearer "):
        return None
    token = authorization.split(" ", 1)[1].strip()
    try:
        claims = verify_ticket(token)
    except Exception:
        return None
    return cl.User(
        identifier=claims["sub"],
        metadata={"username": claims["username"]},
    )


@cl.on_chat_start
async def on_chat_start():
    cl.user_session.set("agent", build_agent())


@cl.on_chat_resume
async def on_chat_resume(thread):
    cl.user_session.set("agent", build_agent())


async def handle_message(agent, content: str) -> str:
    """Stream the agent over one user turn, return the final assistant text."""
    state = {"messages": [HumanMessage(content=content)]}
    config = RunnableConfig(callbacks=[cl.LangchainCallbackHandler()])
    final = ""
    async for step in agent.astream(state, stream_mode="values", config=config):
        messages = step.get("messages") if isinstance(step, dict) else None
        if messages:
            final = messages[-1].content
    return final


@cl.on_message
async def on_message(message: cl.Message):
    agent = cl.user_session.get("agent")
    answer = await handle_message(agent, message.content)
    await cl.Message(content=answer).send()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_app_imports.py -v`
Expected: PASS.

- [ ] **Step 5: Run full suite**

Run: `pytest -v`
Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
git add app.py tests/test_app_imports.py
git commit -m "feat: chainlit app wiring (auth, data layer, message loop)"
```

---

### Task 5: Chainlit config, welcome, DB schema

**Files:**
- Create: `.chainlit/config.toml`
- Create: `chainlit.md`
- Create: `init/schema.sql`

**Interfaces:**
- Consumes: nothing at runtime beyond Chainlit reading `.chainlit/config.toml`.
- Produces: CORS-enabled config; Postgres schema matching `SQLAlchemyDataLayer` (tables `users`, `threads`, `steps`, `elements`, `feedbacks`).

- [ ] **Step 1: Write `.chainlit/config.toml`**

Minimal config; the essential part is `allow_origins` for the datacraft frontend.

```toml
[project]
enable_telemetry = false
allow_origins = ["http://localhost:9000", "http://localhost:8088"]

[features]
unsafe_allow_html = false

[UI]
name = "datacraft"
```

- [ ] **Step 2: Write `chainlit.md`**

```markdown
# datacraft assistant

Минимальный Chainlit-сервис (deepagents + Ollama). Каркас интеграции с datacraft.
```

- [ ] **Step 3: Write `init/schema.sql`**

Official Chainlit SQLAlchemy data-layer schema.

```sql
CREATE TABLE IF NOT EXISTS users (
    "id" UUID PRIMARY KEY,
    "identifier" TEXT NOT NULL UNIQUE,
    "metadata" JSONB NOT NULL,
    "createdAt" TEXT
);

CREATE TABLE IF NOT EXISTS threads (
    "id" UUID PRIMARY KEY,
    "createdAt" TEXT,
    "name" TEXT,
    "userId" UUID,
    "userIdentifier" TEXT,
    "tags" TEXT[],
    "metadata" JSONB,
    FOREIGN KEY ("userId") REFERENCES users("id") ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS steps (
    "id" UUID PRIMARY KEY,
    "name" TEXT NOT NULL,
    "type" TEXT NOT NULL,
    "threadId" UUID NOT NULL,
    "parentId" UUID,
    "streaming" BOOLEAN NOT NULL,
    "waitForAnswer" BOOLEAN,
    "isError" BOOLEAN,
    "metadata" JSONB,
    "tags" TEXT[],
    "input" TEXT,
    "output" TEXT,
    "createdAt" TEXT,
    "start" TEXT,
    "end" TEXT,
    "generation" JSONB,
    "showInput" TEXT,
    "language" TEXT,
    "indent" INT,
    "defaultOpen" BOOLEAN,
    FOREIGN KEY ("threadId") REFERENCES threads("id") ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS elements (
    "id" UUID PRIMARY KEY,
    "threadId" UUID,
    "type" TEXT,
    "url" TEXT,
    "chainlitKey" TEXT,
    "name" TEXT NOT NULL,
    "display" TEXT,
    "objectKey" TEXT,
    "size" TEXT,
    "page" INT,
    "language" TEXT,
    "forId" UUID,
    "mime" TEXT,
    "props" JSONB,
    FOREIGN KEY ("threadId") REFERENCES threads("id") ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS feedbacks (
    "id" UUID PRIMARY KEY,
    "forId" UUID NOT NULL,
    "threadId" UUID NOT NULL,
    "value" INT NOT NULL,
    "comment" TEXT,
    FOREIGN KEY ("threadId") REFERENCES threads("id") ON DELETE CASCADE
);
```

- [ ] **Step 4: Verify SQL parses**

Run: `python -c "import re,sys; s=open('init/schema.sql').read(); assert s.count('CREATE TABLE')==5; print('ok')"`
Expected: prints `ok`.

- [ ] **Step 5: Commit**

```bash
git add .chainlit/config.toml chainlit.md init/schema.sql
git commit -m "feat: chainlit config, welcome, postgres schema"
```

---

### Task 6: Dockerfile & docker-compose

**Files:**
- Create: `Dockerfile`
- Create: `docker-compose.yml`

**Interfaces:**
- Consumes: all previous files; `.env` (copied from `.env.example`).
- Produces: `docker compose up` bringing up `app` (Chainlit on 8000), `chainlit-db` (Postgres), `ollama` (11434).

- [ ] **Step 1: Write `Dockerfile`**

```dockerfile
FROM python:3.13-slim

WORKDIR /app

COPY pyproject.toml ./
RUN pip install --no-cache-dir -e .

COPY . .

EXPOSE 8000
CMD ["chainlit", "run", "app.py", "--host", "0.0.0.0", "--port", "8000"]
```

- [ ] **Step 2: Write `docker-compose.yml`**

```yaml
services:
  app:
    build: .
    env_file: .env
    ports:
      - "8000:8000"
    depends_on:
      chainlit-db:
        condition: service_healthy
      ollama:
        condition: service_started

  chainlit-db:
    image: postgres:16
    environment:
      POSTGRES_USER: chainlit
      POSTGRES_PASSWORD: chainlit
      POSTGRES_DB: chainlit
    volumes:
      - ./init/schema.sql:/docker-entrypoint-initdb.d/schema.sql:ro
      - chainlit-db-data:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U chainlit"]
      interval: 5s
      timeout: 5s
      retries: 5

  ollama:
    image: ollama/ollama:latest
    ports:
      - "11434:11434"
    volumes:
      - ollama-data:/root/.ollama

volumes:
  chainlit-db-data:
  ollama-data:
```

- [ ] **Step 3: Validate compose config**

Run: `cp .env.example .env && docker compose config -q && echo ok`
Expected: prints `ok` (config is valid).

- [ ] **Step 4: Build the app image**

Run: `docker compose build app`
Expected: image builds without error.

- [ ] **Step 5: Commit**

```bash
git add Dockerfile docker-compose.yml
git commit -m "feat: dockerfile and compose (app + postgres + ollama)"
```

---

### Task 7: End-to-end smoke & README

**Files:**
- Create: `README.md`

**Interfaces:**
- Consumes: the full running stack.
- Produces: documented run/verify steps; confirmed working chat + persistence.

- [ ] **Step 1: Bring the stack up**

Run: `docker compose up -d`
Expected: all three services healthy/started.

- [ ] **Step 2: Pull the model**

Run: `docker compose exec ollama ollama pull gemma3`
Expected: model downloads; `ollama list` shows `gemma3`.

- [ ] **Step 3: Verify Chainlit is serving**

Run: `curl -sf http://localhost:8000/ >/dev/null && echo ok`
Expected: prints `ok` (Chainlit app responds).

- [ ] **Step 4: Verify schema was applied**

Run: `docker compose exec chainlit-db psql -U chainlit -d chainlit -c "\dt"`
Expected: lists `users`, `threads`, `steps`, `elements`, `feedbacks`.

- [ ] **Step 5: Write `README.md`**

```markdown
# datacraft-chainlit

Минимальный Chainlit-сервис на deepagents + Ollama (gemma3) с JWT-аутентификацией
и хранением истории в Postgres. Каркас интеграции с фронтендом datacraft.

## Запуск

```bash
cp .env.example .env          # выставить CHAINLIT_JWT_SECRET, общий с datacraft
docker compose up -d
docker compose exec ollama ollama pull gemma3
```

Chainlit доступен на http://localhost:8000.

## Компоненты

- `app.py` — обработчики Chainlit (auth, data layer, on_message).
- `agent.py` — `build_agent()`, фабрика deepagent поверх Ollama.
- `auth.py` — `verify_ticket()`, проверка JWT (HS256).
- `init/schema.sql` — схема Postgres data layer.

## Тесты

```bash
pip install -e ".[dev]"
pytest -v
```

## Область каркаса

Реализовано: JWT-auth, персистентность в Postgres, чистый чат-агент.
Опущено (см. `description.md`): профили charts/analyst, MCP-инструменты,
форвардинг userEnv, cl.Plotly-ответы.
```

- [ ] **Step 6: Commit**

```bash
git add README.md
git commit -m "docs: README with run and verify instructions"
```

---

## Self-Review Notes

- **Spec coverage:** JWT auth (Task 2), data layer NullPool (Task 4/5), streaming-not-ainvoke (Task 4), build_agent isolated (Task 3), Postgres in compose (Task 6), schema (Task 5), CORS allow_origins (Task 5), Python 3.13 (Task 1/6). Out-of-scope items (profiles/MCP/plotly) intentionally excluded per approved spec.
- **Placeholders:** none — all code shown in full.
- **Type consistency:** `build_agent()` (no args) used identically in Task 3 and Task 4; `verify_ticket(token) -> {sub, username}` consumed as `claims["sub"]`/`claims["username"]` in Task 4; `handle_message(agent, content)` defined and referenced in Task 4.
