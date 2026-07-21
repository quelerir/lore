from lore_retrieval.fakes import FakeReranker
from lore_retrieval.pipeline.rerank import rerank_stage


async def test_rerank_orders_by_query_overlap_and_bounds_top_k():
    reranker = FakeReranker()
    text_by_id = {
        "a": "премия сотрудника премия",   # two hits
        "b": "премия годовая",             # one hit
        "c": "отпускные выплаты",          # zero hits
    }
    out = await rerank_stage(reranker, "премия", ["a", "b", "c"], text_by_id, top_k=2)
    assert [cid for cid, _ in out] == ["a", "b"]   # c dropped by top_k, a before b


async def test_rerank_missing_text_scores_zero():
    reranker = FakeReranker()
    out = await rerank_stage(reranker, "премия", ["x"], {}, top_k=5)
    assert out == [("x", 0.0)]
