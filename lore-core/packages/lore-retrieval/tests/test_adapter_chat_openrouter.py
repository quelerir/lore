import json

import httpx
import pytest

from lore_retrieval.adapters.chat_openrouter import OpenRouterChatModel
from lore_retrieval.interfaces import ChatModel


async def test_generate_posts_openai_shape_and_parses_content():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["auth"] = request.headers.get("authorization")
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json={"choices": [{"message": {"content": "привет"}}]})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    model = OpenRouterChatModel(
        api_key="k", model="anthropic/claude-haiku-4.5", max_tokens=256, client=client
    )
    assert isinstance(model, ChatModel)

    out = await model.generate("вопрос")
    await client.aclose()

    assert out == "привет"
    assert captured["url"].endswith("/chat/completions")
    assert captured["auth"] == "Bearer k"
    assert captured["body"]["model"] == "anthropic/claude-haiku-4.5"
    assert captured["body"]["messages"][0]["content"] == "вопрос"
    assert captured["body"]["max_tokens"] == 256


async def test_raises_on_http_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(402, json={"error": "insufficient credits"})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    model = OpenRouterChatModel(api_key="k", model="m", client=client)
    with pytest.raises(httpx.HTTPStatusError):
        await model.generate("q")
    await client.aclose()
