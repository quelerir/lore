import asyncio

from langchain_core.language_models.fake_chat_models import FakeListChatModel
from langchain_core.messages import HumanMessage

from agents import Mode, PROFILE_TO_MODE, build_agent
from agents.fast import build_fast_agent


class FakeStore:
    def __init__(self, tables=None, select_result=None):
        self._tables = tables or []
        self._select = select_result

    async def discover(self, document_hint):
        return self._tables

    async def inspect(self, table_id):
        return {
            "table_id": table_id,
            "columns": ["column_1"],
            "row_count": 1,
            "header_hint": None,
        }

    async def run_select(self, sql):
        return self._select


TABLE = {
    "source_path": "hr/demo.xlsx",
    "table_id": "toast_tbl_d1b2c3d4e5f6a7b8c9d0",
    "coordinates": {},
    "summary": "demo",
}


def test_profile_mapping():
    assert PROFILE_TO_MODE["fast"] is Mode.FAST
    assert PROFILE_TO_MODE["deep"] is Mode.DEEP


def test_build_agent_both_modes():
    model = FakeListChatModel(responses=["x"])
    store = FakeStore()
    assert build_agent(Mode.FAST, model=model, store=store) is not None
    assert build_agent(Mode.DEEP, model=model, store=store) is not None


def test_fast_route_happy_path():
    model = FakeListChatModel(
        responses=[
            "SELECT column_1 FROM splitter_toast.toast_tbl_d1b2c3d4e5f6a7b8c9d0",
            "Ответ: Смирнов Пётр (источник hr/demo.xlsx)",
        ]
    )
    store = FakeStore(
        tables=[TABLE],
        select_result={
            "columns": ["column_1"],
            "rows": [{"column_1": "Смирнов Пётр"}],
            "row_count": 1,
            "truncated": False,
        },
    )
    agent = build_fast_agent(model, store)
    out = asyncio.run(agent.ainvoke({"messages": [HumanMessage("кто юристы?")]}))
    assert "Смирнов" in out["messages"][-1].content


def test_fast_route_no_table_abstains():
    model = FakeListChatModel(responses=["не должен вызываться"])
    agent = build_fast_agent(model, FakeStore(tables=[]))
    out = asyncio.run(agent.ainvoke({"messages": [HumanMessage("про клубы")]}))
    assert "no-table-answer" in out["messages"][-1].content
