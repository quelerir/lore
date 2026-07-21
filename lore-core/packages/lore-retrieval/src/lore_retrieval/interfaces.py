"""Lore-owned retrieval interfaces (Protocols).

Every external dependency of the pipeline sits behind one of these, with two
implementations: a deterministic in-memory fake (offline tests) and the real
backend (Neo4j / cross-encoder / lore_core / toast / OpenRouter). The pipeline
orchestration depends only on these Protocols, so backends swap by injection.
"""
from typing import Protocol, runtime_checkable

from lore_retrieval.contracts import (
    ResolutionResult,
    RetrievalCandidate,
    SqlRequest,
    SQLResult,
)


@runtime_checkable
class ChunkSearchBackend(Protocol):
    """Text-lane dense + lexical search over TextChunk nodes.

    Returns ``(chunk_id, score)`` bounded by ``top_k``. TableChunk nodes do not
    participate in the text lane.
    """

    async def vector_search(self, query: str, top_k: int) -> list[tuple[str, float]]: ...
    async def fulltext_search(self, query: str, top_k: int) -> list[tuple[str, float]]: ...


@runtime_checkable
class GraphExpansionBackend(Protocol):
    """Bounded structural expansion from seed chunks.

    For each seed, discover the containing section's siblings, direct NEXT
    neighbours, and (at most one level up) the parent section's chunks. Every
    returned candidate carries a structural route and a bounded path summary.
    All caps are enforced; no route returns unbounded nodes.
    """

    async def expand(
        self,
        seed_chunk_ids: list[str],
        *,
        max_next: int = 1,
        max_siblings: int = 3,
        parent_ascent: int = 1,
    ) -> list[RetrievalCandidate]: ...


@runtime_checkable
class Reranker(Protocol):
    """Cross-encoder rerank of ``(chunk_id, text)`` docs against the query.

    Returns ``(chunk_id, score)`` ranked best-first, bounded by ``top_k``.
    """

    async def rerank(
        self, query: str, docs: list[tuple[str, str]], top_k: int
    ) -> list[tuple[str, float]]: ...


@runtime_checkable
class CanonicalEvidenceResolver(Protocol):
    """Batch-resolve final canonical envelopes, rejecting missing / stale /
    superseded / wrong-version / hash-mismatched evidence. Not a retrieval stage
    — it supplies trusted citations and SQL lineage for already-selected chunks.
    """

    async def resolve(self, chunk_ids: list[str], *, index_version: str) -> ResolutionResult: ...


@runtime_checkable
class TableSearchBackend(Protocol):
    """Table-lane dense + lexical search over TableChunk nodes only. Runs on
    every query in parallel with the text lane."""

    async def table_vector_search(self, query: str, top_k: int) -> list[tuple[str, float]]: ...
    async def table_fulltext_search(self, query: str, top_k: int) -> list[tuple[str, float]]: ...


@runtime_checkable
class SqlRunner(Protocol):
    """Executes one read-only SQL request against exactly one registered payload
    and returns a typed outcome. Physical table names come only from the trusted
    registry inside this runner."""

    async def run(self, request: SqlRequest) -> SQLResult: ...
