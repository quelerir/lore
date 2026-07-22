import json
import logging
from typing import Any, Optional

import chainlit as cl
from chainlit.data.sql_alchemy import SQLAlchemyDataLayer
from chainlit.types import ThreadDict
from langchain_core.messages import (
    AIMessage,
    AIMessageChunk,
    BaseMessage,
    HumanMessage,
)
from langgraph.graph.state import CompiledStateGraph
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool

from chainlit.server import app as _chainlit_app

from agents import PROFILE_TO_MODE, Mode, build_agent
from audit_mount import attach_audit_router
from auth import verify_ticket
from config import get_settings
from run_trace import ToolCallTracker, iter_node_updates

# Optional: grounded knowledge-base citations. If lore-retrieval is unavailable,
# the chat runs unchanged (no capture, no citation metadata).
try:
    from lore_retrieval.observability import trace_sink

    from retrieval import turn_capture

    _RETRIEVAL_AVAILABLE = True
except Exception:  # pragma: no cover - import-time environment guard
    _RETRIEVAL_AVAILABLE = False

# Сколько последних сообщений истории отдаём агенту: без предела длинный
# диалог рано или поздно упирается в контекст модели.
MAX_HISTORY_MESSAGES = 40

# Read-only audit API (/api/v1/audit) mounted as an ISOLATED sub-app on the
# Chainlit FastAPI server. No-op when AUDIT_* is unconfigured, so the chat runs
# unchanged. Isolation keeps the audit error envelope off the chat's routes.
attach_audit_router(_chainlit_app)

# ---------------------------------------------------------------------------
# Data layer – SQLAlchemyDataLayer subclass that forces NullPool.
#
# Chainlit 2.x SQLAlchemyDataLayer.__init__ calls create_async_engine()
# without exposing a poolclass parameter.  We override __init__ to rebuild
# the engine with poolclass=NullPool after calling super().__init__, which
# satisfies the "MUST use NullPool" constraint while reusing all other
# session/storage setup from the parent.
# ---------------------------------------------------------------------------


class _NullPoolSQLAlchemyDataLayer(SQLAlchemyDataLayer):
    """SQLAlchemyDataLayer with NullPool enforced (no server-side connection pooling)."""

    def __init__(self, conninfo: str, **kwargs: Any) -> None:
        super().__init__(conninfo, **kwargs)
        # Replace the engine that super().__init__ created with a NullPool one.
        old_engine = self.engine  # the pooled engine super() created
        self.engine = create_async_engine(conninfo, poolclass=NullPool)
        self.async_session = sessionmaker(  # type: ignore[call-overload]
            bind=self.engine,
            expire_on_commit=False,
            class_=AsyncSession,
        )
        old_engine.sync_engine.dispose()  # release the superseded pool synchronously


@cl.data_layer
def get_data_layer() -> _NullPoolSQLAlchemyDataLayer:
    return _NullPoolSQLAlchemyDataLayer(
        conninfo=get_settings().database_url,
    )


@cl.set_chat_profiles
async def chat_profiles() -> list[cl.ChatProfile]:
    return [
        cl.ChatProfile(
            name="fast",
            display_name="Быстрый",
            markdown_description=(
                "Grounded-граф по базе знаний: neo4j_retrieve → toast_sql → "
                "summarize. Ответ обоснован источниками, ход виден в трейсе."
            ),
            default=True,
        ),
        cl.ChatProfile(
            name="deep",
            display_name="Умный",
            markdown_description=(
                "deepagents: сам планирует шаги и вызовы инструментов "
                "(калькулятор). Для сложных задач (медленнее)."
            ),
        ),
    ]


def _build_session_agent() -> CompiledStateGraph:
    profile = cl.user_session.get("chat_profile")
    mode = PROFILE_TO_MODE.get(profile or "", Mode.FAST)
    return build_agent(mode)


@cl.header_auth_callback
def header_auth_callback(headers: dict[str, str]) -> Optional[cl.User]:
    authorization = headers.get("Authorization") or headers.get("authorization")
    if not authorization or not authorization.lower().startswith("bearer "):
        return None
    token = authorization.split(" ", 1)[1].strip()
    try:
        claims = verify_ticket(token)
    except Exception:
        return None
    # identifier = username, как и в oauth_user (preferred_username): один и
    # тот же человек через тикет и через authentik — один пользователь/треды.
    return cl.User(
        identifier=claims["username"],
        metadata={"provider": "ticket", "sub": claims["sub"]},
    )


