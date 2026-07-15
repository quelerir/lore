"""SQL-guardrails по контракту problem-questions-report.html."""

import re

ALLOWED_SCHEMAS = frozenset({"lore_core", "splitter_toast", "information_schema"})
TOAST_TABLE_RE = re.compile(r"^toast_tbl_[0-9a-f]{20}$")
_FORBIDDEN = re.compile(
    r"\b(insert|update|delete|drop|alter|create|truncate|grant|revoke|copy|vacuum|call|do)\b",
    re.IGNORECASE,
)
# Проверяем только цели FROM/JOIN: alias.column (например b.column_2) —
# не имя схемы и проверке не подлежит.
_RELATION = re.compile(
    r"\b(?:from|join)\s+([a-zA-Z_][\w]*)\s*\.\s*([a-zA-Z_][\w]*)", re.IGNORECASE
)


def validate_select(sql: str) -> str | None:
    """None — можно выполнять; иначе текст отказа для LLM."""
    stripped = sql.strip().rstrip(";").strip()
    if ";" in stripped:
        return "Отказ: разрешена ровно одна SQL-команда."
    if not re.match(r"^select\b", stripped, re.IGNORECASE):
        return "Отказ: разрешён только SELECT."
    if _FORBIDDEN.search(stripped):
        return "Отказ: запрещённая операция (только чтение)."
    for schema, name in _RELATION.findall(stripped):
        s = schema.lower()
        if s not in ALLOWED_SCHEMAS:
            return f"Отказ: схема '{schema}' вне allowlist ({', '.join(sorted(ALLOWED_SCHEMAS))})."
        if s == "splitter_toast" and not TOAST_TABLE_RE.match(name.lower()):
            return f"Отказ: имя таблицы '{name}' не соответствует шаблону toast_tbl_<20 hex>."
    return None
