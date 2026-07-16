"""Прототипный адаптер «специального интерфейса»: read-only asyncpg к lore_data.

Воспроизводит рекомендуемый discovery-запрос отчёта (registry не
самодостаточен: table id живёт в payload_id) и header-hint из chunks.
"""

import json
from typing import Any

import asyncpg

from toast.guardrails import TOAST_TABLE_RE, qualify_toast_tables, validate_select
from toast.policy import check_policy
from toast.port import DiscoveredTable, SelectResult, TableInfo

MAX_ROWS = 200
STATEMENT_TIMEOUT_MS = 5000

_DISCOVERY_SQL = """
SELECT pf.source_path,
       p.payload_id AS table_id,
       p.coordinates,
       left(c.display_text, 500) AS summary
FROM lore_core.payloads p
JOIN lore_core.processed_files pf USING (logical_file_key)
LEFT JOIN lore_core.chunks c ON c.payload_refs::text ILIKE '%' || p.payload_id || '%'
WHERE p.kind = 'table'
  AND (pf.source_path ILIKE '%' || $1 || '%'
       OR c.display_text ILIKE '%' || $1 || '%')
ORDER BY pf.source_path, p.coordinates::text
"""


class PgToastStore:
    def __init__(self, dsn: str) -> None:
        self._dsn = dsn
        self._pool: asyncpg.Pool | None = None

    async def _acquire_pool(self) -> asyncpg.Pool:
        if self._pool is None:
            self._pool = await asyncpg.create_pool(
                self._dsn,
                min_size=0,
                max_size=3,
                command_timeout=STATEMENT_TIMEOUT_MS / 1000,
                server_settings={
                    # Юзер БД пишущий — read-only и таймаут навязываем сами.
                    "default_transaction_read_only": "on",
                    "statement_timeout": str(STATEMENT_TIMEOUT_MS),
                },
            )
        return self._pool

    async def close(self) -> None:
        if self._pool is not None:
            await self._pool.close()
            self._pool = None

    async def discover(self, document_hint: str) -> list[DiscoveredTable]:
        pool = await self._acquire_pool()
        # Три волны поиска: фраза целиком → слова → стемы (первые 5 символов,
        # грубая защита от русских окончаний: «юристов» должно находить
        # «юристы»). Останавливаемся на первой волне с результатами.
        words = [w.strip(".,?!;:()«»\"'") for w in document_hint.split()]
        words = [w for w in words if len(w) >= 4]
        stems = sorted({w[:5] for w in words if len(w) > 5})
        waves = [[document_hint], words, stems]
        seen: dict[str, DiscoveredTable] = {}
        async with pool.acquire() as conn:
            for wave in waves:
                for hint in wave:
                    rows = await conn.fetch(_DISCOVERY_SQL, hint)
                    for r in rows:
                        seen.setdefault(
                            r["table_id"],
                            DiscoveredTable(
                                source_path=r["source_path"],
                                table_id=r["table_id"],
                                coordinates=r["coordinates"],
                                summary=r["summary"],
                            ),
                        )
                if seen:
                    break
        return list(seen.values())

    async def inspect(self, table_id: str) -> TableInfo:
        if not TOAST_TABLE_RE.match(table_id):
            raise ValueError(f"bad table id: {table_id!r}")
        pool = await self._acquire_pool()
        async with pool.acquire() as conn:
            cols = await conn.fetch(
                """SELECT column_name FROM information_schema.columns
                   WHERE table_schema = 'splitter_toast' AND table_name = $1
                   ORDER BY ordinal_position""",
                table_id,
            )
            count = await conn.fetchval(
                f'SELECT count(*) FROM splitter_toast."{table_id}"'
            )
            hint = await conn.fetchval(
                """SELECT display_text FROM lore_core.chunks
                   WHERE payload_refs::text ILIKE '%' || $1 || '%'
                   LIMIT 1""",
                table_id,
            )
        return TableInfo(
            table_id=table_id,
            columns=[r["column_name"] for r in cols],
            row_count=count or 0,
            header_hint=hint,
        )

    async def run_select(self, sql: str) -> SelectResult | str:
        sql = qualify_toast_tables(sql)
        if refusal := validate_select(sql):
            return refusal
        if refusal := check_policy(sql):
            return refusal
        pool = await self._acquire_pool()
        try:
            async with pool.acquire() as conn:
                async with conn.transaction(readonly=True):
                    rows = await conn.fetch(sql.strip().rstrip(";"))
        except asyncpg.PostgresError as e:
            return f"Ошибка SQL: {e}"
        truncated = len(rows) > MAX_ROWS
        rows = rows[:MAX_ROWS]
        columns = list(rows[0].keys()) if rows else []
        return SelectResult(
            columns=columns,
            rows=[{k: _plain(v) for k, v in dict(r).items()} for r in rows],
            row_count=len(rows),
            truncated=truncated,
        )


def _plain(value: Any) -> Any:
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    try:
        return json.loads(value) if isinstance(value, (bytes, bytearray)) else str(value)
    except Exception:
        return str(value)
