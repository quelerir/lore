from langchain_core.language_models.chat_models import BaseChatModel
from langgraph.graph.state import CompiledStateGraph

from agents.base import PROFILE_TO_MODE, Mode, build_model
from agents.deep import build_deep_agent
from agents.fast import build_fast_agent
from agents.tools import make_tools
from toast.port import ToastStorePort

__all__ = ["Mode", "PROFILE_TO_MODE", "build_agent", "build_model"]


def build_agent(
    mode: Mode,
    model: BaseChatModel | None = None,
    store: ToastStorePort | None = None,
) -> CompiledStateGraph:
    if model is None:
        model = build_model()
    tools = make_tools(model, store)
    if mode is Mode.DEEP:
        return build_deep_agent(model, tools)
    return build_fast_agent(model, tools)
