"""SQL-инструмент как langgraph-граф над ОДНОЙ toast-таблицей.

Топология графа:

    START → sample → generate → execute(∥) → judge → summarize → END

    с тремя условными переходами:
      generate → summarize   если модель не дала ни одного кандидата
      execute  → summarize   если бюджет ИЛИ предел раундов исчерпан (минуя судью)
      judge    → generate    если строк недостаточно (ещё раунд)

Состояние — pydantic-модель с дефолтами (toast/models.py), промпты — в
toast/prompts.py, LLM-обвязка с фолбэками — в toast/llm.py. Здесь — только
узлы и топология. Обоснования решений: docs/sql-tool.md.
"""

import asyncio
import logging
from typing import Any

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from lore_retrieval.budget import sql_query_budget

from toast.llm import generate_candidates, judge_verdict
from toast.models import (
    DbError,
    Refusal,
    SqlToolInput,
    SqlToolState,
    Status,
    Verdict,
    make_attempt,
    ok_rows,
)
from toast.prompts import (
    GENERATE_SYS,
    JUDGE_SYS,
    NO_CANDIDATES_MSG,
    NO_DATA_MSG,
    SAMPLE_LIMIT,
    SUMMARIZE_SYS,
    generate_prompt,
    rows_context,
)

logger = logging.getLogger(__name__)


