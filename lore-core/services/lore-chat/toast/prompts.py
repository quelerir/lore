"""Промпты SQL-инструмента и сборка текстов для LLM.

Промпт-инжиниринг живёт здесь: правки текстов не трогают логику графа.
generate_prompt собирает базовый блок + секции фидбека (ошибки, пустые
запросы, причина судьи, примеры строк); rows_context готовит строки
попыток для судьи/суммаризатора с честной пометкой о неполноте.
"""

import json

from toast.models import Attempt, SqlToolState

FIXED_SCHEMA = (
    "Таблицы извлечены из XLSX (Postgres, схема splitter_toast). У каждой "
    "первые служебные колонки: _splitter_row_number (int), "
    "_splitter_source_row (int), _splitter_source_range (text). Дальше — "
    "колонки данных: column_1, column_2, ... или переименованные "
    "(из заголовков). Используй физические имена колонок строго как в "
    "описании таблицы."
)

GENERATE_SYS = (
    FIXED_SCHEMA
    + " Составь SQL SELECT к ОДНОЙ переданной таблице, чтобы ответить на "
    "вопрос. Верни JSON-массив из нескольких РАЗНЫХ по подходу SELECT-строк "
    "(без markdown, без пояснений). Только SELECT, только эта таблица. "
    "Каждый элемент — ровно один запрос SELECT (WITH разрешён), "
    "без точки с запятой."
)
JUDGE_SYS = (
    "Ты оцениваешь, достаточно ли полученных строк, чтобы ответить на "
    "вопрос. Верни sufficient=true/false и короткую причину reason — "
    "почему строк недостаточно (она попадёт генератору SQL)."
)
SUMMARIZE_SYS = (
    "Ответь на вопрос пользователя СТРОГО по предоставленным строкам таблицы. "
    "Не выдумывай. Если данных недостаточно — так и скажи. Если показаны не "
    "все строки выборки — явно скажи, что ответ построен по неполной выборке. "
    "Кратко, по-русски."
)
NO_DATA_MSG = "В данных таблицы нет ответа на этот вопрос."
NO_CANDIDATES_MSG = "Модель не вернула ни одного SQL-кандидата."
JUDGE_ROWS_CAP = 30  # сколько строк отдаём в контекст судьи/суммаризатора
JUDGE_CONTEXT_CHARS = 8_000  # кап сериализованных строк для судьи/суммаризатора
SAMPLE_LIMIT = 5  # строк-примеров для промпта generate
SAMPLE_CONTEXT_CHARS = 2_000  # кап сериализованных примеров в промпте


def _errors_section(state: SqlToolState) -> str | None:
    errors = [a["error"] for a in state.attempts if not a["ok"] and a["error"]]
    if not errors:
        return None
    return "Прошлые ошибки SQL (исправь):\n" + "\n".join(errors[-3:])


def _empty_section(state: SqlToolState) -> str | None:
    empty = [a["sql"] for a in state.attempts if a["ok"] and a["row_count"] == 0]
    if not empty:
        return None
    return ("Эти запросы выполнились, но вернули 0 строк — "
            "нужен другой подход:\n" + "\n".join(empty[-3:]))


def _judge_section(state: SqlToolState) -> str | None:
    if not state.judge_reason:
        return None
    return (f"Прошлый результат отклонён судьёй: {state.judge_reason} — "
            "построй запрос иначе.")


def _sample_section(state: SqlToolState) -> str | None:
    if not state.sample_rows:
        return None
    sample_json = json.dumps(
        state.sample_rows, ensure_ascii=False, default=str
    )[:SAMPLE_CONTEXT_CHARS]
    return (f"Примеры строк таблицы (до {SAMPLE_LIMIT}, реальные "
            f"имена колонок и формат значений):\n{sample_json}")


def generate_prompt(state: SqlToolState, n: int) -> str:
    """Промпт узла generate: база + секции фидбека прошлых раундов."""
    base = (
        f"Вопрос: {state.question}\n"
        f"Таблица: {state.table}\n"
        f"Описание (кратко): {state.desc_vector}\n"
        f"Описание (полно): {state.desc_full}\n"
        f"Нужно вернуть до {n} разных SELECT."
    )
    sections = [_errors_section(state), _empty_section(state),
                _judge_section(state), _sample_section(state)]
    return "\n\n".join([base, *[s for s in sections if s]])


def rows_context(attempts: list[Attempt]) -> str:
    """Строки успешных попыток, сгруппированные по их SQL.

    Судья и суммаризатор видят, какой запрос что вернул, — плохой первый
    кандидат не вытесняет из контекста хороший второй безымянной смесью.
    Суммарные капы: JUDGE_ROWS_CAP строк и ~JUDGE_CONTEXT_CHARS символов;
    хотя бы одна строка отдаётся всегда.
    """
    sections: list[str] = []
    total = sum(a["row_count"] for a in attempts if a["ok"])
    shown = 0
    size = 0
    for a in attempts:
        if not a["ok"] or not a["rows"]:
            continue
        rows_out: list[dict] = []
        for row in a["rows"]:
            if shown >= JUDGE_ROWS_CAP:
                break
            piece = json.dumps(row, ensure_ascii=False, default=str)
            if shown and size + len(piece) > JUDGE_CONTEXT_CHARS:
                break
            rows_out.append(row)
            shown += 1
            size += len(piece)
        if rows_out:
            sections.append(
                f"Запрос: {a['sql']}\nСтроки: "
                + json.dumps(rows_out, ensure_ascii=False, default=str)
            )
    note = f"Показано строк: {shown} из {total}"
    if any(a["truncated"] for a in attempts):
        note += " (результат SQL дополнительно усечён лимитом исполнителя)"
    return note + ".\n" + "\n\n".join(sections)
