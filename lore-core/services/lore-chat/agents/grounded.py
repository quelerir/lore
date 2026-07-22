"""Grounded retrieval graph — the fast profile.

Runs the retrieval pipeline's three stages as explicit LangGraph nodes:

    START → retrieve → sql → summarize → END

so the answer is grounded end-to-end (no chat agent re-paraphrasing it) and the
debug trace shows each stage as its own node. The nodes call the SAME
``RetrievalPipeline`` methods that ``pipeline.answer`` composes — one source of
truth. ``summarize`` emits the final ``AIMessage`` (streamed to the user) and the
resolved citations in the graph state.
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


def _question(messages: list[BaseMessage]) -> str:
    """The current user question = the last human message."""
    for m in reversed(messages):
        if getattr(m, "type", None) == "human":
            return str(m.content)
    return str(messages[-1].content) if messages else ""


def build_grounded_agent(pipeline: Any) -> CompiledStateGraph:
    async def retrieve(state: GroundedState) -> dict:
        groups, resolution, table_candidates, degradations = await pipeline.retrieve(
            _question(state["messages"])
        )
        return {
            "groups": groups,
            "resolution": resolution,
            "table_candidates": table_candidates,
            "degradations": degradations,
        }

    async def sql(state: GroundedState) -> dict:
        results, degr = await pipeline.run_table_sql(
            _question(state["messages"]), state.get("table_candidates", [])
        )
        return {"sql_results": results, "degradations": state.get("degradations", []) + degr}

    async def summarize(state: GroundedState) -> dict:
        decision, citations = await pipeline.summarize(
            _question(state["messages"]),
            state.get("groups", []),
            state["resolution"],
            state.get("sql_results", []),
        )
        answer = decision.answer or "В базе знаний нет ответа на этот вопрос."
        return {"messages": [AIMessage(content=answer)], "citations": citations}

    g = StateGraph(GroundedState)
    g.add_node("retrieve", retrieve)
    g.add_node("sql", sql)
    g.add_node("summarize", summarize)
    g.add_edge(START, "retrieve")
    g.add_edge("retrieve", "sql")
    g.add_edge("sql", "summarize")
    g.add_edge("summarize", END)
    return g.compile()
