import os

from deepagents import create_deep_agent
from langchain_ollama import ChatOllama
from langgraph.graph.state import CompiledStateGraph

SYSTEM_PROMPT: str = (
    "You are the datacraft assistant. Answer the user's questions clearly "
    "and concisely."
)


def build_agent() -> CompiledStateGraph:
    """Build a tool-less deepagents agent backed by Ollama.

    Reads OLLAMA_MODEL and OLLAMA_BASE_URL from the environment. Returns a
    compiled LangGraph agent; run it with `.astream(...)` (never `.ainvoke`).
    """
    model = ChatOllama(
        model=os.environ.get("OLLAMA_MODEL", "gemma3"),
        base_url=os.environ.get("OLLAMA_BASE_URL", "http://ollama:11434"),
    )
    return create_deep_agent(
        tools=[],
        system_prompt=SYSTEM_PROMPT,
        model=model,
    )