async def oauth_user(
    provider_id: str,
    token: str,
    raw_user_data: dict[str, Any],
    default_user: cl.User,
) -> Optional[cl.User]:
    """Map authentik userinfo to a Chainlit user (identifier = username)."""
    identifier = raw_user_data.get("preferred_username") or default_user.identifier
    return cl.User(
        identifier=str(identifier),
        metadata={
            "provider": "authentik",
            "email": raw_user_data.get("email"),
            "name": raw_user_data.get("name"),
        },
    )


# cl.oauth_callback raises at import time when no oauth provider is configured,
# so register only when the generic provider env is present. Without it the
# service still runs in ticket-only (header auth) mode.
if get_settings().oauth_generic_client_id:
    cl.oauth_callback(oauth_user)


@cl.on_chat_start
async def on_chat_start() -> None:
    cl.user_session.set("agent", _build_session_agent())
    cl.user_session.set("history", [])


@cl.on_chat_resume
async def on_chat_resume(thread: ThreadDict) -> None:
    cl.user_session.set("agent", _build_session_agent())
    # Restore prior turns so the agent keeps context after a page reload/resume.
    # Chainlit persists each message as a step; rebuild the LangChain history
    # from the user/assistant message steps of the thread.
    history: list[BaseMessage] = []
    for step in thread.get("steps") or []:
        output = step.get("output") or ""
        if step.get("type") == "user_message":
            history.append(HumanMessage(content=output))
        elif step.get("type") == "assistant_message":
            history.append(AIMessage(content=output))
    cl.user_session.set("history", history[-MAX_HISTORY_MESSAGES:])


def _trace_step_meta(ev: dict) -> tuple[str, str]:
    """(display name, step type) for a pipeline trace event. 'sql' events carry
    the actual generated query + execution result."""
    stage = ev.get("stage", "")
    if stage == "sql":
        return f"sql · {ev.get('data', {}).get('table', '')}", "tool"
    return stage, "run"


async def _render_run_steps(
    payload: Any, tracker: ToolCallTracker, container: Optional[dict]
) -> None:
    """Render one LangGraph ``updates`` payload: a step per node, and under it the
    node's tool calls plus the retrieval-pipeline stages produced while that node
    ran. Pipeline stages come from the per-turn trace via a cursor, so each stage
    nests under the node that produced it (neo4j_retrieve → neo4j stages, toast_sql
    → SQL queries, summarize → arbitration/cite). Uses ``async with`` so steps nest
    under the on_message run (bare .send() leaves parent_id unset → frontend drops
    them)."""
    trace = (container or {}).get("trace") or []
    cursor = (container or {}).get("_trace_cursor", 0)
    for node_name, msgs in iter_node_updates(payload):
        events = tracker.observe(msgs)
        new_trace = trace[cursor:]
        cursor = len(trace)
        async with cl.Step(name=node_name, type="run"):
            for ev in events:
                async with cl.Step(name=ev["name"], type="tool") as tool_step:
                    tool_step.input = json.dumps(ev["args"], ensure_ascii=False, indent=2)
                    tool_step.output = ev["result"]
            for te in new_trace:
                name, step_type = _trace_step_meta(te)
                async with cl.Step(name=name, type=step_type) as stage_step:
                    stage_step.output = json.dumps(te.get("data", {}), ensure_ascii=False, indent=2)
    if container is not None:
        container["_trace_cursor"] = cursor


