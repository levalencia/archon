"""Tests for PII detection and circuit breaker."""

from __future__ import annotations

import asyncio

import pytest

from app.runtime.capabilities import ProviderCapabilities, UnsupportedProviderCapability
from app.runtime.models import Message, Role
from app.security.circuit_breaker import (
    CircuitBreaker,
    CircuitBreakerOpenError,
    CircuitBreakingProvider,
    CircuitState,
)
from app.security.pii_detector import PIIDetector


class TestPIIDetection:
    """PII detection tests."""

    @pytest.fixture
    def detector(self) -> PIIDetector:
        return PIIDetector()

    @pytest.mark.security
    def test_detects_email(self, detector: PIIDetector) -> None:
        entities = detector.detect("Contact me at john@example.com please")
        assert len(entities) >= 1
        assert any(e.entity_type == "email" for e in entities)

    @pytest.mark.security
    def test_detects_ssn(self, detector: PIIDetector) -> None:
        entities = detector.detect("My SSN is 123-45-6789")
        assert len(entities) >= 1
        ssn = [e for e in entities if e.entity_type == "ssn"]
        assert len(ssn) >= 1
        assert ssn[0].risk_level == "high"

    @pytest.mark.security
    def test_detects_credit_card(self, detector: PIIDetector) -> None:
        entities = detector.detect("Card: 4111-1111-1111-1111")
        assert len(entities) >= 1
        assert any(e.entity_type == "credit_card" for e in entities)

    @pytest.mark.security
    def test_detects_multiple_pii(self, detector: PIIDetector) -> None:
        text = "Email: test@mail.com, SSN: 123-45-6789"
        entities = detector.detect(text)
        types = {e.entity_type for e in entities}
        assert "email" in types
        assert "ssn" in types

    @pytest.mark.security
    def test_no_pii_returns_empty(self, detector: PIIDetector) -> None:
        entities = detector.detect("This text has no personal information")
        assert len(entities) == 0

    @pytest.mark.security
    def test_redact_replaces_pii(self, detector: PIIDetector) -> None:
        text = "Email: john@example.com"
        redacted = detector.redact(text)
        assert "john@example.com" not in redacted
        assert "[EMAIL]" in redacted

    @pytest.mark.security
    def test_redact_preserves_non_pii(self, detector: PIIDetector) -> None:
        text = "Hello, how are you?"
        assert detector.redact(text) == text

    @pytest.mark.security
    def test_risk_assessment_high(self, detector: PIIDetector) -> None:
        assert detector.assess_risk("SSN: 123-45-6789") == "high"

    @pytest.mark.security
    def test_risk_assessment_none(self, detector: PIIDetector) -> None:
        assert detector.assess_risk("Safe text") == "none"


