"""Grounded knowledge-base retrieval for lore-chat.

Wraps the ``lore-retrieval`` pipeline as a LangChain tool. The tool runs the full
pipeline (retrieval → arbitration → citations) and returns the grounded answer to
the agent; the resulting ``PipelineResult`` is captured into a turn-scoped
container so ``app.on_message`` can attach its citations to the assistant message
metadata (which the frontend renders as FileViewer deep-link cards).

Capture mechanism: ``app.on_message`` creates a fresh dict in the PARENT task and
calls ``turn_capture.set(container)`` BEFORE running the agent; the tool (which may
execute in a child task under LangGraph's astream) only MUTATES that shared object.
``contextvar.set`` in a child task does not propagate to the parent, but mutating a
shared object bound in the parent's context is visible everywhere — so capture is
robust whether the tool runs in the same task or a subtask, for both fast and deep.
"""
import contextvars
import logging

from langchain_core.tools import BaseTool, tool

from lore_retrieval.config import get_settings as _retrieval_settings

# Set by app.on_message (parent task) each turn; the tool mutates container["result"].
turn_capture: contextvars.ContextVar[dict | None] = contextvars.ContextVar(
    "retrieval_turn_capture", default=None
)

_pipeline = None  # lazy singleton (built on first use)


def retrieval_configured() -> bool:
    """True when the knowledge base can run: Neo4j creds + a lore_core DSN."""
    s = _retrieval_settings()
    return bool(s.neo4j_uri and s.neo4j_password and s.lore_core_effective_dsn)


def _optional_langfuse_tracer():
    """Best-effort Langfuse tracer. Optional observability must NEVER sink the core
    pipeline build: a missing/broken ``langfuse_tracing`` module (e.g. absent from a
    deployed image) degrades to no Langfuse tracer instead of raising — otherwise the
    whole grounded pipeline fails to build and the session silently downgrades."""
    try:
        from langfuse_tracing import build_langfuse_tracer

        return build_langfuse_tracer()
    except Exception:
        logging.exception("langfuse tracer unavailable — continuing without it")
        return None


def _build_sql_runner():
    """Wire the live TOAST SQL runner. On ANY failure (import / not configured /
    build) log loudly and return an explicit UnavailableSqlRunner — NEVER a silent
    fake that masks the outage as a real per-table 'not applicable' verdict."""
    from lore_retrieval.adapters.sql_callable import UnavailableSqlRunner

    try:
        from toast_binding import toast_configured, toast_sql_runner
    except Exception:
        logging.exception("toast_binding import failed — SQL tool unavailable")
        return UnavailableSqlRunner()
    if not toast_configured():
        logging.warning("TOAST not configured (no lore_core DSN) — SQL tool unavailable")
        return UnavailableSqlRunner()
    try:
        return toast_sql_runner()
    except Exception:
        logging.exception("toast_sql_runner build failed — SQL tool unavailable")
        return UnavailableSqlRunner()


def _build_pipeline(*, tracer=None):
    """Assemble the live pipeline. ``tracer`` overrides the default per-turn
    ContextTracer — the Studio/LangSmith debug export injects a LangSmithTracer
    here so internal pipeline stages surface as spans."""
    from neo4j import AsyncGraphDatabase

    from lore_retrieval.adapters.chat_openrouter import OpenRouterChatModel
    from lore_retrieval.embeddings import build_embedder
    from lore_retrieval.pipeline.factory import build_live_pipeline

    s = _retrieval_settings()
    driver = AsyncGraphDatabase.driver(s.neo4j_uri, auth=(s.neo4j_user, s.neo4j_password))
    embedder = build_embedder(
        endpoint=s.embedding_endpoint, model=s.embedding_model,
        base_url=s.ollama_base_url, dim=s.embedding_dim,
    )
    chat_model = OpenRouterChatModel(
        api_key=s.openrouter_api_key,
        model=s.openrouter_model,
        base_url=s.openrouter_base_url,
        max_tokens=s.llm_max_tokens or 800,
    )
    # Real cross-encoder rerank when RETRIEVAL_RERANKER is configured; else the
    # factory falls back to IdentityReranker (P0 no-op, keeps RRF-fusion order).
    from lore_retrieval.adapters.rerank_http import build_reranker

    reranker = build_reranker(s.reranker_endpoint)
    # Live table lane: bind the toast SQL graph when TOAST is configured; else the
    # factory falls back to a no-op SqlRunner (text-lane answers unaffected).
    sql_runner = _build_sql_runner()
    # Live turns default to the ContextTracer (chat debug view). When Langfuse creds
    # are present, fan out to BOTH so the debug view stays intact AND stages export
    # to Langfuse. An explicit tracer (Studio's LangSmithTracer) is left untouched.
    if tracer is None:
        from lore_retrieval.observability import CompositeTracer, ContextTracer

        langfuse = _optional_langfuse_tracer()
        if langfuse is not None:
            tracer = CompositeTracer([ContextTracer(), langfuse])
    return build_live_pipeline(
        driver=driver,
        database=s.neo4j_database,
        dsn=s.lore_core_effective_dsn,
        embedder=embedder,
        chat_model=chat_model,
        index_version=s.index_version,
        sql_runner=sql_runner,
        reranker=reranker,
        rerank_floor=s.rerank_floor,
        tracer=tracer,
    )


def get_pipeline():
    global _pipeline
    if _pipeline is None:
        _pipeline = _build_pipeline()
    return _pipeline


@tool
async def knowledge_base(query: str) -> str:
    """База знаний datacraft: регламенты, инструкции, правила офиса, компенсации,
    процедуры. Вызывай для вопросов о внутренних документах и правилах компании —
    ответ будет обоснован источниками."""
    container = turn_capture.get()
    try:
        result = await get_pipeline().answer(query)
    except Exception:
        # Honest failure — never invite a parametric answer. Inviting "ответь по
        # общим знаниям" here is what made the model hallucinate "база недоступна,
        # но вот общая информация" (grounding violation, defect #1).
        logging.exception("knowledge_base retrieval failed for query=%r", query)
        # Record the failure so on_message surfaces a deterministic error banner
        # (metadata degradation). In DEEP mode this is the ONLY signal — the tool
        # hands text back to the LLM, which then paraphrases; without this flag the
        # frontend can't show the error at the top of the message.
        if container is not None:
            container.setdefault("degradations", []).append("knowledge_base_unavailable")
        return (
            "Не удалось обратиться к базе знаний — она временно недоступна. "
            "Сообщи об этом пользователю и НЕ отвечай из общих знаний."
        )
    if container is not None:
        container["result"] = result  # captured for on_message (citations metadata)
    return result.decision.answer or "В базе знаний нет ответа на этот вопрос."


def knowledge_base_tool() -> BaseTool:
    return knowledge_base
