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
    redact_sensitive,
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
    def test_compound_credential_keys_are_normalized_without_false_positives(self) -> None:
        opaque_values = {
            "client_secret": "opaque-snake-secret",
            "private_key": "opaque-private-key",
            "refresh_token": "opaque-refresh-token",
            "clientSecret": "opaque-client-secret",
            "privateKey": "opaque-camel-private-key",
            "refreshToken": "opaque-camel-refresh-token",
            "apiKey": "opaque-api-key",
            "access-token": "opaque-access-token",
            "Signing.Key": "opaque-signing-key",
            "ENCRYPTION KEY": "opaque-encryption-key",
            "masterKey": "opaque-master-key",
            "public_key": "opaque-public-key",
            "servicekey": "opaque-key-suffix",
            "sessiontoken": "opaque-token-suffix",
            "sharedsecret": "opaque-secret-suffix",
            "ａｐｉＫｅｙ": "opaque-unicode-api-key",
            f"{'x' * 300}Token": "opaque-overlong-token",
        }
        result = redact_event(
            None,  # type: ignore[arg-type]
            "info",
            {
                "nested": {**opaque_values, 7: {"clientSecret": "opaque-nested-secret"}},
                "monkey": "capuchin",
                "hockey_score": 4,
                "token_count": 17,
                "source_url": "https://docs.example.test/public",
            },
        )

        assert all(result["nested"][key] == "[REDACTED]" for key in opaque_values)
        assert result["nested"][7]["clientSecret"] == "[REDACTED]"
        assert result["monkey"] == "capuchin"
        assert result["hockey_score"] == 4
        assert result["token_count"] == 17
        assert result["source_url"] == "https://docs.example.test/public"

    @pytest.mark.unit
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("secret=top-secret retry=true", "secret=[REDACTED] retry=true"),
            ("Bearer standalone-token next", "Bearer [REDACTED] next"),
            ("cookie=session-cookie; status=failed", "cookie=[REDACTED]; status=failed"),
            (
                "authorization: Basic dXNlcjpwYXNz next",
                "authorization: Basic [REDACTED] next",
            ),
            ("AUTH=Bearer AbC.123-xy next", "AUTH=Bearer [REDACTED] next"),
            ("Api Key: 'quoted secret value' safe", "Api Key: '[REDACTED]' safe"),
            ("passwd=bad-pass, attempt=2", "passwd=[REDACTED], attempt=2"),
            (
                "connect postgresql://db-user:db-pass@private-db.internal/app now",
                "connect postgresql://[REDACTED]@private-db.internal/app now",
            ),
        ],
    )
    def test_free_form_credential_redaction_is_bounded(self, raw: str, expected: str) -> None:
        assert redact_sensitive(raw) == expected

    @pytest.mark.unit
    def test_sensitive_mixed_case_nested_mapping_keys_are_fully_redacted(self) -> None:
        result = redact_event(
            None,  # type: ignore[arg-type]
            "info",
            {
                "nested": {
                    "DaTaBaSe_Url": "postgresql://db-user:db-pass@private-db.internal/app",
                    "Connection_String": "Server=private-db;Password=bad-pass",
                    "AUTHORIZATION": "Basic dXNlcjpwYXNz",
                    "Set-Cookie": "session=session-cookie",
                    "SeCrEt": "top-secret",
                    "URL": "https://private.example/path",
                    "uRi": "redis://cache.internal/0",
                    "DSN": "host=db.internal user=admin",
                    "source_url": "https://public.example/docs",
                }
            },
        )

        assert result["nested"] == {
            "DaTaBaSe_Url": "[REDACTED]",
            "Connection_String": "[REDACTED]",
            "AUTHORIZATION": "[REDACTED]",
            "Set-Cookie": "[REDACTED]",
            "SeCrEt": "[REDACTED]",
            "URL": "[REDACTED]",
            "uRi": "[REDACTED]",
            "DSN": "[REDACTED]",
            "source_url": "https://public.example/docs",
        }

    @pytest.mark.unit
    @pytest.mark.parametrize("json_format", [True, False])
    def test_rendered_sinks_redact_normalized_credential_keys(
        self, capsys, json_format: bool
    ) -> None:
        setup_logging(json_format=json_format)
        opaque_values = (
            "rendered-snake-value",
            "rendered-kebab-value",
            "rendered-camel-value",
            "rendered-mixed-value",
        )

        structlog.get_logger().info(
            "credential fields",
            nested={
                "client_secret": opaque_values[0],
                "access-token": opaque_values[1],
                "privateKey": opaque_values[2],
                "API.Key": opaque_values[3],
            },
        )

        rendered = capsys.readouterr().out
        assert all(value not in rendered for value in opaque_values)
        assert rendered.count("[REDACTED]") >= len(opaque_values)

    @pytest.mark.unit
    @pytest.mark.parametrize("json_format", [True, False])
    def test_rendered_sinks_redact_free_form_credentials_and_credential_uris(
        self, capsys, json_format: bool
    ) -> None:
        setup_logging(json_format=json_format)
        try:
            raise RuntimeError(
                "secret=top-secret cookie=session-cookie "
                "authorization: Basic dXNlcjpwYXNz "
                "postgresql://db-user:db-pass@private-db.internal/app"
            )
        except RuntimeError:
            structlog.get_logger().exception("credential failure")

        rendered = capsys.readouterr().out
        for secret in (
            "top-secret",
            "session-cookie",
            "dXNlcjpwYXNz",
            "db-user",
            "db-pass",
        ):
            assert secret not in rendered
        assert rendered.count("[REDACTED]") >= 4

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
