from enum import Enum

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_ollama import ChatOllama
from langchain_openai import ChatOpenAI

from config import ModelProvider, get_settings


class Mode(Enum):
    FAST = "fast"
    DEEP = "deep"


PROFILE_TO_MODE: dict[str, Mode] = {"fast": Mode.FAST, "deep": Mode.DEEP}


def build_model() -> BaseChatModel:
    """OpenRouter по умолчанию; MODEL_PROVIDER=ollama — локальный фолбэк."""
    s = get_settings()
    if s.model_provider is ModelProvider.OLLAMA:
        return ChatOllama(model=s.ollama_model, base_url=s.ollama_base_url)
    if not s.openrouter_api_key:
        raise RuntimeError(
            "OPENROUTER_API_KEY обязателен при MODEL_PROVIDER=openrouter"
        )
    return ChatOpenAI(
        model=s.openrouter_model,
        base_url=s.openrouter_base_url,
        api_key=s.openrouter_api_key,
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
