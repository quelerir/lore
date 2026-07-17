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


def test_attempt_substeps_slices_new_attempts():
    from sql_demo import attempt_substeps

    old = _attempt(sql="SELECT old", rows=[{"a": 1}], row_count=1)
    ok = _attempt(sql="SELECT fresh", rows=[{"a": 2}], row_count=1)
    bad = _attempt(sql="SELECT bad", ok=False, error="Ошибка SQL: x")
    subs = attempt_substeps(
        {"attempts": [old, ok, bad], "executed_count": 3}, seen_attempts=1,
    )
    assert [c["name"] for c in subs] == ["Попытка 2", "Попытка 3"]
    assert subs[0]["input"] == "SELECT fresh"
    assert subs[0]["is_error"] is False
    assert subs[1]["is_error"] is True
    assert "Ошибка SQL: x" in subs[1]["output"]


def test_attempt_substeps_preview_truncates_rows():
    from sql_demo import ROWS_PREVIEW, attempt_substeps

    rows = [{"n": i} for i in range(ROWS_PREVIEW + 3)]
    att = _attempt(rows=rows, row_count=len(rows))
    subs = attempt_substeps({"attempts": [att]}, seen_attempts=0)
    out = subs[0]["output"]
    assert f"всего строк: {ROWS_PREVIEW + 3}" in out
    assert '"n": 0' in out


def test_attempt_substeps_zero_rows_and_empty_delta():
    from sql_demo import attempt_substeps

    empty = _attempt(rows=[], row_count=0)
    subs = attempt_substeps({"attempts": [empty]}, seen_attempts=0)
    assert subs[0]["output"] == "0 строк"

    assert attempt_substeps({}, seen_attempts=0) == []


def test_node_step_id_finds_last_matching_step():
    from types import SimpleNamespace

    from sql_demo import node_step_id

    class FakeHandler:
        # dict сохраняет порядок создания — как handler.steps в Chainlit.
        steps = {
            "r1": SimpleNamespace(name="execute", id="step-round-1"),
            "r2": SimpleNamespace(name="generate", id="step-gen"),
            "r3": SimpleNamespace(name="execute", id="step-round-2"),
        }

    assert node_step_id(FakeHandler(), "execute") == "step-round-2"
    assert node_step_id(FakeHandler(), "judge") is None
    assert node_step_id(object(), "execute") is None  # нет handler.steps
