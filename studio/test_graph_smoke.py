import importlib
import sys

import pytest

ENV = {
    "OPENROUTER_API_KEY": "k",
    "TOAST_DB_HOST": "localhost",
    "TOAST_DB_USER": "u",
    "TOAST_DB_PASSWORD": "p",
    "TOAST_DB_NAME": "db",
}


def _reload_graph(monkeypatch, env):
    for k in ("OPENROUTER_API_KEY", "TOAST_DB_HOST", "TOAST_DB_USER",
              "TOAST_DB_PASSWORD", "TOAST_DB_NAME", "TOAST_DB_PORT"):
        monkeypatch.delenv(k, raising=False)
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    sys.modules.pop("graph", None)
    return importlib.import_module("graph")


def test_graph_compiles_with_env(monkeypatch):
    mod = _reload_graph(monkeypatch, ENV)
    # graph скомпилирован без I/O (пул asyncpg ленивый)
    assert mod.graph is not None
    assert hasattr(mod.graph, "ainvoke")


def test_missing_env_raises(monkeypatch):
    with pytest.raises(RuntimeError):
        _reload_graph(monkeypatch, {"OPENROUTER_API_KEY": "k"})  # нет TOAST_DB_*
