"""Демо-режим «SQL (демо)»: прогон SQL-графа с полным трейсом в Chainlit.

Дерево шагов строит LangchainCallbackHandler: корневой run «LangGraph», внутри
него узлы графа (generate/execute/judge/summarize), внутри узлов — llm-вызовы.
Этот модуль добавляет к нему только то, чего колбэк не видит: SQL-попытки
исполнителя, вложенные под-шагами В УЗЕЛ execute (parent_id из handler.steps).
Граф (toast/) про Chainlit не знает. Живёт только в демо-ветке.
"""

import json
from typing import Any, TypedDict

import chainlit as cl
from langchain_core.messages import AIMessageChunk
from langchain_core.runnables import RunnableConfig
from langgraph.graph.state import CompiledStateGraph

from agents.base import build_sql_model
from config import get_settings
from toast.executor import PgExecutor
from toast.sql_graph import build_sql_graph

ROWS_PREVIEW = 5  # сколько строк показываем в output попытки


class SubStep(TypedDict):
    """Вложенный шаг одной SQL-попытки."""

    name: str
    input: str
    output: str
    is_error: bool


def _attempt_preview(attempt: dict) -> str:
    """Короткий output попытки: ошибка, «0 строк» или превью строк."""
    if not attempt["ok"]:
        return attempt["error"] or "ошибка"
    if attempt["row_count"] == 0:
        return "0 строк"
    preview = json.dumps(attempt["rows"][:ROWS_PREVIEW],
                         ensure_ascii=False, default=str)
    if attempt["row_count"] > ROWS_PREVIEW:
        preview += f"\n… всего строк: {attempt['row_count']}"
    return preview


def attempt_substeps(delta: dict, seen_attempts: int) -> list[SubStep]:
    """Под-шаги для НОВЫХ попыток из дельты узла execute.

    seen_attempts — сколько попыток уже показано прошлыми раундами: дельта
    узла execute содержит НАКОПЛЕННЫЙ список attempts.
    """
    new = delta.get("attempts", [])[seen_attempts:]
    return [
        {
            "name": f"Попытка {seen_attempts + i + 1}",
            "input": a["sql"],
            "output": _attempt_preview(a),
            "is_error": not a["ok"],
        }
        for i, a in enumerate(new)
    ]


def node_step_id(handler: Any, node: str) -> str | None:
    """id ПОСЛЕДНЕГО шага узла графа из колбэка — родитель для попыток.

    handler.steps: dict[run_id, Step] в порядке создания; берём последний шаг
    с именем узла (текущий раунд). None — колбэк шаг не создал (fail-open:
    попытки лягут на верхний уровень, но не потеряются).
    """
    for step in reversed(list(getattr(handler, "steps", {}).values())):
        if getattr(step, "name", None) == node:
            return getattr(step, "id", None)
    return None


def build_demo_graph() -> CompiledStateGraph:
    """Граф демо-режима: та же сборка, что в Studio, DSN и лимиты из настроек."""
    s = get_settings()
    if s.toast_dsn is None:  # профиль регистрируется только с кредами
        raise RuntimeError("SQL-демо требует TOAST_DB_* в окружении")
    return build_sql_graph(
        build_sql_model(),
        PgExecutor(s.toast_dsn),
        max_queries=s.sql_max_queries,
        candidates_per_round=s.sql_candidates_per_round,
    )


async def handle_sql_message(graph: CompiledStateGraph, question: str,
                             out: cl.Message) -> None:
    """Один прогон графа: трейс — от колбэка, попытки SQL — под узлом execute,
    токены summarize — в сообщение out.

    stream_mode: updates — завершившиеся узлы (→ попытки execute), messages —
    токены LLM (незатегированный summarize стримится в ответ), values —
    финальное состояние (ответ для no_data/error, где LLM не вызывается).
    """
    s = get_settings()
    inputs = {
        "question": question,
        "chunk_id": "demo",
        "table": s.sql_demo_table,
        "desc_vector": s.sql_demo_desc_vector,
        "desc_full": s.sql_demo_desc_full,
    }
    streamed = ""
    final_state: dict | None = None
    seen_attempts = 0
    # Колбэк строит дерево трейса (LangGraph → узлы → llm-вызовы). Тег
    # internal скрывает только токены служебных вызовов из стрима сообщения,
    # шаги остаются видимыми.
    handler = cl.LangchainCallbackHandler()
    config = RunnableConfig(callbacks=[handler])
    async for mode, payload in graph.astream(
        inputs, stream_mode=["updates", "messages", "values"], config=config
    ):
        if mode == "values":
            final_state = payload
            continue
        if mode == "messages":
            chunk, meta = payload
            if "internal" in (meta.get("tags") or []):
                continue
            if (
                isinstance(chunk, AIMessageChunk)
                and isinstance(chunk.content, str)
                and chunk.content
            ):
                streamed += chunk.content
                await out.stream_token(chunk.content)
            continue
        for node, delta in payload.items():
            if node != "execute":
                continue
            subs = attempt_substeps(delta, seen_attempts)
            seen_attempts = len(delta.get("attempts", []))
            parent_id = node_step_id(handler, "execute")
            for child in subs:
                sub = cl.Step(name=child["name"], type="tool",
                              parent_id=parent_id)
                async with sub:
                    sub.input = child["input"]
                    sub.output = child["output"]
                    sub.is_error = child["is_error"]
    # no_data/error не зовут LLM — токенов не было, берём ответ из состояния.
    if not streamed and final_state and final_state.get("answer"):
        await out.stream_token(final_state["answer"])
