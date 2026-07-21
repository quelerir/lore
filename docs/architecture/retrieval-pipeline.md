# Retrieval Pipeline — Composition & Integration

Date: 2026-07-21
Status: full pipeline implemented and tested **offline** (no Neo4j / embeddings / reranker / SQL DB /
LLM). Real backends drop in behind the same interfaces when access is available. Package:
`lore-core/packages/lore-retrieval/`.

## How the "no Neo4j" build works

Every external dependency sits behind a Lore-owned `Protocol` (`lore_retrieval.interfaces`), with two
implementations: a deterministic in-memory **fake** (`lore_retrieval.fakes`) for offline tests, and
the **real** backend wired later. The orchestration (`lore_retrieval.pipeline.graph.RetrievalPipeline`)
depends only on the Protocols, so swapping fake → real is dependency injection, not a rewrite.

| Interface | Fake (now) | Real (when available) |
|---|---|---|
| `ChunkSearchBackend` | `InMemoryChunkSearchBackend` (lexical/Jaccard) | Neo4j `db.index.vector/fulltext.queryNodes` (`neo4j_spike`) |
| `GraphExpansionBackend` | `InMemoryGraphExpansion` (over `StructuralProjection`) | Neo4j fixed Cypher templates |
| `Reranker` | `FakeReranker` (term frequency) | cross-encoder (provider TBD) |
| `CanonicalEvidenceResolver` | `InMemoryEvidenceResolver` | `lore_core` read side (`lore-audit-core`) |
| `TableSearchBackend` | `InMemoryChunkSearchBackend` (table lane) | Neo4j TableChunk indexes |
| `SqlRunner` | `FakeSqlRunner` (canned outcomes) | `lore-chat/toast/` SQL module |
| `ChatModel` | `FakeChatModel` (deterministic) | OpenRouter |

## Stages (module map)

`RetrievalPipeline.answer(question)` runs the text lane and the always-on table lane **in parallel**,
then arbitrates:

```
text lane  (pipeline/*):
  fan_out_and_fuse        fanout.py     vector+fulltext -> RRF -> dedup
  expand_from_fanout      expansion.py  bounded NEXT/siblings/parent (degrades if it fails)
  rerank_stage            rerank.py     cross-encoder over fused+expanded
  resolve_evidence        resolve.py    canonical envelopes; reject stale/superseded/hash-mismatch
  build_context_groups    grouping.py   section-aware auto-merging -> ContextGroups

table lane (pipeline/table_lane.py):
  discover_table_candidates              TableChunk vector+fulltext -> RRF   (degrades if it fails)
  select_table_candidates                dedup to one payload/slot, K<=5, no padding
  run_sql_fanout                         <=5 independent read-only SQL calls in parallel

arbitration (pipeline/arbitration.py):
  arbitrate_and_answer                   pick text/SQL evidence, single final model call
```

Pure structural derivation used by expansion/grouping lives in `projection_model.py`
(`build_structural_projection` + `validate_projection`, the spec's 8 invariants).

## Guardrails enforced (tested)

- TableChunks never enter the text lane; text chunks never enter the table lane.
- Structural expansion is bounded and is *discovery* — everything reranks.
- Evidence resolution rejects missing / wrong-version / superseded / hash-mismatched chunks.
- Auto-merging never loads a whole document for two distant hits; distant/different-section hits stay
  separate; citations retain every member chunk.
- Table lane dedups repeated physical payloads to one SQL slot; K≤5; never padded.
- Arbitration: conflicting SQL successes stay explicit and are never merged across tables; when
  nothing grounds the question, a typed limitation is returned and the model is **not** called.
- Degradation: structural-expansion or table-lane failure is recorded and the answer still proceeds
  from the remaining evidence.

## Wiring the real backends (when access lands)

1. Implement each Protocol with the real backend (Neo4j via `neo4j_spike` primitives; `SqlRunner`
   adapting `lore-chat/toast/`; `ChatModel` over OpenRouter; resolver over `lore-audit-core`).
2. Construct `RetrievalPipeline(...)` with those instead of the fakes — no orchestration change.
3. Wrap `RetrievalPipeline.answer` as a LangGraph node in `lore-chat` and emit Langfuse spans per
   stage (`project_id="loreagent"`). The orchestration logic is identical direct or graph-wrapped.
4. Run the P0 spikes (`spikes/`) to pin embedding dim, analyzer, and latency.

## Known follow-ups

- Parent-section promotion + cross-scope overlap merge in grouping (contract already supports
  `parent_section`).
- Table-profile / schema-feasibility contract (interim: all candidates feasible).
- Reranker provider + score floor calibration; embedding provider (see `neo4j-p0-decisions.md`).
- Langfuse spans + LangGraph node wrapper in lore-chat.
