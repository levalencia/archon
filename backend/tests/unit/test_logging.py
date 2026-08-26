"""Tests for structured logging, correlation IDs, and global redaction."""

from __future__ import annotations

import json

import pytest
import structlog

from app.observability.logging import (
    correlation_id_ctx,
    get_correlation_id,
    new_correlation_id,
    redact_event,
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
        assert len(cid) == 36
        assert "-" in cid

    @pytest.mark.unit
    def test_get_returns_same_within_context(self) -> None:
        assert get_correlation_id() == get_correlation_id()

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
        setup_logging(json_format=True)

    @pytest.mark.unit
    def test_setup_logging_dev_mode(self) -> None:
        setup_logging(json_format=False, log_level="DEBUG")

    @pytest.mark.unit
    def test_correlation_id_processor_adds_to_event(self) -> None:
        from app.observability.logging import add_correlation_id

        set_correlation_id("req-abc-123")
        event_dict: dict = {"event": "test"}
        result = add_correlation_id(None, "info", event_dict)  # type: ignore[arg-type]
        assert result["correlation_id"] == "req-abc-123"

    @pytest.mark.unit
    def test_correlation_id_processor_skips_when_empty(self) -> None:
        from app.observability.logging import add_correlation_id

        event_dict: dict = {"event": "test"}
        result = add_correlation_id(None, "info", event_dict)  # type: ignore[arg-type]
        assert "correlation_id" not in result

    @pytest.mark.unit
    def test_redaction_processor_handles_nested_keys_values_and_collisions(self) -> None:
        secrets = (
            "first@example.com",
            "second@example.com",
            "123-45-6789",
            "4111-1111-1111-1111",
            "202-555-0147",
            "super-secret-value",
        )
        result = redact_event(
            None,  # type: ignore[arg-type]
            "info",
            {
                "event": "contact first@example.com",
                "nested": {
                    "first@example.com": ["123-45-6789", ("202-555-0147",)],
                    "second@example.com": "4111-1111-1111-1111",
                    "api_key": "super-secret-value",
                },
                "count": 4,
            },
        )

        serialized = json.dumps(result)
        assert all(secret not in serialized for secret in secrets)
        assert result["count"] == 4
        assert result["nested"]["[EMAIL]"][0] == "[SSN]"
        assert result["nested"]["[EMAIL]__2"] == "[CREDIT_CARD]"
        assert result["nested"]["api_key"] == "[REDACTED]"

    @pytest.mark.unit
    def test_json_sink_redacts_pii_credentials_and_formatted_exception(self, capsys) -> None:
        setup_logging(json_format=True)
        try:
            raise ValueError("private.user@example.com 123-45-6789")
        except ValueError:
            structlog.get_logger().exception(
                "failed for 202-555-0147",
                nested={"4111-1111-1111-1111": "token=top-secret"},
            )

        rendered = capsys.readouterr().out
        for secret in (
            "private.user@example.com",
            "123-45-6789",
            "202-555-0147",
            "4111-1111-1111-1111",
            "top-secret",
        ):
            assert secret not in rendered
        assert "[EMAIL]" in rendered
        assert "[SSN]" in rendered
