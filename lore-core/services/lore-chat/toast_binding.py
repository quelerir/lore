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
from lore_retrieval.config import get_settings as _settings
from lore_retrieval.contracts import SQLResult, SQLStatus, SqlRequest
from lore_retrieval.observability import trace_sink

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
    """True when the lore_core/TOAST DB is reachable (same instance holds
    lore_core.chunks + the toast_tbl_* data tables)."""
    try:
        return bool(_settings().lore_core_effective_dsn)
    except Exception:
        return False


def _sql_model():
    """The SQL-generator model (langchain), built from the shared retrieval
    settings — decoupled from lore-chat's chainlit/JWT config so it works on the
    host and in the container alike. extra_body caps OpenRouter output tokens."""
    from langchain_openai import ChatOpenAI

    s = _settings()
    kw: dict = {}
    if s.llm_max_tokens:
        kw = {"max_tokens": s.llm_max_tokens, "extra_body": {"max_tokens": s.llm_max_tokens}}
    return ChatOpenAI(
        model=s.sql_model, base_url=s.openrouter_base_url,
        api_key=s.openrouter_api_key, temperature=0.0, **kw,
    )


def _ensure():
    global _graph, _loader
    if _graph is None:
        s = _settings()
        dsn = s.lore_core_effective_dsn
        _graph = build_sql_graph(
            _sql_model(), PgExecutor(dsn), s.sql_max_queries, s.sql_candidates_per_round
        )
        _loader = PostgresChunkContextLoader(dsn)
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
    # Surface the actual generated SQL + execution for the chat debug trace.
    sink = trace_sink.get()
    if sink is not None:
        for a in state.get("attempts", []):
            sink.append({"stage": "sql", "data": {
                "table": request.payload_id,
                "sql": a.get("sql", ""),
                "ok": a.get("ok"),
                "rows": a.get("row_count", 0),
                "error": a.get("error"),
            }})
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
