"""Ollama adapter. Uses Ollama's /api/chat endpoint with tool support."""

from __future__ import annotations

import json

import httpx
import structlog

logger = structlog.get_logger()


class OllamaAdapter:
    """Ollama adapter for local LLMs. No API key needed.

    Supports tool calling via Ollama's native tool format.
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
    ) -> str:
        """Call Ollama chat API with optional tool definitions."""
        payload: dict = {
            "model": self.model,
            "messages": messages,
            "stream": False,
            "options": {
                "num_predict": max_tokens,
            },
        }

        # Add tools if provided
        if tools:
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

        # Check if the model wants to call a tool
        msg = data.get("message", {})

        if msg.get("tool_calls"):
            # Return tool call as JSON for the ReAct loop to parse
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
                model=self.model,
                tool_calls=len(tool_calls),
            )

            # Return as JSON string for the agent to parse
            return json.dumps(
                {
                    "tool_calls": tool_calls,
                }
            )

        content = msg.get("content", "")

        logger.info(
            "ollama_chat",
            model=self.model,
            tokens=data.get("eval_count", 0),
            duration_ms=round(data.get("total_duration", 0) / 1_000_000, 2),
        )

        return content
