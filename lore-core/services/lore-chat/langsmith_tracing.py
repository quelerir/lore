"""LangSmith tracing for the grounded graph — service-side only.

LangSmith-specific code lives here (lore-chat already depends on ``langsmith``);
the pure ``lore-retrieval`` package stays vendor-free and is traced solely through
its existing ``tracer=`` seam (``observability.Tracer`` protocol). Two pieces:

* ``enable_langsmith`` — push the self-hosted endpoint/key from config into the
  process env so LangGraph/LangChain auto-tracing (the retrieve→sql→summarize node
  graph, the nested toast SQL graph, ChatOpenAI calls) reports to OUR instance.
* ``LangSmithTracer`` — turns each pipeline stage ``record(stage, payload)`` into a
  short child span, nested under the current node run via langsmith's contextvars,
  so text_fanout / table_discover / table_sql / arbitration / cite and their error
  details are visible inside the trace.
"""
import os


def enable_langsmith(project: str = "lore-grounded-debug") -> str | None:
    """Enable tracing to the self-hosted LangSmith. Reads endpoint/key from the
    process env (``langgraph.json``'s ``env`` file populates them for Studio; the
    eval harness exports the same vars) and pins TRACING + a dedicated project.
    Returns the endpoint on success, ``None`` when creds are missing — the graph
    still runs, just untraced (and we never leak to the public
    api.smith.langchain.com). Deliberately env-only: no lore-chat config import,
    so this debug seam stays free of the chainlit/JWT settings."""
    endpoint = os.environ.get("LANGSMITH_ENDPOINT")
    api_key = os.environ.get("LANGSMITH_API_KEY")
    if not (endpoint and api_key):
        return None
    os.environ["LANGSMITH_TRACING"] = "true"
    os.environ["LANGSMITH_PROJECT"] = project
    return endpoint


class LangSmithTracer:
    """``observability.Tracer`` impl routing each stage record to a LangSmith span.

    A stage record is a point-event emitted AFTER the stage runs, so each becomes a
    short span carrying the payload (counts, degraded flags, error + detail) rather
    than a duration-wrapping span. Tracing must never break the pipeline, so every
    failure here is swallowed."""

    def record(self, stage: str, payload: dict) -> None:
        try:
            from langsmith import trace

            data = dict(payload)
            with trace(name=stage, run_type="tool", inputs=data) as run:
                run.add_outputs(data)
        except Exception:
            return
