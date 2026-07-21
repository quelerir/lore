"""Bounded structural expansion stage.

Takes the strongest fused text seeds and asks the GraphExpansionBackend for
bounded structural neighbours (NEXT, in-section siblings, one-level parent).
Expansion is evidence *discovery*: expanded candidates still pass through the
reranker and context budget downstream.
"""
from lore_retrieval.contracts import FanoutResult, RetrievalCandidate
from lore_retrieval.interfaces import GraphExpansionBackend


async def expand_from_fanout(
    backend: GraphExpansionBackend,
    fanout: FanoutResult,
    *,
    seed_count: int = 10,
    max_next: int = 1,
    max_siblings: int = 3,
    parent_ascent: int = 1,
) -> list[RetrievalCandidate]:
    seeds = [chunk_id for chunk_id, _ in fanout.fused[:seed_count]]
    return await backend.expand(
        seeds, max_next=max_next, max_siblings=max_siblings, parent_ascent=parent_ascent
    )
