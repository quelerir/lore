"""Cross-encoder rerank stage.

Reranks the union of fused text seeds and structurally expanded candidates
against the query, over each chunk's derived fulltext. Route ranks upstream are
diagnostic; this stage produces the single comparable ordering used to pick
evidence seeds.
"""
from lore_retrieval.interfaces import Reranker


async def rerank_stage(
    reranker: Reranker,
    query: str,
    candidate_ids: list[str],
    text_by_id: dict[str, str],
    *,
    top_k: int = 12,
) -> list[tuple[str, float]]:
    docs = [(chunk_id, text_by_id.get(chunk_id, "")) for chunk_id in candidate_ids]
    return await reranker.rerank(query, docs, top_k)
