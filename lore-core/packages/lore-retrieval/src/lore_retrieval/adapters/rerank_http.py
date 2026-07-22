"""HTTP cross-encoder reranker (P2) behind the ``Reranker`` protocol.

A bge-reranker (e.g. ``bge-reranker-v2-m3``) served over HTTP, mirroring the
``HttpEmbeddingBackend`` deployment: one host+container-reachable network service
over the VPN. The pipeline's P0 used ``IdentityReranker`` (keep RRF-fusion order);
this replaces it with a real cross-encoder when ``RETRIEVAL_RERANKER`` is
configured, sharpening top-k precision before grouping / table selection.

Endpoint contract (LIVE-VERIFY against the real server): ``POST {base}/rerank``
with ``{"query": str, "texts": [str]}`` → either a TEI-style list
``[{"index": int, "score": float}, ...]`` or ``{"results": [ ... ]}``. The pure
``parse_rerank_response`` handles both, so the mapping is offline-testable.

Sync ``httpx`` (like the embeddings backend); the async ``rerank`` runs the POST
off the event loop via ``asyncio.to_thread``.
"""
import asyncio
from typing import Any


def parse_rerank_response(
    payload: Any, ids: list[str]
) -> list[tuple[str, float]]:
    """Map a reranker response to ``(chunk_id, score)`` sorted best-first. Accepts a
    bare list or a ``{"results": [...]}`` envelope; each item is ``{index, score}``.
    Out-of-range indices are dropped (never a wrong chunk id)."""
    items = payload.get("results") if isinstance(payload, dict) else payload
    if not isinstance(items, list):
        return []
    ranked: list[tuple[str, float]] = []
    for item in items:
        if not isinstance(item, dict) or "index" not in item or "score" not in item:
            continue
        idx = item["index"]
        if not isinstance(idx, int) or idx < 0 or idx >= len(ids):
            continue
        ranked.append((ids[idx], float(item["score"])))
    ranked.sort(key=lambda pair: pair[1], reverse=True)
    return ranked


class HttpReranker:
    """``Reranker`` impl calling a bge-reranker HTTP service. Inject ``client`` in
    tests; production builds one ``httpx.Client`` (kept-alive pool) per instance."""

    def __init__(self, base_url: str, *, timeout: float = 30.0, client: Any = None) -> None:
        self._url = base_url.rstrip("/") + "/rerank"
        if client is not None:
            self._client = client
        else:
            import httpx

            self._client = httpx.Client(timeout=timeout)

    def _rank(self, query: str, texts: list[str], ids: list[str]) -> list[tuple[str, float]]:
        resp = self._client.post(self._url, json={"query": query, "texts": texts})
        resp.raise_for_status()
        return parse_rerank_response(resp.json(), ids)

    async def rerank(
        self, query: str, docs: list[tuple[str, str]], top_k: int
    ) -> list[tuple[str, float]]:
        if not docs:
            return []
        ids = [chunk_id for chunk_id, _ in docs]
        texts = [text for _, text in docs]
        ranked = await asyncio.to_thread(self._rank, query, texts, ids)
        return ranked[:top_k]


def build_reranker(endpoint: str | None, *, timeout: float = 30.0) -> HttpReranker | None:
    """Build an ``HttpReranker`` from the configured endpoint, or ``None`` when unset
    (the factory then falls back to ``IdentityReranker`` — RRF order preserved)."""
    if not endpoint:
        return None
    return HttpReranker(endpoint, timeout=timeout)
