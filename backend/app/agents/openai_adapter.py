"""OpenAI adapter. Uses httpx to call the OpenAI Chat Completions API."""

from __future__ import annotations

import httpx
import structlog

from app.observability.logging import safe_value_metadata

logger = structlog.get_logger()


class OpenAIAdapter:
    """OpenAI-compatible LLM adapter. Works with OpenAI, Azure OpenAI, and any
    OpenAI-compatible API (LiteLLM, vLLM, etc).

    The core agent code never imports this directly — it goes through llm_factory.
    """

    def __init__(
        self,
        api_key: str,
        model: str = "gpt-4o",
        base_url: str | None = None,
    ) -> None:
        self.model = model
        self.base_url = (base_url or "https://api.openai.com/v1").rstrip("/")
        self._client = httpx.AsyncClient(
            base_url=self.base_url,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            timeout=60.0,
        )
        logger.info(
            "openai_adapter_init", model=model, **safe_value_metadata("base_url", self.base_url)
        )

    async def chat(
        self,
        messages: list[dict[str, str]],
        max_tokens: int = 4096,
        temperature: float = 0.7,
    ) -> str:
        """Send messages to OpenAI Chat Completions API."""
        payload = {
            "model": self.model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }

        response = await self._client.post("/chat/completions", json=payload)
        response.raise_for_status()

        data = response.json()
        content = data["choices"][0]["message"]["content"]

        logger.info(
            "openai_chat_complete",
            model=self.model,
            input_messages=len(messages),
            usage=data.get("usage"),
        )

        return content
