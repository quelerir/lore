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

from lore_retrieval.contracts import SqlRequest, SQLResult


class CallableSqlRunner:
    """Adapts any ``async (SqlRequest) -> SQLResult`` callable to the SqlRunner
    Protocol."""

    def __init__(self, fn: Callable[[SqlRequest], Awaitable[SQLResult]]) -> None:
        self._fn = fn

    async def run(self, request: SqlRequest) -> SQLResult:
        return await self._fn(request)
