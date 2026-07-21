"""End-to-end: the full pipeline on a fake corpus, all backends stubbed."""

from lore_retrieval.contracts import SQLResult, SQLStatus
from lore_retrieval.fakes import (
    FakeChatModel,
    FakeReranker,
    FakeSqlRunner,
    InMemoryChunkSearchBackend,
    InMemoryEvidenceResolver,
    InMemoryGraphExpansion,
)
from lore_retrieval.pipeline.graph import RetrievalPipeline
from lore_retrieval.projection_model import build_structural_projection
from lore_retrieval.source import SourceChunk


def txt(cid, ordinal, path, text):
    return SourceChunk(
        chunk_id=cid, document_id="d1", run_id="d1", chunk_type="text", position=ordinal,
        heading_path=tuple(path), vector_text=text, fulltext=text,
        vector_text_hash="h", fulltext_hash="h",
    )


def tbl(cid, ordinal, path, text, payload_id):
    return SourceChunk(
        chunk_id=cid, document_id="d1", run_id="d1", chunk_type="table_payload", position=ordinal,
        heading_path=tuple(path), vector_text=text, fulltext=text,
        payload_refs=[{"payload_id": payload_id}], vector_text_hash="h", fulltext_hash="h",
    )


CORPUS = [
    txt("c0", 0, ("Root",), "введение о премиях"),
    txt("c1", 1, ("Root", "Премия"), "премия сотрудника рассчитывается по формуле"),
    txt("c2", 2, ("Root", "Премия"), "формула премии учитывает оклад сотрудника"),
    txt("c3", 3, ("Root", "Отпуск"), "отпускные выплаты и график"),
    tbl("t1", 4, ("Root", "Таблицы"), "таблица оклад сотрудника", "pay_sal"),
    tbl("t2", 5, ("Root", "Таблицы"), "таблица оклад копия", "pay_sal"),
]


def _pipeline(*, table_search=None, sql_runner=None, chat_model=None):
    projection = build_structural_projection(CORPUS)
    positions = {c.chunk_id: c.position for c in CORPUS}
    text_by_id = {c.chunk_id: c.fulltext for c in CORPUS}
    payload_by_chunk = {"t1": "pay_sal", "t2": "pay_sal"}
    backend = InMemoryChunkSearchBackend(CORPUS)
    return RetrievalPipeline(
        chunk_search=backend,
        graph_expansion=InMemoryGraphExpansion(projection),
        reranker=FakeReranker(),
        resolver=InMemoryEvidenceResolver(CORPUS),
        table_search=table_search or backend,
        sql_runner=sql_runner
        or FakeSqlRunner({
            "pay_sal": SQLResult(payload_id="pay_sal", chunk_id="t1",
                                 status=SQLStatus.success, answer_summary="средний оклад 100000"),
        }),
        chat_model=chat_model or FakeChatModel(lambda _p: "ГОТОВЫЙ ОТВЕТ"),
        projection=projection,
        positions=positions,
        text_by_id=text_by_id,
        payload_by_chunk=payload_by_chunk,
    )


async def test_full_pipeline_grounds_text_and_sql():
    result = await _pipeline().answer("оклад премия сотрудника")

    assert result.decision.answer == "ГОТОВЫЙ ОТВЕТ"
    assert result.decision.used_sql_payload_ids == ["pay_sal"]
    assert set(result.decision.used_evidence_chunk_ids) & {"c1", "c2"}
    assert any(g.section_path == ("Root", "Премия") for g in result.groups)
    assert [c.payload_id for c in result.table_candidates] == ["pay_sal"]   # deduped to one slot
    assert [r.status for r in result.sql_results] == [SQLStatus.success]
    assert result.decision.note is None
    assert result.degradations == []


async def test_table_lane_failure_still_answers_from_text():
    class FailingTableSearch:
        async def table_vector_search(self, query, top_k):
            raise RuntimeError("neo4j down")

        async def table_fulltext_search(self, query, top_k):
            raise RuntimeError("neo4j down")

    result = await _pipeline(table_search=FailingTableSearch()).answer("премия сотрудника")
    assert "table_lane_unavailable" in result.degradations
    assert result.sql_results == []
    assert result.groups                      # text evidence still produced
    assert result.decision.answer == "ГОТОВЫЙ ОТВЕТ"


async def test_no_matching_evidence_returns_limitation():
    model = FakeChatModel()
    result = await _pipeline(
        chat_model=model,
        sql_runner=FakeSqlRunner({}),   # every payload -> not_applicable
    ).answer("совершенно посторонний вопрос про космос")
    assert result.groups == []
    assert result.decision.note == "no_grounded_evidence"
    assert model.calls == []             # no invented facts
