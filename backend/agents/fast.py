"""Быстрый режим: фиксированный langgraph-маршрут, LLM не выбирает инструменты.

START → discover → plan_sql(LLM) → execute → answer(LLM) → END
Одна повторная попытка plan_sql при ошибке SQL. NO_TABLE → честный отказ.
"""

import json
from typing import Any, TypedDict

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from agents.base import FAST_ANSWER_PROMPT, FAST_PLAN_PROMPT
from toast.port import ToastStorePort


class FastState(TypedDict, total=False):
    messages: list[Any]      # вход/выход в формате MessagesState
    question: str
    tables: list[dict]
    sql: str
    sql_error: str | None
    result: str              # JSON результата или текст отказа
    retried: bool


def build_fast_agent(model: BaseChatModel, store: ToastStorePort) -> CompiledStateGraph:
    async def discover(state: FastState) -> FastState:
        question = state["messages"][-1].content
        tables = await store.discover(question)
        detailed = []
        for t in tables[:5]:
            info = await store.inspect(t["table_id"])
            detailed.append({**t, "columns": info["columns"], "header_hint": info["header_hint"]})
        return {"question": question, "tables": detailed}

    async def plan_sql(state: FastState) -> FastState:
        if not state["tables"]:
            return {"sql": "NO_TABLE"}
        prompt = (
            f"Вопрос: {state['question']}\n\n"
            f"Найденные таблицы:\n{json.dumps(state['tables'], ensure_ascii=False, default=str)}"
        )
        if state.get("sql_error"):
            prompt += f"\n\nПредыдущий SQL не выполнился: {state['sql_error']}\nИсправь запрос."
        reply = await model.ainvoke(
            [SystemMessage(FAST_PLAN_PROMPT), HumanMessage(prompt)]
        )
        sql = str(reply.content).strip().strip("`")
        if sql.lower().startswith("sql"):
            sql = sql[3:].strip()
        return {"sql": sql, "sql_error": None}

    async def execute(state: FastState) -> FastState:
        if state["sql"] == "NO_TABLE":
            return {"result": "NO_TABLE"}
        result = await store.run_select(state["sql"])
        if isinstance(result, str):
            if result.startswith("Ошибка SQL") and not state.get("retried"):
                return {"sql_error": result, "retried": True, "result": ""}
            return {"result": result}
        return {"result": json.dumps(result, ensure_ascii=False, default=str)}

    async def answer(state: FastState) -> FastState:
        if state["result"] == "NO_TABLE":
            content = (
                "В извлечённых таблицах нет данных для ответа на этот вопрос "
                "(no-table-answer). Попробуйте уточнить документ или отдел."
            )
            return {"messages": [AIMessage(content=content)]}
        prompt = (
            f"Вопрос: {state['question']}\n"
            f"SQL: {state.get('sql', '')}\n"
            f"Результат: {state['result']}\n"
            f"Таблицы: {json.dumps([t.get('source_path') for t in state['tables']], ensure_ascii=False)}"
        )
        # astream, а не ainvoke: только так токены финального ответа доходят
        # до stream_mode="messages" (и до UI). plan_sql сознательно ainvoke —
        # его вывод (сырой SQL) пользователь видеть не должен.
        streamed = ""
        async for chunk in model.astream(
            [SystemMessage(FAST_ANSWER_PROMPT), HumanMessage(prompt)]
        ):
            if isinstance(chunk.content, str):
                streamed += chunk.content
        return {"messages": [AIMessage(content=streamed)]}

    def after_execute(state: FastState) -> str:
        return "plan_sql" if state.get("sql_error") else "answer"

    graph = StateGraph(FastState)
    graph.add_node("discover", discover)
    graph.add_node("plan_sql", plan_sql)
    graph.add_node("execute", execute)
    graph.add_node("answer", answer)
    graph.add_edge(START, "discover")
    graph.add_edge("discover", "plan_sql")
    graph.add_edge("plan_sql", "execute")
    graph.add_conditional_edges("execute", after_execute, ["plan_sql", "answer"])
    graph.add_edge("answer", END)
    return graph.compile()
