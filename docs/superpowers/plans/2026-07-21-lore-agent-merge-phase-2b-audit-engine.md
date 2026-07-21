# Lore↔agent-lore Merge — Phase 2b: write-side audit engine into `lore-audit-core`

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Bring the write-side audit engine (the deterministic rule evaluation + persistence that runs during the pipeline to produce audit snapshots) from agent-lore into `lore-audit-core`, de-Airflowed, with its tests.

**Architecture:** The write-side (`engine`, `service`, `persistence`, `repository`, `ruleset`, `suppression`, `rules/*`) has ZERO real Airflow SDK imports — `service`/`persistence`/`repository` take an injected `connection`/reader/writer, so they are already Airflow-agnostic. Only `airflow_adapters.py` bridges to Airflow hooks, and it stays in the provider (Phase 3). The move is: add the one missing shared primitive (`normalize_text`) to `lore-core-domain`; git-move the 10 modules into `lore_audit` with imports rewritten (`...audit.X` → `lore_audit.X`, splitter primitives → `lore_core_domain.X`); bring the 7 write-side test files; then split the one oversized evaluator file.

**Tech Stack:** Python 3.13, uv workspace, psycopg (already a `lore-audit-core` dep), stdlib. No new third-party dependency.

## Global Constraints

- Branch: `lore-agent-merge`. Python **3.13**.
- **`lore-core-domain` stays dependency-free** (stdlib only). **`lore-audit-core` must NOT import** `fastapi`, `pydantic`, `uvicorn`, `chainlit`, or `airflow*`; deps remain `lore-core-domain` + `psycopg`.
- The write-side code moves **verbatim** (no logic changes) except mechanical import rewrites.
- **Do NOT bring `airflow_adapters.py`** (real Airflow-hook bridge) or `test_audit_airflow_adapters.py` — those are Phase 3.
- Existing suites stay green: `lore-audit-api` **96 passed / 1 skipped**, `lore-chat` **121 passed / 1 skipped** (trailing LangSmith/ls.local warning is expected noise). The write-side tests are NEW and must pass in the `lore-audit-core` suite.
- Source of the write-side code (read verbatim from here):
  `/Users/stamplevskiyd/adventum/agent-lore/lore-core/airflow-providers/apache-airflow-providers-lore/airflow/providers/lore/audit/`
  and its tests under `.../apache-airflow-providers-lore/tests/`.

**Import rewrite rules (apply to every moved module AND test):**
- `from airflow.providers.lore.audit.<m> import ...` → `from lore_audit.<m> import ...`
- `from airflow.providers.lore.audit.rules.<m> import ...` → `from lore_audit.rules.<m> import ...`
- `from airflow.providers.lore.splitter.per_file import RunStatus` → `from lore_core_domain.run_status import RunStatus`
- `from airflow.providers.lore.splitter.per_file import redact_value` → `from lore_core_domain.redaction import redact_value`
- `from airflow.providers.lore.splitter.chunks import normalize_text` → `from lore_core_domain.text import normalize_text`

**Modules to move into `lore-core/packages/lore-audit-core/src/lore_audit/`:**
`engine.py` (204), `service.py` (226), `persistence.py` (209), `repository.py` (525), `ruleset.py` (113), `suppression.py` (211), and `rules/{run.py (162), chunks.py (320), payloads.py (521), transcripts.py (240)}`.

**Test files to bring into `lore-core/packages/lore-audit-core/tests/`:**
`test_audit_engine.py` (510), `test_audit_service.py` (428), `test_audit_persistence.py` (469), `test_audit_repository.py` (509), `test_audit_suppression.py` (214), `test_audit_run_chunk_rules.py` (585), `test_audit_payload_transcript_rules.py` (721).

---

### Task 1: Add the `normalize_text` primitive to `lore-core-domain`