async def handle_message(
    agent: CompiledStateGraph,
    messages: list[BaseMessage],
    out: cl.Message,
    container: Optional[dict] = None,
) -> str:
    """Run the agent for one user turn, streaming assistant tokens into `out`.

    `messages` is the full conversation so far (prior turns + current user
    message), so the agent answers with context. Uses stream_mode="messages"
    so LangGraph yields LLM token chunks as they are produced; each assistant
    text chunk is pushed to the Chainlit message via stream_token for live
    token-by-token rendering. The "updates" mode drives a clean node -> tool-call
    debug trace (see ``_render_run_steps``). Streaming (never ainvoke) avoids the
    nest_asyncio deadlock. Returns the full assistant text.
    """
    state = {"messages": messages}
    tracker = ToolCallTracker()
    streamed = ""
    final_state: Optional[dict] = None
    async for stream_mode, payload in agent.astream(
        state, stream_mode=["messages", "updates", "values"]
    ):
        if stream_mode == "values":
            final_state = payload
            continue
        if stream_mode == "updates":
            await _render_run_steps(payload, tracker, container)
            continue
        chunk, _meta = payload
        # Служебные LLM-вызовы (планирование SQL) помечены тегом internal —
        # их токены пользователю не показываем.
        if "internal" in (_meta.get("tags") or []):
            continue
        # Only assistant text chunks carry a non-empty string content; tool-call
        # chunks have empty content and are skipped.
        if (
            isinstance(chunk, AIMessageChunk)
            and isinstance(chunk.content, str)
            and chunk.content
        ):
            streamed += chunk.content
            await out.stream_token(chunk.content)
    # Ноды могут положить готовый AIMessage без LLM-вызова (например
    # no-table-answer быстрого режима) — тогда токенов не было, берём текст
    # из финального состояния.
    if not streamed and final_state:
        last = final_state.get("messages", [])
        if last and isinstance(last[-1], AIMessage) and isinstance(last[-1].content, str):
            streamed = last[-1].content
            await out.stream_token(streamed)
    # Grounded graph carries citations + degradations in its final state; capture
    # both for on_message to attach as message metadata (cards + warning chips).
    if container is not None and isinstance(final_state, dict):
        if final_state.get("citations"):
            container["citations"] = final_state["citations"]
        if final_state.get("degradations"):
            container["degradations"] = final_state["degradations"]
    return streamed


def _turn_citations(capture: dict) -> list:
    """Citations from either path: the grounded graph's final state (fast mode) or
    the deep-mode knowledge_base tool's PipelineResult."""
    if capture.get("citations"):
        return capture["citations"]
    result = capture.get("result")
    return list(getattr(result, "citations", []) or []) if result is not None else []


def _turn_degradations(capture: dict) -> list:
    """Degradations from either path: grounded graph state (fast) or the deep-mode
    knowledge_base PipelineResult. Surfaced as warning chips on the message."""
    if capture.get("degradations"):
        return list(capture["degradations"])
    result = capture.get("result")
    return list(getattr(result, "degradations", []) or []) if result is not None else []


@cl.on_message
async def on_message(message: cl.Message) -> None:
    agent = cl.user_session.get("agent")
    if agent is None:
        await cl.Message(
            content="Agent not initialised. Please restart the chat."
        ).send()
        return

    # Maintain conversation memory across turns in the session.
    history: list[BaseMessage] = cl.user_session.get("history") or []
    history.append(HumanMessage(content=message.content))

    out = cl.Message(content="")
    await out.send()

    # Set the capture container + per-turn trace sink in THIS (parent) task before
    # running the agent; pipeline stages (in the grounded graph nodes or the deep
    # knowledge_base tool) record into the shared trace, and the grounded summarize
    # node / the tool write their result here (robust across task boundaries).
    capture: dict = {}
    if _RETRIEVAL_AVAILABLE:
        turn_capture.set(capture)
        trace: list = []
        trace_sink.set(trace)
        capture["trace"] = trace

    try:
        answer = await handle_message(agent, history, out, capture)
    except Exception as exc:
        # Last-resort net: any uncaught turn error surfaces as a visible message +
        # an error flag, never silent (the grounded graph degrades most failures
        # itself; this covers the rest — deep mode, node crashes, transport).
        logging.exception("turn failed")
        answer = "⚠️ Ошибка при обработке запроса. Попробуйте ещё раз."
        out.content = answer
        out.metadata = {"error": type(exc).__name__}
        await out.update()
        history.append(AIMessage(content=answer))
        cl.user_session.set("history", history[-MAX_HISTORY_MESSAGES:])
        return

    if _RETRIEVAL_AVAILABLE:
        meta: dict = {}
        citations = _turn_citations(capture)
        if citations:
            meta["citations"] = [c.model_dump() for c in citations]
        degradations = _turn_degradations(capture)
        if degradations:
            meta["degradations"] = degradations
        if meta:
            out.metadata = meta
    await out.update()

    history.append(AIMessage(content=answer))
    cl.user_session.set("history", history[-MAX_HISTORY_MESSAGES:])
