"""LLM-обвязка SQL-инструмента: structured output с обязательными фолбэками.

OpenRouter-модели поддерживают function calling неровно, а фейки тестов не
поддерживают вовсе — поэтому у каждого structured-вызова есть текстовый
фолбэк, а причина фолбэка логируется (NotImplementedError ожидаем → debug,
остальное → warning: транзиентные ошибки не должны молча удваивать
латентность).
"""

import json
import logging
import re

import sqlglot
from langchain_core.language_models.chat_models import BaseChatModel
from sqlglot import exp as sql_exp

from toast.models import JudgeVerdict, SqlCandidates

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


async def generate_candidates(model: BaseChatModel, messages: list,
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


async def judge_verdict(model: BaseChatModel, messages: list) -> JudgeVerdict:
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