class TestCircuitBreaker:
    """Circuit breaker state machine tests."""

    @pytest.mark.unit
    def test_starts_closed(self) -> None:
        cb = CircuitBreaker(failure_threshold=3)
        assert cb.state == CircuitState.CLOSED

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_success_stays_closed(self) -> None:
        cb = CircuitBreaker(failure_threshold=3)
        result = await cb.call(lambda: "ok")
        assert result == "ok"
        assert cb.state == CircuitState.CLOSED

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_capability_rejection_is_propagated_without_counting_as_failure(self) -> None:
        class RejectingProvider:
            routes_capabilities = True
            capabilities = ProviderCapabilities(usage=True)

            async def complete(self, messages, tools=(), **kwargs):
                del messages, tools, kwargs
                raise UnsupportedProviderCapability("delegate", ("usage",))

        breaker = CircuitBreaker(failure_threshold=1)
        provider = CircuitBreakingProvider(RejectingProvider(), breaker)

        with pytest.raises(UnsupportedProviderCapability):
            await provider.complete(
                [Message(Role.USER, "go")],
                required_capabilities=ProviderCapabilities(usage=True),
            )

        assert breaker.state is CircuitState.CLOSED
        assert breaker.get_stats()["failure_count"] == 0

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_opens_after_threshold_failures(self) -> None:
        cb = CircuitBreaker(failure_threshold=2)

        def failing() -> None:
            raise ConnectionError("down")

        for _ in range(2):
            with pytest.raises(ConnectionError):
                await cb.call(failing)

        assert cb.state == CircuitState.OPEN

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_open_rejects_calls(self) -> None:
        cb = CircuitBreaker(failure_threshold=1, recovery_timeout=60)

        with pytest.raises(ConnectionError):
            await cb.call(lambda: (_ for _ in ()).throw(ConnectionError("fail")))

        with pytest.raises(CircuitBreakerOpenError):
            await cb.call(lambda: "should not run")

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_half_open_after_recovery(self) -> None:
        cb = CircuitBreaker(failure_threshold=1, recovery_timeout=0.1)

        with pytest.raises(ConnectionError):
            await cb.call(lambda: (_ for _ in ()).throw(ConnectionError("fail")))

        assert cb.state == CircuitState.OPEN

        import asyncio

        await asyncio.sleep(0.15)  # Wait for recovery
        assert cb.state == CircuitState.HALF_OPEN

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_half_open_success_closes(self) -> None:
        cb = CircuitBreaker(failure_threshold=1, recovery_timeout=0.1)

        with pytest.raises(ConnectionError):
            await cb.call(lambda: (_ for _ in ()).throw(ConnectionError("fail")))

        import asyncio

        await asyncio.sleep(0.15)
        result = await cb.call(lambda: "recovered")
        assert result == "recovered"
        assert cb.state == CircuitState.CLOSED

    @pytest.mark.unit
    def test_get_stats(self) -> None:
        cb = CircuitBreaker(name="llm-provider")
        stats = cb.get_stats()
        assert stats["name"] == "llm-provider"
        assert stats["state"] == "closed"
        assert stats["failure_count"] == 0

    @pytest.mark.unit
    def test_reset(self) -> None:
        cb = CircuitBreaker(failure_threshold=1)
        cb._failure_count = 10
        cb._state = CircuitState.OPEN
        cb.reset()
        assert cb.state == CircuitState.CLOSED
        assert cb._failure_count == 0

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_only_one_half_open_probe_runs_and_success_closes(self) -> None:
        now = 0.0
        cb = CircuitBreaker(failure_threshold=1, recovery_timeout=5, clock=lambda: now)

        with pytest.raises(ConnectionError):
            await cb.call(lambda: (_ for _ in ()).throw(ConnectionError("sensitive failure")))
        now = 6.0
        entered = asyncio.Event()
        release = asyncio.Event()
        calls = 0

        async def probe() -> str:
            nonlocal calls
            calls += 1
            entered.set()
            await release.wait()
            return "recovered"

        first = asyncio.create_task(cb.call(probe))
        await entered.wait()
        with pytest.raises(CircuitBreakerOpenError) as rejected:
            await cb.call(probe)
        assert str(rejected.value) == "Model provider temporarily unavailable"
        release.set()

        assert await first == "recovered"
        assert calls == 1
        assert cb.state is CircuitState.CLOSED

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_stale_success_cannot_close_after_concurrent_failure_opens(self) -> None:
        cb = CircuitBreaker(failure_threshold=1, recovery_timeout=60)
        entered = asyncio.Event()
        release = asyncio.Event()

        async def slow_success() -> str:
            entered.set()
            await release.wait()
            return "late"

        stale = asyncio.create_task(cb.call(slow_success))
        await entered.wait()
        with pytest.raises(ConnectionError):
            await cb.call(lambda: (_ for _ in ()).throw(ConnectionError("down")))
        release.set()
        assert await stale == "late"
        assert cb.state is CircuitState.OPEN

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_cancelled_half_open_probe_returns_to_open_then_allows_one_probe(self) -> None:
        now = 0.0
        cb = CircuitBreaker(failure_threshold=1, recovery_timeout=5, clock=lambda: now)
        with pytest.raises(ConnectionError):
            await cb.call(lambda: (_ for _ in ()).throw(ConnectionError("down")))
        now = 6.0
        entered = asyncio.Event()

        async def probe() -> str:
            entered.set()
            await asyncio.Event().wait()
            return "unreachable"

        task = asyncio.create_task(cb.call(probe))
        await entered.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert cb.state is CircuitState.OPEN

        now = 12.0
        assert await cb.call(lambda: "recovered") == "recovered"
        assert cb.state is CircuitState.CLOSED
