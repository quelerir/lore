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
from langchain_core.runnables import RunnableConfig
from langgraph.graph.state import CompiledStateGraph
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool

from agents import PROFILE_TO_MODE, Mode, build_agent
from auth import verify_ticket
from config import get_settings
from sql_demo import build_demo_graph, handle_sql_message

# Сколько последних сообщений истории отдаём агенту: без предела длинный
# диалог рано или поздно упирается в контекст модели.
MAX_HISTORY_MESSAGES = 40

logger = logging.getLogger(__name__)

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
    profiles = [
        cl.ChatProfile(
            name="fast",
            display_name="Быстрый",
            markdown_description=(
                "Фиксированный langgraph-маршрут с одним циклом "
                "инструментов (калькулятор). Предсказуем и быстр."
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
    s = get_settings()
    # Демо SQL-графа: только при полном конфиге — полурабочих режимов нет.
    if s.toast_dsn and s.openrouter_api_key:
        profiles.append(
            cl.ChatProfile(
                name="sql",
                display_name="SQL (демо)",
                markdown_description=(
                    "Каждый вопрос идёт в SQL-граф по демо-таблице; стадии "
                    "видны в «Ходе выполнения»."
                ),
            )
        )
    return profiles


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
    if cl.user_session.get("chat_profile") == "sql":
        cl.user_session.set("sql_graph", build_demo_graph())
        return
    cl.user_session.set("agent", _build_session_agent())
    cl.user_session.set("history", [])


@cl.on_chat_resume
async def on_chat_resume(thread: ThreadDict) -> None:
    if cl.user_session.get("chat_profile") == "sql":
        # Граф без памяти диалога: история сообщений/шагов и так в data layer.
        cl.user_session.set("sql_graph", build_demo_graph())
        return
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


async def handle_message(
    agent: CompiledStateGraph, messages: list[BaseMessage], out: cl.Message
) -> str:
    """Run the agent for one user turn, streaming assistant tokens into `out`.

    `messages` is the full conversation so far (prior turns + current user
    message), so the agent answers with context. Uses stream_mode="messages"
    so LangGraph yields LLM token chunks as they are produced; each assistant
    text chunk is pushed to the Chainlit message via stream_token for live
    token-by-token rendering. Streaming (never ainvoke) avoids the nest_asyncio
    deadlock. Returns the full assistant text.
    """
    state = {"messages": messages}
    config = RunnableConfig(callbacks=[cl.LangchainCallbackHandler()])
    streamed = ""
    final_state: Optional[dict] = None
    async for stream_mode, payload in agent.astream(
        state, stream_mode=["messages", "values"], config=config
    ):
        if stream_mode == "values":
            final_state = payload
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
    return streamed


@cl.on_message
async def on_message(message: cl.Message) -> None:
    sql_graph = cl.user_session.get("sql_graph")
    if sql_graph is not None:
        out = cl.Message(content="")
        await out.send()
        try:
            await handle_sql_message(sql_graph, message.content, out)
        except Exception:
            logger.exception("SQL demo run failed")
            await out.stream_token(
                "Не удалось выполнить прогон SQL-графа. Попробуйте ещё раз."
            )
        await out.update()
        return

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
    answer = await handle_message(agent, history, out)
    await out.update()

    history.append(AIMessage(content=answer))
    cl.user_session.set("history", history[-MAX_HISTORY_MESSAGES:])
