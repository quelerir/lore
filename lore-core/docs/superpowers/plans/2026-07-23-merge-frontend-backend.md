# Reconcile backend + frontend redesign → main — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Merge the backend line (`lore-agent-merge`) with the frontend redesign (`frontend-done`) into one branch that adopts the new UI while preserving 100% of backend-driven functionality, then open a PR into `main`.

**Architecture:** Base = `lore-agent-merge` (already contains all backend + the 23 frontend files wiring the new backend contracts). Run a real `git merge frontend-done` so git mechanically resolves the unambiguous ~90% and surfaces exactly 4 conflict files. Hand-reconcile those 4 (redesign look + backend logic), then run an importer audit to catch functionality silently dropped by no-conflict auto-merges. Gate on build + tests + audit.

**Tech Stack:** React 18, TypeScript 7, Vite 6, Vitest 3, happy-dom (frontend at `frontend/`); Python backend in `packages/` + `services/` (uv workspace, Python 3.13).

## Global Constraints

- Work on branch `merge-lore-frontend` (already created off `lore-agent-merge`, spec already committed). Work in place; no parallel process holds HEAD.
- `main` is stale — never rely on its content; it will be overwritten by the PR.
- Node **18+** required (Vite 6). Default shell Node is v16 → use the nvm v22 bin. Verify with `node -v` before any npm command.
- Frontend commands run from `frontend/`. Repo root: `/Users/stamplevskiyd/development/lore/lore-core` (referenced below as `$R`).
- This sandbox's git is flaky on tree-walk/pathspec reads (`ls-tree -r` returns empty; `main` shows 0 files) while `log`/`diff`/`cat-file`/`show` are correct. If any git write (`merge`/`checkout`) produces an obviously wrong tree (e.g. emptied working dir), re-run that git command with `dangerouslyDisableSandbox: true`.
- Preserve every backend logic branch. The redesign supplies look; the backend supplies behavior. Never drop behavior to keep looks.
- Do NOT push or merge the PR without explicit user approval.
- No refactoring, no new features, no directory restructuring. Reconcile existing functionality only.

## File map

**Conflict files (hand-reconciled — Tasks 2–3):**
- `frontend/src/components/AssistantMessage/AssistantMessage.tsx`
- `frontend/src/components/AssistantMessage/AssistantMessage.module.css`
- `frontend/src/features/files/FilesPage.tsx`
- `frontend/src/features/files/FilesPage.module.css`

**Backend-only frontend modules that MUST stay wired (audited — Task 4):**
- `frontend/src/chat/`: `citations.ts`, `citationMarkers.ts`, `warnings.ts`, `sessionUi.ts`, `ChainlitRuntimeProvider.tsx` (+ `*.test.ts`)
- `frontend/src/components/Citations/`, `frontend/src/components/Warnings/`, `frontend/src/components/ExecutionSteps/ExecutionSteps.test.tsx`
- `frontend/src/features/files/`: `apiFilesProvider.ts`, `chunkState.ts`, `filesProvider.ts`, `mappers.ts` (+ `*.test.ts`)

**Redesign-only files (auto-applied, spot-checked in Task 4):** `App.tsx`, `components/Sidebar/*`, `components/ChatComposer/*`, `components/ChatHeader/*`, `components/MessageList/*`, `components/ChatList/*`, `components/UserMessage/*`, `styles/global.css`, `chat/chatDates.ts`, `chat/threadToChat.ts`, `router/AppRouter.tsx`, `types/chat.ts`, `index.html`, `public/favicon.svg`.

---

### Task 0: Pre-flight — trust the git environment

**Files:** none (verification only).

**Interfaces:**
- Produces: confidence that `git merge`/`checkout` behave correctly in this sandbox, plus a local ref `frontend-done` tracking `origin/frontend-done`.

- [ ] **Step 1: Confirm base state and create a local tracking ref**

Run:
```bash
git -C $R rev-parse --abbrev-ref HEAD        # expect: merge-lore-frontend
git -C $R branch -f frontend-done origin/frontend-done
git -C $R rev-parse frontend-done            # expect: e21d3eaa0c68950701ba75e6f0ad439890880603
```

- [ ] **Step 2: Trial merge WITHOUT committing**

Run:
```bash
git -C $R merge --no-commit --no-ff frontend-done ; echo "exit=$?"
```
Expected: merge stops with conflicts (exit non-zero) and prints `CONFLICT (content):` lines.

- [ ] **Step 3: Verify the tree is sane (sandbox not emptying it) and conflicts match the design**

