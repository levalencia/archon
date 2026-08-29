"""Chat API routes with real agent execution, tools, skills, and thinking steps.

POST /api/chat — Send a message, agent reasons with tools, returns thinking steps
POST /api/chat/stream — SSE streaming version
GET /api/chat/history/{conversation_id} — Get conversation history
"""

from __future__ import annotations

import time
import uuid
from collections.abc import Sequence
from dataclasses import replace
from typing import Any, cast

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from app.mcp.runtime import MCPBoundToolSpec
from app.memory.scoped import ScopedEncryptedMemoryRepository
from app.observability.logging import get_correlation_id
from app.routes.admin import get_skills_top_k
from app.routes.skills import get_skill_registry
from app.runtime.context import derive_context_asset_hmac_key
from app.runtime.factory import RunContext, create_chat_runtime
from app.runtime.images import ImageValidationError
from app.runtime.support import prepare_effective_context
from app.security.auth import get_current_user
from app.security.compliance import ComplianceViolationError
from app.security.dependencies import enforce_rate_limit
from app.security.policy import RiskClass
from app.services.artifacts import Artifact, detect_artifact_in_response
from app.services.context_snapshots import ContextSnapshotRepository
from app.services.conversations import ConversationRepository
from app.services.monetary_budget import MonetaryBudgetRepository
from app.services.task_queue import DurableJobQueue
from app.tools.builtin import calculator_tool, datetime_tool, read_file_tool, write_file_tool
from app.tools.image_gen import image_gen_tool
from app.tools.memory_tools import (
    create_memory_tool,
    create_session_search_tool,
    memory_tool,
    session_search_tool,
)
from app.tools.registry import SecureToolRegistry, resolve_workspace_path
from app.tools.sandbox import SandboxExecutor
from app.tools.terminal import terminal_tool
from app.tools.web_search import web_search_tool

logger = structlog.get_logger()

# Historical tool-registry test override; production never populates this.
_tools_singleton: SecureToolRegistry | None = (
    None  # Historical test override; production never populates this.
)


def get_model_provider(request: Request) -> Any:
    """Resolve the exact provider owned by this FastAPI application."""
    return request.app.state.model_provider


def get_tool_registry(
    *,
    context: RunContext | None = None,
    scoped_memory: ScopedEncryptedMemoryRepository | None = None,
    conversations: ConversationRepository | None = None,
    sandbox_executor: SandboxExecutor | None = None,
    job_queue: DurableJobQueue | None = None,
    bound_tools: Sequence[MCPBoundToolSpec] = (),
) -> SecureToolRegistry:
    """Create a fresh registry; scoped tools are closures owned by this request."""
    if _tools_singleton is not None:
        return _tools_singleton
    return _create_tool_registry(
        context=context,
        scoped_memory=scoped_memory,
        conversations=conversations,
        sandbox_executor=sandbox_executor,
        job_queue=job_queue,
        bound_tools=bound_tools,
    )


router = APIRouter(prefix="/api/chat", tags=["chat"])


