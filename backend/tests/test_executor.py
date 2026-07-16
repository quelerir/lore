import asyncio
import os

import pytest

DSN = os.environ.get("TOAST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not DSN, reason="TOAST_DATABASE_URL not set")

LEGAL = "toast_tbl_ec48a6d52d16ab405f95"


def _run(coro):
    return asyncio.run(coro)


def _exe():
    from toast.executor import PgExecutor

    return PgExecutor(DSN)


def test_fetch_columns_includes_service_and_renamed():
    exe = _exe()

    async def run():
        try:
            return await exe.fetch_columns(LEGAL)
        finally:
            await exe.close()

    cols = _run(run())
    assert "_splitter_source_row" in cols
    assert "senior_legal_manager" in cols  # переименованная колонка из отчёта


def test_run_select_ok_and_mutation_rejected():
    exe = _exe()

    async def run():
        try:
            ok = await exe.run_select(
                f'SELECT column_1 FROM splitter_toast."{LEGAL}"', LEGAL
            )
            bad = await exe.run_select("DROP TABLE splitter_toast.x", LEGAL)
            return ok, bad
        finally:
            await exe.close()

    ok, bad = _run(run())
    assert not isinstance(ok, str) and ok["row_count"] >= 1
    assert isinstance(bad, str) and "Отказ" in bad
