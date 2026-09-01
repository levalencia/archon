"""Immutable deterministic index over compact capability metadata."""

from __future__ import annotations

from collections.abc import Iterable

from app.capabilities.models import CapabilityDescriptor, CapabilityKind


class CapabilityIndex:
    def __init__(self, descriptors: Iterable[CapabilityDescriptor]) -> None:
        indexed: dict[str, CapabilityDescriptor] = {}
        for descriptor in descriptors:
            if descriptor.id in indexed:
                raise ValueError(f"duplicate capability id: {descriptor.id}")
            indexed[descriptor.id] = descriptor
        self._descriptors = indexed

    def all(self, kind: CapabilityKind | str | None = None) -> tuple[CapabilityDescriptor, ...]:
        selected_kind = CapabilityKind(kind) if kind is not None else None
        return tuple(
            item
            for item in sorted(self._descriptors.values(), key=lambda value: value.id)
            if selected_kind is None or item.kind is selected_kind
        )

    def get(self, capability_id: str) -> CapabilityDescriptor | None:
        return self._descriptors.get(capability_id)