**Files:**
- Create: `lore-core/packages/lore-core-domain/src/lore_core_domain/text.py`
- Create: `lore-core/packages/lore-core-domain/tests/test_text.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `lore_core_domain.text.normalize_text(str) -> str` — used by `rules/chunks.py` (Task 2).

- [ ] **Step 1: Copy `normalize_text` verbatim into `lore_core_domain/text.py`**

Read the function `normalize_text` (and any small private helpers it calls) from the source `.../airflow/providers/lore/splitter/chunks.py` and copy it verbatim into `text.py`, keeping only stdlib imports. Do not alter its logic — the audit hash rules depend on byte-identical normalization.

- [ ] **Step 2: Write a characterization test**

In `test_text.py`, add tests that pin the current behavior with a few representative inputs (e.g. CRLF→LF normalization, trailing-whitespace handling, whatever the copied function does). Assert exact outputs for 3–4 inputs so any future drift is caught.

- [ ] **Step 3: Verify**

```bash
cd /Users/stamplevskiyd/development/lore/lore-core
uv run --package lore-core-domain python -c "from lore_core_domain.text import normalize_text; print('ok')"
uv run --package lore-core-domain pytest packages/lore-core-domain/tests -q
grep -rnE "^from |^import " packages/lore-core-domain/src | grep -vE "(__future__|enum|re$|re |typing|urllib|dataclasses|abc|types|collections|unicodedata)" || echo "stdlib only — OK"
```
Expected: `ok`; tests pass; `stdlib only — OK` (if `normalize_text` uses another stdlib module, add it to the allowlist — but it must remain stdlib-only).

- [ ] **Step 4: Commit**

```bash
cd /Users/stamplevskiyd/development/lore
git add -A lore-core/packages/lore-core-domain
git commit -m "feat(domain): add normalize_text primitive

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 2: Move the write-side modules + tests into `lore-audit-core` (imports rewritten, no split)

**Files:**
- Create in `lore-core/packages/lore-audit-core/src/lore_audit/`: `engine.py`, `service.py`, `persistence.py`, `repository.py`, `ruleset.py`, `suppression.py`, and `rules/{__init__.py,run.py,chunks.py,payloads.py,transcripts.py}`
- Create in `lore-core/packages/lore-audit-core/tests/`: the 7 write-side test files listed above (+ `conftest.py`/fixtures they need)

**Interfaces:**
- Consumes: `lore_core_domain.{run_status,redaction,text,storage_contracts}`; existing `lore_audit.{contracts,engine_contracts,validation,registration}`.
- Produces: `lore_audit.engine.run_audit`, `lore_audit.service.*` (the audit application service), `lore_audit.persistence.PostgresAuditResultWriter`, `lore_audit.repository.{PostgresAuditSnapshotRepository,AuditReadBounds}`, `lore_audit.ruleset.*`, `lore_audit.suppression.classify_finding`, `lore_audit.rules.*` evaluators. These are consumed by the Airflow provider in Phase 3 — do not change their public signatures.

- [ ] **Step 1: Copy the 10 modules into `lore_audit` (create `rules/` package)**

Copy each source file verbatim from the agent-lore audit dir to the destination, preserving names; create `lore_audit/rules/__init__.py` (mirror the source `rules/__init__.py` if it has exports, else empty). Do NOT copy `airflow_adapters.py`.

- [ ] **Step 2: Apply the import-rewrite rules (Global Constraints) to every moved module**

After editing, verify no stale import remains:
```bash
cd /Users/stamplevskiyd/development/lore/lore-core/packages/lore-audit-core/src/lore_audit
grep -rnE "airflow\.providers\.lore|from audit\.|import audit\b" engine.py service.py persistence.py repository.py ruleset.py suppression.py rules/ || echo "clean"
```
Expected: `clean`.

- [ ] **Step 3: Confirm no real Airflow import and package purity**

```bash
cd /Users/stamplevskiyd/development/lore/lore-core
grep -rnE "^import airflow|^from airflow|fastapi|pydantic|chainlit" packages/lore-audit-core/src/lore_audit/{engine,service,persistence,repository,ruleset,suppression}.py packages/lore-audit-core/src/lore_audit/rules || echo "pure — OK"
uv run --package lore-audit-core python -c "import lore_audit.engine, lore_audit.service, lore_audit.persistence, lore_audit.repository, lore_audit.ruleset, lore_audit.suppression, lore_audit.rules.run, lore_audit.rules.chunks, lore_audit.rules.payloads, lore_audit.rules.transcripts; print('write-side imports OK')"
```
Expected: `pure — OK`; `write-side imports OK`.

- [ ] **Step 4: Bring the 7 write-side test files + fixtures, rewriting imports**

Copy the 7 test files into `packages/lore-audit-core/tests/`, applying the same import-rewrite rules. If they reference shared fixtures from the agent-lore provider `tests/conftest.py`, copy only the fixtures those 7 files actually use into a `packages/lore-audit-core/tests/conftest.py`. **DB note:** `test_audit_persistence.py` and `test_audit_repository.py` exercise `PostgresAuditResultWriter`/`PostgresAuditSnapshotRepository`, which take an injected `connection`. If they use a fake/stub connection (no live DB), they run as-is. If any test genuinely requires a live Postgres, mark it with `@pytest.mark.skip(reason="needs live postgres — deferred")` and CALL IT OUT in your report — do not silently drop it.

- [ ] **Step 5: Run the new write-side tests and the existing suites**

