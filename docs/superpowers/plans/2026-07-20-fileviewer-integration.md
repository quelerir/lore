> **⚠️ SUPERSEDED (2026-07-21).** This plan described integrating the audit read
> API by vendoring a copy into `backend/audit/`. That approach was abandoned during
> the lore↔agent-lore merge. The audit API now lives in the `lore-audit-core` /
> `lore-audit-api` packages and is mounted into chat via
> `lore-core/services/lore-chat/audit_mount.py` + `audit_auth.py`. Kept for history only.

# FileViewer (audit read API) Integration — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Vendor the lore-core read-only audit HTTP API into the `lore` monolith and mount it under `/api/v1/audit` on the running Chainlit app, guarded by the existing auth, reading the `lore_core` schema over sync psycopg.

**Architecture:** Copy the read-side of `SRC/audit/` into `backend/audit/`, rewrite `airflow.providers.lore.audit.*` imports to `audit.*`, and satisfy three `splitter` symbols with local vendor shims. Build a sync psycopg pool (PgBouncer-safe) exposing `.acquire()`, assemble `AuditReadService` (repository + table + source readers; image reader deferred), and attach the router to `chainlit.server.app` with a `verify_ticket`-based dependency. Sync route handlers run in FastAPI's threadpool, so blocking psycopg never stalls the Chainlit event loop.

**Tech Stack:** Python 3.13, FastAPI (transitive via Chainlit 2.11), Pydantic v2, `psycopg[binary,pool]==3.3.4`, pytest, `fastapi.testclient`.

**Design spec:** `docs/superpowers/specs/2026-07-20-fileviewer-integration-design.md`
**Frontend contract:** `docs/lore-file-viewer-frontend-spec.md`
**Source (verbatim copy source):** `SRC = /Users/stamplevskiyd/adventum/agent-lore/lore-core/airflow-providers/apache-airflow-providers-lore/airflow/providers/lore`

## Global Constraints

- Copy **only** the read-side; never copy `http_api/runtime.py`, `service.py`, `repository.py`, `ruleset.py`, `rules/`, `suppression.py`, `persistence.py`, `airflow_adapters.py`, `engine.py`.
- No new external dep except `psycopg[binary,pool]==3.3.4` (and later `boto3` for images).
- The audit module must import with **zero** `airflow` or `splitter` imports remaining.
- psycopg connections MUST set `prepare_threshold=None` (PgBouncer transaction-pooling).
- Router prefix `/api/v1/audit` is built into `create_audit_router` — do not add another prefix.
- Cursor HMAC key ≥16 bytes, stable across restarts (`AUDIT_CURSOR_KEY`).
- DTOs stay as the real `audit-read/*` shapes — do not reshape output.
- Image reader is **not** wired in this plan (S3 deferred); `/payloads/{id}/image` returns `capability_unavailable` by design.
- Run all backend commands from `backend/` with the project venv (`uv run ...`).

---

### Task 1: Vendor the read-side package with import rewrite and shims

**Files:**
- Create: `backend/audit/__init__.py` (minimal)
- Create (copy): `backend/audit/http_api/*`, `backend/audit/read_service.py`, `read_repositories.py`, `read_adapters.py`, `read_cursor.py`, `read_contracts.py`, `contracts.py`, `registration.py`, `validation.py`, `engine_contracts.py`, `image_safety.py`, `postgres_connections.py`
- Create: `backend/audit/_vendor/__init__.py`, `backend/audit/_vendor/run_status.py`, `backend/audit/_vendor/redaction.py`, `backend/audit/_vendor/storage_contracts.py`
- Test: `backend/tests/test_audit_import.py`

**Interfaces:**
- Produces: importable package `audit.http_api.routes.create_audit_router`, `audit.http_api.factory.create_audit_app`, `audit.read_service.AuditReadService`, `audit.read_repositories.PostgresAuditReadRepository`, `audit.read_adapters.{PostgresRegisteredTableReader,CurrentSourceObjectReader}`, `audit.read_cursor.CursorCodec`, `audit._vendor.run_status.RunStatus`.

- [ ] **Step 1: Copy the read-side files verbatim**

