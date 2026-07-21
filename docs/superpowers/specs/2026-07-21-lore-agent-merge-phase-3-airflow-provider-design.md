# Phase 3 — Airflow Provider — Design Spec

**Branch:** `lore-agent-merge` · **Date:** 2026-07-21 · **Status:** approved (design)

Final phase of the lore↔agent-lore monorepo merge. Phases 0–2 ported the entire non-Airflow surface (`lore_splitter`, `lore_audit`, `lore_audit_api`, chat). Phase 3 lands the **real Airflow SDK edge** — the only code that imports `airflow.*` — into a standalone provider package, completing the merge.

## Goal

Land the Airflow-coupled code (2 operators + 3 hook-wrappers + provider metadata + config loader + example DAG) into a **standalone** `apache-airflow-providers-lore` package, keeping `lore_splitter`/`lore_audit` 100% Airflow-free, verified by stub-based tests that need no real Airflow install.

## Approved Decisions

1. **All Airflow code in the provider package.** The 3 hook-wrappers (`airflow_postgres.py`, `airflow_s3.py`, `airflow_adapters.py`) move OUT of `splitter/storage/` and `audit/` and INTO the provider, alongside the operators. `lore_splitter` and `lore_audit` remain the single pure layer; the provider is the single Airflow-importing layer.
2. **Standalone package + stub-based tests.** The provider has its own `pyproject.toml`, is **excluded from the app uv-workspace**, and depends on `lore-splitter`/`lore-audit-core` via `[tool.uv.sources]` path deps. Airflow's dependency tree never enters the chat/audit-api env. Operator/adapter tests use an `install_airflow_stubs()` helper (fakes the SDK) and run without a real Airflow install. Real-DagBag/UAT assertions skip-mark when Airflow is unavailable.
3. **Port `config/runtime.py` faithfully.** The provider resolves runtime config from a bounded YAML document + Airflow **Connection IDs** (`s3_conn_id`, `postgres_conn_id`) — NOT env vars. It therefore does not read the app's `TOAST_DB_*`/`CHAINLIT_JWT_SECRET` contract at all (DB/S3 creds live in Airflow Connections), so the "one canonical env name per physical value, no aliases" rule is inherently satisfied with no reconciliation needed. The 292-line loader (bounded YAML, alias limit, credential-concept rejection, numeric bounds) comes over unchanged apart from the namespace rewrite.
4. **Include the example DAG + its structure tests.** `example_dags/lore_splitter.py` documents the `split_file → audit_file` wiring; `test_lore_dag.py` and `test_phase26_uat.py` come over (stubbed; real-DagBag parts skip when Airflow absent).

## Target Structure

```
lore-core/airflow-providers/apache-airflow-providers-lore/
├── pyproject.toml            # standalone; apache-airflow>=3.1.7,<4; NOT a workspace member
├── README.md
├── airflow/providers/lore/    # keep the airflow.providers.lore import namespace (provider discovery)
│   ├── __init__.py
│   ├── get_provider_info.py    # entry-point metadata (2 operators)
│   ├── operators/
│   │   ├── __init__.py         # __all__ = [LoreSplitterAuditOperator, LoreSplitterOperator]
│   │   ├── lore_splitter_operator.py         # BaseOperator → PerFileExecutionService
│   │   └── lore_splitter_audit_operator.py   # BaseOperator → AuditService
│   ├── adapters/               # the 3 hook-wrappers, moved out of the packages
│   │   ├── __init__.py
│   │   ├── airflow_postgres.py    # PostgresHook → lore_splitter PostgresTableToastStore
│   │   ├── airflow_s3.py          # S3Hook → S3HookObjectToastStore (defined here)
│   │   └── airflow_audit_adapters.py  # PostgresHook/S3Hook → lore_audit reader/writer/resolver
│   └── config/
│       ├── __init__.py         # re-exports the runtime config contracts
│       └── runtime.py          # bounded YAML loader (faithful port)
├── example_dags/
│   └── lore_splitter.py
└── tests/
    ├── _airflow_stubs.py       # shared install_airflow_stubs() helper (lifted from operator test)
    ├── test_lore_splitter_operator.py
    ├── test_lore_splitter_audit_operator.py
    ├── test_audit_airflow_adapters.py
    ├── test_storage_airflow_hooks.py
    ├── test_lore_dag.py
    ├── test_phase26_uat.py
    └── (reinstated debt tests — see Testing)
```

