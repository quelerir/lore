# Phase 4 — Final Cleanup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Finish the merge — remove the transitional re-export shims, clear lint, tidy git/docs hygiene, and add a regression guard for the packages' dependency-purity invariant.

**Architecture:** Mechanical import repointing + shim deletion, then targeted lint/hygiene/doc fixes, then a new subprocess-based purity test per pure package. No functional change.

**Tech Stack:** Python 3.13, uv workspace, pytest, ruff.

## Global Constraints

- Repo root: `/Users/stamplevskiyd/development/lore`. Workspace root: `lore-core/`.
- Test commands (from `lore-core/`):
  - audit-core: `uv run --package lore-audit-core pytest packages/lore-audit-core/tests -q` (baseline **156 passed**)
  - audit-api: `uv run --package lore-audit-api pytest services/lore-audit-api/tests -q` (baseline **96 passed / 1 skipped**)
  - chat: `uv run --package datacraft-chainlit pytest services/lore-chat/tests -q` (baseline **121 passed / 1 skipped**)
  - lore-splitter: `uv run --package lore-splitter pytest packages/lore-splitter/tests -q` (baseline **284 passed**)
  - lore-core-domain: `uv run --package lore-core-domain pytest packages/lore-core-domain/tests -q`
  - ruff: `uv run --package lore-audit-core ruff check lore-core/packages lore-core/services` from repo root, OR `cd lore-core && uv run ruff check packages services`
- Nothing is broken; this phase changes NO behavior. The only public-surface change is deleting the two shim modules.
- Stage only the files each task names. Never `git add -A`. Never stage `lore-core/.chainlit/`.
- If you learn the chat pytest package name differs, discover it: `grep -n "^name" lore-core/services/lore-chat/pyproject.toml`.

---

### Task 1: Remove the re-export shims

Repoint every importer of the two shim modules to the canonical subpackages, then delete the shims. Pure module-path change — the canonical `lore_audit.read` and `lore_audit.repository` packages both define `__all__` and export every symbol the shims re-exported, so each `from ... import <names>` resolves unchanged.

**Files (repoint `lore_audit.read_contracts` → `lore_audit.read`):**
- `lore-core/packages/lore-audit-core/src/lore_audit/read_cursor.py:14`
- `lore-core/packages/lore-audit-core/src/lore_audit/repository/mapping.py:9` and `:20`
- `lore-core/packages/lore-audit-core/src/lore_audit/repository/__init__.py:18`
- `lore-core/packages/lore-audit-core/src/lore_audit/read_service.py:9`
- `lore-core/packages/lore-audit-core/src/lore_audit/read_adapters.py:14`
- `lore-core/services/lore-audit-api/src/lore_audit_api/http/limits.py:7`
- `lore-core/services/lore-audit-api/src/lore_audit_api/http/routes.py:32`
- `lore-core/services/lore-audit-api/src/lore_audit_api/http/contracts.py:22`
- `lore-core/services/lore-audit-api/src/lore_audit_api/http/errors.py:12`
- `lore-core/services/lore-audit-api/tests/test_http_security.py:15`
- `lore-core/services/lore-audit-api/tests/test_http_contracts.py:31`
- `lore-core/services/lore-audit-api/tests/test_http_routes.py:24`

**Files (repoint `lore_audit.read_repositories` → `lore_audit.repository`):**
- `lore-core/packages/lore-audit-core/src/lore_audit/read_adapters.py:36`
- `lore-core/packages/lore-audit-core/src/lore_audit/read_service.py:50`
- `lore-core/services/lore-audit-api/src/lore_audit_api/factory.py:21`
- `lore-core/services/lore-chat/tests/test_audit_import.py:5` (this line is `import lore_audit.read_repositories` — a module-name import, not a `from`)

**Delete:**
- `lore-core/packages/lore-audit-core/src/lore_audit/read_contracts.py`
- `lore-core/packages/lore-audit-core/src/lore_audit/read_repositories.py`

