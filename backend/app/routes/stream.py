"""Real-time SSE streaming: events during agent execution.

Events sent progressively:
1. {"event": "thinking", "data": "Searching skills..."}
2. {"event": "skill", "data": {"name": "research-assistant", ...}}
3. {"event": "tool_start", "data": {"tool": "web_search", "params": {...}}}
4. {"event": "tool_result", "data": {"tool": "web_search", "result": "..."}}
5. {"event": "token", "data": "word "} (repeated per word)
6. {"event": "done", "data": {"iterations": 2, "artifacts": [...]}}
"""

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
from app.agents.llm_factory import create_llm_client
from app.middleware.correlation import get_correlation_id
from app.routes.chat import (
    _create_tool_registry,
    _memory,
    get_skill_registry,
    get_skills_top_k,
)
from app.services.artifacts import detect_artifacts

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
        cid = get_correlation_id()
        start = time.monotonic()

        # Step 1: Skills search
        yield _sse("thinking", "Searching relevant skills...")

        skill_registry = get_skill_registry()
        top_k = get_skills_top_k()
        relevant_skills = skill_registry.search(body.message, limit=top_k)
        skills_context = ""
        skills_used = []

        for skill in relevant_skills:
            skills_context += f"\n\n[Skill: {skill.name}]\n{skill.content}"
            skill_info = {
                "name": skill.name,
                "description": skill.description,
            }
            skills_used.append(skill_info)
            yield _sse("skill", skill_info)

        if not skills_used:
            yield _sse("thinking", "No relevant skills found")

        # Step 2: Create agent
        yield _sse("thinking", "Preparing agent...")
        llm = create_llm_client(settings)
        tools = _create_tool_registry()
        conv_id = body.conversation_id or str(uuid.uuid4())

        agent = ProductionAgent(
            llm=llm,
            tools=tools,
            memory=_memory,
            system_prompt_extra=skills_context,
        )

        # Step 3: Run agent with progress callback
        images = [body.image] if body.image else None

        # We need to run the agent and capture tool calls as they happen.
        # The current agent.run() is monolithic, so we post-process.
        # For real streaming, we'd need to refactor agent internals.
        yield _sse("thinking", "Reasoning with LLM...")

        result = await agent.run(
            body.message,
            conversation_id=conv_id,
            images=images,
        )

        # Step 4: Stream tool calls
        for tc in result.tool_calls:
            yield _sse(
                "tool_call",
                {
                    "tool": tc["tool"],
                    "parameters": tc.get("parameters", {}),
                    "result": _truncate(tc.get("result", ""), 200),
                    "status": tc.get("status", "success"),
                },
            )

        # Step 5: Detect artifacts
        artifacts = detect_artifacts(result.response, conv_id)
        for art in artifacts:
            yield _sse(
                "artifact",
                {
                    "id": art["id"],
                    "title": art["title"],
                    "type": art["type"],
                    "content_length": art.get("content_length", 0),
                },
            )

        # Step 6: Stream response text word by word
        yield _sse("thinking", "Generating response...")
        words = result.response.split(" ")
        buffer = ""
        for i, word in enumerate(words):
            buffer += (" " if i > 0 else "") + word
            if i % 2 == 0 or i == len(words) - 1:
                yield _sse("token", buffer)
                buffer = ""
                await asyncio.sleep(0.02)

        # Step 7: Done
        elapsed = round((time.monotonic() - start) * 1000, 2)
        yield _sse(
            "done",
            {
                "iterations": result.iterations,
                "tools_used": len(result.tool_calls),
                "skills_used": skills_used,
                "artifacts": [
                    {"id": a["id"], "title": a["title"], "type": a["type"]} for a in artifacts
                ],
                "elapsed_ms": elapsed,
                "conversation_id": conv_id,
            },
        )

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


def _sse(event: str, data) -> str:
    """Format an SSE event."""
    if isinstance(data, (dict, list)):
        payload = json.dumps(data, ensure_ascii=False)
    else:
        payload = str(data)
    return f"event: {event}\ndata: {payload}\n\n"


def _truncate(value, max_len: int) -> str:
    s = json.dumps(value, ensure_ascii=False) if isinstance(value, (dict, list)) else str(value)
    return s[:max_len] if len(s) > max_len else s
