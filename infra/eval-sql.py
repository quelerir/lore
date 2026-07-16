#!/usr/bin/env python3
"""Eval SQL-инструмента на захардкоженных чанках/таблицах из отчёта.

Нужны TOAST_DB_* (host/port/user/password/name) и OPENROUTER_API_KEY в
окружении. Диагностика, не CI-гейт: exit 0 всегда.

Запуск: cd backend && uv run python ../infra/eval-sql.py
"""

import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from agents.base import build_sql_model  # noqa: E402
from config import build_dsn, get_settings  # noqa: E402
from toast.executor import PgExecutor  # noqa: E402
from toast.sql_tool import run_sql_tool  # noqa: E402


def _toast_dsn() -> str | None:
    host = os.environ.get("TOAST_DB_HOST")
    user = os.environ.get("TOAST_DB_USER")
    password = os.environ.get("TOAST_DB_PASSWORD")
    name = os.environ.get("TOAST_DB_NAME")
    if not all([host, user, password, name]):
        return None
    port = int(os.environ.get("TOAST_DB_PORT", "5432"))
    return build_dsn("postgresql", user, password, host, port, name)

# desc_full — реальный display_text из sqls/second_sql.csv (сокращённо).
CASES = [
    {
        "id": "sql-legal-001",
        "question": "Какие ФИО у юристов и их должности?",
        "chunk_id": "e6d9b7ff6df20d08b9c1c543760530ce",
        "table": "toast_tbl_ec48a6d52d16ab405f95",
        "desc_vector": "юристы Adventum, ФИО и должности",
        "desc_full": "Table payload: Лист1 A15:R16. Реестр юристов: ФИО, должность, email.",
        "must_any": [["каневск"]],
        "must_not": ["ирин"],
    },
    {
        "id": "sql-grade-001",
        "question": "Какие компетенции базовой матрицы отдела контекстной рекламы?",
        "chunk_id": "grade-base",
        "table": "toast_tbl_17a7241d0a976f287103",
        "desc_vector": "грейды контекстной рекламы, компетенции",
        "desc_full": "Table payload: Junior-Group head. Базовая матрица компетенций.",
        "must_any": [["компетен", "kpi", "отчет", "анализ"]],
        "must_not": [],
    },
]


def check(answer: str, case: dict) -> tuple[bool, list[str]]:
    low = answer.lower()
    problems = []
    for group in case["must_any"]:
        if not any(n.lower() in low for n in group):
            problems.append(f"нет ни одного из {group}")
    for banned in case["must_not"]:
        if banned.lower() in low:
            problems.append(f"запрещённое вхождение: {banned!r}")
    return (not problems, problems)


async def main() -> None:
    # Гейт по env ДО get_settings(): в голой оболочке нет обязательных полей
    # стека (CHAINLIT_DB_*/JWT), и Settings() упал бы раньше SKIP.
    dsn = _toast_dsn()
    if not dsn or not os.environ.get("OPENROUTER_API_KEY"):
        print("SKIP: нужны TOAST_DB_* и OPENROUTER_API_KEY")
        return
    s = get_settings()
    exe = PgExecutor(dsn)
    model = build_sql_model()
    passed = 0
    try:
        for case in CASES:
            inputs = {k: case[k] for k in
                      ("question", "chunk_id", "table", "desc_vector", "desc_full")}
            out = await run_sql_tool(inputs, model, exe,
                                     s.sql_max_queries, s.sql_candidates_per_round)
            ok, problems = check(out.get("answer", ""), case)
            passed += ok
            print(f"[{'PASS' if ok else 'FAIL'}] {case['id']} status={out['status']} "
                  f"rows={out['rows_used']}")
            if not ok:
                print("      проблемы:", problems)
                print("      ответ:", out.get("answer", "")[:300])
    finally:
        await exe.close()
    print(f"\nEVAL SQL: {passed}/{len(CASES)} passed")


if __name__ == "__main__":
    asyncio.run(main())
    sys.exit(0)
