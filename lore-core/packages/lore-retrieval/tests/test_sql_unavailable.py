"""The live pipeline must NEVER silently substitute a fake SQL runner: an
unavailable SQL tool reports an honest 'unsupported' status, not a masking
'not_applicable' that reads like a real per-table verdict."""
from lore_retrieval.adapters.sql_callable import UnavailableSqlRunner
from lore_retrieval.contracts import SQLStatus, SqlRequest
from lore_retrieval.pipeline.factory import build_live_pipeline


async def test_unavailable_runner_reports_unsupported_with_reason():
    runner = UnavailableSqlRunner()
    result = await runner.run(
        SqlRequest(question="q", payload_id="toast_tbl_x", chunk_id="c1")
    )
    assert result.status is SQLStatus.unsupported
    assert result.payload_id == "toast_tbl_x"
    assert result.chunk_id == "c1"
    assert result.error and "недоступ" in result.error.lower()
    # honest emptiness — never a canned answer or rows
    assert result.rows == [] and result.answer_summary is None
    assert runner.seen == ["toast_tbl_x"]  # records what it was asked, like the fake


def test_live_pipeline_defaults_to_unavailable_not_fake_sql_runner():
    # Constructing the live pipeline touches no network (backends are lazy), so we
    # can assert the wiring: with no sql_runner, it must be the honest Unavailable
    # runner, NOT FakeSqlRunner (which would answer not_applicable to everything).
    pipeline = build_live_pipeline(
        driver=object(), database="db", dsn="postgresql://x", embedder=object(),
        chat_model=object(), index_version="v",
    )
    assert type(pipeline._sql_runner).__name__ == "UnavailableSqlRunner"
