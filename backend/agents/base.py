import os
from enum import Enum

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_ollama import ChatOllama
from langchain_openai import ChatOpenAI


class Mode(Enum):
    FAST = "fast"
    DEEP = "deep"


PROFILE_TO_MODE: dict[str, Mode] = {"fast": Mode.FAST, "deep": Mode.DEEP}


def build_model() -> BaseChatModel:
    """OpenRouter по умолчанию; MODEL_PROVIDER=ollama — локальный фолбэк."""
    if os.environ.get("MODEL_PROVIDER", "openrouter") == "ollama":
        return ChatOllama(
            model=os.environ.get("OLLAMA_MODEL", "gemma3"),
            base_url=os.environ.get("OLLAMA_BASE_URL", "http://ollama:11434"),
        )
    return ChatOpenAI(
        model=os.environ.get("OPENROUTER_MODEL", "anthropic/claude-haiku-4.5"),
        base_url=os.environ.get(
            "OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1"
        ),
        api_key=os.environ["OPENROUTER_API_KEY"],
    )


SYSTEM_PROMPT = (
    "Ты — ассистент datacraft. Отвечай на вопросы пользователя ясно и "
    "кратко, по-русски. Для любых вычислений используй инструмент "
    "calculator — не считай в уме. Для вопросов о сотрудниках, отделах, "
    "грейдах, компетенциях и внутренних документах используй инструмент "
    "query_document_tables. Работа с его результатом: указывай источник "
    "(source_path и table_id); rows и header_hints — два РАЗНЫХ источника "
    "записей, перечисляй записи из обоих (ничего не теряй); при "
    "status=no_table честно скажи, что ответа в таблицах нет — не "
    "выдумывай; при status=refused передай отказ policy gate, не обходи "
    "его; при truncated=true упомяни, что результат неполный."
)

DEEP_PROMPT = SYSTEM_PROMPT + (
    " Если задача сложная — разбей её на шаги и решай последовательно."
)
