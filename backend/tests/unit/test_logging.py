"""Tests for structured logging and correlation ID management."""

from __future__ import annotations

import pytest

from app.observability.logging import (
    correlation_id_ctx,
    get_correlation_id,
    new_correlation_id,
    set_correlation_id,
    setup_logging,
)


@pytest.fixture(autouse=True)
def _reset_correlation_id() -> None:
    """Reset correlation ID between tests."""
    correlation_id_ctx.set("")


class TestCorrelationId:
    """Correlation ID management."""

    @pytest.mark.unit
    def test_get_generates_when_empty(self) -> None:
        cid = get_correlation_id()
        assert len(cid) == 36  # UUID format
        assert "-" in cid

    @pytest.mark.unit
    def test_get_returns_same_within_context(self) -> None:
        cid1 = get_correlation_id()
        cid2 = get_correlation_id()
        assert cid1 == cid2

    @pytest.mark.unit
    def test_set_and_get(self) -> None:
        set_correlation_id("test-123")
        assert get_correlation_id() == "test-123"

    @pytest.mark.unit
    def test_new_generates_fresh(self) -> None:
        cid1 = new_correlation_id()
        cid2 = new_correlation_id()
        assert cid1 != cid2
        assert get_correlation_id() == cid2


class TestStructuredLogging:
    """Structured log output."""

    @pytest.mark.unit
    def test_setup_logging_json_mode(self) -> None:
        """setup_logging(json_format=True) does not raise."""
        setup_logging(json_format=True)

    @pytest.mark.unit
    def test_setup_logging_dev_mode(self) -> None:
        """setup_logging(json_format=False) does not raise."""
        setup_logging(json_format=False, log_level="DEBUG")

    @pytest.mark.unit
    def test_correlation_id_processor_adds_to_event(self) -> None:
        """The add_correlation_id processor injects correlation_id."""
        from app.observability.logging import add_correlation_id

        set_correlation_id("req-abc-123")
        event_dict: dict = {"event": "test"}
        result = add_correlation_id(None, "info", event_dict)  # type: ignore[arg-type]
        assert result["correlation_id"] == "req-abc-123"

    @pytest.mark.unit
    def test_correlation_id_processor_skips_when_empty(self) -> None:
        """No correlation_id added when context is empty."""
        from app.observability.logging import add_correlation_id

        event_dict: dict = {"event": "test"}
        result = add_correlation_id(None, "info", event_dict)  # type: ignore[arg-type]
        assert "correlation_id" not in result
