"""Интеграционные тесты PgToastStore против живой loreagent_test.

Диагностика: без TOAST_DATABASE_URL пропускаются. Ожидания — реальные
таблицы из problem-questions-report.html.
"""

import asyncio
import os

import pytest

DSN = os.environ.get("TOAST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not DSN, reason="TOAST_DATABASE_URL not set")

# Реальные таблицы кейса «грейды контекстной рекламы» из отчёта
GRADE_BASE = "toast_tbl_17a7241d0a976f287103"
GRADE_MIDDLE = "toast_tbl_e765505051472ed91b81"
GRADE_HEAD = "toast_tbl_e04534bd1cd4501a7e85"


def _run(coro):
    return asyncio.run(coro)


def _store():
    from toast.pg import PgToastStore

    return PgToastStore(DSN)


def test_discover_finds_grade_tables():
    store = _store()

    async def run():
        try:
            return await store.discover("отдел контекстной рекламы")
        finally:
            await store.close()

    ids = {t["table_id"] for t in _run(run())}
    assert {GRADE_BASE, GRADE_MIDDLE, GRADE_HEAD} <= ids


def test_discover_empty_for_unknown_topic():
    # Negative control отчёта: таблиц про «следы»/толстовки нет
    store = _store()

    async def run():
        try:
            return await store.discover("фирменная толстовка следы начисление")
        finally:
            await store.close()

    assert _run(run()) == []


def test_inspect_returns_columns_and_rows():
    store = _store()

    async def run():
        try:
            return await store.inspect(GRADE_BASE)
        finally:
            await store.close()

    info = _run(run())
    assert "column_1" in info["columns"]
    assert info["row_count"] > 0


def test_run_select_rejects_mutation_and_allows_select():
    store = _store()

    async def run():
        try:
            bad = await store.run_select("DROP TABLE lore_core.payloads")
            ok = await store.run_select(
                f'SELECT count(*) AS n FROM splitter_toast."{GRADE_BASE}"'
            )
            return bad, ok
        finally:
            await store.close()

    bad, ok = _run(run())
    assert isinstance(bad, str) and "Отказ" in bad
    assert not isinstance(ok, str) and ok["row_count"] == 1
