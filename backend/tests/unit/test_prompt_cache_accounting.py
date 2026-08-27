"""Truthful provider prompt-cache usage and cost-accounting contracts."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import pytest

from app.agents.anthropic_adapter import AnthropicAdapter
from app.agents.foundry_adapter import FoundryAdapter
from app.agents.llm_factory import _create_single_client
from app.config import Settings
from app.observability.cost_tracker import CostTracker
from app.runtime.anthropic import normalize_anthropic_usage
from app.runtime.models import TokenUsage


@pytest.mark.unit
@pytest.mark.parametrize(
    ("usage", "expected"),
    [
        ({"input_tokens": 11, "output_tokens": 3}, TokenUsage(11, 3)),
        (
            {
                "input_tokens": 11,
                "output_tokens": 3,
                "cache_creation_input_tokens": 0,
                "cache_read_input_tokens": 0,
            },
            TokenUsage(11, 3, cache_read_input_tokens=0, cache_write_input_tokens=0),
        ),
        (
            SimpleNamespace(
                input_tokens=11,
                output_tokens=3,
                cache_creation_input_tokens=5,
                cache_read_input_tokens=7,
            ),
            TokenUsage(23, 3, cache_read_input_tokens=7, cache_write_input_tokens=5),
        ),
    ],
)
def test_anthropic_usage_normalizer_preserves_absent_zero_and_reported(usage, expected) -> None:
    assert normalize_anthropic_usage(usage) == expected


@pytest.mark.unit
@pytest.mark.parametrize(
    "usage",
    [
        {"input_tokens": True, "output_tokens": 1},
        {"input_tokens": "1", "output_tokens": 1},
        {"input_tokens": 1, "output_tokens": -1},
        {"input_tokens": 1, "output_tokens": 1, "cache_read_input_tokens": False},
        {"input_tokens": 1, "output_tokens": 1, "cache_creation_input_tokens": -1},
    ],
)
def test_anthropic_usage_normalizer_rejects_malformed_before_recording(usage) -> None:
    with pytest.raises((TypeError, ValueError)):
        normalize_anthropic_usage(usage)


@pytest.mark.unit
def test_cache_capability_follows_configuration() -> None:
    for adapter_type, args in (
        (AnthropicAdapter, ("key",)),
        (FoundryAdapter, ("key", "https://example.com")),
    ):
        enabled = adapter_type(*args, prompt_caching_enabled=True)
        disabled = adapter_type(*args, prompt_caching_enabled=False)
        assert enabled.capabilities.prompt_caching and enabled.capabilities.cache_usage
        assert not disabled.capabilities.prompt_caching and not disabled.capabilities.cache_usage


@pytest.mark.unit
@pytest.mark.parametrize("provider", ["anthropic", "foundry"])
def test_factory_passes_prompt_cache_setting(provider: str) -> None:
    settings = Settings(
        llm_provider=provider,
        llm_api_key="key",
        llm_base_url="https://example.com",
        prompt_caching_enabled=False,
    )
    target = (
        "app.agents.anthropic_adapter.AnthropicAdapter"
        if provider == "anthropic"
        else "app.agents.foundry_adapter.FoundryAdapter"
    )
    with patch(target) as adapter:
        _create_single_client(provider, settings)
    assert adapter.call_args.kwargs["prompt_caching_enabled"] is False


@pytest.mark.unit
def test_cost_tracker_distinguishes_unknown_zero_read_write_and_accumulates() -> None:
    tracker = CostTracker()
    unknown = tracker.record("c", "u", "claude-sonnet-4-20250514", 1000, 0)
    zero = tracker.record(
        "c",
        "u",
        "claude-sonnet-4-20250514",
        1000,
        0,
        cache_read_input_tokens=0,
        cache_write_input_tokens=0,
        provider="anthropic",
    )
    cached = tracker.record(
        "c",
        "u",
        "claude-sonnet-4-20250514",
        1000,
        0,
        cache_read_input_tokens=800,
        cache_write_input_tokens=100,
        provider="anthropic",
    )

    assert unknown["cache_read_input_tokens"] is None
    assert unknown["cache_savings_usd"] is None
    assert zero["cache_read_input_tokens"] == 0
    assert zero["cache_savings_usd"] == 0
    assert cached["cache_read_input_tokens"] == 800
    assert cached["cache_write_input_tokens"] == 100
    assert cached["cache_savings_usd"] > 0
    totals = tracker.get_conversation_cost("c")
    assert totals["cache_read_input_tokens"] == 800
    assert totals["cache_write_input_tokens"] == 100
    assert totals["cache_savings_usd"] == cached["cache_savings_usd"]


@pytest.mark.unit
def test_unknown_model_assumes_no_cache_discount_and_invalid_subsets_fail() -> None:
    tracker = CostTracker()
    info = tracker.record(
        "c",
        "u",
        "unknown",
        100,
        0,
        cache_read_input_tokens=100,
        cache_write_input_tokens=0,
        provider="other",
    )
    assert info["cache_savings_usd"] == 0
    with pytest.raises(ValueError, match="cannot exceed total input"):
        tracker.record(
            "c",
            "u",
            "unknown",
            10,
            0,
            cache_read_input_tokens=8,
            cache_write_input_tokens=3,
        )
