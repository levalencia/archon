"""SSE adapter consuming runtime events directly (no monkey-patching)."""

from __future__ import annotations

import asyncio
import json
import time
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from starlette.responses import StreamingResponse

from app.observability.cost_tracker import CostTracker
from app.observability.logging import get_correlation_id
from app.observability.runtime_events import CompositeEventSink
from app.routes.chat import (
    get_conversation_repository,
    get_llm_client,
    get_skill_registry,
    get_skills_top_k,
    get_tool_registry,
)
from app.runtime import AgentEvent, AgentEventKind, AgentRuntime, RuntimeBudget
from app.runtime.support import as_model_provider, prepare_messages
from app.security.auth import get_current_user
from app.services.artifacts import detect_artifact_in_response

router = APIRouter(prefix="/api/chat", tags=["chat"])

# Module-level pending approval state (keyed by tool_call_id)
_pending: dict[str, asyncio.Event] = {}
_decisions: dict[str, bool] = {}

APPROVAL_TIMEOUT_SECONDS = 60


class StreamRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=10000)
    conversation_id: str = ""
    image: str = ""


class ApprovalBody(BaseModel):
    approved: bool


class QueueEventSink:
    """Per-request sink: queue ownership prevents concurrent stream cross-talk."""

    def __init__(self, queue: asyncio.Queue[AgentEvent]) -> None:
        self.queue = queue

    async def emit(self, event: AgentEvent) -> None:
        await self.queue.put(event)


