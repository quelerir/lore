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
