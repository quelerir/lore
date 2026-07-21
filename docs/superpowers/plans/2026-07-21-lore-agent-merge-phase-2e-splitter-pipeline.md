# Slice 2e — Splitter Pipeline Orchestration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Port the last four Splitter orchestration modules from the source Airflow provider into `lore-splitter`, completing the splitter port.

**Architecture:** Verbatim byte-for-byte move of each source module with a single mechanical namespace rewrite (`airflow.providers.lore.splitter.*` → `lore_splitter.*`), plus a small number of *known* symbol remaps for storage-result types that moved to `lore_core_domain` in earlier slices. No behavioural change. Package `__init__.py` stays empty (house convention in this merge is direct-submodule imports).

**Tech Stack:** Python 3.13, uv workspace, pytest. `lore-splitter` package already contains every dependency these four modules need (contracts, per_file, chunks, resolver, manifest, storage/, xlsx/, markdown/, documents/, transcripts/).

## Global Constraints

- Source repo root for these modules: `/Users/stamplevskiyd/adventum/agent-lore/lore-core/airflow-providers/apache-airflow-providers-lore/`
  - Source modules dir: `airflow/providers/lore/splitter/`
  - Source tests dir: `tests/`
- Target package: `/Users/stamplevskiyd/development/lore/lore-core/packages/lore-splitter/`
  - Source dir: `src/lore_splitter/`
  - Tests dir: `tests/`
- **Namespace rewrite (every ported file):** `airflow.providers.lore.splitter` → `lore_splitter`. Do this to imports only; touch nothing else.
- **Move must be verbatim** apart from the rewrite + the explicit remaps named in each task. Do not "improve", reformat, or reorder. The reviewer will diff against source.
- **Empty `__init__.py`:** do NOT add package-root exports. `src/lore_splitter/__init__.py` stays empty. `cli.py` and `__main__.py` are already ported — do not touch them.
- **Test command** (run from `lore-core/` root):
  `uv run --package lore-splitter pytest packages/lore-splitter/tests/<file> -q`
- **Full-suite regression** (must stay green each task):
  `uv run --package lore-splitter pytest packages/lore-splitter/tests -q`
  Baseline before this slice: 241 passed / 1 skipped.
- **Do NOT run** `git add -A`. Add only the files each task names.
- Untracked `lore-core/.chainlit/` is unrelated noise — never stage it.

---

### Task 1: Leaf modules — `config.py` + `airflow_item.py` (+ their tests, + CLI-summary test)

Two stdlib/contracts-only leaf modules and three test files that were left behind when `cli.py` was pulled forward in 2d. All independent of the pipeline.

**Files:**
- Create: `src/lore_splitter/config.py` (from source `config.py`, 63 lines)
- Create: `src/lore_splitter/airflow_item.py` (from source `airflow_item.py`, 61 lines)
- Create: `tests/test_airflow_item.py` (from source `tests/test_phase17_contracts.py`, 74 lines — covers `airflow_item` **and** `config`; renamed because the "phase17" label is misleading and this test has zero Airflow-SDK dependency)
- Create: `tests/test_cli_summary.py` (from source `tests/test_cli_summary.py`, 89 lines — exercises the already-ported `cli.py` `manifest-summary` subcommand)

**Interfaces:**
- Produces (`config.py`): `SplitterConfigError`, `validate_splitter_config(configurations: dict) -> dict`, `content_config_hash(config: dict) -> str`. Depends only on stdlib (`hashlib`, `json`).
- Produces (`airflow_item.py`): `NormalizedAirbyteItem` (frozen dataclass), `AirbyteItemError`, `normalize_airbyte_item(item: dict) -> NormalizedAirbyteItem`. Imports only `from lore_splitter.contracts import SourceFile`.
- Consumed by later tasks: `content_config_hash` (Task 2), nothing else.

- [ ] **Step 1: Copy `config.py` verbatim, then rewrite imports**

```bash
cp "/Users/stamplevskiyd/adventum/agent-lore/lore-core/airflow-providers/apache-airflow-providers-lore/airflow/providers/lore/splitter/config.py" \
   "/Users/stamplevskiyd/development/lore/lore-core/packages/lore-splitter/src/lore_splitter/config.py"
```

`config.py` imports only stdlib — **no namespace rewrite needed**. Confirm zero `airflow` references:

```bash
grep -n "airflow" /Users/stamplevskiyd/development/lore/lore-core/packages/lore-splitter/src/lore_splitter/config.py
```
Expected: no output.

- [ ] **Step 2: Copy `airflow_item.py` verbatim, then rewrite imports**

