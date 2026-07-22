"""Grounded graph: neo4j_retrieve → toast_sql → summarize, on a fake pipeline."""
import asyncio
from types import SimpleNamespace

from langchain_core.messages import AIMessage, HumanMessage

from agents.grounded import build_grounded_agent


def _tc():
    return SimpleNamespace(payload_id="p", chunk_id="c", score=0.5)


def _sqlres():
    return SimpleNamespace(
        payload_id="p", chunk_id="c", status="success",
        rows=[{"a": 1}], answer_summary="ok", error=None,
    )


class _FakePipe:
    def __init__(self):
        self.calls = []

    async def retrieve(self, q):
        self.calls.append(("retrieve", q))
        resolution = SimpleNamespace(resolved=[], rejected=[])
        return ([], resolution, [_tc()], ["degr1"])

    async def run_table_sql(self, q, table_candidates):
        self.calls.append(("run_table_sql", table_candidates))
        return ([_sqlres()], ["degr2"])

    async def summarize(self, q, groups, resolution, sql_results, table_candidates):
        self.calls.append(("summarize", q, sql_results))
        decision = SimpleNamespace(
            answer="Каневский — Помощник Юриста", note="", used_sql_payload_ids=[]
        )
        return (decision, ["CIT"])


def test_runs_three_stages_in_order_and_answers_with_citations():
    pipe = _FakePipe()
    agent = build_grounded_agent(pipe)
    state = asyncio.run(agent.ainvoke({"messages": [HumanMessage(content="ФИО юристов?")]}))

    # stages executed in sequence, sql receiving retrieve's candidates
    assert [c[0] for c in pipe.calls] == ["retrieve", "run_table_sql", "summarize"]
    assert pipe.calls[1][1][0].payload_id == "p"  # run_table_sql got retrieve's candidates
    assert pipe.calls[2][2][0].payload_id == "p"  # summarize got the sql results

    msgs = state["messages"]
    assert isinstance(msgs[-1], AIMessage)
    assert msgs[-1].content == "Каневский — Помощник Юриста"
    assert state["citations"] == ["CIT"]
    # compact per-node detail surfaced for the Studio inspector
    assert state["neo4j_detail"]["table_candidates"][0]["table"] == "p"
    assert state["sql_detail"][0]["status"] == "success"
    assert state["sql_detail"][0]["rows"] == 1


def test_summarize_joins_once_after_both_branches():
    """Diamond: summarize is a join — it runs exactly once, after toast_sql, so it
    sees the SQL results (a naive short edge would fire it early/twice)."""
    pipe = _FakePipe()
    agent = build_grounded_agent(pipe)
    asyncio.run(agent.ainvoke({"messages": [HumanMessage(content="q")]}))
    assert [c[0] for c in pipe.calls].count("summarize") == 1
    assert pipe.calls[-1][0] == "summarize"  # ran last, after run_table_sql


def test_no_table_candidate_marks_sql_branch_explicitly():
    """When retrieve finds no table candidate, the SQL branch is honest: it records
    a 'no_candidate' outcome and never calls run_table_sql."""
    pipe = _FakePipe()

    async def _retrieve(q):
        pipe.calls.append(("retrieve", q))
        return ([], SimpleNamespace(resolved=[], rejected=[]), [], [])

    pipe.retrieve = _retrieve
    agent = build_grounded_agent(pipe)
    state = asyncio.run(agent.ainvoke({"messages": [HumanMessage(content="q")]}))
    assert "run_table_sql" not in [c[0] for c in pipe.calls]
    assert state["sql_detail"][0]["status"] == "no_candidate"


def test_empty_answer_falls_back_to_message():
    pipe = _FakePipe()

    async def _summarize(q, g, r, s, tc):
        return (SimpleNamespace(answer="", note="", used_sql_payload_ids=[]), [])

    pipe.summarize = _summarize
    agent = build_grounded_agent(pipe)
    state = asyncio.run(agent.ainvoke({"messages": [HumanMessage(content="x")]}))
    assert "нет ответа" in state["messages"][-1].content
