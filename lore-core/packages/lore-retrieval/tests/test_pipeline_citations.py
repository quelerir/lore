"""End-to-end: the pipeline turns model [n] markers into FileViewer citations."""
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


async def test_pipeline_without_markers_has_no_citations():
    result = await _pipeline(lambda _p: "Ответ без ссылок.").answer("премия сотрудника формула")
    assert result.citations == []