```bash
cp "/Users/stamplevskiyd/adventum/agent-lore/lore-core/airflow-providers/apache-airflow-providers-lore/airflow/providers/lore/splitter/airflow_item.py" \
   "/Users/stamplevskiyd/development/lore/lore-core/packages/lore-splitter/src/lore_splitter/airflow_item.py"
```

Rewrite the single import line `from airflow.providers.lore.splitter.contracts import SourceFile` → `from lore_splitter.contracts import SourceFile` (use Edit). Confirm:

```bash
grep -n "airflow" /Users/stamplevskiyd/development/lore/lore-core/packages/lore-splitter/src/lore_splitter/airflow_item.py
```
Expected: no output.

- [ ] **Step 3: Copy the two test files, rewrite namespaces**

```bash
cp "/Users/stamplevskiyd/adventum/agent-lore/lore-core/airflow-providers/apache-airflow-providers-lore/tests/test_phase17_contracts.py" \
   "/Users/stamplevskiyd/development/lore/lore-core/packages/lore-splitter/tests/test_airflow_item.py"
cp "/Users/stamplevskiyd/adventum/agent-lore/lore-core/airflow-providers/apache-airflow-providers-lore/tests/test_cli_summary.py" \
   "/Users/stamplevskiyd/development/lore/lore-core/packages/lore-splitter/tests/test_cli_summary.py"
```

In BOTH copied test files, replace every `airflow.providers.lore.splitter` → `lore_splitter`. Then confirm no stragglers:

```bash
grep -rn "airflow.providers" /Users/stamplevskiyd/development/lore/lore-core/packages/lore-splitter/tests/test_airflow_item.py /Users/stamplevskiyd/development/lore/lore-core/packages/lore-splitter/tests/test_cli_summary.py
```
Expected: no output.

- [ ] **Step 4: Run the two new tests**

Run (from `lore-core/`):
```bash
uv run --package lore-splitter pytest packages/lore-splitter/tests/test_airflow_item.py packages/lore-splitter/tests/test_cli_summary.py -q
```
Expected: all pass (source had ~5 tests across the two files). If `test_cli_summary` shells out to the CLI, it invokes `python -m lore_splitter ...` or the `splitter` entrypoint — verify the test's subprocess/argv target resolves to the ported `cli.py`; if it references the old module path, rewrite that string too.

- [ ] **Step 5: Full-suite regression**

Run: `uv run --package lore-splitter pytest packages/lore-splitter/tests -q`
Expected: 241 + new tests passed, 1 skipped. No regressions.

- [ ] **Step 6: Commit**

```bash
cd /Users/stamplevskiyd/development/lore
git add lore-core/packages/lore-splitter/src/lore_splitter/config.py \
        lore-core/packages/lore-splitter/src/lore_splitter/airflow_item.py \
        lore-core/packages/lore-splitter/tests/test_airflow_item.py \
        lore-core/packages/lore-splitter/tests/test_cli_summary.py
git commit -m "feat(splitter): config + airflow_item leaf modules"
```

---

### Task 2: `per_file_execution.py` — single-file orchestration service

**Files:**
- Create: `src/lore_splitter/per_file_execution.py` (from source `per_file_execution.py`, 421 lines)
- Create: `tests/test_per_file_execution.py` (from source `tests/test_per_file_execution.py`, 290 lines)

**Interfaces:**
- Consumes: `lore_splitter.config.content_config_hash` (Task 1); `lore_splitter.chunks` (`CHUNK_SCHEMA_VERSION`, `Chunk`, `build_chunk`); `lore_splitter.contracts.SourceFile`; `lore_splitter.per_file` (`Diagnostic`, `RunResult`, `RunStatus`, `build_processing_identity`, `logical_file_key`); dynamic lane imports from `documents.*`, `xlsx.*`, `transcripts.lane`, `resolver`.
- Produces: `LaneResult`, `DurableExecutionResult`, `PerFileExecutionService`, `build_v12_dispatcher()`.

- [ ] **Step 1: Copy source verbatim**

```bash
cp "/Users/stamplevskiyd/adventum/agent-lore/lore-core/airflow-providers/apache-airflow-providers-lore/airflow/providers/lore/splitter/per_file_execution.py" \
   "/Users/stamplevskiyd/development/lore/lore-core/packages/lore-splitter/src/lore_splitter/per_file_execution.py"
```

- [ ] **Step 2: Rewrite namespaces (module-level AND lazy in-function imports)**

Replace every `airflow.providers.lore.splitter` → `lore_splitter` throughout the file. This includes the dynamic imports inside `build_v12_dispatcher` (`documents.chunking`, `documents.conversion`, `documents.presentations`, `documents.pdfs`, `xlsx.chunking`, `xlsx.workbook`, `transcripts.lane`, `resolver`). Note: `RunStatus` is imported `from lore_splitter.per_file import ... RunStatus ...` — `per_file` re-exposes `RunStatus` in its namespace (it does `from lore_core_domain.run_status import RunStatus`), so that import resolves; leave it as-is. Confirm:

