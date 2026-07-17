"""SQL-инструмент как langgraph-граф над ОДНОЙ toast-таблицей.

Инструмент отвечает на вопрос пользователя по одной таблице: генерирует SQL в
несколько раундов (внутри раунда — параллельные кандидаты), проверяет
достаточность результата и суммирует ответ.

Топология графа:

    START → init → generate → execute(∥) → judge ─┐
                       ▲                    │      │
     (нужен ещё раунд) └──────────< generate┘      │
                                                   ▼
                            (бюджет исчерпан) → summarize → END

Ответственность узлов:
  • init      — детерминированный: инициализирует аккумуляторы (без БД).
                Имена и смысл колонок берутся из desc_full (рукописное
                описание), поэтому реальные колонки из БД не тянутся.
  • generate  — LLM: по вопросу, описаниям и реальным колонкам выдаёт батч
                РАЗНЫХ SQL-кандидатов (учитывая остаток бюджета и прошлые ошибки).
  • execute   — детерминированный: гоняет кандидатов ПАРАЛЛЕЛЬНО через read-only
                исполнитель, копит попытки и счётчик выполненных запросов.
  • judge     — LLM: решает, достаточно ли полученных строк для ответа
                (ловит «строки есть, но не по теме»). Не зовёт модель, если
                строк ещё нет.
  • summarize — LLM/детерминированный: формулирует ответ строго по строкам,
                либо возвращает статус no_data / error.

Управление циклом:
  • Бюджет `max_queries` — жёсткий предел ЧИСЛА выполненных SQL за все раунды.
    Проверяется в `after_execute` ДО судьи: если бюджет исчерпан, идём прямо в
    summarize (не тратим лишний вызов судьи).
  • Вердикт судьи — в `after_judge`: sufficient → summarize, иначе → новый раунд.
LLM используется только в generate/judge/summarize; дисциплина шагов и бюджет
зашиты в код и не зависят от качества модели.
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
    "(из заголовков). Используй физические имена колонок строго как в "
    "описании таблицы."
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
JUDGE_ROWS_CAP = 30  # сколько строк отдаём в контекст судьи/суммаризатора


class SqlToolState(TypedDict, total=False):
    """Состояние графа. total=False: узлы возвращают частичные апдейты,
    langgraph сливает их в общее состояние (последняя запись побеждает).

    Вход (от вызывающего): question, chunk_id, table, desc_vector, desc_full.
    Заполняется узлами: candidates (generate),
    round/executed_count/attempts (init+execute), verdict (judge),
    answer/status (summarize).
    """

    question: str
    chunk_id: str
    table: str
    desc_vector: str
    desc_full: str
    candidates: list[str]
    round: int
    executed_count: int
    attempts: list[dict[str, Any]]
    verdict: str
    answer: str
    status: str


class SqlToolInput(TypedDict):
    """Входные поля инструмента (форма ввода в Studio)."""

    question: str
    chunk_id: str
    table: str
    desc_vector: str
    desc_full: str


def parse_sql_candidates(text: str, limit: int) -> list[str]:
    """Достаёт до `limit` SELECT-строк из ответа модели.

    Принимает два формата: JSON-массив строк (основной) или голые строки,
    каждая начинается с SELECT (фолбэк, если модель проигнорировала формат).
    Снимает markdown-ограждение ```/```json.
    """
    cleaned = text.strip().strip("`").strip()
    if cleaned.lower().startswith("json"):
        cleaned = cleaned[4:].strip()
    try:
        data = json.loads(cleaned)
        if isinstance(data, list):
            return [str(x).strip() for x in data if str(x).strip()][:limit]
    except json.JSONDecodeError:
        pass
    lines = [ln.strip() for ln in cleaned.splitlines()
             if ln.strip().lower().startswith("select")]
    return lines[:limit] or ([cleaned] if cleaned.lower().startswith("select") else [])


def _ok_rows(attempts: list[dict]) -> list[dict]:
    """Плоский список строк из всех успешных попыток (для судьи/суммаризатора)."""
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
    """Собирает и компилирует граф SQL-инструмента.

    Аргументы:
      model      — LLM для generate/judge/summarize.
      executor   — объект с async `fetch_columns(table)` и
                   `run_select(sql, table) -> SelectResult | str` (str = отказ/ошибка).
      max_queries          — предел числа выполненных SQL за все раунды.
      candidates_per_round — сколько параллельных кандидатов генерить в раунде.

    Узлы замыкают эти аргументы; состояние течёт по `SqlToolState`.
    """

    async def init(state: SqlToolState) -> SqlToolState:
        """Детерминированный старт: инициализация аккумуляторов (без БД).

        Имена и смысл колонок приходят из desc_full (рукописное описание),
        поэтому реальные колонки из БД тянуть не нужно.
        """
        return {"attempts": [], "executed_count": 0, "round": 0}

    async def generate(state: SqlToolState) -> SqlToolState:
        """LLM выдаёт батч SQL-кандидатов под остаток бюджета и прошлые ошибки."""
        remaining = max_queries - state["executed_count"]
        # remaining >= 1 гарантируется маршрутизацией (в generate не попадаем при
        # исчерпанном бюджете); max(1, …) — просто страховка.
        n = max(1, min(candidates_per_round, remaining))
        errors = [a["error"] for a in state["attempts"] if not a["ok"]]
        prompt = (
            f"Вопрос: {state['question']}\n"
            f"Таблица: {state['table']}\n"
            f"Описание (кратко): {state['desc_vector']}\n"
            f"Описание (полно): {state['desc_full']}\n"
            f"Нужно вернуть до {n} разных SELECT."
        )
        if errors:
            prompt += "\n\nПрошлые ошибки SQL (исправь):\n" + "\n".join(errors[-3:])
        # tag internal: служебные токены не показываем пользователю в UI.
        reply = await model.ainvoke(
            [SystemMessage(GENERATE_SYS), HumanMessage(prompt)],
            config={"tags": ["internal"]},
        )
        candidates = parse_sql_candidates(str(reply.content), n)
        return {"candidates": candidates, "round": state["round"] + 1}

    async def execute(state: SqlToolState) -> SqlToolState:
        """Гоняет всех кандидатов раунда параллельно; копит попытки и счётчик."""
        table = state["table"]
        cands = state["candidates"]
        results = await asyncio.gather(
            *(executor.run_select(sql, table) for sql in cands)
        )
        new: list[dict] = []
        for sql, res in zip(cands, results):
            # Исполнитель возвращает str при отказе guardrails / ошибке SQL,
            # иначе SelectResult со строками.
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
        """LLM: достаточно ли строк для ответа. Без строк — need_more без вызова."""
        rows = _ok_rows(state["attempts"])
        if not rows:
            return {"verdict": "need_more"}
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
        """Терминальный узел: ответ по строкам, либо статус no_data / error."""
        rows = _ok_rows(state["attempts"])
        if not rows:
            # Хоть один успешный (но пустой) SELECT → данных нет; иначе все
            # попытки — ошибки БД → техническая ошибка.
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

    def after_execute(state: SqlToolState) -> str:
        """Бюджет исчерпан → сразу summarize (судью не зовём); иначе → judge."""
        return "summarize" if state["executed_count"] >= max_queries else "judge"

    def after_judge(state: SqlToolState) -> str:
        """Судья доволен → summarize; иначе → ещё раунд generate."""
        return "summarize" if state.get("verdict") == "sufficient" else "generate"

    g = StateGraph(SqlToolState, input_schema=SqlToolInput)
    g.add_node("init", init)
    g.add_node("generate", generate)
    g.add_node("execute", execute)
    g.add_node("judge", judge)
    g.add_node("summarize", summarize)
    g.add_edge(START, "init")
    g.add_edge("init", "generate")
    g.add_edge("generate", "execute")
    g.add_conditional_edges("execute", after_execute, ["judge", "summarize"])
    g.add_conditional_edges("judge", after_judge, ["generate", "summarize"])
    g.add_edge("summarize", END)
    return g.compile()