- [ ] **Step 1: Repoint all `from` imports**

Run this exact transform (repo root). It rewrites the two `from ... import` prefixes and the one bare-module import, across src + tests, EXCLUDING the shim files themselves:

```bash
cd /Users/stamplevskiyd/development/lore
python3 - <<'PY'
import pathlib
roots = [
    "lore-core/packages/lore-audit-core/src",
    "lore-core/services/lore-audit-api/src",
    "lore-core/services/lore-audit-api/tests",
    "lore-core/services/lore-chat/tests",
]
skip = {"read_contracts.py", "read_repositories.py"}
n = 0
for root in roots:
    for p in pathlib.Path(root).rglob("*.py"):
        if p.name in skip:
            continue
        s = p.read_text()
        o = s
        s = s.replace("from lore_audit.read_contracts import", "from lore_audit.read import")
        s = s.replace("from lore_audit.read_repositories import", "from lore_audit.repository import")
        s = s.replace("import lore_audit.read_repositories", "import lore_audit.repository")
        if s != o:
            p.write_text(s); n += 1
            print("rewrote", p)
print("files changed:", n)
PY
```
Expected: ~15 files rewritten.

- [ ] **Step 2: Delete the shim files**

```bash
cd /Users/stamplevskiyd/development/lore
git rm lore-core/packages/lore-audit-core/src/lore_audit/read_contracts.py \
       lore-core/packages/lore-audit-core/src/lore_audit/read_repositories.py
```

- [ ] **Step 3: Verify no references remain**

```bash
grep -rn "read_contracts\|read_repositories" lore-core/packages lore-core/services --include='*.py'
```
Expected: no output. (If any remains — e.g. a docstring — inspect and repoint/adjust.)

- [ ] **Step 4: Run the three affected suites**

```bash
cd /Users/stamplevskiyd/development/lore/lore-core
uv run --package lore-audit-core pytest packages/lore-audit-core/tests -q
uv run --package lore-audit-api pytest services/lore-audit-api/tests -q
uv run --package datacraft-chainlit pytest services/lore-chat/tests -q
```
Expected: 156 passed; 96 passed / 1 skipped; 121 passed / 1 skipped. A circular-import error would mean `lore_audit.read` transitively imports `lore_audit.repository` — it does not today (`read/` imports no `repository`), so this should be clean.

- [ ] **Step 5: Commit**

```bash
cd /Users/stamplevskiyd/development/lore
git add lore-core/packages/lore-audit-core lore-core/services/lore-audit-api lore-core/services/lore-chat/tests/test_audit_import.py
git commit -m "refactor(audit): drop read_contracts/read_repositories re-export shims"
```

---

### Task 2: Lint fixes

Clear the remaining ruff findings so the packages/services lint clean. Two are co-located with Task 1's repoints (now pointing at `lore_audit.read`); this task removes the unused names and fixes the import ordering.

**Files:**
- Modify: `lore-core/packages/lore-audit-core/src/lore_audit/repository/mapping.py` (drop unused `CursorCodec` at line 18, unused `AuditReadError` at line 20)
- Modify: `lore-core/services/lore-audit-api/tests/test_http_routes.py` (E402 — move the module-level import block to the top)
- Modify: `lore-core/services/lore-audit-api/tests/test_settings.py` (drop unused `import pytest`)

- [ ] **Step 1: See the current findings**

```bash
cd /Users/stamplevskiyd/development/lore/lore-core
uv run ruff check packages services 2>&1 | tail -30
```
Expected findings: `mapping.py` unused `CursorCodec` + `AuditReadError`; `test_http_routes.py` E402; `test_settings.py` unused `pytest`. (The two former `read_contracts.py` findings are gone — the file was deleted.)

- [ ] **Step 2: Fix `mapping.py` unused imports**

