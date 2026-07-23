"""The per-turn SQL budget (shared across the table fan-out) caps how many
GENERATED queries the toast graph runs — the schema sample is never counted."""
from langchain_core.messages import AIMessage

from fakes import ScriptedChatModel
from graph_utils import LEGAL, FakeExecutor, _rows, _run, _sample
from lore_retrieval.budget import SqlQueryBudget, sql_query_budget

_THREE_ROUNDS = [
    AIMessage(content='["SELECT column_1 FROM %s"]' % LEGAL),
    AIMessage(content='["SELECT column_2 FROM %s"]' % LEGAL),
    AIMessage(content='["SELECT column_3 FROM %s"]' % LEGAL),
]


def test_turn_budget_caps_generated_queries():
    # Per-table allowance is 3 rounds, but the per-turn budget allows only ONE
    # generated query — the graph runs one, then the budget is spent and the round
    # cap ends it. Sample is never counted.
    model = ScriptedChatModel(responses=list(_THREE_ROUNDS))
    exe = FakeExecutor(results=[_sample(), _rows(0), _rows(0), _rows(0)])
    token = sql_query_budget.set(SqlQueryBudget(1))
    try:
        out = _run(model, exe, candidates=1, max_queries=3)
    finally:
        sql_query_budget.reset(token)
    assert out["status"] == "no_data"
    assert len(exe.calls) == 2  # sample + ONE generated (turn budget=1)


def test_no_budget_runs_full_per_table_allowance():
    # Baseline: without a turn budget the graph uses its full per-table allowance.
    model = ScriptedChatModel(responses=list(_THREE_ROUNDS))
    exe = FakeExecutor(results=[_sample(), _rows(0), _rows(0), _rows(0)])
    out = _run(model, exe, candidates=1, max_queries=3)
    assert len(exe.calls) == 4  # sample + 3 generated (no turn cap)
