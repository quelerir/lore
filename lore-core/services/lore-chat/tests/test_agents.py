import asyncio

import pytest
from langchain_core.language_models.fake_chat_models import FakeListChatModel
from langchain_core.messages import AIMessage, HumanMessage

from fakes import ScriptedChatModel

from agents import Mode, PROFILE_TO_MODE, build_agent
from agents.fast import build_fast_agent
from agents.tools import calculator, evaluate_expression, make_tools


def test_profile_mapping():
    assert PROFILE_TO_MODE["fast"] is Mode.FAST
    assert PROFILE_TO_MODE["deep"] is Mode.DEEP


def test_build_agent_both_modes():
    model = FakeListChatModel(responses=["x"])
    assert build_agent(Mode.FAST, model=model) is not None
    assert build_agent(Mode.DEEP, model=model) is not None


# --- калькулятор -------------------------------------------------------------


def test_calculator_arithmetic():
    assert calculator.invoke({"expression": "(17 + 3) * 4 / 2"}) == "40"
    assert calculator.invoke({"expression": "2 ** 10"}) == "1024"
    assert calculator.invoke({"expression": "-5 + 3"}) == "-2"
    assert calculator.invoke({"expression": "7 / 2"}) == "3.5"


def test_calculator_rejects_evil():
    assert "Ошибка" in calculator.invoke({"expression": "__import__('os')"})
    assert "Ошибка" in calculator.invoke({"expression": "1 if True else 2"})
    assert "Ошибка" in calculator.invoke({"expression": "1/0"})
    assert "Ошибка" in calculator.invoke({"expression": "2 ** 999999"})
    # степень в лимите, но результат астрономический — режем по размеру
    assert "Ошибка" in calculator.invoke({"expression": "(2 ** 10000) ** 10000"})


def test_evaluate_expression_pure():
    assert evaluate_expression("100 // 7") == 14
    with pytest.raises((ValueError, SyntaxError)):
        evaluate_expression("open('/etc/passwd')")


# --- fast-граф ---------------------------------------------------------------


def test_fast_route_direct_answer():
    """Модель отвечает без инструмента — маршрут model → END."""
    model = FakeListChatModel(responses=["Прямой ответ"])
    agent = build_fast_agent(model, make_tools())
    out = asyncio.run(agent.ainvoke({"messages": [HumanMessage("привет")]}))
    assert out["messages"][-1].content == "Прямой ответ"


def test_fast_route_with_tool_call():
    """Модель зовёт калькулятор — маршрут model → tools → final → END."""
    model = ScriptedChatModel(
        responses=[
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "calculator",
                        "args": {"expression": "17 * 23"},
                        "id": "call-1",
                        "type": "tool_call",
                    }
                ],
            ),
            AIMessage(content="Получилось 391."),
        ]
    )
    agent = build_fast_agent(model, make_tools())
    out = asyncio.run(agent.ainvoke({"messages": [HumanMessage("сколько 17*23?")]}))
    # ToolNode отработал: в истории есть ToolMessage с результатом 391
    tool_outputs = [
        m.content for m in out["messages"] if m.__class__.__name__ == "ToolMessage"
    ]
    assert tool_outputs == ["391"]
    assert out["messages"][-1].content == "Получилось 391."


# --- инструменты --------------------------------------------------------------


def test_make_tools_calculator_only_when_retrieval_unconfigured(monkeypatch):
    import retrieval

    monkeypatch.setattr(retrieval, "retrieval_configured", lambda: False)
    assert [t.name for t in make_tools()] == ["calculator"]


def test_make_tools_adds_knowledge_base_when_configured(monkeypatch):
    import retrieval

    monkeypatch.setattr(retrieval, "retrieval_configured", lambda: True)
    names = [t.name for t in make_tools()]
    assert names == ["calculator", "knowledge_base"]


# --- model provider -----------------------------------------------------------


def test_build_model_provider_switch(monkeypatch):
    from langchain_ollama import ChatOllama
    from langchain_openai import ChatOpenAI

    from agents.base import build_model
    from config import get_settings

    monkeypatch.setenv("MODEL_PROVIDER", "openrouter")
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    get_settings.cache_clear()
    model = build_model()
    assert isinstance(model, ChatOpenAI)
    assert "openrouter.ai" in str(model.openai_api_base)

    monkeypatch.setenv("MODEL_PROVIDER", "ollama")
    get_settings.cache_clear()
    assert isinstance(build_model(), ChatOllama)


def test_build_model_openrouter_requires_key(monkeypatch):
    from agents.base import build_model
    from config import get_settings

    monkeypatch.setenv("MODEL_PROVIDER", "openrouter")
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    get_settings.cache_clear()
    with pytest.raises(RuntimeError):
        build_model()


def test_build_sql_model_openrouter(monkeypatch):
    from langchain_openai import ChatOpenAI

    from agents.base import build_sql_model
    from config import get_settings

    monkeypatch.setenv("OPENROUTER_API_KEY", "k")
    monkeypatch.setenv("SQL_MODEL", "anthropic/claude-sonnet-4.6")
    monkeypatch.delenv("LLM_MAX_TOKENS", raising=False)
    get_settings.cache_clear()
    m = build_sql_model()
    assert isinstance(m, ChatOpenAI)
    assert "openrouter.ai" in str(m.openai_api_base)
    # По умолчанию лимита нет: max_tokens не задаём, extra_body пуст.
    assert m.max_tokens is None
    assert m.extra_body is None


def test_build_sql_model_respects_max_tokens(monkeypatch):
    from langchain_openai import ChatOpenAI

    from agents.base import build_sql_model
    from config import get_settings

    monkeypatch.setenv("OPENROUTER_API_KEY", "k")
    monkeypatch.setenv("SQL_MODEL", "anthropic/claude-sonnet-4.6")
    monkeypatch.setenv("LLM_MAX_TOKENS", "2000")
    get_settings.cache_clear()
    m = build_sql_model()
    assert isinstance(m, ChatOpenAI)
    # Заданный лимит идёт и в max_tokens, и в extra_body (OpenRouter игнорирует
    # max_completion_tokens, читает родной max_tokens из JSON запроса).
    assert m.max_tokens == 2000
    assert m.extra_body == {"max_tokens": 2000}


def test_build_sql_model_empty_max_tokens_means_unset(monkeypatch):
    from langchain_openai import ChatOpenAI

    from agents.base import build_sql_model
    from config import get_settings

    monkeypatch.setenv("OPENROUTER_API_KEY", "k")
    monkeypatch.setenv("SQL_MODEL", "anthropic/claude-sonnet-4.6")
    # Пустая строка из compose (${LLM_MAX_TOKENS:-}) трактуется как «не задан».
    monkeypatch.setenv("LLM_MAX_TOKENS", "")
    get_settings.cache_clear()
    m = build_sql_model()
    assert isinstance(m, ChatOpenAI)
    assert m.max_tokens is None
    assert m.extra_body is None


def test_build_sql_model_requires_key(monkeypatch):
    import pytest

    from agents.base import build_sql_model
    from config import get_settings

    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    get_settings.cache_clear()
    with pytest.raises(RuntimeError):
        build_sql_model()
