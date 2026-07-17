"""SQL-инструмент как langgraph-граф над ОДНОЙ toast-таблицей.

Инструмент отвечает на вопрос пользователя по одной таблице: генерирует SQL в
несколько раундов (внутри раунда — параллельные кандидаты), проверяет
достаточность результата и суммирует ответ.

Топология графа:

    START → sample → generate → execute(∥) → judge → summarize → END

    с тремя условными переходами:
      generate → summarize   если модель не дала ни одного кандидата
      execute  → summarize   если бюджет запросов исчерпан (минуя судью)
      judge    → generate    если строк недостаточно (ещё раунд)

Состояние — pydantic-модель с дефолтами: аккумуляторы (attempts,
executed_count, round, …) инициализируются схемой, отдельный узел init не
нужен. Имена и смысл колонок берутся из desc_full (рукописное описание).

Ответственность узлов:
  • sample    — детерминированный: SELECT * LIMIT 5 вне бюджета — примеры
                строк для промпта generate; сбой не фатален.
  • generate  — LLM: по вопросу и описаниям таблицы выдаёт батч РАЗНЫХ
                SQL-кандидатов (учитывая остаток бюджета, прошлые ошибки и
                запросы, вернувшие 0 строк).
  • execute   — детерминированный: гоняет кандидатов ПАРАЛЛЕЛЬНО через
                read-only исполнитель, копит попытки и счётчик запросов.
                Дубликаты уже выполнявшихся SQL повторно не гоняет.
  • judge     — LLM: решает, достаточно ли полученных строк для ответа
                (ловит «строки есть, но не по теме»). Не зовёт модель, если
                строк ещё нет.
  • summarize — LLM/детерминированный: формулирует ответ строго по строкам,
                либо возвращает статус no_data / error.

Управление циклом:
  • Бюджет `max_queries` — предел ЧИСЛА реально выполненных SQL (дубликаты и
    отказы guardrails не считаются: их фидбек существует для переписывания).
    Проверяется в `after_execute` ДО судьи вместе с пределом раундов
    (round >= max_queries) — страховкой завершаемости.
  • Пустой батч кандидатов (модель не вернула ни одного SELECT) → сразу
    summarize.
  • Вердикт судьи — в `after_judge`: sufficient → summarize, иначе → новый раунд.
LLM используется только в generate/judge/summarize; дисциплина шагов и бюджет
зашиты в код и не зависят от качества модели.
"""

import asyncio
import json
import logging
import re
from typing import Any

import sqlglot
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from sqlglot import exp as sql_exp

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
from toast.models import (
    DbError,
    JudgeVerdict,
    Refusal,
    SqlCandidates,
    SqlToolInput,
    SqlToolState,
    Status,
    Verdict,
    make_attempt,
    ok_rows,
)


# «sufficient» с границами слова: в «insufficient» и «NEED_MORE...» не матчится.
_SUFFICIENT_RE = re.compile(r"\bsufficient\b")


def _log_fallback(node: str, exc: Exception) -> None:
    """Лог причины фолбэка structured output → текстовый путь.

    NotImplementedError — ожидаемо (фейки, модели без tools) → debug;
    остальное (сеть, 4xx) — warning: транзиентные ошибки не должны молча
    удваивать латентность.
    """
    level = logging.DEBUG if isinstance(exc, NotImplementedError) else logging.WARNING
    logging.getLogger(__name__).log(
        level, "%s: structured output недоступен (%r), текстовый фолбэк",
        node, exc,
    )


async def _judge_verdict(model: BaseChatModel, messages: list) -> JudgeVerdict:
    """Вердикт через structured output; фолбэк — текстовый парсинг без причины."""
    try:
        structured = model.with_structured_output(
            JudgeVerdict, method="function_calling"
        )
        return await structured.ainvoke(messages, config={"tags": ["internal"]})
    except Exception as e:
        _log_fallback("judge", e)
        reply = await model.ainvoke(messages, config={"tags": ["internal"]})
        text = str(reply.content).lower()
        ok = bool(_SUFFICIENT_RE.search(text)) and "need_more" not in text
        return JudgeVerdict(sufficient=ok, reason="")


