# Lore↔agent-lore Merge — Phase 0: Monorepo Skeleton

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Relocate the current Chainlit chat backend into the monorepo layout (`backend/` → `lore-core/services/lore-chat/`) and create the empty engine scaffold, with **zero behavior change**.

**Architecture:** Pure structural move. The chat service stays self-contained (its own `pyproject.toml` + `uv.lock`, unchanged deps), so the Dockerfile keeps working as-is. All references to the old `backend/` path (docker-compose build context, schema volume, studio sys.path shim, docs) are updated. Empty scaffold dirs are created for the engine packages that land in later phases.

**Tech Stack:** Python 3.13, uv, Chainlit, docker-compose.

## Global Constraints

- Branch: `lore-agent-merge` (already checked out).
- **No behavior change in Phase 0** — the running app, its tests, and FileViewer must behave exactly as before the move.
- Everything targets Python **3.13**; missing deps added via uv.
- The chat service stays self-contained: **do NOT introduce a uv workspace or a shared `lore-core/config/` in this phase.** Both are deferred to the start of Phase 1, where the first cross-package dependency (`lore-audit-core`) makes them necessary. (This refines the design spec, which listed them under Phase 0; deferring avoids destabilizing the working app before there is anything to share.)
- Chat concerns (`agents/`, `toast/`, `evals/`, `audit/`) move *with* the chat service unchanged. The vendored `audit/` is replaced only in Phase 1.

**Target layout after this phase:**

```text
lore/  (branch lore-agent-merge)
├── docker-compose.yml
├── frontend/
└── lore-core/
    ├── services/
    │   ├── lore-chat/          # ← former backend/ (unchanged internals)
    │   └── lore-audit-api/     # empty placeholder (.gitkeep)
    ├── packages/               # empty placeholder (.gitkeep)
    └── airflow-providers/      # empty placeholder (.gitkeep)
```

---

### Task 1: Relocate the chat backend directory

**Files:**
- Move: `backend/` → `lore-core/services/lore-chat/` (all tracked files, via `git mv`)
- Delete first (untracked, regenerable caches): `backend/.venv`, `backend/__pycache__`, `backend/.pytest_cache`, `backend/.mypy_cache`, `backend/.ruff_cache`

**Interfaces:**
- Consumes: nothing (first task).
- Produces: the chat service at `lore-core/services/lore-chat/` with `app.py`, `config.py`, `auth.py`, `pyproject.toml`, `uv.lock`, `Dockerfile`, and packages `agents/ audit/ evals/ toast/ init/ tests/` at that root. Later tasks reference this path.

- [ ] **Step 1: Remove regenerable caches so `git mv` moves a clean tree**

```bash
cd /Users/stamplevskiyd/development/lore
rm -rf backend/.venv backend/__pycache__ backend/.pytest_cache backend/.mypy_cache backend/.ruff_cache
```

- [ ] **Step 2: Create the parent dir and move the tree with git**

```bash
mkdir -p lore-core/services
git mv backend lore-core/services/lore-chat
```

- [ ] **Step 3: Verify the move is staged as renames and nothing is left behind**

Run:
```bash
ls backend 2>/dev/null && echo "LEFTOVER: backend/ still exists" || echo "OK: backend/ gone"
ls lore-core/services/lore-chat/app.py lore-core/services/lore-chat/pyproject.toml lore-core/services/lore-chat/Dockerfile
git status --short | grep -c '^R' 
```
Expected: `OK: backend/ gone`; the three files listed; a non-zero count of staged renames (`R`).

- [ ] **Step 4: Verify the chat service still builds its env and passes tests in the new location**

Run:
```bash
cd /Users/stamplevskiyd/development/lore/lore-core/services/lore-chat
uv sync --frozen
uv run pytest -q
```
Expected: `uv sync` succeeds; the existing suite passes (same result as before the move — all tests that passed still pass). If any test fails, it must be a pre-existing failure unrelated to the move (confirm by comparing against `git stash`-ed baseline if unsure).

- [ ] **Step 5: Commit**

