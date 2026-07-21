# Lore↔agent-lore Merge — Phase 2a: `lore-core-domain` shared primitives package

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Create a new `lore-core-domain` package holding the shared primitives (`RunStatus`, `redaction`, `storage_contracts`) that both `lore-audit-core` and (later) `lore-splitter` depend on, and repoint `lore-audit-core`/`lore-audit-api` off their Phase-1 copies onto it.

**Architecture:** The three primitives were vendored into `lore_audit` during Phase 1. They are actually shared vocabulary between the audit read-side and the splitter write-side. Move them into a dependency-free `lore_core_domain` package that both sides import, giving a clean dependency graph with no writer→reader cycle. Two tasks: (1) create the package and move the files behind thin re-export shims so nothing breaks; (2) repoint all consumers and delete the shims.

**Tech Stack:** Python 3.13, uv workspace, stdlib only (the primitives use `enum`, `re`, `urllib`, `dataclasses`, `typing` — no third-party deps).

## Global Constraints

- Branch: `lore-agent-merge`. Python **3.13** (pinned via `lore-core/.python-version`).
- **No behavior change**: both suites stay green — `lore-audit-api` **96 passed / 1 skipped**, `lore-chat` **121 passed / 1 skipped** (trailing LangSmith/ls.local warning is expected noise).
- **`lore-core-domain` has ZERO third-party dependencies** (the three modules are pure stdlib). It must not import from `lore_audit`, `lore_audit_api`, `fastapi`, `pydantic`, `chainlit`, or `airflow`.
- The three primitive modules move **verbatim** — no logic changes.
- End state: the canonical import path is `lore_core_domain.{run_status,redaction,storage_contracts}`; no `lore_audit.{run_status,redaction,storage_contracts}` module remains.

**The 10 current consumers of the three primitives** (all must end up importing from `lore_core_domain`):
- `packages/lore-audit-core/src/lore_audit/contracts.py:11` — `from lore_audit.run_status import RunStatus`
- `packages/lore-audit-core/src/lore_audit/read/requests.py:8` — run_status
- `packages/lore-audit-core/src/lore_audit/read/responses.py:10` — run_status
- `packages/lore-audit-core/src/lore_audit/repository/__init__.py:51` — run_status
- `packages/lore-audit-core/src/lore_audit/repository/mapping.py:19` — run_status
- `packages/lore-audit-core/src/lore_audit/registration.py:17` — `from lore_audit.storage_contracts import (...)`
- `packages/lore-audit-core/src/lore_audit/validation.py:12` — `from lore_audit.redaction import redact_value`
- `services/lore-audit-api/src/lore_audit_api/http/contracts.py:39` — run_status
- `services/lore-audit-api/tests/test_http_contracts.py:39` — run_status
- `services/lore-chat/tests/test_audit_import.py:8` — run_status

---

### Task 1: Create `lore-core-domain` and move the primitives behind re-export shims

**Files:**
- Create: `lore-core/packages/lore-core-domain/pyproject.toml`
- Create: `lore-core/packages/lore-core-domain/src/lore_core_domain/__init__.py` (empty)
- Move: `lore-core/packages/lore-audit-core/src/lore_audit/{run_status,redaction,storage_contracts}.py` → `lore-core/packages/lore-core-domain/src/lore_core_domain/`
- Recreate as shims: `lore-core/packages/lore-audit-core/src/lore_audit/{run_status,redaction,storage_contracts}.py`
- Modify: `lore-core/packages/lore-audit-core/pyproject.toml` (add `lore-core-domain` dep)
- Modify: `lore-core/pyproject.toml` workspace sources (add `lore-core-domain`)

**Interfaces:**
- Consumes: the existing workspace.
- Produces: importable `lore_core_domain.run_status.RunStatus`, `lore_core_domain.redaction.redact_value`, and the `lore_core_domain.storage_contracts` types. `lore_audit.{run_status,redaction,storage_contracts}` still resolve (via shims) this task.

