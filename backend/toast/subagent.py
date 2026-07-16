"""Toast-субагент: детерминированный пайплайн из problem-questions-report.html.

discover → inspect → policy → plan SQL (LLM) → validate/execute → результат.
LLM используется ровно в одной точке — планирование SELECT по уже найденной
схеме. Один retry при ошибке SQL. Дисциплина шагов зашита в код, а не в
промпт — не зависит от качества модели.
"""

import json
from typing import Any, Literal, TypedDict

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage

from toast.policy import PII_TABLES, POLICY_REFUSAL
from toast.port import ToastStorePort

MAX_TABLES = 5

PLAN_PROMPT = (
    "Ты пишешь SQL по таблицам, извлечённым из внутренних документов "
    "(Postgres). Правила: РОВНО ОДИН SELECT; только схемы lore_core и "
    "splitter_toast; параллельные таблицы одного листа соединяются по "
    "_splitter_source_row. Верни только SQL без пояснений и без markdown. "
    "Если найденные таблицы не подходят к вопросу — верни ровно NO_TABLE."
)

NO_TABLE_MESSAGE = (
    "В извлечённых таблицах нет данных для ответа на этот вопрос "
    "(no-table-answer)."
)


class SubagentResult(TypedDict, total=False):
    status: Literal["ok", "no_table", "refused", "error"]
    rows: list[dict[str, Any]]
    row_count: int
    truncated: bool
    sql: str
    sources: list[dict[str, Any]]
    header_hints: dict[str, str]
    message: str


def _sources(tables: list[dict]) -> list[dict[str, Any]]:
    return [
        {
            "source_path": t["source_path"],
            "table_id": t["table_id"],
            "coordinates": t["coordinates"],
        }
        for t in tables
    ]


async def _plan_sql(
    model: BaseChatModel, question: str, tables: list[dict], error: str | None
) -> str:
    prompt = (
        f"Вопрос: {question}\n\n"
        f"Найденные таблицы:\n{json.dumps(tables, ensure_ascii=False, default=str)}"
    )
    if error:
        prompt += f"\n\nПредыдущий SQL не выполнился: {error}\nИсправь запрос."
    # Тег internal: handle_message не выводит эти токены пользователю
    # (langgraph stream_mode="messages" отдаёт токены и из ainvoke).
    reply = await model.ainvoke(
        [SystemMessage(PLAN_PROMPT), HumanMessage(prompt)],
        config={"tags": ["internal"]},
    )
    sql = str(reply.content).strip().strip("`")
    if sql.lower().startswith("sql"):
        sql = sql[3:].strip()
    return sql


async def run_toast_subagent(
    model: BaseChatModel, store: ToastStorePort, question: str
) -> SubagentResult:
    tables = await store.discover(question)
    if not tables:
        return SubagentResult(status="no_table", message=NO_TABLE_MESSAGE)

    detailed: list[dict] = []
    for t in tables[:MAX_TABLES]:
        info = await store.inspect(t["table_id"])
        detailed.append(
            {
                **t,
                "columns": info["columns"],
                "row_count": info["row_count"],
                "header_hint": info["header_hint"],
            }
        )

    # Policy gate ДО планирования (детерминированно, не доверяем LLM):
    # если все найденные таблицы — PII, SQL не планируем вовсе.
    if all(t["table_id"] in PII_TABLES for t in detailed):
        return SubagentResult(
            status="refused", message=POLICY_REFUSAL, sources=_sources(detailed)
        )

    sql = ""
    error: str | None = None
    for _ in range(2):  # первая попытка + один retry
        sql = await _plan_sql(model, question, detailed, error)
        if sql == "NO_TABLE":
            return SubagentResult(
                status="no_table",
                message=NO_TABLE_MESSAGE,
                sources=_sources(detailed),
            )
        result = await store.run_select(sql)
        if isinstance(result, str):
            # Policy-отказ окончателен; отказы guardrails и ошибки SQL —
            # повод один раз перепланировать запрос.
            if result.startswith("Отказ policy"):
                return SubagentResult(
                    status="refused",
                    message=result,
                    sql=sql,
                    sources=_sources(detailed),
                )
            error = result
            continue
        return SubagentResult(
            status="ok",
            rows=result["rows"],
            row_count=result["row_count"],
            truncated=result["truncated"],
            sql=sql,
            sources=_sources(detailed),
            header_hints={
                t["table_id"]: t["header_hint"]
                for t in detailed
                if t.get("header_hint")
            },
        )
    return SubagentResult(
        status="error",
        message=error or "неизвестная ошибка",
        sql=sql,
        sources=_sources(detailed),
    )
