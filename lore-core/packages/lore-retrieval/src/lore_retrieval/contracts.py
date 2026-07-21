"""Typed contracts shared across the retrieval pipeline.

These are Lore-owned application types — never upstream library types — so the
backend behind any stage can change without changing the orchestration.
"""
from enum import Enum

from pydantic import BaseModel


class Route(str, Enum):
    vector = "vector"
    fulltext = "fulltext"
    section_parent = "section_parent"
    section_child = "section_child"
    next_neighbor = "next_neighbor"
    table_lane = "table_lane"


class RetrievalCandidate(BaseModel):
    """One route's view of a chunk. Route ranks/scores are diagnostic — vector,
    Lucene, and structural expansion do not share one scale."""

    chunk_id: str
    route: Route
    route_rank: int
    first_stage_score: float
    index_version: str = "spike1"
    structural_path_summary: str | None = None


class FanoutResult(BaseModel):
    per_route: list[RetrievalCandidate]  # every route's candidates, for provenance
    fused: list[tuple[str, float]]  # (chunk_id, rrf_score), deduped by chunk_id, ranked


class EvidenceEnvelope(BaseModel):
    """A canonical, verified piece of evidence. ``fulltext`` is the hash-linked
    answer context; ``display_text``/``coordinates`` are for citation and
    ``payload_refs`` is the trusted SQL-lineage locator (never an SQL trigger)."""

    chunk_id: str
    fulltext: str
    display_text: str
    coordinates: dict
    payload_refs: list
    run_id: str
    index_version: str
    fulltext_hash: str


class ResolutionResult(BaseModel):
    resolved: list[EvidenceEnvelope]
    rejected: list[tuple[str, str]]  # (chunk_id, reason): missing|wrong_version|superseded|hash_mismatch


class ContextGroup(BaseModel):
    """A coherent local window of source context (small-to-big / parent-child).
    Retains every canonical member ``chunk_id``; ``citations`` target the
    original contributing chunks. Never spans documents; never the whole
    document merely because two distant chunks matched."""

    document_id: str
    section_id: str
    section_path: tuple[str, ...]
    scope: str  # window | section | parent_section
    chunk_ids: list[str]
    start_position: int
    end_position: int
    text: str
    retrieval_routes: list[str] = []
    group_score: float
    citations: list[str]
    truncation_reason: str | None = None
