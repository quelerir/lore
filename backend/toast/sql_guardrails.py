"""SQL-guardrails: разрешён только SELECT ровно к одной переданной таблице.

Валидация по AST (sqlglot, диалект postgres), а не по regex: проверяются ВСЕ
упомянутые в запросе таблицы, включая comma-join и подзапросы. Строковые
литералы с «опасными» словами и точками с запятой ложных отказов не дают.
CTE разрешены: алиасы WITH исключаются из проверки таблиц.
Вторая линия обороны — read-only транзакция в исполнителе.
"""

import re

import sqlglot
from sqlglot import exp

TOAST_TABLE_RE = re.compile(r"^toast_tbl_[0-9a-f]{20}$")
_BARE = re.compile(r"(?i)\b(from|join)\s+(toast_tbl_[0-9a-f]{20})\b")

ALLOWED_SCHEMA = "splitter_toast"

# Денайлист функций (сравнение по нормализации: lower + без подчёркиваний,
# по префиксу — накрывает семейства вида query_to_xml*/dblink_*/pg_read_*).
# Классы: исполнение SQL-текста (query_to_xml, xmltable, dblink), чтение
# файлов/каталогов сервера, large objects, DoS/управление сессиями, GUC.
_FORBIDDEN_FUNC_PREFIXES = (
    "querytoxml", "xmltable", "dblink", "pgread", "pgls", "pgstatfile",
    "loimport", "loexport", "pgsleep", "pgterminatebackend",
    "pgcancelbackend", "currentsetting", "setconfig",
)


def _forbidden_func(stmt: exp.Expression) -> str | None:
    """Имя первой запрещённой функции в выражении, иначе None."""
    for f in stmt.find_all(exp.Func):
        name = f.name if isinstance(f, exp.Anonymous) else f.sql_name()
        normalized = name.lower().replace("_", "")
        if normalized.startswith(_FORBIDDEN_FUNC_PREFIXES):
            return name
    return None


def qualify_table(sql: str, table: str) -> str:
    """Дописывает splitter_toast. к голому имени переданной таблицы."""
    return _BARE.sub(
        lambda m: f"{m.group(1)} {ALLOWED_SCHEMA}.{m.group(2)}"
        if m.group(2) == table
        else m.group(0),
        sql,
    )


def validate_select(sql: str, table: str) -> str | None:
    """None — можно выполнять; иначе текст отказа для LLM."""
    if not TOAST_TABLE_RE.match(table):
        return f"Отказ: недопустимое имя таблицы '{table}'."
    try:
        statements = [s for s in sqlglot.parse(sql, read="postgres") if s is not None]
    except sqlglot.errors.ParseError as e:
        return f"Отказ: не удалось разобрать SQL ({e})."
    if len(statements) != 1:
        return "Отказ: разрешена ровно одна SQL-команда."
    stmt = statements[0]
    if not isinstance(stmt, (exp.Select, exp.SetOperation)):
        return "Отказ: разрешён только SELECT."
    for sel in stmt.find_all(exp.Select):
        if sel.args.get("into"):
            return "Отказ: SELECT INTO запрещён (только чтение)."
        if sel.args.get("locks"):
            return "Отказ: FOR UPDATE/SHARE запрещён (только чтение)."
    if bad_func := _forbidden_func(stmt):
        return f"Отказ: функция {bad_func} запрещена."
    # Ссылки без схемы на алиасы CTE — не таблицы; всё со схемой проверяем.
    ctes = {cte.alias_or_name for cte in stmt.find_all(exp.CTE)}
    tables = [
        t for t in stmt.find_all(exp.Table)
        if t.db or t.name not in ctes
    ]
    if not tables:
        return "Отказ: не вижу FROM с явной таблицей."
    for t in tables:
        if t.db.lower() != ALLOWED_SCHEMA or t.name != table:
            found = ".".join(p for p in (t.db, t.name) if p) or t.sql()
            return (
                f"Отказ: разрешена только таблица {ALLOWED_SCHEMA}.{table}, "
                f"найдено {found}."
            )
    return None
