import asyncio
import os

import pytest


def _dsn() -> str | None:
    host = os.environ.get("TOAST_DB_HOST")
    user = os.environ.get("TOAST_DB_USER")
    password = os.environ.get("TOAST_DB_PASSWORD")
    name = os.environ.get("TOAST_DB_NAME")
    if not all([host, user, password, name]):
        return None
    from config import build_dsn

    port = int(os.environ.get("TOAST_DB_PORT", "5432"))
    return build_dsn("postgresql", user, password, host, port, name)


DSN = _dsn()
pytestmark = pytest.mark.skipif(not DSN, reason="TOAST_DB_* not set")

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
