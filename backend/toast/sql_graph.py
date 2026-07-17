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
from typing import Any, TypedDict

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from pydantic import BaseModel, Field

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
    "(без markdown, без пояснений). Только SELECT, только эта таблица. "
    "Каждый элемент — ровно один запрос SELECT (WITH разрешён), "
    "без точки с запятой."
)
JUDGE_SYS = (
    "Ты оцениваешь, достаточно ли полученных строк, чтобы ответить на "
    "вопрос. Верни sufficient=true/false и короткую причину reason — "
    "почему строк недостаточно (она попадёт генератору SQL)."
)
SUMMARIZE_SYS = (
    "Ответь на вопрос пользователя СТРОГО по предоставленным строкам таблицы. "
    "Не выдумывай. Если данных недостаточно — так и скажи. Кратко, по-русски."
)
NO_DATA_MSG = "В данных таблицы нет ответа на этот вопрос."
NO_CANDIDATES_MSG = "Модель не вернула ни одного SQL-кандидата."
JUDGE_ROWS_CAP = 30  # сколько строк отдаём в контекст судьи/суммаризатора
JUDGE_CONTEXT_CHARS = 8_000  # кап сериализованных строк для судьи/суммаризатора
SAMPLE_LIMIT = 5  # строк-примеров для промпта generate
SAMPLE_CONTEXT_CHARS = 2_000  # кап сериализованных примеров в промпте

# «sufficient» с границами слова: в «insufficient» и «NEED_MORE...» не матчится.
_SUFFICIENT_RE = re.compile(r"\bsufficient\b")


class SqlCandidates(BaseModel):
    """Батч SQL-кандидатов — схема structured output узла generate."""

    candidates: list[str]


class JudgeVerdict(BaseModel):
    """Вердикт судьи: достаточно ли строк и почему нет (structured output)."""

    sufficient: bool
    reason: str = ""


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


class Attempt(TypedDict):
    """Одна попытка выполнения SQL-кандидата (успех или отказ/ошибка)."""

    sql: str
    ok: bool
    error: str | None
    rows: list[dict[str, Any]]
    row_count: int
    truncated: bool


class SqlToolInput(BaseModel):
    """Входные поля инструмента (форма ввода в Studio)."""

    question: str
    chunk_id: str
    table: str
    desc_vector: str
    desc_full: str


class SqlToolState(SqlToolInput):
    """Состояние графа: вход + аккумуляторы с дефолтами.

    Дефолты полей заменяют бывший узел init: langgraph применяет их сам,
    «забытая инициализация» перестала существовать как класс ошибки
    (инцидент KeyError: 'candidates' в TypedDict-версии). Узлы возвращают
    dict-апдейты, langgraph сливает их в состояние.
    """

    sample_rows: list[dict] = Field(default_factory=list)
    candidates: list[str] = Field(default_factory=list)
    round: int = 0
    executed_count: int = 0
    attempts: list[Attempt] = Field(default_factory=list)
    verdict: str = ""
    judge_reason: str = ""
    answer: str = ""
    status: str = ""


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


def _attempt(sql: str, res: Any) -> Attempt:
    """Собирает запись попытки из результата исполнителя.

    Исполнитель возвращает str при отказе guardrails / ошибке SQL, иначе
    SelectResult. Исключение приходит из gather(return_exceptions=True) —
    неожиданный сбой исполнителя не должен ронять весь граф, но обязан
    попасть в лог: иначе инфраструктурные проблемы (DNS, сеть до БД) видны
    только в UI как текст неуспешной попытки.
    """
    if isinstance(res, BaseException):
        logging.getLogger(__name__).warning(
            "SQL attempt failed with exception: %r (sql=%.120s)", res, sql
        )
        res = f"Ошибка выполнения: {res!r}"
    if isinstance(res, str):
        return {"sql": sql, "ok": False, "error": res,
                "rows": [], "row_count": 0, "truncated": False}
    return {"sql": sql, "ok": True, "error": None,
            "rows": res["rows"], "row_count": res["row_count"],
            "truncated": res["truncated"]}


def _ok_rows(attempts: list[Attempt]) -> list[dict]:
    """Плоский список строк из всех успешных попыток (для судьи/суммаризатора)."""
    out: list[dict] = []
    for a in attempts:
        if a["ok"]:
            out.extend(a["rows"])
    return out


