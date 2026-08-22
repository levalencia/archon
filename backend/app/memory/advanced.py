"""Token counting with tiktoken + drift detection + LLM summarization.

Completes plan items #79, #91, #92, #96.
"""

from __future__ import annotations

import time
from collections import defaultdict

import structlog

logger = structlog.get_logger()

# --- Token counting with tiktoken (#96) ---

_encoder = None


def get_token_count(text: str, model: str = "gpt-4") -> int:
    """Count tokens using tiktoken if available, else approximate."""
    global _encoder
    try:
        import tiktoken

        if _encoder is None:
            _encoder = tiktoken.encoding_for_model(model)
        return len(_encoder.encode(text))
    except (ImportError, KeyError):
        # Fallback: ~4 chars per token for English
        return max(1, len(text) // 4)


def count_messages_tokens_accurate(messages: list[dict], model: str = "gpt-4") -> int:
    """Count tokens for a message list (including overhead per message)."""
    total = 0
    for msg in messages:
        total += get_token_count(msg.get("content", ""), model)
        total += 4  # role + formatting overhead
    total += 3  # reply priming
    return total


# --- Drift detection (#79) ---


class DriftDetector:
    """Compare response distributions over time to detect model drift.

    Tracks: response length, token count, tool usage, latency.
    Alerts when current window deviates from baseline by > threshold.
    """

    def __init__(self, window_size: int = 100, threshold: float = 0.3) -> None:
        self.window_size = window_size
        self.threshold = threshold
        self._baseline: dict[str, list[float]] = defaultdict(list)
        self._current: dict[str, list[float]] = defaultdict(list)
        self._alerts: list[dict] = []

    def record(
        self,
        response_length: int,
        tokens: int,
        tool_calls: int,
        latency_ms: float,
    ) -> dict | None:
        """Record a response. Returns drift alert if detected."""
        metrics = {
            "response_length": float(response_length),
            "tokens": float(tokens),
            "tool_calls": float(tool_calls),
            "latency_ms": latency_ms,
        }

        for key, value in metrics.items():
            self._current[key].append(value)
            if len(self._current[key]) > self.window_size:
                # Move oldest to baseline
                self._baseline[key].append(self._current[key].pop(0))
                if len(self._baseline[key]) > self.window_size * 5:
                    self._baseline[key] = self._baseline[key][-self.window_size * 5 :]

        # Check drift after enough data
        if len(self._current.get("tokens", [])) < self.window_size // 2:
            return None

        return self._check_drift()

    def _check_drift(self) -> dict | None:
        """Compare current window vs baseline."""
        if not self._baseline.get("tokens"):
            return None

        drifts = {}
        for key in ["response_length", "tokens", "latency_ms"]:
            baseline_avg = sum(self._baseline[key]) / len(self._baseline[key])
            current_avg = sum(self._current[key]) / len(self._current[key])

            if baseline_avg == 0:
                continue

            deviation = abs(current_avg - baseline_avg) / baseline_avg

            if deviation > self.threshold:
                drifts[key] = {
                    "baseline_avg": round(baseline_avg, 2),
                    "current_avg": round(current_avg, 2),
                    "deviation_pct": round(deviation * 100, 1),
                }

        if drifts:
            alert = {
                "type": "drift_detected",
                "timestamp": time.time(),
                "metrics": drifts,
            }
            self._alerts.append(alert)
            logger.warning("drift_detected", **{k: v["deviation_pct"] for k, v in drifts.items()})
            return alert

        return None

    def get_stats(self) -> dict:
        return {
            "baseline_size": len(self._baseline.get("tokens", [])),
            "current_size": len(self._current.get("tokens", [])),
            "alerts": len(self._alerts),
            "recent_alerts": self._alerts[-3:],
        }


# --- LLM Summarization (#91) ---


async def summarize_messages(
    messages: list[dict],
    llm_chat_fn: object,
    max_summary_tokens: int = 200,
) -> str:
    """Summarize a list of messages into a concise summary using LLM.

    Used for warm→cold tier transition.
    """
    if not messages:
        return ""

    # Build conversation text
    conversation = "\n".join(f"{m['role']}: {m['content'][:500]}" for m in messages)

    summary_prompt = [
        {
            "role": "system",
            "content": (
                "Summarize this conversation concisely. "
                "Keep key facts, decisions, and context. "
                f"Maximum {max_summary_tokens} tokens."
            ),
        },
        {"role": "user", "content": conversation},
    ]

    if callable(llm_chat_fn):
        summary = await llm_chat_fn(summary_prompt, max_tokens=max_summary_tokens)
        logger.info(
            "messages_summarized",
            input_messages=len(messages),
            summary_length=len(summary),
        )
        return summary

    # Fallback: simple extractive summary
    key_messages = [m for m in messages if m["role"] in ("user", "assistant")]
    summary_parts = [m["content"][:100] for m in key_messages[-5:]]
    return " | ".join(summary_parts)


# --- Importance-weighted compression (#92) ---


def importance_weighted_trim(
    messages: list[dict],
    max_tokens: int,
    recency_weight: float = 0.5,
    relevance_weight: float = 0.3,
    role_weight: float = 0.2,
) -> list[dict]:
    """Trim messages by importance score: recency + relevance + role.

    More recent messages score higher.
    System messages always kept.
    User messages score higher than assistant.
    """
    if not messages:
        return messages

    system = [m for m in messages if m.get("role") == "system"]
    non_system = [m for m in messages if m.get("role") != "system"]

    if not non_system:
        return system

    # Score each message
    scored = []
    total = len(non_system)
    for i, msg in enumerate(non_system):
        # Recency: newer = higher (0 to 1)
        recency = (i + 1) / total

        # Role: user messages more important
        role_score = 0.8 if msg.get("role") == "user" else 0.5

        # Relevance: longer messages assumed more relevant
        content_len = len(msg.get("content", ""))
        relevance = min(content_len / 500, 1.0)

        score = recency * recency_weight + relevance * relevance_weight + role_score * role_weight

        scored.append((score, msg))

    # Sort by score descending
    scored.sort(key=lambda x: x[0], reverse=True)

    # Keep messages until budget exhausted
    kept = []
    budget = max_tokens - sum(get_token_count(m.get("content", "")) for m in system)

    for _score, msg in scored:
        tokens = get_token_count(msg.get("content", ""))
        if budget - tokens >= 0:
            kept.append(msg)
            budget -= tokens

    # Restore original order
    original_order = {id(m): i for i, m in enumerate(non_system)}
    kept.sort(key=lambda m: original_order.get(id(m), 0))

    return system + kept
