"""Truthful provider prompt-cache usage and cost-accounting contracts."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import pytest

from app.agents.anthropic_adapter import AnthropicAdapter
from app.agents.foundry_adapter import FoundryAdapter
from app.agents.llm_factory import _create_single_client
from app.config import Settings
from app.observability.cost_tracker import MODEL_PRICING, CostTracker
from app.routes.stream import ResponseCostEventSink
from app.runtime import AgentEvent, AgentEventKind, RecordingEventSink
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


@pytest.mark.unit
def test_opus_46_pricing_uses_current_per_1k_rates() -> None:
    pricing = MODEL_PRICING["claude-opus-4-6"]
    assert (pricing.input, pricing.output, pricing.cache_read, pricing.cache_write) == (
        0.005,
        0.025,
        0.0005,
        0.00625,
    )


@pytest.mark.unit
@pytest.mark.parametrize(
    "supported_provider", ["anthropic", "AnthropicAdapter", "foundry", "FoundryAdapter"]
)
def test_claude_cache_rates_require_anthropic_compatible_provider(
    supported_provider: str,
) -> None:
    tracker = CostTracker()
    supported = tracker.record(
        "supported-conversation",
        "u",
        "claude-opus-4-6",
        1000,
        0,
        cache_read_input_tokens=1000,
        provider=f" {supported_provider} ",
    )
    unrecognized = tracker.record(
        "other-conversation",
        "u",
        "claude-opus-4-6",
        1000,
        0,
        cache_read_input_tokens=1000,
        provider="OpenAIAdapter",
    )

    assert supported["cost_usd"] == 0.0005
    assert supported["cache_savings_usd"] == 0.0045
    assert unrecognized["cost_usd"] == 0.005
    assert unrecognized["cache_savings_usd"] == 0


@pytest.mark.unit
@pytest.mark.asyncio
async def test_response_cost_sink_prices_each_actual_winner_once_and_forwards_every_event() -> None:
    downstream = RecordingEventSink()
    sink = ResponseCostEventSink(
        conversation_id="c",
        user_id="u",
        default_provider="anthropic",
        default_model="claude-opus-4-6",
        downstream=downstream,
    )
    events = [
        AgentEvent(AgentEventKind.ITERATION_STARTED, 1),
        AgentEvent(
            AgentEventKind.MODEL_RESPONSE,
            1,
            {"actual_provider": "AnthropicAdapter", "actual_model": "claude-opus-4-6"},
            TokenUsage(1000, 100, 800, 100),
        ),
        AgentEvent(AgentEventKind.ITERATION_STARTED, 2),
        AgentEvent(
            AgentEventKind.MODEL_RESPONSE,
            2,
            {"actual_provider": "OpenAIAdapter", "actual_model": "gpt-4o"},
            TokenUsage(1000, 100),
        ),
    ]
    for event in events:
        await sink.emit(event)

    assert downstream.events == events
    assert sink.totals == {
        "cost_usd": 0.007525,
        "cache_read_input_tokens": 800,
        "cache_write_input_tokens": 100,
        "cache_savings_usd": 0.003475,
    }
    assert sink.calls == 2


@pytest.mark.unit
@pytest.mark.asyncio
async def test_response_cost_sink_falls_back_for_unsafe_blank_actual_identity() -> None:
    sink = ResponseCostEventSink(
        conversation_id="c",
        user_id="u",
        default_provider="anthropic",
        default_model="claude-opus-4-6",
    )
    await sink.emit(
        AgentEvent(
            AgentEventKind.MODEL_RESPONSE,
            1,
            {"actual_provider": "  ", "actual_model": "\n"},
            TokenUsage(1000, 0, 1000, 0),
        )
    )

    assert sink.totals["cost_usd"] == 0.0005


@pytest.mark.unit
@pytest.mark.asyncio
async def test_response_cost_sink_without_model_response_has_zero_unknown_totals() -> None:
    sink = ResponseCostEventSink(
        conversation_id="c",
        user_id="u",
        default_provider="anthropic",
        default_model="claude-opus-4-6",
    )
    await sink.emit(AgentEvent(AgentEventKind.RUN_STARTED, 0))

    assert sink.calls == 0
    assert sink.totals == {
        "cost_usd": 0.0,
        "cache_read_input_tokens": None,
        "cache_write_input_tokens": None,
        "cache_savings_usd": None,
    }
