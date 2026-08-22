"""Chat API routes with real agent execution, tools, skills, and thinking steps.

POST /api/chat — Send a message, agent reasons with tools, returns thinking steps
POST /api/chat/stream — SSE streaming version
GET /api/chat/history/{conversation_id} — Get conversation history
"""

from __future__ import annotations

import json
import time
import uuid

import structlog
from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.agents.agent import ProductionAgent
from app.agents.llm_factory import create_llm_client
from app.memory.in_memory import InMemoryStore
from app.observability.logging import get_correlation_id
from app.routes.skills import get_skill_registry
from app.tools.builtin import (
    calculator_tool,
    datetime_tool,
    read_file_tool,
)
from app.tools.registry import SecureToolRegistry
from app.tools.web_search import web_search_tool

logger = structlog.get_logger()

router = APIRouter(prefix="/api/chat", tags=["chat"])

# Module-level stores (replaced by DI in production)
_memory = InMemoryStore()


def _create_tool_registry() -> SecureToolRegistry:
    """Create a tool registry with real tools wired in."""
    registry = SecureToolRegistry()

    registry.register(
        name="calculator",
        handler=calculator_tool,
        description="Evaluate math expressions: +, -, *, /, sqrt, sin, cos, log, pi",
        input_schema={"required": ["expression"]},
        timeout=5,
    )
    registry.register(
        name="datetime",
        handler=datetime_tool,
        description="Get current date, time, timestamp, timezone info",
        input_schema={"required": ["query"]},
        timeout=5,
    )
    registry.register(
        name="web_search",
        handler=web_search_tool,
        description="Search the web for current information. Returns titles, URLs, snippets.",
        input_schema={"required": ["query"]},
        timeout=30,
    )
    registry.register(
        name="read_file",
        handler=read_file_tool,
        description="Read the contents of a file by path",
        input_schema={"required": ["path"]},
        timeout=10,
    )

    return registry


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=10000)
    conversation_id: str = ""


class ChatResponse(BaseModel):
    response: str
    conversation_id: str
    correlation_id: str
    iterations: int
    tool_calls: list[dict]
    tokens_used: int
    thinking_steps: list[dict]
    skills_used: list[dict]


@router.post("", response_model=ChatResponse)
async def chat(body: ChatRequest, request: Request) -> ChatResponse:
    """Send a message. The agent reasons with tools and skills, returns thinking steps."""
    cid = get_correlation_id()
    start_time = time.monotonic()
    settings = request.app.state.settings
    llm = create_llm_client(settings)

    # Create tool registry
    tools = _create_tool_registry()

    # Search for relevant skills
    skill_registry = get_skill_registry()
    relevant_skills = skill_registry.search(body.message, limit=2)
    skills_context = ""
    skills_used = []
    for skill in relevant_skills:
        skills_context += f"\n\n[Skill: {skill.name}]\n{skill.content}"
        skills_used.append(
            {
                "name": skill.name,
                "description": skill.description,
                "reason": "Matched query keywords",
            }
        )

    # Build agent with tools and skill context
    conv_id = body.conversation_id or str(uuid.uuid4())
    agent = ProductionAgent(
        llm=llm,
        tools=tools,
        memory=_memory,
        system_prompt_extra=skills_context,
    )

    logger.info(
        "chat_request",
        message_length=len(body.message),
        conversation_id=conv_id,
        tools_available=len(tools.list_tools()),
        skills_found=len(skills_used),
        correlation_id=cid,
    )

    # Run the agent
    result = await agent.run(body.message, conversation_id=conv_id)

    elapsed_ms = (time.monotonic() - start_time) * 1000

    # Build thinking steps from agent execution trace
    thinking_steps = []
    for i, step in enumerate(result.steps):
        thinking_steps.append(
            {
                "step": i + 1,
                "type": step.get("type", "reasoning"),
                "agent": step.get("agent", "archon"),
                "detail": step.get("detail", step.get("content", "")[:100]),
                "done": True,
                "duration_ms": step.get("duration_ms", 0),
            }
        )

    # Add skills step if any were used
    if skills_used:
        thinking_steps.insert(
            0,
            {
                "step": 0,
                "type": "skills",
                "agent": "skill_search",
                "detail": (
                    f"Found {len(skills_used)} relevant skills: "
                    f"{', '.join(s['name'] for s in skills_used)}"
                ),
                "done": True,
                "duration_ms": 0,
            },
        )

    logger.info(
        "chat_response",
        conversation_id=conv_id,
        iterations=result.iterations,
        tool_calls=len(result.tool_calls),
        skills_used=len(skills_used),
        elapsed_ms=round(elapsed_ms, 2),
        correlation_id=cid,
    )

    return ChatResponse(
        response=result.response,
        conversation_id=conv_id,
        correlation_id=cid,
        iterations=result.iterations,
        tool_calls=result.tool_calls,
        tokens_used=result.tokens_used,
        thinking_steps=thinking_steps,
        skills_used=skills_used,
    )


@router.post("/stream")
async def chat_stream(body: ChatRequest, request: Request) -> StreamingResponse:
    """SSE streaming chat with thinking steps."""
    settings = request.app.state.settings
    llm = create_llm_client(settings)
    tools = _create_tool_registry()
    skill_registry = get_skill_registry()

    relevant_skills = skill_registry.search(body.message, limit=2)
    skills_context = ""
    for skill in relevant_skills:
        skills_context += f"\n\n[Skill: {skill.name}]\n{skill.content}"

    conv_id = body.conversation_id or str(uuid.uuid4())
    agent = ProductionAgent(
        llm=llm,
        tools=tools,
        memory=_memory,
        system_prompt_extra=skills_context,
    )

    async def event_stream():
        # Skills step
        if relevant_skills:
            data = json.dumps(
                {
                    "step": "skills",
                    "detail": f"Found {len(relevant_skills)} relevant skills",
                }
            )
            yield f"event: thinking\ndata: {data}\n\n"

        data = json.dumps(
            {
                "step": "reasoning",
                "detail": "Starting ReAct loop...",
            }
        )
        yield f"event: thinking\ndata: {data}\n\n"

        result = await agent.run(body.message, conversation_id=conv_id)

        # Stream thinking steps
        for step in result.steps:
            yield f"event: thinking\ndata: {json.dumps(step)}\n\n"

        # Stream response token by token (simulated from complete response)
        words = result.response.split()
        for word in words:
            yield f"event: token\ndata: {json.dumps({'token': word + ' '})}\n\n"

        done_data = json.dumps(
            {
                "iterations": result.iterations,
                "tool_calls": result.tool_calls,
                "tokens_used": result.tokens_used,
            }
        )
        yield f"event: done\ndata: {done_data}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@router.get("/history/{conversation_id}")
async def get_history(conversation_id: str) -> dict:
    """Get conversation history."""
    messages = await _memory.retrieve(conversation_id)
    return {
        "conversation_id": conversation_id,
        "messages": messages,
        "count": len(messages),
    }