def parse_sql_candidates(text: str, limit: int) -> list[str]:
    """Достаёт до `limit` SELECT-строк из ответа модели.

    Форматы по убыванию приоритета: JSON-массив строк (основной); текст
    целиком как SQL через sqlglot (многострочные запросы целы); построчный
    сбор строк, начинающихся с SELECT (прозаический ответ со вкраплениями).
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
    # Фолбэк 1: текст целиком — SQL (в т.ч. многострочный / несколько команд).
    try:
        statements = [s for s in sqlglot.parse(cleaned, read="postgres") if s]
        sqls = [
            s.sql(dialect="postgres")
            for s in statements
            if isinstance(s, (sql_exp.Select, sql_exp.SetOperation))
        ]
        if sqls:
            return sqls[:limit]
    except sqlglot.errors.ParseError:
        pass
    # Фолбэк 2: прозаический ответ со вкраплениями однострочных SELECT.
    lines = [ln.strip() for ln in cleaned.splitlines()
             if ln.strip().lower().startswith("select")]
    return lines[:limit] or ([cleaned] if cleaned.lower().startswith("select") else [])


async def _generate_candidates(model: BaseChatModel, messages: list,
                               n: int) -> list[str]:
    """Кандидаты через structured output; при любом сбое — текстовый фолбэк.

    OpenRouter-модели поддерживают function calling неровно, а фейки тестов
    не поддерживают вовсе, поэтому parse_sql_candidates остаётся фолбэком.
    """
    try:
        structured = model.with_structured_output(
            SqlCandidates, method="function_calling"
        )
        result = await structured.ainvoke(messages, config={"tags": ["internal"]})
        return [c.strip() for c in result.candidates if c.strip()][:n]
    except Exception as e:
        _log_fallback("generate", e)
        reply = await model.ainvoke(messages, config={"tags": ["internal"]})
        return parse_sql_candidates(str(reply.content), n)





def build_sql_graph(
    model: BaseChatModel,
    executor: Any,
    max_queries: int,
    candidates_per_round: int,
) -> CompiledStateGraph:
    """Собирает и компилирует граф SQL-инструмента.

    Аргументы:
      model      — LLM для generate/judge/summarize.
      executor   — объект с async `run_select(sql, table) -> SelectResult | str`
                   (str = отказ/ошибка).
      max_queries          — предел числа выполненных SQL за все раунды.
      candidates_per_round — сколько параллельных кандидатов генерить в раунде.

    Узлы замыкают эти аргументы; состояние течёт по `SqlToolState`.
    """

    async def sample(state: SqlToolState) -> dict:
        """Детерминированные примеры строк — ВНЕ бюджета.

        Модель видит реальные имена колонок и формат значений до генерации;
        рассинхрон desc_full со схемой всплывает здесь, а не тратой бюджета.
        Сбой не фатален: пустые примеры + warning, граф продолжает.
        """
        sql = f"SELECT * FROM {state.table} LIMIT {SAMPLE_LIMIT}"
        try:
            res = await executor.run_select(sql, state.table)
        except Exception:
            logging.getLogger(__name__).warning(
                "sample query failed for %s", state.table, exc_info=True)
            return {"sample_rows": []}
        if isinstance(res, (Refusal, DbError)):
            reason = res.reason if isinstance(res, Refusal) else res.message
            logging.getLogger(__name__).warning("sample refused: %s", reason)
            return {"sample_rows": []}
        return {"sample_rows": res["rows"]}

    async def generate(state: SqlToolState) -> dict:
        """LLM выдаёт батч SQL-кандидатов под остаток бюджета, прошлые ошибки
        и запросы, вернувшие 0 строк."""
        remaining = max_queries - state.executed_count
        # remaining >= 1 гарантируется маршрутизацией (в generate не попадаем при
        # исчерпанном бюджете); max(1, …) — просто страховка.
        n = max(1, min(candidates_per_round, remaining))
        candidates = await _generate_candidates(
            model,
            [SystemMessage(GENERATE_SYS), HumanMessage(generate_prompt(state, n))],
            n,
        )
        return {"candidates": candidates, "round": state.round + 1}

    async def execute(state: SqlToolState) -> dict:
        """Гоняет кандидатов раунда параллельно; копит попытки и счётчик.

        Уже выполнявшиеся SQL повторно не гоняем и бюджет на них НЕ
        списываем; завершаемость цикла держит предел раундов в
        after_execute. return_exceptions: сбой одного кандидата не роняет
        остальных — он станет неуспешной попыткой в _attempt.
        """
        table = state.table
        tried = {a["sql"] for a in state.attempts}
        unique = [s for s in dict.fromkeys(state.candidates) if s not in tried]
        results = await asyncio.gather(
            *(executor.run_select(sql, table) for sql in unique),
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

    async def judge(state: SqlToolState) -> dict:
        """LLM: достаточно ли строк для ответа. Без строк — need_more без вызова."""
        rows = ok_rows(state.attempts)
        if not rows:
            return {"verdict": Verdict.NEED_MORE}
        verdict = await _judge_verdict(
            model,
            [
                SystemMessage(JUDGE_SYS),
                HumanMessage(
                    f"Вопрос: {state.question}\n"
                    + rows_context(state.attempts)
                ),
            ],
        )
        return {
            "verdict": Verdict.SUFFICIENT if verdict.sufficient else Verdict.NEED_MORE,
            "judge_reason": verdict.reason,
        }

    async def summarize(state: SqlToolState) -> dict:
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
            last = next((a["error"] for a in reversed(state.attempts) if a["error"]),
                        "неизвестная ошибка")
            return {"status": Status.ERROR, "answer": f"Не удалось выполнить SQL: {last}"}
        reply = await model.ainvoke(
            [
                SystemMessage(SUMMARIZE_SYS),
                HumanMessage(
                    f"Вопрос: {state.question}\n"
                    + rows_context(state.attempts)
                ),
            ]
        )
        return {"status": Status.OK, "answer": str(reply.content)}

    def after_generate(state: SqlToolState) -> str:
        """Пустой батч кандидатов → summarize (иначе цикл без прогресса)."""
        return "execute" if state.candidates else "summarize"

    def after_execute(state: SqlToolState) -> str:
        """Бюджет или предел раундов исчерпан → summarize; иначе judge.

        Предел раундов — страховка завершаемости: батчи из дубликатов или
        отказов guardrails бюджет не двигают.
        """
        if state.executed_count >= max_queries or state.round >= max_queries:
            return "summarize"
        return "judge"

    def after_judge(state: SqlToolState) -> str:
        """Судья доволен → summarize; иначе → ещё раунд generate."""
        return "summarize" if state.verdict == Verdict.SUFFICIENT else "generate"

    g = StateGraph(SqlToolState, input_schema=SqlToolInput)
    g.add_node("sample", sample)
    g.add_node("generate", generate)
    g.add_node("execute", execute)
    g.add_node("judge", judge)
    g.add_node("summarize", summarize)
    g.add_edge(START, "sample")
    g.add_edge("sample", "generate")
    g.add_conditional_edges("generate", after_generate, ["execute", "summarize"])
    g.add_conditional_edges("execute", after_execute, ["judge", "summarize"])
    g.add_conditional_edges("judge", after_judge, ["generate", "summarize"])
    g.add_edge("summarize", END)
    return g.compile()
