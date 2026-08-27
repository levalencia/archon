"""Auto-compact context when approaching token limit.

Like Hermes/Claude Code: when context reaches threshold,
summarize old messages and keep recent ones.
"""

from __future__ import annotations

import structlog

from app.memory.advanced import get_token_count, summarize_messages

logger = structlog.get_logger()

# Config
MAX_CONTEXT_TOKENS = 200000  # Claude Opus can handle 200K but we keep it efficient
COMPACT_THRESHOLD = 0.75  # Trigger at 75% full
KEEP_RECENT = 10  # Always keep last N messages (adjusted down if few messages)


async def auto_compact_context(
    messages: list[dict],
    llm_chat_fn=None,
    max_tokens: int = MAX_CONTEXT_TOKENS,
    threshold: float = COMPACT_THRESHOLD,
    keep_recent: int = KEEP_RECENT,
) -> list[dict]:
    """Auto-compact context when it exceeds threshold.

    Flow:
    1. Count tokens in current messages
    2. If under threshold → return unchanged
    3. If over → summarize old messages, keep recent
    4. Return: [system] + [summary] + [recent messages]

    This is how Hermes and Claude Code handle long conversations.
    """
    if not messages:
        return messages, {
            "compacted": False,
            "tokens": 0,
            "budget": max_tokens,
            "utilization_pct": 0,
            "messages": 0,
            "summarized_messages": 0,
            "summary_version": None,
        }

    # Separate system from conversation messages
    system_msgs = [m for m in messages if m.get("role") == "system"]
    conv_msgs = [m for m in messages if m.get("role") != "system"]

    # Count tokens
    total_tokens = sum(get_token_count(m.get("content", "")) + 4 for m in messages)
    budget = max_tokens
    utilization = total_tokens / budget if budget > 0 else 0

    if utilization < threshold:
        return messages, {
            "compacted": False,
            "tokens": total_tokens,
            "budget": budget,
            "utilization_pct": round(utilization * 100, 1),
            "messages": len(messages),
            "summarized_messages": 0,
            "summary_version": None,
        }

    # Need to compact — but need at least 2 conv messages to split
    if len(conv_msgs) < 2:
        return messages, {
            "compacted": False,
            "tokens": total_tokens,
            "budget": budget,
            "utilization_pct": round(utilization * 100, 1),
            "messages": len(messages),
            "summarized_messages": 0,
            "summary_version": None,
        }

    # Adjust keep_recent down if we have few messages
    actual_keep = min(keep_recent, max(1, len(conv_msgs) - 1))
    old_msgs = conv_msgs[:-actual_keep]
    recent_msgs = conv_msgs[-actual_keep:]

    logger.info(
        "context_compacting",
        total_tokens=total_tokens,
        budget=budget,
        utilization_pct=round(utilization * 100, 1),
        total_messages=len(conv_msgs),
        old_messages=len(old_msgs),
        recent_messages=len(recent_msgs),
    )

    # Summarize old messages
    summary = await summarize_messages(old_msgs, llm_chat_fn)

    if not summary:
        # Fallback: just keep titles
        summary = " | ".join(m.get("content", "")[:80] for m in old_msgs[-5:])

    # Build compacted context
    summary_msg = {
        "role": "system",
        "content": (
            f"[CONTEXT COMPACTION — previous {len(old_msgs)} messages "
            f"summarized below]\n\n{summary}\n\n"
            f"[End of summary — {len(recent_msgs)} recent messages follow]"
        ),
    }

    compacted = system_msgs + [summary_msg] + recent_msgs

    new_tokens = sum(get_token_count(m.get("content", "")) + 4 for m in compacted)

    logger.info(
        "context_compacted",
        before_tokens=total_tokens,
        after_tokens=new_tokens,
        saved_tokens=total_tokens - new_tokens,
        saved_pct=round((1 - new_tokens / total_tokens) * 100, 1),
        messages_before=len(messages),
        messages_after=len(compacted),
    )

    return compacted, {
        "compacted": True,
        "tokens_before": total_tokens,
        "tokens_after": new_tokens,
        "tokens_saved": total_tokens - new_tokens,
        "saved_pct": round((1 - new_tokens / total_tokens) * 100, 1),
        "budget": budget,
        "utilization_pct": round(new_tokens / budget * 100, 1),
        "messages_before": len(messages),
        "messages_after": len(compacted),
        "messages": len(compacted),
        "tokens": new_tokens,
        "summarized_messages": len(old_msgs),
        "summary_version": "auto-compact-v1",
    }
