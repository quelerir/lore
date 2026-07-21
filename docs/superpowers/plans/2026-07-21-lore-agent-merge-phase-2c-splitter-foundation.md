# Lore↔agent-lore Merge — Phase 2c: splitter foundation → new `lore-splitter` package

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Create the `lore-splitter` package and bring in the splitter's dependency-foundation — `contracts.py`, `per_file.py`, `chunks.py` — de-Airflowed, with the primitive definitions they still hold (`RunStatus`, `redact_value`, `normalize_text`) deduplicated onto `lore-core-domain`.

**Architecture:** These three modules are the bottom layer of the splitter (content and storage sit on top of them). They are pure (stdlib only; `per_file` → `contracts` is the only intra-splitter edge; no Airflow SDK, no psycopg). They still *define* three primitives that are now canonical in `lore_core_domain` (the domain copies were sourced from exactly these files), so we remove the local definitions and import from the domain — single source of truth. Their unit tests (`test_per_file`, `test_chunks`, `test_manifest_contracts`) are the safety net proving the domain primitives behave identically.

**Tech Stack:** Python 3.13, uv workspace, `lore-core-domain`, stdlib. No third-party deps.

## Global Constraints

- Branch: `lore-agent-merge`. Python **3.13**.
- **`lore-splitter` foundation is pure**: deps are `lore-core-domain` + stdlib only. It must NOT import `fastapi`, `pydantic`, `chainlit`, `airflow*`, or `psycopg`.
- The three modules move **verbatim** EXCEPT: (1) mechanical import rewrites, and (2) the deliberate primitive deduplication described below.
- **Primitive dedup (single source of truth):**
  - `per_file.py` currently defines `class RunStatus(StrEnum)` (line ~42) and `def redact_value(...)` (line ~110). REMOVE both definitions; add `from lore_core_domain.run_status import RunStatus` and `from lore_core_domain.redaction import redact_value`.
  - `chunks.py` currently defines `def normalize_text(...)` (line ~24). REMOVE it; add `from lore_core_domain.text import normalize_text`.
  - **Before deleting each local definition, VERIFY it is behavior-identical to the domain version** (compare the enum members / function bodies against `lore_core_domain.{run_status,redaction,text}`). The domain copies were vendored from these files, so they should match. If any differs, STOP and report — a drifted primitive is a real problem, not a mechanical dedup.
  - After removing definitions, remove any now-unused imports (e.g. `from enum import StrEnum`, `import unicodedata`) — run `ruff check` to catch them.