class _NoOpContextOptimizer:
    """Lightweight stand-in after context_optimizer module was removed."""

    def __init__(self, max_tokens: int = 200000, reserve_for_response: int = 4096):
        self.max_tokens = max_tokens
        self.reserve_for_response = reserve_for_response

    def optimize(self, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return messages  # pass-through

    def get_stats(self, messages: list[dict[str, Any]]) -> dict[str, Any]:
        return {"total_tokens": 0, "utilization_pct": 0.0}


_context_optimizer = _NoOpContextOptimizer(max_tokens=200000, reserve_for_response=4096)


def get_conversation_repository(request: Request) -> ConversationRepository:
    return cast(ConversationRepository, request.app.state.conversations)


def _create_tool_registry(
    *,
    context: RunContext | None = None,
    scoped_memory: ScopedEncryptedMemoryRepository | None = None,
    conversations: ConversationRepository | None = None,
    sandbox_executor: SandboxExecutor | None = None,
    job_queue: DurableJobQueue | None = None,
    bound_tools: Sequence[MCPBoundToolSpec] = (),
) -> SecureToolRegistry:
    """Create a tool registry with real tools wired in."""
    registry = SecureToolRegistry()

    registry.register(
        name="calculator",
        handler=calculator_tool,
        description="Evaluate math expressions: +, -, *, /, sqrt, sin, cos, log, pi",
        input_schema={"required": ["expression"]},
        timeout=5,
        risk_classes=frozenset({RiskClass.READ}),
    )
    registry.register(
        name="datetime",
        handler=datetime_tool,
        description="Get current date, time, timestamp, timezone info",
        input_schema={"required": ["query"]},
        timeout=5,
        risk_classes=frozenset({RiskClass.READ}),
    )
    registry.register(
        name="web_search",
        handler=web_search_tool,
        description="Search the web for current information. Returns titles, URLs, snippets.",
        input_schema={
            "required": ["query"],
            "properties": {
                "query": {"type": "string"},
                "num_results": {"type": "integer"},
                "max_results": {"type": "integer"},
            },
        },
        timeout=30,
        risk_classes=frozenset({RiskClass.NETWORK}),
    )
    registry.register(
        name="read_file",
        handler=read_file_tool,
        description="Read the contents of a file by path",
        input_schema={
            "required": ["path"],
            "properties": {
                "path": {"type": "string"},
                "max_size": {"type": "integer"},
            },
        },
        timeout=10,
        risk_classes=frozenset({RiskClass.READ}),
        resource_resolver=resolve_workspace_path,
    )
    registry.register(
        name="write_file",
        handler=write_file_tool,
        description="Write content to a file",
        input_schema={"required": ["path", "content"]},
        timeout=10,
        requires_approval=True,
        risk_classes=frozenset({RiskClass.WRITE}),
        resource_resolver=resolve_workspace_path,
    )

    registry.register(
        name="image_gen",
        handler=image_gen_tool,
        description="Generate an image from a text description. Returns image URL.",
        input_schema={
            "required": ["prompt"],
            "properties": {
                "prompt": {"type": "string"},
                "provider": {"type": "string"},
                "size": {"type": "string"},
            },
        },
        timeout=60,
        risk_classes=frozenset({RiskClass.NETWORK, RiskClass.EXTERNAL_SIDE_EFFECT}),
    )

    # Context-free construction is retained for registry metadata compatibility only.
    # Every live request has a context, and disabled mode therefore omits the tool entirely.
    if context is None or scoped_memory is not None:
        memory_handler = (
            create_memory_tool(scoped_memory, context) if context is not None else memory_tool
        )
        registry.register(
            name="memory",
            handler=memory_handler,
            description=(
                "Save/recall persistent facts about the user. "
                "Actions: add (content=fact), remove (old_text=substring), "
                "replace (old_text=old, content=new), list (no args). "
                "Example: memory(action='add', content='User is 47 years old')"
            ),
            input_schema={
                "required": ["action"],
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["add", "remove", "replace", "list"],
                    },
                    "content": {
                        "type": "string",
                        "description": "The fact to save (add/replace)",
                    },
                    "old_text": {
                        "type": "string",
                        "description": "Substring to find (remove/replace)",
                    },
                },
            },
            requires_approval=True,
            risk_classes=frozenset({RiskClass.READ, RiskClass.WRITE}),
        )

    session_handler = (
        create_session_search_tool(conversations, context)
        if context is not None and conversations is not None
        else session_search_tool
    )
    registry.register(
        name="session_search",
        handler=session_handler,
        description="Search past conversations. Use when user asks about previous discussions.",
        input_schema={
            "required": ["query"],
            "properties": {
                "query": {"type": "string"},
                "limit": {"type": "integer"},
            },
        },
        risk_classes=frozenset({RiskClass.READ}),
    )

    if sandbox_executor is not None:

        async def _code_execute_handler(code: str) -> dict[str, object]:
            return (await sandbox_executor.execute(code, kind="python")).to_dict()

        async def _terminal_handler(command: str, timeout: int = 30) -> dict[str, object]:
            return await terminal_tool(command, timeout, executor=sandbox_executor)

        registry.register(
            name="code_execute",
            handler=_code_execute_handler,
            description=(
                "Execute Python code in an isolated Docker container. "
                "Returns stdout, stderr, and exit_code."
            ),
            input_schema={
                "required": ["code"],
                "properties": {"code": {"type": "string", "description": "Python code to execute"}},
            },
            timeout=125,
            requires_approval=True,
            risk_classes=frozenset({RiskClass.EXECUTE}),
        )
        registry.register(
            name="terminal",
            handler=_terminal_handler,
            description="Execute shell input in an isolated Docker container.",
            input_schema={
                "required": ["command"],
                "properties": {
                    "command": {"type": "string", "description": "Shell input to execute"},
                    "timeout": {"type": "integer", "description": "Max seconds"},
                },
            },
            timeout=125,
            requires_approval=True,
            risk_classes=frozenset({RiskClass.EXECUTE}),
        )

    async def _background_task_handler(action: str, task_id: str = "") -> dict[str, Any]:
        """Read durable background-job state for the current owner/project."""
        if context is None or job_queue is None:
            return {"error": "Background jobs unavailable"}
        if action == "list":
            return {
                "tasks": await job_queue.list(
                    context.user_id, project_id=context.project_id, limit=50
                )
            }
        if action == "status" and task_id:
            status = await job_queue.get(context.user_id, context.project_id, task_id)
            if status is None or status["project_id"] != context.project_id:
                return {"error": "Task not found"}
            return status
        return {"error": "Unknown action. Use 'list' or 'status'."}

    registry.register(
        name="background_task",
        handler=_background_task_handler,
        description="Manage background tasks: list all tasks or check status of a specific task.",
        input_schema={
            "required": ["action"],
            "properties": {
                "action": {"type": "string", "description": "'list' or 'status'"},
                "task_id": {"type": "string", "description": "Task ID (for status action)"},
            },
        },
        timeout=10,
        risk_classes=frozenset({RiskClass.READ}),
    )

    for spec in bound_tools:
        registry.register(
            name=spec.name,
            handler=spec.handler,
            description=spec.description,
            input_schema=dict(spec.input_schema),
            timeout=spec.timeout,
            requires_approval=spec.requires_approval,
            risk_classes=spec.risk_classes,
        )

    return registry


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=10000)
    conversation_id: str = ""
    project_id: str = Field(
        default="default", min_length=1, max_length=100, pattern=r"^[A-Za-z0-9._-]+$"
    )
    image: str = Field(default="", max_length=7_000_000)


