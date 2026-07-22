"""Degradation behaviours: a failing stage degrades, it does not sink the turn."""
import lore_retrieval.pipeline.graph as graph_mod
from lore_retrieval.fakes import (
    FakeChatModel,
    FakeReranker,
    FakeSqlRunner,
    InMemoryChunkContextLoader,
    InMemoryChunkSearchBackend,
    InMemoryEvidenceResolver,
    InMemoryGraphExpansion,
)
from lore_retrieval.pipeline.fanout import fan_out_and_fuse
from lore_retrieval.pipeline.graph import RetrievalPipeline
from lore_retrieval.projection_model import build_structural_projection
from lore_retrieval.source import SourceChunk

CORPUS = [
    SourceChunk(chunk_id="c1", document_id="d", run_id="d", chunk_type="text", position=1,
                heading_path=("Root", "Премия"), vector_text="премия формула", fulltext="премия формула",
                display_text="премия формула", vector_text_hash="h", fulltext_hash="h"),
    SourceChunk(chunk_id="c2", document_id="d", run_id="d", chunk_type="text", position=2,
                heading_path=("Root", "Премия"), vector_text="формула оклад", fulltext="формула оклад",
                display_text="формула оклад", vector_text_hash="h", fulltext_hash="h"),
]


class OneLaneBackend(InMemoryChunkSearchBackend):
    """Text vector lane raises; fulltext (and table lanes) still work."""

    async def vector_search(self, query, top_k):
        raise RuntimeError("vector index down")


class BoomReranker:
    async def rerank(self, query, docs, top_k):
        raise RuntimeError("reranker down")


def _pipeline(**over):
    projection = build_structural_projection(CORPUS)
    backend = over.pop("backend", None) or InMemoryChunkSearchBackend(CORPUS)
    kwargs = dict(
        chunk_search=backend, graph_expansion=InMemoryGraphExpansion(projection),
        reranker=FakeReranker(), resolver=InMemoryEvidenceResolver(CORPUS),
        table_search=backend, sql_runner=FakeSqlRunner({}),
        chat_model=FakeChatModel(lambda _p: "ответ [1]"),
        context_loader=InMemoryChunkContextLoader(CORPUS),
    )
    kwargs.update(over)
    return RetrievalPipeline(**kwargs)


async def test_fanout_degrades_when_one_route_fails():
    res, degraded, _failures = await fan_out_and_fuse(OneLaneBackend(CORPUS), "премия формула")
    assert degraded == ["vector_search_failed"]
    assert [cid for cid, _ in res.fused]              # fulltext still produced candidates


async def test_pipeline_survives_vector_lane_failure():
    result = await _pipeline(backend=OneLaneBackend(CORPUS)).answer("премия формула")
    assert "vector_search_failed" in result.degradations
    assert result.groups                               # still grounded from fulltext
    assert result.decision.answer == "ответ [1]"


async def test_reranker_failure_falls_back_to_fused_order():
    result = await _pipeline(reranker=BoomReranker()).answer("премия формула")
    assert "reranker_failed" in result.degradations
    assert result.groups                               # evidence preserved via fallback order


async def test_auto_merging_failure_yields_singleton_groups(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("grouping down")

    monkeypatch.setattr(graph_mod, "build_context_groups", boom)
    result = await _pipeline().answer("премия формула")
    assert "auto_merging_failed" in result.degradations
    assert result.groups                               # individual chunks kept, not lost
    assert all(len(g.chunk_ids) == 1 for g in result.groups)
