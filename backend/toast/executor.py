"""Read-only исполнитель одной toast-таблицы: guarded SELECT с лимитом строк."""

from typing import Any, TypedDict

import asyncpg

from toast.sql_guardrails import qualify_table, validate_select

MAX_ROWS = 200
STATEMENT_TIMEOUT_MS = 5000


class SelectResult(TypedDict):
    """Результат успешного SELECT (строки уже приведены к JSON-совместимым типам)."""

    columns: list[str]
    rows: list[dict[str, Any]]
    row_count: int
    truncated: bool


class PgExecutor:
    """Read-only исполнитель toast-таблиц (asyncpg, соединение на запрос).

    Юзер БД пишущий, поэтому read-only и statement_timeout навязываем сами —
    ПО-ТРАНЗАКЦИОННО (BEGIN READ ONLY + SET LOCAL), а не через server_settings
    соединения: startup-параметры не принимает transaction-pooling пулер
    (PgBouncer), он рвёт коннект с `unsupported startup parameter`.

    Пул не держим: перед БД и так стоит пулер, а на каждый запрос берём
    отдельное соединение — кандидаты раунда исполняются параллельно, а одно
    asyncpg-соединение нельзя делить между конкурентными запросами.
    """

    def __init__(self, dsn: str) -> None:
        self._dsn = dsn

    async def run_select(self, sql: str, table: str) -> SelectResult | str:
        """Выполнить SELECT к `table` в read-only транзакции.

        Возвращает SelectResult при успехе или строку-отказ (guardrails) /
        текст ошибки БД / таймаута. Результат усечён до MAX_ROWS ещё на
        стороне БД (обёртка LIMIT MAX_ROWS+1 — лишние строки в память не
        тянем; наличие (MAX_ROWS+1)-й строки поднимает флаг truncated).
        """
        sql = qualify_table(sql, table)
        if refusal := validate_select(sql, table):
            return refusal
        wrapped = (
            f"SELECT * FROM ({sql.strip().rstrip(';')}) AS _q LIMIT {MAX_ROWS + 1}"
        )
        try:
            conn = await asyncpg.connect(
                self._dsn, command_timeout=STATEMENT_TIMEOUT_MS / 1000
            )
            try:
                async with conn.transaction(readonly=True):
                    await conn.execute(
                        f"SET LOCAL statement_timeout = {STATEMENT_TIMEOUT_MS}"
                    )
                    rows = await conn.fetch(wrapped)
            finally:
                await conn.close()
        except TimeoutError:
            # Клиентский command_timeout asyncpg; серверный statement_timeout
            # приходит как QueryCanceledError (подкласс PostgresError).
            return f"Ошибка SQL: превышен таймаут {STATEMENT_TIMEOUT_MS} мс"
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
    """Приведение значения asyncpg к JSON-совместимому типу.

    json/jsonb asyncpg отдаёт как str; bytes — это bytea, декодируем с
    заменой некорректных байтов. Остальное (Decimal, даты, UUID) — str().
    """
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, (bytes, bytearray, memoryview)):
        return bytes(value).decode("utf-8", "replace")
    return str(value)
