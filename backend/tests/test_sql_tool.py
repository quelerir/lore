import asyncio

from langchain_core.messages import AIMessage

from fakes import ScriptedChatModel
from test_sql_graph import FakeExecutor, _rows, _sample  # переиспользуем фейки

LEGAL = "toast_tbl_ec48a6d52d16ab405f95"


def test_run_sql_tool_projects_contract():
    from toast.sql_tool import run_sql_tool

    model = ScriptedChatModel(responses=[
        AIMessage(content='["SELECT column_1 FROM %s"]' % LEGAL),
        AIMessage(content="SUFFICIENT"),
        AIMessage(content="Каневский Георгий."),
    ])
    exe = FakeExecutor(results=[_sample(), _rows(1)])
    inputs = {"question": "ФИО юристов", "chunk_id": "c1", "table": LEGAL,
              "desc_vector": "юристы", "desc_full": "Таблица юристов"}
    out = asyncio.run(run_sql_tool(inputs, model, exe, max_queries=3,
                                   candidates_per_round=1))
    assert out["status"] == "ok"
    assert out["chunk_id"] == "c1"
    assert out["table"] == LEGAL
    assert out["rows_used"] == 1
    assert out["sql_attempts"] and out["sql_attempts"][0]["ok"] is True
    assert "sql" in out["sql_attempts"][0]
