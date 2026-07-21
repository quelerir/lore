import pytest

from lore_retrieval.contracts import SQLResult, SQLStatus
from lore_retrieval.fakes import FakeSqlRunner, InMemoryChunkSearchBackend
from lore_retrieval.pipeline.table_lane import (
    discover_table_candidates,
    run_sql_fanout,
    select_table_candidates,
)
from lore_retrieval.source import SourceChunk


def tbl(cid, text, payload_id):
    return SourceChunk(
        chunk_id=cid, document_id="d", run_id="d", chunk_type="table_payload", position=0,
        heading_path=(), vector_text=text, fulltext=text,
        payload_refs=[{"payload_id": payload_id}], vector_text_hash="h", fulltext_hash="h",
    )


def txt(cid, text):
    return SourceChunk(
        chunk_id=cid, document_id="d", run_id="d", chunk_type="text", position=0,
        heading_path=(), vector_text=text, fulltext=text, vector_text_hash="h", fulltext_hash="h",
    )


@pytest.fixture
def corpus():
    return [
        tbl("t1", "оклады таблица", "pay1"),
        tbl("t2", "оклады таблица копия", "pay1"),   # same physical payload as t1
        tbl("t3", "премии таблица", "pay2"),
        txt("x", "оклады прозой"),                   # text chunk: never in table lane
    ]


PAYLOAD_BY_CHUNK = {"t1": "pay1", "t2": "pay1", "t3": "pay2"}


async def test_table_lane_searches_table_chunks_only(corpus):
    backend = InMemoryChunkSearchBackend(corpus)
    fused = await discover_table_candidates(backend, "оклады")
    ids = {cid for cid, _ in fused}
    assert "t1" in ids and "t2" in ids
    assert "x" not in ids                            # text chunk excluded from table lane


def test_select_dedups_physical_payload_to_one_slot():
    reranked = [("t1", 2.0), ("t2", 1.5), ("t3", 0.5)]
    picked = select_table_candidates(reranked, PAYLOAD_BY_CHUNK)
    assert [c.payload_id for c in picked] == ["pay1", "pay2"]   # t2 (dup of pay1) drops
    assert picked[0].chunk_id == "t1"


def test_select_respects_floor_feasibility_and_cap():
    reranked = [("t1", 2.0), ("t3", 0.5)]
    assert [c.payload_id for c in select_table_candidates(reranked, PAYLOAD_BY_CHUNK, floor=1.0)] == ["pay1"]
    # feasibility can drop a whole payload
    only_p2 = select_table_candidates(reranked, PAYLOAD_BY_CHUNK, feasible=lambda cid: cid != "t1")
    assert [c.payload_id for c in only_p2] == ["pay2"]
    # cap never exceeded, never padded
    assert len(select_table_candidates(reranked, PAYLOAD_BY_CHUNK, max_k=1)) == 1


async def test_sql_fanout_runs_selected_payloads_in_parallel():
    picked = select_table_candidates([("t1", 2.0), ("t3", 0.5)], PAYLOAD_BY_CHUNK)
    runner = FakeSqlRunner({
        "pay1": SQLResult(payload_id="pay1", chunk_id="t1", status=SQLStatus.success,
                          rows=[{"n": 42}], answer_summary="42"),
        "pay2": SQLResult(payload_id="pay2", chunk_id="t3", status=SQLStatus.empty),
    })
    results = await run_sql_fanout(runner, picked, "сколько окладов")
    by_payload = {r.payload_id: r.status for r in results}
    assert by_payload == {"pay1": SQLStatus.success, "pay2": SQLStatus.empty}
    assert set(runner.seen) == {"pay1", "pay2"}      # one slot per physical payload
