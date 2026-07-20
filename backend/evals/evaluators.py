"""Оценщики eval-харнесса.

Детерминированные эвристики над проекцией run_sql_tool + LLM-judge
корректности с фиксированной моделью-судьёй. langsmith биндит аргументы
оценщиков по имени параметра (outputs / inputs / reference_outputs).
"""


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
