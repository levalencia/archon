"""State checkpoints: save and restore conversation state at any point.

Plan item #93: State versioning with checkpoints.
"""

from __future__ import annotations

import copy
import time
import uuid

import structlog

logger = structlog.get_logger()


class Checkpoint:
    """A saved snapshot of conversation state."""

    def __init__(self, conversation_id: str, messages: list[dict], label: str = "") -> None:
        self.id = str(uuid.uuid4())
        self.conversation_id = conversation_id
        self.messages = copy.deepcopy(messages)
        self.label = label or f"checkpoint-{len(messages)}-messages"
        self.created_at = time.time()
        self.message_count = len(messages)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "conversation_id": self.conversation_id,
            "label": self.label,
            "message_count": self.message_count,
            "created_at": self.created_at,
        }


class CheckpointManager:
    """Manage conversation state checkpoints."""

    def __init__(self, max_checkpoints_per_conv: int = 10) -> None:
        self.max_per_conv = max_checkpoints_per_conv
        self._checkpoints: dict[str, list[Checkpoint]] = {}

    async def save(self, conversation_id: str, messages: list[dict], label: str = "") -> Checkpoint:
        cp = Checkpoint(conversation_id, messages, label)
        cps = self._checkpoints.setdefault(conversation_id, [])
        cps.append(cp)
        if len(cps) > self.max_per_conv:
            cps.pop(0)
        logger.info("checkpoint_saved", id=cp.id, messages=cp.message_count)
        return cp

    async def restore(self, checkpoint_id: str) -> list[dict] | None:
        for cps in self._checkpoints.values():
            for cp in cps:
                if cp.id == checkpoint_id:
                    logger.info("checkpoint_restored", id=cp.id, messages=cp.message_count)
                    return copy.deepcopy(cp.messages)
        return None

    async def list_checkpoints(self, conversation_id: str) -> list[dict]:
        cps = self._checkpoints.get(conversation_id, [])
        return [cp.to_dict() for cp in cps]

    async def delete(self, checkpoint_id: str) -> bool:
        for _conv_id, cps in self._checkpoints.items():
            for cp in cps:
                if cp.id == checkpoint_id:
                    cps.remove(cp)
                    return True
        return False