def _rows_context(attempts: list[Attempt], rows: list[dict]) -> str:
    """Строки для контекста LLM с честной пометкой о неполноте выборки.

    Два капа: не больше JUDGE_ROWS_CAP строк и не больше ~JUDGE_CONTEXT_CHARS
    символов JSON (одна «широкая» строка не должна раздувать контекст).
    Хотя бы одна строка отдаётся всегда.
    """
    shown: list[dict] = []
    size = 0
    for row in rows[:JUDGE_ROWS_CAP]:
        piece = json.dumps(row, ensure_ascii=False, default=str)
        if shown and size + len(piece) > JUDGE_CONTEXT_CHARS:
            break
        shown.append(row)
        size += len(piece)
    note = f"Показано строк: {len(shown)} из {len(rows)}"
    if any(a["truncated"] for a in attempts):
        note += " (результат SQL дополнительно усечён лимитом исполнителя)"
    return f"{note}.\nСтроки: {json.dumps(shown, ensure_ascii=False, default=str)}"


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
        if isinstance(res, str):
            logging.getLogger(__name__).warning("sample refused: %s", res)
            return {"sample_rows": []}
        return {"sample_rows": res["rows"]}

    async def generate(state: SqlToolState) -> dict:
        """LLM выдаёт батч SQL-кандидатов под остаток бюджета, прошлые ошибки
        и запросы, вернувшие 0 строк."""
        remaining = max_queries - state.executed_count
        # remaining >= 1 гарантируется маршрутизацией (в generate не попадаем при
        # исчерпанном бюджете); max(1, …) — просто страховка.
        n = max(1, min(candidates_per_round, remaining))
        errors = [a["error"] for a in state.attempts if not a["ok"] and a["error"]]
        empty = [a["sql"] for a in state.attempts if a["ok"] and a["row_count"] == 0]
        prompt = (
            f"Вопрос: {state.question}\n"
            f"Таблица: {state.table}\n"
            f"Описание (кратко): {state.desc_vector}\n"
            f"Описание (полно): {state.desc_full}\n"
            f"Нужно вернуть до {n} разных SELECT."
        )
        if errors:
            prompt += "\n\nПрошлые ошибки SQL (исправь):\n" + "\n".join(errors[-3:])
        if empty:
            prompt += (
                "\n\nЭти запросы выполнились, но вернули 0 строк — "
                "нужен другой подход:\n" + "\n".join(empty[-3:])
            )
        if state.judge_reason:
            prompt += (
                "\n\nПрошлый результат отклонён судьёй: "
                f"{state.judge_reason} — построй запрос иначе."
            )
        if state.sample_rows:
            sample_json = json.dumps(
                state.sample_rows, ensure_ascii=False, default=str
            )[:SAMPLE_CONTEXT_CHARS]
            prompt += (
                f"\n\nПримеры строк таблицы (до {SAMPLE_LIMIT}, реальные "
                f"имена колонок и формат значений):\n{sample_json}"
            )
        # tag internal: служебные токены не показываем пользователю в UI.
        candidates = await _generate_candidates(
            model, [SystemMessage(GENERATE_SYS), HumanMessage(prompt)], n
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
        new = [_attempt(sql, res) for sql, res in zip(unique, results)]
        # Бюджет — только SQL, дошедшие до БД: отказ guardrails существует,
        # чтобы модель ПЕРЕПИСАЛА запрос, и не должен съедать попытку.
        executed = sum(
            1 for a in new
            if a["ok"] or not (a["error"] or "").startswith("Отказ:")
        )
        return {
            "attempts": state.attempts + new,
            "executed_count": state.executed_count + executed,
        }

    async def judge(state: SqlToolState) -> dict:
        """LLM: достаточно ли строк для ответа. Без строк — need_more без вызова."""
        rows = _ok_rows(state.attempts)
        if not rows:
            return {"verdict": "need_more"}
        verdict = await _judge_verdict(
            model,
            [
                SystemMessage(JUDGE_SYS),
                HumanMessage(
                    f"Вопрос: {state.question}\n"
                    + _rows_context(state.attempts, rows)
                ),
            ],
        )
        return {
            "verdict": "sufficient" if verdict.sufficient else "need_more",
            "judge_reason": verdict.reason,
        }

    async def summarize(state: SqlToolState) -> dict:
        """Терминальный узел: ответ по строкам, либо статус no_data / error."""
        rows = _ok_rows(state.attempts)
        if not rows:
            if not state.attempts:
                # Сюда попадаем только из after_generate при пустом батче.
                return {"status": "error",
                        "answer": f"Не удалось выполнить SQL: {NO_CANDIDATES_MSG}"}
            # Хоть один успешный (но пустой) SELECT → данных нет; иначе все
            # попытки — ошибки БД → техническая ошибка.
            if any(a["ok"] for a in state.attempts):
                return {"status": "no_data", "answer": NO_DATA_MSG}
            last = next((a["error"] for a in reversed(state.attempts) if a["error"]),
                        "неизвестная ошибка")
            return {"status": "error", "answer": f"Не удалось выполнить SQL: {last}"}
        reply = await model.ainvoke(
            [
                SystemMessage(SUMMARIZE_SYS),
                HumanMessage(
                    f"Вопрос: {state.question}\n"
                    + _rows_context(state.attempts, rows)
                ),
            ]
        )
        return {"status": "ok", "answer": str(reply.content)}

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
        return "summarize" if state.verdict == "sufficient" else "generate"

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
