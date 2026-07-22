"""Grounded retrieval graph — the fast profile.

Runs the retrieval pipeline's three stages as explicit LangGraph nodes:

    START → neo4j_retrieve → toast_sql → summarize → END

so the answer is grounded end-to-end (no chat agent re-paraphrasing it) and the
debug trace shows each stage as its own node. The nodes call the SAME
``RetrievalPipeline`` methods that ``pipeline.answer`` composes — one source of
truth. ``summarize`` emits the final ``AIMessage`` (streamed to the user) and the
resolved citations in the graph state.

Each node also writes a compact ``*_detail`` object into the state so a viewer
(LangGraph Studio's node inspector, or any state dump) sees what happened at a
glance — counts, table candidates, per-table SQL status/rows — without needing
the LangSmith trace. The deep per-stage spans (neo4j fanout, the nested toast SQL
graph) still live in the LangSmith trace.
"""
from typing import Annotated, Any, TypedDict

from langchain_core.messages import AIMessage, BaseMessage
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.graph.state import CompiledStateGraph


class GroundedState(TypedDict, total=False):
    messages: Annotated[list[BaseMessage], add_messages]
    groups: list
    resolution: Any
    table_candidates: list
    sql_results: list
    citations: list
    degradations: list
    # Compact, human-readable per-node summaries (for Studio / state dumps).
    neo4j_detail: dict
    sql_detail: list
    answer_detail: dict


def _question(messages: list[BaseMessage]) -> str:
    """The current user question = the last human message."""
    for m in reversed(messages):
        if getattr(m, "type", None) == "human":
            return str(m.content)
    return str(messages[-1].content) if messages else ""


def _status(value: Any) -> str:
    return str(getattr(value, "value", value))


def build_grounded_agent(pipeline: Any) -> CompiledStateGraph:
    async def neo4j_retrieve(state: GroundedState) -> dict:
        groups, resolution, table_candidates, degradations = await pipeline.retrieve(
            _question(state["messages"])
        )
        return {
            "groups": groups,
            "resolution": resolution,
            "table_candidates": table_candidates,
            "degradations": degradations,
            "neo4j_detail": {
                "context_groups": len(groups),
                "resolved_evidence": len(resolution.resolved),
                "rejected_evidence": len(resolution.rejected),
                "table_candidates": [
                    {"table": tc.payload_id, "chunk": tc.chunk_id, "score": round(tc.score, 4)}
                    for tc in table_candidates
                ],
                "degradations": degradations,
            },
        }

    async def toast_sql(state: GroundedState) -> dict:
        results, degr = await pipeline.run_table_sql(
            _question(state["messages"]), state.get("table_candidates", [])
        )
        return {
            "sql_results": results,
            "degradations": state.get("degradations", []) + degr,
            "sql_detail": [
                {
                    "table": r.payload_id,
                    "chunk": r.chunk_id,
                    "status": _status(r.status),
                    "rows": len(r.rows),
                    "answer": r.answer_summary,
                    "error": r.error,
                }
                for r in results
            ],
        }

    async def summarize(state: GroundedState) -> dict:
        decision, citations = await pipeline.summarize(
            _question(state["messages"]),
            state.get("groups", []),
            state["resolution"],
            state.get("sql_results", []),
        )
        answer = decision.answer or "В базе знаний нет ответа на этот вопрос."
        return {
            "messages": [AIMessage(content=answer)],
            "citations": citations,
            "answer_detail": {
                "note": decision.note,
                "used_sql_payloads": list(decision.used_sql_payload_ids),
                "citations": len(citations),
            },
        }

    g = StateGraph(GroundedState)
    g.add_node("neo4j_retrieve", neo4j_retrieve)
    g.add_node("toast_sql", toast_sql)
    g.add_node("summarize", summarize)
    g.add_edge(START, "neo4j_retrieve")
    g.add_edge("neo4j_retrieve", "toast_sql")
    g.add_edge("toast_sql", "summarize")
    g.add_edge("summarize", END)
    return g.compile()
