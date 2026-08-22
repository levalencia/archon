"""Per-conversation cost tracking with alerting thresholds."""

from __future__ import annotations

import time
from collections import defaultdict

import structlog

logger = structlog.get_logger()

# Cost per 1K tokens (approximate, configurable)
COST_PER_1K = {
    "llama3.1:8b": 0.0,  # Local, free
    "llava:7b": 0.0,
    "gpt-4o": 0.005,
    "gpt-4o-mini": 0.00015,
    "claude-opus-4-6": 0.015,
    "claude-sonnet-4-20250514": 0.003,
    "default": 0.001,
}


class CostTracker:
    """Track token spend per conversation, per user, per day."""

    def __init__(self, alert_threshold_usd: float = 1.0) -> None:
        self.alert_threshold = alert_threshold_usd
        self._by_conversation: dict[str, dict] = defaultdict(
            lambda: {"tokens": 0, "cost_usd": 0.0, "calls": 0}
        )
        self._by_user: dict[str, dict] = defaultdict(
            lambda: {"tokens": 0, "cost_usd": 0.0, "calls": 0}
        )
        self._daily: dict[str, dict] = defaultdict(
            lambda: {"tokens": 0, "cost_usd": 0.0, "calls": 0}
        )
        self._alerts: list[dict] = []

    def record(
        self,
        conversation_id: str,
        user_id: str,
        model: str,
        input_tokens: int,
        output_tokens: int,
    ) -> dict:
        """Record token usage and calculate cost."""
        total_tokens = input_tokens + output_tokens
        rate = COST_PER_1K.get(model, COST_PER_1K["default"])
        cost = (total_tokens / 1000) * rate

        # Update counters
        for tracker, key in [
            (self._by_conversation, conversation_id),
            (self._by_user, user_id),
            (self._daily, time.strftime("%Y-%m-%d")),
        ]:
            tracker[key]["tokens"] += total_tokens
            tracker[key]["cost_usd"] += cost
            tracker[key]["calls"] += 1

        # Check alert threshold
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
            "model": model,
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
