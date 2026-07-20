"""Фабрика моделей eval-харнесса: OpenRouter через ChatOpenAI.

Единственная варьируемая ось эксперимента — имя модели. Переиспользует
_max_tokens_kwargs из agents.base, чтобы поведение предела вывода совпадало
с боевыми моделями.
"""

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_openai import ChatOpenAI

from agents.base import _max_tokens_kwargs


def build_eval_model(name: str, settings, temperature: float = 0.0) -> BaseChatModel:
    """ChatOpenAI на OpenRouter по имени модели. temperature=0 — воспроизводимость."""
    if not settings.openrouter_api_key:
        raise RuntimeError("OPENROUTER_API_KEY обязателен для eval-харнесса")
    return ChatOpenAI(
        model=name,
        base_url=settings.openrouter_base_url,
        api_key=settings.openrouter_api_key,
        temperature=temperature,
        **_max_tokens_kwargs(settings.llm_max_tokens),
    )