The exact package-dir layout (`airflow/providers/lore/` vs `src/`) follows Airflow provider convention so `get_provider_info`'s entry-point resolves; confirmed during implementation. The `adapters/` subpackage placement (vs. keeping the source's `audit/airflow_adapters.py` path) is a deliberate tidy — grouping all hook-wrappers together.

## Components

### Operators (real Airflow SDK — genuine edge)
- **`LoreSplitterOperator`** (`operators/lore_splitter_operator.py`, ~224 lines). `BaseOperator`. Runs one Airbyte file item through `lore_splitter` `PerFileExecutionService.execute()` with hook-backed storage/repository adapters; manages tempfiles; returns compact XCom (run_id, status, counts, schema_identities). Airflow symbols: `airflow.models.BaseOperator`, `airflow.exceptions.{AirflowException,AirflowFailException}`, `airflow.utils.context.Context`.
- **`LoreSplitterAuditOperator`** (`operators/lore_splitter_audit_operator.py`, ~169 lines). `BaseOperator`. Pulls the splitter's run claim via `task_instance.xcom_pull()`, builds audit adapters, runs `lore_audit` `AuditService.audit_run()`, returns audit payload. Airflow symbols: `BaseOperator`, `AirflowFailException`, `Context`.

Both consume `lore_splitter`/`lore_audit` public surfaces via straight package imports.

### Adapters (hook-wrappers — lazy `importlib` of hooks)
- **`airflow_postgres.py`** (~34 lines): factory wrapping a `PostgresHook` connection into `lore_splitter.storage.postgres.PostgresTableToastStore`.
- **`airflow_s3.py`** (~61 lines): defines `S3HookObjectToastStore` (accepts hook/conn_id, uploads image TOAST via `hook.load_bytes()`).
- **`airflow_audit_adapters.py`** (~210 lines, from source `audit/airflow_adapters.py`): builds the frozen `AirflowAuditAdapters` (reader/writer/payload_resolver); lazy-imports `PostgresHook`/`S3Hook` only when needed.

**Adapter import remaps** (beyond the mechanical `airflow.providers.lore.*` → package rewrite):
- `.engine_contracts` → `lore_audit.engine_contracts`
- `.persistence import PostgresAuditResultWriter` → `lore_audit.persistence`
- `.repository import AuditReadBounds, PostgresAuditSnapshotRepository` → **`lore_audit.snapshot_repository`** (honors the 2b write-side rename `repository.py` → `snapshot_repository.py`)
- `PostgresTableToastStore` → `lore_splitter.storage.postgres`

### Provider metadata & config
- **`get_provider_info.py`**: static provider info dict declaring the 2 operators under the "Lore Splitter" integration; wired via the `apache_airflow_provider` entry-point in `pyproject.toml`.
- **`config/runtime.py`** + `config/__init__.py`: bounded YAML runtime-config loader (faithful port, namespace-rewritten). Its only non-stdlib imports are `yaml` and `lore_splitter.config.{validate_splitter_config, SplitterConfigError}` — no Airflow import.

### Example DAG
- **`example_dags/lore_splitter.py`**: `dag_id=lore_splitter`; `validated_file_items` producer → `split_file` (mapped `LoreSplitterOperator.partial().expand()`) → `audit_file` (mapped `LoreSplitterAuditOperator`, `trigger_rule=all_done`). Uses Airflow 3.1 SDK decorators (`@dag`, `@task`, `get_current_context`).

## Packaging & Isolation

