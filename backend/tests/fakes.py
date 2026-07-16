"""Общие фейки для тестов агентов и SQL-графа."""

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.outputs import ChatGeneration, ChatResult


class ScriptedChatModel(BaseChatModel):
    """Отдаёт заранее заданные AIMessage по одному на вызов.

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