```bash
cd /Users/stamplevskiyd/development/lore/backend
SRC=/Users/stamplevskiyd/adventum/agent-lore/lore-core/airflow-providers/apache-airflow-providers-lore/airflow/providers/lore/audit
mkdir -p audit/http_api audit/_vendor
cp "$SRC"/http_api/{__init__,contracts,errors,factory,limits,middleware,routes}.py audit/http_api/
cp "$SRC"/{read_service,read_repositories,read_adapters,read_cursor,read_contracts,contracts,registration,validation,engine_contracts,image_safety,postgres_connections}.py audit/
```

- [ ] **Step 2: Create the vendor shims**

`backend/audit/_vendor/__init__.py`:
```python
```

`backend/audit/_vendor/run_status.py`:
```python
from __future__ import annotations

from enum import StrEnum


class RunStatus(StrEnum):
    ACTIVE = "active"
    SUCCESS = "success"
    SKIPPED = "skipped"
    FAILED = "failed"
    STALE = "stale"
```

`backend/audit/_vendor/redaction.py` (copied verbatim from `SRC/../splitter/per_file.py` lines 33-121):
```python
from __future__ import annotations

import re
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

_SECRET_KEY = re.compile(
    r"(token|secret|password|passwd|credential|authorization|api[_-]?key|dsn|signature|signed[_-]?url)",
    re.I,
)
_DSN = re.compile(r"(?:postgres(?:ql)?|mysql|redis)://[^\s]+", re.I)
_BEARER = re.compile(r"\bBearer\s+[A-Za-z0-9._~+/=-]+", re.I)
_HTTP_URL = re.compile(r"https?://[^\s<>'\"]{1,2048}", re.I)


def _redact_url(value: str) -> str:
    parts = urlsplit(value)
    if parts.scheme and parts.netloc:
        _, at, host = parts.netloc.rpartition("@")
        netloc = host if at else parts.netloc
        query = [
            (key, "[redacted]")
            if _SECRET_KEY.search(key)
            or key.lower() in {"x-amz-signature", "sig", "signature", "token"}
            else (key, item)
            for key, item in parse_qsl(parts.query, keep_blank_values=True)
        ]
        value = urlunsplit(
            (parts.scheme, netloc, parts.path, urlencode(query), parts.fragment)
        )
    return value


def redact_text(value: str) -> str:
    value = _DSN.sub("[redacted-dsn]", value)
    value = _BEARER.sub("[redacted-token]", value)
    value = _HTTP_URL.sub(lambda match: _redact_url(match.group(0)), value)
    return _redact_url(value)


def redact_value(value: Any) -> Any:
    if isinstance(value, str):
        return redact_text(value)
    if isinstance(value, dict):
        return {
            key: "[redacted]" if _SECRET_KEY.search(str(key)) else redact_value(item)
            for key, item in value.items()
            if not _SECRET_KEY.search(str(key)) or item is None
        }
    if isinstance(value, list):
        return [redact_value(item) for item in value]
    return value
```

`backend/audit/_vendor/storage_contracts.py` — copy the whole self-contained file (stdlib-only imports):
```bash
cp /Users/stamplevskiyd/adventum/agent-lore/lore-core/airflow-providers/apache-airflow-providers-lore/airflow/providers/lore/splitter/storage/contracts.py audit/_vendor/storage_contracts.py
```

- [ ] **Step 3: Rewrite imports across the copied tree**

Rewrite the audit package prefix, then repoint the three splitter symbols to the shims:
```bash
cd /Users/stamplevskiyd/development/lore/backend
# 1) audit package prefix
grep -rl 'airflow.providers.lore.audit' audit | xargs sed -i '' 's/airflow\.providers\.lore\.audit/audit/g'
# 2) RunStatus (read_repositories, read_contracts, contracts)
grep -rl 'from airflow.providers.lore.splitter.per_file import RunStatus' audit \
  | xargs sed -i '' 's/from airflow\.providers\.lore\.splitter\.per_file import RunStatus/from audit._vendor.run_status import RunStatus/g'
# 3) redact_value (validation.py)
grep -rl 'from airflow.providers.lore.splitter.per_file import redact_value' audit \
  | xargs sed -i '' 's/from airflow\.providers\.lore\.splitter\.per_file import redact_value/from audit._vendor.redaction import redact_value/g'
# 4) storage contracts (registration.py)
grep -rl 'from airflow.providers.lore.splitter.storage.contracts import' audit \
  | xargs sed -i '' 's/from airflow\.providers\.lore\.splitter\.storage\.contracts import/from audit._vendor.storage_contracts import/g'
```