- [ ] **Step 1: Write `packages/lore-core-domain/pyproject.toml`**

```toml
[project]
name = "lore-core-domain"
version = "0.1.0"
requires-python = ">=3.13"
dependencies = []

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/lore_core_domain"]
```
Create `packages/lore-core-domain/src/lore_core_domain/__init__.py` (empty).

- [ ] **Step 2: Register the package as a workspace source**

In `lore-core/pyproject.toml`, add under `[tool.uv.sources]`:
```toml
lore-core-domain = { workspace = true }
```
(The `[tool.uv.workspace] members = ["packages/*", "services/*"]` glob already includes it.)

- [ ] **Step 3: git mv the three primitive modules into the new package**

```bash
cd /Users/stamplevskiyd/development/lore/lore-core
DEST=packages/lore-core-domain/src/lore_core_domain
for f in run_status redaction storage_contracts; do
  git mv "packages/lore-audit-core/src/lore_audit/$f.py" "$DEST/$f.py"
done
```

- [ ] **Step 4: Recreate thin re-export shims in `lore_audit`**

Create each of the three as a shim so existing imports keep working this task:

`packages/lore-audit-core/src/lore_audit/run_status.py`:
```python
from lore_core_domain.run_status import *  # noqa: F401,F403
from lore_core_domain.run_status import RunStatus  # noqa: F401
```
`packages/lore-audit-core/src/lore_audit/redaction.py`:
```python
from lore_core_domain.redaction import *  # noqa: F401,F403
from lore_core_domain.redaction import redact_value  # noqa: F401
```
`packages/lore-audit-core/src/lore_audit/storage_contracts.py`:
```python
from lore_core_domain.storage_contracts import *  # noqa: F401,F403
```

- [ ] **Step 5: Add the dep to `lore-audit-core`**

In `packages/lore-audit-core/pyproject.toml`, add `"lore-core-domain"` to `[project].dependencies` (keep `psycopg[binary,pool]==3.3.4`).

- [ ] **Step 6: Sync and verify both suites stay green**

Run:
```bash
cd /Users/stamplevskiyd/development/lore/lore-core
uv sync
uv run --package lore-core-domain python -c "from lore_core_domain.run_status import RunStatus; from lore_core_domain.redaction import redact_value; import lore_core_domain.storage_contracts; print('domain OK')"
uv run --package lore-audit-api pytest services/lore-audit-api/tests -q
(cd services/lore-chat && uv run pytest -q)
```
Expected: `domain OK`; lore-audit-api **96 passed, 1 skipped**; lore-chat **121 passed, 1 skipped**.

- [ ] **Step 7: Verify the new package is dependency-free**

Run:
```bash
grep -rnE "^from |^import " lore-core/packages/lore-core-domain/src | grep -vE "(__future__|enum|re$|re |typing|urllib|dataclasses|abc|types|collections)" || echo "stdlib only — OK"
```
Expected: `stdlib only — OK`.

- [ ] **Step 8: Commit**

