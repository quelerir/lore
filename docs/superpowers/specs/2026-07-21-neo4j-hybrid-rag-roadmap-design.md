# Neo4j-Native Hybrid RAG + TOAST SQL Routing — Milestone Roadmap

Date: 2026-07-21
Status: milestone roadmap (design-level). Not a phase plan, requirements set, or deployment
authorization. Source spec: `agent-lore/.planning/future/lore-neo4j-native-hybrid-rag-and-toast-sql-routing-draft.md`.

## Purpose

Turn the future-milestone draft into an ordered, dependency-aware roadmap grounded in the current
codebase, plus an explicit gap analysis. This document is the alignment artifact before any phase is
planned or built. Each phase later gets its own spec → plan → implement cycle.

The goal of the milestone itself: the smallest useful graph-RAG baseline with one derived retrieval
backend (Neo4j) — dense vector + Lucene fulltext + deterministic structural graph — orchestrated by
LangGraph, with an always-on table lane that can fan out to up to five read-only SQL calls over
registered TOAST tables. `lore_core` stays canonical; Neo4j is a rebuildable projection.

## Invariants (carried into every phase)

- `lore_core` remains canonical for files, runs, chunks, the three text views, coordinates, hashes,
  payloads, occurrences, and `payload_refs`.
- Neo4j is a rebuildable projection, never the only copy of canonical content or SQL lineage.
- Existing chunking and canonical `chunk_id` are retained. No re-chunking in Neo4j.
- Exactly one ready index version is visible at query time.
- Search and expansion use fixed, parameterized Cypher templates only; user/LLM text never becomes a
  label, relationship type, index name, or Cypher fragment.
- SQL is read-only, allowlisted, timed, and row-limited; physical table names come only from the
  trusted registry.
- LangGraph owns the final prompt and model call. Neo4j GraphRAG never generates the answer.
- Out of scope this milestone: Qdrant, semantic entity graph, per-user/per-file ACL, cross-table
  joins/unions/arithmetic, agent-generated Cypher, custom-trained rerankers.

## Current state (grounding)

- **Canonical `lore_core` foundation — exists, in `agent-lore`, not yet code-merged here.** The
  Splitter produces `chunk_id` (SHA256 over `run_id`/ordinal/schema_version), the three text views
  (`vector_text`/`fulltext`/`display_text`), nested `coordinates.heading_path`, `vector_text_hash`/
  `fulltext_hash`, `chunk_type` incl. `table_payload`, and `payloads`/`payload_occurrences`/
  `payload_refs` with TOAST registration. Persisted to `lore_core.*` Postgres tables.
- **Read side is merged here.** `lore-core/services/lore-chat/audit/` is a read-only HTTP API over
  that same `lore_core` data (chunks, payloads, coordinates, table profiles).
- **TOAST SQL — a working but isolated sub-graph.** `lore-core/services/lore-chat/toast/` is a
  LangGraph graph (`sample → generate → execute∥ → judge → summarize`) with read-only asyncpg,
  sqlglot guardrails (`splitter_toast` schema, `toast_tbl_[0-9a-f]{20}` pattern), statement
  timeouts, and row caps. It runs against **one already-known table** and is **not wired into the
  chat agent**. Its parallelism is across SQL variants for one table, not across tables.
- **Chat agent — LangGraph, zero retrieval.** `agents/fast.py` / `deep.py` are tool-calling agents
  whose only tool is a calculator. No RAG context reaches the model today.
- **Observability — LangSmith for evals only.** No Langfuse.

**De-risking consequence:** the retrieval work depends only on `lore_core` chunk **data** (reachable
now via Postgres / the audit read side), not on the Splitter **code** being merged into this repo.

## Gap analysis — what's missing for the full pipeline

Almost the entire retrieval half of the spec is greenfield:

1. **Embeddings.** `vector_text` is stored as text; no embedding vectors are computed. No embedding
   model, batching, or derived `embedding` property.
2. **Neo4j — all of it.** No server/driver/`neo4j-graphrag-python`, no vector index, no Lucene
   fulltext index, no graph model.
3. **Projection pipeline.** Nothing reads a ready Lore run and projects `Document`/`Section`/`Chunk`
   + `TextChunk`/`TableChunk` + `HAS_SECTION`/`HAS_SUBSECTION`/`HAS_CHUNK`/`NEXT` idempotently.
4. **Section derivation.** `heading_path` exists on chunks, but no code turns path-prefixes into
   `Section` nodes, nor the synthetic per-source-type fallback.
5. **Derived identity & activation.** No `projection_id`, no derived-index ledger, no
   one-ready-version activation / rebuild / rollback / backup / restore.
6. **Retrieval fan-out.** No vector search, no fulltext search, no RRF fusion, no dedup by `chunk_id`.
7. **Bounded structural expansion.** No fixed Cypher templates (section / NEXT / sibling / parent).
8. **Reranker.** No cross-encoder.
9. **Section-aware auto-merging.** No `ContextGroup`, grouping algorithm, scoring, or citations.
10. **Canonical evidence resolver.** The read API can fetch chunks, but there's no batch envelope
    resolver enforcing hash/version/superseded rejection wired into retrieval.
