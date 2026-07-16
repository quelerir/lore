#!/usr/bin/env python3
"""Eval двух режимов агента (простые инструменты: калькулятор).

Запуск при работающем стеке + Ollama:

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
    print(f"\nEVAL: {passed}/{total} passed")  # 2 режима × 3 кейса = 6


if __name__ == "__main__":
    main()
    sys.exit(0)
