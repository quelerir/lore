"""Per-turn SQL query budget, shared across the parallel table fan-out.

The table lane runs SQL for several candidate tables in parallel, each via the
toast graph with its own per-table attempt budget. On a query the text lane can
answer, that fans out into many futile DB round-trips. This is a single per-turn
allowance of *generated* SQL executions (never schema samples): the pipeline sets
it before the fan-out, and every toast execute-node draws from the SAME counter,
so the total DB queries per turn stay bounded.

Same mechanism as ``trace_sink``: a ContextVar holding one mutable object; child
tasks (the fan-out) inherit the reference and mutate it. asyncio is single
threaded, so ``try_consume`` needs no lock (no await between check and decrement).
"""
import contextvars


class SqlQueryBudget:
    def __init__(self, total: int) -> None:
        self.total = total
        self.remaining = total

    def try_consume(self) -> bool:
        """Claim one query slot. True if granted; False once the budget is spent."""
        if self.remaining <= 0:
            return False
        self.remaining -= 1
        return True


sql_query_budget: contextvars.ContextVar[SqlQueryBudget | None] = contextvars.ContextVar(
    "sql_query_budget", default=None
)
