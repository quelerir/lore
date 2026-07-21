# Lore — End-to-End Pipeline (Request → Answer)

Date: 2026-07-21
Status: integrating overview. This is the single "whole picture" document that stitches the
project's vertical slices together. It is intentionally high-level — each layer links to its own
detailed spec. Where a layer does not exist yet, this doc says so and points at the roadmap.

## Why this document exists

The project is documented as separate vertical slices (Splitter/ingestion, Audit, the SQL tool, the
chat agent) with **no single narrative from a user's question to the final answer**. In particular,
the retrieval layer that connects "Splitter produced chunks and TOAST tables" to "the SQL tool
receives a `chunk_id` and a `table`" is not yet built and, until the Neo4j milestone roadmap, was
not specified anywhere. This document is that missing map.

Read this first for orientation; follow the per-layer links for detail.

## The whole pipeline

```text
                          ┌───────────────────────────── OFFLINE / BATCH ─────────────────────────────┐

  source files ──▶  (1) SPLITTER  ──▶  lore_core.*  (canonical)          (2) PROJECTION ──▶  Neo4j
  (xlsx, md, pdf,      chunking +        chunks: chunk_id, 3 text views,      embeddings +       (derived,
   pptx, docx,         TOAST reg.        heading_path, hashes, chunk_type,    Document/Section/   rebuildable
   transcripts)                          payload_refs; TOAST tables in        Chunk graph +       projection)
                          │              splitter_toast schema                vector+fulltext
                          │                     │                             indexes
                          ▼                     │                                  │
                     (1b) AUDIT  ◀──────────────┘                                  │
                     verify run,                                                   │
                     read-only API                                                │
                          └───────────────────────────────────────────────────────┘

                          ┌───────────────────────────── ONLINE / PER TURN ───────────────────────────┐

  user question ──▶  (3) CHAT ENTRY  ──▶  (4) RETRIEVAL  ──────────────────────────────────────────┐
  (React SPA →          Chainlit +           A. TextChunk vector search                             │
   Chainlit WS)         LangGraph agent      B. TextChunk fulltext search                           │
                        (fast / deep)        C. TableChunk vector+fulltext (RRF + rerank)           │
                             │               → RRF fuse A+B, dedup by chunk_id                       │
                             │               → bounded structural expansion (fixed Cypher)          │
                             │               → cross-encoder rerank                                 │
                             │               → (5) section-aware auto-merging (ContextGroups)       │
                             │               → batch canonical evidence resolution (hash/version)   │
                             │                                                                       │
                             │                                    ┌──────────────────────────────────┘
                             │                                    ▼
                             │                          (6) TABLE LANE + SQL
                             │                          table candidates → schema feasibility
                             │                          → adaptive K≤5 → up to 5 INDEPENDENT
                             │                          read-only SQL calls over registered
                             │                          TOAST tables (parallel)
                             │                                    │
                             ▼                                    ▼
                      (7) TOP-LEVEL AGENT ARBITRATION  ◀──────────┘
                      receives ContextGroups + individual evidence + structural provenance
                      + table candidates + SQLResult[] + citations → chooses evidence
                             │
                             ▼
                      (8) FINAL ANSWER  (LangGraph owns the prompt + model call)
                             │
                             ▼
                      React SPA + Postgres history        Langfuse trace (project_id="loreagent")
                                                          spans every stage above
                          └────────────────────────────────────────────────────────────────────────┘
```

Legend for status: **(1)(1b)** exist and ship today. **(3)(6-partial)** exist but are not yet
connected as drawn. **(2)(4)(5)(7)** and the always-on/cross-table parts of **(6)**, plus Langfuse,
are the Neo4j milestone (roadmap, not yet built).

## Layer-by-layer

### (1) Splitter — ingestion & canonical `lore_core` — EXISTS

Source files (xlsx, markdown, pdf, pptx, docx, transcripts) are chunked into canonical records and
registered TOAST tables. Owns: `chunk_id` (SHA256 over `run_id`/ordinal/schema_version), the three
text views (`vector_text` / `fulltext` / `display_text`), nested `coordinates.heading_path`,
`vector_text_hash` / `fulltext_hash`, `chunk_type` (incl. `table_payload`), and
`payloads` / `payload_occurrences` / `payload_refs`. Physical structured rows live in registered
TOAST tables under the `splitter_toast` schema.

- Code (today): `agent-lore` airflow provider —
  `airflow/providers/lore/splitter/`. Not yet code-merged into this repo; the merge is tracked
  separately (see `architecture.md` and the lore↔agent-lore merge work).
- Specs: `agent-lore/.planning/` — `PROJECT.md`, `ROADMAP.md`, `MILESTONES.md` (v1.0–v1.3).
- Data reachable here: `lore_core.*` Postgres tables.

### (1b) Audit — run verification & read-only API — EXISTS (read side merged here)

Deterministic verification of a Splitter run plus a bounded read-only HTTP API over `lore_core`
(chunks, payloads, coordinates, table profiles). This is the **stable boundary** the online layers
read across.

- Code (here): `lore-core/services/lore-chat/audit/`.
- Specs: `agent-lore/.planning/phases/18–26`, `agent-lore/.planning/research/ARCHITECTURE.md`.

### (2) Projection — `lore_core` → Neo4j — ROADMAP (P1)

Reads a ready Lore run and projects it into Neo4j as a rebuildable derived index: computes embeddings
from `vector_text`, builds `Document`/`Section`/`Chunk` (+ `TextChunk`/`TableChunk`) nodes and
`HAS_SECTION`/`HAS_SUBSECTION`/`HAS_CHUNK`/`NEXT` edges, derives sections from `heading_path`
prefixes, and creates text/table vector + fulltext indexes. One ready index version at query time.

