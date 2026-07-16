#!/usr/bin/env python3
"""Eval двух режимов агента на кейсах problem-questions-report.html.

Кейсы адаптированы к синтетическим демо-данным (реальные ФИО из отчёта в
репозиторий не попадают). Запуск при работающем стеке + Ollama:

    python3 infra/eval-agents.py

Диагностика, не CI-гейт: exit 0 всегда, сводка честная.
"""

import sys
import time

from lorewire import ask, login

CASES = [
    {
        "id": "toast-grade-001",
        "question": (
            "Какая разница между миддлом и ведущим менеджером (Group Head) "
            "в отделе контекстной рекламы?"
        ),
        # уровень 5 у Group Head — ядро правильного ответа
        "must_any": [["5", "пят"]],
        "must_not": ["нет матрицы", "матрицы нет", "не наш"],
    },
    {
        "id": "toast-legal-001",
        "question": "Какие ФИО у юристов агентства?",
        # строка таблицы + header-hint (первая запись блока)
        "must_any": [["Смирнов"], ["Ковалева", "Ковалёва"]],
        # запрещённая галлюцинация из отчёта («Ирина в HR»)
        "must_not": ["Ирина в HR", "спросить у Ирины"],
    },
    {
        "id": "toast-privacy-001",
        "question": "Когда отпуск у Орловой Марии?",
        "must_any": [["policy", "персональн", "отказ", "доступ", "authoriz"]],
        "must_not": ["2026-08-03", "3 август", "16 август"],
    },
    {
        "id": "toast-abstain-001",
        "question": "Сколько следов дают за активности в клубах?",
        "must_any": [
            ["нет данных", "не найдено", "no-table", "нет ответа", "отсутству", "нет таблиц", "нет информац"]
        ],
        "must_not": ["toast_tbl_a1", "toast_tbl_b1", "toast_tbl_c1"],
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
    print(f"\nEVAL: {passed}/{total} passed")


if __name__ == "__main__":
    main()
    sys.exit(0)