In `lore-core/packages/lore-audit-core/src/lore_audit/repository/mapping.py`:
- Line ~18 `from lore_audit.read_cursor import CursorCodec, TextWindowBuilder` → `from lore_audit.read_cursor import TextWindowBuilder` (drop `CursorCodec`; `read_cursor` is a real module, not a shim).
- Line ~20 `from lore_audit.read import AuditReadError, ChunkDetail, ChunkDetailRequest` → `from lore_audit.read import ChunkDetail, ChunkDetailRequest` (drop `AuditReadError`).
Verify these names are genuinely unused in the file first: `grep -n "CursorCodec\|AuditReadError" lore-core/packages/lore-audit-core/src/lore_audit/repository/mapping.py` — expect each to appear only on its import line.

- [ ] **Step 3: Fix `test_http_routes.py` E402**

Move the module-level `from lore_audit.read import (...)` block (currently after the `_app()` helper, ~line 24) up to the top import section of the file (with the other imports, before the first function/def). Only reorder — change no import contents.

- [ ] **Step 4: Fix `test_settings.py` unused import**

In `lore-core/services/lore-audit-api/tests/test_settings.py`, delete the `import pytest` line (line ~5). Confirm unused first: `grep -n "pytest" lore-core/services/lore-audit-api/tests/test_settings.py` — expect only the import line.

- [ ] **Step 5: Verify ruff clean + suites still green**

```bash
cd /Users/stamplevskiyd/development/lore/lore-core
uv run ruff check packages services
uv run --package lore-audit-core pytest packages/lore-audit-core/tests -q
uv run --package lore-audit-api pytest services/lore-audit-api/tests -q
```
Expected: `All checks passed!`; 156 passed; 96 passed / 1 skipped.

- [ ] **Step 6: Commit**

```bash
cd /Users/stamplevskiyd/development/lore
git add lore-core/packages/lore-audit-core/src/lore_audit/repository/mapping.py \
        lore-core/services/lore-audit-api/tests/test_http_routes.py \
        lore-core/services/lore-audit-api/tests/test_settings.py
git commit -m "style(audit): clear ruff findings (unused imports, import order)"
```

---

### Task 3: Git hygiene

Remove the one untracked stray and stop it (and the app-workspace stray class) from being re-committed. Note: no `.pytest_cache` is tracked; the tracked `.chainlit/` dirs at repo root and `services/lore-chat/` are intentional Chainlit runtime config — leave them.

**Files:**
- Delete (filesystem, untracked): `lore-core/.chainlit/`
- Modify: `.gitignore`

- [ ] **Step 1: Remove the untracked stray**

```bash
cd /Users/stamplevskiyd/development/lore
rm -rf lore-core/.chainlit
```

- [ ] **Step 2: Fix the stale ignore + add the stray path**

In the repo-root `.gitignore`: the line `backend/.chainlit/translations/` references the pre-merge `backend/` dir that no longer exists. Replace that single line with an entry for the stray location that Chainlit creates when run from the workspace root:

```
lore-core/.chainlit/
```
(Leave the existing `__pycache__/`, `.venv/`, `.pytest_cache/` lines as-is.)

- [ ] **Step 3: Verify status clean**

```bash
cd /Users/stamplevskiyd/development/lore
git status --short | grep -iE "chainlit|pytest_cache"
```
Expected: no output (the stray is gone and now ignored).

- [ ] **Step 4: Commit**

```bash
cd /Users/stamplevskiyd/development/lore
git add .gitignore
git commit -m "chore: ignore workspace-root .chainlit stray; drop stale backend ignore"
```

---

### Task 4: Docs sweep

Mark the one superseded plan doc; the current docs (`README`, `lore-core/README.md`, `architecture.md`) were verified accurate and `docs/deployment.md`/`docs/usage.md` carry no stale `backend/` paths.

**Files:**
- Modify: `docs/superpowers/plans/2026-07-20-fileviewer-integration.md`

- [ ] **Step 1: Add a superseded banner**

Insert at the very top of `docs/superpowers/plans/2026-07-20-fileviewer-integration.md` (before its first line):

