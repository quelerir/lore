import logging

from langchain_core.language_models.chat_models import BaseChatModel
from langgraph.graph.state import CompiledStateGraph

from agents.base import PROFILE_TO_MODE, Mode, build_model
from agents.deep import build_deep_agent
from agents.fast import build_fast_agent
from agents.tools import make_tools

__all__ = ["Mode", "PROFILE_TO_MODE", "build_agent", "build_model"]


def build_agent(
    mode: Mode,
    model: BaseChatModel | None = None,
) -> CompiledStateGraph:
    if mode is Mode.DEEP:
        return build_deep_agent(model or build_model(), make_tools())
    # FAST = the grounded retrieval graph (retrieve → sql → summarize) when the
    # knowledge base is configured; otherwise the plain calculator tool graph.
    try:
        from retrieval import get_pipeline, retrieval_configured

        if retrieval_configured():
            from agents.grounded import build_grounded_agent

            return build_grounded_agent(get_pipeline())
    except Exception:
        # Retrieval IS configured but the grounded graph failed to build. Do NOT
        # swallow this: a silent fall-through downgrades the whole (cached) session
        # to the optional-tool fast agent, so mandatory grounding is lost until the
        # chat is restarted. Log loudly so the real cause is visible; we still fall
        # back to a usable agent below.
        logging.exception(
            "grounded agent build failed despite retrieval being configured — "
            "falling back to the optional-tool fast agent; grounding is NOT "
            "guaranteed for this session"
        )
    return build_fast_agent(model or build_model(), make_tools())
