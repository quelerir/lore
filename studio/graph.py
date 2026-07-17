"""Фабрика SQL-графа для LangGraph Studio (dev-only).

Backend не установлен пакетом — подключаем по sys.path. Креды и настройки
читаются из окружения (langgraph.json грузит studio/.env), Toast-DSN собирается
через config.build_dsn. Экспортирует переменную `graph` для langgraph.json.
"""

import os
import sys

_BACKEND = os.path.join(os.path.dirname(__file__), "..", "backend")
if _BACKEND not in sys.path:
    sys.path.insert(0, _BACKEND)

from langchain_openai import ChatOpenAI  # noqa: E402

from config import build_dsn  # noqa: E402
from toast.executor import PgExecutor  # noqa: E402
from toast.sql_graph import build_sql_graph  # noqa: E402


def _require(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"Studio: переменная окружения {name} обязательна")
    return value


def _toast_dsn() -> str:
    host = _require("TOAST_DB_HOST")
    user = _require("TOAST_DB_USER")
    password = _require("TOAST_DB_PASSWORD")
    name = _require("TOAST_DB_NAME")
    port = int(os.environ.get("TOAST_DB_PORT", "5432"))
    return build_dsn("postgresql", user, password, host, port, name)


def _build_studio_graph():
    api_key = _require("OPENROUTER_API_KEY")
    # Необязательный лимит вывода: без него OpenRouter резервирует полное окно
    # модели (65536 у sonnet) и может ответить 402 при нехватке кредитов. Если
    # задан, extra_body обязателен — langchain шлёт max_completion_tokens,
    # который OpenRouter игнорирует, а родной max_tokens кладём в JSON запроса.
    raw_limit = os.environ.get("LLM_MAX_TOKENS")
    limit_kwargs = {}
    if raw_limit:
        limit = int(raw_limit)
        limit_kwargs = {"max_tokens": limit, "extra_body": {"max_tokens": limit}}
    model = ChatOpenAI(
        model=os.environ.get("SQL_MODEL", "anthropic/claude-sonnet-4.6"),
        base_url=os.environ.get(
            "OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1"
        ),
        api_key=api_key,
        **limit_kwargs,
    )
    executor = PgExecutor(_toast_dsn())
    return build_sql_graph(
        model,
        executor,
        max_queries=int(os.environ.get("SQL_MAX_QUERIES", "3")),
        candidates_per_round=int(os.environ.get("SQL_CANDIDATES_PER_ROUND", "2")),
    )


graph = _build_studio_graph()
