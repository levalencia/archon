"""Tool-budget prompt wiring: configured value must appear in the SYSTEM prompt."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.runtime.context import build_effective_context, build_messages
from app.runtime.models import Role
from app.runtime.support import prepare_effective_context, prepare_messages


class _NoTools:
    def list_tools(self):
        return []


class _EmptyMemory:
    async def retrieve_with_metadata(self, conversation_id, limit=20, user_id="default"):
        del conversation_id, limit, user_id
        return []


class _MemoryWithMessage:
    """Returns a single user message with id=1 so current_message_id=1 resolves."""

    async def retrieve_with_metadata(self, conversation_id, limit=20, user_id="default"):
        del conversation_id, limit, user_id
        return [{"id": 1, "role": "user", "content": "hello"}]


# ---------------------------------------------------------------------------
# 1. _assemble_messages / build_effective_context renders configured value
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.asyncio
async def test_build_effective_context_renders_configured_tool_budget() -> None:
    """A non-default tool_budget=42 must appear in the SYSTEM message."""
    context = await build_effective_context(
        "hello",
        "conv-1",
        _EmptyMemory(),
        _NoTools(),
        user_id="owner",
        project_id="project",
        run_id="run-1",
        tool_budget=42,
    )
    system_msg = context.messages[0]
    assert system_msg.role is Role.SYSTEM
    assert "42" in system_msg.content
    # The hardcoded default 8 must NOT appear as the tool budget
    assert "maximum of 8 tool calls" not in system_msg.content
    assert "maximum of 42 tool calls" in system_msg.content


@pytest.mark.unit
@pytest.mark.asyncio
async def test_build_messages_renders_configured_tool_budget() -> None:
    """Legacy build_messages also renders the configured value."""
    messages = await build_messages(
        "hello",
        "conv-1",
        _EmptyMemory(),
        _NoTools(),
        tool_budget=42,
    )
    system_msg = messages[0]
    assert system_msg.role is Role.SYSTEM
    assert "maximum of 42 tool calls" in system_msg.content


# ---------------------------------------------------------------------------
# 2. Support-layer wrappers propagate tool_budget
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.asyncio
async def test_prepare_effective_context_propagates_tool_budget() -> None:
    """prepare_effective_context forwards tool_budget to build_effective_context."""
    context = await prepare_effective_context(
        "hello",
        "conv-1",
        _EmptyMemory(),
        _NoTools(),
        "",
        user_id="owner",
        project_id="project",
        run_id="run-1",
        tool_budget=17,
    )
    system_msg = context.messages[0]
    assert "maximum of 17 tool calls" in system_msg.content


@pytest.mark.unit
@pytest.mark.asyncio
async def test_prepare_messages_propagates_tool_budget() -> None:
    """prepare_messages forwards tool_budget to build_messages."""
    messages = await prepare_messages(
        "hello",
        "conv-1",
        _EmptyMemory(),
        _NoTools(),
        "",
        tool_budget=17,
    )
    system_msg = messages[0]
    assert "maximum of 17 tool calls" in system_msg.content


# ---------------------------------------------------------------------------
# 3. RequestContextPreparationService.prepare passes tool_budget through
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.asyncio
async def test_request_context_preparer_propagates_tool_budget() -> None:
    """The full prepare() path must render the configured tool_budget in the SYSTEM prompt."""
    from app.services.request_context import RequestContextPreparationService

    # Minimal stubs
    discovery = AsyncMock()
    discovery.discover = AsyncMock(
        return_value=MagicMock(
            blocks=[],
            manifest=MagicMock(
                skill_ids=(),
                instruction_revisions=(),
                skill_revisions=(),
                selected_capability_ids=(),
                rejected_capability_ids=(),
                context_cost_bytes=0,
            ),
        )
    )

    enrichment = AsyncMock()
    enrichment.enrich = AsyncMock(
        return_value=MagicMock(
            blocks=[],
            manifest=MagicMock(
                skill_ids=(),
                instruction_revisions=(),
                skill_revisions=(),
                selected_capability_ids=(),
                rejected_capability_ids=(),
                context_cost_bytes=0,
            ),
        )
    )
    snapshots = AsyncMock()
    snapshots.record = AsyncMock(return_value=None)
    preferences = AsyncMock()
    preferences.list = AsyncMock(return_value=[])

    tools = MagicMock()
    tools.list_tools = lambda: []
    tools.definitions = lambda: ()
    tools.get_tool = lambda name: None

    memory = _MemoryWithMessage()

    service = RequestContextPreparationService(discovery, enrichment, snapshots, preferences)
    prepared = await service.prepare(
        owner_id="owner",
        project_id="project",
        intent="hello",
        current_path=None,
        run_id="run-1",
        conversation_id="conv-1",
        memory=memory,
        tools=tools,
        images=None,
        persistent_memory_text="",
        memory_ids=(),
        current_message_id=1,
        application_secret="test-secret-key-for-testing",
        max_context_bytes=400_000,
        max_tokens=100_000,
        tool_budget=33,
    )
    system_msg = prepared.effective_context.messages[0]
    assert system_msg.role is Role.SYSTEM
    assert "maximum of 33 tool calls" in system_msg.content
