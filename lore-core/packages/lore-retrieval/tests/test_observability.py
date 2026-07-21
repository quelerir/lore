from lore_retrieval.fakes import (
    FakeChatModel,
    FakeReranker,
    FakeSqlRunner,
    InMemoryChunkSearchBackend,
    InMemoryEvidenceResolver,
    InMemoryGraphExpansion,
)
from lore_retrieval.observability import NullTracer, RecordingTracer
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


def _pipeline(tracer):
    projection = build_structural_projection(CORPUS)
    backend = InMemoryChunkSearchBackend(CORPUS)
    return RetrievalPipeline(
        chunk_search=backend, graph_expansion=InMemoryGraphExpansion(projection),
        reranker=FakeReranker(), resolver=InMemoryEvidenceResolver(CORPUS),
        table_search=backend, sql_runner=FakeSqlRunner({}),
        chat_model=FakeChatModel(lambda _p: "ответ [1]"),
        projection=projection, positions={c.chunk_id: c.position for c in CORPUS},
        text_by_id={c.chunk_id: c.fulltext for c in CORPUS}, payload_by_chunk={},
        tracer=tracer,
    )


async def test_tracer_records_every_stage():
    tracer = RecordingTracer()
    await _pipeline(tracer).answer("премия формула")
    stages = set(tracer.stages())
    assert {
        "text_fanout", "text_expansion", "text_rerank", "text_resolve",
        "grouping", "table_discover", "table_sql", "arbitration", "cite",
    } <= stages
    # payloads carry bounded counts, not content
    by_stage = dict(tracer.events)
    assert "fused" in by_stage["text_fanout"]
    assert by_stage["cite"]["citations"] >= 0


async def test_default_tracer_is_noop_and_pipeline_still_works():
    result = await _pipeline(NullTracer()).answer("премия формула")
    assert result.decision.answer == "ответ [1]"     # no-op tracer doesn't disturb the flow