```bash
cd /Users/stamplevskiyd/development/lore
git add -A lore-core/pyproject.toml lore-core/uv.lock lore-core/packages/lore-core-domain lore-core/packages/lore-audit-core
git commit -m "feat(domain): add lore-core-domain package, move shared primitives behind shims

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 2: Repoint all consumers onto `lore_core_domain` and delete the shims

**Files:**
- Modify (repoint imports): the 10 consumer files listed in Global Constraints
- Modify: `services/lore-audit-api/pyproject.toml` (add `lore-core-domain` direct dep — it imports it directly)
- Delete: `packages/lore-audit-core/src/lore_audit/{run_status,redaction,storage_contracts}.py` shims

**Interfaces:**
- Consumes: `lore_core_domain.*` from Task 1.
- Produces: no `lore_audit.{run_status,redaction,storage_contracts}` module anywhere; every consumer imports the primitives from `lore_core_domain`.

- [ ] **Step 1: Repoint the seven `lore-audit-core` internal imports**

In each file, replace the `lore_audit.<primitive>` import with the `lore_core_domain.<primitive>` equivalent:
- `contracts.py:11`, `read/requests.py:8`, `read/responses.py:10`, `repository/__init__.py:51`, `repository/mapping.py:19`: `from lore_audit.run_status import RunStatus` → `from lore_core_domain.run_status import RunStatus`
- `registration.py:17`: `from lore_audit.storage_contracts import (...)` → `from lore_core_domain.storage_contracts import (...)` (keep the imported names identical)
- `validation.py:12`: `from lore_audit.redaction import redact_value` → `from lore_core_domain.redaction import redact_value`

- [ ] **Step 2: Repoint the `lore-audit-api` import + its test, and add the direct dep**

- `services/lore-audit-api/src/lore_audit_api/http/contracts.py:39`: `from lore_audit.run_status import RunStatus` → `from lore_core_domain.run_status import RunStatus`
- `services/lore-audit-api/tests/test_http_contracts.py:39`: same repoint
- In `services/lore-audit-api/pyproject.toml`, add `"lore-core-domain"` to `[project].dependencies` (it now imports it directly).

- [ ] **Step 3: Repoint the chat import-smoke test**

- `services/lore-chat/tests/test_audit_import.py:8`: `from lore_audit.run_status import RunStatus` → `from lore_core_domain.run_status import RunStatus`

- [ ] **Step 4: Delete the shims**

```bash
cd /Users/stamplevskiyd/development/lore/lore-core
git rm packages/lore-audit-core/src/lore_audit/run_status.py \
       packages/lore-audit-core/src/lore_audit/redaction.py \
       packages/lore-audit-core/src/lore_audit/storage_contracts.py
```

- [ ] **Step 5: Verify no stale references remain**

```bash
cd /Users/stamplevskiyd/development/lore/lore-core
grep -rn --include="*.py" -E "lore_audit\.(run_status|redaction|storage_contracts)" packages services | grep -v "/.venv/" || echo "no stale refs — OK"
```
Expected: `no stale refs — OK`.

- [ ] **Step 6: Sync and verify both suites stay green**

```bash
cd /Users/stamplevskiyd/development/lore/lore-core
uv sync
uv run --package lore-audit-api pytest services/lore-audit-api/tests -q
(cd services/lore-chat && uv run pytest -q)
```
Expected: lore-audit-api **96 passed, 1 skipped**; lore-chat **121 passed, 1 skipped**.

- [ ] **Step 7: Commit**

```bash
cd /Users/stamplevskiyd/development/lore
git add -A
git commit -m "refactor(domain): repoint consumers onto lore_core_domain; drop lore_audit shims

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Self-Review

**Spec coverage:**
- New `lore-core-domain` package, stdlib-only, both sides depend on it — Task 1. ✓
- Repoint `lore-audit-core` + `lore-audit-api` off Phase-1 copies; delete copies — Task 2. ✓
- No behavior change; suites green — verified in both tasks. ✓
- Canonical path `lore_core_domain.*`, no `lore_audit.<primitive>` left — Task 2 Steps 4–5. ✓
- `lore-splitter` will depend on this package — out of scope here (2c/2d); the package is created ready for it.

**Placeholder scan:** none — every step has concrete file paths, code, and commands.

**Type consistency:** the primitives move verbatim, so `RunStatus`, `redact_value`, and the `storage_contracts` types keep identical signatures. The shim (Task 1) and the direct repoint (Task 2) expose the same names.

**Note:** `normalize_text` is intentionally NOT part of 2a — it has no consumer in the repo yet (it arrives with the write-side rules in 2b, which will add it to `lore_core_domain` then). Adding it now would be speculative (YAGNI).
