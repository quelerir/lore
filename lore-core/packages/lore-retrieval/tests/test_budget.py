from lore_retrieval.budget import SqlQueryBudget, sql_query_budget
from lore_retrieval.contracts import SQLStatus, SqlRequest, TableCandidate
from lore_retrieval.pipeline.graph import RetrievalPipeline


def test_budget_grants_up_to_total_then_refuses():
    b = SqlQueryBudget(2)
    assert b.try_consume() is True
    assert b.try_consume() is True
    assert b.try_consume() is False  # spent
    assert b.remaining == 0


def test_zero_budget_grants_nothing():
    b = SqlQueryBudget(0)
    assert b.try_consume() is False


class _BudgetProbeRunner:
    """A SqlRunner that reports the per-turn budget it sees during the fan-out."""

    def __init__(self) -> None:
        self.seen_total = None
        self.seen_remaining = None

    async def run(self, request: SqlRequest):
        b = sql_query_budget.get()
        self.seen_total = None if b is None else b.total
        self.seen_remaining = None if b is None else b.remaining
        return SQLResult_stub(request)


def SQLResult_stub(request):
    from lore_retrieval.contracts import SQLResult

    return SQLResult(payload_id=request.payload_id, chunk_id=request.chunk_id,
                     status=SQLStatus.empty)


async def test_run_table_sql_sets_the_turn_budget_for_the_fanout():
    runner = _BudgetProbeRunner()
    pipe = RetrievalPipeline(
        chunk_search=None, graph_expansion=None, reranker=None, resolver=None,
        table_search=None, sql_runner=runner, chat_model=None, context_loader=None,
        sql_queries_per_turn=7,
    )
    cand = [TableCandidate(chunk_id="c1", payload_id="t1", score=1.0)]
    await pipe.run_table_sql("q", cand)
    assert runner.seen_total == 7  # budget visible to the fan-out
    # and it is torn down after the turn (no leak into the next)
    assert sql_query_budget.get() is None
