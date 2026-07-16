"""Обёртка SQL-графа: прямой вызов run_sql_tool + LangChain StructuredTool."""

from typing import Any

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.tools import BaseTool, StructuredTool

from toast.sql_graph import build_sql_graph


def _project(inputs: dict, state: dict) -> dict:
    attempts = state.get("attempts", [])
    rows_used = sum(a["row_count"] for a in attempts if a["ok"])
    return {
        "status": state.get("status", "error"),
        "answer": state.get("answer", ""),
        "chunk_id": inputs["chunk_id"],
        "table": inputs["table"],
        "sql_attempts": [
            {"sql": a["sql"], "ok": a["ok"], "error": a["error"],
             "row_count": a["row_count"]}
            for a in attempts
        ],
        "rows_used": rows_used,
    }


async def run_sql_tool(
    inputs: dict,
    model: BaseChatModel,
    executor: Any,
    max_queries: int,
    candidates_per_round: int,
) -> dict:
    graph = build_sql_graph(model, executor, max_queries, candidates_per_round)
    state = await graph.ainvoke(inputs)
    return _project(inputs, state)


def make_sql_tool(
    executor: Any,
    model: BaseChatModel,
    max_queries: int,
    candidates_per_round: int,
) -> BaseTool:
    async def _call(
        question: str,
        chunk_id: str,
        table: str,
        desc_vector: str,
        desc_full: str,
    ) -> dict:
        inputs = {
            "question": question, "chunk_id": chunk_id, "table": table,
            "desc_vector": desc_vector, "desc_full": desc_full,
        }
        return await run_sql_tool(inputs, model, executor,
                                  max_queries, candidates_per_round)

    return StructuredTool.from_function(
        coroutine=_call,
        name="query_table",
        description=(
            "Ответить на вопрос по одной toast-таблице. Вход: question, "
            "chunk_id, table (toast_tbl_<hex>), desc_vector, desc_full. "
            "Возвращает {status, answer, sql_attempts, rows_used}."
        ),
    )
