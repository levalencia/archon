"""Capability-aware fallback across typed and legacy LLM adapters."""

from __future__ import annotations

import inspect
from collections.abc import Sequence
from dataclasses import fields, replace
from inspect import Parameter
from typing import Any

import structlog

from app.observability.logging import safe_exception_metadata
from app.runtime.capabilities import (
    ProviderCapabilities,
    UnsupportedProviderCapability,
    get_provider_capabilities,
)
from app.runtime.models import Message, ModelResponse, Role, ToolDefinition
from app.runtime.ports import ModelProvider
from app.runtime.structured_output import ResponseContract
from app.runtime.support import as_model_provider

logger = structlog.get_logger()


class NoCompatibleProviderError(UnsupportedProviderCapability):
    """No candidate can satisfy one typed request's complete requirement set."""

    def __init__(
        self,
        required_capabilities: tuple[str, ...],
        missing_capabilities: tuple[str, ...],
        candidate_count: int,
    ) -> None:
        self.required_capabilities = tuple(required_capabilities)
        self.required_count = len(self.required_capabilities)
        self.missing_count = len(missing_capabilities)
        self.candidate_count = candidate_count
        self.compatible_candidate_count = 0
        super().__init__("FallbackLLMChain", missing_capabilities)


class ProviderFallbackExhausted(RuntimeError):  # noqa: N818 - contract name
    """Every compatible provider failed, without retaining provider exceptions."""

    def __init__(self, attempted_count: int, provider_names: tuple[str, ...]) -> None:
        self.attempted_count = attempted_count
        self.provider_names = tuple(provider_names)
        names = ", ".join(self.provider_names) or "none"
        super().__init__(f"Provider fallback exhausted after {attempted_count} attempts ({names})")


def _union_capabilities(candidates: Sequence[ModelProvider]) -> ProviderCapabilities:
    return ProviderCapabilities(
        **{
            item.name: any(
                getattr(get_provider_capabilities(candidate), item.name) for candidate in candidates
            )
            for item in fields(ProviderCapabilities)
        }
    )


def _required_capabilities(
    messages: Sequence[Message],
    tools: Sequence[ToolDefinition],
    response_contract: ResponseContract | None,
    response_format: str | None,
) -> ProviderCapabilities:
    return ProviderCapabilities(
        native_tools=bool(tools),
        images=any(message.images for message in messages),
        json_mode=response_contract is not None or response_format == "json",
    )


def _enabled_names(capabilities: ProviderCapabilities) -> tuple[str, ...]:
    return tuple(item.name for item in fields(capabilities) if getattr(capabilities, item.name))


def _safe_model_name(adapter: object) -> str | None:
    """Read only a plain string model attribute without invoking descriptors."""
    value = inspect.getattr_static(adapter, "model", None)
    return value if isinstance(value, str) else None


def _supports_temperature(adapter: object) -> bool:
    """Inspect the declared chat signature without invoking descriptors."""
    method = inspect.getattr_static(type(adapter), "chat", None)
    if method is None:
        return False
    try:
        parameters = inspect.signature(method).parameters.values()
    except (TypeError, ValueError):
        return False
    return any(
        parameter.name == "temperature" or parameter.kind is Parameter.VAR_KEYWORD
        for parameter in parameters
    )


