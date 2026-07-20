"""Оценщики eval-харнесса.

Детерминированные эвристики над проекцией run_sql_tool + LLM-judge
корректности с фиксированной моделью-судьёй. langsmith биндит аргументы
оценщиков по имени параметра (outputs / inputs / reference_outputs).
"""

import logging
import re
from collections.abc import Callable

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel

logger = logging.getLogger(__name__)

_CORRECT_RE = re.compile(r"\bcorrect\b")  # \b: в "incorrect" не матчится

_JUDGE_SYS = (
    "Ты — придирчивый оценщик. Ответ считается верным, только если он "
    "содержит те же факты, что и эталон (числа, ФИО, значения совпадают по "
    "сути). Расхождение в формулировке допустимо, расхождение в фактах — нет."
)


class JudgeCorrectness(BaseModel):
    correct: bool
    reason: str = ""


def executes_ok(outputs: dict) -> dict:
    """Хоть один SQL дошёл до БД без ошибки."""
    ok = any(a["ok"] for a in outputs.get("sql_attempts", []))
    return {"key": "executes_ok", "score": int(ok)}


def status_ok(outputs: dict) -> dict:
    """Инструмент завершился статусом ok (а не no_data / error)."""
    return {"key": "status_ok", "score": int(outputs.get("status") == "ok")}


def has_rows(outputs: dict) -> dict:
    """Итоговый ответ опирался хотя бы на одну строку."""
    return {"key": "has_rows", "score": int(outputs.get("rows_used", 0) > 0)}


async def judge_correctness(
    model: BaseChatModel, question: str, answer: str, reference: str
) -> JudgeCorrectness:
    """Вердикт судьи; structured output с текстовым фолбэком (как toast/llm.py)."""
    messages = [
        SystemMessage(_JUDGE_SYS),
        HumanMessage(
            f"Вопрос: {question}\nОтвет инструмента: {answer}\nЭталон: {reference}\n"
            "Верен ли ответ инструмента относительно эталона?"
        ),
    ]
    try:
        structured = model.with_structured_output(
            JudgeCorrectness, method="function_calling"
        )
        return await structured.ainvoke(messages)
    except Exception as e:
        logger.debug("judge: structured недоступен (%r), текстовый фолбэк", e)
        reply = await model.ainvoke(messages)
        text = str(reply.content).lower()
        ok = bool(_CORRECT_RE.search(text))
        return JudgeCorrectness(correct=ok, reason="")


def make_answer_correct(judge_model: BaseChatModel) -> Callable:
    """Async-оценщик корректности с фиксированной моделью-судьёй."""

    async def answer_correct(
        inputs: dict, outputs: dict, reference_outputs: dict
    ) -> dict:
        verdict = await judge_correctness(
            judge_model,
            inputs.get("question", ""),
            outputs.get("answer", ""),
            reference_outputs.get("reference_answer", ""),
        )
        return {
            "key": "answer_correct",
            "score": int(verdict.correct),
            "comment": verdict.reason,
        }

    return answer_correct
