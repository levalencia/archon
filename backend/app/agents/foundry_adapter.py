"""Azure AI Foundry adapter using the Anthropic Python SDK.

Uses AsyncAnthropicFoundry for proper Azure authentication.
"""

from __future__ import annotations

import time

import structlog

logger = structlog.get_logger()


class FoundryAdapter:
    """Azure AI Foundry adapter using the official Anthropic SDK.

    Uses AsyncAnthropic with azure endpoint for proper auth handling.
    """

    def __init__(
        self,
        api_key: str,
        base_url: str,
        model: str = "claude-opus-4-6",
    ) -> None:
        from anthropic import AsyncAnthropic

        self.model = model
        self._client = AsyncAnthropic(
            api_key=api_key,
            base_url=base_url,
        )
        logger.info("foundry_adapter_init", model=model, base_url=base_url)

    async def chat(
        self,
        messages: list[dict[str, str]],
        max_tokens: int = 2048,
        **kwargs,
    ) -> str:
        """Send messages to Azure Foundry via Anthropic SDK."""
        system_msg = None
        chat_messages = []
        for msg in messages:
            if msg["role"] == "system":
                system_msg = msg["content"]
            else:
                chat_messages.append({"role": msg["role"], "content": msg["content"]})

        start = time.monotonic()

        create_kwargs: dict = {
            "model": self.model,
            "messages": chat_messages,
            "max_tokens": max_tokens,
        }
        if system_msg:
            create_kwargs["system"] = system_msg

        response = await self._client.messages.create(**create_kwargs)

        duration_ms = (time.monotonic() - start) * 1000
        content = response.content[0].text

        logger.info(
            "foundry_chat_complete",
            model=self.model,
            input_messages=len(chat_messages),
            output_length=len(content),
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
            duration_ms=round(duration_ms, 2),
        )

        return content