```markdown
> **⚠️ SUPERSEDED (2026-07-21).** This plan described integrating the audit read
> API by vendoring a copy into `backend/audit/`. That approach was abandoned during
> the lore↔agent-lore merge. The audit API now lives in the `lore-audit-core` /
> `lore-audit-api` packages and is mounted into chat via
> `lore-core/services/lore-chat/audit_mount.py` + `audit_auth.py`. Kept for history only.

```

- [ ] **Step 2: Confirm no other stale `backend/` path in swept docs**

```bash
grep -rn "backend/" docs/deployment.md docs/usage.md 2>/dev/null; echo "exit $?"
```
Expected: exit 1 (no matches).

- [ ] **Step 3: Commit**

```bash
cd /Users/stamplevskiyd/development/lore
git add docs/superpowers/plans/2026-07-20-fileviewer-integration.md
git commit -m "docs: mark superseded fileviewer-integration plan"
```

---

### Task 5: Purity regression guard

Add a subprocess-based test per pure package asserting it imports none of the forbidden dependencies. Each test spawns a fresh interpreter, imports every submodule of the package, and checks `sys.modules` — so it fails loudly if any future edit re-couples a pure package. Denylist (not allowlist) avoids false positives from interpreter startup imports.

**Files:**
- Create: `lore-core/packages/lore-core-domain/tests/test_purity.py`
- Create: `lore-core/packages/lore-audit-core/tests/test_purity.py`
- Create: `lore-core/packages/lore-splitter/tests/test_purity.py`

**Interfaces:** none consumed; each test is self-contained (stdlib `subprocess`/`sys`).

- [ ] **Step 1: Domain purity test (stdlib-only + no siblings/third-party)**

Create `lore-core/packages/lore-core-domain/tests/test_purity.py`:

```python
"""Guard: lore_core_domain stays stdlib-only (the merge's base-layer invariant)."""

from __future__ import annotations

import subprocess
import sys

# lore_core_domain must not pull ANY third-party or sibling package.
FORBIDDEN = [
    "airflow", "fastapi", "pydantic", "chainlit", "psycopg", "markitdown",
    "openpyxl", "PIL", "fitz", "docx", "pptx", "defusedxml", "yaml",
    "lore_audit", "lore_splitter", "lore_audit_api",
]

_SCRIPT = """
import importlib, pkgutil, sys
import lore_core_domain
for m in pkgutil.walk_packages(lore_core_domain.__path__, "lore_core_domain."):
    importlib.import_module(m.name)
forbidden = set(%r)
loaded = {name.split(".")[0] for name in sys.modules}
bad = sorted(forbidden & loaded)
assert not bad, "lore_core_domain pulled forbidden imports: " + repr(bad)
"""


def test_lore_core_domain_imports_no_forbidden_dependencies():
    result = subprocess.run(
        [sys.executable, "-c", _SCRIPT % FORBIDDEN],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
```

- [ ] **Step 2: Run it**

```bash
cd /Users/stamplevskiyd/development/lore/lore-core
uv run --package lore-core-domain pytest packages/lore-core-domain/tests/test_purity.py -q
```
Expected: 1 passed.

- [ ] **Step 3: Audit-core purity test**

Create `lore-core/packages/lore-audit-core/tests/test_purity.py` (audit legitimately uses psycopg, so it is NOT forbidden; airflow/web stack IS):

```python
"""Guard: lore_audit imports no Airflow / web-stack dependencies."""

from __future__ import annotations

import subprocess
import sys

FORBIDDEN = ["airflow", "fastapi", "pydantic", "chainlit", "lore_splitter"]

_SCRIPT = """
import importlib, pkgutil, sys
import lore_audit
for m in pkgutil.walk_packages(lore_audit.__path__, "lore_audit."):
    importlib.import_module(m.name)
forbidden = set(%r)
loaded = {name.split(".")[0] for name in sys.modules}
bad = sorted(forbidden & loaded)
assert not bad, "lore_audit pulled forbidden imports: " + repr(bad)
"""


def test_lore_audit_imports_no_forbidden_dependencies():
    result = subprocess.run(
        [sys.executable, "-c", _SCRIPT % FORBIDDEN],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
```

