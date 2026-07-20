"""PgBouncer-safe psycopg connection pool for audit reads."""

from __future__ import annotations

from typing import Any

from psycopg_pool import ConnectionPool


class AuditConnectionPool:
    """Wrap a psycopg pool to expose the `.acquire()` shape the readers expect.

    `audit.postgres_connections.acquire_postgres_connection` duck-types on a
    callable `.acquire()` returning a context manager that yields a live
    psycopg connection — which is exactly `ConnectionPool.connection()`.
    """

    def __init__(self, pool: Any) -> None:
        self._pool = pool

    def acquire(self) -> Any:
        return self._pool.connection()

    def close(self) -> None:
        self._pool.close()


def build_audit_pool(dsn: str, *, max_size: int = 8) -> AuditConnectionPool:
    """Build a psycopg pool with prepared statements disabled (PgBouncer txn pooling).

    PgBouncer in transaction-pooling mode cannot support server-side prepared
    statements, so `prepare_threshold=None` is mandatory here.
    """
    pool = ConnectionPool(
        conninfo=dsn,
        min_size=0,  # open connections lazily so startup never blocks on the DB
        max_size=max_size,
        open=True,
        kwargs={"prepare_threshold": None, "autocommit": False},
    )
    return AuditConnectionPool(pool)
