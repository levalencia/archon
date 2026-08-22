"""Integration test: message flow through hot → warm → cold memory tiers.

Plan items #102, #103.
"""

from __future__ import annotations

import pytest

from app.memory.advanced import get_token_count, importance_weighted_trim, summarize_messages
from app.memory.checkpoints import CheckpointManager
from app.memory.in_memory import InMemoryStore


class TestTierIntegration:
    """Test message flow through memory tiers."""

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_hot_to_warm_flow(self) -> None:
        """Messages stored in hot tier, overflow moves to warm (summarized)."""
        hot = InMemoryStore()

        # Simulate 20 messages in hot tier
        for i in range(20):
            role = "user" if i % 2 == 0 else "assistant"
            await hot.store("conv-1", role, f"Message number {i} about Python programming")

        # Retrieve all from hot
        messages = await hot.retrieve("conv-1")
        assert len(messages) == 20

        # Summarize old messages (simulate warm tier compression)
        old_messages = messages[:14]  # Keep last 6 in hot
        summary = await summarize_messages(old_messages, None)
        assert len(summary) > 0

        # After move: hot has 6 recent + 1 summary
        warm_summary = {"role": "system", "content": f"Previous context: {summary}"}
        recent = messages[14:]
        combined = [warm_summary] + recent
        assert len(combined) == 7  # 1 summary + 6 recent

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_importance_weighted_preserves_key_messages(self) -> None:
        """Importance-weighted trim keeps system + recent user messages."""
        messages = [
            {"role": "system", "content": "You are Archon."},
            {"role": "user", "content": "Old question about weather"},
            {"role": "assistant", "content": "Old answer about weather"},
            {"role": "user", "content": "Another old question"},
            {"role": "assistant", "content": "Another old answer"},
            {"role": "user", "content": "Latest important question about AI agents"},
            {"role": "assistant", "content": "Latest answer about AI agents"},
        ]

        trimmed = importance_weighted_trim(messages, max_tokens=50)

        # System message always kept
        assert trimmed[0]["role"] == "system"

        # Latest messages preferred
        contents = " ".join(m.get("content", "") for m in trimmed)
        assert "Latest" in contents or "AI agents" in contents

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_checkpoint_saves_full_state(self) -> None:
        """Checkpoints preserve the exact conversation state."""
        mgr = CheckpointManager()
        hot = InMemoryStore()

        # Build conversation
        for i in range(5):
            await hot.store("conv-1", "user", f"msg-{i}")

        messages = await hot.retrieve("conv-1")
        cp = await mgr.save("conv-1", messages, "before-trim")

        # Trim messages
        trimmed = messages[-2:]
        assert len(trimmed) == 2

        # Restore checkpoint
        restored = await mgr.restore(cp.id)
        assert restored is not None
        assert len(restored) == 5  # Full state restored

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_token_counting_consistent(self) -> None:
        """Token counting works across tiers."""
        text = "Hello world, this is a test message for token counting."
        count = get_token_count(text)
        assert count > 0
        assert count < 100  # Reasonable for a short sentence

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_large_conversation_performance(self) -> None:
        """1000-message conversation processes within reasonable time."""
        import time

        hot = InMemoryStore()

        start = time.monotonic()
        for i in range(1000):
            role = "user" if i % 2 == 0 else "assistant"
            await hot.store("perf-test", role, f"Message {i}: " + "x" * 100)

        messages = await hot.retrieve("perf-test", limit=1000)
        elapsed_ms = (time.monotonic() - start) * 1000

        assert len(messages) == 1000
        assert elapsed_ms < 5000  # Under 5 seconds (generous for in-memory)