```bash
cd /Users/stamplevskiyd/development/lore
git add -A
git commit -m "refactor(merge): relocate chat backend to lore-core/services/lore-chat

Phase 0 of the lore<->agent-lore monorepo merge. Pure move, no behavior change.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 2: Repoint docker-compose at the new chat location

**Files:**
- Modify: `docker-compose.yml` (backend service `build:` context, service name `backend` → `chat`, frontend `depends_on`, chainlit-db schema volume path)

**Interfaces:**
- Consumes: chat service at `lore-core/services/lore-chat/` (Task 1).
- Produces: a compose stack whose chat service is named `chat` and builds from the new path. No other service references the chat service except `frontend.depends_on`.

- [ ] **Step 1: Update the build context and rename the service to `chat`**

In `docker-compose.yml`, change the service key `backend:` to `chat:` and its build line:

```yaml
  chat:
    build: ./lore-core/services/lore-chat
```
(Everything else under the service — `env_file`, `environment`, `extra_hosts`, `ports`, `restart`, `depends_on`, `healthcheck` — stays byte-for-byte the same.)

- [ ] **Step 2: Update the frontend `depends_on` to reference `chat`**

In the `frontend` service:

```yaml
    depends_on:
      chat:
        condition: service_healthy
```

- [ ] **Step 3: Update the chainlit-db schema volume path**

In the `chainlit-db` service `volumes:`:

```yaml
      - ./lore-core/services/lore-chat/init/schema.sql:/docker-entrypoint-initdb.d/schema.sql:ro
```

- [ ] **Step 4: Verify compose parses and the chat image builds**

Run:
```bash
cd /Users/stamplevskiyd/development/lore
docker compose config >/dev/null && echo "compose config OK"
docker compose build chat
```
Expected: `compose config OK`; the `chat` image builds successfully (uv sync + copy, no path errors).

- [ ] **Step 5: Verify the stack comes up healthy and the app serves**

Run:
```bash
cd /Users/stamplevskiyd/development/lore
docker compose up -d
docker compose ps
```
Expected: `chat` reaches `healthy`; `frontend` starts after it. Manually confirm `http://localhost:3000` loads the chat and (with `FILES_PROVIDER=api`) the FileViewer at `/files` still works, exactly as before. Then `docker compose down`.

- [ ] **Step 6: Commit**

```bash
git add docker-compose.yml
git commit -m "refactor(merge): point docker-compose at lore-core/services/lore-chat

Rename backend service to chat; update build context and schema volume path.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 3: Update the studio sys.path shim and doc references

**Files:**
- Modify: `studio/graph.py` (the `_BACKEND` path shim)
- Modify: `studio/README.md`, `README.md`, `docs/deployment.md` (textual `backend/...` path references)

**Interfaces:**
- Consumes: chat service at `lore-core/services/lore-chat/` (Task 1).
- Produces: studio imports resolve against the new path; docs describe the new tree.

- [ ] **Step 1: Repoint the studio sys.path shim**

In `studio/graph.py`, replace the `_BACKEND` line:

```python
_BACKEND = os.path.join(os.path.dirname(__file__), "..", "lore-core", "services", "lore-chat")
```
(The `sys.path.insert` and the `from config ...` / `from toast ...` imports stay unchanged — they resolve against this path.)

- [ ] **Step 2: Verify studio still imports the graph**

Run:
```bash
cd /Users/stamplevskiyd/development/lore/studio
uv run python -c "import graph; print('studio graph import OK')"
```
Expected: `studio graph import OK` (it imports the factory module; it does not need live DB creds just to import).

- [ ] **Step 3: Update textual path references in docs**

Replace the stale `backend/...` paths with `lore-core/services/lore-chat/...`:
- `studio/README.md:3` — `backend/toast/sql_graph.py` → `lore-core/services/lore-chat/toast/sql_graph.py`
- `README.md:17` — the tree line `└── backend/` → `└── lore-core/services/lore-chat/`
- `README.md:87` — `backend/.chainlit/config.toml` → `lore-core/services/lore-chat/.chainlit/config.toml`
- `README.md:119` — `backend/agents/tools.py` → `lore-core/services/lore-chat/agents/tools.py`
- `README.md:122` — `backend/toast/` → `lore-core/services/lore-chat/toast/`
- `docs/deployment.md:114` — `backend/init/schema.sql` → `lore-core/services/lore-chat/init/schema.sql`
- `docs/deployment.md:158` — `backend/.chainlit/config.toml` → `lore-core/services/lore-chat/.chainlit/config.toml`

- [ ] **Step 4: Verify no stale `backend/` path references remain**

Run:
```bash
cd /Users/stamplevskiyd/development/lore
grep -rn "backend/" README.md docs/ studio/ docker-compose.yml --include='*.md' --include='*.yml' --include='*.py' | grep -v "lore-chat"
```
Expected: no output (every remaining match, if any, is an unrelated word, not a path — inspect to confirm none point at the old `backend/` tree).

- [ ] **Step 5: Commit**

```bash
git add studio/graph.py studio/README.md README.md docs/deployment.md
git commit -m "refactor(merge): repoint studio shim and docs at lore-core/services/lore-chat

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 4: Create the engine scaffold directories

