"""End-to-end: the pipeline turns model [n] markers into FileViewer citations."""
from lore_retrieval.contracts import SQLResult, SQLStatus
from lore_retrieval.fakes import (
    FakeChatModel,
    FakeReranker,
    FakeSqlRunner,
    InMemoryChunkContextLoader,
    InMemoryChunkSearchBackend,
    InMemoryEvidenceResolver,
    InMemoryGraphExpansion,
)
from lore_retrieval.pipeline.graph import RetrievalPipeline
from lore_retrieval.projection_model import build_structural_projection
from lore_retrieval.source import SourceChunk


class FakeFileKeyResolver:
    def __init__(self, mapping):
        self._m = mapping

    async def resolve(self, run_ids):
        return {r: self._m[r] for r in run_ids if r in self._m}


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


def _pipeline(responder):
    projection = build_structural_projection(CORPUS)
    backend = InMemoryChunkSearchBackend(CORPUS)
    return RetrievalPipeline(
        chunk_search=backend,
        graph_expansion=InMemoryGraphExpansion(projection),
        reranker=FakeReranker(),
        resolver=InMemoryEvidenceResolver(CORPUS),
        table_search=backend,
        sql_runner=FakeSqlRunner({}),
        chat_model=FakeChatModel(responder),
        context_loader=InMemoryChunkContextLoader(CORPUS),
        file_key_resolver=FakeFileKeyResolver({"d1": "doc.pdf"}),
    )


async def test_pipeline_emits_citations_from_markers():
    result = await _pipeline(lambda _p: "Премия по формуле [1].").answer("премия сотрудника формула")
    assert result.citations, "expected at least one citation"
    c = result.citations[0]
    assert c.chunk_id in {"c1", "c2"}
    assert c.logical_file_key == "doc.pdf"
    assert c.deep_link.startswith("/files?file=doc.pdf&run=d1&chunk=")
    assert c.preview_text  # non-empty preview


async def test_pipeline_without_markers_falls_back_to_grounded_sources():
    result = await _pipeline(lambda _p: "Ответ без ссылок.").answer("премия сотрудника формула")
    # No markers but grounding existed -> deterministic top-N fallback (marker=None).
    assert result.citations
    assert all(c.marker is None for c in result.citations)


def tbl(cid, ordinal, path, text, payload_id):
    return SourceChunk(
        chunk_id=cid, document_id="d1", run_id="d1", chunk_type="table_payload",
        position=ordinal, heading_path=tuple(path), vector_text=text, fulltext=text,
        display_text=text, payload_refs=[{"payload_id": payload_id}],
        vector_text_hash="h", fulltext_hash="h",
    )


# Table-only corpus: the text lane finds nothing (table chunks are excluded), so
# the SQL success is marker [1].
TABLE_CORPUS = [tbl("t1", 1, ("Root", "Оклады"), "оклад сотрудник таблица", "p1")]


def _table_pipeline(responder, outcomes):
    projection = build_structural_projection(TABLE_CORPUS)
    backend = InMemoryChunkSearchBackend(TABLE_CORPUS)
    return RetrievalPipeline(
        chunk_search=backend,
        graph_expansion=InMemoryGraphExpansion(projection),
        reranker=FakeReranker(),
        resolver=InMemoryEvidenceResolver(TABLE_CORPUS),
        table_search=backend,
        sql_runner=FakeSqlRunner(outcomes),
        chat_model=FakeChatModel(responder),
        context_loader=InMemoryChunkContextLoader(TABLE_CORPUS),
        file_key_resolver=FakeFileKeyResolver({"d1": "grades.xlsx"}),
    )


async def test_answer_emits_table_citation_when_sql_grounds():
    ok = SQLResult(payload_id="p1", chunk_id="t1", status=SQLStatus.success,
                   answer_summary="Итог: 42")
    result = await _table_pipeline(
        lambda _p: "Ответ по таблице [1].", {"p1": ok}
    ).answer("оклад сотрудник")
    table_cites = [c for c in result.citations if c.kind == "table"]
    assert table_cites, result.citations
    cit = table_cites[0]
    assert cit.deep_link.endswith("&tab=payloads")
    assert cit.run_id == "d1"                       # provenance from the loaded anchor row
    assert cit.logical_file_key == "grades.xlsx"
    assert cit.preview_text == "Итог: 42"
    assert cit.marker == 1
