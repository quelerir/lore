"""Grounded retrieval graph for LangGraph Studio (dev-only).

Sibling of ``graph.py`` (which serves only the toast SQL tool). This serves the
FULL grounded pipeline — neo4j_retrieve → toast_sql → summarize — so Studio shows
the whole answer path, with the deep per-stage spans (neo4j fanout, the nested
toast SQL graph) in the self-hosted LangSmith trace.

The graph itself is built once in ``lore-core/services/lore-chat/studio_graph.py``
(single source of truth, shared with the chat's factory). This wrapper only puts
that backend on ``sys.path`` so Studio can import it from studio/'s own venv, the
same way ``graph.py`` reaches ``config``/``toast``. Backend deps (lore_retrieval,
neo4j, langchain-ollama, langsmith) are declared in ``pyproject.toml``.
"""
import os
import sys

_BACKEND = os.path.join(os.path.dirname(__file__), "..", "lore-core", "services", "lore-chat")
if _BACKEND not in sys.path:
    sys.path.insert(0, _BACKEND)

from studio_graph import graph  # noqa: E402,F401  (compiled grounded graph)
