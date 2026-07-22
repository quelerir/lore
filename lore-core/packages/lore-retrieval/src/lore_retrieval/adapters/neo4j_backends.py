"""Real Neo4j implementations of the retrieval interfaces.

VERIFIED LIVE against Neo4j Community 5.26.28 on 2026-07-22 via
``spikes/live_validate_neo4j.py`` (ensure_indexes + project_batch +
project_structure + vector/fulltext/table search + expansion, then cleanup).
Drop-in adapters behind ``ChunkSearchBackend`` / ``TableSearchBackend`` /
``GraphExpansionBackend``; also unit-tested (query construction + result mapping).
All search/expansion uses fixed parameterized Cypher; only internal index/label
identifiers are interpolated.
"""
from neo4j import AsyncDriver

from lore_retrieval import neo4j_spike
from lore_retrieval.contracts import RetrievalCandidate, Route
from lore_retrieval.neo4j_spike import _labels


class Neo4jChunkSearchBackend:
    def __init__(self, driver: AsyncDriver, database: str, index_version: str, embedder) -> None:
        self._driver = driver
        self._db = database
        self._v = index_version
        self._embedder = embedder

    async def vector_search(self, query: str, top_k: int) -> list[tuple[str, float]]:
        return await neo4j_spike.vector_search(
            self._driver, self._db, self._v, query, self._embedder, top_k
        )

    async def fulltext_search(self, query: str, top_k: int) -> list[tuple[str, float]]:
        return await neo4j_spike.fulltext_search(self._driver, self._db, self._v, query, top_k)


class Neo4jTableSearchBackend:
    def __init__(self, driver: AsyncDriver, database: str, index_version: str, embedder) -> None:
        self._driver = driver
        self._db = database
        self._v = index_version
        self._embedder = embedder

    async def table_vector_search(self, query: str, top_k: int) -> list[tuple[str, float]]:
        return await neo4j_spike.table_vector_search(
            self._driver, self._db, self._v, query, self._embedder, top_k
        )

    async def table_fulltext_search(self, query: str, top_k: int) -> list[tuple[str, float]]:
        return await neo4j_spike.table_fulltext_search(
            self._driver, self._db, self._v, query, top_k
        )


# One bounded template: NEXT neighbours, in-section siblings, one-level parent chunks.
_EXPAND_CYPHER = """
MATCH (seed:{label} {{chunk_id: $seed}})
CALL (seed) {{
    MATCH (seed)-[:NEXT]->(nx) RETURN nx AS n, 'next_neighbor' AS route
    UNION
    MATCH (pv)-[:NEXT]->(seed) RETURN pv AS n, 'next_neighbor' AS route
    UNION
    MATCH (sec)-[:HAS_CHUNK]->(seed), (sec)-[:HAS_CHUNK]->(sib)
    WHERE sib <> seed RETURN sib AS n, 'section_child' AS route LIMIT $max_siblings
    UNION
    MATCH (parent)-[:HAS_SUBSECTION]->(sec)-[:HAS_CHUNK]->(seed),
    (parent)-[:HAS_CHUNK]->(pc) RETURN pc AS n, 'section_parent' AS route LIMIT $max_siblings
}}
RETURN DISTINCT n.chunk_id AS chunk_id, route
"""


class Neo4jGraphExpansionBackend:
    def __init__(self, driver: AsyncDriver, database: str, index_version: str) -> None:
        self._driver = driver
        self._db = database
        self._v = index_version

    async def expand(
        self,
        seed_chunk_ids: list[str],
        *,
        max_next: int = 1,
        max_siblings: int = 3,
        parent_ascent: int = 1,
    ) -> list[RetrievalCandidate]:
        text_label, _ = _labels(self._v)
        cypher = _EXPAND_CYPHER.format(label=text_label)
        seen = set(seed_chunk_ids)
        out: list[RetrievalCandidate] = []
        async with self._driver.session(database=self._db) as sess:
            for seed in seed_chunk_ids:
                res = await sess.run(cypher, seed=seed, max_siblings=max_siblings)
                async for r in res:
                    chunk_id, route = r["chunk_id"], r["route"]
                    if chunk_id in seen:
                        continue
                    if route == "section_parent" and parent_ascent <= 0:
                        continue
                    if route == "next_neighbor" and max_next <= 0:
                        continue
                    seen.add(chunk_id)
                    out.append(
                        RetrievalCandidate(
                            chunk_id=chunk_id,
                            route=Route(route),
                            route_rank=len(out),
                            first_stage_score=0.0,
                            index_version=self._v,
                        )
                    )
        return out
