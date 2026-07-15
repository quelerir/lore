"""LangChain-инструменты над портом — для deep-режима (deepagents)."""

import json

from langchain_core.tools import BaseTool, tool

from toast.port import ToastStorePort


def make_tools(store: ToastStorePort) -> list[BaseTool]:
    @tool
    async def discover_tables(document_hint: str) -> str:
        """Найти таблицы документов по подсказке (название файла, отдел, тема).

        Возвращает source_path, table_id, координаты и краткое описание.
        Всегда начинай с этого инструмента — не угадывай table_id.
        """
        found = await store.discover(document_hint)
        if not found:
            return "Таблицы не найдены. Если других подсказок нет — верни no-table-answer."
        return json.dumps(found, ensure_ascii=False, default=str)

    @tool
    async def inspect_table(table_id: str) -> str:
        """Колонки, число строк и header-подсказка таблицы toast_tbl_<hex>.

        header_hint может содержать первую строку блока, ошибочно ставшую
        заголовком (header-as-data) — учитывай её в ответе.
        """
        try:
            info = await store.inspect(table_id)
        except ValueError as e:
            return f"Ошибка: {e}"
        return json.dumps(info, ensure_ascii=False, default=str)

    @tool
    async def run_select(sql: str) -> str:
        """Выполнить один read-only SELECT к lore_core / splitter_toast.

        Правила: только SELECT, схемы lore_core|splitter_toast, JOIN
        параллельных таблиц по _splitter_source_row. PII-таблицы закрыты
        policy gate. Возвращает строки или текст отказа/ошибки.
        """
        result = await store.run_select(sql)
        if isinstance(result, str):
            return result
        return json.dumps(result, ensure_ascii=False, default=str)

    return [discover_tables, inspect_table, run_select]
