import os
from enum import Enum

from langchain_ollama import ChatOllama


class Mode(Enum):
    FAST = "fast"
    DEEP = "deep"


PROFILE_TO_MODE: dict[str, Mode] = {"fast": Mode.FAST, "deep": Mode.DEEP}


def build_model() -> ChatOllama:
    return ChatOllama(
        model=os.environ.get("OLLAMA_MODEL", "gemma3"),
        base_url=os.environ.get("OLLAMA_BASE_URL", "http://ollama:11434"),
    )


SYSTEM_PROMPT = (
    "Ты — ассистент datacraft. Отвечай на вопросы пользователя ясно и "
    "кратко, по-русски. Для любых вычислений используй инструмент "
    "calculator — не считай в уме."
)

DEEP_PROMPT = SYSTEM_PROMPT + (
    " Если задача сложная — разбей её на шаги и решай последовательно."
)
