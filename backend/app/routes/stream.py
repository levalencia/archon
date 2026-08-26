"""SSE adapter consuming runtime events directly (no monkey-patching)."""

from __future__ import annotations

import asyncio
import ipaddress
import json
import re
import time
import unicodedata
import uuid
from collections.abc import Mapping
from contextlib import suppress
from dataclasses import replace
from typing import Any
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from starlette.responses import StreamingResponse

from app.observability.cost_tracker import CostTracker
from app.observability.logging import get_correlation_id
from app.routes.chat import (
    get_conversation_repository,
    get_model_provider,
    get_skill_registry,
    get_skills_top_k,
    get_tool_registry,
)
from app.runtime import AgentEvent, AgentEventKind
from app.runtime.factory import RunContext, create_chat_runtime
from app.runtime.support import prepare_messages
from app.security.auth import get_current_user
from app.security.dependencies import enforce_rate_limit
from app.security.live_approvals import ApprovalBroker
from app.services.artifacts import Artifact, detect_artifact_in_response

router = APIRouter(prefix="/api/chat", tags=["chat"])


class StreamRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=10000)
    conversation_id: str = ""
    project_id: str = Field(
        default="default", min_length=1, max_length=100, pattern=r"^[A-Za-z0-9._-]+$"
    )
    image: str = ""