```bash
grep -n "airflow" /Users/stamplevskiyd/development/lore/lore-core/packages/lore-splitter/src/lore_splitter/per_file_execution.py
```
Expected: no output.

- [ ] **Step 3: Copy the test, rewrite namespaces**

```bash
cp "/Users/stamplevskiyd/adventum/agent-lore/lore-core/airflow-providers/apache-airflow-providers-lore/tests/test_per_file_execution.py" \
   "/Users/stamplevskiyd/development/lore/lore-core/packages/lore-splitter/tests/test_per_file_execution.py"
```

Replace every `airflow.providers.lore.splitter` → `lore_splitter` in the test. Confirm:

```bash
grep -n "airflow.providers" /Users/stamplevskiyd/development/lore/lore-core/packages/lore-splitter/tests/test_per_file_execution.py
```
Expected: no output.

- [ ] **Step 4: Run the new test**

Run: `uv run --package lore-splitter pytest packages/lore-splitter/tests/test_per_file_execution.py -q`
Expected: all pass. If a lane import fails, the culprit is an un-rewritten dynamic import string in Step 2 — fix and rerun.

- [ ] **Step 5: Full-suite regression**

Run: `uv run --package lore-splitter pytest packages/lore-splitter/tests -q`
Expected: prior total + new tests passed, 1 skipped.

- [ ] **Step 6: Commit**

```bash
cd /Users/stamplevskiyd/development/lore
git add lore-core/packages/lore-splitter/src/lore_splitter/per_file_execution.py \
        lore-core/packages/lore-splitter/tests/test_per_file_execution.py
git commit -m "feat(splitter): per-file execution service"
```

---

### Task 3: `pipeline.py` — end-to-end pipeline orchestrator

The big one. Verbatim move + namespace rewrite + **one known symbol remap** (storage-result types moved to `lore_core_domain` in slice 2c). Must preserve the psycopg-laziness invariant that `test_pipeline` asserts.

**Files:**
- Create: `src/lore_splitter/pipeline.py` (from source `pipeline.py`, 609 lines)
- Create: `tests/test_pipeline.py` (from source `tests/test_pipeline.py`, 1165 lines)

**Interfaces:**
- Consumes: `contracts.ManifestDiagnostic`; `documents.*` (many symbols); `manifest` (`ManifestError`, `load_manifest`); `markdown.contracts` (`TableData`, `TableProfile`, `ToastDecision`, `WorkbookOutputBundle`); `markdown.output` (`MetadataConfig`, `write_document_outputs`, `write_run_manifest`, `write_workbook_outputs`); `markdown.profile.profile_table`; `markdown.table_data.extract_table_data`; `markdown.table_markdown` (`MarkdownTableExtractionResult`, `extract_markdown_document_tables`); `markdown.toast` (`ToastThresholds`, `classify_table`); `resolver.resolve_manifest`; `storage.object_schema.image_object_key`; `storage.schema` (`DEFAULT_TOAST_SCHEMA`, `build_table_storage_plan`); `storage.fake` (`FakeObjectToastStore`, `FakeTableToastStore`); `xlsx.extract_workbooks`; **and** `ImageToastStorageResult` + `TableToastStorageResult` (remapped — see Step 2). All verified present in target.
- Produces: `PipelineConfig`, `PipelineResult`, `PipelineRunError`, `run(...)`.

- [ ] **Step 1: Copy source verbatim**

```bash
cp "/Users/stamplevskiyd/adventum/agent-lore/lore-core/airflow-providers/apache-airflow-providers-lore/airflow/providers/lore/splitter/pipeline.py" \
   "/Users/stamplevskiyd/development/lore/lore-core/packages/lore-splitter/src/lore_splitter/pipeline.py"
```

- [ ] **Step 2: Rewrite namespaces + remap the storage-result import**

First, blanket-replace `airflow.providers.lore.splitter` → `lore_splitter`.

Then fix the ONE import that would otherwise break — source line ~43:
```python
from airflow.providers.lore.splitter.storage.contracts import (
    ImageToastStorageResult,
    TableToastStorageResult,
)
```
`storage/contracts.py` no longer exists (removed in 2c; these types live in `lore_core_domain`). Rewrite it to mirror the sibling `markdown/output.py`:
```python
from lore_core_domain.storage_contracts import (
    ImageToastStorageResult,
    TableToastStorageResult,
)
```
Confirm no stragglers and no dangling `storage.contracts`:
```bash
grep -n "airflow\|storage.contracts\|storage\.contracts" /Users/stamplevskiyd/development/lore/lore-core/packages/lore-splitter/src/lore_splitter/pipeline.py
```
Expected: no output.

