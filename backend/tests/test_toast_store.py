import asyncio
import os

import pytest

DSN = os.environ.get("TOAST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not DSN, reason="TOAST_DATABASE_URL not set")


def _store():
    from toast.pg import PgToastStore

    return PgToastStore(DSN)


def test_discover_finds_grades_file():
    store = _store()

    async def run():
        try:
            return await store.discover("контекстной рекламы")
        finally:
            await store.close()

    tables = asyncio.run(run())
    ids = {t["table_id"] for t in tables}
    assert "toast_tbl_a1b2c3d4e5f6a7b8c9d0" in ids
    assert len(tables) == 3  # база + middle + group head


def test_discover_handles_russian_inflection():
    # «юристов» (вопрос) vs «юристы» (display_text) — ловится стем-волной
    store = _store()

    async def run():
        try:
            return await store.discover("Какие ФИО у юристов агентства?")
        finally:
            await store.close()

    tables = asyncio.run(run())
    assert any(t["table_id"] == "toast_tbl_d1b2c3d4e5f6a7b8c9d0" for t in tables)


def test_discover_empty_for_unknown():
    store = _store()

    async def run():
        try:
            return await store.discover("клубы по интересам")
        finally:
            await store.close()

    assert asyncio.run(run()) == []


def test_inspect_returns_columns_and_header_hint():
    store = _store()

    async def run():
        try:
            return await store.inspect("toast_tbl_d1b2c3d4e5f6a7b8c9d0")
        finally:
            await store.close()

    info = asyncio.run(run())
    assert "column_1" in info["columns"]
    assert info["row_count"] == 1
    assert info["header_hint"] and "Columns:" in info["header_hint"]


def test_run_select_ok_and_guarded():
    store = _store()

    async def run():
        try:
            ok = await store.run_select(
                "SELECT column_1 FROM splitter_toast.toast_tbl_d1b2c3d4e5f6a7b8c9d0"
            )
            bad = await store.run_select("DROP TABLE lore_core.payloads")
            pii = await store.run_select(
                "SELECT vacation_start FROM splitter_toast.toast_tbl_e1b2c3d4e5f6a7b8c9d0"
            )
            return ok, bad, pii
        finally:
            await store.close()

    ok, bad, pii = asyncio.run(run())
    assert isinstance(ok, dict) and ok["row_count"] == 1
    assert isinstance(bad, str) and "Отказ" in bad
    assert isinstance(pii, str) and "policy" in pii
