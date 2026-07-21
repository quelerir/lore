"""Spike projection + retrieval primitives over an external Neo4j.

Index/label names are version-scoped (e.g. ``TextChunk_v3`` / ``vec_TextChunk_v3``)
so exactly one ready index version serves queries — the Community-portable
one-ready-version mechanism. Version identifiers are internal, never user text.
All node data is written with bound parameters; only internal index/label
identifiers are interpolated into Cypher.

Projection and search require a live Neo4j (deferred to creds during P0). ``rrf_fuse``
is pure and unit-tested offline.
"""
from neo4j import AsyncDriver

from lore_retrieval.identity import projection_id, section_id
from lore_retrieval.source import SourceChunk


def _labels(index_version: str) -> tuple[str, str]:
    v = index_version.replace("-", "_")
    return f"TextChunk_{v}", f"TableChunk_{v}"


async def ensure_indexes(
    driver: AsyncDriver, database: str, index_version: str, dim: int
) -> None:
    text_label, table_label = _labels(index_version)
    async with driver.session(database=database) as sess:
        for label in (text_label, table_label):
            await sess.run(
                f"CREATE VECTOR INDEX vec_{label} IF NOT EXISTS "
                f"FOR (n:{label}) ON (n.embedding) "
                f"OPTIONS {{ indexConfig: {{ `vector.dimensions`: {int(dim)}, "
                f"`vector.similarity_function`: 'cosine' }} }}"
            )
            await sess.run(
                f"CREATE FULLTEXT INDEX ft_{label} IF NOT EXISTS "
                f"FOR (n:{label}) ON EACH [n.fulltext]"
            )


async def project_batch(
    driver: AsyncDriver,
    database: str,
    index_version: str,
    chunks: list[SourceChunk],
    backend,
    embed_batch: int = 64,
) -> int:
    text_label, table_label = _labels(index_version)
    total = 0
    async with driver.session(database=database) as sess:
        for i in range(0, len(chunks), embed_batch):
            window = chunks[i : i + embed_batch]
            vectors = backend.embed_documents([c.vector_text for c in window])
            rows = [
                {
                    "projection_id": projection_id(index_version, c.chunk_id),
                    "chunk_id": c.chunk_id,
                    "document_id": c.document_id,
                    "section_id": section_id(c.document_id, c.heading_path),
                    "chunk_type": c.chunk_type,
                    "position": c.position,
                    "fulltext": c.fulltext,
                    "fulltext_hash": c.fulltext_hash,
                    "embedding": vec,
                    "label": table_label if c.is_table else text_label,
                }
                for c, vec in zip(window, vectors)
            ]
            for label in (text_label, table_label):
                sub = [r for r in rows if r["label"] == label]
                if not sub:
                    continue
                await sess.run(
                    f"""
                    UNWIND $rows AS r
                    MERGE (c:{label} {{projection_id: r.projection_id}})
                    SET c.chunk_id = r.chunk_id, c.document_id = r.document_id,
                        c.section_id = r.section_id, c.chunk_type = r.chunk_type,
                        c.position = r.position, c.fulltext = r.fulltext,
                        c.fulltext_hash = r.fulltext_hash, c.embedding = r.embedding
                    """,
                    rows=sub,
                )
                total += len(sub)
    return total


async def vector_search(
    driver: AsyncDriver, database: str, index_version: str, query: str, embedder, top_k: int = 50
) -> list[tuple[str, float]]:
    text_label, _ = _labels(index_version)
    qvec = embedder.embed_query(query)
    async with driver.session(database=database) as sess:
        res = await sess.run(
            "CALL db.index.vector.queryNodes($index, $k, $qvec) YIELD node, score "
            "RETURN node.chunk_id AS chunk_id, score",
            index=f"vec_{text_label}", k=top_k, qvec=qvec,
        )
        return [(r["chunk_id"], r["score"]) async for r in res]


async def fulltext_search(
    driver: AsyncDriver, database: str, index_version: str, query: str, top_k: int = 50
) -> list[tuple[str, float]]:
    text_label, _ = _labels(index_version)
    async with driver.session(database=database) as sess:
        res = await sess.run(
            "CALL db.index.fulltext.queryNodes($index, $q) YIELD node, score "
            "RETURN node.chunk_id AS chunk_id, score ORDER BY score DESC LIMIT $k",
            index=f"ft_{text_label}", q=query, k=top_k,
        )
        return [(r["chunk_id"], r["score"]) async for r in res]


def rrf_fuse(
    routes: list[list[tuple[str, float]]], rrf_k: int = 60
) -> list[tuple[str, float]]:
    scores: dict[str, float] = {}
    for route in routes:
        for rank, (chunk_id, _) in enumerate(route):
            scores[chunk_id] = scores.get(chunk_id, 0.0) + 1.0 / (rrf_k + rank)
    return sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