- Status: does not exist. See roadmap P0 (identity/activation design) and P1 (projection).

### (3) Chat entry — Chainlit + LangGraph agent — EXISTS (no retrieval yet)

React SPA talks to Chainlit over WebSocket; `app.py` handles the turn and selects a `fast` (fixed
LangGraph route) or `deep` (deepagents) agent. Today the only tool is a calculator and **no retrieval
context reaches the model**.

- Code (here): `lore-core/services/lore-chat/` — `app.py`, `agents/{base,fast,deep,tools}.py`.
- Specs: `lore-core/services/lore-chat/description.md` (frontend contract, chat profiles, response
  format incl. `cl.Plotly`), `README.md`, `chainlit.md`.

### (4) Retrieval — hybrid graph RAG — ROADMAP (P2)

The missing middle. Normalizes the query, runs TextChunk vector + fulltext search in parallel, fuses
with RRF and dedups by canonical `chunk_id`, does bounded structural expansion via fixed Cypher
templates, cross-encoder reranks, then batch-resolves canonical evidence envelopes (rejecting
stale / superseded / hash-mismatched). Sits behind Lore-owned interfaces (`ChunkSearchBackend`,
`GraphExpansionBackend`, `CanonicalEvidenceResolver`) so the backend can later change without
touching orchestration.

- Status: does not exist. See roadmap P2.

### (5) Section-aware auto-merging — ROADMAP (P3)

Small-to-big / parent-child grouping: precise chunk hits are merged into coherent local windows or
promoted to a parent section under a token budget, producing `ContextGroup`s whose citations preserve
every contributing canonical `chunk_id`.

- Status: does not exist. See roadmap P3.

### (6) Table lane + parallel SQL — PARTIAL (single-table SQL exists; discovery + fan-out are roadmap)

The always-on table lane discovers relevant `TableChunk`s on every query (vector + fulltext → RRF →
rerank → dedup → schema feasibility), selects an adaptive `K ≤ 5`, resolves each to a registered
payload via the **trusted registry** (never from Neo4j text, the user, or an LLM), and fans out up to
five **independent** read-only SQL calls in parallel.

- Exists today: the `toast/` LangGraph graph (`sample → generate → execute∥ → judge → summarize`),
  read-only asyncpg, sqlglot guardrails (`splitter_toast` schema, `toast_tbl_[0-9a-f]{20}`),
  timeouts, row caps. **But** it runs against **one already-known table** and is **not wired into the
  chat agent**; its parallelism is across SQL variants for one table, not across tables.
- Roadmap (P4): table *discovery* from retrieval + `TableCandidateSelector` + cross-table fan-out.
  The existing graph becomes the last mile.
- Code (here): `lore-core/services/lore-chat/toast/`. Spec: `docs/sql-tool.md`.

### (7) Top-level agent arbitration — ROADMAP (P4)

A LangGraph node receives `ContextGroup[]`, individual evidence, structural provenance, table
candidates, and `SQLResult[]`, then chooses the evidence. Guardrails: first non-empty SQL result is
not automatically correct; no mechanical sum/union/join across tables; conflicts stay explicit; no
invented row facts when all SQL fails.

- Status: does not exist. See roadmap P4.

### (8) Final answer + observability

LangGraph owns the final prompt and model call (OpenRouter/Ollama); the answer streams back to the
SPA and is persisted to Postgres history. Neo4j GraphRAG never generates the answer. A single Langfuse
trace per turn (`project_id="loreagent"`) spans retrieval, grouping, table/SQL, arbitration, and
generation.

- Exists today: final generation + streaming + Postgres history.
- Roadmap: Langfuse (wired at P2).

## The integration boundary (why the SQL tool fits without rework)

The contract that keeps the SQL tool stable as the pipeline grows:

- Retrieval (4–6) is responsible for **selecting** table candidates and resolving each to a
  registered payload. The SQL tool (6, last mile) is responsible for **executing** read-only SQL
  against exactly one registered table and returning a typed outcome.
- Physical table/schema names come only from the trusted registry — never from retrieval text.
- `payload_refs` is a locator, not an SQL trigger.

So the SQL tool's input contract (`question`, `chunk_id`, `table`, descriptions) is exactly the
hand-off from the table lane. Building retrieval means **feeding** that contract, not changing it.

## Current status at a glance

| # | Layer | State |
|---|---|---|
| 1 | Splitter (ingestion, canonical `lore_core`) | ✅ Exists (code in agent-lore) |
| 1b | Audit (verify + read-only API) | ✅ Exists (read side merged here) |
| 2 | Projection → Neo4j | ❌ Roadmap P1 |
| 3 | Chat entry (Chainlit + LangGraph) | ✅ Exists, no retrieval wired |
| 4 | Retrieval (hybrid graph RAG) | ❌ Roadmap P2 |
| 5 | Section-aware auto-merging | ❌ Roadmap P3 |
| 6 | Table lane + parallel SQL | ⚠️ Single-table SQL exists; discovery/fan-out = P4 |
| 7 | Agent arbitration | ❌ Roadmap P4 |
| 8 | Final answer | ✅ Generation exists; Langfuse = P2 |

## Related documents

- Retrieval milestone roadmap: `docs/superpowers/specs/2026-07-21-neo4j-hybrid-rag-roadmap-design.md`
- SQL tool detail: `docs/sql-tool.md`
- Chat/frontend contract: `lore-core/services/lore-chat/description.md`
- Audit package boundaries (refactor): `architecture.md`
- Splitter/Audit planning: `agent-lore/.planning/` (PROJECT.md, ROADMAP.md, MILESTONES.md)
- Deployment / usage: `docs/deployment.md`, `docs/usage.md`
