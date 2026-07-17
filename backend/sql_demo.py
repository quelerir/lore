"""Демо-режим «SQL (демо)»: конвертация хода SQL-графа в Chainlit-шаги.

Граф (toast/) про Chainlit не знает: он отдаёт события через
astream(stream_mode=["updates", "messages", "values"]), а этот модуль
превращает их в cl.Step (стадии + вложенные попытки) и стрим токенов ответа.
Живёт только в демо-ветке; в прод не мержится.
"""

import json
from typing import TypedDict

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
