"""Typed contracts shared across the retrieval pipeline.

These are Lore-owned application types — never upstream library types — so the
backend behind any stage can change without changing the orchestration.
"""
from enum import Enum
from typing import Literal

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


class TableCandidate(BaseModel):
    """A discovered table, deduped to one physical payload. ``payload_id`` is the
    trusted locator; the physical table name is resolved only by the registry in
    the SQL runner, never from Neo4j text."""

    chunk_id: str
    payload_id: str
    score: float
    feasible: bool = True
    reason: str | None = None
    run_id: str = ""                      # anchor provenance (from the loaded SourceChunk)
    heading_path: tuple[str, ...] = ()


class SQLStatus(str, Enum):
    success = "success"
    empty = "empty"
    not_applicable = "not_applicable"
    unsupported = "unsupported"
    ambiguity = "ambiguity"
    validation_error = "validation_error"
    execution_error = "execution_error"
    timeout = "timeout"


class TableProfile(BaseModel):
    """Bounded description of a registered table: purpose, columns, types, and a
    few sample values. It cannot enumerate every row — a query value absent from
    samples must not reject an otherwise-expressible schema."""

    payload_id: str
    purpose: str = ""
    columns: list[str] = []
    column_types: dict[str, str] = {}
    sample_values: dict[str, list] = {}


class QueryRequirements(BaseModel):
    """A lightweight extraction of what the question needs. Helps assess schema
    feasibility; it is not a pre-retrieval SQL gate and cannot pick a table."""

    concepts: list[str] = []
    filters: list[str] = []
    measures: list[str] = []


class SqlRequest(BaseModel):
    question: str
    payload_id: str
    chunk_id: str


class SQLResult(BaseModel):
    payload_id: str
    chunk_id: str
    status: SQLStatus
    rows: list[dict] = []
    answer_summary: str | None = None
    error: str | None = None


class AgentDecision(BaseModel):
    """The top-level agent's evidence choice and final answer. Conflicting SQL
    results stay explicit (``note``); text and SQL evidence are attributed, never
    mechanically merged; no answer is produced from thin air when nothing grounds it."""

    answer: str
    used_evidence_chunk_ids: list[str]
    used_sql_payload_ids: list[str]
    citations: list[str]
    note: str | None = None  # conflicting_sql_results | no_grounded_evidence | ...
    # index -> contributing chunk_ids, mirroring the [n] evidence enumeration shown
    # to the model, so the cite step can resolve the markers it emitted.
    evidence_map: dict[int, list[str]] = {}
    # index -> the SQL success's anchor chunk_id, continuing the [n] sequence after
    # the text groups; disjoint index range from evidence_map.
    sql_evidence_map: dict[int, str] = {}


class Citation(BaseModel):
    """A model-chosen source reference rendered as a clickable preview card that
    deep-links into the FileViewer. Built only from verified EvidenceEnvelopes."""

    chunk_id: str
    run_id: str
    logical_file_key: str
    preview_text: str
    heading_path: tuple[str, ...]
    deep_link: str
    kind: Literal["text", "table"] = "text"
    marker: int | None = None  # the [n] index; None for deterministic-fallback citations


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


class PipelineResult(BaseModel):
    """Everything one user turn produced — the decision plus the intermediate
    artifacts (for citations, observability, and tests)."""

    decision: AgentDecision
    groups: list[ContextGroup]
    sql_results: list[SQLResult]
    table_candidates: list[TableCandidate]
    citations: list[Citation] = []
    rejected_evidence: list[tuple[str, str]] = []
    degradations: list[str] = []
