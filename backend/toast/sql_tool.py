"""Обёртка над SQL-графом.

`run_sql_tool(...)` — компилирует граф и гоняет один вход; используется тестами
и eval-скриптом. Состояние графа приводится к стабильному внешнему контракту
через `_project`. LangChain-инструмент для чат-агента здесь не живёт: он
появится вместе с реальным пайплайном, который будет поставлять table/desc_*.
"""

from typing import Any

from langchain_core.language_models.chat_models import BaseChatModel

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


async def run_sql_tool(
    inputs: dict,
    model: BaseChatModel,
    executor: Any,
    max_queries: int,
    candidates_per_round: int,
) -> dict:
    """Скомпилировать граф и ответить на один вход. Для тестов и eval."""
    graph = build_sql_graph(model, executor, max_queries, candidates_per_round)
    state = await graph.ainvoke(inputs)
    return _project(inputs, state)
