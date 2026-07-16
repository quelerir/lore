import asyncio

import pytest
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.language_models.fake_chat_models import FakeListChatModel
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.outputs import ChatGeneration, ChatResult


class ScriptedChatModel(BaseChatModel):
    """Отдаёт заранее заданные AIMessage (с tool_calls) по одному на вызов.

    Не реализует _stream: BaseChatModel.astream отдаст ответ одним чанком —
    именно так tool_calls доезжают до графа без потерь.
    """

    responses: list

    @property
    def _llm_type(self) -> str:
        return "scripted"

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        return ChatResult(
            generations=[ChatGeneration(message=self.responses.pop(0))]
        )

    def bind_tools(self, tools, **kwargs):
        return self  # tool_calls зашиты в responses

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
