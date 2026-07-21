# Lore↔agent-lore Merge — Phase 2d: splitter core (content + storage) → `lore-splitter`

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Bring the tightly-coupled splitter core — `xlsx/`, `markdown/`, `documents/`, `transcripts/`, and `storage/` — into `lore-splitter`, de-Airflowed, with its full test suite; and light up the 24 audit DB integration tests deferred from slice 2b.

**Architecture:** These modules form one mutually-entangled cluster (content calls storage's `build_table_storage_plan`/`image_object_key`; `storage/schema.py` lazily references `markdown.contracts`; `markdown ↔ documents` are circular). They cannot be cleanly ordered into separate slices, so they come as ONE slice, moved together (the circular/mutual imports resolve exactly as they did in agent-lore). Tasks are sequenced bottom-up (contract leaves → storage → xlsx/transcripts → markdown+documents → DB tests) so each task ends green. The move is mechanical: namespace rewrites, `storage/contracts.py` dropped in favor of `lore_core_domain.storage_contracts`, primitives from `lore_core_domain`, audit refs to `lore_audit`.

**Tech Stack:** Python 3.13, uv workspace, `lore-core-domain`, `lore-audit-core` (test-only, for the audit DB tests), external doc libs (openpyxl, markitdown, Pillow, pymupdf, python-docx, python-pptx, defusedxml), psycopg, Docker (for DB tests).

## Global Constraints

- Branch: `lore-agent-merge`. Python **3.13**. All modules land in the existing `lore-core/packages/lore-splitter/` package (`lore_splitter`).
- Modules move **verbatim** except: mechanical import rewrites, dropping `storage/contracts.py`, and the two monolith splits in Task 4.
- **Do NOT bring** `storage/airflow_postgres.py`, `storage/airflow_s3.py` (real Airflow hooks — Phase 3), or `test_storage_airflow_hooks.py`.
- `lore-splitter` must NOT import `airflow*`, `fastapi`, `pydantic`, `chainlit`. It MAY import the external doc libs + psycopg.
- Existing suites stay green throughout: `lore-audit-core` **156**, `lore-audit-api` **96/1**, `lore-chat` **121/1** (trailing LangSmith/ls.local warning expected).

**Import-rewrite rules (apply to every moved module AND test):**
- `from airflow.providers.lore.splitter.storage.contracts import ...` → `from lore_core_domain.storage_contracts import ...`
- `from airflow.providers.lore.splitter.<foundation> import ...` (foundation = `contracts`/`per_file`/`chunks`/`resolver`) → `from lore_splitter.<foundation> import ...` (note: `resolver` is a Phase-2f module; if a content module imports `splitter.resolver`, flag it — see Task 3)
- `from airflow.providers.lore.splitter.<subdir>[.X] import ...` (subdir = storage/documents/xlsx/markdown/transcripts) → `from lore_splitter.<subdir>[.X] import ...`
- `from airflow.providers.lore.audit.<m> import ...` → `from lore_audit.<m> import ...`
- Any `RunStatus`/`redact_value`/`normalize_text` still imported from `splitter.per_file`/`splitter.chunks` resolve via `lore_splitter.{per_file,chunks}` (they re-expose the domain primitives) — leave or repoint to `lore_core_domain`, both work.

**Source dir:** `/Users/stamplevskiyd/adventum/agent-lore/lore-core/airflow-providers/apache-airflow-providers-lore/airflow/providers/lore/splitter/`
**Tests + fixtures dir:** `/Users/stamplevskiyd/adventum/agent-lore/lore-core/airflow-providers/apache-airflow-providers-lore/tests/`

---

### Task 1: External deps + content contract leaves

**Files:**
- Modify: `lore-core/packages/lore-splitter/pyproject.toml` (add external deps)
- Create in `lore_splitter/`: `markdown/__init__.py`+`markdown/contracts.py`, `documents/__init__.py`+`documents/contracts.py`+`documents/normalize.py`, `xlsx/__init__.py`+`xlsx/contracts.py`, `transcripts/__init__.py`+`transcripts/contracts.py`
- Create tests: `markdown/`+`documents/`+`xlsx/`+`transcripts/` contract test files (`test_markdown_contracts.py`, `test_document_markdown_contracts.py`, `test_xlsx_contracts.py`) into `packages/lore-splitter/tests/`

**Interfaces:**
- Consumes: `lore_splitter.{contracts,per_file,chunks}` (foundation), `lore_core_domain.*`.
- Produces: `lore_splitter.markdown.contracts.{TableData,ColumnProfile,TableProfile,ToastDecision,MarkdownTableLocation,XlsxTableLocation,WorkbookOutputBundle,DocumentOutputBundle,RunOutputManifest,...}`, `lore_splitter.documents.contracts.*`, `lore_splitter.xlsx.contracts.{CellRange,SheetRegion,WorkbookExtraction,TableCandidate,...}`, `lore_splitter.transcripts.contracts.*`. These are the leaf contracts every later task builds on.

- [ ] **Step 1: Add external deps to `lore-splitter/pyproject.toml`**

Set `[project].dependencies` to:
```toml
dependencies = [
    "lore-core-domain",
    "defusedxml==0.7.1",
    "markitdown[docx,pptx,pdf]==0.1.6",
    "openpyxl==3.1.5",
    "Pillow==12.3.0",
    "pymupdf==1.28.0",
    "python-docx==1.2.0",
    "python-pptx==1.0.2",
    "psycopg[binary,pool]==3.3.4",
]
```
(These are the exact versions from the agent-lore provider.) Run `cd lore-core && uv sync` to confirm they resolve.

- [ ] **Step 2: Copy the 4 leaf contract modules (+ `documents/normalize.py`) and create `__init__.py`s**

Create `lore_splitter/{markdown,documents,xlsx,transcripts}/__init__.py` by copying the source subdir `__init__.py` (they have re-exports; they will import their own submodules which arrive across tasks — if an `__init__` imports a not-yet-present submodule, temporarily reduce it to the contracts re-export and restore the full exports in the task that adds those submodules; note any such trim in your report). Copy `markdown/contracts.py`, `documents/contracts.py`, `documents/normalize.py`, `xlsx/contracts.py`, `transcripts/contracts.py` verbatim.

- [ ] **Step 3: Apply the import-rewrite rules to the copied modules**

Then verify:
```bash
cd /Users/stamplevskiyd/development/lore/lore-core/packages/lore-splitter/src/lore_splitter
grep -rn "airflow" markdown/ documents/ xlsx/ transcripts/ || echo "clean"
```
Expected: `clean`.

- [ ] **Step 4: Bring the contract tests, rewrite imports, verify**

Copy `test_markdown_contracts.py`, `test_document_markdown_contracts.py`, `test_xlsx_contracts.py` into `packages/lore-splitter/tests/`, apply the rewrite rules.
```bash
cd /Users/stamplevskiyd/development/lore/lore-core
uv sync
uv run --package lore-splitter python -c "import lore_splitter.markdown.contracts, lore_splitter.documents.contracts, lore_splitter.xlsx.contracts, lore_splitter.transcripts.contracts; print('contracts OK')"
uv run --package lore-splitter pytest packages/lore-splitter/tests -q
```
Expected: `contracts OK`; contract tests pass (the 2c foundation tests + these).

- [ ] **Step 5: Commit**

```bash
cd /Users/stamplevskiyd/development/lore
git add -A lore-core/packages/lore-splitter lore-core/uv.lock
git commit -m "feat(splitter): content contract leaves + external deps

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 2: Storage layer (minus Airflow hooks)

**Files:**
- Create in `lore_splitter/storage/`: `__init__.py`, `core_schema.py`, `schema.py`, `object_schema.py`, `postgres.py`, `core_repository.py`, `persistence.py`, `fake.py`, and `migrations/` (all 4 `.sql` + any loader)
- DROP: do NOT create `storage/contracts.py` (use `lore_core_domain.storage_contracts`); do NOT bring `airflow_postgres.py`/`airflow_s3.py`
- Create tests: `test_persistence.py`, `test_storage_fake.py`, `test_storage_contracts.py`, `test_storage_object_contracts.py`, `test_storage_schema.py` (the non-DB storage tests)

**Interfaces:**
- Consumes: `lore_core_domain.storage_contracts`, `lore_splitter.{contracts,per_file,chunks}`, `lore_splitter.markdown.contracts` (lazily in `schema.py`), `lore_audit.{registration,validation}`.
- Produces: `lore_splitter.storage.{build_table_storage_plan, validate_table_storage_plan, image_object_key, validate_image_storage_plan, apply_migration, PostgresTableToastStore, FakeTableToastStore, FakeObjectToastStore, CoreRepository, PersistenceCoordinator, ...}` (via `storage/__init__.py` re-exports). Consumed by content (Tasks 3–4) and the DB tests (Task 5).

- [ ] **Step 1: Copy the storage modules + migrations, drop contracts/hooks**

Copy the listed storage modules + `migrations/` verbatim. Rewrite `storage/__init__.py` so it no longer lazy-loads `airflow_postgres`/`airflow_s3`/`contracts` (contracts now comes from `lore_core_domain.storage_contracts`) — keep the portable re-exports only.

- [ ] **Step 2: Apply import-rewrite rules (incl. the two lazy/TYPE_CHECKING `markdown.contracts` imports in `schema.py`)**

`schema.py` line ~17 (TYPE_CHECKING) and line ~142 (function-local) import `markdown.contracts` — rewrite both to `from lore_splitter.markdown.contracts import ...`. Verify:
```bash
cd /Users/stamplevskiyd/development/lore/lore-core/packages/lore-splitter/src/lore_splitter/storage
grep -rn "airflow" . || echo "clean"
```
Expected: `clean` (no `airflow` — the hook adapters were not brought).

- [ ] **Step 3: Bring the 5 non-DB storage tests, rewrite imports, verify**

```bash
cd /Users/stamplevskiyd/development/lore/lore-core
uv sync
uv run --package lore-splitter python -c "import lore_splitter.storage; from lore_splitter.storage import build_table_storage_plan, image_object_key, apply_migration, FakeTableToastStore; print('storage OK')"
uv run --package lore-splitter pytest packages/lore-splitter/tests -q
```
Expected: `storage OK`; the non-DB storage tests pass (DB tests come in Task 5).

- [ ] **Step 4: Commit**

```bash
cd /Users/stamplevskiyd/development/lore
git add -A lore-core/packages/lore-splitter
git commit -m "feat(splitter): storage layer (portable; Airflow hooks deferred to Phase 3)

storage/contracts.py dropped in favor of lore_core_domain.storage_contracts.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 3: xlsx + transcripts implementations

**Files:**
- Create in `lore_splitter/xlsx/`: `regions.py`, `workbook.py`, `chunking.py`, `merged.py` (+ restore `xlsx/__init__.py` exports)
- Create in `lore_splitter/transcripts/`: `parser.py`, `llm.py`, `batching.py`, `lane.py`, `validation.py`, `rendering.py` (+ restore `transcripts/__init__.py` exports)
- Create tests: `test_xlsx_workbook.py`, `test_xlsx_regions.py`, `test_xlsx_fixtures.py`, `test_cli_xlsx.py` (xlsx); any transcript tests
- Create: `packages/lore-splitter/tests/fixtures/xlsx/` (copy the xlsx fixture files the tests use)

**Interfaces:**
- Consumes: foundation, `lore_splitter.xlsx.contracts`, `lore_splitter.storage` (`build_table_storage_plan`), `lore_core_domain`.
- Produces: `lore_splitter.xlsx.{extract_workbooks,...}`, `lore_splitter.transcripts.{run_batch, parse_transcript, ...}`.

- [ ] **Step 1: Copy xlsx + transcripts impl modules, rewrite imports**

If any module imports `splitter.resolver` (a Phase-2f module), STOP and report — resolver is not in scope for 2d; if only a type is needed, note it. (`transcripts/llm.py` uses a `StructuredClient` Protocol — the LLM client is injected, no SDK import; leave it as-is.)

- [ ] **Step 2: Copy the xlsx fixtures and tests, verify**

Copy the xlsx fixture files into `packages/lore-splitter/tests/fixtures/xlsx/`; adjust any fixture path constants in the tests to the new location. Rewrite test imports.
```bash
cd /Users/stamplevskiyd/development/lore/lore-core
uv sync
uv run --package lore-splitter python -c "import lore_splitter.xlsx, lore_splitter.transcripts; print('xlsx+transcripts OK')"
uv run --package lore-splitter pytest packages/lore-splitter/tests -q
grep -rn "airflow" packages/lore-splitter/src/lore_splitter/xlsx packages/lore-splitter/src/lore_splitter/transcripts || echo "clean"
```
Expected: `xlsx+transcripts OK`; tests pass; `clean`.

- [ ] **Step 3: Commit**

```bash
cd /Users/stamplevskiyd/development/lore
git add -A lore-core/packages/lore-splitter
git commit -m "feat(splitter): xlsx + transcripts implementations

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 4: markdown + documents implementations (circular — together), split the two monoliths

**Files:**
- Create in `lore_splitter/markdown/`: `output.py`, `table_markdown.py`, `toast.py`, `profile.py`, `render.py`, `table_data.py` (+ restore `markdown/__init__.py` exports)
- Create in `lore_splitter/documents/`: `conversion.py`, `chunking.py`, `images.py`, `pdfs.py`, `presentations.py`, `markitdown_images.py`, `pdf_images.py`, `external_images.py` (+ restore `documents/__init__.py` exports)
- Split: `markdown/output.py` (1021) and `markdown/table_markdown.py` (640) per the contracts/module convention (see Step 3)
- Create tests: `test_markdown_output.py`, `test_markdown_render.py`, `test_markdown_toast.py`, `test_markdown_table_markdown.py`, `test_markdown_table_data.py`, `test_markdown_profile.py`, `test_markdown_fixtures.py`, and the documents fixture tests; copy `tests/fixtures/documents/` + `tests/fixtures/phase17/`

**Interfaces:**
- Consumes: foundation, all contracts, `lore_splitter.storage`, `lore_splitter.xlsx`, `lore_core_domain`.
- Produces: `lore_splitter.markdown.*`, `lore_splitter.documents.*` — the full content extraction surface consumed by the pipeline (Phase 2f).

- [ ] **Step 1: Copy markdown + documents impl modules together (they are circular)**

Copy all listed modules in one step (the `markdown ↔ documents` cycle resolves only when both are present, exactly as in agent-lore). Apply import-rewrite rules.

- [ ] **Step 2: Verify imports resolve (cycle intact) before splitting**

```bash
cd /Users/stamplevskiyd/development/lore/lore-core
uv sync
uv run --package lore-splitter python -c "import lore_splitter.markdown, lore_splitter.documents; print('markdown+documents OK')"
grep -rn "airflow" packages/lore-splitter/src/lore_splitter/markdown packages/lore-splitter/src/lore_splitter/documents || echo "clean"
```
Expected: `markdown+documents OK`; `clean`.

- [ ] **Step 3: Split `output.py` (1021) and `table_markdown.py` (640) per convention**

Split each by concern behind a re-export shim (as in Phase-1a/2b): keep `lore_splitter.markdown.output` and `lore_splitter.markdown.table_markdown` importable with their existing public names via re-exports, moving the bodies into sub-modules (e.g. `markdown/output/{__init__,workbook,document,metadata}.py`; `markdown/table_markdown/{__init__,pipe,html,classify}.py`). If a clean split risks behavior, apply the conservative fallback (smaller safe split, or keep intact) and report — do NOT risk behavior for layout.

- [ ] **Step 4: Bring markdown + documents tests + fixtures, verify**

Copy the markdown tests + documents fixture tests; copy `tests/fixtures/documents/` and `tests/fixtures/phase17/` into `packages/lore-splitter/tests/fixtures/`; fix fixture path constants; rewrite imports.
```bash
cd /Users/stamplevskiyd/development/lore/lore-core
uv run --package lore-splitter pytest packages/lore-splitter/tests -q
```
Expected: the markdown/documents test files pass (incl. `test_markdown_output.py` 848 — the split's safety net).

- [ ] **Step 5: Commit**

```bash
cd /Users/stamplevskiyd/development/lore
git add -A lore-core/packages/lore-splitter
git commit -m "feat(splitter): markdown + documents implementations; split output/table_markdown

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 5: DB integration tests — postgres harness + storage DB tests + the 24 deferred 2b audit DB tests

**Files:**
- Create: `packages/lore-splitter/tests/postgres_test_harness.py` (the Docker-backed `ephemeral_postgres`)
- Create tests: `test_core_repository.py`, `test_storage_postgres.py` (storage DB tests), and the two DEFERRED-from-2b files `test_audit_persistence.py`, `test_audit_repository.py`
- Modify: `lore-core/packages/lore-splitter/pyproject.toml` (add `lore-audit-core` to a `[dependency-groups] dev` — the audit DB tests import `lore_audit`)

**Interfaces:**
- Consumes: `lore_splitter.storage` (`apply_migration`, `CoreRepository`, `PostgresTableToastStore`), `lore_audit.{persistence,snapshot_repository}`, the harness.
- Produces: executable DB integration coverage for the storage layer AND the write-side audit persistence/repository (which shipped code-only in 2b).

- [ ] **Step 1: Bring the harness and DB tests here (co-located)**

Copy `postgres_test_harness.py` into `packages/lore-splitter/tests/`. Copy `test_core_repository.py`, `test_storage_postgres.py`, `test_audit_persistence.py`, `test_audit_repository.py` into the same dir. Apply the import-rewrite rules; the harness import becomes `from postgres_test_harness import ephemeral_postgres` (same dir), `apply_migration` from `lore_splitter.storage.core_schema`, audit imports from `lore_audit.*`. Add `lore-audit-core` to lore-splitter's dev dependency group.

- [ ] **Step 2: Run the DB tests (Docker required)**

```bash
cd /Users/stamplevskiyd/development/lore/lore-core
docker info >/dev/null 2>&1 && echo "docker up" || echo "NO DOCKER"
uv run --package lore-splitter pytest packages/lore-splitter/tests/test_core_repository.py packages/lore-splitter/tests/test_storage_postgres.py packages/lore-splitter/tests/test_audit_persistence.py packages/lore-splitter/tests/test_audit_repository.py -q
```
Expected (Docker up): all four DB test files pass — this restores the 24 deferred 2b tests + the storage DB tests. If Docker is NOT available in this environment, mark these four files with a module-level `pytest.importorskip`/`pytest.mark.skipif(no docker)` guard so the suite skips them cleanly rather than erroring, and CALL IT OUT in your report (they must run wherever Docker exists).

- [ ] **Step 3: Full-suite verification**

```bash
cd /Users/stamplevskiyd/development/lore/lore-core
uv run --package lore-splitter pytest packages/lore-splitter/tests -q
uv run --package lore-audit-core pytest packages/lore-audit-core/tests -q
uv run --package lore-audit-api pytest services/lore-audit-api/tests -q
(cd services/lore-chat && uv run pytest -q)
grep -rnE "airflow|fastapi|pydantic|chainlit" packages/lore-splitter/src/lore_splitter || echo "pure — OK"
```
Expected: lore-splitter suite green (DB tests pass or cleanly skip per Step 2); lore-audit-core 156; lore-audit-api 96/1; lore-chat 121/1; `pure — OK`.

- [ ] **Step 4: Commit**

```bash
cd /Users/stamplevskiyd/development/lore
git add -A lore-core/packages/lore-splitter
git commit -m "test(splitter): DB integration harness + storage/audit DB tests

Restores the 24 audit DB tests deferred from slice 2b (test_audit_persistence,
test_audit_repository) + storage DB tests, co-located with the ephemeral_postgres
harness. Require Docker.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Self-Review

**Spec coverage:**
- content (xlsx/markdown/documents/transcripts) + storage into `lore-splitter`, de-Airflowed — Tasks 1–4. ✓
- `storage/contracts.py` dropped for `lore_core_domain.storage_contracts` — Task 2. ✓
- Airflow hooks (`airflow_postgres`/`airflow_s3`) + their test excluded (Phase 3) — Task 2 constraint. ✓
- External deps added — Task 1. ✓
- Monolith split (`output.py`, `table_markdown.py`) — Task 4 Step 3 (with conservative fallback). ✓
- 24 deferred 2b DB tests restored + storage DB tests — Task 5. ✓
- `lore-splitter` free of airflow/fastapi/pydantic/chainlit — Task 5 Step 3. ✓
- Existing suites unaffected — every task's verify. ✓

**Placeholder scan:** none. The judgement points are called out with concrete instructions: `__init__` trimming across tasks (Task 1 Step 2), the `splitter.resolver` forward-ref STOP (Task 3 Step 1), the monolith-split conservative fallback (Task 4 Step 3), and the no-Docker skip guard (Task 5 Step 2).

**Type consistency:** import-rewrite rules stated once, applied throughout. Bottom-up task order guarantees each module's dependencies exist before it lands. The circular `markdown↔documents` pair is moved in one task (Task 4). Storage's public names (`build_table_storage_plan`, `image_object_key`, `apply_migration`, `CoreRepository`) are produced in Task 2 and consumed unchanged in Tasks 3–5.

**Note:** this slice is large; execute subagent-driven with a review after each task. The DB tests (Task 5) are the only ones needing Docker; everything else is pure-Python and fixture-driven.
