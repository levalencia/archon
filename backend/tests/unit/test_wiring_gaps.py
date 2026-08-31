"""Tests for wiring gaps.

Covers encrypted memory, resilient coordinator, image input, and write approval.
"""

from __future__ import annotations

import base64
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from app.memory.persistent import get_persistent_memory, reset_singletons
from app.runtime.context import build_messages
from app.runtime.models import Message, Role

# ---------------------------------------------------------------------------
# 1. Encrypted memory wiring
# ---------------------------------------------------------------------------


class TestEncryptedMemoryWiring:
    """get_persistent_memory() should attach EncryptedMemoryStore when config says so."""

    def setup_method(self):
        reset_singletons()

    def teardown_method(self):
        reset_singletons()

    def test_encryption_attached_when_enabled(self):
        """When memory_encryption_enabled=True and key is set, _encrypted_store is attached."""

        class _FakeSettings:
            memory_encryption_enabled = True
            encryption_master_key = base64.urlsafe_b64encode(b"9" * 32).decode().rstrip("=")

        with patch("app.config.get_settings", return_value=_FakeSettings()):
            mem = get_persistent_memory()
            assert hasattr(mem, "_encrypted_store")
            from app.memory.encrypted_memory import EncryptedMemoryStore

            assert isinstance(mem._encrypted_store, EncryptedMemoryStore)

    def test_no_encryption_when_disabled(self):
        """When memory_encryption_enabled=False, no _encrypted_store is set."""

        class _FakeSettings:
            memory_encryption_enabled = False
            encryption_master_key = ""

        with patch("app.config.get_settings", return_value=_FakeSettings()):
            mem = get_persistent_memory()
            assert not hasattr(mem, "_encrypted_store")


# ---------------------------------------------------------------------------
# 2. ResilientCoordinator wiring
# ---------------------------------------------------------------------------


class TestResilientCoordinatorWiring:
    """multi_agent route should use ResilientCoordinator, not AgentCoordinator."""

    def test_route_imports_resilient_coordinator(self):
        """The multi_agent route module should reference ResilientCoordinator."""
        from app.routes import multi_agent as mod

        assert hasattr(mod, "ResilientCoordinator")
        # Verify AgentCoordinator is NOT directly referenced at module level
        assert "AgentCoordinator" not in dir(mod)


# ---------------------------------------------------------------------------
# 3. Image input plumbing
# ---------------------------------------------------------------------------


class TestImageInputPlumbing:
    """Message with images should survive through build_messages."""

    @pytest.mark.asyncio
    async def test_images_flow_through_build_messages(self):
        """Images passed to build_messages appear on the final user Message."""
        mock_memory = AsyncMock()
        mock_memory.retrieve = AsyncMock(return_value=[])

        mock_tools = AsyncMock()
        mock_tools.list_tools = lambda: []

        images = ["data:image/png;base64,abc"]
        messages = await build_messages(
            user_input="Describe this image",
            conversation_id="test-conv",
            memory=mock_memory,
            tools=mock_tools,
            images=images,
        )

        # Last message should be the user message with images
        user_msg = messages[-1]
        assert user_msg.role == Role.USER
        assert user_msg.images == ("data:image/png;base64,abc",)

    def test_message_with_images(self):
        """Message dataclass accepts and preserves images tuple."""
        msg = Message(Role.USER, "hello", images=("data:image/png;base64,abc",))
        assert msg.images == ("data:image/png;base64,abc",)
        assert len(msg.images) == 1


# ---------------------------------------------------------------------------
# 4. Write file requires approval
# ---------------------------------------------------------------------------


class TestWriteFileApproval:
    """write_file tool in chat.py registry should require approval."""

    def test_write_file_requires_approval_in_chat_registry(self):
        """The chat route's tool registry should mark write_file as requires_approval."""
        # Reset singleton so we get a fresh registry
        import app.routes.chat as chat_mod

        old = chat_mod._tools_singleton
        chat_mod._tools_singleton = None
        try:
            registry = chat_mod.get_tool_registry()
            assert registry.tool_requires_approval("write_file") is True
        finally:
            chat_mod._tools_singleton = old

    def test_write_file_requires_approval_in_builtin_registry(self):
        """The builtin register_builtin_tools should also mark write_file as requires_approval."""
        from app.tools.builtin import register_builtin_tools
        from app.tools.registry import SecureToolRegistry

        registry = SecureToolRegistry()
        register_builtin_tools(registry)
        assert registry.tool_requires_approval("write_file") is True


class TestMemoryCheckpointSurface:
    """Memory page must not expose the unsupported legacy restore flow."""

    def test_memory_page_does_not_claim_legacy_checkpoint_restore(self) -> None:
        root = Path(__file__).parents[3]
        page = (root / "frontend" / "src" / "routes" / "memory" / "+page.svelte").read_text(
            encoding="utf-8"
        )
        route = (root / "backend" / "app" / "routes" / "memory.py").read_text(encoding="utf-8")
        api_map = (root / "docs" / "course" / "reference" / "api-map.md").read_text(
            encoding="utf-8"
        )

        assert "/api/memory/checkpoints" not in page
        assert '@router.get("/checkpoints")' not in route
        assert "GET /api/memory/checkpoints" not in api_map
        assert "Restore checkpoint" not in page
        assert "created automatically every 10 messages" not in page
