"""Lore-owned retrieval interfaces (Protocols).

Every external dependency of the pipeline sits behind one of these, with two
implementations: a deterministic in-memory fake (offline tests) and the real
backend (Neo4j / cross-encoder / lore_core / toast / OpenRouter). The pipeline
orchestration depends only on these Protocols, so backends swap by injection.
"""
from typing import Protocol, runtime_checkable


@runtime_checkable
class ChunkSearchBackend(Protocol):
    """Text-lane dense + lexical search over TextChunk nodes.

    Returns ``(chunk_id, score)`` bounded by ``top_k``. TableChunk nodes do not
    participate in the text lane.
    """

    async def vector_search(self, query: str, top_k: int) -> list[tuple[str, float]]: ...
    async def fulltext_search(self, query: str, top_k: int) -> list[tuple[str, float]]: ...