Run:
```bash
git -C $R status --porcelain | grep -E '^(UU|AA|U|DD)' | sort
git -C $R status --porcelain | wc -l
ls "$R/frontend/src/App.tsx" "$R/services/lore-chat/app.py" && echo "TREE OK"
```
Expected: exactly these 4 conflicted paths —
`frontend/src/components/AssistantMessage/AssistantMessage.tsx`,
`frontend/src/components/AssistantMessage/AssistantMessage.module.css`,
`frontend/src/features/files/FilesPage.tsx`,
`frontend/src/features/files/FilesPage.module.css`;
both `ls` paths exist; `TREE OK` printed. If the working dir looks emptied or conflicts differ, abort and re-run Step 2 under `dangerouslyDisableSandbox`.

- [ ] **Step 4: Abort the trial merge (clean slate for the real run)**

Run:
```bash
git -C $R merge --abort && git -C $R status -sb | head -1
```
Expected: clean tree on `merge-lore-frontend`.

---

### Task 1: Mechanical merge

**Files:** whole tree (git-driven).

**Interfaces:**
- Consumes: green pre-flight from Task 0.
- Produces: an in-progress merge with all non-conflicting changes staged and exactly 4 conflict files left for Tasks 2–3.

- [ ] **Step 1: Start the real merge**

Run:
```bash
git -C $R merge --no-ff frontend-done ; echo "exit=$?"
```
Expected: `CONFLICT` on the 4 files; merge paused (not committed).

- [ ] **Step 2: Verify backend Python merged clean (no conflicts outside the 4 frontend files)**

Run:
```bash
git -C $R status --porcelain | grep -E '^(UU|AA|DD|U.|.U)' | sort
```
Expected: only the 4 `frontend/...AssistantMessage...` and `frontend/...FilesPage...` paths. Any Python (`.py`) conflict here means the assumption broke — stop and investigate before continuing.

- [ ] **Step 3: Snapshot each conflict's two sides for reference during reconciliation**

Run:
```bash
for f in \
  frontend/src/components/AssistantMessage/AssistantMessage.tsx \
  frontend/src/components/AssistantMessage/AssistantMessage.module.css \
  frontend/src/features/files/FilesPage.tsx \
  frontend/src/features/files/FilesPage.module.css ; do
    git -C $R show HEAD:$f      > "/tmp/OURS_$(basename $f)"
    git -C $R show frontend-done:$f > "/tmp/THEIRS_$(basename $f)"
done
ls -la /tmp/OURS_* /tmp/THEIRS_*
```
Expected: 8 files written — `OURS_*` = backend-wired version, `THEIRS_*` = redesign version.

- [ ] **Step 4: Do NOT commit yet.** Leave the merge in progress; proceed to Task 2.

---

### Task 2: Reconcile `AssistantMessage` (redesign look + backend rendering)

**Files:**
- Modify: `frontend/src/components/AssistantMessage/AssistantMessage.tsx`
- Modify: `frontend/src/components/AssistantMessage/AssistantMessage.module.css`

**Interfaces:**
- Consumes: `/tmp/OURS_AssistantMessage.tsx` (backend rendering of citations/warnings/execution-trace) and `/tmp/THEIRS_AssistantMessage.tsx` (redesigned layout).
- Produces: a single `AssistantMessage.tsx` with the redesigned markup AND every backend render path intact.

**Backend render paths that MUST survive (from `/tmp/OURS_AssistantMessage.tsx`):** rendering of `<Citations>` (from `../Citations/Citations`), `<Warnings>` (from `../Warnings/Warnings`), the execution-trace `{input, output}` via `ExecutionSteps`, and any use of `citationMarkers`/`citations`/`warnings` helpers from `../../chat/`.

- [ ] **Step 1: Read both sides**

Read `/tmp/OURS_AssistantMessage.tsx`, `/tmp/THEIRS_AssistantMessage.tsx`, and the conflicted `frontend/src/components/AssistantMessage/AssistantMessage.tsx`. List, from OURS, every import and JSX element tied to citations, warnings, execution-trace, and node_io.

- [ ] **Step 2: Reconcile the TSX**

Take THEIRS (redesign) as the structural base. Re-insert each backend render path from Step 1 into the redesigned markup so citations, warnings, and the execution-trace `{input, output}` still render. Resolve imports to include both the redesign's and the backend's. Remove all conflict markers.

- [ ] **Step 3: Reconcile the CSS**

In `AssistantMessage.module.css`, keep the redesign's classes (THEIRS) and add back any class selectors referenced by the backend render paths that only existed in OURS (e.g. citation/warning/trace containers). Remove all conflict markers.

- [ ] **Step 4: Stage and type-check just this component's graph**

Run:
```bash
git -C $R add frontend/src/components/AssistantMessage/
cd $R/frontend && npx tsc -b --noEmit 2>&1 | grep -i AssistantMessage || echo "no AssistantMessage type errors"
```
Expected: `no AssistantMessage type errors`.