class FallbackLLMChain:
    """Try compatible model providers in order, preserving typed response contracts."""

    def __init__(self, adapters: Sequence[object]) -> None:
        if not adapters:
            msg = "At least one adapter required"
            raise ValueError(msg)
        # Keep the originals for legacy identity and stable statistics. Typed candidates
        # are deliberately created only through the existing conservative adapter.
        self.adapters = list(adapters)
        self._candidates = tuple(as_model_provider(adapter) for adapter in adapters)
        self.capabilities = _union_capabilities(self._candidates)
        self._failures: dict[int, int] = {}

    async def complete(
        self,
        messages: Sequence[Message],
        tools: Sequence[ToolDefinition] = (),
        *,
        max_tokens: int = 4096,
        response_contract: ResponseContract | None = None,
        response_format: str | None = None,
    ) -> ModelResponse:
        """Return the first successful candidate satisfying every request requirement."""
        if response_contract is not None and response_format is not None:
            raise ValueError("response_contract and response_format are mutually exclusive")

        required = _required_capabilities(messages, tools, response_contract, response_format)
        compatible_indices = [
            index
            for index, candidate in enumerate(self._candidates)
            if not get_provider_capabilities(candidate).missing(required)
        ]
        if not compatible_indices:
            all_missing = {
                name
                for candidate in self._candidates
                for name in get_provider_capabilities(candidate).missing(required)
            }
            ordered_missing = tuple(
                item.name for item in fields(required) if item.name in all_missing
            )
            raise NoCompatibleProviderError(
                _enabled_names(required), ordered_missing, len(self._candidates)
            )

        attempted_names: list[str] = []
        failed_attempts = 0
        for index in compatible_indices:
            adapter = self.adapters[index]
            candidate = self._candidates[index]
            adapter_name = type(adapter).__name__
            attempted_names.append(adapter_name)
            kwargs: dict[str, Any] = {"max_tokens": max_tokens}
            if response_contract is not None:
                kwargs["response_contract"] = response_contract
            if response_format is not None:
                kwargs["response_format"] = response_format
            try:
                response = await candidate.complete(messages, tools, **kwargs)
            except Exception as exc:
                failed_attempts += 1
                self._failures[index] = self._failures.get(index, 0) + 1
                logger.warning(
                    "llm_adapter_failed",
                    adapter=adapter_name,
                    position=index,
                    **safe_exception_metadata(exc, "provider_request_failed"),
                    total_failures=self._failures[index],
                )
                continue

            if index > 0:
                logger.info(
                    "llm_fallback_success",
                    adapter=adapter_name,
                    position=index,
                    failures_skipped=failed_attempts,
                )

            model_name = _safe_model_name(adapter)
            actual_provider = response.actual_provider
            actual_model = response.actual_model
            if actual_provider is None:
                actual_provider = adapter_name
            if actual_model is None and model_name is not None:
                actual_model = model_name
            if actual_provider != response.actual_provider or actual_model != response.actual_model:
                return replace(
                    response,
                    actual_provider=actual_provider,
                    actual_model=actual_model,
                )
            return response

        logger.error(
            "llm_all_adapters_failed",
            attempted_count=len(attempted_names),
            provider_names=tuple(attempted_names),
        )
        raise ProviderFallbackExhausted(len(attempted_names), tuple(attempted_names))

    async def chat(
        self,
        messages: list[dict[str, str]],
        max_tokens: int = 4096,
        temperature: float = 0.7,
    ) -> str:
        """Compatibility API that preserves supported legacy sampling arguments."""
        typed_messages = [
            Message(role=Role(message["role"]), content=message["content"]) for message in messages
        ]
        attempted_names: list[str] = []
        failed_attempts = 0
        for index, (adapter, candidate) in enumerate(zip(self.adapters, self._candidates, strict=True)):
            adapter_name = type(adapter).__name__
            attempted_names.append(adapter_name)
            try:
                chat_method: Any = getattr(adapter, "chat", None)
                if callable(chat_method):
                    kwargs: dict[str, Any] = {"max_tokens": max_tokens}
                    if _supports_temperature(adapter):
                        kwargs["temperature"] = temperature
                    text = await chat_method(messages, **kwargs)
                else:
                    response = await candidate.complete(typed_messages, max_tokens=max_tokens)
                    text = response.content or ""
            except Exception as exc:
                failed_attempts += 1
                self._failures[index] = self._failures.get(index, 0) + 1
                logger.warning(
                    "llm_adapter_failed",
                    adapter=adapter_name,
                    position=index,
                    **safe_exception_metadata(exc, "provider_request_failed"),
                    total_failures=self._failures[index],
                )
                continue
            if index > 0:
                logger.info(
                    "llm_fallback_success",
                    adapter=adapter_name,
                    position=index,
                    failures_skipped=failed_attempts,
                )
            return text

        logger.error(
            "llm_all_adapters_failed",
            attempted_count=len(attempted_names),
            provider_names=tuple(attempted_names),
        )
        raise ProviderFallbackExhausted(len(attempted_names), tuple(attempted_names))

    def get_stats(self) -> dict[str, object]:
        """Get failure stats keyed by original adapter position."""
        return {
            "adapters": [type(adapter).__name__ for adapter in self.adapters],
            "failures": dict(self._failures),
        }
