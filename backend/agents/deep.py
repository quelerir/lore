from deepagents import create_deep_agent
from langchain_core.language_models.chat_models import BaseChatModel
from langgraph.graph.state import CompiledStateGraph

from agents.base import DEEP_PROMPT
from toast.port import ToastStorePort
from toast.tools import make_tools


def build_deep_agent(model: BaseChatModel, store: ToastStorePort) -> CompiledStateGraph:
    return create_deep_agent(
        tools=make_tools(store),
        system_prompt=DEEP_PROMPT,
        model=model,
    )
