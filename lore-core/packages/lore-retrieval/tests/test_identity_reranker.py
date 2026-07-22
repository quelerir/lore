"""IdentityReranker: preserves fusion order, never re-scores by term overlap."""
from lore_retrieval.fakes import IdentityReranker


async def test_preserves_input_order_and_caps_top_k():
    docs = [("a", "нерелевантный текст"), ("b", "юристконсульт Суворова"), ("c", "прочее")]
    out = await IdentityReranker().rerank("юристы", docs, top_k=2)
    # order preserved (a, b) — b NOT demoted despite "юристы" not literally in its text
    assert [cid for cid, _ in out] == ["a", "b"]
    assert out[0][1] > out[1][1]  # descending positional scores


async def test_empty_docs():
    assert await IdentityReranker().rerank("q", [], top_k=5) == []
