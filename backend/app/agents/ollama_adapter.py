"""Ollama adapter. For running local LLMs without API keys."""

from __future__ import annotations

import httpx
import structlog

logger = structlog.get_logger()


class OllamaAdapter:
    """Ollama adapter for local LLM inference. No API key needed.

    The core agent code never imports this directly — it goes through llm_factory.
    """

    def __init__(
        self,
        model: str = "llama3",
        base_url: str = "http://localhost:11434",
    ) -> None:
        self.model = model
        self._client = httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            headers={"Content-Type": "application/json"},
            timeout=120.0,  # Local models can be slow
        )
        logger.info("ollama_adapter_init", model=model, base_url=base_url)

    async def chat(
        self,
        messages: list[dict[str, str]],
        max_tokens: int = 4096,
        temperature: float = 0.7,
    ) -> str:
        """Send messages to Ollama chat API."""
        payload = {
            "model": self.model,
            "messages": messages,
            "options": {
                "num_predict": max_tokens,
                "temperature": temperature,
            },
            "stream": False,
        }

        response = await self._client.post("/api/chat", json=payload)
        response.raise_for_status()

        data = response.json()
        content = data["message"]["content"]

        logger.info(
            "ollama_chat_complete",
            model=self.model,
            input_messages=len(messages),
            eval_count=data.get("eval_count"),
        )

        return content
