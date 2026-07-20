"""Юниты eval-харнесса: без сети и без LangSmith, только фейки."""

import pytest
from langchain_openai import ChatOpenAI

import config
from evals.models import build_eval_model


def _settings(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    config.get_settings.cache_clear()
    return config.get_settings()


def test_build_eval_model_openrouter(monkeypatch):
    model = build_eval_model("openai/gpt-4o", _settings(monkeypatch))
    assert isinstance(model, ChatOpenAI)
    assert model.model_name == "openai/gpt-4o"
    assert model.temperature == 0.0


def test_build_eval_model_requires_key(monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    config.get_settings.cache_clear()
    with pytest.raises(RuntimeError, match="OPENROUTER_API_KEY"):
        build_eval_model("openai/gpt-4o", config.get_settings())