- [ ] **Step 4: Write the minimal package `__init__` and verify no external imports remain**

`backend/audit/__init__.py`:
```python
"""Vendored read-only audit HTTP API (from apache-airflow-providers-lore)."""
```

Run: `cd backend && grep -rnE 'airflow|splitter' audit`
Expected: no output (empty). If any line prints, repoint it to a shim before proceeding.

- [ ] **Step 5: Write the import smoke test**

`backend/tests/test_audit_import.py`:
```python
def test_audit_package_imports_without_airflow():
    import audit.http_api.routes
    import audit.http_api.factory
    import audit.read_service
    import audit.read_repositories
    import audit.read_adapters
    import audit.read_cursor
    from audit._vendor.run_status import RunStatus

    assert RunStatus.SUCCESS == "success"
    assert hasattr(audit.http_api.routes, "create_audit_router")
    assert hasattr(audit.read_service, "AuditReadService")
```

- [ ] **Step 6: Run the import test**

Run: `cd backend && uv run pytest tests/test_audit_import.py -v`
Expected: PASS. (If `ModuleNotFoundError: airflow`, a rewrite was missed — fix and rerun.)

- [ ] **Step 7: Port and run the DB-independent unit tests**

```bash
cd /Users/stamplevskiyd/development/lore/backend
SRC=/Users/stamplevskiyd/adventum/agent-lore/lore-core/airflow-providers/apache-airflow-providers-lore/airflow/providers/lore/audit
cp "$SRC"/tests/test_audit_http_contracts.py tests/test_audit_http_contracts.py
sed -i '' 's/airflow\.providers\.lore\.audit/audit/g' tests/test_audit_http_contracts.py
```

Run: `cd backend && uv run pytest tests/test_audit_http_contracts.py -v`
Expected: PASS (contracts tests need no DB). Fix any residual import lines the same way.

- [ ] **Step 8: Register the package for tooling**

Modify `backend/pyproject.toml` — add `"audit"` to `[tool.setuptools] packages`:
```toml
packages = ["agents", "toast", "evals", "audit"]
```

- [ ] **Step 9: Commit**

```bash
cd /Users/stamplevskiyd/development/lore
git add backend/audit backend/tests/test_audit_import.py backend/tests/test_audit_http_contracts.py backend/pyproject.toml
git commit -m "feat(audit): vendor read-only audit HTTP API into backend/audit"
```

---

### Task 2: Add audit dependency and configuration

**Files:**
- Modify: `backend/pyproject.toml` (dependencies)
- Modify: `backend/config.py` (Settings fields + `audit_db_dsn` property)
- Test: `backend/tests/test_audit_config.py`

**Interfaces:**
- Consumes: `config.get_settings()`, existing `build_dsn(...)`, `toast_db_*` fields.
- Produces: `Settings.audit_cursor_key: str`, `Settings.audit_db_dsn -> str | None`, `Settings.audit_manifest_target_cap: int`; property returns a psycopg-style DSN string.

- [ ] **Step 1: Add the runtime dependency**

Modify `backend/pyproject.toml` `[project] dependencies` — add:
```toml
    "psycopg[binary,pool]==3.3.4",
```
Then: `cd backend && uv sync`
Expected: lock updates, psycopg installed.

- [ ] **Step 2: Write the failing config test**

`backend/tests/test_audit_config.py`:
```python
import importlib

import config as config_module


def _settings(monkeypatch, **env):
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    importlib.reload(config_module)
    config_module.get_settings.cache_clear()
    return config_module.get_settings()


def test_audit_dsn_falls_back_to_toast(monkeypatch):
    s = _settings(
        monkeypatch,
        CHAINLIT_JWT_SECRET="x", CHAINLIT_JWT_AUDIENCE="a", CHAINLIT_JWT_ISSUER="i",
        AUDIT_CURSOR_KEY="0123456789abcdef",
        TOAST_DB_HOST="db", TOAST_DB_USER="u", TOAST_DB_PASSWORD="p", TOAST_DB_NAME="lore",
    )
    assert s.audit_cursor_key == "0123456789abcdef"
    assert s.audit_db_dsn == "postgresql://u:p@db:5432/lore"


def test_audit_dsn_none_without_db(monkeypatch):
    s = _settings(
        monkeypatch,
        CHAINLIT_JWT_SECRET="x", CHAINLIT_JWT_AUDIENCE="a", CHAINLIT_JWT_ISSUER="i",
        AUDIT_CURSOR_KEY="0123456789abcdef",
    )
    assert s.audit_db_dsn is None
```

