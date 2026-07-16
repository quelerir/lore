"""SQL-guardrails: разрешён только SELECT ровно к одной переданной таблице."""

import re

TOAST_TABLE_RE = re.compile(r"^toast_tbl_[0-9a-f]{20}$")
_FORBIDDEN = re.compile(
    r"\b(insert|update|delete|drop|alter|create|truncate|grant|revoke|"
    r"copy|vacuum|call|do)\b",
    re.IGNORECASE,
)
# Цели FROM/JOIN: schema.table (alias.column проверке не подлежит).
_RELATION = re.compile(
    r"\b(?:from|join)\s+([a-zA-Z_]\w*)\s*\.\s*([a-zA-Z_]\w*)", re.IGNORECASE
)
_BARE = re.compile(r"(?i)\b(from|join)\s+(toast_tbl_[0-9a-f]{20})\b")


def qualify_table(sql: str, table: str) -> str:
    """Дописывает splitter_toast. к голому имени переданной таблицы."""
    return _BARE.sub(
        lambda m: f"{m.group(1)} splitter_toast.{m.group(2)}"
        if m.group(2) == table
        else m.group(0),
        sql,
    )


def validate_select(sql: str, table: str) -> str | None:
    """None — можно выполнять; иначе текст отказа для LLM."""
    if not TOAST_TABLE_RE.match(table):
        return f"Отказ: недопустимое имя таблицы '{table}'."
    stripped = sql.strip().rstrip(";").strip()
    if ";" in stripped:
        return "Отказ: разрешена ровно одна SQL-команда."
    if not re.match(r"^select\b", stripped, re.IGNORECASE):
        return "Отказ: разрешён только SELECT."
    if _FORBIDDEN.search(stripped):
        return "Отказ: запрещённая операция (только чтение)."
    relations = _RELATION.findall(stripped)
    if not relations:
        return "Отказ: не вижу FROM с явной таблицей."
    for schema, name in relations:
        if schema.lower() != "splitter_toast" or name != table:
            return (
                f"Отказ: разрешена только таблица splitter_toast.{table}, "
                f"найдено {schema}.{name}."
            )
    return None
