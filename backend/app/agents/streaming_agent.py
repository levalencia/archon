"""Streaming-aware agent run: emits events via asyncio.Queue during execution."""

from __future__ import annotations

import asyncio
import json

import structlog

from app.agents.agent import AgentResult, ProductionAgent

logger = structlog.get_logger()


async def run_agent_streaming(
    agent: ProductionAgent,
    message: str,
    conversation_id: str,
    event_queue: asyncio.Queue,
    images: list[str] | None = None,
) -> AgentResult:
    """Run agent and push events to queue as they happen.

    Events pushed:
    - ("thinking", "Iteration 1: calling LLM...")
    - ("tool_start", {"tool": "web_search", "params": {...}})
    - ("tool_result", {"tool": "web_search", "result": "...", "status": "success"})
    - ("iteration", {"number": 1, "response_preview": "..."})
    """
    # Monkey-patch the agent's tool execution to emit events
    original_execute = agent.tools.execute if agent.tools else None

    async def patched_execute(tool_name: str, parameters: dict, **kwargs):
        await event_queue.put(
            (
                "tool_start",
                {
                    "tool": tool_name,
                    "parameters": parameters,
                },
            )
        )

        result = await original_execute(tool_name, parameters, **kwargs)

        # Truncate result for streaming
        result_str = json.dumps(result, ensure_ascii=False, default=str)
        await event_queue.put(
            (
                "tool_result",
                {
                    "tool": tool_name,
                    "result": result_str[:300],
                    "status": "success",
                },
            )
        )

        return result

    if agent.tools and original_execute:
        agent.tools.execute = patched_execute

    # Monkey-patch LLM to emit iteration events
    original_chat = agent.llm.chat

    iteration_count = 0

    async def patched_chat(messages, max_tokens=4096, **kwargs):
        nonlocal iteration_count
        iteration_count += 1
        await event_queue.put(("thinking", f"Iteration {iteration_count}: calling LLM..."))

        response = await original_chat(messages, max_tokens, **kwargs)

        await event_queue.put(("thinking", f"LLM responded ({len(response)} chars)"))

        return response

    agent.llm.chat = patched_chat

    # Run the agent
    try:
        result = await agent.run(
            message,
            conversation_id=conversation_id,
            images=images,
        )
    finally:
        # Restore originals
        if agent.tools and original_execute:
            agent.tools.execute = original_execute
        agent.llm.chat = original_chat

    await event_queue.put(("agent_done", None))
    return result
