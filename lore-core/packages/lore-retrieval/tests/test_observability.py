from lore_retrieval.fakes import (
    FakeChatModel,
    FakeReranker,
    FakeSqlRunner,
    InMemoryChunkContextLoader,
    InMemoryChunkSearchBackend,
    InMemoryEvidenceResolver,
    InMemoryGraphExpansion,
)
from lore_retrieval.observability import CompositeTracer, NullTracer, RecordingTracer
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


def _pipeline(tracer, *, rerank_floor: float = 0.0):
    projection = build_structural_projection(CORPUS)
    backend = InMemoryChunkSearchBackend(CORPUS)
    return RetrievalPipeline(
        chunk_search=backend, graph_expansion=InMemoryGraphExpansion(projection),
        reranker=FakeReranker(), resolver=InMemoryEvidenceResolver(CORPUS),
        table_search=backend, sql_runner=FakeSqlRunner({}),
        chat_model=FakeChatModel(lambda _p: "ответ [1]"),
        context_loader=InMemoryChunkContextLoader(CORPUS),
        tracer=tracer, rerank_floor=rerank_floor,
    )


async def test_tracer_records_every_stage():
    tracer = RecordingTracer()
    await _pipeline(tracer).answer("премия формула")
    stages = set(tracer.stages())
    assert {
        "text_fanout", "text_expansion", "text_rerank", "text_resolve",
        "grouping", "table_discover", "table_sql", "arbitration", "cite",
    } <= stages
    by_stage = dict(tracer.events)
    # un-migrated stages keep their bounded-count payload
    assert "fused" in by_stage["text_fanout"]
    # arbitration + cite now carry the uniform {input, output} with real content
    assert "answer" in by_stage["arbitration"]["output"]
    assert isinstance(by_stage["cite"]["output"]["citations"], list)


async def test_default_tracer_is_noop_and_pipeline_still_works():
    result = await _pipeline(NullTracer()).answer("премия формула")
    assert result.decision.answer == "ответ [1]"     # no-op tracer doesn't disturb the flow


async def test_rerank_floor_drops_weak_seeds_but_never_empties():
    tracer = RecordingTracer()
    # A floor above every FakeReranker score drops all but the top seed — the
    # pipeline still produces evidence (never empty) and records what was floored.
    result = await _pipeline(tracer, rerank_floor=100.0).answer("премия формула")
    ev = dict(tracer.events)["text_rerank"]
    assert ev["candidates"] >= 1
    assert ev["floored"] >= 1
    assert result.groups


async def test_rerank_floor_zero_is_a_noop():
    tracer = RecordingTracer()
    await _pipeline(tracer, rerank_floor=0.0).answer("премия формула")
    assert dict(tracer.events)["text_rerank"]["floored"] == 0


def test_composite_tracer_fans_out_to_all_children():
    a, b = RecordingTracer(), RecordingTracer()
    CompositeTracer([a, b]).record("text_fanout", {"fused": 3})
    assert a.events == [("text_fanout", {"fused": 3})]
    assert b.events == [("text_fanout", {"fused": 3})]


def test_composite_tracer_isolates_a_failing_child():
    class Boom:
        def record(self, stage, payload):
            raise RuntimeError("sink down")

    good = RecordingTracer()
    # A broken sink must not stop the others, nor break the pipeline.
    CompositeTracer([Boom(), good]).record("cite", {"citations": 1})
    assert good.events == [("cite", {"citations": 1})]


from lore_retrieval.observability import stage_io  # noqa: E402


def test_stage_io_shapes_input_and_output():
    assert stage_io(input={"q": "x"}, output={"n": 1}) == {
        "input": {"q": "x"},
        "output": {"n": 1},
    }


def test_stage_io_defaults_to_none():
    assert stage_io() == {"input": None, "output": None}
    assert stage_io(output={"a": 1}) == {"input": None, "output": {"a": 1}}