class ApprovalBody(BaseModel):
    approved: bool
    run_id: uuid.UUID


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
    app_provider: Any = Depends(get_model_provider),  # noqa: B008
) -> StreamingResponse:
    await enforce_rate_limit(request, user, "chat")
    settings = request.app.state.settings
    memory = get_conversation_repository(request)
    conv_id = body.conversation_id or str(uuid.uuid4())
    if body.conversation_id:
        if await memory.get(conv_id, user["user_id"]) is None:
            raise HTTPException(status_code=404, detail="Conversation not found")
    else:
        await memory.create(conv_id, "New Conversation", user["user_id"])
    run_context = RunContext.create(
        user_id=user["user_id"],
        conversation_id=conv_id,
        correlation_id=get_correlation_id(),
    )
    run_context = replace(run_context, project_id=body.project_id)
    scoped_memory = request.app.state.scoped_memory
    tools = get_tool_registry(
        context=run_context,
        scoped_memory=scoped_memory,
        conversations=memory,
        sandbox_executor=request.app.state.sandbox_executor,
    )
    approval_broker: ApprovalBroker = request.app.state.approval_broker

    async def event_stream():
        started = time.monotonic()
        # Detect /json prefix for structured output mode
        user_message = body.message
        json_mode = False
        if user_message.startswith("/json "):
            json_mode = True
            user_message = user_message[6:]  # Strip '/json ' prefix
        skills = get_skill_registry().search(user_message, limit=get_skills_top_k())
        skills_context = "".join(f"\n\n[Skill: {s.name}]\n{s.content}" for s in skills)
        skills_used = [{"name": s.name, "description": s.description} for s in skills]
        for skill in skills_used:
            yield _sse("skill", skill)

        persistent_memory_text = (
            await scoped_memory.context_text(user["user_id"], body.project_id)
            if scoped_memory is not None
            else ""
        )
        messages = await prepare_messages(
            user_message,
            conv_id,
            memory,
            tools,
            skills_context,
            [body.image] if body.image else None,
            user["user_id"],
            persistent_memory_text,
        )

        # Auto-compact context if approaching token limit
        from app.runtime.models import Role as MRole
        from app.services.auto_compact import auto_compact_context

        raw_msgs = [{"role": m.role.value, "content": m.content} for m in messages]
        raw_msgs, compact_stats = await auto_compact_context(
            raw_msgs,
            llm_chat_fn=None,
            max_tokens=settings.context_length,
        )
        yield _sse("context", compact_stats)

        if compact_stats.get("compacted"):
            # Rebuild typed messages from compacted raw messages
            from app.runtime.models import Message as MMsg

            messages = [MMsg(MRole(m["role"]), m["content"]) for m in raw_msgs]

        queue: asyncio.Queue[AgentEvent] = asyncio.Queue()

        provider = app_provider
        if json_mode:
            from app.runtime.support import JsonModeProvider

            provider = JsonModeProvider(provider)

        runtime = create_chat_runtime(
            context=run_context,
            provider=provider,
            tools=tools,
            settings=settings,
            repository=memory,
            exporter=request.app.state.otel_exporter,
            redactor=request.app.state.persistence_redactor,
            log_buffer=request.app.state.log_buffer,
            downstream=QueueEventSink(queue),
            authorizer=approval_broker.authorizer(run_context),
        )
        task = asyncio.create_task(runtime.run(messages))
        try:
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
                    yield _sse(
                        "tool_call",
                        {
                            "tool": event.data["name"],
                            "tool_call_id": event.data["id"],
                            "arguments_hash": event.data.get("arguments_hash"),
                            "output_hash": event.data.get("output_hash"),
                            "output_size": event.data.get("output_size"),
                            "status": event.data.get("status", "success"),
                        },
                    )
                elif event.kind is AgentEventKind.TEXT_DELTA:
                    yield _sse("token", event.data["text"])
                elif event.kind is AgentEventKind.POLICY_DECIDED:
                    yield _sse("policy_decided", _routed_event(event.data, run_context))
                elif event.kind is AgentEventKind.APPROVAL_REQUIRED:
                    yield _sse("approval_required", _routed_event(event.data, run_context))
                elif event.kind is AgentEventKind.APPROVAL_DECIDED:
                    yield _sse("approval_decided", _routed_event(event.data, run_context))
                elif event.kind is AgentEventKind.TOOL_DENIED:
                    yield _sse("tool_denied", _routed_event(event.data, run_context))
                elif event.kind is AgentEventKind.TOOL_PROGRESS:
                    yield _sse(
                        "thinking",
                        {
                            "tool": event.data["name"],
                            "tool_call_id": event.data.get("id"),
                            "status": event.data.get("status", "in_progress"),
                        },
                    )
        finally:
            if not task.done():
                task.cancel()
                with suppress(asyncio.CancelledError):
                    await task
            await approval_broker.cancel_run(run_context)

        result = await task
        await memory.store(conv_id, "user", body.message, user["user_id"])
        await memory.store(conv_id, "assistant", result.content, user["user_id"])
        artifacts = detect_artifact_in_response(result.content)
        artifact_store = request.app.state.artifacts
        for artifact_data in artifacts:
            artifact = Artifact(
                conversation_id=conv_id,
                user_id=user["user_id"],
                title=artifact_data["title"],
                artifact_type=artifact_data["type"],
                language=artifact_data.get("language", ""),
                content=artifact_data["content"],
            )
            await artifact_store.save(artifact)
            yield _sse("artifact", artifact.to_summary())

        sources = _project_web_search_sources(result.tool_calls)
        if sources:
            yield _sse("sources", sources)

        # Estimate cost
        cost_tracker = CostTracker()
        cost_info = cost_tracker.record(
            conversation_id=conv_id,
            user_id=user["user_id"],
            model=settings.llm_model,
            input_tokens=result.usage.input_tokens,
            output_tokens=result.usage.output_tokens,
        )

        elapsed_ms = (time.monotonic() - started) * 1000
        await memory.runs.finalize_metadata(
            user["user_id"],
            str(run_context.run_id),
            answer=result.content,
            cost_usd=cost_info["cost_usd"],
            latency_ms=elapsed_ms,
        )

        yield _sse(
            "done",
            {
                "iterations": result.iterations,
                "tools_used": len(result.tool_calls),
                "skills_used": skills_used,
                "artifacts": artifacts,
                "elapsed_ms": round(elapsed_ms, 2),
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


def _project_web_search_sources(
    tool_calls: tuple[dict[str, Any], ...],
) -> list[dict[str, str]]:
    """Expose only display-safe source identity from successful web-search results."""
    sources: list[dict[str, str]] = []
    for call in tool_calls:
        if call.get("tool") != "web_search" or call.get("status") != "success":
            continue
        result = call.get("result")
        if not isinstance(result, Mapping):
            continue
        results = result.get("results")
        if not isinstance(results, (list, tuple)):
            continue
        for item in results:
            if not isinstance(item, Mapping):
                continue
            title = item.get("title")
            url = item.get("url")
            if isinstance(title, str) and isinstance(url, str) and _is_safe_source_url(url):
                sources.append({"title": title[:300], "url": url})
    return sources


def _is_safe_source_url(url: str) -> bool:
    if not url or len(url) > 2048 or any(unicodedata.category(char) == "Cc" for char in url):
        return False
    try:
        parsed = urlsplit(url)
        hostname = parsed.hostname
        # Accessing port performs urllib's integer and range validation.
        _ = parsed.port
    except ValueError:
        return False
    if (
        parsed.scheme.lower() not in {"http", "https"}
        or not parsed.netloc
        or not hostname
        or parsed.username is not None
        or parsed.password is not None
    ):
        return False
    try:
        ipaddress.ip_address(hostname)
        return True
    except ValueError:
        pass
    try:
        ascii_hostname = hostname.encode("idna").decode("ascii").removesuffix(".")
    except UnicodeError:
        return False
    return len(ascii_hostname) <= 253 and all(
        re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?", label)
        for label in ascii_hostname.split(".")
    )


def _routed_event(data, context: RunContext) -> dict:
    """Add non-secret routing while preserving runtime policy identity fields."""
    safe_fields = {
        key: data[key]
        for key in (
            "id",
            "name",
            "arguments_hash",
            "risk_classes",
            "matched_rule_id",
            "action",
            "reason_code",
            "approved",
        )
        if key in data
    }
    return {
        **safe_fields,
        "tool": data.get("name"),
        "tool_call_id": data.get("id"),
        "run_id": context.run_id,
        "conversation_id": context.conversation_id,
    }


@router.post("/approve/{tool_call_id}")
async def approve_tool_call(
    tool_call_id: str,
    body: ApprovalBody,
    request: Request,
    user: dict = Depends(get_current_user),  # noqa: B008
) -> dict:
    """Approve or deny the authenticated owner's exact run-bound pending tool call."""
    await enforce_rate_limit(request, user, "approval")
    broker: ApprovalBroker = request.app.state.approval_broker
    run_id = str(body.run_id)
    decided = await broker.decide_for_owner(
        user_id=user["user_id"],
        run_id=run_id,
        tool_call_id=tool_call_id,
        approved=body.approved,
    )
    if not decided:
        raise HTTPException(status_code=404, detail="No pending approval for this tool call")
    return {"run_id": run_id, "tool_call_id": tool_call_id, "approved": body.approved}
