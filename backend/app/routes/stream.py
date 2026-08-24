"""Real-time SSE: events fire AS the agent thinks, calls tools, generates text."""

from __future__ import annotations

import asyncio
import json
import time
import uuid

import structlog
from fastapi import APIRouter, Request
from pydantic import BaseModel
from starlette.responses import StreamingResponse

from app.agents.agent import ProductionAgent
from app.agents.streaming_agent import run_agent_streaming
from app.routes.chat import (
    _memory,
    get_skill_registry,
    get_skills_top_k,
)
from app.services.artifacts import detect_artifact_in_response

logger = structlog.get_logger()

router = APIRouter(prefix="/api/chat", tags=["chat"])


class StreamRequest(BaseModel):
    message: str
    conversation_id: str = ""
    image: str = ""


@router.post("/stream")
async def chat_stream_real(body: StreamRequest, request: Request):
    """Real-time SSE: events fire as agent thinks, calls tools, generates text."""
    settings = request.app.state.settings

    async def event_stream():
        start = time.monotonic()

        # Step 1: Skills
        yield _sse("thinking", "Searching relevant skills...")
        await asyncio.sleep(0)  # Flush

        skill_registry = get_skill_registry()
        top_k = get_skills_top_k()
        relevant_skills = skill_registry.search(body.message, limit=top_k)
        skills_context = ""
        skills_used = []
        for skill in relevant_skills:
            skills_context += f"\n\n[Skill: {skill.name}]\n{skill.content}"
            info = {"name": skill.name, "description": skill.description}
            skills_used.append(info)
            yield _sse("skill", info)

        if not skills_used:
            yield _sse("thinking", "No relevant skills found")

        # Step 2: Create agent
        yield _sse("thinking", "Preparing agent...")
        await asyncio.sleep(0)

        from app.routes.chat import get_llm_client, get_tool_registry

        llm = get_llm_client(settings)
        tools = get_tool_registry()
        conv_id = body.conversation_id or str(uuid.uuid4())
        agent = ProductionAgent(
            llm=llm,
            tools=tools,
            memory=_memory,
            system_prompt_extra=skills_context,
        )

        # Step 3: Run agent with event queue (events fire DURING execution)
        event_queue: asyncio.Queue = asyncio.Queue()
        images = [body.image] if body.image else None

        # Start agent in background task
        result_holder: list = []

        async def run_agent():
            r = await run_agent_streaming(agent, body.message, conv_id, event_queue, images)
            result_holder.append(r)

        agent_task = asyncio.create_task(run_agent())

        # Stream events from queue as they arrive
        while True:
            try:
                event_type, event_data = await asyncio.wait_for(event_queue.get(), timeout=0.5)

                if event_type == "agent_done":
                    break
                elif event_type == "thinking":
                    yield _sse("thinking", event_data)
                elif event_type == "tool_start":
                    yield _sse("thinking", f"Calling {event_data['tool']}...")
                elif event_type == "tool_result":
                    yield _sse("tool_call", event_data)

            except TimeoutError:
                # No event yet — check if agent task is done
                if agent_task.done():
                    break
                # Send heartbeat to keep connection alive
                yield ": heartbeat\n\n"

        # Wait for task to complete
        await agent_task
        result = result_holder[0] if result_holder else None

        if not result:
            yield _sse("token", "Error: agent failed to produce a result")
            return

        # Step 4: Send context stats from agent's compact check
        compact_stats = None
        for step in result.steps or []:
            if isinstance(step, dict) and step.get("type") == "compact":
                compact_stats = step.get("stats", {})

        from app.memory.advanced import get_token_count

        # Estimate from result
        resp_tokens = get_token_count(result.response)
        ctx_budget = 8000
        ctx_tokens = resp_tokens * (result.iterations or 1) * 3  # rough estimate
        if compact_stats:
            ctx_tokens = compact_stats.get("tokens", ctx_tokens)

        yield _sse(
            "context",
            {
                "tokens": ctx_tokens,
                "budget": ctx_budget,
                "utilization_pct": round(min(ctx_tokens / ctx_budget * 100, 100), 1),
                "messages": result.iterations * 2,
                "compacted": bool(compact_stats),
            },
        )

        # Step 5: Stream tool calls summary
        for tc in result.tool_calls:
            # Already streamed via queue, but add to final data
            pass

        # Step 5: Artifacts
        artifacts = detect_artifact_in_response(result.response)
        for art in artifacts:
            yield _sse(
                "artifact",
                {
                    "id": art.get("id", ""),
                    "title": art.get("title", ""),
                    "type": art.get("type", ""),
                    "content_length": art.get("content_length", 0),
                },
            )

        # Step 6: Stream response word by word
        yield _sse("thinking", "Generating response...")
        words = result.response.split(" ")
        for i, word in enumerate(words):
            yield _sse("token", (" " if i > 0 else "") + word)
            if i % 3 == 0:
                await asyncio.sleep(0.015)

        # Step 7: Done
        elapsed = round((time.monotonic() - start) * 1000, 2)
        yield _sse(
            "done",
            {
                "iterations": result.iterations,
                "tools_used": len(result.tool_calls),
                "skills_used": skills_used,
                "artifacts": [
                    {"id": a.get("id", ""), "title": a.get("title", ""), "type": a.get("type", "")}
                    for a in artifacts
                ],
                "elapsed_ms": elapsed,
                "conversation_id": conv_id,
            },
        )

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


def _sse(event: str, data) -> str:
    if isinstance(data, (dict, list)):
        payload = json.dumps(data, ensure_ascii=False)
    else:
        payload = str(data)
    return f"event: {event}\ndata: {payload}\n\n"
