"""Online, resumable encrypted-memory key rotation orchestration."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType

from app.memory.scoped import MemoryRotationBatch, ScopedEncryptedMemoryRepository


@dataclass(frozen=True, slots=True)
class MemoryRotationStatus:
    active_version: int
    version_counts: Mapping[int, int]

    @property
    def remaining(self) -> int:
        return sum(
            count for version, count in self.version_counts.items() if version != self.active_version
        )

    @property
    def complete(self) -> bool:
        return self.remaining == 0


class MemoryKeyRotationService:
    def __init__(self, repository: ScopedEncryptedMemoryRepository) -> None:
        self._repository = repository

    async def status(self, owner_id: str, project_id: str) -> MemoryRotationStatus:
        counts = await self._repository.key_version_counts(owner_id, project_id)
        return MemoryRotationStatus(
            active_version=self._repository.active_key_version,
            version_counts=MappingProxyType(dict(counts)),
        )

    async def rotate_scope(
        self, owner_id: str, project_id: str, *, batch_size: int = 100
    ) -> MemoryRotationBatch:
        return await self._repository.rotate_batch(
            owner_id, project_id, batch_size=batch_size
        )

    async def assert_key_retirable(self, version: int) -> None:
        await self._repository.assert_key_retirable(version)