- **Import rewrite rule:** `from airflow.providers.lore.splitter.<m> import ...` → `from lore_splitter.<m> import ...` (e.g. `per_file`'s `from airflow.providers.lore.splitter.contracts import SourceFile` → `from lore_splitter.contracts import SourceFile`).
- Existing suites stay green: `lore-audit-core` write-side **156 passed**; `lore-audit-api` **96/1**; `lore-chat` **121/1** (trailing LangSmith/ls.local warning is expected noise). These do not import the foundation, so they should be unaffected — confirm.

**Modules (from `/Users/stamplevskiyd/adventum/agent-lore/lore-core/airflow-providers/apache-airflow-providers-lore/airflow/providers/lore/splitter/`):**
`contracts.py` (231, leaf), `per_file.py` (256, → contracts), `chunks.py` (330, leaf).

**Test files (from `.../apache-airflow-providers-lore/tests/`):**
`test_per_file.py` (95), `test_chunks.py` (92), `test_manifest_contracts.py` (154) — all pure, no DB.

---

### Task 1: Create the `lore-splitter` package skeleton

**Files:**
- Create: `lore-core/packages/lore-splitter/pyproject.toml`
- Create: `lore-core/packages/lore-splitter/src/lore_splitter/__init__.py` (empty)
- Modify: `lore-core/pyproject.toml` (`[tool.uv.sources]` add `lore-splitter`)

**Interfaces:**
- Consumes: the existing workspace.
- Produces: an installable empty `lore_splitter` package that depends on `lore-core-domain`.

- [ ] **Step 1: Write `packages/lore-splitter/pyproject.toml`**

```toml
[project]
name = "lore-splitter"
version = "0.1.0"
requires-python = ">=3.13"
dependencies = ["lore-core-domain"]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/lore_splitter"]
```
Create `packages/lore-splitter/src/lore_splitter/__init__.py` (empty).

- [ ] **Step 2: Register the workspace source**

In `lore-core/pyproject.toml` under `[tool.uv.sources]`, add:
```toml
lore-splitter = { workspace = true }
```

- [ ] **Step 3: Sync and verify the empty package resolves**

```bash
cd /Users/stamplevskiyd/development/lore/lore-core
uv sync
uv run --package lore-splitter python -c "import lore_splitter; print('lore_splitter OK')"
```
Expected: sync succeeds; `lore_splitter OK`.

- [ ] **Step 4: Commit**

```bash
cd /Users/stamplevskiyd/development/lore
git add -A lore-core/pyproject.toml lore-core/uv.lock lore-core/packages/lore-splitter
git commit -m "build(splitter): scaffold empty lore-splitter package

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 2: Bring the foundation modules + tests, deduplicating primitives onto the domain

**Files:**
- Create in `lore-core/packages/lore-splitter/src/lore_splitter/`: `contracts.py`, `per_file.py`, `chunks.py`
- Create in `lore-core/packages/lore-splitter/tests/`: `test_per_file.py`, `test_chunks.py`, `test_manifest_contracts.py`

**Interfaces:**
- Consumes: `lore_core_domain.{run_status,redaction,text}`; `lore_splitter.contracts` (by `per_file`).
- Produces: `lore_splitter.contracts.{SourceFile, InputClassification, ManifestDiagnostic, RunSummary, ...}`, `lore_splitter.per_file.{ProcessingIdentity, Diagnostic, RunResult, sanitize_metadata, DEFAULT_LEASE_SECONDS, ...}` (RunStatus/redact_value re-exposed via import from domain), `lore_splitter.chunks.{Chunk, validate_chunk, ChunkCoordinates, ...}` (normalize_text re-exposed via import). These are consumed by content (2d) and storage (2e); do not change public signatures.

- [ ] **Step 1: Copy the three modules verbatim**

```bash
SRC="/Users/stamplevskiyd/adventum/agent-lore/lore-core/airflow-providers/apache-airflow-providers-lore/airflow/providers/lore/splitter"
DEST="/Users/stamplevskiyd/development/lore/lore-core/packages/lore-splitter/src/lore_splitter"
for f in contracts per_file chunks; do cp "$SRC/$f.py" "$DEST/$f.py"; done
```

- [ ] **Step 2: Rewrite the intra-splitter import in `per_file.py`**

`from airflow.providers.lore.splitter.contracts import SourceFile` → `from lore_splitter.contracts import SourceFile`. Verify none remain:
```bash
cd /Users/stamplevskiyd/development/lore/lore-core/packages/lore-splitter/src/lore_splitter
grep -rn "airflow" contracts.py per_file.py chunks.py || echo "clean"
```
Expected: `clean`.

- [ ] **Step 3: Verify the three primitives are behavior-identical to the domain, then dedup**

Compare before deleting (the domain copies were vendored from these files):
```bash
cd /Users/stamplevskiyd/development/lore
# RunStatus members:
diff <(sed -n '/class RunStatus/,/^$/p' lore-core/packages/lore-splitter/src/lore_splitter/per_file.py) \
     <(sed -n '/class RunStatus/,/^$/p' lore-core/packages/lore-core-domain/src/lore_core_domain/run_status.py)
# redact_value body:
diff <(sed -n '/def redact_value/,/^def /p' lore-core/packages/lore-splitter/src/lore_splitter/per_file.py) \
     <(sed -n '/def redact_value/,/^$/p' lore-core/packages/lore-core-domain/src/lore_core_domain/redaction.py)
# normalize_text body:
diff <(sed -n '/def normalize_text/,/^$/p' lore-core/packages/lore-splitter/src/lore_splitter/chunks.py) \
     <(sed -n '/def normalize_text/,/^$/p' lore-core/packages/lore-core-domain/src/lore_core_domain/text.py)
```
If a diff shows only formatting/adjacent-code noise but the logic matches, proceed. If the actual member list or function logic differs, STOP and report.

Then in `per_file.py`: delete the `class RunStatus(StrEnum): ...` block and the `def redact_value(...)` block; add near the other imports:
```python
from lore_core_domain.redaction import redact_value
from lore_core_domain.run_status import RunStatus
```
In `chunks.py`: delete the `def normalize_text(...)` block; add:
```python
from lore_core_domain.text import normalize_text
```

- [ ] **Step 4: Remove now-unused imports**

```bash
cd /Users/stamplevskiyd/development/lore/lore-core
uv run ruff check packages/lore-splitter/src --select F401
```
Remove any unused imports it flags (likely `from enum import StrEnum` in `per_file.py`, `import unicodedata` in `chunks.py`). Re-run until clean.

- [ ] **Step 5: Bring the three test files, rewriting imports**

Copy `test_per_file.py`, `test_chunks.py`, `test_manifest_contracts.py` into `packages/lore-splitter/tests/`. Rewrite:
- `from airflow.providers.lore.splitter.<m> import ...` → `from lore_splitter.<m> import ...`
- If a test imports `RunStatus`/`redact_value` from `...splitter.per_file` or `normalize_text` from `...splitter.chunks`, repoint to `lore_core_domain.{run_status,redaction,text}` (single source) — OR leave importing from `lore_splitter.per_file`/`chunks` (they re-expose it via the domain import). Prefer the domain path for new clarity, but either resolves.

- [ ] **Step 6: Verify foundation tests + purity + existing suites**

```bash
cd /Users/stamplevskiyd/development/lore/lore-core
uv sync
uv run --package lore-splitter python -c "import lore_splitter.contracts, lore_splitter.per_file, lore_splitter.chunks; from lore_splitter.per_file import RunStatus, redact_value; from lore_splitter.chunks import normalize_text; print('foundation OK')"
uv run --package lore-splitter pytest packages/lore-splitter/tests -q
grep -rnE "airflow|fastapi|pydantic|chainlit|psycopg" packages/lore-splitter/src/lore_splitter || echo "pure — OK"
uv run --package lore-audit-core pytest packages/lore-audit-core/tests -q
uv run --package lore-audit-api pytest services/lore-audit-api/tests -q
(cd services/lore-chat && uv run pytest -q)
```
Expected: `foundation OK`; the 3 foundation test files pass (proving the deduped primitives behave identically); `pure — OK`; lore-audit-core 156; lore-audit-api 96/1; lore-chat 121/1 (all unchanged).

- [ ] **Step 7: Commit**

```bash
cd /Users/stamplevskiyd/development/lore
git add -A lore-core/packages/lore-splitter
git commit -m "feat(splitter): bring foundation (contracts/per_file/chunks) into lore-splitter

De-Airflowed; RunStatus/redact_value/normalize_text deduplicated onto
lore_core_domain (single source of truth). +foundation tests.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Self-Review

**Spec coverage:**
- New `lore-splitter` package, domain-dep, pure — Task 1 + Task 2 Step 6 purity check. ✓
- contracts/per_file/chunks moved, de-Airflowed — Task 2 Steps 1–2. ✓
- Primitive dedup (RunStatus/redact_value/normalize_text → domain), with identity verification — Task 2 Step 3. ✓
- Unused-import cleanup — Task 2 Step 4. ✓
- Foundation tests brought and green (the dedup safety net) — Task 2 Steps 5–6. ✓
- Existing suites unaffected — Task 2 Step 6. ✓

**Placeholder scan:** none. The one judgement point (whether a primitive `diff` is "only noise" vs real drift) is given an explicit STOP-and-report criterion.

**Type consistency:** the import-rewrite rule is uniform; `RunStatus`/`redact_value`/`normalize_text` keep identical identities (now the domain ones) so any consumer — including the already-migrated audit code that imports them from `lore_core_domain` — sees the same objects. Public API of contracts/per_file/chunks is otherwise unchanged (verbatim move).

**Note:** downstream splitter slices (2d content, 2e storage) will import these foundation symbols; storage's `core_repository`/`persistence` additionally need `audit.registration`/`audit.validation` (already in `lore_audit`) — those land cleanly in 2e. No forward reference is introduced by 2c.
