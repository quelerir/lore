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


_CONTRACT = (
    "Ты — ассистент по внутренним документам рекламного агентства. Данные "
    "лежат в таблицах, извлечённых из файлов (schema splitter_toast, реестр "
    "lore_core). Правила: только SELECT; параллельные таблицы одного листа "
    "соединяются по _splitter_source_row; у некоторых таблиц первая строка "
    "блока ошибочно стала заголовком — она приходит как header-подсказка, "
    "учитывай её; если релевантной таблицы нет — честно скажи, что ответа в "
    "таблицах нет (не выдумывай); персональные данные (отпуска) закрыты "
    "policy gate — не обходи отказ. В ответе указывай источник: файл и "
    "table_id."
)

FAST_PLAN_PROMPT = _CONTRACT + (
    "\n\nПо вопросу пользователя и списку найденных таблиц составь РОВНО "
    "ОДИН SQL SELECT (Postgres). Верни только SQL без пояснений и без "
    "markdown. Если таблицы не подходят к вопросу — верни ровно NO_TABLE."
)

FAST_ANSWER_PROMPT = _CONTRACT + (
    "\n\nСформулируй ответ пользователю. Кратко, по-русски, с указанием "
    "источника. ВАЖНО: строки результата SQL и header-подсказки — два "
    "РАЗНЫХ источника записей; если есть и то и другое, перечисли записи "
    "из обоих (ничего не теряй). Если результата нет или пришёл отказ — "
    "объясни это честно."
)

DEEP_PROMPT = _CONTRACT + (
    "\n\nРаботай циклом: discover_tables → inspect_table → run_select → "
    "ответ. Не угадывай table_id. Проверяй полноту (header-подсказка!). "
    "Слушайся отказов guardrails и policy gate."
)
