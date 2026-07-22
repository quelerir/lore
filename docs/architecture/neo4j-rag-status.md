# Neo4j Hybrid RAG + Citations — Status

Date: 2026-07-21 (updated overnight)
Branch: `lore-agent-merge` · package: `lore-core/packages/lore-retrieval/`

One-liner: the **entire request→answer pipeline + citations** is built and runs **end-to-end offline**
(fakes for every external service). **97 tests green, ruff + mypy clean.** What remains is *connecting*
real backends — not writing logic.

## Package map

```
src/lore_retrieval/
  config.py                 settings (Neo4j/Ollama/DSN/embedding)
  identity.py               projection_id, section_id, prefixes
  source.py                 SourceChunk + read-only lore_core adapter (fetch_chunks)
  projection_model.py       P1 core: Section/NEXT derivation + validate_projection (8 invariants)
  neo4j_spike.py            index create/project_batch/vector+fulltext/table search/project_structure/RRF
  embeddings.py             EmbeddingBackend + Ollama bge-m3 + graphrag adapter
  ledger.py                 DerivedIndexRecord (activation ledger)
  contracts.py              RetrievalCandidate, EvidenceEnvelope, ContextGroup, TableCandidate,
                            SQLResult, AgentDecision, Citation, PipelineResult, TableProfile, ...
  interfaces.py             ChunkSearchBackend, GraphExpansionBackend, Reranker,
                            CanonicalEvidenceResolver, TableSearchBackend, SqlRunner, ChatModel
  observability.py          Tracer seam (NullTracer / RecordingTracer)
  fakes.py                  in-memory impls of every interface (offline)
  pipeline/                 fanout, expansion, rerank, resolve, grouping, table_lane, feasibility,
                            arbitration, citation, message, graph (RetrievalPipeline), factory
  adapters/                 real/code-ahead backends (see below)
```

## Fully verified offline (97 tests, mypy + ruff clean)

- Full pipeline: text lane ∥ table lane → arbitration → citations, via `RetrievalPipeline` /
  `build_offline_pipeline`.
- P1 structural core (Section/NEXT + 8 invariants), property-tested on random corpora.
- RRF, bounded expansion, rerank, canonical resolution (reject stale/superseded/wrong-version/hash),
  section-aware auto-merging (+ opt-in parent promotion), table lane (dedup→K≤5→parallel SQL),
  schema feasibility, arbitration guardrails (conflicts explicit, no invented facts).
- Citations: model `[n]` markers → `Citation` (deep-link `/files?...`), only-provided/dedup/cap.
- Degradation: vector/fulltext route failure, reranker failure (→ fused order), auto-merging failure
  (→ singleton chunks), structural-expansion + table-lane failure. All degrade, never sink the turn.
- Observability seam records every stage.

## Code-ahead — UNVERIFIED vs live (mock-tested only, clearly flagged in-module)

- `adapters/neo4j_backends.py`: `Neo4j{ChunkSearch,TableSearch,GraphExpansion}Backend` +
  `neo4j_spike.project_structure` — **VERIFIED LIVE 2026-07-22** on Neo4j Community 5.26.28
  (`spikes/live_validate_neo4j.py`; fixed the deprecated `CALL{WITH}` → `CALL(seed){}`). No longer
  code-ahead.
- `adapters/evidence_postgres.py`, `adapters/file_keys.py`: asyncpg over `lore_core.chunks` /
  `processing_runs` — pure cores unit-tested; SQL needs a live `loreagent_test` DSN.
- `adapters/chat_openrouter.py`: httpx OpenRouter adapter, mock-tested (needs a key to run live).
- `adapters/sql_callable.py`: `CallableSqlRunner` seam — toast binding happens in lore-chat.
- `frontend/src/chat/citations.ts` (+ test): pure extraction, **not executed** (Node 16 here can't run
  vite/vitest v3). React `CitationList` is a reference sketch in `citations-frontend-integration.md`.

## What truly still waits (access / decisions)

| Blocker | Unlocks |
|---|---|
| External Neo4j (`NEO4J_URI`+auth, edition) | live-verify Neo4j backends; P0 spikes (analyzer/latency); one-ready-version activation |
| Embeddings provider decision (OpenRouter has none) | vector lane (interim bge-m3/Ollama) |
| `loreagent_test` RO-DSN | live resolver + file-key adapter; real corpus for eval |
| OpenRouter key | live ChatModel |
| TOAST DB + toast binding in lore-chat | live SqlRunner |
| Node 20 machine | run frontend vitest + implement Phase C rendering |
| Running chat stack | LangGraph cite node wiring + Langfuse adapter |

## When access arrives — do this

1. **Neo4j:** construct `Neo4j*Backend` + `project_batch`/`project_structure`; run P0 spikes
   (`spikes/`), fill `neo4j-p0-decisions.md`, pick activation shape. Swap fakes → real in the pipeline.
2. **Embeddings:** implement the chosen provider behind `EmbeddingBackend` (interim `OllamaEmbeddingBackend`).
3. **lore-chat:** wrap `RetrievalPipeline.answer` in a LangGraph node; attach `to_message_metadata(result)`;
   bind toast behind `CallableSqlRunner`; wire a Langfuse adapter to the `Tracer` seam.
4. **Frontend:** implement `CitationList` per `citations-frontend-integration.md`; `npm test` on Node 20.
5. **Eval:** build the versioned RU eval set + comparison matrix on the real corpus.

## Overnight changes (2026-07-21 night)

mypy (clean) + property tests · Neo4j backends + P1 structural write · frontend citation extraction +
integration guide · observability Tracer seam · message-metadata builder · degradation hardening
(vector/fulltext/reranker/auto-merge) · `build_offline_pipeline` factory · code-review fixes (H1/H2/M/L).

## Resume / how to run (2026-07-22)

- **Branch:** `lore-agent-merge`, working tree clean. Package: `lore-core/packages/lore-retrieval/`.
  **100 tests, ruff + mypy clean.** Solo — no parallel writer now.
- **Neo4j is LIVE:** Community 5.26.28, reachable over **VPN** via plain **`bolt://`** (server not
  TLS on 7687). Creds in the **shared root `.env`** as `RETRIEVAL_NEO4J_URI/USER/PASSWORD/DATABASE`
  (config finds root by `docker-compose.yml`/`.git` marker; never per-package .env).
- **Run tests:** `cd lore-core/packages/lore-retrieval && uv run pytest -q` (also `ruff check src tests`,
  `mypy`).
- **Run a spike** (needs `src` on path): `PYTHONPATH=src uv run python spikes/<name>.py`.
  `probe_capabilities.py` (done) and `live_validate_neo4j.py` (done, self-cleans) both work.
- **Verified live:** Neo4j chunk/table search + graph expansion + `project_batch`/`project_structure`.
- **Next spikes need:** Ollama + `bge-m3` (`ollama pull bge-m3`) and `RETRIEVAL_LORE_CORE_DSN`
  (loreagent_test) in the root `.env` → then run projection of a real run → analyzer eval
  (`run_analyzer_eval.py`) → latency (`run_latency.py`), filling `neo4j-p0-decisions.md` §2/§3/§5.
- **Still pending elsewhere:** embeddings provider decision (interim bge-m3/Ollama); frontend Phase C
  render on Node 20; lore-chat LangGraph `cite` node + Langfuse adapter to the Tracer seam.
