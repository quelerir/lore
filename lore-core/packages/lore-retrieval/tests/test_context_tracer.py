"""ContextTracer routes stage records to the per-turn trace_sink (or no-ops)."""
from lore_retrieval.observability import ContextTracer, trace_sink


def test_records_into_the_current_sink():
    tr = ContextTracer()
    sink: list = []
    token = trace_sink.set(sink)
    try:
        tr.record("text_fanout", {"fused": 3})
        tr.record("table_sql", {"calls": 5})
    finally:
        trace_sink.reset(token)
    assert sink == [
        {"stage": "text_fanout", "data": {"fused": 3}},
        {"stage": "table_sql", "data": {"calls": 5}},
    ]


def test_no_sink_is_noop():
    ContextTracer().record("grouping", {"groups": 2})  # must not raise


async def test_pipeline_populates_sink_end_to_end():
    from lore_retrieval.pipeline.factory import build_offline_pipeline
    from lore_retrieval.source import SourceChunk

    chunks = [
        SourceChunk(chunk_id="c1", document_id="d", run_id="d", chunk_type="text", position=1,
                    heading_path=("Root",), vector_text="премия формула", fulltext="премия формула",
                    display_text="премия формула", vector_text_hash="h", fulltext_hash="h"),
    ]
    pipeline = build_offline_pipeline(chunks, tracer=ContextTracer())
    sink: list = []
    token = trace_sink.set(sink)
    try:
        await pipeline.answer("премия формула")
    finally:
        trace_sink.reset(token)
    stages = [e["stage"] for e in sink]
    assert "text_fanout" in stages and "arbitration" in stages