class SqlToolNodes:
    """Узлы и роутеры графа; зависимости — в конструкторе.

    LLM зовут только generate/judge/summarize; дисциплина шагов, бюджет и
    предел раундов зашиты в код и не зависят от качества модели.
    """

    def __init__(self, model: BaseChatModel, executor: Any,
                 max_queries: int, candidates_per_round: int) -> None:
        self.model = model
        self.executor = executor
        self.max_queries = max_queries
        self.candidates_per_round = candidates_per_round

    async def sample(self, state: SqlToolState) -> dict:
        """Детерминированные примеры строк — ВНЕ бюджета.

        Модель видит реальные имена колонок и формат значений до генерации;
        рассинхрон desc_full со схемой всплывает здесь, а не тратой бюджета.
        Сбой не фатален: пустые примеры + warning, граф продолжает.
        """
        sql = f"SELECT * FROM {state.table} LIMIT {SAMPLE_LIMIT}"
        try:
            res = await self.executor.run_select(sql, state.table)
        except Exception:
            logger.warning("sample query failed for %s", state.table,
                           exc_info=True)
            return {"sample_rows": []}
        if isinstance(res, (Refusal, DbError)):
            reason = res.reason if isinstance(res, Refusal) else res.message
            logger.warning("sample refused: %s", reason)
            return {"sample_rows": []}
        return {"sample_rows": res["rows"]}

    async def generate(self, state: SqlToolState) -> dict:
        """LLM выдаёт батч SQL-кандидатов под остаток бюджета и фидбек
        прошлых раундов (ошибки, пустые запросы, причина судьи, примеры)."""
        remaining = self.max_queries - state.executed_count
        # remaining >= 1 гарантируется маршрутизацией; max(1, …) — страховка.
        n = max(1, min(self.candidates_per_round, remaining))
        candidates = await generate_candidates(
            self.model,
            [SystemMessage(GENERATE_SYS), HumanMessage(generate_prompt(state, n))],
            n,
        )
        return {"candidates": candidates, "round": state.round + 1}

    async def execute(self, state: SqlToolState) -> dict:
        """Гоняет кандидатов раунда параллельно; копит попытки и счётчик.

        Дубликаты уже выполнявшихся SQL повторно не гоняются и бюджет не
        двигают; завершаемость держит предел раундов в after_execute.
        return_exceptions: сбой одного кандидата не роняет остальных.
        """
        tried = {a["sql"] for a in state.attempts}
        unique = [s for s in dict.fromkeys(state.candidates) if s not in tried]
        # Per-turn budget shared across the parallel table fan-out: run only as many
        # generated queries as the turn allowance still permits (the sample node is
        # never counted). When exhausted, run none — the round cap then ends the graph.
        budget = sql_query_budget.get()
        if budget is not None:
            unique = [sql for sql in unique if budget.try_consume()]
        results = await asyncio.gather(
            *(self.executor.run_select(sql, state.table) for sql in unique),
            return_exceptions=True,
        )
        new = [make_attempt(sql, res) for sql, res in zip(unique, results)]
        # Бюджет — только SQL, дошедшие до БД: Refusal guardrails существует,
        # чтобы модель ПЕРЕПИСАЛА запрос, и не должен съедать попытку.
        executed = sum(1 for r in results if not isinstance(r, Refusal))
        return {
            "attempts": state.attempts + new,
            "executed_count": state.executed_count + executed,
        }

    async def judge(self, state: SqlToolState) -> dict:
        """LLM: достаточно ли строк. Без строк — need_more без вызова."""
        if not ok_rows(state.attempts):
            return {"verdict": Verdict.NEED_MORE}
        verdict = await judge_verdict(
            self.model,
            [
                SystemMessage(JUDGE_SYS),
                HumanMessage(f"Вопрос: {state.question}\n"
                             + rows_context(state.attempts)),
            ],
        )
        return {
            "verdict": Verdict.SUFFICIENT if verdict.sufficient
            else Verdict.NEED_MORE,
            "judge_reason": verdict.reason,
        }

    async def summarize(self, state: SqlToolState) -> dict:
        """Терминальный узел: ответ по строкам, либо статус no_data / error."""
        rows = ok_rows(state.attempts)
        if not rows:
            if not state.attempts:
                # Сюда попадаем только из after_generate при пустом батче.
                return {"status": Status.ERROR,
                        "answer": f"Не удалось выполнить SQL: {NO_CANDIDATES_MSG}"}
            # Хоть один успешный (но пустой) SELECT → данных нет; иначе все
            # попытки — ошибки БД → техническая ошибка.
            if any(a["ok"] for a in state.attempts):
                return {"status": Status.NO_DATA, "answer": NO_DATA_MSG}
            last = next(
                (a["error"] for a in reversed(state.attempts) if a["error"]),
                "неизвестная ошибка",
            )
            return {"status": Status.ERROR,
                    "answer": f"Не удалось выполнить SQL: {last}"}
        reply = await self.model.ainvoke(
            [
                SystemMessage(SUMMARIZE_SYS),
                HumanMessage(f"Вопрос: {state.question}\n"
                             + rows_context(state.attempts)),
            ]
        )
        return {"status": Status.OK, "answer": str(reply.content)}

    def after_generate(self, state: SqlToolState) -> str:
        """Пустой батч кандидатов → summarize (иначе цикл без прогресса)."""
        return "execute" if state.candidates else "summarize"

    def after_execute(self, state: SqlToolState) -> str:
        """Бюджет или предел раундов исчерпан → summarize; иначе judge.

        Предел раундов — страховка завершаемости: батчи из дубликатов или
        отказов guardrails бюджет не двигают.
        """
        if (state.executed_count >= self.max_queries
                or state.round >= self.max_queries):
            return "summarize"
        return "judge"

    def after_judge(self, state: SqlToolState) -> str:
        """Судья доволен → summarize; иначе → ещё раунд generate."""
        return ("summarize" if state.verdict == Verdict.SUFFICIENT
                else "generate")


def build_sql_graph(
    model: BaseChatModel,
    executor: Any,
    max_queries: int,
    candidates_per_round: int,
) -> CompiledStateGraph:
    """Собирает и компилирует граф SQL-инструмента.

    executor — объект с async `run_select(sql, table) ->
    SelectResult | Refusal | DbError`. Сигнатура стабильна (Studio, демо).
    """
    nodes = SqlToolNodes(model, executor, max_queries, candidates_per_round)
    g = StateGraph(SqlToolState, input_schema=SqlToolInput)
    g.add_node("sample", nodes.sample)
    g.add_node("generate", nodes.generate)
    g.add_node("execute", nodes.execute)
    g.add_node("judge", nodes.judge)
    g.add_node("summarize", nodes.summarize)
    g.add_edge(START, "sample")
    g.add_edge("sample", "generate")
    g.add_conditional_edges("generate", nodes.after_generate,
                            ["execute", "summarize"])
    g.add_conditional_edges("execute", nodes.after_execute,
                            ["judge", "summarize"])
    g.add_conditional_edges("judge", nodes.after_judge,
                            ["generate", "summarize"])
    g.add_edge("summarize", END)
    return g.compile()