Standalone `pyproject.toml`:
- `dependencies`: `apache-airflow(>=3.1.7,<4.0.0)` + `defusedxml`, `markitdown[docx,pptx,pdf]`, `openpyxl`, `Pillow`, `pymupdf`, `PyYAML`, `python-docx`, `python-pptx` (same pins as the splitter). Optional extras: `api` (fastapi/pydantic), `postgres` (psycopg==3.3.4).
- `[project.entry-points.apache_airflow_provider] provider_info = "airflow.providers.lore.get_provider_info:get_provider_info"`.
- `[tool.uv.sources]` path deps on `lore-splitter` and `lore-audit-core` (the sibling packages).
- **Excluded from the app uv-workspace** — the root `lore-core/pyproject.toml` `[tool.uv.workspace] members` must NOT glob this package into the app env (verify: `airflow-providers/*` is not a member, or is explicitly excluded). Airflow never installs into the chat/audit-api env.
- Python floor `>=3.10` (Airflow's constraint), not the app's 3.13 pin.

## Testing

Strategy: **stub the Airflow SDK** so tests run in the provider's own env without a real Airflow install.
- Lift `install_airflow_stubs()` (currently defined inside `test_lore_splitter_operator.py`) into a shared `tests/_airflow_stubs.py`; all operator/adapter/DAG tests import it.
- Port the stub-based suites: `test_lore_splitter_operator` (697), `test_lore_splitter_audit_operator` (340), `test_audit_airflow_adapters` (362), `test_storage_airflow_hooks` (172).
- Port the DAG-structure suites: `test_lore_dag` (217), `test_phase26_uat` (490). Their real-`DagBag` assertions skip-mark when Airflow/DagBag is unavailable (the source already gates this conditionally).
- **Reinstate the 3 owed debts** (recorded across phases 2b/2d):
  1. the excised provider `__all__`-surface test (originally from `test_audit_engine`),
  2. the airflow_adapters integration test (originally from `test_audit_service`) — realized by `test_audit_airflow_adapters.py`,
  3. the skip-marked `test_real_postgres_catalog_error_does_not_poison_failure_write` (2d) — un-skip now that the airflow adapter lands.
- The provider's tests run via its own env (e.g. `uv run` against the provider's lock, or `pytest` with the sibling packages on the path); the exact invocation is settled in the plan. Cross-check that the app suites (audit-core 156, api 96/1, chat 121/1, lore-splitter 284/1) remain untouched — Phase 3 adds no code to the packages.

## Non-Goals / Out of Scope

- No changes to `lore_splitter`/`lore_audit`/`lore_audit_api`/chat source (Phase 3 is additive; it only removes nothing from them — the hook-wrappers were never ported into them).
- No live Airflow deployment or scheduler run as part of this merge (real-DagBag tests are opportunistic/skip-marked).
- No merge to `main` — the branch continues to Phase 4 (final cleanup: tests/scripts/docs/shims).

## Slice Breakdown (for the implementation plan)

1. **Provider skeleton + packaging** — `pyproject.toml`, `get_provider_info.py`, `__init__.py`s, workspace exclusion; verify the package resolves standalone and is discoverable.
2. **Storage hook-adapters** — `airflow_postgres.py` + `airflow_s3.py` + `test_storage_airflow_hooks` (stubbed) + `_airflow_stubs.py` helper.
3. **Audit hook-adapter** — `airflow_audit_adapters.py` (with the 3 remaps) + `test_audit_airflow_adapters` + reinstate the excised 2b adapter/`__all__` tests + un-skip the 2d test.
4. **Operators + config** — both operators + `config/runtime.py` + `config/__init__.py` + `test_lore_splitter_operator` + `test_lore_splitter_audit_operator`.
5. **Example DAG + UAT** — `example_dags/lore_splitter.py` + `test_lore_dag` + `test_phase26_uat` (skip-marked where real Airflow needed).

Order 1→2→3→4→5 (each an independently testable deliverable). Execute subagent-driven.
