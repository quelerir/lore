"""run_id -> logical_file_key resolution.

The FileViewer deep-link needs ``logical_file_key`` (the ``file`` param), but
``lore_core.chunks`` only carries ``run_id`` — the file key lives on
``lore_core.processing_runs``. Pure ``rows_to_file_keys`` (unit-tested) + a thin
asyncpg wrapper (live-verified with a DSN).
"""


def rows_to_file_keys(rows: list[dict]) -> dict[str, str]:
    return {r["run_id"]: r["logical_file_key"] for r in rows}


class PostgresFileKeyResolver:
    def __init__(self, dsn: str) -> None:
        self._dsn = dsn

    async def resolve(self, run_ids: list[str]) -> dict[str, str]:
        if not run_ids:
            return {}
        import asyncpg

        conn = await asyncpg.connect(self._dsn, statement_cache_size=0)  # pgbouncer-safe
        try:
            async with conn.transaction(readonly=True):
                rows = await conn.fetch(
                    """
                    SELECT run_id::text AS run_id, logical_file_key
                    FROM lore_core.processing_runs
                    WHERE run_id::text = ANY($1::text[])
                    """,
                    run_ids,
                )
        finally:
            await conn.close()
        return rows_to_file_keys([dict(r) for r in rows])