class ChatResponse(BaseModel):
    response: str
    conversation_id: str
    correlation_id: str
    iterations: int
    tool_calls: list[dict[str, Any]]
    tokens_used: int
    thinking_steps: list[dict[str, Any]]
    skills_used: list[dict[str, Any]]
    image_analyzed: bool = False
    artifacts: list[dict[str, Any]] = []


@router.post("", response_model=ChatResponse)
async def chat(
    body: ChatRequest,
    request: Request,
    user: dict[str, Any] = Depends(get_current_user),  # noqa: B008
    provider: Any = Depends(get_model_provider),  # noqa: B008
) -> ChatResponse:
    """Send a message. The agent reasons with tools and skills, returns thinking steps."""
    await enforce_rate_limit(request, user, "chat")
    try:
        request.app.state.compliance.enforce_input(body.message)
    except ComplianceViolationError as exc:
        raise HTTPException(
            status_code=422, detail="Message rejected by compliance policy"
        ) from exc
    images: list[str] | None = None
    if body.image:
        try:
            attachment = request.app.state.image_attachments.add_data_uri(
                body.image,
                owner_id=user["user_id"],
                project_id=body.project_id,
                filename="chat-image",
                persist=False,
            )
        except ImageValidationError as exc:
            raise HTTPException(
                status_code=422, detail="Image rejected by validation policy"
            ) from exc
        images = [attachment.data_uri]
    cid = get_correlation_id()
    start_time = time.monotonic()
    settings = request.app.state.settings
    memory = get_conversation_repository(request)

    # Search for relevant skills
    skill_registry = get_skill_registry()
    top_k = get_skills_top_k()
    relevant_skills = skill_registry.search(body.message, limit=top_k)
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

    # Build typed runtime with native provider tools and skill context.
    conv_id = body.conversation_id or str(uuid.uuid4())
    if body.conversation_id:
        if await memory.get(conv_id, user["user_id"]) is None:
            raise HTTPException(status_code=404, detail="Conversation not found")
    else:
        await memory.create(conv_id, "New Conversation", user["user_id"])
    run_context = RunContext.create(
        user_id=user["user_id"],
        conversation_id=conv_id,
        correlation_id=cid,
    )
    run_context = replace(run_context, project_id=body.project_id)
    scoped_memory = request.app.state.scoped_memory
    bound_tools = await request.app.state.mcp_runtime_tools.for_scope(
        user["user_id"], body.project_id
    )
    tools = get_tool_registry(
        context=run_context,
        scoped_memory=scoped_memory,
        conversations=memory,
        sandbox_executor=request.app.state.sandbox_executor,
        job_queue=request.app.state.job_queue,
        bound_tools=bound_tools,
    )

    logger.info(
        "chat_request",
        message_length=len(body.message),
        conversation_id=conv_id,
        tools_available=len(tools.list_tools()),
        skills_found=len(skills_used),
        correlation_id=cid,
    )

    # Run the agent with the validated image tuple prepared above.
    # Optimize context window before running agent
    history = await memory.retrieve(conv_id, limit=50, user_id=user["user_id"])
    if len(history) > 10:
        optimized = _context_optimizer.optimize(history)
        stats = _context_optimizer.get_stats(optimized)
        logger.info(
            "context_optimized",
            original=len(history),
            optimized=len(optimized),
            utilization_pct=stats["utilization_pct"],
        )

    if scoped_memory is not None:
        memory_bundle = await scoped_memory.context_bundle(user["user_id"], body.project_id)
        persistent_memory_text = memory_bundle.text
        memory_ids = memory_bundle.fact_ids
    else:
        persistent_memory_text = ""
        memory_ids = ()
    await memory.runs.ensure_run(
        run_id=run_context.run_id,
        user_id=user["user_id"],
        project_id=body.project_id,
        conversation_id=conv_id,
        correlation_id=run_context.correlation_id,
        provider=settings.llm_provider,
        model=settings.llm_model,
    )
    current_message_id = await memory.store(conv_id, "user", body.message, user["user_id"])
    if current_message_id is None:
        raise RuntimeError("context_message_persistence_failed")
    effective_context = await prepare_effective_context(
        body.message,
        conv_id,
        memory,
        tools,
        skills_context,
        images,
        user["user_id"],
        persistent_memory_text,
        project_id=body.project_id,
        run_id=run_context.run_id,
        memory_ids=memory_ids,
        skill_ids=tuple(skill.name for skill in relevant_skills),
        current_message_id=current_message_id,
        asset_hmac_key=derive_context_asset_hmac_key(settings.secret_key),
    )
    await ContextSnapshotRepository(memory.session_factory).record(effective_context.manifest)
    messages = list(effective_context.messages)
    runtime = create_chat_runtime(
        context=run_context,
        provider=provider,
        tools=tools,
        settings=settings,
        repository=memory,
        exporter=request.app.state.otel_exporter,
        redactor=request.app.state.persistence_redactor,
        log_buffer=request.app.state.log_buffer,
        result_recorder=lambda answer: memory.store(conv_id, "assistant", answer, user["user_id"]),
    )
    result = await runtime.run(messages)

    elapsed_ms = (time.monotonic() - start_time) * 1000
    cost_usd: float | None = None
    if settings.durable_monetary_budget_enabled:
        summary = await MonetaryBudgetRepository(memory.session_factory).summary(
            owner_id=user["user_id"],
            project_id=run_context.project_id,
            run_id=run_context.run_id,
        )
        if summary is not None:
            cost_usd = round(summary.run_spent_nusd / 1_000_000_000, 9)
    await memory.runs.finalize_metadata(
        user["user_id"],
        str(run_context.run_id),
        answer=result.content,
        cost_usd=cost_usd,
        latency_ms=elapsed_ms,
    )

    thinking_steps = [
        {
            "step": i + 1,
            "type": "tool_call",
            "agent": "runtime",
            "detail": f"Called {call['tool']}({call.get('parameters', {})})",
            "result": str(call.get("result", ""))[:200],
            "done": True,
            "duration_ms": 0,
        }
        for i, call in enumerate(result.tool_calls)
    ]

    # Add image step if image was analyzed
    if images:
        thinking_steps.insert(
            0,
            {
                "step": 0,
                "type": "vision",
                "agent": "vision",
                "detail": "Analyzing uploaded image with vision model",
                "done": True,
                "duration_ms": 0,
            },
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

    # Detect and save artifacts from response
    detected = detect_artifact_in_response(result.content)
    saved_artifacts = []
    artifact_store = request.app.state.artifacts
    for art_data in detected:
        artifact = Artifact(
            conversation_id=conv_id,
            user_id=user["user_id"],
            title=art_data["title"],
            artifact_type=art_data["type"],
            language=art_data.get("language", ""),
            content=art_data["content"],
        )
        await artifact_store.save(artifact)
        saved_artifacts.append(artifact.to_summary())

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
        response=result.content,
        conversation_id=conv_id,
        correlation_id=cid,
        iterations=result.iterations,
        tool_calls=list(result.tool_calls),
        tokens_used=result.usage.total_tokens,
        thinking_steps=thinking_steps,
        skills_used=skills_used,
        image_analyzed=bool(images),
        artifacts=saved_artifacts,
    )


@router.get("/history/{conversation_id}")
async def get_history(
    conversation_id: str,
    request: Request,
    user: dict[str, Any] = Depends(get_current_user),  # noqa: B008
) -> dict[str, Any]:
    """Get conversation history."""
    repository = get_conversation_repository(request)
    if await repository.get(conversation_id, user["user_id"]) is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    messages = await repository.retrieve(conversation_id, user_id=user["user_id"])
    return {
        "conversation_id": conversation_id,
        "messages": messages,
        "count": len(messages),
    }
