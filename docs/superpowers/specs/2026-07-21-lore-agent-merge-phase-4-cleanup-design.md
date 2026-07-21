# Phase 4 — Final Cleanup — Design Spec

**Branch:** `lore-agent-merge` · **Date:** 2026-07-21 · **Status:** approved (design)

The final phase of the lore↔agent-lore monorepo merge. Phases 0–3 delivered the full functional merge; nothing is broken. Phase 4 is **tidiness only**: finish the last mile of the refactor (remove transitional shims), clear lint, tidy git/docs hygiene, and add a regression guard for the merge's core purity invariant.

## Goal

Leave the repository in a clean, final state: one canonical import path per symbol (no transitional shims), zero lint findings in the packages/services, no stray tracked artifacts, no stale docs, and an automated guard that the pure packages cannot silently re-couple to forbidden dependencies.

## Context

- During the merge, two 1000+ line monoliths were split into subpackages and the old filenames kept as thin re-export shims so importers didn't all need updating at once:
  - `lore_audit/read_contracts.py` → re-exports `lore_audit.read` (read-side request/response/enum/error contracts)
  - `lore_audit/read_repositories.py` → re-exports `lore_audit.repository` (read-side repository)
- The Phase-4 inventory found **no MUST/broken items**. The re-export shims are load-bearing (≈16 active importers), 5 minor ruff findings exist, one stray untracked `.chainlit/` directory, a few tracked `.pytest_cache/README.md`, and one superseded plan doc. Root `README`, `lore-core/README.md`, and `architecture.md` are already current.
- The merge's central invariant — the pure packages (`lore_core_domain`, `lore_audit`, `lore_splitter`) never import `airflow`/`fastapi`/`pydantic`/`chainlit` — is currently not guarded by any test.

## Approved Decision

**Remove the re-export shims (finish the refactor).** Repoint all importers to the canonical paths and delete the shim files, rather than keeping the shims as a stable facade. This gives one canonical import path per symbol (matching the project's "no duplicate paths for the same thing" principle) and completes the split the merge started.

## Slices

### Slice 1 — Remove re-export shims
Repoint every importer of the two shims to the canonical subpackages, then delete the shim files:
- `from lore_audit.read_contracts import X` → `from lore_audit.read import X`
- `from lore_audit.read_repositories import X` → `from lore_audit.repository import X`

Importers span `lore-audit-core` (`repository/mapping.py`), `lore-audit-api` (factory, http/routes, tests), and `lore-chat`. The plan enumerates the exact call sites. After repointing, delete `lore_audit/read_contracts.py` and `lore_audit/read_repositories.py`. Verify the three suites stay green: audit-core 156, audit-api 96/1, chat 121/1.

### Slice 2 — Lint fixes
Resolve the 5 ruff findings so `ruff check lore-core/packages lore-core/services` is clean:
- `repository/mapping.py` — remove unused `CursorCodec`, `AuditReadError` imports.
- `lore-audit-api/tests/test_http_routes.py` — move the module-level import block to the top of the file (E402).
- `lore-audit-api/tests/test_settings.py` — remove unused `pytest` import.
- (The two `read_contracts.py` findings disappear with Slice 1's deletion.)

### Slice 3 — Git hygiene
- Delete the stray untracked `lore-core/.chainlit/` (a duplicate of the canonical root `.chainlit/`, created by running Chainlit from that dir).
- Untrack the accidentally-committed `.pytest_cache/README.md` file(s) via `git rm --cached`.
- Add `.gitignore` entries where missing so `.chainlit/` (outside root), `.pytest_cache/`, `__pycache__/`, and `.venv/` stay untracked going forward.

### Slice 4 — Docs sweep (minimal)
- Mark `docs/superpowers/plans/2026-07-20-fileviewer-integration.md` as **superseded** (a short banner at top): it describes the abandoned `backend/audit/` vendoring approach; the actual integration is `audit_mount.py` + `audit_auth.py` in `lore-chat`.
- Spot-check `docs/deployment.md` and `docs/usage.md` for stale `backend/` paths or pre-merge layout references; fix any found.
- Root `README`, `lore-core/README.md`, `architecture.md` were verified current — no change expected.

### Slice 5 — Purity regression guard
Add a test (in `lore-core-domain`'s tests, or a small shared test) that imports each pure package and asserts its transitive module set excludes the forbidden dependencies:
- `lore_core_domain` — no third-party imports at all (stdlib-only).
- `lore_audit` — no `airflow`, `fastapi`, `pydantic`, `chainlit`.
- `lore_splitter` — no `airflow` (it legitimately uses psycopg + doc libs, so the guard targets `airflow` specifically).

Implementation approach: import the package's public modules in a subprocess/fresh interpreter and assert none of the forbidden top-level names appear in `sys.modules`, or statically scan the source tree for forbidden `import`/`from` statements. The plan picks the concrete mechanism; the guard must fail loudly if a future edit re-couples a pure package.

## Non-Goals

- No functional changes, no new features, no API changes (beyond deleting the two shim modules).
- No broad documentation rewrite — only stale-reference fixes.
- No merge to `main` as part of this phase (that is a separate decision after Phase 4).

## Success Criteria

- The two shim files are gone; no code imports `lore_audit.read_contracts` or `lore_audit.read_repositories`.
- `ruff check lore-core/packages lore-core/services` reports no errors.
- `git status` shows no stray `.chainlit/`; `.pytest_cache/README.md` no longer tracked; `.gitignore` covers the artifact classes.
- The superseded plan doc carries a banner; no stale `backend/` path in the swept docs.
- The purity guard test passes and fails when a forbidden import is introduced.
- All suites green: audit-core 156, audit-api 96/1, chat 121/1, lore-splitter 284/0, provider 69/2-skipped.

## Slice Order

1 (shims) → 2 (lint) → 3 (git hygiene) → 4 (docs) → 5 (purity guard). Each is an independently verifiable deliverable.
