"""Per-conversation cost tracking with truthful prompt-cache accounting."""

from __future__ import annotations

import time
from collections import defaultdict
from dataclasses import dataclass

import structlog

logger = structlog.get_logger()


@dataclass(frozen=True, slots=True)
class ModelPricing:
    """USD rates per 1K tokens; cache rates are explicit where published."""

    input: float
    output: float
    cache_read: float | None = None
    cache_write: float | None = None


# Source: provider pricing pages, reviewed Aug 2026. Rates are per 1K tokens.
MODEL_PRICING: dict[str, ModelPricing] = {
    "claude-opus-4-6": ModelPricing(0.015, 0.075, 0.0015, 0.01875),
    "claude-sonnet-4-20250514": ModelPricing(0.003, 0.015, 0.0003, 0.00375),
    "claude-haiku-3": ModelPricing(0.00025, 0.00125, 0.000025, 0.0003125),
    "gpt-4o": ModelPricing(0.0025, 0.01),
    "gpt-4o-mini": ModelPricing(0.00015, 0.0006),
    "gpt-4-turbo": ModelPricing(0.01, 0.03),
    "o1": ModelPricing(0.015, 0.06),
    "llama3.1:8b": ModelPricing(0.0, 0.0),
    "llava:7b": ModelPricing(0.0, 0.0),
    "mock-model": ModelPricing(0.0, 0.0),
    "default": ModelPricing(0.001, 0.002),
}
# Backward-compatible public table used by existing integrations/tests.
COST_PER_1K: dict[str, tuple[float, float]] = {
    model: (pricing.input, pricing.output) for model, pricing in MODEL_PRICING.items()
}


def _counter() -> dict:
    return {
        "tokens": 0,
        "cost_usd": 0.0,
        "calls": 0,
        "cache_read_input_tokens": None,
        "cache_write_input_tokens": None,
        "cache_savings_usd": None,
    }


class CostTracker:
    """Track token spend per conversation, per user, per day."""

    def __init__(self, alert_threshold_usd: float = 1.0) -> None:
        self.alert_threshold = alert_threshold_usd
        self._by_conversation: dict[str, dict] = defaultdict(_counter)
        self._by_user: dict[str, dict] = defaultdict(_counter)
        self._daily: dict[str, dict] = defaultdict(_counter)
        self._alerts: list[dict] = []

    def record(
        self,
        conversation_id: str,
        user_id: str,
        model: str,
        input_tokens: int,
        output_tokens: int,
        cache_read_input_tokens: int | None = None,
        cache_write_input_tokens: int | None = None,
        provider: str | None = None,
    ) -> dict:
        """Record total input/output and calculate provider cache-aware cost.

        ``input_tokens`` is total input. Cache subsets must fit inside it. An
        absent cache counter stays unknown; explicit zero remains observable.
        Unknown models use the default input rate for all input classes and
        therefore never receive an assumed cache discount.
        """
        del provider  # Reserved for provider-specific model-name collisions.
        counts = {
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "cache_read_input_tokens": cache_read_input_tokens,
            "cache_write_input_tokens": cache_write_input_tokens,
        }
        for name, value in counts.items():
            if value is not None and type(value) is not int:
                raise TypeError(f"{name} must be an int")
            if value is not None and value < 0:
                raise ValueError(f"{name} cannot be negative")

        cache_reported = cache_read_input_tokens is not None or cache_write_input_tokens is not None
        cache_read = cache_read_input_tokens or 0
        cache_write = cache_write_input_tokens or 0
        if cache_read + cache_write > input_tokens:
            raise ValueError("cache token subsets cannot exceed total input tokens")
        uncached_input = max(input_tokens - cache_read - cache_write, 0)

        known_model = model in MODEL_PRICING
        pricing = MODEL_PRICING.get(model, MODEL_PRICING["default"])
        cache_read_rate = pricing.cache_read if known_model else None
        cache_write_rate = pricing.cache_write if known_model else None
        # No published/known cache rate means no assumed discount or surcharge.
        read_rate = pricing.input if cache_read_rate is None else cache_read_rate
        write_rate = pricing.input if cache_write_rate is None else cache_write_rate
        baseline_cost = (input_tokens * pricing.input + output_tokens * pricing.output) / 1000
        cost = (
            uncached_input * pricing.input
            + cache_read * read_rate
            + cache_write * write_rate
            + output_tokens * pricing.output
        ) / 1000
        cache_savings = baseline_cost - cost if cache_reported else None
        total_tokens = input_tokens + output_tokens

        for tracker, key in [
            (self._by_conversation, conversation_id),
            (self._by_user, user_id),
            (self._daily, time.strftime("%Y-%m-%d")),
        ]:
            bucket = tracker[key]
            bucket["tokens"] += total_tokens
            bucket["cost_usd"] += cost
            bucket["calls"] += 1
            for field, value in (
                ("cache_read_input_tokens", cache_read_input_tokens),
                ("cache_write_input_tokens", cache_write_input_tokens),
                ("cache_savings_usd", cache_savings),
            ):
                if value is not None:
                    bucket[field] = (bucket[field] or 0) + value

        user_cost = self._by_user[user_id]["cost_usd"]
        if user_cost >= self.alert_threshold and len(self._alerts) < 100:
            alert = {
                "type": "cost_threshold",
                "user_id": user_id,
                "cost_usd": round(user_cost, 4),
                "threshold": self.alert_threshold,
                "timestamp": time.time(),
            }
            self._alerts.append(alert)
            logger.warning("cost_alert", **alert)

        return {
            "tokens": total_tokens,
            "cost_usd": round(cost, 6),
            "baseline_cost_usd": round(baseline_cost, 6),
            "model": model,
            "cache_read_input_tokens": cache_read_input_tokens,
            "cache_write_input_tokens": cache_write_input_tokens,
            "cache_savings_usd": None if cache_savings is None else round(cache_savings, 6),
        }

    def get_conversation_cost(self, conversation_id: str) -> dict:
        return dict(self._by_conversation.get(conversation_id, {}))

    def get_user_cost(self, user_id: str) -> dict:
        return dict(self._by_user.get(user_id, {}))

    def get_daily_cost(self, date: str = "") -> dict:
        date = date or time.strftime("%Y-%m-%d")
        return dict(self._daily.get(date, {}))

    def get_summary(self) -> dict:
        total_cost = sum(d["cost_usd"] for d in self._by_user.values())
        total_tokens = sum(d["tokens"] for d in self._by_user.values())
        return {
            "total_cost_usd": round(total_cost, 4),
            "total_tokens": total_tokens,
            "total_calls": sum(d["calls"] for d in self._by_user.values()),
            "users": len(self._by_user),
            "conversations": len(self._by_conversation),
            "alerts": len(self._alerts),
            "recent_alerts": self._alerts[-5:],
        }
