"""SqlRunner seam.

``lore-retrieval`` must not import the ``lore-chat/toast`` SQL module (that would
invert the package→service dependency direction). Instead the integration layer
in ``lore-chat`` binds toast behind this callable seam and injects it.

The binding the integration layer must provide, per SqlRequest:
  - resolve ``payload_id`` -> physical table + logical/physical column schema via
    the TRUSTED registry (never from Neo4j text or the LLM);
  - call the toast SQL graph (``run_sql_tool``) with question/chunk_id/table/desc;
  - map its typed result -> ``SQLResult`` (status -> ``SQLStatus``, answer ->
    ``answer_summary``, rows -> ``rows``).
"""
from collections.abc import Awaitable, Callable

from lore_retrieval.contracts import SqlRequest, SQLResult, SQLStatus


class CallableSqlRunner:
    """Adapts any ``async (SqlRequest) -> SQLResult`` callable to the SqlRunner
    Protocol."""

    def __init__(self, fn: Callable[[SqlRequest], Awaitable[SQLResult]]) -> None:
        self._fn = fn

    async def run(self, request: SqlRequest) -> SQLResult:
        return await self._fn(request)


class UnavailableSqlRunner:
    """Honest stand-in when the live TOAST SQL tool could not be wired. Returns an
    explicit ``unsupported`` status with a reason — NEVER a masking
    ``not_applicable`` (that reads like a real per-table verdict and misleads both
    users and coders into thinking the tables were checked). Used by the LIVE
    factory instead of a silent fake, so an SQL outage is visible, not disguised."""

    def __init__(self) -> None:
        self.seen: list[str] = []

    async def run(self, request: SqlRequest) -> SQLResult:
        self.seen.append(request.payload_id)
        return SQLResult(
            payload_id=request.payload_id,
            chunk_id=request.chunk_id,
            status=SQLStatus.unsupported,
            error="SQL-инструмент недоступен (живой TOAST не подключён)",
        )
