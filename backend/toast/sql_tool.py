"""Обёртки над SQL-графом.

Два способа вызова:
  • `run_sql_tool(...)` — низкоуровневый помощник: компилирует граф и гоняет один
    вход. Удобен для тестов и eval-скрипта.
  • `make_sql_tool(...)` — возвращает LangChain StructuredTool `query_table` для
    будущего пайплайна; граф компилируется ОДИН раз и переиспользуется между
    вызовами.

Оба приводят состояние графа к стабильному внешнему контракту через `_project`.
"""

from typing import Any

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.tools import BaseTool, StructuredTool
from langgraph.graph.state import CompiledStateGraph

from toast.sql_graph import build_sql_graph


def _project(inputs: dict, state: dict) -> dict:
    """Проекция состояния графа во внешний контракт инструмента."""
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


async def _invoke(graph: CompiledStateGraph, inputs: dict) -> dict:
    """Прогнать готовый граф на одном входе и вернуть контракт."""
    state = await graph.ainvoke(inputs)
    return _project(inputs, state)


async def run_sql_tool(
    inputs: dict,
    model: BaseChatModel,
    executor: Any,
    max_queries: int,
    candidates_per_round: int,
) -> dict:
    """Скомпилировать граф и ответить на один вход. Для тестов и eval."""
    graph = build_sql_graph(model, executor, max_queries, candidates_per_round)
    return await _invoke(graph, inputs)


def make_sql_tool(
    executor: Any,
    model: BaseChatModel,
    max_queries: int,
    candidates_per_round: int,
) -> BaseTool:
    """StructuredTool `query_table` с графом, скомпилированным один раз."""
    graph = build_sql_graph(model, executor, max_queries, candidates_per_round)

    async def _call(
        question: str,
        chunk_id: str,
        table: str,
        desc_vector: str,
        desc_full: str,
    ) -> dict:
        return await _invoke(graph, {
            "question": question, "chunk_id": chunk_id, "table": table,
            "desc_vector": desc_vector, "desc_full": desc_full,
        })

    return StructuredTool.from_function(
        coroutine=_call,
        name="query_table",
        description=(
            "Ответить на вопрос по одной toast-таблице. Вход: question, "
            "chunk_id, table (toast_tbl_<hex>), desc_vector, desc_full. "
            "Возвращает {status, answer, sql_attempts, rows_used}."
        ),
    )
