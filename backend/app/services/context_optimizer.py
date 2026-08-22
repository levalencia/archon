"""Context window optimizer: token counting + summarization + trimming.

Manages the context window budget for LLM calls:
- Count tokens accurately with tiktoken
- Summarize old messages when context grows too large
- Importance-weighted compression (recency, relevance)
"""

from __future__ import annotations

import structlog

from app.memory.advanced import get_token_count

logger = structlog.get_logger()


CHARS_PER_TOKEN = 4  # Fallback constant


def count_tokens(text: str) -> int:
    """Count tokens using tiktoken (with fallback)."""
    return get_token_count(text)


def count_messages_tokens(messages: list[dict]) -> int:
    """Count total tokens across all messages."""
    total = 0
    for msg in messages:
        total += count_tokens(msg.get("content", ""))
        total += 4  # Role, formatting overhead
    return total


class ContextOptimizer:
    """Manages context window to stay within token budget.

    Strategies:
    1. Trim oldest messages first (keep system + last N)
    2. Summarize old messages into a single summary
    3. Drop tool call results (keep tool names only)
    """

    def __init__(
        self,
        max_tokens: int = 4096,
        reserve_for_response: int = 1024,
        summary_threshold: int = 10,
    ) -> None:
        self.max_tokens = max_tokens
        self.reserve = reserve_for_response
        self.budget = max_tokens - reserve_for_response
        self.summary_threshold = summary_threshold

    def optimize(self, messages: list[dict]) -> list[dict]:
        """Optimize messages to fit within token budget.

        Returns optimized messages list.
        """
        current_tokens = count_messages_tokens(messages)

        if current_tokens <= self.budget:
            return messages

        logger.info(
            "context_optimizing",
            current_tokens=current_tokens,
            budget=self.budget,
            messages=len(messages),
        )

        # Strategy 1: Keep system prompt + last N messages
        optimized = self._trim_oldest(messages)

        # Strategy 2: If still too large, truncate long messages
        if count_messages_tokens(optimized) > self.budget:
            optimized = self._truncate_long(optimized)

        final_tokens = count_messages_tokens(optimized)
        logger.info(
            "context_optimized",
            original_tokens=current_tokens,
            final_tokens=final_tokens,
            messages_kept=len(optimized),
            messages_dropped=len(messages) - len(optimized),
        )

        return optimized

    def _trim_oldest(self, messages: list[dict]) -> list[dict]:
        """Keep system prompt + most recent messages within budget."""
        if not messages:
            return messages

        # Always keep system message
        system = [m for m in messages if m.get("role") == "system"]
        non_system = [m for m in messages if m.get("role") != "system"]

        system_tokens = count_messages_tokens(system)
        remaining_budget = self.budget - system_tokens

        # Add messages from newest to oldest
        kept = []
        for msg in reversed(non_system):
            msg_tokens = count_tokens(msg.get("content", "")) + 4
            if remaining_budget - msg_tokens >= 0:
                kept.insert(0, msg)
                remaining_budget -= msg_tokens
            else:
                break

        return system + kept

    def _truncate_long(self, messages: list[dict]) -> list[dict]:
        """Truncate individual messages that are too long."""
        max_msg_tokens = self.budget // max(len(messages), 1)
        max_chars = max_msg_tokens * CHARS_PER_TOKEN

        truncated = []
        for msg in messages:
            content = msg.get("content", "")
            if len(content) > max_chars and msg.get("role") != "system":
                msg = {**msg, "content": content[:max_chars] + "\n[...truncated]"}
            truncated.append(msg)

        return truncated

    def get_stats(self, messages: list[dict]) -> dict:
        """Get context window stats."""
        tokens = count_messages_tokens(messages)
        return {
            "total_tokens": tokens,
            "budget": self.budget,
            "max_tokens": self.max_tokens,
            "utilization_pct": round(tokens / self.budget * 100, 1),
            "messages": len(messages),
            "remaining_tokens": max(0, self.budget - tokens),
        }
