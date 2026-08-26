"""Concurrency-safe circuit breaker and typed model-provider adapter."""

from __future__ import annotations

import asyncio
import inspect
import time
from collections.abc import Awaitable, Callable, Sequence
from enum import Enum
from typing import Any, TypeVar

import structlog

from app.runtime.models import Message, ModelResponse, ToolDefinition
from app.runtime.ports import ModelProvider

logger = structlog.get_logger()
_T = TypeVar("_T")


class CircuitState(Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class CircuitBreakerOpenError(RuntimeError):
    """Sanitized fail-fast signal; never includes provider errors or prompts."""

    def __init__(self, recovery_time: float) -> None:
        self.recovery_time = max(0.0, recovery_time)
        super().__init__("Model provider temporarily unavailable")


class ProviderUnavailableError(RuntimeError):
    """Stable provider boundary error suitable for API handling."""


class CircuitBreaker:
    def __init__(
        self,
        failure_threshold: int = 5,
        recovery_timeout: float = 30.0,
        name: str = "default",
        *,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if failure_threshold < 1:
            raise ValueError("failure_threshold must be positive")
        if recovery_timeout <= 0:
            raise ValueError("recovery_timeout must be positive")
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.name = name
        self._clock = clock
        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._last_failure_time = 0.0
        self._success_count = 0
        self._total_calls = 0
        self._probe_in_flight = False
        self._epoch = 0
        self._generation = 0
        self._probe_token: object | None = None
        self._lock = asyncio.Lock()

    @property
    def state(self) -> CircuitState:
        if (
            self._state is CircuitState.OPEN
            and self._clock() - self._last_failure_time >= self.recovery_timeout
        ):
            return CircuitState.HALF_OPEN
        return self._state

    async def call(
        self, func: Callable[..., _T | Awaitable[_T]], *args: object, **kwargs: object
    ) -> _T:
        is_probe = False
        probe_token: object | None = None
        async with self._lock:
            current = self.state
            if current is CircuitState.OPEN or (
                current is CircuitState.HALF_OPEN and self._probe_in_flight
            ):
                remaining = self.recovery_timeout - (self._clock() - self._last_failure_time)
                logger.warning("circuit_breaker_rejected", name=self.name, state=current.value)
                raise CircuitBreakerOpenError(remaining)
            if current is CircuitState.HALF_OPEN:
                self._state = CircuitState.HALF_OPEN
                self._probe_in_flight = True
                self._epoch += 1
                probe_token = object()
                self._probe_token = probe_token
                is_probe = True
            admission_epoch = self._epoch
            admission_generation = self._generation
            self._total_calls += 1
        try:
            value = func(*args, **kwargs)
            result = await value if inspect.isawaitable(value) else value
        except asyncio.CancelledError:
            if is_probe:
                await self._abandon_probe(probe_token)
            raise
        except Exception:
            async with self._lock:
                if is_probe and self._probe_token is probe_token:
                    self._failure_count += 1
                    self._last_failure_time = self._clock()
                    self._probe_in_flight = False
                    self._probe_token = None
                    self._state = CircuitState.OPEN
                    self._epoch += 1
                    self._generation += 1
                    logger.warning(
                        "circuit_breaker_opened",
                        name=self.name,
                        failure_count=self._failure_count,
                    )
                elif not is_probe and self._epoch == admission_epoch:
                    self._failure_count += 1
                    self._last_failure_time = self._clock()
                    self._generation += 1
                    if self._failure_count >= self.failure_threshold:
                        self._state = CircuitState.OPEN
                        self._epoch += 1
                        logger.warning(
                            "circuit_breaker_opened",
                            name=self.name,
                            failure_count=self._failure_count,
                        )
            raise
        except BaseException:
            if is_probe:
                await self._abandon_probe(probe_token)
            raise
        async with self._lock:
            if is_probe and self._probe_token is probe_token:
                self._state = CircuitState.CLOSED
                self._probe_in_flight = False
                self._probe_token = None
                self._failure_count = 0
                self._success_count += 1
                self._epoch += 1
                self._generation += 1
            elif (
                not is_probe
                and self._state is CircuitState.CLOSED
                and self._epoch == admission_epoch
                and self._generation == admission_generation
            ):
                self._failure_count = 0
                self._success_count += 1
        return result

    async def _abandon_probe(self, probe_token: object | None) -> None:
        """Release a cancelled/aborted half-open trial without wedging the breaker."""
        async with self._lock:
            if self._probe_token is probe_token:
                self._probe_in_flight = False
                self._probe_token = None
                self._state = CircuitState.OPEN
                self._last_failure_time = self._clock()
                self._epoch += 1
                self._generation += 1

    def get_stats(self) -> dict[str, str | int | float]:
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
        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._success_count = 0
        self._probe_in_flight = False
        self._probe_token = None
        self._epoch += 1
        self._generation += 1
        logger.info("circuit_breaker_reset", name=self.name)


class CircuitBreakingProvider:
    """Shared app-scoped breaker around the typed provider port."""

    def __init__(self, delegate: ModelProvider, breaker: CircuitBreaker) -> None:
        self.delegate = delegate
        self.breaker = breaker

    async def complete(
        self,
        messages: Sequence[Message],
        tools: Sequence[ToolDefinition] = (),
        *,
        max_tokens: int = 4096,
        response_format: str | None = None,
    ) -> ModelResponse:
        async def invoke() -> ModelResponse:
            kwargs: dict[str, Any] = {"max_tokens": max_tokens}
            # Legacy typed providers predate the optional JSON-mode keyword. Avoid passing
            # it on ordinary sync/SSE calls so existing injected providers remain valid.
            if response_format is not None:
                kwargs["response_format"] = response_format
            return await self.delegate.complete(messages, tools, **kwargs)

        try:
            return await self.breaker.call(invoke)
        except CircuitBreakerOpenError as exc:
            raise ProviderUnavailableError("Model provider temporarily unavailable") from exc
        except Exception as exc:
            raise ProviderUnavailableError("Model provider temporarily unavailable") from exc