11. **Always-on table lane.** No table discovery from retrieval, schema-feasibility assessment,
    recall-first adaptive `K≤5`, or fan-out of up to 5 **independent per-table** SQL calls.
12. **Top-level agent arbitration.** No node that receives `ContextGroups` + evidence + table
    candidates + `SQLResult[]` and does the final grounded model call.
13. **Langfuse.** Not installed; no `project_id="loreagent"` traces/spans.
14. **Lore-owned interfaces & typed contracts.** `ChunkSearchBackend`, `GraphExpansionBackend`,
    `ContextGrouper`, `TableCandidateSelector`, `CanonicalEvidenceResolver`, plus
    `RetrievalCandidate` / `ContextGroup` / `SQLResult` — none exist.
15. **Evaluation.** SQL eval harness exists; the versioned retrieval eval set + comparison matrix do
    not.
16. **Ops.** Neo4j deployment, backup/restore, monitoring, circuit breakers / concurrency limits.

## Phase breakdown

Dependency spine: **P0 → P1 → P2 → {P3 ∥ P4} → P5.** P3 and P4 run in parallel once P2 lands.

### P0 — Foundations & spike

Goal: de-risk the one new backend before committing to build.

Deliverables:
- Pinned versions: Neo4j server, driver, `neo4j-graphrag-python`, embedding model, reranker.
- Embedding model + batching decision; Russian/multilingual Lucene analyzer decision.
- Working spike proving vector + fulltext + hybrid retrieval at expected scale and latency.
- Design of derived identity (`projection_id = index_version + ":" + canonical_id`), derived-index
  ledger, and the one-ready-version activation / rebuild / rollback / backup / restore shape
  (separate DB/instance vs version-specific labels/indexes).

Exit criteria: the spec's "Promotion Questions" answered with source-backed evidence; activation
isolation shape chosen; latency at expected scale acceptable.

### P1 — Projection pipeline

Goal: canonical run → Neo4j, deterministically and idempotently.

Deliverables:
- Embedding computation over `vector_text` → derived `embedding` property.
- Idempotent projection of `Document`/`Section`/`Chunk` (+ mutually exclusive `TextChunk`/
  `TableChunk` labels from canonical `chunk_type`), with `HAS_SECTION`/`HAS_SUBSECTION`/
  `HAS_CHUNK`/`NEXT` edges.
- Section derivation: one `Section` per unique `heading_path` prefix, `section_id` from
  `(document_id, heading_path)`; synthetic structural fallback per source type (PDF page, slide,
  sheet/region, transcript topic, or document-root).
- Text-lane and table-lane vector + fulltext indexes.
- Derived-index ledger writes (status: pending/indexing/ready/failed/superseded).

Exit criteria: the 8 projection invariants proven by tests (no cross-doc chunks; one section per path
prefix; parent/child edges reproduce heading order; structurally compatible chunks per section; split
continuations retain section; siblings not merged; unique ordered positions; table anchors preserved).

### P2 — Core retrieval

Goal: grounded candidates behind Lore-owned interfaces.

Deliverables:
- Interfaces + Neo4j implementations: `ChunkSearchBackend`, `GraphExpansionBackend`,
  `CanonicalEvidenceResolver`.
- LangGraph fan-out: TextChunk vector + fulltext (parallel) → RRF fusion → dedup by canonical
  `chunk_id` → bounded structural expansion (fixed Cypher templates) → cross-encoder rerank over
  `query × Chunk.fulltext` → batch canonical envelope resolution.
- Typed `RetrievalCandidate` (chunk_id, route, route_rank, first_stage_score, structural_path,
  index_version).
- Degradation paths (structural timeout, vector/fulltext failure, reranker failure, Neo4j
  unavailable → typed retrieval-unavailable).
- **Langfuse wired here** (`project_id="loreagent"`) so retrieval is observable while it is tuned.

Exit criteria: comparison-matrix rungs (vector → +fulltext → +structural → +rerank) measurable;
degradation modes tested; retrieval budgets enforced (no unbounded routes).

### P3 — Section-aware auto-merging

Goal: coherent local source context (small-to-big / parent-child).

Deliverables:
- `ContextGrouper` + `ContextGroup` (document_id, section_id, section_path, scope, chunk_ids,
  positions, text, routes, group_score, citations, truncation_reason).
- Grouping algorithm: local runs per leaf section, adjacent/split-continuation merge, parent
  promotion under budget with hit density, overlap merge, capped diminishing group scoring.
- Citations preserve every contributing canonical `chunk_id`; no whole-document loads; grouping never
  copies/inherits `payload_refs`.

Exit criteria: grouping eval cases pass; distant hits stay separate; one highly split document cannot
consume all context.

### P4 — Table lane + parallel SQL + arbitration

Goal: always-on table discovery → up to five parallel SQL → agent arbitration.

Deliverables:
- Always-on `TableChunk` lane: table vector + fulltext → RRF → fulltext rerank → physical-payload
  dedup → schema-feasibility assessment.
- `TableCandidateSelector`: recall-first adaptive `K≤5` from fused/reranked top 10–15 candidates
  (reject only non-expressible schemas / below floor; preserve exact matches; never pad to five).
