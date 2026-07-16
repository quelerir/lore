from deepagents import create_deep_agent
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.tools import BaseTool
from langgraph.graph.state import CompiledStateGraph

from agents.base import DEEP_PROMPT


def build_deep_agent(
    model: BaseChatModel, tools: list[BaseTool]
) -> CompiledStateGraph:
    return create_deep_agent(
        tools=tools,
        system_prompt=DEEP_PROMPT,
        model=model,
    )
