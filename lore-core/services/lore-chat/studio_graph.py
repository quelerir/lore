"""LangGraph Studio export of the grounded graph (dev-only, host).

``langgraph dev`` imports ``graph`` from here to serve Studio: a visual view of
the START→retrieve→sql→summarize graph where you type a user message and inspect
each node's state. Runs against the SAME live backends as the chat (Neo4j +
bge-m3/Ollama + lore_core Postgres + toast SQL + OpenRouter) and the SAME env
(``langgraph.json`` points at the shared root ``.env``).

``graph`` is a COMPILED graph object, not a factory: langgraph-cli only accepts a
factory whose params are typed ``ServerRuntime``/``RunnableConfig``, so a plain
compiled object is the simplest contract. Building the pipeline here is cheap and
connectionless (drivers/clients connect lazily on first invoke), so importing this
module needs no event loop and no live VPN.

A ``LangSmithTracer`` is injected so the internal pipeline stages (text_fanout,
table_discover, table_sql, arbitration, cite) — which live inside the retrieve/sql
nodes — also surface as spans alongside the auto-traced node graph and the nested
toast SQL graph.

Launch (host, VPN up, Ollama up, LANGSMITH_*/creds in root .env):

    cd lore-core/services/lore-chat
    uv run --with 'langgraph-cli[inmem]' langgraph dev
"""
import os

# Studio always runs on the host. The shared .env carries the CONTAINER's Ollama
# URL (host.docker.internal, correct for the chat container) which does not
# resolve on the host. Force a host-reachable Ollama unless the process env
# already pins a non-container URL (an explicit override we respect). Setting the
# process env wins over the .env FILE value that pydantic would otherwise read,
# and must happen before the first get_settings(). Cleanest permanent fix: drop
# OLLAMA_BASE_URL from .env — then the host uses the localhost default and the
# container uses docker-compose's ${OLLAMA_BASE_URL:-host.docker.internal}.
_ollama = os.environ.get("OLLAMA_BASE_URL", "")
if not _ollama or "host.docker.internal" in _ollama:
    os.environ["OLLAMA_BASE_URL"] = "http://localhost:11434"

import importlib.util  # noqa: E402

from langsmith_tracing import LangSmithTracer, enable_langsmith  # noqa: E402
from retrieval import _build_pipeline  # noqa: E402


def _load_build_grounded_agent():
    """Load agents/grounded.py directly, bypassing agents/__init__.py (which pulls
    deepagents/fast/base — absent in the Studio venv). grounded.py itself only
    needs langchain_core + langgraph."""
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "agents", "grounded.py")
    spec = importlib.util.spec_from_file_location("_grounded_studio", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.build_grounded_agent


build_grounded_agent = _load_build_grounded_agent()

# Point auto-tracing at our self-hosted LangSmith before the graph runs.
enable_langsmith("lore-grounded-debug")

# Compiled grounded graph served by Studio.
graph = build_grounded_agent(_build_pipeline(tracer=LangSmithTracer()))