@router.post("/stream")
async def chat_stream_real(
    body: StreamRequest,
    request: Request,
    user: dict = Depends(get_current_user),  # noqa: B008
) -> StreamingResponse:
    settings = request.app.state.settings
    memory = get_conversation_repository(request)
    conv_id = body.conversation_id or str(uuid.uuid4())
    if body.conversation_id:
        if await memory.get(conv_id, user["user_id"]) is None:
            raise HTTPException(status_code=404, detail="Conversation not found")
    else:
        await memory.create(conv_id, "New Conversation", user["user_id"])

    async def event_stream():
        started = time.monotonic()
        skills = get_skill_registry().search(body.message, limit=get_skills_top_k())
        skills_context = "".join(f"\n\n[Skill: {s.name}]\n{s.content}" for s in skills)
        skills_used = [{"name": s.name, "description": s.description} for s in skills]
        for skill in skills_used:
            yield _sse("skill", skill)

        tools = get_tool_registry()
        messages = await prepare_messages(
            body.message,
            conv_id,
            memory,
            tools,
            skills_context,
            [body.image] if body.image else None,
            user["user_id"],
        )

        # Auto-compact context if approaching token limit
        from app.runtime.models import Role as MRole
        from app.services.auto_compact import auto_compact_context

        raw_msgs = [{"role": m.role.value, "content": m.content} for m in messages]
        raw_msgs, compact_stats = await auto_compact_context(
            raw_msgs,
            llm_chat_fn=get_llm_client(settings).chat
            if hasattr(get_llm_client(settings), "chat")
            else None,
            max_tokens=settings.context_length,
        )
        yield _sse("context", compact_stats)

        if compact_stats.get("compacted"):
            # Rebuild typed messages from compacted raw messages
            from app.runtime.models import Message as MMsg

            messages = [MMsg(MRole(m["role"]), m["content"]) for m in raw_msgs]

        queue: asyncio.Queue[AgentEvent] = asyncio.Queue()

        async def _approval_hook(tool_name: str, tool_call_id: str, arguments: dict) -> bool:
            """Approval hook: emits event via queue, waits for POST decision."""
            evt = asyncio.Event()
            _pending[tool_call_id] = evt
            try:
                await asyncio.wait_for(evt.wait(), timeout=APPROVAL_TIMEOUT_SECONDS)
                return _decisions.pop(tool_call_id, False)
            except (TimeoutError, asyncio.TimeoutError):
                return False
            finally:
                _pending.pop(tool_call_id, None)
                _decisions.pop(tool_call_id, None)

        runtime = AgentRuntime(
            as_model_provider(get_llm_client(settings)),
            tools,
            events=CompositeEventSink(
                conversation_id=conv_id,
                correlation_id=get_correlation_id(),
                model=settings.llm_model,
                repository=memory,
                exporter=request.app.state.otel_exporter,
                downstream=QueueEventSink(queue),
            ),
            budget=RuntimeBudget(
                max_iterations=settings.agent_max_iterations,
                max_tool_calls=8,
                max_tokens=settings.agent_token_budget,
                max_seconds=90,
            ),
            approval_hook=_approval_hook,
        )
        task = asyncio.create_task(runtime.run(messages))
        while not task.done() or not queue.empty():
            try:
                event = await asyncio.wait_for(queue.get(), 0.25)
            except TimeoutError:
                yield ": heartbeat\n\n"
                continue
            if event.kind is AgentEventKind.ITERATION_STARTED:
                yield _sse("thinking", f"Iteration {event.iteration}: calling LLM...")
            elif event.kind is AgentEventKind.MODEL_PROGRESS:
                yield _sse("thinking", event.data["text"])
            elif event.kind is AgentEventKind.TOOL_CALL_REQUESTED:
                yield _sse("thinking", f"Calling {event.data['name']}...")
            elif event.kind is AgentEventKind.TOOL_CALL_COMPLETED:
                output = event.data.get("output", {})
                yield _sse(
                    "tool_call",
                    {
                        "tool": event.data["name"],
                        "parameters": event.data.get("arguments", {}),
                        "result": json.dumps(output, ensure_ascii=False, default=str)[
                            :300
                        ],
                        "status": "success",
                    },
                )
                # Emit source citations for web search results
                if event.data["name"] == "web_search" and isinstance(output, dict):
                    sources = [
                        {"title": r.get("title", ""), "url": r.get("url", "")}
                        for r in output.get("results", [])
                        if r.get("url")
                    ]
                    if sources:
                        yield _sse("sources", sources)
            elif event.kind is AgentEventKind.TEXT_DELTA:
                yield _sse("token", event.data["text"])
            elif event.kind is AgentEventKind.APPROVAL_REQUIRED:
                yield _sse("approval_required", {
                    "tool": event.data["name"],
                    "tool_call_id": event.data["id"],
                    "parameters": event.data.get("arguments", {}),
                })
            elif event.kind is AgentEventKind.TOOL_DENIED:
                yield _sse("tool_denied", {
                    "tool": event.data["name"],
                    "tool_call_id": event.data["id"],
                })

        result = await task
        await memory.store(conv_id, "user", body.message, user["user_id"])
        await memory.store(conv_id, "assistant", result.content, user["user_id"])
        artifacts = detect_artifact_in_response(result.content)
        for artifact in artifacts:
            yield _sse("artifact", artifact)

        # Estimate cost
        cost_tracker = CostTracker()
        cost_info = cost_tracker.record(
            conversation_id=conv_id,
            user_id=user["user_id"],
            model=settings.llm_model,
            input_tokens=result.usage.input_tokens,
            output_tokens=result.usage.output_tokens,
        )

        yield _sse(
            "done",
            {
                "iterations": result.iterations,
                "tools_used": len(result.tool_calls),
                "skills_used": skills_used,
                "artifacts": artifacts,
                "elapsed_ms": round((time.monotonic() - started) * 1000, 2),
                "conversation_id": conv_id,
                "stop_reason": result.stop_reason.value,
                "tokens_used": result.usage.total_tokens,
                "cost_usd": cost_info["cost_usd"],
                "error": result.error,
            },
        )

        # Auto-evaluate response quality
        from app.eval.evaluators import (
            evaluate_cost,
            evaluate_faithfulness,
            evaluate_relevance,
            evaluate_safety,
        )

        # Build context from tool results for faithfulness check
        tool_context = " ".join(
            json.dumps(tc.get("output", ""), default=str)[:500]
            for tc in (result.tool_calls or [])
            if tc.get("output")
        )
        scores = [
            evaluate_faithfulness(result.content, tool_context or body.message),
            evaluate_relevance(result.content, body.message),
            evaluate_safety(result.content),
            evaluate_cost(result.usage.total_tokens),
        ]
        yield _sse("eval", [{"name": s.name, "score": s.score, "reason": s.reason} for s in scores])

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


def _sse(event: str, data) -> str:
    payload = (
        json.dumps(data, ensure_ascii=False, default=str)
        if isinstance(data, (dict, list))
        else str(data)
    )
    return f"event: {event}\n" + "\n".join(f"data: {line}" for line in payload.split("\n")) + "\n\n"


@router.post("/approve/{tool_call_id}")
async def approve_tool_call(
    tool_call_id: str,
    body: ApprovalBody,
    user: dict = Depends(get_current_user),  # noqa: B008
) -> dict:
    """Approve or deny a pending tool call."""
    evt = _pending.get(tool_call_id)
    if evt is None:
        raise HTTPException(status_code=404, detail="No pending approval for this tool call")
    _decisions[tool_call_id] = body.approved
    evt.set()
    return {"tool_call_id": tool_call_id, "approved": body.approved}
