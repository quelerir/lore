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