- [ ] **Step 5: Run the component + wiring tests**

Run:
```bash
cd $R/frontend && npx vitest run src/components/ExecutionSteps src/chat/citations src/chat/warnings src/chat/citationMarkers 2>&1 | tail -20
```
Expected: all pass. (These lock the contracts `AssistantMessage` must honor.)

- [ ] **Step 6: Commit is deferred** — the merge is one atomic commit created in Task 5. Leave changes staged.

---

### Task 3: Reconcile `FilesPage` (redesign look + progressive-chunk FileViewer)

**Files:**
- Modify: `frontend/src/features/files/FilesPage.tsx`
- Modify: `frontend/src/features/files/FilesPage.module.css`

**Interfaces:**
- Consumes: `/tmp/OURS_FilesPage.tsx` (progressive-chunk loading via `apiFilesProvider`, `chunkState`, `mappers`, `filesProvider`) and `/tmp/THEIRS_FilesPage.tsx` (redesigned files view).
- Produces: one `FilesPage.tsx` with the redesigned view AND the full progressive-chunk data flow.

**Backend data flow that MUST survive (from `/tmp/OURS_FilesPage.tsx`):** imports/calls into `./apiFilesProvider`, `./chunkState`, `./mappers`, `./filesProvider`; progressive chunk loading (load-beyond-preview-cap, deep-link to cited chunk, newest-first run sort, non-self-cancelling stream previews).

- [ ] **Step 1: Read both sides**

Read `/tmp/OURS_FilesPage.tsx`, `/tmp/THEIRS_FilesPage.tsx`, and the conflicted file. List, from OURS, every provider/hook/state tied to chunk loading and citations deep-linking.

- [ ] **Step 2: Reconcile the TSX**

Take THEIRS (redesign) as structural base. Re-wire each backend data path from Step 1 so progressive chunk loading, deep-linking to the cited chunk, and run ordering still work. Resolve imports to the union. Remove all conflict markers.

- [ ] **Step 3: Reconcile the CSS**

Keep redesign classes (THEIRS); add back selectors used only by the chunk/preview UI that existed in OURS. Remove all conflict markers.

- [ ] **Step 4: Stage and type-check**

Run:
```bash
git -C $R add frontend/src/features/files/
cd $R/frontend && npx tsc -b --noEmit 2>&1 | grep -iE 'FilesPage|features/files' || echo "no files-feature type errors"
```
Expected: `no files-feature type errors`.

- [ ] **Step 5: Run the files-feature tests**

Run:
```bash
cd $R/frontend && npx vitest run src/features/files 2>&1 | tail -20
```
Expected: `apiFilesProvider.test`, `chunkState.test` (and any others) pass.

- [ ] **Step 6: Commit deferred** — leave staged for Task 5.

---

### Task 4: Silent-loss importer audit + rewire

**Files:** any redesign-only file that dropped a backend import (discovered here). Likely candidates: `frontend/src/components/MessageList/MessageList.tsx`, `frontend/src/App.tsx`, `frontend/src/chat/threadToChat.ts`.

**Interfaces:**
- Consumes: the merged tree from Tasks 1–3.
- Produces: a written `feature → importer → status` checklist, and restored wiring wherever a redesign-only file silently dropped a backend module.

- [ ] **Step 1: Find importers of every backend-only module**