- [ ] **Step 4: Run it**

```bash
cd /Users/stamplevskiyd/development/lore/lore-core
uv run --package lore-audit-core pytest packages/lore-audit-core/tests/test_purity.py -q
```
Expected: 1 passed.

- [ ] **Step 5: Splitter purity test**

Create `lore-core/packages/lore-splitter/tests/test_purity.py` (splitter legitimately uses psycopg + doc libs + `lore_audit`; only Airflow / web stack is forbidden):

```python
"""Guard: lore_splitter imports no Airflow / web-stack dependencies."""

from __future__ import annotations

import subprocess
import sys

FORBIDDEN = ["airflow", "fastapi", "pydantic", "chainlit"]

_SCRIPT = """
import importlib, pkgutil, sys
import lore_splitter
for m in pkgutil.walk_packages(lore_splitter.__path__, "lore_splitter."):
    importlib.import_module(m.name)
forbidden = set(%r)
loaded = {name.split(".")[0] for name in sys.modules}
bad = sorted(forbidden & loaded)
assert not bad, "lore_splitter pulled forbidden imports: " + repr(bad)
"""


def test_lore_splitter_imports_no_forbidden_dependencies():
    result = subprocess.run(
        [sys.executable, "-c", _SCRIPT % FORBIDDEN],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
```

- [ ] **Step 6: Run all three + confirm the guard actually bites**

```bash
cd /Users/stamplevskiyd/development/lore/lore-core
uv run --package lore-core-domain pytest packages/lore-core-domain/tests/test_purity.py -q
uv run --package lore-audit-core pytest packages/lore-audit-core/tests/test_purity.py -q
uv run --package lore-splitter pytest packages/lore-splitter/tests/test_purity.py -q
```
Expected: each `1 passed`. Sanity-check the guard has teeth: temporarily add `FORBIDDEN = ["json"]` locally in one script and confirm it FAILS (json is always loaded), then revert — do NOT commit that change.

- [ ] **Step 7: Commit**

```bash
cd /Users/stamplevskiyd/development/lore
git add lore-core/packages/lore-core-domain/tests/test_purity.py \
        lore-core/packages/lore-audit-core/tests/test_purity.py \
        lore-core/packages/lore-splitter/tests/test_purity.py
git commit -m "test(packages): guard dependency-purity of the pure packages"
```

---

## Post-phase

The merge is fully complete: canonical import paths everywhere, lint clean, no stray artifacts, docs accurate, and the purity invariant guarded. Run the full sweep once more (audit-core 156+1, audit-api 96/1, chat 121/1, lore-splitter 284+1, lore-core-domain, provider 69/2) and update `.superpowers/sdd/progress.md` + memory `lore-agent-merge.md`. Whether to merge `lore-agent-merge` → `main` is a separate decision for the user.

## Self-Review

- **Spec coverage:** Slice 1 → Task 1 (repoint + delete shims). Slice 2 → Task 2 (5 findings; two former `read_contracts.py` findings vanish with the deletion). Slice 3 → Task 3 (stray `.chainlit`, `.gitignore`; corrected: no `.pytest_cache` is tracked, so that item is dropped as a no-op). Slice 4 → Task 4 (superseded banner; deployment/usage verified clean). Slice 5 → Task 5 (three purity tests). All success criteria mapped.
- **Placeholder scan:** none — every step is a concrete command, exact edit, or full code block.
- **Type/name consistency:** canonical targets `lore_audit.read` / `lore_audit.repository` both define `__all__` (verified) so the repoints resolve; the splitter denylist correctly omits `lore_audit`/psycopg/doc-libs (splitter depends on them); the audit denylist omits psycopg (audit uses it); domain denylist forbids all siblings + third-party. `read/` does not import `repository/`, so Task 1 introduces no cycle.
