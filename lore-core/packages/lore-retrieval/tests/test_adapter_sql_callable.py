from lore_retrieval.adapters.sql_callable import CallableSqlRunner
from lore_retrieval.contracts import SqlRequest, SQLResult, SQLStatus
from lore_retrieval.interfaces import SqlRunner
from lore_retrieval.pipeline.table_lane import run_sql_fanout
from lore_retrieval.contracts import TableCandidate


async def test_callable_runner_delegates_and_satisfies_protocol():
    seen = []

    async def fake_toast(request: SqlRequest) -> SQLResult:
        seen.append(request.payload_id)
        return SQLResult(payload_id=request.payload_id, chunk_id=request.chunk_id,
                         status=SQLStatus.success, answer_summary="ok")

    runner = CallableSqlRunner(fake_toast)
    assert isinstance(runner, SqlRunner)

    out = await run_sql_fanout(
        runner, [TableCandidate(chunk_id="t1", payload_id="p1", score=1.0)], "вопрос"
    )
    assert seen == ["p1"]
    assert out[0].status is SQLStatus.success
