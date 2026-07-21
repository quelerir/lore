"""Throwaway (P0 Task 9): measure vector/fulltext/hybrid latency at scale.

Requires a projected corpus and RETRIEVAL_NEO4J_* + Ollama env. Untested until creds.
"""
import asyncio
import statistics
import time

from neo4j import AsyncGraphDatabase

from lore_retrieval.config import get_settings
from lore_retrieval.embeddings import Neo4jGraphRagEmbedder, OllamaEmbeddingBackend
from lore_retrieval.neo4j_spike import fulltext_search, rrf_fuse, vector_search

QUERIES = [
    "как рассчитывается премия", "табельный номер сотрудника",
    "матрица грейдов", "отпускные выплаты", "структура подразделения",
]


async def timed(coro_factory, runs=20):
    lat = []
    for _ in range(runs):
        for q in QUERIES:
            t0 = time.perf_counter()
            await coro_factory(q)
            lat.append((time.perf_counter() - t0) * 1000)
    lat.sort()
    p50 = statistics.median(lat)
    p90 = lat[int(len(lat) * 0.9)]
    return p50, p90


async def main():
    s = get_settings()
    emb = Neo4jGraphRagEmbedder(
        OllamaEmbeddingBackend(s.embedding_model, s.ollama_base_url, s.embedding_dim)
    )
    d = AsyncGraphDatabase.driver(s.neo4j_uri, auth=(s.neo4j_user, s.neo4j_password))

    async def vec(q):
        return await vector_search(d, s.neo4j_database, "spike1", q, emb, 50)

    async def ft(q):
        return await fulltext_search(d, s.neo4j_database, "spike1", q, 50)

    async def hybrid(q):
        v = await vec(q)
        f = await ft(q)
        return rrf_fuse([v, f])

    for name, fac in [("vector", vec), ("fulltext", ft), ("hybrid", hybrid)]:
        p50, p90 = await timed(fac)
        print(f"{name:9s} p50={p50:.1f}ms p90={p90:.1f}ms")
    await d.close()


if __name__ == "__main__":
    asyncio.run(main())