- Refactor the existing `toast/` graph from single-table to a **cross-table fan-out** of up to five
  independent read-only SQL calls, each targeting exactly one registered payload resolved from the
  trusted registry (never from Neo4j text, the user, or an LLM identifier). Preserve existing
  guardrails, timeouts, and row limits. Typed outcomes (success/empty/not_applicable/unsupported/
  ambiguity/validation_error/execution_error/timeout).
- Top-level LangGraph arbitration node receiving `ContextGroup[]`, individual evidence, structural
  provenance, table candidates, and `SQLResult[]`, then performing the final model call. Guardrails:
  first non-empty result is not automatically correct; no mechanical sum/union/join across tables;
  conflicts stay explicit; no invented row facts on total SQL failure.

Exit criteria: table + SQL eval cases pass; existing toast guardrails preserved; table discovery runs
on every query even when it yields no SQL calls.

### P5 — Evaluation, observability, hardening

Goal: prove promotion-worthiness.

Deliverables:
- Versioned eval set (prose, exact lexical, structural, long-section, TOAST) + full comparison matrix
  (vector only … full baseline + table lane + parallel SQL).
- Metrics: candidate/final recall, exact-name/code/value recall, structural recovery + wrong-expansion
  rates, groundedness, group coherence, citation completeness, duplicate/context tokens,
  table recall@1..5, SQL fan-out / wrong-table rates, p50/p90 latency, Neo4j load, indexing cost,
  freshness, degraded-mode rate.
- Calibration of floors/budgets; complete Langfuse spans (retrieval, grouping, table/SQL,
  agent-decision, final generation).
- Load/failure/security probes; UAT.

Exit criteria: material gain shown without unacceptable latency, context inflation, wrong-table
regression, or Neo4j capacity risk (the spec's promotion bar).

## Cross-cutting concerns

- **Lore-owned interfaces** (`ChunkSearchBackend`, `GraphExpansionBackend`, `ContextGrouper`,
  `TableCandidateSelector`, `CanonicalEvidenceResolver`) are introduced early (P0 design, P2/P3/P4
  implementation) so Qdrant can later replace `ChunkSearchBackend` without touching grouping, SQL, or
  orchestration.
- **Langfuse at P2, not P5** — retrieval is tuned under observation from the moment it exists.
- **Neo4j ops** (backup/restore, monitoring, circuit breakers, concurrency limits) are designed in P0
  and hardened in P5. Because Neo4j owns all retrieval routes in this baseline, a tested
  previous-ready activation path is a production requirement.
- **New code goes in a new place** — a dedicated retrieval service/package under `lore-core/`, so this
  milestone and the merge branch do not contend for the same files.

## Relationship to the parallel lore↔agent-lore refactor

The refactor moves Splitter/storage **code** into `lore-core/packages`. This milestone consumes chunk
**data**, not that code. Therefore:

- **Run in parallel; do not block on the merge.** Projection reads `lore_core` data via Postgres /
  the audit read side.
- **Single coupling point:** the table-profile / TOAST registry contract (needed in P4 for SQL). Fix
  it as an explicit interface now so the refactor can change the implementation beneath it.
- **Read across a stable boundary** — the audit read API / `lore_core` schema, not internal modules
  the refactor will relocate. No imports from `airflow.providers.lore` (same boundary as
  `architecture.md`).
- **Independent merges to main.** Whichever branch is ready lands first. If the refactor lands first,
  we re-point the read imports to the new package in one commit. Expected file overlap is minimal
  (mostly `docker-compose` / infra — coordinated pointwise).

## Top risks

1. Russian Lucene morphology vs exact-code/identifier recall — an evaluation gate, not an assumption.
2. Activation isolation done wrong lets inactive index versions consume native `top_k` recall.
3. Refactoring the working `toast/` graph into cross-table fan-out without regressing its guardrails.
4. Reranker latency and floor calibration (no provider default threshold as corpus-independent truth).
5. The table-profile / registry contract is the one real coupling to the in-progress merge.

## Open promotion questions (resolve via source-backed spikes)

- Neo4j edition/version and vector/fulltext capabilities; `neo4j-graphrag-python` version and public
  contracts.
- Activation via `projection_id` filtering vs separate databases vs separate instances.
- Embedding model, dimensions, similarity, batching, throughput.
- Russian/multilingual Lucene behavior for morphology and exact codes.
- Reranker choice, budgets, latency, calibrated floors.
- Deterministic nested `Section` derivation and synthetic fallback per source type.
- Auto-merging adjacency/promotion/gap/group/total-context thresholds.
- RRF constant and route budgets.
- Table feasibility contract and relevance floor.
- SQL pool capacity, concurrency, timeouts, result limits, fan-out deadline.
- Target recall for adaptive `K ≤ 5`.
- Agent arbitration contract for multiple SQL results.
- Neo4j capacity, backup/restore, monitoring, and unavailable behavior.

## Next step

When ready to build, start with **P0** via its own spec → plan cycle (writing-plans skill). Later
phases stay high-level in this roadmap until their predecessor lands.
