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

    def with_structured_output(self, schema, **kwargs):
        # Скриптованные тесты идут через текстовый фолбэк generate:
        # bind_tools у фейка возвращает self, и без явного отказа structured-
        # путь съел бы лишний response из сценария.
        raise NotImplementedError


class StructuredScriptedChatModel(ScriptedChatModel):
    """with_structured_output отдаёт следующий response как готовый объект схемы."""

    def with_structured_output(self, schema, **kwargs):
        model = self

        class _Structured:
            async def ainvoke(self, messages, config=None):
                return model.responses.pop(0)

        return _Structured()
