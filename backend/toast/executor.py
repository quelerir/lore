"""Read-only исполнитель одной toast-таблицы: фетч колонок + guarded SELECT."""

import json
from typing import Any, TypedDict

import asyncpg

from toast.sql_guardrails import TOAST_TABLE_RE, qualify_table, validate_select

MAX_ROWS = 200
STATEMENT_TIMEOUT_MS = 5000


class SelectResult(TypedDict):
    """Результат успешного SELECT (строки уже приведены к JSON-совместимым типам)."""

    columns: list[str]
    rows: list[dict[str, Any]]
    row_count: int
    truncated: bool


class PgExecutor:
    """Пул соединений к БД toast-таблиц (asyncpg).

    Юзер БД пишущий, поэтому read-only и statement_timeout навязываем сами —
    ПО-ТРАНЗАКЦИОННО (BEGIN READ ONLY + SET LOCAL), а не через server_settings
    пула: startup-параметры не принимает transaction-pooling пулер (PgBouncer),
    он рвёт коннект с `unsupported startup parameter`. Пул ленивый — создаётся
    при первом обращении.
    """

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
            )
        return self._pool

    async def close(self) -> None:
        if self._pool is not None:
            await self._pool.close()
            self._pool = None

    async def fetch_columns(self, table: str) -> list[str]:
        """Реальные имена колонок таблицы (в порядке ordinal_position).

        Обязательно для генерации SQL: физические имена часто переименованы из
        заголовков и не совпадают с человеческим описанием таблицы.
        """
        if not TOAST_TABLE_RE.match(table):
            raise ValueError(f"bad table id: {table!r}")
        pool = await self._acquire_pool()
        async with pool.acquire() as conn:
            async with conn.transaction(readonly=True):
                await conn.execute(f"SET LOCAL statement_timeout = {STATEMENT_TIMEOUT_MS}")
                rows = await conn.fetch(
                    """SELECT column_name FROM information_schema.columns
                       WHERE table_schema = 'splitter_toast' AND table_name = $1
                       ORDER BY ordinal_position""",
                    table,
                )
        return [r["column_name"] for r in rows]

    async def run_select(self, sql: str, table: str) -> SelectResult | str:
        """Выполнить SELECT к `table` в read-only транзакции.

        Возвращает SelectResult при успехе или строку-отказ (guardrails) /
        текст ошибки БД. Результат усечён до MAX_ROWS (флаг truncated).
        """
        sql = qualify_table(sql, table)
        if refusal := validate_select(sql, table):
            return refusal
        pool = await self._acquire_pool()
        try:
            async with pool.acquire() as conn:
                async with conn.transaction(readonly=True):
                    await conn.execute(f"SET LOCAL statement_timeout = {STATEMENT_TIMEOUT_MS}")
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
        return (
            json.loads(value)
            if isinstance(value, (bytes, bytearray))
            else str(value)
        )
    except Exception:
        return str(value)