- [ ] **Step 2b: Run it to confirm it fails**

Run: `cd backend && uv run pytest tests/test_audit_config.py -v`
Expected: FAIL (`AttributeError: audit_cursor_key`).

- [ ] **Step 3: Add the config fields**

Modify `backend/config.py` — inside `Settings`, after the Toast block:
```python
    # --- Audit read API (FileViewer) ---
    audit_cursor_key: str | None = Field(
        default=None, validation_alias="AUDIT_CURSOR_KEY"
    )
    audit_manifest_target_cap: int = Field(
        default=100, validation_alias="AUDIT_MANIFEST_TARGET_CAP"
    )
    # AUDIT_DB_* override the shared Toast instance when the audit DB differs.
    audit_db_host: str | None = Field(default=None, validation_alias="AUDIT_DB_HOST")
    audit_db_port: int | None = Field(default=None, validation_alias="AUDIT_DB_PORT")
    audit_db_user: str | None = Field(default=None, validation_alias="AUDIT_DB_USER")
    audit_db_password: str | None = Field(
        default=None, validation_alias="AUDIT_DB_PASSWORD"
    )
    audit_db_name: str | None = Field(default=None, validation_alias="AUDIT_DB_NAME")
```

Add a property (near `toast_dsn`):
```python
    @property
    def audit_db_dsn(self) -> str | None:
        """psycopg DSN for the lore_core schema. Falls back to the Toast instance."""
        host = self.audit_db_host or self.toast_db_host
        user = self.audit_db_user or self.toast_db_user
        password = self.audit_db_password or self.toast_db_password
        name = self.audit_db_name or self.toast_db_name
        if not (host and user and password and name):
            return None
        port = self.audit_db_port or self.toast_db_port
        return build_dsn("postgresql", user, password, host, port, name)
```

- [ ] **Step 4: Run the config test**

Run: `cd backend && uv run pytest tests/test_audit_config.py -v`
Expected: PASS.

- [ ] **Step 5: Document env in `.env.example`**

Append to `.env.example`:
```
# --- Audit read API (FileViewer) ---
AUDIT_CURSOR_KEY=change-me-min-16-bytes-stable
# AUDIT_DB_* optional: default to TOAST_DB_* (same instance, schema lore_core)
# AUDIT_DB_HOST=
# AUDIT_DB_NAME=
```

- [ ] **Step 6: Commit**

```bash
cd /Users/stamplevskiyd/development/lore
git add backend/pyproject.toml backend/uv.lock backend/config.py .env.example
git commit -m "feat(audit): add psycopg dep and AUDIT_* configuration"
```

---

### Task 3: PgBouncer-safe psycopg pool with `.acquire()` adapter

**Files:**
- Create: `backend/audit/pool.py`
- Test: `backend/tests/test_audit_pool.py`

**Interfaces:**
- Consumes: `psycopg_pool.ConnectionPool`.
- Produces: `build_audit_pool(dsn: str) -> AuditConnectionPool`; `AuditConnectionPool.acquire()` returns a context manager yielding a psycopg connection with `prepare_threshold=None`; `AuditConnectionPool.close() -> None`. Shape matches `audit.postgres_connections.acquire_postgres_connection` (duck-typed `.acquire()`).

- [ ] **Step 1: Write the failing test**

`backend/tests/test_audit_pool.py`:
```python
from audit.pool import AuditConnectionPool


class _FakeCtx:
    def __init__(self, conn): self._conn = conn
    def __enter__(self): return self._conn
    def __exit__(self, *a): return False


class _FakePool:
    def __init__(self): self.closed = False
    def connection(self): return _FakeCtx("CONN")
    def close(self): self.closed = True


def test_acquire_yields_connection_from_pool():
    pool = AuditConnectionPool(_FakePool())
    with pool.acquire() as conn:
        assert conn == "CONN"


def test_close_delegates_to_pool():
    fake = _FakePool()
    AuditConnectionPool(fake).close()
    assert fake.closed is True
```

- [ ] **Step 2: Run it to confirm it fails**

