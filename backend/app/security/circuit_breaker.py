"""Circuit breaker for protecting against dead external services.

State machine: CLOSED → OPEN → HALF_OPEN → CLOSED (or back to OPEN).

See: https://github.com/levalencia/production-ai-agents/
Concept: Layer 5 - Guardrails (circuit breaker for resilience)
Course reference: AIAMastery Day 4 - Resilient Agent
"""

from __future__ import annotations

import asyncio
import time
from enum import Enum

import structlog

logger = structlog.get_logger()


class CircuitState(Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class CircuitBreakerOpen(Exception):
    """Raised when circuit is open and rejecting calls."""

    def __init__(self, recovery_time: float) -> None:
        self.recovery_time = recovery_time
        super().__init__(f"Circuit breaker is open. Recovery in {recovery_time:.1f}s")


class CircuitBreaker:
    """Circuit breaker with CLOSED/OPEN/HALF_OPEN states.

    - CLOSED: normal operation, failures counted
    - OPEN: all calls rejected instantly (fail fast)
    - HALF_OPEN: one trial call allowed; success → CLOSED, failure → OPEN
    """

    def __init__(
        self,
        failure_threshold: int = 5,
        recovery_timeout: float = 30.0,
        name: str = "default",
    ) -> None:
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.name = name

        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._last_failure_time = 0.0
        self._success_count = 0
        self._total_calls = 0

    @property
    def state(self) -> CircuitState:
        """Current state, considering recovery timeout."""
        if self._state == CircuitState.OPEN:
            elapsed = time.time() - self._last_failure_time
            if elapsed >= self.recovery_timeout:
                return CircuitState.HALF_OPEN
        return self._state

    async def call(self, func: object, *args: object, **kwargs: object) -> object:
        """Execute a function through the circuit breaker."""
        self._total_calls += 1
        current_state = self.state

        if current_state == CircuitState.OPEN:
            remaining = self.recovery_timeout - (time.time() - self._last_failure_time)
            logger.warning(
                "circuit_breaker_rejected",
                name=self.name,
                state="open",
                recovery_in=round(remaining, 1),
            )
            raise CircuitBreakerOpen(remaining)

        if current_state == CircuitState.HALF_OPEN:
            logger.info("circuit_breaker_trial", name=self.name)

        try:
            if asyncio.iscoroutinefunction(func):
                result = await func(*args, **kwargs)  # type: ignore[misc]
            else:
                result = func(*args, **kwargs)  # type: ignore[misc]

            self._on_success()
            return result

        except CircuitBreakerOpen:
            raise
        except Exception:
            self._on_failure()
            raise

    def _on_success(self) -> None:
        """Handle successful call."""
        if self._state in (CircuitState.HALF_OPEN, CircuitState.OPEN):
            logger.info(
                "circuit_breaker_closed",
                name=self.name,
                previous_state=self._state.value,
            )
        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._success_count += 1

    def _on_failure(self) -> None:
        """Handle failed call."""
        self._failure_count += 1
        self._last_failure_time = time.time()

        if self._failure_count >= self.failure_threshold:
            self._state = CircuitState.OPEN
            logger.error(
                "circuit_breaker_opened",
                name=self.name,
                failure_count=self._failure_count,
                threshold=self.failure_threshold,
            )
        else:
            logger.warning(
                "circuit_breaker_failure",
                name=self.name,
                failure_count=self._failure_count,
                threshold=self.failure_threshold,
            )

    def get_stats(self) -> dict:
        """Get circuit breaker statistics."""
        return {
            "name": self.name,
            "state": self.state.value,
            "failure_count": self._failure_count,
            "failure_threshold": self.failure_threshold,
            "success_count": self._success_count,
            "total_calls": self._total_calls,
            "recovery_timeout": self.recovery_timeout,
        }

    def reset(self) -> None:
        """Manually reset the circuit breaker."""
        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._success_count = 0
        logger.info("circuit_breaker_reset", name=self.name)
