"""Explicit, conservative capability declarations for typed model providers."""

from __future__ import annotations

import inspect
from dataclasses import dataclass, fields


@dataclass(frozen=True, slots=True)
class ProviderCapabilities:
    """Features a provider explicitly declares at its typed boundary."""

    native_tools: bool = False
    images: bool = False
    json_mode: bool = False
    json_schema: bool = False
    prompt_caching: bool = False
    cache_usage: bool = False
    usage: bool = False
    stop_reason: bool = False
    streaming: bool = False

    def __post_init__(self) -> None:
        for item in fields(self):
            if type(getattr(self, item.name)) is not bool:
                raise TypeError(f"{item.name} must be bool")

    def missing(self, required: ProviderCapabilities) -> tuple[str, ...]:
        """Return required capabilities not supplied by this declaration."""
        return tuple(
            item.name
            for item in fields(self)
            if getattr(required, item.name) and not getattr(self, item.name)
        )


TEXT_ONLY_CAPABILITIES = ProviderCapabilities()


class UnsupportedProviderCapability(RuntimeError):  # noqa: N818 - contract name
    """A provider cannot satisfy one or more explicitly required capabilities."""

    def __init__(self, provider_identity: str, missing_capabilities: tuple[str, ...]) -> None:
        self.provider_identity = provider_identity
        self.missing_capabilities = tuple(missing_capabilities)
        missing = ", ".join(self.missing_capabilities) or "unspecified"
        super().__init__(f"Provider {provider_identity!r} does not support: {missing}")


def get_provider_capabilities(provider: object) -> ProviderCapabilities:
    """Read an explicit declaration without calling or dynamically probing the provider."""
    declared = inspect.getattr_static(provider, "capabilities", None)
    if isinstance(declared, ProviderCapabilities):
        return declared
    return TEXT_ONLY_CAPABILITIES


# Readable alias for callers that prefer a noun phrase.
provider_capabilities = get_provider_capabilities
