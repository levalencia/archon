"""Per-conversation cost tracking with truthful prompt-cache accounting."""

from __future__ import annotations

import time
from collections import defaultdict
from dataclasses import dataclass
from decimal import ROUND_CEILING, Decimal
from typing import Any

import structlog

logger = structlog.get_logger()

USD_TO_NUSD = 1_000_000_000
_MAX_BIGINT = 2**63 - 1


class UnknownModelPricing(ValueError):  # noqa: N818 - stable public domain name
    """Pricing enforcement cannot safely price a model."""

    def __init__(self, model: str) -> None:
        super().__init__("unknown_model_pricing")
        self.code = "unknown_model_pricing"
        self.model = model


@dataclass(frozen=True, slots=True)
class ModelPricing:
    """Exact USD rates per 1K tokens and provider families allowed to report them."""

    input: float
    output: float
    cache_read: float | None = None
    cache_write: float | None = None
    providers: frozenset[str] = frozenset()


# Source: provider pricing pages, reviewed Aug 2026. Rates are per 1K tokens.
# Decimal(str(rate)) below preserves the published decimal exactly; provider
# families prevent a known model name from laundering arbitrary provider usage.
MODEL_PRICING: dict[str, ModelPricing] = {
    "claude-opus-4-6": ModelPricing(
        0.005, 0.025, 0.0005, 0.00625, frozenset({"anthropic", "foundry"})
    ),
    "claude-sonnet-4-20250514": ModelPricing(
        0.003, 0.015, 0.0003, 0.00375, frozenset({"anthropic", "foundry"})
    ),
    "claude-haiku-3": ModelPricing(
        0.00025, 0.00125, 0.000025, 0.0003125, frozenset({"anthropic", "foundry"})
    ),
    "gpt-4o": ModelPricing(0.0025, 0.01, providers=frozenset({"openai", "foundry"})),
    "gpt-4o-mini": ModelPricing(0.00015, 0.0006, providers=frozenset({"openai", "foundry"})),
    "gpt-4-turbo": ModelPricing(0.01, 0.03, providers=frozenset({"openai", "foundry"})),
    "o1": ModelPricing(0.015, 0.06, providers=frozenset({"openai", "foundry"})),
    "llama3.1:8b": ModelPricing(0.0, 0.0, providers=frozenset({"ollama"})),
    "llava:7b": ModelPricing(0.0, 0.0, providers=frozenset({"ollama"})),
    "mock-model": ModelPricing(0.0, 0.0, providers=frozenset({"mock"})),
    # Kept for non-enforcing CostTracker compatibility; never accepted by the
    # exact budget pricing helpers.
    "default": ModelPricing(0.001, 0.002),
}
# Backward-compatible public table used by existing integrations/tests.
COST_PER_1K: dict[str, tuple[float, float]] = {
    model: (float(pricing.input), float(pricing.output)) for model, pricing in MODEL_PRICING.items()
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


def _supports_cache_pricing(provider: str) -> bool:
    """Recognize configured provider names and fallback adapter class names."""
    normalized = "".join(character for character in provider.casefold() if character.isalnum())
    return normalized in {"anthropic", "anthropicadapter", "foundry", "foundryadapter"}


def validated_pricing_pair(model: str, provider: str) -> tuple[str, str]:
    """Canonicalize an allowed provider/model pair for safe persistence."""
    if not isinstance(model, str) or not model or model == "default" or model not in MODEL_PRICING:
        raise UnknownModelPricing(str(model))
    if not isinstance(provider, str) or not provider:
        raise ValueError("provider must be a non-empty string")
    normalized = provider.casefold()
    aliases = {
        "openai": "openai",
        "openaiadapter": "openai",
        "anthropic": "anthropic",
        "anthropicadapter": "anthropic",
        "foundry": "foundry",
        "foundryadapter": "foundry",
        "ollama": "ollama",
        "ollamaadapter": "ollama",
        "mock": "mock",
    }
    family = aliases.get(normalized)
    if family is None or family not in MODEL_PRICING[model].providers:
        raise UnknownModelPricing(model)
    return family, model


def _token_count(value: int | None, name: str, *, optional: bool = False) -> int | None:
    if value is None and optional:
        return None
    if type(value) is not int:
        raise TypeError(f"{name} must be an int")
    if not 0 <= value <= _MAX_BIGINT:
        raise ValueError(f"{name} must be between 0 and {_MAX_BIGINT}")
    return value


def price_model_usage_nusd(
    model: str,
    provider: str,
    input_tokens: int,
    output_tokens: int,
    cache_read: int | None = None,
    cache_write: int | None = None,
) -> int:
    """Pure, exact nano-USD price for one provider usage report."""
    provider, model = validated_pricing_pair(model, provider)
    input_count = _token_count(input_tokens, "input_tokens")
    output_count = _token_count(output_tokens, "output_tokens")
    read_count = _token_count(cache_read, "cache_read", optional=True)
    write_count = _token_count(cache_write, "cache_write", optional=True)
    assert input_count is not None and output_count is not None
    read = read_count or 0
    write = write_count or 0
    if read + write > input_count:
        raise ValueError("cache token subsets cannot exceed total input tokens")

    pricing = MODEL_PRICING[model]
    cache_rates = _supports_cache_pricing(provider)
    read_rate = (
        pricing.cache_read if cache_rates and pricing.cache_read is not None else pricing.input
    )
    write_rate = (
        pricing.cache_write if cache_rates and pricing.cache_write is not None else pricing.input
    )
    amount = (
        (
            Decimal(input_count - read - write) * Decimal(str(pricing.input))
            + Decimal(read) * Decimal(str(read_rate))
            + Decimal(write) * Decimal(str(write_rate))
            + Decimal(output_count) * Decimal(str(pricing.output))
        )
        * Decimal(USD_TO_NUSD)
        / Decimal(1000)
    )
    integral = amount.to_integral_value(rounding=ROUND_CEILING)
    if not 0 <= integral <= _MAX_BIGINT:
        raise OverflowError("priced usage is outside the BIGINT nUSD range")
    return int(integral)


def quote_model_call_nusd(candidates: object, max_input_tokens: int, max_output_tokens: int) -> int:
    """Return the maximum quote across candidates and eligible input price classes."""
    _token_count(max_input_tokens, "max_input_tokens")
    _token_count(max_output_tokens, "max_output_tokens")
    if isinstance(candidates, (str, bytes)):
        raise ValueError("candidates must be a non-empty sequence")
    try:
        values = tuple(candidates)  # type: ignore[arg-type]
    except TypeError as exc:
        raise TypeError("candidates must be iterable") from exc
    if not values:
        raise ValueError("candidates must not be empty")
    quotes: list[int] = []
    for candidate in values:
        provider: Any
        model: Any
        if isinstance(candidate, (tuple, list)) and len(candidate) == 2:
            provider, model = candidate
        elif isinstance(candidate, dict):
            provider, model = candidate.get("provider"), candidate.get("model")
        else:
            provider, model = (
                getattr(candidate, "provider", None),
                getattr(candidate, "model", None),
            )
        if not isinstance(provider, str) or not provider or not isinstance(model, str) or not model:
            raise ValueError("each candidate must contain safe provider and model strings")
        provider, model = validated_pricing_pair(model, provider)
        candidate_quotes = [
            price_model_usage_nusd(model, provider, max_input_tokens, max_output_tokens)
        ]
        if _supports_cache_pricing(provider):
            pricing = MODEL_PRICING[model]
            if pricing.cache_read is not None:
                candidate_quotes.append(
                    price_model_usage_nusd(
                        model,
                        provider,
                        max_input_tokens,
                        max_output_tokens,
                        cache_read=max_input_tokens,
                    )
                )
            if pricing.cache_write is not None:
                candidate_quotes.append(
                    price_model_usage_nusd(
                        model,
                        provider,
                        max_input_tokens,
                        max_output_tokens,
                        cache_write=max_input_tokens,
                    )
                )
        quotes.append(max(candidate_quotes))
    return max(quotes)


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
        Unknown models and providers use the ordinary input rate for all input
        classes and therefore never receive an assumed cache discount.
        """
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
        input_rate, output_rate = float(pricing.input), float(pricing.output)
        cache_pricing_supported = provider is not None and _supports_cache_pricing(provider)
        cache_read_rate = (
            float(pricing.cache_read)
            if known_model and cache_pricing_supported and pricing.cache_read is not None
            else None
        )
        cache_write_rate = (
            float(pricing.cache_write)
            if known_model and cache_pricing_supported and pricing.cache_write is not None
            else None
        )
        # No published/known cache rate means no assumed discount or surcharge.
        read_rate = input_rate if cache_read_rate is None else cache_read_rate
        write_rate = input_rate if cache_write_rate is None else cache_write_rate
        baseline_cost = (input_tokens * input_rate + output_tokens * output_rate) / 1000
        cost = (
            uncached_input * input_rate
            + cache_read * read_rate
            + cache_write * write_rate
            + output_tokens * output_rate
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
