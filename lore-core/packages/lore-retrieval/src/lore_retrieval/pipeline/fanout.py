"""Parallel retrieval fan-out: text vector + fulltext -> RRF fuse -> dedup.

The first pipeline stage. Runs the two text-lane routes concurrently, records
each route's ranked candidates for provenance, then fuses with Reciprocal Rank
Fusion and deduplicates by canonical chunk_id.

Degradation (spec): a route that fails does not sink the lane — the other route
still answers, and the failed route name is returned so the caller can record it.
"""
import asyncio

from lore_retrieval.contracts import FanoutResult, RetrievalCandidate, Route
from lore_retrieval.interfaces import ChunkSearchBackend
from lore_retrieval.neo4j_spike import rrf_fuse


async def fan_out_and_fuse(
    backend: ChunkSearchBackend,
    query: str,
    *,
    vector_k: int = 50,
    fulltext_k: int = 50,
    rrf_k: int = 60,
    index_version: str = "spike1",
) -> tuple[FanoutResult, list[str]]:
    raw = await asyncio.gather(
        backend.vector_search(query, vector_k),
        backend.fulltext_search(query, fulltext_k),
        return_exceptions=True,
    )

    degraded: list[str] = []
    resolved: list[list[tuple[str, float]]] = []
    for name, result in (("vector_search_failed", raw[0]), ("fulltext_search_failed", raw[1])):
        if isinstance(result, BaseException):
            degraded.append(name)
            resolved.append([])
        else:
            resolved.append(result)
    vec, ft = resolved[0], resolved[1]

    per_route: list[RetrievalCandidate] = []
    for route, results in ((Route.vector, vec), (Route.fulltext, ft)):
        for rank, (chunk_id, score) in enumerate(results):
            per_route.append(
                RetrievalCandidate(
                    chunk_id=chunk_id,
                    route=route,
                    route_rank=rank,
                    first_stage_score=score,
                    index_version=index_version,
                )
            )

    fused = rrf_fuse([vec, ft], rrf_k=rrf_k)
    return FanoutResult(per_route=per_route, fused=fused), degraded
