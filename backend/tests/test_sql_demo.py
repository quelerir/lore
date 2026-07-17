"""Тесты демо-режима «SQL (демо)»: конфиг, профиль, конвертация шагов."""

import asyncio
import importlib


def _app():
    return importlib.import_module("app")


def test_sql_demo_settings_defaults():
    from config import get_settings

    s = get_settings()
    assert s.sql_demo_table.startswith("toast_tbl_")
    assert s.sql_demo_desc_vector
    assert s.sql_demo_desc_full


def test_sql_profile_requires_creds(monkeypatch):
    from config import get_settings

    app = _app()
    monkeypatch.delenv("TOAST_DB_HOST", raising=False)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    get_settings.cache_clear()
    assert [p.name for p in asyncio.run(app.chat_profiles())] == ["fast", "deep"]


def test_sql_profile_registered_with_creds(monkeypatch):
    from config import get_settings

    app = _app()
    for key, value in {
        "TOAST_DB_HOST": "h", "TOAST_DB_USER": "u",
        "TOAST_DB_PASSWORD": "p", "TOAST_DB_NAME": "d",
        "OPENROUTER_API_KEY": "k",
    }.items():
        monkeypatch.setenv(key, value)
    get_settings.cache_clear()
    assert [p.name for p in asyncio.run(app.chat_profiles())] == [
        "fast", "deep", "sql",
    ]


def _attempt(sql="SELECT 1", ok=True, error=None, rows=None, row_count=0):
    rows = rows if rows is not None else []
    return {"sql": sql, "ok": ok, "error": error, "rows": rows,
            "row_count": row_count, "truncated": False}


def test_step_payload_generate():
    from sql_demo import step_payload

    desc = step_payload(
        "generate", {"candidates": ["SELECT a", "SELECT b"], "round": 2},
        round_no=2, seen_attempts=0,
    )
    assert desc["name"] == "Генерация SQL — раунд 2"
    assert "SELECT a" in desc["output"] and "SELECT b" in desc["output"]
    assert desc["children"] == []


def test_step_payload_execute_slices_new_attempts():
    from sql_demo import step_payload

    old = _attempt(sql="SELECT old", rows=[{"a": 1}], row_count=1)
    ok = _attempt(sql="SELECT fresh", rows=[{"a": 2}], row_count=1)
    bad = _attempt(sql="SELECT bad", ok=False, error="Ошибка SQL: x")
    desc = step_payload(
        "execute", {"attempts": [old, ok, bad], "executed_count": 3},
        round_no=2, seen_attempts=1,
    )
    assert desc["name"] == "Выполнение SQL — раунд 2"
    assert [c["name"] for c in desc["children"]] == ["Попытка 2", "Попытка 3"]
    assert desc["children"][0]["input"] == "SELECT fresh"
    assert desc["children"][0]["is_error"] is False
    assert desc["children"][1]["is_error"] is True
    assert "Ошибка SQL: x" in desc["children"][1]["output"]


def test_step_payload_preview_truncates_rows():
    from sql_demo import ROWS_PREVIEW, step_payload

    rows = [{"n": i} for i in range(ROWS_PREVIEW + 3)]
    att = _attempt(rows=rows, row_count=len(rows))
    desc = step_payload("execute", {"attempts": [att]},
                        round_no=1, seen_attempts=0)
    out = desc["children"][0]["output"]
    assert f"всего строк: {ROWS_PREVIEW + 3}" in out
    assert '"n": 0' in out


def test_step_payload_zero_rows_and_judge_and_skips():
    from sql_demo import step_payload

    empty = _attempt(rows=[], row_count=0)
    desc = step_payload("execute", {"attempts": [empty]},
                        round_no=1, seen_attempts=0)
    assert desc["children"][0]["output"] == "0 строк"

    judge = step_payload("judge", {"verdict": "need_more"},
                         round_no=1, seen_attempts=0)
    assert judge["name"] == "Оценка достаточности"
    assert judge["output"] == "need_more"

    assert step_payload("init", {}, round_no=0, seen_attempts=0) is None
    assert step_payload("summarize", {"answer": "x"},
                        round_no=1, seen_attempts=0) is None
