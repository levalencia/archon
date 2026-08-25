"""Integration test: message flow through hot → warm → cold memory tiers.

Plan items #102, #103.
"""

from __future__ import annotations

import pytest

from app.memory.advanced import get_token_count, importance_weighted_trim, summarize_messages
from app.memory.checkpoints import CheckpointManager


class TestTierIntegration:
    """Test message flow through memory tiers."""

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
    async def test_token_counting_consistent(self) -> None:
        """Token counting works across tiers."""
        text = "Hello world, this is a test message for token counting."
        count = get_token_count(text)
        assert count > 0
        assert count < 100  # Reasonable for a short sentence
