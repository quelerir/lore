"""Демо-режим «SQL (демо)»: конвертация хода SQL-графа в Chainlit-шаги.

Граф (toast/) про Chainlit не знает: он отдаёт события через
astream(stream_mode=["updates", "messages", "values"]), а этот модуль
превращает их в cl.Step (стадии + вложенные попытки) и стрим токенов ответа.
Живёт только в демо-ветке; в прод не мержится.
"""

import json
from typing import TypedDict

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


class StepDesc(TypedDict):
    """Описание Chainlit-шага стадии графа."""

    name: str
    output: str
    children: list[SubStep]


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


def step_payload(node: str, delta: dict, *, round_no: int,
                 seen_attempts: int) -> StepDesc | None:
    """Описание шага для завершившегося узла графа; None — узел не показываем.

    init не несёт информации; summarize уходит токенами в само сообщение.
    seen_attempts — сколько попыток уже показано прошлыми раундами: дельта
    узла execute содержит НАКОПЛЕННЫЙ список attempts.
    """
    if node == "generate":
        cands = delta.get("candidates", [])
        return {
            "name": f"Генерация SQL — раунд {round_no}",
            "output": "\n\n".join(cands) if cands else "(нет кандидатов)",
            "children": [],
        }
    if node == "execute":
        new = delta.get("attempts", [])[seen_attempts:]
        return {
            "name": f"Выполнение SQL — раунд {round_no}",
            "output": f"попыток: {len(new)}",
            "children": [
                {
                    "name": f"Попытка {seen_attempts + i + 1}",
                    "input": a["sql"],
                    "output": _attempt_preview(a),
                    "is_error": not a["ok"],
                }
                for i, a in enumerate(new)
            ],
        }
    if node == "judge":
        return {
            "name": "Оценка достаточности",
            "output": delta.get("verdict", ""),
            "children": [],
        }
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
    """Один прогон графа: стадии → cl.Step, токены summarize → сообщение out.

    stream_mode: updates — завершившиеся узлы (→ шаги), messages — токены
    LLM (незатегированный summarize стримится в ответ), values — финальное
    состояние (ответ для no_data/error, где LLM не вызывается).
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
    round_no = 0
    seen_attempts = 0
    # Колбэк превращает LLM-вызовы узлов (generate/judge/summarize) в
    # llm-шаги Chainlit — полный трейс для дебага. Тег internal скрывает
    # только их токены из стрима сообщения, шаги остаются видимыми.
    config = RunnableConfig(callbacks=[cl.LangchainCallbackHandler()])
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
            if node == "generate":
                round_no = delta.get("round", round_no + 1)
            desc = step_payload(node, delta, round_no=round_no,
                                seen_attempts=seen_attempts)
            if node == "execute":
                seen_attempts = len(delta.get("attempts", []))
            if desc is None:
                continue
            async with cl.Step(name=desc["name"], type="tool") as step:
                step.output = desc["output"]
                for child in desc["children"]:
                    async with cl.Step(name=child["name"], type="tool") as sub:
                        sub.input = child["input"]
                        sub.output = child["output"]
                        sub.is_error = child["is_error"]
    # no_data/error не зовут LLM — токенов не было, берём ответ из состояния.
    if not streamed and final_state and final_state.get("answer"):
        await out.stream_token(final_state["answer"])
