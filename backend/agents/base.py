from enum import Enum

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_ollama import ChatOllama
from langchain_openai import ChatOpenAI

from config import ModelProvider, get_settings


class Mode(Enum):
    FAST = "fast"
    DEEP = "deep"


PROFILE_TO_MODE: dict[str, Mode] = {"fast": Mode.FAST, "deep": Mode.DEEP}


def _max_tokens_kwargs(limit: int | None) -> dict:
    """Опциональный предел вывода для OpenRouter. Пусто, если лимит не задан.
    langchain-openai шлёт max_completion_tokens, который OpenRouter игнорирует
    (и резервирует полное окно модели → 402 при нехватке кредитов), поэтому
    родной max_tokens кладём ещё и в extra_body — прямо в JSON запроса."""
    if limit is None:
        return {}
    return {"max_tokens": limit, "extra_body": {"max_tokens": limit}}


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
        **_max_tokens_kwargs(s.llm_max_tokens),
    )


def build_sql_model(temperature: float = 0.0) -> BaseChatModel:
    """Модель SQL-инструмента (OpenRouter). Temperature варьируется для
    разнообразия кандидатов при генерации."""
    s = get_settings()
    if not s.openrouter_api_key:
        raise RuntimeError("OPENROUTER_API_KEY обязателен для sql_model")
    return ChatOpenAI(
        model=s.sql_model,
        base_url=s.openrouter_base_url,
        api_key=s.openrouter_api_key,
        temperature=temperature,
        **_max_tokens_kwargs(s.llm_max_tokens),
    )


SYSTEM_PROMPT = (
    "Ты — ассистент datacraft. Отвечай на вопросы пользователя ясно и "
    "кратко, по-русски. Для любых вычислений используй инструмент "
    "calculator — не считай в уме."
)

DEEP_PROMPT = SYSTEM_PROMPT + (
    " Если задача сложная — разбей её на шаги и решай последовательно."
)