- [ ] **Step 3: Verify the psycopg-laziness invariant is intact**

`test_pipeline` has `test_importing_pipeline_does_not_import_airflow_or_psycopg`: importing `lore_splitter.pipeline` must NOT pull `airflow` or `psycopg` into `sys.modules`. The verbatim move preserves this (postgres stores are imported lazily inside functions, not at module top). Do a sanity check:
```bash
cd /Users/stamplevskiyd/development/lore/lore-core && uv run --package lore-splitter python -c "import sys, lore_splitter.pipeline; assert 'psycopg' not in sys.modules and 'airflow' not in sys.modules; print('lazy OK')"
```
Expected: `lazy OK`. If it fails, an import that should be function-local ended up at module scope — do NOT hoist any psycopg/postgres import to the top; keep the source's lazy structure.

- [ ] **Step 4: Copy the test, rewrite namespaces + remap**

```bash
cp "/Users/stamplevskiyd/adventum/agent-lore/lore-core/airflow-providers/apache-airflow-providers-lore/tests/test_pipeline.py" \
   "/Users/stamplevskiyd/development/lore/lore-core/packages/lore-splitter/tests/test_pipeline.py"
```

Blanket-replace `airflow.providers.lore.splitter` → `lore_splitter`. Then fix the test's own `storage.contracts` import (source line ~168):
```python
from lore_splitter.storage.contracts import (
    ImageToastStorageResult,
    TableToastStorageResult,
)
```
→ import from the storage package root, which re-exports both:
```python
from lore_splitter.storage import (
    ImageToastStorageResult,
    TableToastStorageResult,
)
```
The purity test's own line `import lore_splitter.pipeline` stays. Confirm:
```bash
grep -n "airflow.providers\|storage\.contracts" /Users/stamplevskiyd/development/lore/lore-core/packages/lore-splitter/tests/test_pipeline.py
```
Expected: no output.

- [ ] **Step 5: Run the new test**

Run: `uv run --package lore-splitter pytest packages/lore-splitter/tests/test_pipeline.py -q`
Expected: all pass. Common failure modes and fixes:
- `ModuleNotFoundError: ...storage.contracts` → an un-remapped import (Step 2 or 4).
- purity test fails → a psycopg/postgres import got hoisted (Step 3).
- a `from lore_splitter.storage import (...)` at test lines ~933/~1020 references a symbol not in `storage/__init__.py __all__` → check the symbol name; it should already be exported. Do not invent exports; if genuinely missing, STOP and report (out-of-scope surprise).

- [ ] **Step 6: Full-suite regression**

Run: `uv run --package lore-splitter pytest packages/lore-splitter/tests -q`
Expected: prior total + new tests passed, 1 skipped.

- [ ] **Step 7: Commit**

```bash
cd /Users/stamplevskiyd/development/lore
git add lore-core/packages/lore-splitter/src/lore_splitter/pipeline.py \
        lore-core/packages/lore-splitter/tests/test_pipeline.py
git commit -m "feat(splitter): end-to-end pipeline orchestrator"
```

---

## Post-slice

After Task 3, the splitter port is complete: every non-Airflow-SDK module lives in `lore-splitter`. What remains for **Phase 3** (Airflow provider) is only the real SDK surface — operators, DAGs, hooks (`airflow_postgres.py`, `airflow_s3.py`, `airflow_adapters.py`) and the operator regression suite `test_phase17_regression.py` (which imports real `airflow.models.BaseOperator`).

Update the SDD progress ledger (`.superpowers/sdd/progress.md`) and the memory file `lore-agent-merge.md` on completion.

## Self-Review

- **Spec coverage:** all four target modules accounted for — `config.py`+`airflow_item.py` (Task 1), `per_file_execution.py` (Task 2), `pipeline.py` (Task 3); `cli.py` already landed in 2d, its two tests filled by Tasks 1/3. Every source test that lacks a real Airflow-SDK import is ported; the one that has it (`test_phase17_regression.py`) is explicitly deferred to Phase 3.
- **Placeholder scan:** none — every step is a concrete `cp`/`grep`/`pytest`/`git` command or a named import remap with exact before/after text.
- **Type consistency:** produced symbols (`content_config_hash`, `PerFileExecutionService`, `PipelineConfig`/`run`, `normalize_airbyte_item`) match how downstream tasks/tests consume them. The two remapped types keep their exact names (`ImageToastStorageResult`, `TableToastStorageResult`).
