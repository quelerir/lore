"""ChatModel over OpenRouter (OpenAI-compatible /chat/completions).

Thin adapter — LangGraph owns the prompt; this just performs the final call.
``client`` is injectable so tests use ``httpx.MockTransport`` (no network/key).
``max_tokens`` is passed through because OpenRouter otherwise reserves the full
model window and can 402 on low credits.
"""
import httpx


class OpenRouterChatModel:
    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        base_url: str = "https://openrouter.ai/api/v1",
        max_tokens: int | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._api_key = api_key
        self._model = model
        self._base_url = base_url.rstrip("/")
        self._max_tokens = max_tokens
        self._client = client

    async def generate(self, prompt: str) -> str:
        payload: dict = {
            "model": self._model,
            "messages": [{"role": "user", "content": prompt}],
        }
        if self._max_tokens is not None:
            payload["max_tokens"] = self._max_tokens

        owns_client = self._client is None
        client = self._client or httpx.AsyncClient(timeout=60)
        try:
            resp = await client.post(
                f"{self._base_url}/chat/completions",
                headers={"Authorization": f"Bearer {self._api_key}"},
                json=payload,
            )
            resp.raise_for_status()
            data = resp.json()
            choices = data.get("choices")
            if not choices:
                raise RuntimeError(f"OpenRouter returned no choices: {data.get('error', data)}")
            content = choices[0].get("message", {}).get("content")
            if content is None:
                raise RuntimeError("OpenRouter returned empty content")
            return content
        finally:
            if owns_client:
                await client.aclose()
