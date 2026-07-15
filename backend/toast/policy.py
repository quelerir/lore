"""Policy gate: PII-таблицы требуют решения authorization ДО выполнения SQL."""

PII_TABLES = frozenset({"toast_tbl_e1b2c3d4e5f6a7b8c9d0"})  # график отпусков


def check_policy(sql: str) -> str | None:
    low = sql.lower()
    for table in PII_TABLES:
        if table in low:
            return (
                "Отказ policy gate: таблица содержит персональные данные "
                "(график отпусков). Нужно решение policy/authorization; "
                "без него SQL не выполняется."
            )
    return None