Run: `cd backend && uv run pytest tests/test_audit_pool.py -v`
Expected: FAIL (`ModuleNotFoundError: audit.pool`).

- [ ] **Step 3: Implement `pool.py`**

`backend/audit/pool.py`:
```python
"""PgBouncer-safe psycopg connection pool for audit reads."""

from __future__ import annotations

from typing import Any

from psycopg_pool import ConnectionPool


class AuditConnectionPool:
    """Wrap a psycopg pool to expose the `.acquire()` shape the readers expect."""

    def __init__(self, pool: Any) -> None:
        self._pool = pool

    def acquire(self) -> Any:
        # psycopg's `.connection()` is a context manager yielding a live connection.
        return self._pool.connection()

    def close(self) -> None:
        self._pool.close()


def build_audit_pool(dsn: str, *, max_size: int = 8) -> AuditConnectionPool:
    """Build a psycopg pool with prepared statements disabled (PgBouncer txn pooling)."""
    pool = ConnectionPool(
        conninfo=dsn,
        max_size=max_size,
        open=True,
        # prepare_threshold=None disables server-side prepared statements, which
        # PgBouncer in transaction-pooling mode cannot support.
        kwargs={"prepare_threshold": None, "autocommit": False},
    )
    return AuditConnectionPool(pool)
```

- [ ] **Step 4: Run the test**

Run: `cd backend && uv run pytest tests/test_audit_pool.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
cd /Users/stamplevskiyd/development/lore
git add backend/audit/pool.py backend/tests/test_audit_pool.py
git commit -m "feat(audit): PgBouncer-safe psycopg pool with acquire adapter"
```

---

### Task 4: Auth dependency reusing `verify_ticket`

**Files:**
- Create: `backend/audit/auth_dep.py`
- Test: `backend/tests/test_audit_auth_dep.py`

**Interfaces:**
- Consumes: `auth.verify_ticket(token) -> dict[str, str]` (raises `jwt.InvalidTokenError`).
- Produces: `require_audit_identity(authorization: str | None) -> dict[str, str]`; raises `fastapi.HTTPException(401)` on missing/invalid token.

- [ ] **Step 1: Write the failing test**

`backend/tests/test_audit_auth_dep.py`:
```python
import jwt
import pytest
from fastapi import HTTPException

from audit.auth_dep import require_audit_identity


def test_missing_header_raises_401():
    with pytest.raises(HTTPException) as exc:
        require_audit_identity(None)
    assert exc.value.status_code == 401


def test_invalid_token_raises_401(monkeypatch):
    def _boom(_token): raise jwt.InvalidTokenError("bad")
    monkeypatch.setattr("audit.auth_dep.verify_ticket", _boom)
    with pytest.raises(HTTPException) as exc:
        require_audit_identity("Bearer nope")
    assert exc.value.status_code == 401


def test_valid_token_returns_identity(monkeypatch):
    monkeypatch.setattr(
        "audit.auth_dep.verify_ticket", lambda t: {"sub": "u1", "username": "u1"}
    )
    assert require_audit_identity("Bearer good") == {"sub": "u1", "username": "u1"}
```

- [ ] **Step 2: Run it to confirm it fails**

Run: `cd backend && uv run pytest tests/test_audit_auth_dep.py -v`
Expected: FAIL (`ModuleNotFoundError: audit.auth_dep`).

- [ ] **Step 3: Implement `auth_dep.py`**

`backend/audit/auth_dep.py`:
```python
"""Auth dependency for the audit router — reuses the chat's HS256 ticket."""

from __future__ import annotations

import jwt
from fastapi import Header, HTTPException

from auth import verify_ticket


def require_audit_identity(
    authorization: str | None = Header(default=None),
) -> dict[str, str]:
    """Validate the same Bearer ticket the chat frontend already carries."""
    if not authorization:
        raise HTTPException(status_code=401, detail="missing authorization")
    token = authorization.removeprefix("Bearer ").strip()
    try:
        return verify_ticket(token)
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="invalid token") from None
```

- [ ] **Step 4: Run the test**

Run: `cd backend && uv run pytest tests/test_audit_auth_dep.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
cd /Users/stamplevskiyd/development/lore
git add backend/audit/auth_dep.py backend/tests/test_audit_auth_dep.py
git commit -m "feat(audit): auth dependency reusing verify_ticket"
```