**Files:**
- Create: `lore-core/packages/.gitkeep`
- Create: `lore-core/airflow-providers/.gitkeep`
- Create: `lore-core/services/lore-audit-api/.gitkeep`
- Create: `lore-core/README.md` (one short paragraph describing the monorepo layout and what lands where)

**Interfaces:**
- Consumes: `lore-core/services/lore-chat/` (Task 1).
- Produces: empty, committed scaffold dirs that Phases 1–3 populate.

- [ ] **Step 1: Create the placeholder directories**

```bash
cd /Users/stamplevskiyd/development/lore
mkdir -p lore-core/packages lore-core/airflow-providers lore-core/services/lore-audit-api
touch lore-core/packages/.gitkeep lore-core/airflow-providers/.gitkeep lore-core/services/lore-audit-api/.gitkeep
```

- [ ] **Step 2: Write `lore-core/README.md`**

```markdown
# lore-core

Root of the Lore Python monorepo. Merge in progress (branch `lore-agent-merge`);
see `docs/superpowers/specs/2026-07-20-lore-agent-merge-design.md`.

Layout:
- `services/lore-chat/` — Chainlit chat backend (product).
- `services/lore-audit-api/` — standalone audit read API (ASGI factory; Phase 1).
- `packages/lore-audit-core/` — audit rule engine + read domain (Phase 1).
- `packages/lore-splitter/` — document ingestion / chunking pipeline (Phase 2).
- `airflow-providers/apache-airflow-providers-lore/` — Airflow operators, DAGs,
  hooks; thin adapters over the packages (Phase 3). External Airflow only.
```

- [ ] **Step 3: Verify the target tree matches the design**

Run:
```bash
cd /Users/stamplevskiyd/development/lore
find lore-core -maxdepth 2 -type d | sort
```
Expected: shows `lore-core/services/lore-chat`, `lore-core/services/lore-audit-api`, `lore-core/packages`, `lore-core/airflow-providers`.

- [ ] **Step 4: Commit**

```bash
git add lore-core/README.md lore-core/packages/.gitkeep lore-core/airflow-providers/.gitkeep lore-core/services/lore-audit-api/.gitkeep
git commit -m "chore(merge): scaffold lore-core engine directories

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Self-Review

**Spec coverage (Phase 0 rows of the design):**
- `backend/` → `lore-core/` with chat under `services/lore-chat/` — Task 1. ✓
- Empty `packages/`/`services/`/`airflow-providers/` — Task 4. ✓
- docker-compose build context + schema volume updated — Task 2. ✓
- Imports/paths updated (studio shim, docs) — Task 3. ✓
- uv workspace + single `config/` — **deliberately deferred to Phase 1** (see Global Constraints); flagged, not dropped.
- Verify compose comes up, chat tests green, FileViewer works — Tasks 1 (tests), 2 (compose + FileViewer). ✓

**Placeholder scan:** none — every step has exact commands/paths.

**Type consistency:** no code interfaces introduced (structural move only); the one code edit (studio `_BACKEND`) preserves the existing import surface.

**Note on the service rename** (`backend` → `chat` in compose): the only in-compose consumer of the service name is `frontend.depends_on`, updated in Task 2. External URLs (`VITE_CHAINLIT_URL`, OAuth) use `localhost`/`authentik-server`, not the chat service name, so they are unaffected.
