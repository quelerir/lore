"""Bind the toast SQL graph behind the retrieval pipeline's SqlRunner seam.

Stage 2 of the spec (SQL generation + execution) wired to stage 1's output. The
pipeline's table lane hands us ``SqlRequest{question, payload_id, chunk_id}``.
``payload_id`` IS the physical table name (from the chunk's trusted
``payload_refs`` — never from an LLM). We load the chunk's description, run the
toast SQL graph (sample→generate→execute→judge→summarize) against the TOAST DB,
and map its typed result to the pipeline's ``SQLResult``.

Lives in lore-chat (it imports ``toast/``) and is injected into
``build_live_pipeline`` via ``retrieval.py`` — keeping ``lore-retrieval`` free of
any lore-chat/toast import (dependency direction stays package←service).
"""
from lore_retrieval.adapters.context_postgres import PostgresChunkContextLoader
from lore_retrieval.adapters.sql_callable import CallableSqlRunner
from lore_retrieval.config import get_settings as _retrieval_settings
from lore_retrieval.contracts import SQLResult, SQLStatus, SqlRequest

from agents.base import build_sql_model
from config import get_settings as _chat_settings
from toast.executor import PgExecutor
from toast.models import ok_rows
from toast.sql_graph import build_sql_graph

# toast Status (ok/no_data/error) -> pipeline SQLStatus.
_STATUS_MAP = {
    "ok": SQLStatus.success,
    "no_data": SQLStatus.empty,
    "error": SQLStatus.execution_error,
}

_graph = None
_loader: PostgresChunkContextLoader | None = None


def toast_configured() -> bool:
    """True when the TOAST DB is fully configured (TOAST_DB_* complete)."""
    try:
        return bool(_chat_settings().toast_dsn)
    except Exception:
        return False


def _ensure():
    global _graph, _loader
    if _graph is None:
        cs = _chat_settings()
        _graph = build_sql_graph(
            build_sql_model(),
            PgExecutor(cs.toast_dsn),
            cs.sql_max_queries,
            cs.sql_candidates_per_round,
        )
        _loader = PostgresChunkContextLoader(_retrieval_settings().lore_core_effective_dsn)
    return _graph, _loader


async def _run(request: SqlRequest) -> SQLResult:
    graph, loader = _ensure()
    # desc comes from the canonical chunk; `table` is the trusted payload_id.
    rows = await loader.load([request.chunk_id])
    if not rows:
        return SQLResult(
            payload_id=request.payload_id,
            chunk_id=request.chunk_id,
            status=SQLStatus.not_applicable,
            error="table chunk not found in lore_core",
        )
    chunk = rows[0]
    state = await graph.ainvoke(
        {
            "question": request.question,
            "chunk_id": request.chunk_id,
            "table": request.payload_id,
            "desc_vector": chunk.vector_text,
            "desc_full": chunk.fulltext,
        }
    )
    status = _STATUS_MAP.get(state.get("status", ""), SQLStatus.execution_error)
    answer = state.get("answer") or None
    return SQLResult(
        payload_id=request.payload_id,
        chunk_id=request.chunk_id,
        status=status,
        rows=ok_rows(state.get("attempts", [])),
        answer_summary=answer,
        error=answer if status == SQLStatus.execution_error else None,
    )


def toast_sql_runner() -> CallableSqlRunner:
    return CallableSqlRunner(_run)
