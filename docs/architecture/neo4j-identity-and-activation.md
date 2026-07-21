# Neo4j Derived Identity & One-Ready-Version Activation

Date: 2026-07-21
Status: P0 design (Task 10). The final isolation choice is gated on the Task 5 capability probe
(edition/multi-database availability) and recorded in `neo4j-p0-decisions.md`.

## Derived identity

Lore `chunk_id` represents a source *occurrence*, not merely content. Neo4j therefore carries both a
canonical id and a version-scoped projection id:

```
projection_id = index_version + ":" + canonical_id      # e.g. "v3:chunk_abc"
chunk_id      = canonical Lore chunk_id
```

`projection_id` is the node's MERGE key, so re-projecting the same `(index_version, chunk_id)` is
idempotent. `section_id = sha256(document_id \x1e heading_path)` is deterministic and stable for a
given `(document_id, heading_path)` within an index version (see `lore_retrieval.identity`).

**Why `projection_id` filtering after `top_k` is insufficient.** Native vector / fulltext procedures
return their `top_k` *before* any post-filter. If multiple index versions share one index, an inactive
version's nodes can consume slots in that `top_k`, silently reducing the active version's recall.
Post-filtering on `projection_id` cannot recover the lost recall. Therefore isolation must happen at
the *index* level, not by filtering results.

## One-ready-version activation

Query-time retrieval must see exactly one ready version. Two isolation shapes, chosen by edition:

### Baseline (portable, Community-compatible): version-scoped labels + indexes

Each projection uses version-suffixed labels and indexes:

```
labels:  TextChunk_<v>, TableChunk_<v>
indexes: vec_TextChunk_<v>, ft_TextChunk_<v>, vec_TableChunk_<v>, ft_TableChunk_<v>
```

Only the active version's labels/indexes exist and serve queries. Building a new version creates a
disjoint label/index set; the old version keeps serving until switchover. Activation = point retrieval
at the new version suffix (a single config value: the active `index_version`) once it passes checks;
then drop the superseded version's labels/indexes. No cross-version `top_k` contention because each
query names exactly one version's indexes. This is what `lore_retrieval.neo4j_spike` implements.

### Enterprise option: separate databases

If the probe (Task 5) shows Enterprise multi-database, each `index_version` can live in its own Neo4j
database; activation switches the database the retriever connects to, and the old database is dropped
after switchover. Cleaner isolation and drop semantics, but requires Enterprise. The `neo4j_database`
setting already parameterizes this.

The final choice is recorded in `neo4j-p0-decisions.md` after Task 5.

## Ledger

Every projection is tracked by a `DerivedIndexRecord` (`lore_retrieval.ledger`) with the pinned
component versions and lifecycle status:

```
status: pending -> indexing -> ready       (previous ready stays ready)
                 -> failed                  (never activated; previous stays ready)
        ready   -> superseded               (only after the new version is activated)
```

Fields: `run_id, index_version, chunk_schema_version, section_projection_version,
embedding_model_version, fulltext_analyzer_version, graph_schema_version, neo4j_server_version,
neo4j_graphrag_version, reranker_version, status, started_at, completed_at, error_summary`.

Persistence (a Postgres table alongside `lore_core`, or a Neo4j `:IndexVersion` node) is deferred to
P1; P0 delivers the typed shape and the lifecycle rules.

## Rebuild / rollback / backup / restore

- **Rebuild:** build a complete projection under a fresh `index_version` before activation. A failed
  build never replaces the previous ready version (`failed`, not `superseded`).
- **Rollback:** because the superseded version's labels/indexes (or database) are retained until the
  new one is verified, rollback = re-point the active `index_version` at the prior one. Retain the
  previous ready projection until the new one passes retrieval evaluation and activation checks.
- **Backup:** Neo4j owns all retrieval routes in this baseline, so tested backup/restore is a
  production requirement (P5 hardening). The projection is derived, so the ultimate restore path is a
  full rebuild from canonical `lore_core`.
- **Restore:** if Neo4j is lost and no retained production retriever exists, retrieval returns a typed
  retrieval-unavailable rather than an ungrounded answer, and the projection is rebuilt from
  `lore_core`.

## Security note

Index/label identifiers come only from the internal `index_version`, never from user or LLM text.
Search and expansion use fixed parameterized Cypher; node data is always written/queried via bound
parameters. No `payload_refs`, physical TOAST names, or ACL policy are stored in retrievable text
properties.
