"""Opt-in integration check against a real lore_core database.

Validates the one integration concern the unit tests cannot: a psycopg
REPEATABLE READ READ ONLY transaction against the real schema survives the
PgBouncer transaction pooler (prepared statements disabled). Set AUDIT_TEST_DSN
to run; skipped otherwise.
"""

from __future__ import annotations

import os

import pytest

from lore_audit_api.pool import build_audit_pool

DSN = os.environ.get("AUDIT_TEST_DSN")


@pytest.mark.skipif(not DSN, reason="set AUDIT_TEST_DSN to run against real lore_core")
def test_repeatable_read_txn_survives_pgbouncer():
    pool = build_audit_pool(DSN)
    try:
        with pool.acquire() as conn:
            with conn.cursor() as cur:
                cur.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
                cur.execute("SELECT count(*) FROM lore_core.processed_files")
                assert cur.fetchone()[0] >= 0
    finally:
        pool.close()
