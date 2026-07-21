"""Deterministic in-memory implementations of the retrieval interfaces.

These let the whole pipeline run and be tested offline — no Neo4j, embeddings,
reranker, SQL DB, or LLM. Scoring is intentionally simple and reproducible; the
real backends produce better relevance behind the same interface.
"""
import re

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
