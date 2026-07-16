import asyncio

from langchain_core.messages import AIMessage

from fakes import FakeToastStore, ScriptedChatModel
from toast.policy import POLICY_REFUSAL

TBL_A = "toast_tbl_17a7241d0a976f287103"
TBL_B = "toast_tbl_e765505051472ed91b81"
PII = "toast_tbl_9c6dcab0dfdd486cfddf"


def _table(table_id, source="функционал Отдел контекстной рекламы.xlsx"):
    return {
        "table_id": table_id,
        "source_path": source,
        "coordinates": "A1:C10",
        "summary": "Columns: ...",
    }


def _info(table_id, header_hint=None):
    return {
        "table_id": table_id,
        "columns": ["_splitter_source_row", "column_1", "column_2"],
        "row_count": 42,
        "header_hint": header_hint,
    }


def _run(model, store, question="вопрос"):
    from toast.subagent import run_toast_subagent

    return asyncio.run(run_toast_subagent(model, store, question))


def test_happy_path_returns_rows_sql_and_provenance():
    store = FakeToastStore(
        tables=[_table(TBL_A), _table(TBL_B)],
        infos={TBL_A: _info(TBL_A, header_hint="Columns: Вадим Шестаков ..."),
               TBL_B: _info(TBL_B)},
        select_results=[{
            "columns": ["column_1"],
            "rows": [{"column_1": "x"}],
            "row_count": 1,
            "truncated": False,
        }],
    )
    model = ScriptedChatModel(
        responses=[AIMessage(content=f"SELECT column_1 FROM {TBL_A}")]
    )
    result = _run(model, store)
    assert result["status"] == "ok"
    assert result["rows"] == [{"column_1": "x"}]
    assert result["sql"].startswith("SELECT")
    assert {s["table_id"] for s in result["sources"]} == {TBL_A, TBL_B}
    assert TBL_A in result["header_hints"]
    assert store.executed == [f"SELECT column_1 FROM {TBL_A}"]


def test_empty_discovery_returns_no_table_without_llm():
    store = FakeToastStore(tables=[])
    model = ScriptedChatModel(responses=[])  # LLM не должна вызываться
    result = _run(model, store)
    assert result["status"] == "no_table"


def test_model_no_table_verdict():
    store = FakeToastStore(tables=[_table(TBL_A)], infos={TBL_A: _info(TBL_A)})
    model = ScriptedChatModel(responses=[AIMessage(content="NO_TABLE")])
    result = _run(model, store)
    assert result["status"] == "no_table"
    assert store.executed == []


def test_all_pii_tables_refused_before_planning():
    store = FakeToastStore(tables=[_table(PII)], infos={PII: _info(PII)})
    model = ScriptedChatModel(responses=[])  # до планирования не доходит
    result = _run(model, store)
    assert result["status"] == "refused"
    assert result["message"] == POLICY_REFUSAL
    assert store.executed == []


def test_policy_refusal_from_store_not_retried():
    store = FakeToastStore(
        tables=[_table(TBL_A), _table(PII)],
        infos={TBL_A: _info(TBL_A), PII: _info(PII)},
        select_results=["Отказ policy gate: таблица содержит персональные данные"],
    )
    model = ScriptedChatModel(
        responses=[AIMessage(content=f"SELECT * FROM {PII}")]
    )
    result = _run(model, store)
    assert result["status"] == "refused"
    assert len(store.executed) == 1  # без retry


def test_sql_error_retried_once_then_ok():
    store = FakeToastStore(
        tables=[_table(TBL_A)],
        infos={TBL_A: _info(TBL_A)},
        select_results=[
            "Ошибка SQL: column \"nope\" does not exist",
            {"columns": ["column_1"], "rows": [], "row_count": 0, "truncated": False},
        ],
    )
    model = ScriptedChatModel(
        responses=[
            AIMessage(content=f"SELECT nope FROM {TBL_A}"),
            AIMessage(content=f"SELECT column_1 FROM {TBL_A}"),
        ]
    )
    result = _run(model, store)
    assert result["status"] == "ok"
    assert len(store.executed) == 2


def test_two_sql_errors_return_error_status():
    store = FakeToastStore(
        tables=[_table(TBL_A)],
        infos={TBL_A: _info(TBL_A)},
        select_results=[
            "Ошибка SQL: синтаксис",
            "Ошибка SQL: синтаксис снова",
        ],
    )
    model = ScriptedChatModel(
        responses=[
            AIMessage(content="SELECT ??"),
            AIMessage(content="SELECT ?!"),
        ]
    )
    result = _run(model, store)
    assert result["status"] == "error"
    assert "синтаксис снова" in result["message"]


def test_truncated_flag_passthrough():
    store = FakeToastStore(
        tables=[_table(TBL_A)],
        infos={TBL_A: _info(TBL_A)},
        select_results=[{
            "columns": ["column_1"],
            "rows": [{"column_1": "x"}],
            "row_count": 200,
            "truncated": True,
        }],
    )
    model = ScriptedChatModel(
        responses=[AIMessage(content=f"SELECT column_1 FROM {TBL_A}")]
    )
    result = _run(model, store)
    assert result["status"] == "ok"
    assert result["truncated"] is True
