"""Общие фейки для тестов агентов и субагента."""

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.outputs import ChatGeneration, ChatResult


class ScriptedChatModel(BaseChatModel):
    """Отдаёт заранее заданные AIMessage (с tool_calls) по одному на вызов.

    Не реализует _stream: BaseChatModel.astream отдаст ответ одним чанком —
    именно так tool_calls доезжают до графа без потерь.
    """

    responses: list

    @property
    def _llm_type(self) -> str:
        return "scripted"

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        return ChatResult(
            generations=[ChatGeneration(message=self.responses.pop(0))]
        )

    def bind_tools(self, tools, **kwargs):
        return self  # tool_calls зашиты в responses


class FakeToastStore:
    """ToastStorePort на заранее заданных данных; пишет выполненные SQL."""

    def __init__(self, tables=None, infos=None, select_results=None):
        self.tables = tables or []
        self.infos = infos or {}
        self.select_results = list(select_results or [])
        self.executed: list[str] = []

    async def discover(self, document_hint):
        return self.tables

    async def inspect(self, table_id):
        return self.infos[table_id]

    async def run_select(self, sql):
        self.executed.append(sql)
        return self.select_results.pop(0)