Run (from `$R/frontend`):
```bash
cd $R/frontend
for m in Citations Warnings ExecutionSteps citations citationMarkers warnings sessionUi apiFilesProvider chunkState mappers filesProvider ChainlitRuntimeProvider ; do
  echo "### $m"
  grep -rn --include=*.ts --include=*.tsx -E "from ['\"].*${m}['\"]|import .*${m}" src | grep -v ".test." | grep -viE "/${m}(/|\.|['\"])" || echo "  (no external importers)"
done
```
This lists who imports each backend module (excluding the module's own files/tests).

- [ ] **Step 2: Compare against the pre-merge backend baseline**

For each module, compare current importers to the backend line's importers:
```bash
for m in Citations Warnings ExecutionSteps sessionUi ; do
  echo "### $m  (baseline lore-agent-merge)"
  git -C $R grep -n -E "${m}" lore-agent-merge -- 'frontend/src/**/*.tsx' 'frontend/src/**/*.ts' | grep -v ".test." | grep -viE "/${m}(/|\.)" || echo "  none"
done
```
Any importer present in the baseline but absent now = a **silent loss**. Record it.

- [ ] **Step 3: Restore each lost wiring**

For every silent loss found: open the redesign-only importer file, re-add the import and the render/call site from the baseline version (`git -C $R show lore-agent-merge:<path>`), fitting it into the redesigned markup. Keep the new look; restore the behavior.

- [ ] **Step 4: Write the audit checklist into the merge commit body draft**

Create `/tmp/AUDIT.md` with one line per feature:
```
Citations       → <file:line where rendered>   → CONFIRMED
Warnings        → <file:line>                   → CONFIRMED
ExecutionSteps  → <file:line>                   → CONFIRMED
FileViewer(chunks) → FilesPage.tsx:<line>       → CONFIRMED
sessionUi/runtime  → <file:line>                → CONFIRMED
```
Every line must read CONFIRMED before proceeding.

- [ ] **Step 5: Stage any rewired files**

Run:
```bash
git -C $R add frontend/src
git -C $R status --porcelain | grep -E '^(UU|AA|U|DD)' && echo "STILL CONFLICTED — fix before continuing" || echo "no conflict markers remain"
```
Expected: `no conflict markers remain`.

---

### Task 5: Full verification + create the merge commit

**Files:** none new (verification + commit).

**Interfaces:**
- Consumes: fully reconciled, staged tree.
- Produces: one merge commit on `merge-lore-frontend`.

- [ ] **Step 1: Confirm Node 18+**

Run:
```bash
node -v   # if < 18, load nvm v22 bin first, then re-check
```
Expected: `v18` or higher (v22 per environment).

- [ ] **Step 2: Install and run the full frontend test suite**

Run:
```bash
cd $R/frontend && npm ci && npx vitest run 2>&1 | tail -30
```
Expected: entire suite green (citations, warnings, citationMarkers, chunkState, apiFilesProvider, ExecutionSteps, plus redesign tests).

- [ ] **Step 3: Full production build**

Run:
```bash
cd $R/frontend && npm run build 2>&1 | tail -30
```
Expected: `tsc -b` clean, `vite build` succeeds, no errors.

- [ ] **Step 4: Run affected backend Python tests**

Run:
```bash
cd $R && uv run pytest services/lore-chat/tests -q 2>&1 | tail -20
```
Expected: pass (backend was merged clean; this is a regression guard).

- [ ] **Step 5: Create the merge commit with an honest body**

Run:
```bash
git -C $R commit --no-edit 2>/dev/null || git -C $R commit -F - <<'MSG'
merge: reconcile frontend redesign (frontend-done) into backend line

Adopts the frontend-done UI redesign while preserving all backend-wired
functionality. Hand-reconciled 4 conflict files:
- AssistantMessage.tsx/.module.css — redesign layout + citations/warnings/execution-trace rendering
- FilesPage.tsx/.module.css       — redesign view + progressive-chunk FileViewer

Silent-loss audit (importers of citations/warnings/ExecutionSteps/sessionUi/
chunk providers) passed — see body checklist. Frontend build + full vitest
suite green; affected backend pytest green.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
MSG
git -C $R log --oneline -1
```
Expected: merge commit recorded on `merge-lore-frontend`.

---

### Task 6: Open PR into `main`

**Files:** none.

**Interfaces:**
- Consumes: verified `merge-lore-frontend`.
- Produces: a PR into `main`. Nothing merged/pushed without user approval beyond opening the PR.

- [ ] **Step 1: Push the branch**

Run:
```bash
git -C $R push -u origin merge-lore-frontend
```

- [ ] **Step 2: Open the PR**

Run:
```bash
gh -C $R pr create --base main --head merge-lore-frontend \
  --title "Merge frontend redesign + backend into main" \
  --body "$(cat <<'BODY'
Reconciles the frontend redesign (`frontend-done`) with the backend line
(`lore-agent-merge`) into a single state. `main` is stale and fully replaced.

- 4 conflict files hand-reconciled (redesign look + backend behavior).
- Silent-loss importer audit passed (citations, warnings, execution-trace,
  progressive-chunk FileViewer, session/runtime all confirmed wired).
- Frontend build + full vitest suite green; affected backend pytest green.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
BODY
)"
```

- [ ] **Step 3: Report the PR URL to the user and STOP.** Do not merge without explicit approval.

## Self-Review

- **Spec coverage:** Pre-flight (Step 0 risk) → Task 0. Mechanical merge → Task 1. 4 conflict files → Tasks 2–3. Silent-loss audit + functional inventory → Task 4. Build+tests+audit bar → Task 5. PR into main → Task 6. All spec sections covered.
- **Placeholder scan:** Conflict-resolution tasks give exact procedure + exact preservation lists + exact verify commands rather than literal merged source, because the merged source is produced from the actual conflict during execution — this is inherent to a merge, not a placeholder. All commands and paths are concrete.
- **Type/name consistency:** Module names (`apiFilesProvider`, `chunkState`, `citationMarkers`, `ExecutionSteps`, `sessionUi`, `ChainlitRuntimeProvider`) match across File map, Tasks 2–4, and the audit loop.