---

### Task 5: Assemble the audit app (service + readers + router)

**Files:**
- Create: `backend/audit/assembly.py`
- Test: `backend/tests/test_audit_assembly.py`

**Interfaces:**
- Consumes: `config.get_settings()`, `audit.pool.build_audit_pool`, `audit.read_cursor.CursorCodec`, `audit.read_repositories.PostgresAuditReadRepository`, `audit.read_adapters.PostgresRegisteredTableReader`, `audit.read_service.AuditReadService`, `audit.http_api.routes.create_audit_router`, `audit.http_api.limits.AuditHttpLimits`.
- Produces: `build_audit_service(settings) -> tuple[AuditReadService, AuditConnectionPool] | None` (None when `audit_db_dsn`/`audit_cursor_key` absent); `build_audit_router(settings)` returning a mounted `APIRouter` or `None`.

- [ ] **Step 1: Write the failing test**

`backend/tests/test_audit_assembly.py`:
```python
from audit.assembly import build_audit_service


class _S:
    audit_db_dsn = None
    audit_cursor_key = None
    audit_manifest_target_cap = 100


def test_service_is_none_without_db_or_key():
    assert build_audit_service(_S()) is None
```

- [ ] **Step 2: Run it to confirm it fails**

Run: `cd backend && uv run pytest tests/test_audit_assembly.py -v`
Expected: FAIL (`ModuleNotFoundError: audit.assembly`).

- [ ] **Step 3: Implement `assembly.py`**

`backend/audit/assembly.py`:
```python
"""Wire config into a mounted audit read router. Image reader deferred (no S3)."""

from __future__ import annotations

from typing import Any

from audit.http_api.limits import AuditHttpLimits
from audit.http_api.routes import create_audit_router
from audit.pool import AuditConnectionPool, build_audit_pool
from audit.read_adapters import PostgresRegisteredTableReader
from audit.read_cursor import CursorCodec
from audit.read_repositories import PostgresAuditReadRepository
from audit.read_service import AuditReadService


def build_audit_service(settings: Any) -> tuple[AuditReadService, AuditConnectionPool] | None:
    """Return (service, pool) or None when the audit DB/cursor key is not configured."""
    dsn = settings.audit_db_dsn
    key = settings.audit_cursor_key
    if not dsn or not key:
        return None
    pool = build_audit_pool(dsn)
    codec = CursorCodec(key.encode("utf-8"))
    repository = PostgresAuditReadRepository(pool, codec)
    service = AuditReadService(
        repository,
        manifest_target_cap=settings.audit_manifest_target_cap,
        table_reader=PostgresRegisteredTableReader(pool, codec),
        # image_reader deferred to the S3 phase; source_reader deferred until a
        # source object loader is available. Both capabilities degrade gracefully.
    )
    return service, pool


def build_audit_router(settings: Any):
    """Return a mounted audit router, or None when audit is not configured."""
    built = build_audit_service(settings)
    if built is None:
        return None
    service, _pool = built
    return create_audit_router(service, AuditHttpLimits())
```

- [ ] **Step 4: Run the test**

Run: `cd backend && uv run pytest tests/test_audit_assembly.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
cd /Users/stamplevskiyd/development/lore
git add backend/audit/assembly.py backend/tests/test_audit_assembly.py
git commit -m "feat(audit): assemble service + readers + router from config"
```

---

### Task 6: Mount the router on the Chainlit app with auth and safe errors

**Files:**
- Modify: `backend/app.py` (mount block near module top-level, after imports)
- Test: `backend/tests/test_audit_mount.py`

**Interfaces:**
- Consumes: `chainlit.server.app`, `audit.assembly.build_audit_router`, `audit.auth_dep.require_audit_identity`, `audit.http_api.errors.install_safe_error_handlers`, `audit.http_api.middleware.AuditHttpMiddleware`.
- Produces: side effect — the audit router is attached to the Chainlit FastAPI app under `/api/v1/audit`, guarded by `require_audit_identity`, when audit is configured.

- [ ] **Step 1: Write the failing test (stubbed service via TestClient)**

