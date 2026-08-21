"""Anthropic adapter. Uses httpx to call the Anthropic Messages API."""

from __future__ import annotations

import httpx
import structlog

logger = structlog.get_logger()


class AnthropicAdapter:
    """Anthropic Claude adapter via the Messages API.

    The core agent code never imports this directly — it goes through llm_factory.
    """

    def __init__(
        self,
        api_key: str,
        model: str = "claude-sonnet-4-20250514",
    ) -> None:
        self.model = model
        self._client = httpx.AsyncClient(
            base_url="https://api.anthropic.com/v1",
            headers={
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
                "Content-Type": "application/json",
            },
            timeout=60.0,
        )
        logger.info("anthropic_adapter_init", model=model)

    async def chat(
        self,
        messages: list[dict[str, str]],
        max_tokens: int = 4096,
        temperature: float = 0.7,
    ) -> str:
        """Send messages to Anthropic Messages API."""
        # Anthropic requires system message separate from messages
        system_msg = None
        chat_messages = []
        for msg in messages:
            if msg["role"] == "system":
                system_msg = msg["content"]
            else:
                chat_messages.append(msg)

        payload: dict = {
            "model": self.model,
            "messages": chat_messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        if system_msg:
            payload["system"] = system_msg

        response = await self._client.post("/messages", json=payload)
        response.raise_for_status()

        data = response.json()
        content = data["content"][0]["text"]

        logger.info(
            "anthropic_chat_complete",
            model=self.model,
            input_messages=len(chat_messages),
            usage=data.get("usage"),
        )

        return content
