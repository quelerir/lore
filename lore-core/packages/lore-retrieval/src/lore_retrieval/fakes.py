"""Deterministic in-memory implementations of the retrieval interfaces.

These let the whole pipeline run and be tested offline — no Neo4j, embeddings,
reranker, SQL DB, or LLM. Scoring is intentionally simple and reproducible; the
real backends produce better relevance behind the same interface.
"""
import re
from collections.abc import Callable

from lore_retrieval.contracts import (
    EvidenceEnvelope,
    ResolutionResult,
    RetrievalCandidate,
    Route,
    SqlRequest,
    SQLResult,
    SQLStatus,
)
from lore_retrieval.projection_model import StructuralProjection
from lore_retrieval.source import SourceChunk

_TOKEN = re.compile(r"\w+", re.UNICODE)


def _tokens(text: str) -> list[str]:
    return [t.lower() for t in _TOKEN.findall(text)]


def _rank_fulltext(chunks: list[SourceChunk], query: str, top_k: int) -> list[tuple[str, float]]:
    q = _tokens(query)
    scored = [
        (c.chunk_id, float(sum(_tokens(c.fulltext).count(t) for t in q)))
        for c in chunks
    ]
    scored = [(cid, s) for cid, s in scored if s > 0]
    scored.sort(key=lambda kv: (-kv[1], kv[0]))
    return scored[:top_k]


def _rank_vector(chunks: list[SourceChunk], query: str, top_k: int) -> list[tuple[str, float]]:
    q = set(_tokens(query))
    scored: list[tuple[str, float]] = []
    for c in chunks:
        toks = set(_tokens(c.vector_text))
        if toks and q:
            jaccard = len(q & toks) / len(q | toks)
            if jaccard > 0:
                scored.append((c.chunk_id, jaccard))
    scored.sort(key=lambda kv: (-kv[1], kv[0]))
    return scored[:top_k]


class InMemoryChunkSearchBackend:
    """Offline stand-in for a Neo4j ChunkSearchBackend over one ready corpus.

    - ``fulltext_search``: lexical — summed term frequency of query tokens in
      ``fulltext`` (exact-token behaviour, like Lucene).
    - ``vector_search``: 'semantic-ish' — Jaccard of query vs ``vector_text``
      token sets (a distinct, dense-like signal).

    Only non-table chunks participate; TableChunk nodes are held separately for
    the table lane (added in a later increment).
    """

    def __init__(self, chunks: list[SourceChunk]) -> None:
        self._text = [c for c in chunks if not c.is_table]
        self._table = [c for c in chunks if c.is_table]

    async def fulltext_search(self, query: str, top_k: int) -> list[tuple[str, float]]:
        return _rank_fulltext(self._text, query, top_k)

    async def vector_search(self, query: str, top_k: int) -> list[tuple[str, float]]:
        return _rank_vector(self._text, query, top_k)

    async def table_fulltext_search(self, query: str, top_k: int) -> list[tuple[str, float]]:
        return _rank_fulltext(self._table, query, top_k)

    async def table_vector_search(self, query: str, top_k: int) -> list[tuple[str, float]]:
        return _rank_vector(self._table, query, top_k)


class InMemoryGraphExpansion:
    """Offline stand-in for the Neo4j GraphExpansionBackend, driven by a
    StructuralProjection (see ``projection_model``). Mirrors the fixed bounded
    Cypher templates: NEXT neighbours, in-section siblings, one-level parent ascent.
    """

    def __init__(self, projection: StructuralProjection) -> None:
        self._chunk_section = dict(projection.chunk_section)
        self._section_by_id = {s.section_id: s for s in projection.sections}
        self._section_chunks: dict[str, list[str]] = {
            s.section_id: list(s.chunk_ids) for s in projection.sections
        }
        self._next: dict[str, str] = {}
        self._prev: dict[str, str] = {}
        for a, b in projection.next_edges:
            self._next[a] = b
            self._prev[b] = a

    def _path_summary(self, section_id: str | None) -> str:
        s = self._section_by_id.get(section_id) if section_id else None
        return "/".join(s.heading_path) if s and s.heading_path else "(root)"

    async def expand(
        self,
        seed_chunk_ids: list[str],
        *,
        max_next: int = 1,
        max_siblings: int = 3,
        parent_ascent: int = 1,
    ) -> list[RetrievalCandidate]:
        seen = set(seed_chunk_ids)
        out: list[RetrievalCandidate] = []

        def emit(chunk_id: str, route: Route, section_id: str | None) -> None:
            if chunk_id in seen:
                return
            seen.add(chunk_id)
            out.append(
                RetrievalCandidate(
                    chunk_id=chunk_id,
                    route=route,
                    route_rank=len(out),
                    first_stage_score=0.0,  # structural: no first-stage score
                    structural_path_summary=self._path_summary(section_id),
                )
            )

        for seed in seed_chunk_ids:
            sec_id = self._chunk_section.get(seed)

            # direct NEXT neighbours (previous and next), bounded
            if max_next > 0:
                for neighbour in (self._prev.get(seed), self._next.get(seed)):
                    if neighbour is not None:
                        emit(neighbour, Route.next_neighbor, self._chunk_section.get(neighbour))

            # in-section siblings, bounded
            for sib in self._section_chunks.get(sec_id, [])[:max_siblings + 1]:
                if sib != seed:
                    emit(sib, Route.section_child, sec_id)

            # one-level parent ascent, bounded
            section = self._section_by_id.get(sec_id) if sec_id else None
            if parent_ascent > 0 and section and section.parent_section_id:
                pid = section.parent_section_id
                for c in self._section_chunks.get(pid, [])[:max_siblings]:
                    emit(c, Route.section_parent, pid)

        return out


