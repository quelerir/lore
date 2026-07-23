from lore_retrieval.fakes import (
    FakeChatModel,
    FakeReranker,
    FakeSqlRunner,
    InMemoryChunkContextLoader,
    InMemoryChunkSearchBackend,
    InMemoryEvidenceResolver,
    InMemoryGraphExpansion,
)
from lore_retrieval.observability import RecordingTracer
from lore_retrieval.pipeline.graph import RetrievalPipeline
from lore_retrieval.projection_model import build_structural_projection
from lore_retrieval.source import SourceChunk

CORPUS = [
    SourceChunk(chunk_id="c1", document_id="d", run_id="d", chunk_type="text", position=1,
                heading_path=("Root", "Премия"), vector_text="премия формула",
                fulltext="премия формула", display_text="премия формула",
                vector_text_hash="h", fulltext_hash="h"),
]


def _pipeline(tracer):
    projection = build_structural_projection(CORPUS)
    backend = InMemoryChunkSearchBackend(CORPUS)
    return RetrievalPipeline(
        chunk_search=backend, graph_expansion=InMemoryGraphExpansion(projection),
        reranker=FakeReranker(), resolver=InMemoryEvidenceResolver(CORPUS),
        table_search=backend, sql_runner=FakeSqlRunner({}),
        chat_model=FakeChatModel(lambda _p: "ответ по премии [1]"),
        context_loader=InMemoryChunkContextLoader(CORPUS),
        tracer=tracer,
    )


async def test_arbitration_trace_carries_answer_text():
    tracer = RecordingTracer()
    await _pipeline(tracer).answer("премия формула")
    arb = next(data for stage, data in tracer.events if stage == "arbitration")
    assert arb["output"]["answer"] == "ответ по премии [1]"
    assert "input" in arb and "question" in arb["input"]


async def test_cite_trace_carries_citation_list():
    tracer = RecordingTracer()
    await _pipeline(tracer).answer("премия формула")
    cite = next(data for stage, data in tracer.events if stage == "cite")
    cits = cite["output"]["citations"]
    assert isinstance(cits, list) and cits
    assert set(cits[0]) >= {"marker", "file", "chunk", "kind", "preview"}
