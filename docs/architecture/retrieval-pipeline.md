# Retrieval Pipeline — Composition & Integration

Date: 2026-07-21 (updated 2026-07-22)
Status: full pipeline implemented + tested offline; the **real backends are now wired** in lore-chat
(Neo4j, HTTP bge-m3 embeddings, HTTP bge-reranker, `lore_core` resolver, toast SQL, OpenRouter) behind
the same interfaces — swap is dependency injection, not a rewrite. Grounded citations ship end-to-end
(Phase A–D: text + table `tab=payloads` deep-links, inline `[n]` superscripts, deterministic top-N
fallback). An offline eval harness lives in `lore_retrieval.eval`. Live end-to-end was verified once on
the real RU corpus; the reranker + Langfuse paths are built but NOT yet live-verified. Package:
`lore-core/packages/lore-retrieval/`.

## How the "no Neo4j" build works

Every external dependency sits behind a Lore-owned `Protocol` (`lore_retrieval.interfaces`), with two
implementations: a deterministic in-memory **fake** (`lore_retrieval.fakes`) for offline tests, and
the **real** backend wired later. The orchestration (`lore_retrieval.pipeline.graph.RetrievalPipeline`)
depends only on the Protocols, so swapping fake → real is dependency injection, not a rewrite.

| Interface | Fake (offline) | Real (wired) |
|---|---|---|
| `ChunkSearchBackend` | `InMemoryChunkSearchBackend` (lexical/Jaccard) | Neo4j `db.index.vector/fulltext.queryNodes` (`neo4j_spike`) |
| `GraphExpansionBackend` | `InMemoryGraphExpansion` (over `StructuralProjection`) | Neo4j fixed Cypher templates |
| `Reranker` | `IdentityReranker` (P0 no-op) / `FakeReranker` | `HttpReranker` (bge-reranker, `adapters/rerank_http.py`; opt-in `RETRIEVAL_RERANKER`, else identity) |
| `CanonicalEvidenceResolver` | `InMemoryEvidenceResolver` | `PostgresEvidenceResolver` over `lore_core` (`lore-audit-core`) |
| `TableSearchBackend` | `InMemoryChunkSearchBackend` (table lane) | Neo4j TableChunk indexes |
| `SqlRunner` | `FakeSqlRunner` (canned outcomes) | `lore-chat/toast/` SQL module via `toast_binding` |
| `ChatModel` | `FakeChatModel` (deterministic) | `OpenRouterChatModel` |
| `ChunkContextLoader` | `InMemoryChunkContextLoader` | `PostgresChunkContextLoader` (per-query rows) |
| `Tracer` (observability) | `NullTracer` / `RecordingTracer` | `ContextTracer` (UI debug) + `LangfuseTracer` via `CompositeTracer`; Studio uses `LangSmithTracer` |

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
  arbitrate_and_answer                   enumerate text[1..G]+SQL[G+1..] evidence as [n],
                                         single final model call, sql_evidence_map

citations (pipeline/citation.py):
  build_citations                        resolve model [n] -> Citations (text: tab=display;
                                         table: tab=payloads on the anchor chunk), dedup + cap,
                                         deterministic top-N fallback when nothing resolved
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

## Real backends (wired) + evaluation

- `lore-chat/retrieval.py::_build_pipeline` constructs the live `RetrievalPipeline` from real adapters
  and `factory.build_live_pipeline`; `pipeline.answer` runs both directly (deep-mode `knowledge_base`
  tool) and as explicit LangGraph nodes (`agents/grounded.py`, the fast/grounded diamond). The
  orchestration is identical direct or graph-wrapped.
- **Observability:** stage records flow through the `Tracer` seam. Live turns fan out via
  `CompositeTracer` to `ContextTracer` (chat debug view) and, when `LANGFUSE_*` is set, `LangfuseTracer`.
- **Eval:** `lore_retrieval.eval` — pure metrics (retrieval/citation recall, grounding, fallback_rate,
  answer_rate, decline_correct) over `PipelineResult` + gold labels, run against the offline pipeline
  over `GOLDEN_CASES`. The same `EvalCase` shape will host live cases + judge-based answer quality.

## Known follow-ups

- Parent-section promotion + cross-scope overlap merge in grouping (contract already supports
  `parent_section`).
- Table-profile / schema-feasibility contract (interim: all candidates feasible).
- Reranker score-floor calibration; **live-verify** the bge-reranker `/rerank` and Langfuse span
  contracts (built, not yet exercised against the real services).
- Deep-mode double-answer: the `knowledge_base` tool returns arbitration prose AND the deepagent
  relays — collapse to one top-level agent (fast/grounded mode already single-answer). Design decision
  pending.
- Eval: live cases + answer-quality (judge) metrics.
