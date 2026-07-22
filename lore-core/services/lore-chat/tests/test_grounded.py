"""Grounded graph: retrieve → sql → summarize, on a fake pipeline."""
import asyncio
from types import SimpleNamespace

from langchain_core.messages import AIMessage, HumanMessage

from agents.grounded import build_grounded_agent


class _FakePipe:
    def __init__(self):
        self.calls = []

    async def retrieve(self, q):
        self.calls.append(("retrieve", q))
        return ([], object(), ["tc"], ["degr1"])

    async def run_table_sql(self, q, table_candidates):
        self.calls.append(("run_table_sql", table_candidates))
        return (["sqlres"], ["degr2"])

    async def summarize(self, q, groups, resolution, sql_results):
        self.calls.append(("summarize", q, sql_results))
        return (SimpleNamespace(answer="Каневский — Помощник Юриста"), ["CIT"])


def test_runs_three_stages_in_order_and_answers_with_citations():
    pipe = _FakePipe()
    agent = build_grounded_agent(pipe)
    state = asyncio.run(agent.ainvoke({"messages": [HumanMessage(content="ФИО юристов?")]}))

    # stages executed in sequence, sql receiving retrieve's candidates
    assert [c[0] for c in pipe.calls] == ["retrieve", "run_table_sql", "summarize"]
    assert pipe.calls[1][1] == ["tc"]
    assert pipe.calls[2][2] == ["sqlres"]

    msgs = state["messages"]
    assert isinstance(msgs[-1], AIMessage)
    assert msgs[-1].content == "Каневский — Помощник Юриста"
    assert state["citations"] == ["CIT"]


def test_empty_answer_falls_back_to_message():
    pipe = _FakePipe()

    async def _summarize(q, g, r, s):
        return (SimpleNamespace(answer=""), [])

    pipe.summarize = _summarize
    agent = build_grounded_agent(pipe)
    state = asyncio.run(agent.ainvoke({"messages": [HumanMessage(content="x")]}))
    assert "нет ответа" in state["messages"][-1].content
