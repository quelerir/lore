# Lore ↔ agent-lore Merge Design

## Goal

Merge two parallel lines of the Lore project into one monorepo on branch
`lore-agent-merge`:

- **`development/lore`** (this repo) — the deployable product: Chainlit chat
  backend (LangGraph/deepagents), React 18 frontend (chat + FileViewer),
  docker-compose stack (frontend, backend, authentik, chainlit-db). Its code
  style is the reference standard.
- **`adventum/agent-lore`** — the heavy engine: the **Lore Splitter** (Airflow
  provider, ~64k LOC) for document ingestion, chunking (XLSX/PDF/DOCX/PPTX/
  transcripts/images), the deterministic **audit** rule engine, the read-only
  audit HTTP API (19 endpoints), operators, DAGs, and extensive tests.

The current repo already vendored the *read-side* of agent-lore's audit into
`backend/audit/` (the FileViewer integration). This merge brings the full
engine in as clean packages, with the product app as the deployment shell.

The target package layout follows `architecture.md` (audit-core / audit-api /
airflow-provider with clean boundaries), extended to also host the chat app.

## Nature of the hybrid

**Monorepo: application + engine.** One repository where the current product
(chat + FileViewer + docker-compose) is the product/deploy shell, and the
splitter + audit engine live alongside as clean packages. Both the pipeline
and the app coexist in one tree.

## Target structure

```text
lore/  (repo, branch lore-agent-merge)
├── docker-compose.yml          # frontend, chat, authentik, chainlit-db (NO Airflow)
├── frontend/                   # React 18 (chat + FileViewer) — unchanged
└── lore-core/                  # former backend/, root of the Python monorepo
    ├── config/                 # single Pydantic-settings for the whole monorepo
    ├── services/
    │   ├── lore-chat/          # current Chainlit backend (app.py, agents/, toast/, evals/)
    │   └── lore-audit-api/     # standalone ASGI factory (routes/middleware/limits/errors/factory)
    ├── packages/
    │   ├── lore-audit-core/    # rules engine, models, read service/repos/adapters, persistence
    │   └── lore-splitter/      # pipeline: documents/ xlsx/ transcripts/ markdown/ storage/
    └── airflow-providers/
        └── apache-airflow-providers-lore/   # operators, DAGs, postgres/s3 hooks — thin adapters
```

Frontend and `docker-compose.yml` stay at repo root. `lore-core/` becomes the
root of the Python monorepo and matches `architecture.md`'s `lore-core/` root;
the Chainlit chat becomes one service alongside `lore-audit-api`.

## Key decisions

1. **Branch.** `lore-agent-merge` (already checked out).
2. **Host & layout.** Current repo is the host. `backend/` → `lore-core/`. The
   Chainlit chat moves into `lore-core/services/lore-chat/`. Engine packages
   land under `lore-core/` per the structure above.
3. **Audit API serving.** `lore-audit-api` is a **standalone ASGI factory**
   that is *also mountable* into Chainlit. In the product it is mounted into
   the chat app (cookie-auth preserved, HS256 ticket fallback retained). On
   internal2 it runs as a standalone uvicorn sidecar. One codebase, two
   deployment contexts — both are in scope.
4. **Both deployment contexts matter.** The product (docker-compose) and the
   internal2/Airflow sidecar deployment (`lore-test.adventum.ru`, port 8340)
   are both supported. This is *why* the audit API must be a standalone factory
   rather than only a Chainlit sub-app.
5. **Vendored `backend/audit/` is removed** and replaced by the canonical
   `lore-audit-core` + a mount of the `lore-audit-api` ASGI app.
6. **Refactor-as-you-move.** Each piece is tidied to the current repo's quality
   bar *before* it is wired in; migrated tests ride along as the safety net.
   Worst offenders are split during the move (see Conventions).
7. **Configs centralized.** agent-lore scatters config (YAML `config/runtime.py`
   + ad-hoc). The hybrid uses a **single Pydantic-settings** module in
   `lore-core/config/`, extending the current `config.py`. The YAML runtime
   config collapses into it.
8. **`toast/`, `evals/`, `agents/` stay inside `services/lore-chat`** — they are
   chat concerns, not engine concerns.
9. **Airflow is external.** docker-compose does **not** run Airflow. The
   provider/pipeline source lives in the monorepo and deploys to external
   Airflow (internal2). Locally the app reads the real `lore_core` DB over VPN,
   as it does today. The splitter/provider is integrated the same way as in
   agent-lore, corrected only for centralized config.

## Conventions

### Config
Single Pydantic-settings in `lore-core/config/`, extending the current
`backend/config.py`. Pydantic lives only at the edges (config + API layer),
never in the domain core.

### Contracts → split by role
`contracts.py` files bundle four unrelated things (enums, closed vocabulary,
frozen dataclasses, validation/errors). The name `contracts.py` goes away.
Split into:

- **`enums.py`** — StrEnums + closed vocabulary constants (error codes, schema
  versions, caps). Widely imported; isolating them avoids import cycles.
- **`models.py`** — the frozen dataclasses (the data shapes). Name chosen to
  match the current repo's house style (`toast/models.py`).
