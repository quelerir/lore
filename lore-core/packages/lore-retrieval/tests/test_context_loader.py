"""Per-query context loader: in-memory fake + pipeline degradation on failure."""
from lore_retrieval.fakes import InMemoryChunkContextLoader
from lore_retrieval.pipeline.factory import build_offline_pipeline
from lore_retrieval.source import SourceChunk


def _txt(cid, ordinal, text):
    return SourceChunk(
        chunk_id=cid, document_id="d", run_id="d", chunk_type="text", position=ordinal,
        heading_path=("Root", "Премия"), vector_text=text, fulltext=text, display_text=text,
        vector_text_hash="h", fulltext_hash="h",
    )


CORPUS = [_txt("c1", 1, "премия формула"), _txt("c2", 2, "формула оклад")]


async def test_loader_returns_requested_rows_in_order_and_drops_unknown():
    loader = InMemoryChunkContextLoader(CORPUS)
    rows = await loader.load(["c2", "nope", "c1"])
    assert [r.chunk_id for r in rows] == ["c2", "c1"]


async def test_loader_empty_ids_returns_empty():
    assert await InMemoryChunkContextLoader(CORPUS).load([]) == []


class _BoomLoader:
    async def load(self, chunk_ids):
        raise RuntimeError("lore_core down")


async def test_context_load_failure_degrades_not_sinks():
    # A failing loader must not crash the turn: the pipeline records the
    # degradation and returns a PipelineResult. With no groups it answers
    # ungrounded (note=no_grounded_evidence) rather than inventing facts.
    pipeline = build_offline_pipeline(CORPUS, context_loader=_BoomLoader())
    result = await pipeline.answer("премия формула")
    assert "context_load_failed" in result.degradations
    assert result.decision.note == "no_grounded_evidence"  # survived, ungrounded
