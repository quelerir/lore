"""Grounded retrieval graph — the fast profile.

Runs the retrieval pipeline as an explicit LangGraph diamond — two answer
variants that rejoin at summarize (matches the neo4j spec's parallel text/table
lanes → top-level arbitration):

    START → neo4j_retrieve ─┬→ neo4j_only ──→ summarize → END
                            └→ toast_sql ────↗

    · variant 1 (pure neo4j): text evidence via ``neo4j_only`` to summarize;
    · variant 2 (neo4j → SQL): SQL over the discovered table candidate;
    · summarize is a JOIN — waits for both, merges the evidence, emits the final
      ``AIMessage`` + citations.

    ``neo4j_only`` and ``toast_sql`` run in parallel (same supersteps), so both
    reach summarize together and it fires ONCE. A direct neo4j_retrieve→summarize
    edge would be shorter than the SQL branch and fire summarize early/twice — the
    equal-length passthrough is what makes the join correct.

The nodes call the SAME ``RetrievalPipeline`` methods that ``pipeline.answer``
composes — one source of truth. When no table candidate is discovered, toast_sql
records an explicit ``no_candidate`` outcome (honest empty, not silent).

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
    variant1_detail: dict
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

    async def neo4j_only(state: GroundedState) -> dict:
        # Variant 1: answer straight from neo4j text evidence (no SQL). A light
        # passthrough that marks the pure-neo4j branch AND keeps both variants the
        # same length so summarize joins them in one superstep.
        groups = state.get("groups", [])
        return {"variant1_detail": {"variant": "pure_neo4j", "context_groups": len(groups)}}

    async def toast_sql(state: GroundedState) -> dict:
        candidates = state.get("table_candidates", [])
        if not candidates:
            # Spec-aligned: SQL runs only when a table candidate is discovered
            # (стр. 56-57: "table discovery does not imply SQL execution"). Make
            # the empty branch HONEST — an explicit "no candidate" outcome rather
            # than a silent empty, so the trace shows the SQL path was reached.
            return {
                "sql_results": [],
                "sql_detail": [
                    {
                        "status": "no_candidate",
                        "note": "таблица-кандидат в neo4j не найдена — SQL не запускался",
                    }
                ],
            }
        results, degr = await pipeline.run_table_sql(
            _question(state["messages"]), candidates
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
        try:
            decision, citations = await pipeline.summarize(
                _question(state["messages"]),
                state.get("groups", []),
                state["resolution"],
                state.get("sql_results", []),
            )
        except Exception as exc:
            # Answer generation failed (model 403/timeout/etc). Degrade VISIBLY —
            # a shown message + a degradation flag — instead of crashing the turn.
            return {
                "messages": [
                    AIMessage(
                        content="⚠️ Не удалось сгенерировать ответ — сервис модели "
                        "сейчас недоступен. Попробуйте ещё раз позже."
                    )
                ],
                "citations": [],
                "degradations": state.get("degradations", []) + ["answer_generation_failed"],
                "answer_detail": {"error": type(exc).__name__, "detail": repr(exc)},
            }
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
    g.add_node("neo4j_only", neo4j_only)
    g.add_node("toast_sql", toast_sql)
    g.add_node("summarize", summarize)
    g.add_edge(START, "neo4j_retrieve")
    # Diamond: neo4j_retrieve forks into two equal-length branches that rejoin at
    # summarize. Equal length => both land in the same superstep => summarize is a
    # true join (fires once with BOTH evidence sources).
    g.add_edge("neo4j_retrieve", "neo4j_only")  # variant 1: pure neo4j
    g.add_edge("neo4j_retrieve", "toast_sql")   # variant 2: neo4j → SQL
    g.add_edge("neo4j_only", "summarize")
    g.add_edge("toast_sql", "summarize")
    g.add_edge("summarize", END)
    return g.compile()
