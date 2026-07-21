# Neo4j P0 Decision Record

Date: 2026-07-21
Status: **IN PROGRESS.** Offline design/code decisions are recorded; sections marked
`PENDING (creds)` require a live external Neo4j + Ollama + `loreagent_test` and are filled by the
spike harnesses under `lore-core/packages/lore-retrieval/spikes/`.

This record answers the P0-relevant promotion questions from the milestone roadmap and gates P1.

## 1. Neo4j capabilities — PENDING (creds)

Run `spikes/probe_capabilities.py`. Record: edition (`community`/`enterprise`), exact 5.x version,
whether `db.index.vector.queryNodes` and `db.index.fulltext.queryNodes` are available, and
multi-database availability.

Activation baseline = version-labeled indexes (portable). Separate-DB activation is available only
if edition is Enterprise. See `neo4j-identity-and-activation.md`.

## 2. Analyzer — PENDING (creds)

Run `spikes/run_analyzer_eval.py` (after projecting a batch). Record the recall@10 table over
`standard` / `standard-no-stop-words` / `russian` / `whitespace` for the `prose` and `exact` buckets,
the chosen analyzer (or the decision to run a second exact-match sub-index if no single analyzer wins
both), and any Lucene escaping needed for exact-code queries.

## 3. Latency — PENDING (creds)

Run `spikes/run_latency.py` at the target corpus size. Record corpus size, p50/p90 for vector /
fulltext / hybrid, whether latency is acceptable for an interactive turn, and whether query-embedding
should be cached/warmed (it calls Ollama per turn).

## 4. Pinned versions

- Exact resolved versions (from `uv.lock`, 2026-07-21): `neo4j==5.28.4`, `neo4j-graphrag==1.18.0`,
  `langchain-ollama==1.1.0`, `asyncpg==0.31.0`, `pydantic==2.13.4`, `pydantic-settings==2.14.2`.
- Neo4j server version: PENDING (creds) — from section 1.
- Reranker: **none in P0** (deferred to P2).

## 5. Embedding model

- **Chat/LLM provider: OpenRouter only** (Ollama dropped as an LLM fallback). Embeddings are a
  separate concern — **OpenRouter exposes no embeddings API**, so it cannot serve the vector lane.
- Embedding model: **bge-m3 via Ollama (interim)**, behind the `EmbeddingBackend` interface
  (`lore_retrieval.embeddings`), swappable by config. The final embeddings provider is **OPEN —
  under team review** (2026-07-21). Candidates when decided: a managed multilingual API
  (OpenAI text-embedding-3-large / Voyage / Jina / Cohere via an OpenAI-compatible client) or a
  self-hosted bge-m3 (HF TEI, no Ollama). Swapping is one `EmbeddingBackend` implementation.
- Dimension: 1024 (config default, bge-m3). Confirm against a live `embed_query` call (Task 3 Step 5)
  and record the observed dimension here: PENDING (creds). Note a provider change may change the
  dimension and require re-projection under a new `index_version`.
- Similarity: cosine (set on the vector index).

## 6. Activation shape

See `neo4j-identity-and-activation.md`. Baseline = version-scoped labels/indexes (implemented in
`lore_retrieval.neo4j_spike`); Enterprise separate-DB option chosen only if section 1 allows it.

## 7. Promotion-question status

- Neo4j edition/version & vector/fulltext capabilities — PENDING (section 1).
- Activation via projection ids / separate dbs / instances — DESIGNED (identity+activation doc);
  final pick PENDING (section 1).
- Embedding model, dimensions, similarity, batching — DECIDED (bge-m3/1024/cosine, batched in
  `project_batch`); dimension confirmation PENDING (section 5).
- Russian/multilingual Lucene behavior — PENDING (section 2).
- Reranker, budgets, floors — DEFERRED to P2.
- Deterministic nested Section derivation + synthetic fallback — PARTIAL (spike uses `section_id`
  only; full Section graph is P1).
- RRF constant & route budgets — DEFAULTED (rrf_k=60, top_k=50); calibration in P5.
- Neo4j capacity, backup/restore, monitoring — DESIGNED (identity+activation doc); hardening in P5.
