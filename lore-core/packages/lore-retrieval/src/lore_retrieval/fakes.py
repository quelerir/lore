"""Deterministic in-memory implementations of the retrieval interfaces.

These let the whole pipeline run and be tested offline — no Neo4j, embeddings,
reranker, SQL DB, or LLM. Scoring is intentionally simple and reproducible; the
real backends produce better relevance behind the same interface.
"""
import re

from lore_retrieval.contracts import RetrievalCandidate, Route
from lore_retrieval.projection_model import StructuralProjection
from lore_retrieval.source import SourceChunk

_TOKEN = re.compile(r"\w+", re.UNICODE)


def _tokens(text: str) -> list[str]:
    return [t.lower() for t in _TOKEN.findall(text)]


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
        q = _tokens(query)
        scored: list[tuple[str, float]] = []
        for c in self._text:
            toks = _tokens(c.fulltext)
            score = sum(toks.count(t) for t in q)
            if score > 0:
                scored.append((c.chunk_id, float(score)))
        scored.sort(key=lambda kv: (-kv[1], kv[0]))
        return scored[:top_k]

    async def vector_search(self, query: str, top_k: int) -> list[tuple[str, float]]:
        q = set(_tokens(query))
        scored: list[tuple[str, float]] = []
        for c in self._text:
            toks = set(_tokens(c.vector_text))
            if not toks or not q:
                continue
            jaccard = len(q & toks) / len(q | toks)
            if jaccard > 0:
                scored.append((c.chunk_id, jaccard))
        scored.sort(key=lambda kv: (-kv[1], kv[0]))
        return scored[:top_k]


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