`backend/tests/test_audit_mount.py`:
```python
from fastapi import FastAPI
from fastapi.testclient import TestClient

from audit.auth_dep import require_audit_identity
from audit.mount import attach_audit_router


class _StubRouter:
    """Minimal object create_audit_router would return: exercise auth + a route."""


def test_mount_guards_with_auth(monkeypatch):
    app = FastAPI()

    # Build a tiny router that echoes identity, mounted the same way app.py does.
    from fastapi import APIRouter, Depends

    router = APIRouter(prefix="/api/v1/audit")

    @router.get("/ping")
    def ping():
        return {"ok": True}

    monkeypatch.setattr("audit.mount.build_audit_router", lambda s: router)
    monkeypatch.setattr(
        "audit.mount.get_settings", lambda: object()
    )
    monkeypatch.setattr(
        "audit.auth_dep.verify_ticket", lambda t: {"sub": "u", "username": "u"}
    )
    attach_audit_router(app)
    client = TestClient(app)

    assert client.get("/api/v1/audit/ping").status_code == 401
    ok = client.get("/api/v1/audit/ping", headers={"Authorization": "Bearer good"})
    assert ok.status_code == 200 and ok.json() == {"ok": True}


def test_mount_noop_when_unconfigured(monkeypatch):
    app = FastAPI()
    monkeypatch.setattr("audit.mount.build_audit_router", lambda s: None)
    monkeypatch.setattr("audit.mount.get_settings", lambda: object())
    attach_audit_router(app)  # must not raise
    assert TestClient(app).get("/api/v1/audit/ping").status_code == 404
```

- [ ] **Step 2: Run it to confirm it fails**

Run: `cd backend && uv run pytest tests/test_audit_mount.py -v`
Expected: FAIL (`ModuleNotFoundError: audit.mount`).

- [ ] **Step 3: Implement `audit/mount.py`**

`backend/audit/mount.py`:
```python
"""Attach the audit router to a FastAPI app with auth, middleware and safe errors."""

from __future__ import annotations

from fastapi import Depends, FastAPI

from audit.assembly import build_audit_router
from audit.auth_dep import require_audit_identity
from audit.http_api.errors import install_safe_error_handlers
from audit.http_api.middleware import AuditHttpMiddleware
from config import get_settings


def attach_audit_router(app: FastAPI) -> bool:
    """Mount /api/v1/audit if configured. Returns True when attached."""
    router = build_audit_router(get_settings())
    if router is None:
        return False
    app.include_router(router, dependencies=[Depends(require_audit_identity)])
    install_safe_error_handlers(app)
    app.add_middleware(AuditHttpMiddleware)
    return True
```

- [ ] **Step 4: Run the test**

Run: `cd backend && uv run pytest tests/test_audit_mount.py -v`
Expected: PASS.

- [ ] **Step 5: Wire it into the real app**

Modify `backend/app.py` — after the imports and `get_settings` import, add:
```python
from chainlit.server import app as _chainlit_app
from audit.mount import attach_audit_router

# Mount the read-only audit API (/api/v1/audit) on the Chainlit FastAPI app when
# AUDIT_* is configured. No-op otherwise, so the chat runs unchanged.
attach_audit_router(_chainlit_app)
```

- [ ] **Step 6: Verify the app still imports**

Run: `cd backend && uv run python -c "import app"`
Expected: no error (audit unconfigured in a bare shell → mount is a no-op).

- [ ] **Step 7: Commit**

```bash
cd /Users/stamplevskiyd/development/lore
git add backend/audit/mount.py backend/tests/test_audit_mount.py backend/app.py
git commit -m "feat(audit): mount audit router on Chainlit app with auth guard"
```

---

### Task 7: Port DB-backed audit tests and add a PgBouncer integration check

**Files:**
- Create (copy): `backend/tests/test_audit_http_routes.py`, `test_audit_http_security.py`, `test_audit_http_integration.py`
- Create: `backend/tests/test_audit_pgbouncer_integration.py` (opt-in, real DB)
- Modify: `backend/tests/conftest.py` (only if fixtures need path adaptation)

**Interfaces:**
- Consumes: everything above; the vendored tests use `create_audit_app`/`create_audit_router` and in-memory/fake repositories.

- [ ] **Step 1: Copy and re-point the vendored HTTP tests**

```bash
cd /Users/stamplevskiyd/development/lore/backend
SRC=/Users/stamplevskiyd/adventum/agent-lore/lore-core/airflow-providers/apache-airflow-providers-lore/airflow/providers/lore/audit
for t in routes security integration; do
  cp "$SRC/tests/test_audit_http_$t.py" "tests/test_audit_http_$t.py"
  sed -i '' 's/airflow\.providers\.lore\.audit/audit/g' "tests/test_audit_http_$t.py"
done
```

