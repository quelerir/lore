#!/usr/bin/env python3
"""Eval двух режимов агента (калькулятор + таблицы документов).

Запуск при работающем стеке (нужны OPENROUTER_API_KEY и
TOAST_DATABASE_URL в окружении backend):

    python3 infra/eval-agents.py

Диагностика, не CI-гейт: exit 0 всегда, сводка честная.
"""

import sys
import time

from lorewire import ask, login

CASES = [
    {
        "id": "calc-001",
        "question": "Сколько будет 17 * 23? Посчитай точно.",
        "must_any": [["391"]],
        "must_not": [],
    },
    {
        "id": "calc-002",
        "question": "Посчитай выражение (100 - 36) / 8 и назови результат.",
        "must_any": [["8"]],
        "must_not": [],
    },
    {
        "id": "chat-001",
        "question": "Столица Франции? Ответь одним словом.",
        "must_any": [["париж", "paris"]],
        "must_not": [],
    },
    {
        # toast-grade-001: multi-table JOIN по _splitter_source_row
        "id": "toast-grade-001",
        "question": (
            "Какая разница между миддлом и ведущим менеджером (Group Head) "
            "в отделе контекстной рекламы?"
        ),
        "must_any": [
            ["5"],  # уровень Group Head почти по всему профилю
            ["конкурентн", "менторств", "маркетплейс", "коллтрекинг", "google ads"],
        ],
        "must_not": ["матрицы нет", "нет формальной грейдовой"],
    },
    {
        # toast-mobile-001: discovery файла + агрегация одной таблицы
        "id": "toast-mobile-001",
        "question": "Чем занимается отдел mobile marketing? Что в него входит?",
        "must_any": [
            ["appsflyer", "adjust", "appmetrica", "mmp"],
            ["in-app", "источник", "закупк"],
        ],
        "must_not": ["нет данных об отделе", "документа с описанием отдела нет"],
    },
    {
        # toast-abstain-001: no-table-answer, не выдумывать SQL
        "id": "toast-abstain-001",
        "question": (
            "Сколько следов дают за активности и как получить "
            "фирменную толстовку A.Store?"
        ),
        "must_any": [["нет", "не найд", "отсутств", "no-table"]],
        "must_not": [],
    },
]


def check(answer: str, case: dict) -> tuple[bool, list[str]]:
    low = answer.lower()
    problems = []
    for group in case["must_any"]:
        if not any(needle.lower() in low for needle in group):
            problems.append(f"нет ни одного из {group}")
    for banned in case["must_not"]:
        if banned.lower() in low:
            problems.append(f"запрещённое вхождение: {banned!r}")
    return (not problems, problems)


def main() -> None:
    cookie = login()
    print("SSO ok\n")
    passed = total = 0
    for profile in ("fast", "deep"):
        for case in CASES:
            total += 1
            started = time.time()
            try:
                answer = ask(cookie, profile, case["question"])
            except Exception as e:  # noqa: BLE001 — диагностический скрипт
                answer = f"<ошибка прогона: {e}>"
            ok, problems = check(answer, case)
            passed += ok
            took = time.time() - started
            status = "PASS" if ok else "FAIL"
            print(f"[{status}] {profile:4s} {case['id']} ({took:.0f}s)")
            if not ok:
                print(f"       проблемы: {problems}")
                print(f"       ответ: {answer[:300]!r}")
    print(f"\nEVAL: {passed}/{total} passed")  # 2 режима × 6 кейсов = 12


if __name__ == "__main__":
    main()
    sys.exit(0)
