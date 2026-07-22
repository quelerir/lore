from lore_retrieval.pipeline.factory import build_offline_pipeline
from lore_retrieval.source import SourceChunk


def txt(cid, ordinal, path, text):
    return SourceChunk(
        chunk_id=cid, document_id="d1", run_id="d1", chunk_type="text", position=ordinal,
        heading_path=tuple(path), vector_text=text, fulltext=text, display_text=text,
        vector_text_hash="h", fulltext_hash="h",
    )


CORPUS = [
    txt("c1", 1, ("Root", "Премия"), "премия сотрудника формула"),
    txt("c2", 2, ("Root", "Премия"), "формула премии оклад"),
]


async def test_factory_builds_working_pipeline_with_citations():
    pipe = build_offline_pipeline(
        CORPUS, chat_responder=lambda _p: "ответ [1]", file_keys={"d1": "doc.pdf"}
    )
    result = await pipe.answer("премия сотрудника формула")
    assert result.decision.answer == "ответ [1]"
    assert result.citations
    assert result.citations[0].logical_file_key == "doc.pdf"


async def test_factory_default_responder_falls_back_to_grounded_sources():
    pipe = build_offline_pipeline(CORPUS)
    result = await pipe.answer("премия")
    assert result.decision.answer == "ОТВЕТ"   # default responder emits no [n] markers
    # No markers but grounding existed -> deterministic top-N fallback (marker=None).
    assert result.citations
    assert all(c.marker is None for c in result.citations)