- [ ] **Step 2: Run them; fix residual imports**

Run: `cd backend && uv run pytest tests/test_audit_http_routes.py tests/test_audit_http_security.py tests/test_audit_http_integration.py -v`
Expected: PASS. If a test imports a not-copied symbol (e.g. from `runtime`/`splitter`), adapt the import to the vendored equivalent or skip that single test with a `pytest.mark.skip("airflow-only")` and a one-line reason.

- [ ] **Step 3: Write the opt-in PgBouncer integration test**

`backend/tests/test_audit_pgbouncer_integration.py`:
```python
import os

import pytest

from audit.pool import build_audit_pool

DSN = os.environ.get("AUDIT_TEST_DSN")


@pytest.mark.skipif(not DSN, reason="set AUDIT_TEST_DSN to run against real lore_core")
def test_repeatable_read_txn_survives_pgbouncer():
    pool = build_audit_pool(DSN)
    try:
        with pool.acquire() as conn:
            with conn.cursor() as cur:
                cur.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
                cur.execute("SELECT count(*) FROM lore_core.processed_files")
                assert cur.fetchone()[0] >= 0
    finally:
        pool.close()
```

- [ ] **Step 4: Run the full audit suite (unit portion)**

Run: `cd backend && uv run pytest tests/ -k audit -v`
Expected: PASS (integration test SKIPPED without `AUDIT_TEST_DSN`).

- [ ] **Step 5: Manually run the integration test against the real DB (record result)**

Run (with real creds): `cd backend && AUDIT_TEST_DSN="postgresql://user:pass@host:port/db" uv run pytest tests/test_audit_pgbouncer_integration.py -v`
Expected: PASS. If it fails with a prepared-statement error, confirm `prepare_threshold=None` reached the connection (Task 3) before proceeding.

- [ ] **Step 6: Commit**

```bash
cd /Users/stamplevskiyd/development/lore
git add backend/tests/test_audit_http_routes.py backend/tests/test_audit_http_security.py backend/tests/test_audit_http_integration.py backend/tests/test_audit_pgbouncer_integration.py
git commit -m "test(audit): port HTTP tests and add PgBouncer integration check"
```

---

## Deferred (follow-on plans, out of scope here)

- **S3 images:** `boto3` image reader implementing `RegisteredImageReader`, `AUDIT_S3_*` config, MinIO compose service, wire `image_reader` into `build_audit_service`. Until then `/payloads/{id}/image` → `capability_unavailable` (by design).
- **source-context loader:** provide `CurrentSourceObjectReader(loader)` when a source-object loader exists; until then source-context → `capability_unavailable`.
- **Richer `/files` facets:** counts/filters/sorts from frontend spec §4.1 that the real `FileCard`/`FileListQuery` do not provide — extends vendored SQL/DTO.
- **React `/files` module** per `docs/lore-file-viewer-frontend-spec.md`.

## Self-Review Notes

- **Spec coverage:** §4.1 vendoring → Task 1; §4.3 pool/PgBouncer → Task 3 + Task 7; §4.4 table/source readers → Task 5 (image deferred, per spec §4.4/§10); §4.5 auth → Task 4 + Task 6; §4.6 config/cursor/limits/middleware/errors → Task 2 + Task 6; §8 testing → Task 1 (contracts), Task 7 (routes/security/integration/PgBouncer). Image/S3 (§9 phase 3), source-context, richer facets (§7.2) explicitly deferred.
- **Type consistency:** `build_audit_service -> tuple[service, pool] | None` and `build_audit_router -> router | None` used consistently across Tasks 5–6; `AuditConnectionPool.acquire()`/`.close()` consistent Tasks 3–5–7; `require_audit_identity` signature consistent Tasks 4–6.
- **Constructors verified against source:** `create_audit_router(service, limits)` (prefix built-in), `AuditReadService(repository, *, manifest_target_cap, table_reader, image_reader, source_reader)`, `PostgresAuditReadRepository(connection, cursor_codec, *, statement_timeout_ms)`, `PostgresRegisteredTableReader(connection, cursor_codec)`, `CursorCodec(key: bytes)`.
