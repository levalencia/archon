"""Ollama adapter with vision support. Handles text + image input."""

from __future__ import annotations

import json

import httpx
import structlog

logger = structlog.get_logger()


class OllamaAdapter:
    """Ollama adapter for local LLMs. Supports text and vision models.

    For text: llama3.1:8b
    For vision: llava:7b (accepts base64 images)
    """

    def __init__(
        self,
        model: str = "llama3.1:8b",
        base_url: str = "http://localhost:11434",
    ) -> None:
        self.model = model
        self.base_url = base_url.rstrip("/")
        self._client = httpx.AsyncClient(timeout=120.0)

    async def chat(
        self,
        messages: list[dict],
        max_tokens: int = 2048,
        tools: list[dict] | None = None,
        images: list[str] | None = None,
    ) -> str:
        """Call Ollama chat API with optional tools and images.

        Args:
            messages: Chat messages
            max_tokens: Max tokens to generate
            tools: Tool definitions for function calling
            images: List of base64-encoded images to analyze
        """
        # If images provided, use vision model and add images to last user message
        model = self.model
        if images:
            # Switch to vision model if available
            model = await self._get_vision_model()
            # Ollama expects images in the message
            for msg in reversed(messages):
                if msg["role"] == "user":
                    msg["images"] = images
                    break

        payload: dict = {
            "model": model,
            "messages": messages,
            "stream": False,
            "options": {
                "num_predict": max_tokens,
            },
        }

        # Add tools if provided (not supported with vision models)
        if tools and not images:
            ollama_tools = []
            for tool in tools:
                ollama_tools.append(
                    {
                        "type": "function",
                        "function": {
                            "name": tool["name"],
                            "description": tool.get("description", ""),
                            "parameters": tool.get(
                                "parameters",
                                {
                                    "type": "object",
                                    "properties": {},
                                },
                            ),
                        },
                    }
                )
            payload["tools"] = ollama_tools

        response = await self._client.post(
            f"{self.base_url}/api/chat",
            json=payload,
        )
        response.raise_for_status()
        data = response.json()

        msg = data.get("message", {})

        if msg.get("tool_calls"):
            tool_calls = []
            for tc in msg["tool_calls"]:
                fn = tc.get("function", {})
                tool_calls.append(
                    {
                        "tool": fn.get("name", ""),
                        "args": fn.get("arguments", {}),
                    }
                )

            logger.info(
                "ollama_tool_call",
                model=model,
                tool_calls=len(tool_calls),
            )
            return json.dumps({"tool_calls": tool_calls})

        content = msg.get("content", "")

        logger.info(
            "ollama_chat",
            model=model,
            tokens=data.get("eval_count", 0),
            duration_ms=round(data.get("total_duration", 0) / 1_000_000, 2),
            has_images=bool(images),
        )

        return content

    async def _get_vision_model(self) -> str:
        """Check if a vision model is available, return its name."""
        try:
            r = await self._client.get(f"{self.base_url}/api/tags")
            models = r.json().get("models", [])
            vision_models = ["llava", "llava:7b", "llava:13b", "bakllava"]
            for vm in vision_models:
                for m in models:
                    if vm in m.get("name", ""):
                        logger.info("vision_model_found", model=m["name"])
                        return m["name"]
        except Exception:
            pass

        # Fallback to current model (may not support images)
        logger.warning("no_vision_model", fallback=self.model)
        return self.model
