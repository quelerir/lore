import pytest

from lore_retrieval.contracts import Route
from lore_retrieval.fakes import InMemoryChunkSearchBackend
from lore_retrieval.pipeline.fanout import fan_out_and_fuse
from lore_retrieval.source import SourceChunk


def mk(cid, text, vtext=None, ctype="text"):
    return SourceChunk(
        chunk_id=cid, document_id="d", run_id="d", chunk_type=ctype, position=0,
        heading_path=(), vector_text=vtext or text, fulltext=text,
        vector_text_hash="h", fulltext_hash="h",
    )


@pytest.fixture
def backend():
    return InMemoryChunkSearchBackend([
        mk("a", "премия сотрудника расчёт"),
        mk("b", "премия годовая бонус"),
        mk("c", "отпуск и отпускные выплаты"),
        mk("t", "таблица окладов", ctype="table_payload"),
    ])


async def test_fulltext_ranks_lexical_overlap(backend):
    ids = [cid for cid, _ in await backend.fulltext_search("премия", 10)]
    assert "a" in ids and "b" in ids and "c" not in ids


async def test_table_chunks_excluded_from_text_lane(backend):
    assert await backend.fulltext_search("таблица", 10) == []
    assert await backend.vector_search("таблица окладов", 10) == []


async def test_fanout_fuses_dedups_and_labels_routes(backend):
    res, degraded, failures = await fan_out_and_fuse(backend, "премия сотрудника")
    assert degraded == []
    assert failures == []
    routes = {c.route for c in res.per_route}
    assert Route.vector in routes and Route.fulltext in routes

    fused_ids = [cid for cid, _ in res.fused]
    assert len(fused_ids) == len(set(fused_ids))       # deduped by chunk_id
    assert fused_ids[0] == "a"                          # agreed across both lanes -> first
    assert "t" not in fused_ids                         # table chunk never in text lane


async def test_fanout_surfaces_failed_route_detail():
    """A failed route degrades AND surfaces its exception detail — parity with
    table_sql / structural_expansion, so a logic bug isn't silent behind the code."""

    class BoomVector(InMemoryChunkSearchBackend):
        async def vector_search(self, query, top_k):
            raise RuntimeError("vector index down")

    res, degraded, failures = await fan_out_and_fuse(BoomVector([mk("a", "премия")]), "премия")
    assert degraded == ["vector_search_failed"]        # frontend-facing code, unchanged
    assert len(failures) == 1
    fail = failures[0]
    assert fail["lane"] == "vector_search_failed"
    assert fail["error"] == "RuntimeError"
    assert "vector index down" in fail["detail"]
    assert [cid for cid, _ in res.fused]               # fulltext still produced candidates