```bash
cd /Users/stamplevskiyd/development/lore/lore-core
uv sync
uv run --package lore-audit-core pytest packages/lore-audit-core/tests -q
uv run --package lore-audit-api pytest services/lore-audit-api/tests -q
(cd services/lore-chat && uv run pytest -q)
```
Expected: the 7 write-side test files pass (report the count; note any skips per Step 4); lore-audit-api **96/1**; lore-chat **121/1**.

- [ ] **Step 6: Commit**

```bash
cd /Users/stamplevskiyd/development/lore
git add -A
git commit -m "feat(audit): bring write-side audit engine into lore-audit-core

engine/service/persistence/repository/ruleset/suppression + rules/* moved from
the Airflow provider, de-Airflowed (injected connections; primitives from
lore_core_domain). airflow_adapters stays in the provider (Phase 3). +tests.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 3: Split `rules/payloads.py` per the convention

**Files:**
- Split `lore-core/packages/lore-audit-core/src/lore_audit/rules/payloads.py` (521) → `lore_audit/rules/payloads/{__init__.py, references.py, occurrences.py, resolution.py}` (group the evaluator functions by concern), behind a re-export shim.

**Interfaces:**
- Consumes: Task 2 modules.
- Produces: the same public evaluator names (`evaluate_payload_references`, `evaluate_payload_occurrences`, `evaluate_payload_resolution`, and the image/table evaluators `engine.py` imports). Keep them importable from `lore_audit.rules.payloads` via `payloads/__init__.py` re-exports so `engine.py`'s imports don't change.

- [ ] **Step 1: Split the evaluators into the subpackage**

Move each evaluator function verbatim into the module matching its concern (references/occurrences/resolution; put the image/table storage-identity + metadata + summary evaluators wherever they cohere — keep related helpers with them). `payloads/__init__.py` re-exports every name `engine.py` imports from `lore_audit.rules.payloads`.

- [ ] **Step 2: Verify import stability and tests**

```bash
cd /Users/stamplevskiyd/development/lore/lore-core
uv run --package lore-audit-core python -c "from lore_audit.rules.payloads import evaluate_payload_references, evaluate_payload_occurrences, evaluate_payload_resolution; print('payloads shim OK')"
uv run --package lore-audit-core pytest packages/lore-audit-core/tests -q
```
Expected: `payloads shim OK`; the write-side tests still pass (the split is a pure reshuffle behind the `__init__` re-export).

- [ ] **Step 3: Conservative fallback**

If any evaluator's helpers are too entangled to separate cleanly without behavior risk, prefer a smaller safe split (e.g. only extract `references.py` + `resolution.py`, leave the rest in `payloads/__init__.py`) and note it as DONE_WITH_CONCERNS. Do not risk behavior to hit an exact layout.

- [ ] **Step 4: Commit**

```bash
cd /Users/stamplevskiyd/development/lore
git add -A
git commit -m "refactor(audit): split rules/payloads.py by concern behind re-export shim

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Self-Review

**Spec coverage:**
- Write-side modules into `lore-audit-core`, de-Airflowed — Task 2. ✓
- `normalize_text` primitive into `lore-core-domain` — Task 1. ✓
- `RunStatus`/`redact_value` repointed to `lore_core_domain` — Task 2 import rules. ✓
- `airflow_adapters.py` + its test explicitly excluded (Phase 3) — Global Constraints. ✓
- Write-side tests brought and green — Task 2 Step 5. ✓
- Split the oversized `rules/payloads.py` — Task 3. ✓
- `lore-audit-core` stays free of fastapi/pydantic/chainlit/airflow — Task 2 Step 3. ✓
- No new third-party dep — deps stay `lore-core-domain` + psycopg. ✓

**Placeholder scan:** none. The two judgement points (which conftest fixtures to copy; DB-requiring tests) are called out explicitly with a concrete instruction (copy only used fixtures; skip-mark + report DB tests) rather than left vague.

**Type consistency:** import-rewrite rules are stated once and applied uniformly; public names produced in Task 2 (`run_audit`, `PostgresAuditResultWriter`, `PostgresAuditSnapshotRepository`, `AuditReadBounds`, `classify_finding`, the `evaluate_*` functions) are the ones `engine.py`/`service.py` already consume and that Phase 3's provider will consume — unchanged. Task 3 preserves the `lore_audit.rules.payloads` import surface via `__init__` re-exports.

**Note:** `repository.py` (525) is left as one cohesive repository class (not split) — like `contracts.py` in Phase 1a, it is a single coherent boundary; only the multi-function `rules/payloads.py` is split.
