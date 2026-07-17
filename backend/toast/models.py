"""Все типы SQL-инструмента: состояние графа, structured output, результаты.

Единое место объявления моделей. Контракты между слоями выражены типами, а
не строковыми префиксами: результат исполнителя различается isinstance'ом
(SelectResult | Refusal | DbError) — от Refusal зависит подсчёт бюджета.
"""

import logging
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, TypedDict

from pydantic import BaseModel, Field


class Status(StrEnum):
    """Итог прогона инструмента (внешний контракт: ok / no_data / error)."""

    OK = "ok"
    NO_DATA = "no_data"
    ERROR = "error"


class Verdict(StrEnum):
    """Вердикт судьи в состоянии графа."""

    SUFFICIENT = "sufficient"
    NEED_MORE = "need_more"


class SelectResult(TypedDict):
    """Результат успешного SELECT (строки уже приведены к JSON-совместимым типам)."""

    columns: list[str]
    rows: list[dict[str, Any]]
    row_count: int
    truncated: bool


@dataclass
class Refusal:
    """Отказ guardrails: SQL не дошёл до БД — бюджет НЕ тратится."""

    reason: str


@dataclass
class DbError:
    """Ошибка БД/сети/таймаута: SQL дошёл до БД — бюджет потрачен."""

    message: str


class Attempt(TypedDict):
    """Одна попытка выполнения SQL-кандидата (успех или отказ/ошибка)."""

    sql: str
    ok: bool
    error: str | None
    rows: list[dict[str, Any]]
    row_count: int
    truncated: bool


class SqlCandidates(BaseModel):
    """Батч SQL-кандидатов — схема structured output узла generate."""

    candidates: list[str]


class JudgeVerdict(BaseModel):
    """Вердикт судьи: достаточно ли строк и почему нет (structured output)."""

    sufficient: bool
    reason: str = ""


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


def make_attempt(sql: str, res: Any) -> Attempt:
    """Запись попытки из результата исполнителя.

    Принимает SelectResult | Refusal | DbError, а также исключение из
    gather(return_exceptions=True) — неожиданный сбой исполнителя не должен
    ронять весь граф, но обязан попасть в лог: иначе инфраструктурные
    проблемы (DNS, сеть до БД) видны только в UI как текст попытки.
    """
    if isinstance(res, BaseException):
        logging.getLogger(__name__).warning(
            "SQL attempt failed with exception: %r (sql=%.120s)", res, sql
        )
        res = DbError(f"Ошибка выполнения: {res!r}")
    if isinstance(res, Refusal):
        return {"sql": sql, "ok": False, "error": res.reason,
                "rows": [], "row_count": 0, "truncated": False}
    if isinstance(res, DbError):
        return {"sql": sql, "ok": False, "error": res.message,
                "rows": [], "row_count": 0, "truncated": False}
    return {"sql": sql, "ok": True, "error": None,
            "rows": res["rows"], "row_count": res["row_count"],
            "truncated": res["truncated"]}


def ok_rows(attempts: list[Attempt]) -> list[dict]:
    """Плоский список строк из всех успешных попыток."""
    out: list[dict] = []
    for a in attempts:
        if a["ok"]:
            out.extend(a["rows"])
    return out
