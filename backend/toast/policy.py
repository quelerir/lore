"""Policy gate: PII-таблицы требуют решения authorization ДО выполнения SQL.

Итерация 1 — детерминированный block-list (БД живая, график отпусков
реальный). Полноценный authz-gate — итерация 3 спеки.
"""

PII_TABLES = frozenset({"toast_tbl_9c6dcab0dfdd486cfddf"})  # график отпусков 2026

POLICY_REFUSAL = (
    "Отказ policy gate: таблица содержит персональные данные "
    "(график отпусков). Нужно решение policy/authorization; "
    "без него SQL не выполняется."
)


def check_policy(sql: str) -> str | None:
    low = sql.lower()
    for table in PII_TABLES:
        if table in low:
            return POLICY_REFUSAL
    return None
