"""SQL-инструмент как langgraph-граф над одной таблицей.

scope -> generate -> execute(∥) -> judge -> (retry | summarize) -> END
LLM: generate (батч SQL), judge (достаточно/ещё раунд), summarize (ответ).
Детерминированные части: фетч колонок, параллельное выполнение, учёт бюджета.
"""

import asyncio
import json
from typing import Any, TypedDict

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

FIXED_SCHEMA = (
    "Таблицы извлечены из XLSX (Postgres, схема splitter_toast). У каждой "
    "первые служебные колонки: _splitter_row_number (int), "
    "_splitter_source_row (int), _splitter_source_range (text). Дальше — "
    "колонки данных: column_1, column_2, ... или переименованные "
    "(из заголовков). Используй ТОЛЬКО реальные имена колонок из списка ниже."
)

GENERATE_SYS = (
    FIXED_SCHEMA
    + " Составь SQL SELECT к ОДНОЙ переданной таблице, чтобы ответить на "
    "вопрос. Верни JSON-массив из нескольких РАЗНЫХ по подходу SELECT-строк "
    "(без markdown, без пояснений). Только SELECT, только эта таблица."
)
JUDGE_SYS = (
    "Ты оцениваешь, достаточно ли полученных строк, чтобы ответить на вопрос. "
    "Ответь ровно одним словом: SUFFICIENT или NEED_MORE."
)
SUMMARIZE_SYS = (
    "Ответь на вопрос пользователя СТРОГО по предоставленным строкам таблицы. "
    "Не выдумывай. Если данных недостаточно — так и скажи. Кратко, по-русски."
)
NO_DATA_MSG = "В данных таблицы нет ответа на этот вопрос."
JUDGE_ROWS_CAP = 30  # строк в контекст судьи/суммаризатора


class SqlToolState(TypedDict, total=False):
    question: str
    chunk_id: str
    table: str
    desc_vector: str
    desc_full: str
    columns: list[str]
    candidates: list[str]
    round: int
    executed_count: int
    attempts: list[dict[str, Any]]
    verdict: str
    answer: str
    status: str


def parse_sql_candidates(text: str, limit: int) -> list[str]:
    """Достаёт список SELECT-строк из ответа модели (JSON-массив или строки)."""
    cleaned = text.strip().strip("`").strip()
    if cleaned.lower().startswith("json"):
        cleaned = cleaned[4:].strip()
    try:
        data = json.loads(cleaned)
        if isinstance(data, list):
            out = [str(x).strip() for x in data if str(x).strip()]
            return out[:limit]
    except json.JSONDecodeError:
        pass
    lines = [ln.strip() for ln in cleaned.splitlines()
             if ln.strip().lower().startswith("select")]
    return lines[:limit] or ([cleaned] if cleaned.lower().startswith("select") else [])


def _ok_rows(attempts: list[dict]) -> list[dict]:
    out: list[dict] = []
    for a in attempts:
        if a["ok"]:
            out.extend(a["rows"])
    return out


def build_sql_graph(
    model: BaseChatModel,
    executor: Any,
    max_queries: int,
    candidates_per_round: int,
) -> CompiledStateGraph:
    async def scope(state: SqlToolState) -> SqlToolState:
        columns = await executor.fetch_columns(state["table"])
        return {"columns": columns, "attempts": [], "executed_count": 0, "round": 0}

    async def generate(state: SqlToolState) -> SqlToolState:
        remaining = max_queries - state["executed_count"]
        n = max(1, min(candidates_per_round, remaining))
        errors = [a["error"] for a in state["attempts"] if not a["ok"]]
        prompt = (
            f"Вопрос: {state['question']}\n"
            f"Таблица: {state['table']}\n"
            f"Описание (кратко): {state['desc_vector']}\n"
            f"Описание (полно): {state['desc_full']}\n"
            f"Реальные колонки: {', '.join(state['columns'])}\n"
            f"Нужно вернуть до {n} разных SELECT."
        )
        if errors:
            prompt += "\n\nПрошлые ошибки SQL (исправь):\n" + "\n".join(errors[-3:])
        reply = await model.ainvoke(
            [SystemMessage(GENERATE_SYS), HumanMessage(prompt)],
            config={"tags": ["internal"]},
        )
        candidates = parse_sql_candidates(str(reply.content), n)
        return {"candidates": candidates, "round": state["round"] + 1}

    async def execute(state: SqlToolState) -> SqlToolState:
        table = state["table"]
        cands = state["candidates"]
        results = await asyncio.gather(
            *(executor.run_select(sql, table) for sql in cands)
        )
        new: list[dict] = []
        for sql, res in zip(cands, results):
            if isinstance(res, str):
                new.append({"sql": sql, "ok": False, "error": res,
                            "rows": [], "row_count": 0, "truncated": False})
            else:
                new.append({"sql": sql, "ok": True, "error": None,
                            "rows": res["rows"], "row_count": res["row_count"],
                            "truncated": res["truncated"]})
        return {
            "attempts": state["attempts"] + new,
            "executed_count": state["executed_count"] + len(cands),
        }

    async def judge(state: SqlToolState) -> SqlToolState:
        rows = _ok_rows(state["attempts"])
        if not rows:
            return {"verdict": "need_more"}  # нечего оценивать — без LLM
        reply = await model.ainvoke(
            [
                SystemMessage(JUDGE_SYS),
                HumanMessage(
                    f"Вопрос: {state['question']}\n"
                    f"Строки: {json.dumps(rows[:JUDGE_ROWS_CAP], ensure_ascii=False, default=str)}"
                ),
            ],
            config={"tags": ["internal"]},
        )
        verdict = "sufficient" if "suffic" in str(reply.content).lower() else "need_more"
        return {"verdict": verdict}

    async def summarize(state: SqlToolState) -> SqlToolState:
        rows = _ok_rows(state["attempts"])
        if not rows:
            any_ok = any(a["ok"] for a in state["attempts"])
            if any_ok:
                return {"status": "no_data", "answer": NO_DATA_MSG}
            last = next((a["error"] for a in reversed(state["attempts"]) if a["error"]),
                        "неизвестная ошибка")
            return {"status": "error", "answer": f"Не удалось выполнить SQL: {last}"}
        reply = await model.ainvoke(
            [
                SystemMessage(SUMMARIZE_SYS),
                HumanMessage(
                    f"Вопрос: {state['question']}\n"
                    f"Строки: {json.dumps(rows[:JUDGE_ROWS_CAP], ensure_ascii=False, default=str)}"
                ),
            ]
        )
        return {"status": "ok", "answer": str(reply.content)}

    def route(state: SqlToolState) -> str:
        if state.get("verdict") == "sufficient":
            return "summarize"
        if state["executed_count"] >= max_queries:
            return "summarize"
        return "generate"

    g = StateGraph(SqlToolState)
    g.add_node("scope", scope)
    g.add_node("generate", generate)
    g.add_node("execute", execute)
    g.add_node("judge", judge)
    g.add_node("summarize", summarize)
    g.add_edge(START, "scope")
    g.add_edge("scope", "generate")
    g.add_edge("generate", "execute")
    g.add_edge("execute", "judge")
    g.add_conditional_edges("judge", route, ["generate", "summarize"])
    g.add_edge("summarize", END)
    return g.compile()
