"""Быстрый режим: чистый langgraph с фиксированным маршрутом и одним
циклом инструментов.

START → model(+tools) ─┬─ tool_calls → tools → final(без tools) → END
                       └─ нет вызова ────────────────────────────→ END

Ровно один проход через инструменты — маршрут не может зациклиться,
что важно для маленьких моделей.
"""

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, SystemMessage
from langchain_core.tools import BaseTool
from langgraph.graph import END, START, MessagesState, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.prebuilt import ToolNode

from agents.base import SYSTEM_PROMPT


def build_fast_agent(
    model: BaseChatModel, tools: list[BaseTool]
) -> CompiledStateGraph:
    try:
        model_with_tools = model.bind_tools(tools)
    except NotImplementedError:
        # Фейковые модели в тестах не умеют bind_tools, но сами
        # возвращают tool_calls в ответах.
        model_with_tools = model

    async def call_model(state: MessagesState) -> MessagesState:
        messages = [SystemMessage(SYSTEM_PROMPT), *state["messages"]]
        # astream: если модель отвечает сразу (без инструмента), это финальный
        # ответ и его токены должны дойти до UI через stream_mode="messages".
        response: AIMessage | None = None
        async for chunk in model_with_tools.astream(messages):
            response = chunk if response is None else response + chunk
        return {"messages": [response]}

    async def call_final(state: MessagesState) -> MessagesState:
        # Финальный ответ после инструментов — модель без tools, чтобы
        # маршрут гарантированно завершился.
        messages = [SystemMessage(SYSTEM_PROMPT), *state["messages"]]
        response: AIMessage | None = None
        async for chunk in model.astream(messages):
            response = chunk if response is None else response + chunk
        return {"messages": [response]}

    def route_after_model(state: MessagesState) -> str:
        last = state["messages"][-1]
        return "tools" if getattr(last, "tool_calls", None) else END

    graph = StateGraph(MessagesState)
    graph.add_node("model", call_model)
    graph.add_node("tools", ToolNode(tools))
    graph.add_node("final", call_final)
    graph.add_edge(START, "model")
    graph.add_conditional_edges("model", route_after_model, ["tools", END])
    graph.add_edge("tools", "final")
    graph.add_edge("final", END)
    return graph.compile()
