# Design: Reconcile backend (`lore-agent-merge`) + frontend redesign (`frontend-done`) → PR into `main`

**Date:** 2026-07-23
**Status:** Approved (design), pending implementation plan
**Author:** Claude (paired with user)

## Problem

The backend and a frontend redesign were developed in parallel and their logic has
diverged. We must produce a single unified state that adopts the new UI **and**
preserves 100% of backend-driven functionality, then open a PR into `main`.

`main` is **not relevant** — its current content is stale and will be fully
overwritten by the PR. Only two branches matter:

- `lore-agent-merge` (HEAD, "current backend") — all backend Python + 23 frontend
  files wiring the new backend contracts (citations, warnings, execution-trace,
  progressive-chunk FileViewer).
- `frontend-done` = `lore-agent-merge`'s branch point `58496b6` + **one** commit
  `e21d3ea "Apply frontend UI updates"` (29 `frontend/` files, a UI/UX redesign).
  Contains **none** of the ~30 backend commits.

## Topology

```
main (c8f5f96, stale — ignore, overwrite via PR)
  └─ ... shared history ...
       └─ 58496b6  ← merge-base
            ├─ e21d3ea  "Apply frontend UI updates"   → frontend-done (redesign, 29 files)
            └─ ...~30 backend commits...              → lore-agent-merge (HEAD, base)
```

## Frontend reconciliation surface (authoritative, computed via `git diff`)

`git diff --name-only 58496b6 <ref> | grep '^frontend/'` on each side yields:

| Category | Count | Files | git behavior | Risk |
|---|---|---|---|---|
| **Conflict** (both changed) | 4 | `AssistantMessage.tsx`+`.module.css`, `FilesPage.tsx`+`.module.css` | Marks conflict | Manual reconciliation |
| **Backend-only** | 19 | `chat/citations*`, `chat/citationMarkers*`, `chat/warnings*`, `chat/sessionUi.ts`, `chat/ChainlitRuntimeProvider.tsx`, `components/Citations/*`, `components/Warnings/*`, `components/ExecutionSteps/ExecutionSteps.test.tsx`, `features/files/apiFilesProvider*`, `features/files/chunkState*`, `features/files/filesProvider.ts`, `features/files/mappers.ts` | Kept as-is | **Silent loss** — redesigned components may no longer import/render them |
| **Redesign-only** | ~25 | `App.tsx`, `Sidebar/*`, `ChatComposer/*`, `ChatHeader/*`, `MessageList/*`, `ChatList/*`, `UserMessage/*`, `styles/global.css`, `chat/chatDates.ts`, `router/*`, `types/chat.ts`, … | Applied clean | Verify redesign didn't drop calls into the backend-only modules |

Backend Python (`packages/`, `services/**/*.py`, ~300 files) merges with **no
conflict** — `frontend-done` never touched it.

## Key risks

1. **Silent functional loss.** A no-conflict auto-merge can still drop functionality:
   git takes the redesign version of a redesign-only file (e.g. `MessageList.tsx`,
   `App.tsx`) that was written without the backend wiring, so imports of
   `Citations`/`Warnings`/`ExecutionSteps`/`sessionUi` vanish with no conflict marker.
   Mitigation: **importer audit** (Step 3).
2. **Flaky git sandbox.** In this environment `ls-tree -r`/pathspec tree-walks return
   empty (`main` shows 0 files) while `log`/`diff`/`cat-file` are correct — consistent
   with a restricted sandbox view. A real `git merge`/`checkout` could be corrupted.
   Mitigation: **pre-flight** verification (Step 0); fall back to
   `dangerouslyDisableSandbox` for git if needed.

## Approach (chosen: A — "merge + functional audit")

Base = `lore-agent-merge` (backend + wiring already inside). Merge `frontend-done`
so git mechanically does the ~90% that is unambiguous and surfaces exactly the 4
collision files. Full functional preservation is the default; the visual redesign is
opt-in per file. Then an explicit audit closes the silent-loss gap.

Rejected: (B) full manual per-file rebuild — slow, regression-prone, discards a
correct auto-merge. (C) take redesign wholesale, re-add wiring after — guarantees
functional loss, contradicts the requirement.

## Process

**Branch:** `merge-lore-frontend` off `lore-agent-merge`. Work in place (no parallel
process). Final deliverable: PR `merge-lore-frontend → main` (main content overwritten).

**Step 0 — Pre-flight (environment trust).** Trial `git merge --no-commit --no-ff
frontend-done`; confirm the working tree and file counts are sane (not emptied by
sandbox flakiness) and `git status` lists the expected conflicts. If tree-walk/checkout
misbehaves, redo git operations under `dangerouslyDisableSandbox`. Do not proceed to
reconciliation without a green pre-flight.

**Step 1 — Mechanical merge.** `git merge frontend-done`. Expect: backend Python clean;
25 redesign-only files applied clean; 19 backend-only files kept; conflict in exactly
the 4 files.

**Step 2 — Reconcile the 4 conflict files.** Per file: take the **visual/structural
base from the redesign**, weld in the **functional logic from backend**:
- `AssistantMessage.tsx`/`.module.css`: render citations, warnings, and the
  execution-trace `{input, output}` inside the redesigned message layout.
- `FilesPage.tsx`/`.module.css`: keep progressive-chunk loading, `apiFilesProvider`,
  `chunkState` inside the redesigned files view.
No logic branch dropped.

**Step 3 — Silent-loss audit (core of the task).** For each of the 19 backend-only
modules, `grep` its importers. Where the importer is a redesign-only file, confirm the
redesign version still calls/renders it; where lost, restore the wiring while keeping
the new look. Produce a checklist: `feature → where rendered → confirmed`.

Functional inventory that MUST survive:
- Citations: `citations`, `citationMarkers`, `components/Citations`
- Warnings: `warnings`, `components/Warnings`
- Execution-trace `{input, output}`: `ExecutionSteps`
- Progressive-chunk FileViewer: `FilesPage`, `apiFilesProvider`, `chunkState`,
  `mappers`, `filesProvider`
- Session / runtime: `sessionUi`, `ChainlitRuntimeProvider`

**Step 4 — Verification (bar: build + tests + audit).** Node 18+ required (default
shell Node is v16 → use nvm v22 bin). `npm ci` → `npm test` (all frontend tests,
incl. citations/warnings/chunkState/apiFilesProvider, green) → `npm run build` (Vite,
no errors). Run affected backend Python tests. Audit checklist from Step 3 fully passed.

**Step 5 — PR into `main`.** Honest commit message(s): what merged, which 4 files were
hand-reconciled, audit result. Open PR `merge-lore-frontend → main`. **Do not push or
merge without explicit user approval** (a UI change once landed on main accidentally —
be careful).

## Scope / YAGNI

Reconcile existing functionality only. No refactoring, no new features, no directory
restructuring. The redesign's look + the backend's behavior, welded — nothing more.

## Success criteria

- `merge-lore-frontend` builds and all tests pass (frontend + affected backend).
- Every item in the Step-3 functional inventory is confirmed rendered/wired in the
  redesigned UI.
- No backend logic branch silently dropped by the merge.
- PR opened into `main`; nothing pushed/merged without approval.