- **`errors.py`** — error classes/codes (e.g. `AuditReadError`).
- **`validation.py`** — validation helpers (already a separate file in
  agent-lore; kept).

For oversized contract files (e.g. `read_contracts.py`, 1300 LOC) split further
by role into a subpackage:

```text
audit/read/
├── enums.py       # error codes, vocabulary
├── requests.py    # *Request DTOs
├── responses.py   # *Response DTOs
└── errors.py      # AuditReadError
```

**Domain stays on `frozen dataclasses`, not Pydantic** — `lore-audit-core` must
not import FastAPI/Pydantic (per `architecture.md`). "schemas" is deliberately
avoided as a name because it implies Pydantic/serialization.

### Packaging
- **uv workspace** on the application side (Python **3.13**, matching the
  current repo): `lore-audit-core`, `lore-audit-api`, `lore-chat`,
  `lore-splitter`. Missing dependencies are added via uv as needed.
- The **Airflow provider keeps its own pyproject** (separate build target for
  internal2). It targets 3.13 as well; if Airflow on internal2 cannot run 3.13,
  that single point is revisited then. It is not part of the app's uv workspace
  env (Airflow must not be dragged into the app runtime).

## Migration phases

Each phase ends with a working application.

### Phase 0 — Monorepo skeleton (no behavior change)
- `backend/` → `lore-core/`; chat → `lore-core/services/lore-chat/`.
- Empty `packages/`, `services/`, `airflow-providers/`; uv workspace wiring;
  single `lore-core/config/`.
- Update docker-compose (build context, Dockerfile paths) and imports.
- **Verify:** compose comes up exactly as before; chat tests green; FileViewer
  still works (still on the vendored audit at this point).

### Phase 1 — Canonical audit-core + audit-api
- Bring `lore-audit-core` (rules engine, models, read repos/adapters/cursor,
  persistence, registration, validation). De-Airflow the namespace: move shared
  primitives (`RunStatus`, redaction, storage contracts) into core; no imports
  from `airflow.providers.lore`.
- Split the monolith contract files (`read_contracts.py` 1300,
  `read_repositories.py` 1159) per the conventions; centralize config.
- Bring `lore-audit-api` as a standalone ASGI factory (routes, middleware,
  limits, errors, factory, server).
- Remove the vendored `backend/audit/`; mount the canonical factory into
  Chainlit (cookie-auth + ticket fallback preserved).
- **Verify:** FileViewer works end-to-end against real `lore_core`; exactly 19
  endpoints; audit-core unit tests + API contract tests green;
  `uvicorn lore_audit_api` boots standalone.

### Phase 2 — Splitter pipeline packages
- Bring `documents/`, `markdown/`, `xlsx/`, `transcripts/`, `storage/`,
  `pipeline`, `per_file`. Clean the worst files (`output.py` 1021,
  `table_markdown.py` 640). Centralize config (YAML `runtime.py` → central
  Pydantic). Make storage adapters pluggable (Airflow hooks injected at
  composition, not imported by the domain).
- **Verify:** splitter unit + integration tests (postgres harness) green;
  standalone CLI run works.

### Phase 3 — Airflow provider (thin adapters)
- Bring `apache-airflow-providers-lore`: operators, DAGs, `get_provider_info`,
  postgres/s3 hook adapters. Only the Airflow edge. Own build outside the uv
  workspace. Depends on `lore-audit-core` + `lore-splitter` +
  `lore-audit-api` composition adapter.
- **Verify:** provider test suite green; compatibility import shims work; a
  repo-wide search proves no canonical code remains under the airflow namespace.

### Phase 4 — Tests, scripts, docs, cleanup
- Migrate remaining tests (phase26 UAT, audit skill) and useful scripts. Merge
  relevant docs / `.planning` material into `docs/`. Remove compatibility shims
  after a search confirms no remaining consumers.
- **Verify:** full suite + ruff green.

## Risks

- **Python 3.13 (app) vs Airflow.** Everything targets 3.13; deps added via uv.
  The provider keeps a separate build; if internal2's Airflow cannot run 3.13,
  that one point is revisited (does not block Phases 0–2).
- **De-Airflow shared primitives.** `RunStatus`, redaction, storage contracts
  currently imported from the airflow namespace must be relocated into core,
  not re-imported.
- **Cross-origin cookie-auth.** Only relevant if the audit API is ever detached
  from Chainlit; while mounted it is a non-issue. Chainlit `allow_origins` must
  not be `*` for cookie auth.
- **Duplicate contract layers.** Similar `contracts.py` shapes across layers are
  refactor candidates: consolidate truly-shared vocabulary into core, keep
  layer-specific request/response separate.

## Out of scope

- Running Airflow locally / in docker-compose.
- Production (`loreagent`) deployment changes — checked only via non-mutating
  health/state verification.
- Converting the domain core to Pydantic.
- Frontend restructuring beyond what the audit-API mount requires.

## References

- `architecture.md` — target `lore-core/` package boundaries and dependency
  direction.
- `docs/superpowers/specs/2026-07-20-fileviewer-integration-design.md` — the
  prior FileViewer/audit read integration this builds on.