class FakeReranker:
    """Offline stand-in for a cross-encoder. Scores each doc by summed term
    frequency of query tokens in its text — a deterministic relevance proxy.
    """

    async def rerank(
        self, query: str, docs: list[tuple[str, str]], top_k: int
    ) -> list[tuple[str, float]]:
        q = _tokens(query)
        scored: list[tuple[str, float]] = []
        for chunk_id, text in docs:
            toks = _tokens(text)
            score = float(sum(toks.count(t) for t in q))
            scored.append((chunk_id, score))
        scored.sort(key=lambda kv: (-kv[1], kv[0]))
        return scored[:top_k]


class InMemoryEvidenceResolver:
    """Offline stand-in for the CanonicalEvidenceResolver over one ready corpus.

    Rejects requests that a real resolver would reject: unknown chunk (missing),
    a query index_version other than the active one (wrong_version), an
    explicitly superseded chunk, or a chunk flagged as hash-mismatched.
    """

    def __init__(
        self,
        chunks: list[SourceChunk],
        *,
        active_index_version: str = "spike1",
        superseded: frozenset[str] = frozenset(),
        hash_mismatch: frozenset[str] = frozenset(),
    ) -> None:
        self._by_id = {c.chunk_id: c for c in chunks}
        self._active = active_index_version
        self._superseded = set(superseded)
        self._hash_mismatch = set(hash_mismatch)

    async def resolve(self, chunk_ids: list[str], *, index_version: str) -> ResolutionResult:
        resolved: list[EvidenceEnvelope] = []
        rejected: list[tuple[str, str]] = []
        for cid in chunk_ids:
            chunk = self._by_id.get(cid)
            if chunk is None:
                rejected.append((cid, "missing"))
            elif index_version != self._active:
                rejected.append((cid, "wrong_version"))
            elif cid in self._superseded:
                rejected.append((cid, "superseded"))
            elif cid in self._hash_mismatch:
                rejected.append((cid, "hash_mismatch"))
            else:
                resolved.append(
                    EvidenceEnvelope(
                        chunk_id=cid,
                        fulltext=chunk.fulltext,
                        display_text=chunk.display_text or chunk.fulltext,
                        coordinates=chunk.coordinates,
                        payload_refs=chunk.payload_refs,
                        run_id=chunk.run_id,
                        index_version=self._active,
                        fulltext_hash=chunk.fulltext_hash,
                    )
                )
        return ResolutionResult(resolved=resolved, rejected=rejected)


class FakeChatModel:
    """Offline stand-in for the final generation model. Records prompts (so tests
    can assert the model was/was not called and what evidence it saw) and returns
    a deterministic response."""

    def __init__(self, responder: Callable[[str], str] | None = None) -> None:
        self.calls: list[str] = []
        self._responder = responder or (lambda _prompt: "ОТВЕТ")

    async def generate(self, prompt: str) -> str:
        self.calls.append(prompt)
        return self._responder(prompt)


class FakeSqlRunner:
    """Offline stand-in for the SQL module. Maps a payload_id to a canned typed
    outcome; unknown payloads return not_applicable. Records the requests it saw
    so tests can assert the fan-out ran exactly the selected payloads."""

    def __init__(self, outcomes: dict[str, SQLResult]) -> None:
        self._outcomes = outcomes
        self.seen: list[str] = []

    async def run(self, request: SqlRequest) -> SQLResult:
        self.seen.append(request.payload_id)
        canned = self._outcomes.get(request.payload_id)
        if canned is not None:
            return canned
        return SQLResult(
            payload_id=request.payload_id,
            chunk_id=request.chunk_id,
            status=SQLStatus.not_applicable,
        )
