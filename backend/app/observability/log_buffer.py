"""Application-scoped, owner-aware live operational log storage."""

from __future__ import annotations

import asyncio
import copy
import time
from collections import deque
from contextlib import suppress
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class _Subscriber:
    queue: asyncio.Queue[dict[str, Any]]
    owner_id: str
    include_all: bool


class OwnerLogBuffer:
    """Bounded live-log buffer isolated to one app and filtered by authenticated owner."""

    def __init__(self, max_entries: int = 200) -> None:
        self._entries: deque[dict[str, Any]] = deque(maxlen=max_entries)
        self._subscribers: list[_Subscriber] = []

    def append(
        self,
        *,
        owner_id: str,
        level: str,
        event: str,
        data: dict[str, Any],
    ) -> None:
        """Append already-redacted data without retaining caller-owned mutable values."""
        entry = {
            "ts": time.strftime("%H:%M:%S"),
            "level": level,
            "event": event,
            "owner_id": owner_id,
            "data": copy.deepcopy(data),
        }
        self._entries.append(entry)
        for subscriber in tuple(self._subscribers):
            if subscriber.include_all or subscriber.owner_id == owner_id:
                with suppress(asyncio.QueueFull):
                    subscriber.queue.put_nowait(copy.deepcopy(entry))

    def recent(self, *, owner_id: str, include_all: bool, limit: int = 50) -> list[dict[str, Any]]:
        entries = (entry for entry in self._entries if include_all or entry["owner_id"] == owner_id)
        return copy.deepcopy(list(entries)[-max(0, min(limit, 200)) :])

    def subscribe(self, *, owner_id: str, include_all: bool) -> asyncio.Queue[dict[str, Any]]:
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=100)
        self._subscribers.append(_Subscriber(queue, owner_id, include_all))
        return queue

    def unsubscribe(self, queue: asyncio.Queue[dict[str, Any]]) -> None:
        self._subscribers = [item for item in self._subscribers if item.queue is not queue]

    @property
    def subscriber_count(self) -> int:
        """Expose count for lifecycle/isolation probes without exposing subscriber objects."""
        return len(self._subscribers)
