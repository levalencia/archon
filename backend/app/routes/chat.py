"""Chat API routes with SSE streaming.

POST /api/chat — Send a message and get a streaming response
GET /api/chat/history/{conversation_id} — Get conversation history
"""

from __future__ import annotations

import json

import structlog
from fastapi import APIRouter, Request
from pydantic import BaseModel, Field
from sse_starlette.sse import EventSourceResponse

from app.agents.agent import ProductionAgent
from app.agents.llm_factory import create_llm_client
from app.memory.in_memory import InMemoryStore
from app.observability.logging import new_correlation_id
from app.tools.registry import SecureToolRegistry

logger = structlog.get_logger()

router = APIRouter(prefix="/api/chat", tags=["chat"])

# Module-level stores (replaced by DI in production)
_memory_store = InMemoryStore()
_tool_registry = SecureToolRegistry()


class ChatRequest(BaseModel):
    """Chat request body."""

    message: str = Field(..., min_length=1, max_length=10000)
    conversation_id: str | None = None


class ChatResponse(BaseModel):
    """Chat response body (non-streaming)."""

    response: str
    conversation_id: str
    correlation_id: str
    iterations: int
    tool_calls: list[dict]
    tokens_used: int


def _build_agent(request: Request) -> ProductionAgent:
    """Build an agent from app state settings."""
    settings = request.app.state.settings
    llm = create_llm_client(settings)

    return ProductionAgent(
        llm=llm,
        memory=_memory_store,
        tools=_tool_registry if _tool_registry.list_tools() else None,
        agent_id="archon",
        max_iterations=settings.agent_max_iterations,
        token_budget=settings.agent_token_budget,
    )


@router.post("", response_model=ChatResponse)
async def chat(body: ChatRequest, request: Request) -> ChatResponse:
    """Send a message and get a complete response."""
    correlation_id = new_correlation_id()
    agent = _build_agent(request)

    logger.info(
        "chat_request",
        message_length=len(body.message),
        conversation_id=body.conversation_id,
        correlation_id=correlation_id,
    )

    result = await agent.run(
        user_input=body.message,
        conversation_id=body.conversation_id,
    )

    return ChatResponse(
        response=result.response,
        conversation_id=result.conversation_id,
        correlation_id=result.correlation_id,
        iterations=result.iterations,
        tool_calls=result.tool_calls,
        tokens_used=result.tokens_used,
    )


@router.post("/stream")
async def chat_stream(body: ChatRequest, request: Request) -> EventSourceResponse:
    """Send a message and get a streaming SSE response.

    Events:
    - type=thinking: agent is reasoning (iteration info)
    - type=tool_call: agent is calling a tool
    - type=token: streaming response token
    - type=done: final result with metadata
    - type=error: error occurred
    """
    correlation_id = new_correlation_id()
    agent = _build_agent(request)

    async def event_generator():  # type: ignore[no-untyped-def]
        try:
            # For now, run the full agent and stream the result
            # TODO: Implement true token-by-token streaming with LLM provider
            yield {
                "event": "thinking",
                "data": json.dumps(
                    {
                        "status": "processing",
                        "correlation_id": correlation_id,
                    }
                ),
            }

            result = await agent.run(
                user_input=body.message,
                conversation_id=body.conversation_id,
            )

            # Stream tool calls as events
            for tc in result.tool_calls:
                yield {
                    "event": "tool_call",
                    "data": json.dumps(
                        {
                            "tool": tc["tool"],
                            "status": tc["status"],
                        }
                    ),
                }

            # Stream the response in chunks (simulate token streaming)
            words = result.response.split()
            chunk_size = 5
            for i in range(0, len(words), chunk_size):
                chunk = " ".join(words[i : i + chunk_size])
                yield {
                    "event": "token",
                    "data": json.dumps({"text": chunk}),
                }

            # Final done event
            yield {
                "event": "done",
                "data": json.dumps(result.to_dict()),
            }

        except Exception as e:
            logger.error("chat_stream_error", error=str(e), correlation_id=correlation_id)
            yield {
                "event": "error",
                "data": json.dumps({"error": str(e)}),
            }

    return EventSourceResponse(event_generator())


@router.get("/history/{conversation_id}")
async def get_history(conversation_id: str) -> dict:
    """Get conversation history."""
    messages = await _memory_store.retrieve(conversation_id)
    return {
        "conversation_id": conversation_id,
        "messages": messages,
        "count": len(messages),
    }
