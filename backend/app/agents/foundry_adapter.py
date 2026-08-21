"""Azure AI Foundry adapter. Uses httpx with api-key header."""

from __future__ import annotations

import httpx
import structlog

logger = structlog.get_logger()


class FoundryAdapter:
    """Azure AI Foundry adapter for Claude/GPT models hosted on Foundry.

    Uses the Anthropic Messages API format with Azure's api-key auth header.
    The core agent code never imports this directly — it goes through llm_factory.
    """

    def __init__(
        self,
        api_key: str,
        base_url: str,
        model: str = "claude-opus-4-6",
    ) -> None:
        self.model = model
        self.base_url = base_url.rstrip("/")
        self._client = httpx.AsyncClient(
            base_url=self.base_url,
            headers={
                "api-key": api_key,
                "anthropic-version": "2023-06-01",
                "Content-Type": "application/json",
            },
            timeout=60.0,
        )
        logger.info("foundry_adapter_init", model=model, base_url=self.base_url)

    async def chat(
        self,
        messages: list[dict[str, str]],
        max_tokens: int = 4096,
        temperature: float = 0.7,
    ) -> str:
        """Send messages to Azure Foundry endpoint."""
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

        response = await self._client.post("/v1/messages", json=payload)
        response.raise_for_status()

        data = response.json()
        content = data["content"][0]["text"]

        logger.info(
            "foundry_chat_complete",
            model=self.model,
            input_messages=len(chat_messages),
            usage=data.get("usage"),
        )

        return content
