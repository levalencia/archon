"""Conversation management API routes.

GET    /api/conversations           — List all conversations
POST   /api/conversations           — Create a new conversation
GET    /api/conversations/{id}      — Get conversation details + messages
DELETE /api/conversations/{id}      — Delete a conversation
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import structlog
from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.memory.in_memory import InMemoryStore

logger = structlog.get_logger()

router = APIRouter(prefix="/api/conversations", tags=["conversations"])

# Module-level store (shared with chat routes via import)
_memory_store = InMemoryStore()
# Conversation metadata
_conversation_meta: dict[str, dict] = {}


class ConversationCreate(BaseModel):
    """Create conversation request."""

    title: str = Field(default="New Conversation", max_length=200)


class ConversationResponse(BaseModel):
    """Conversation metadata response."""

    id: str
    title: str
    created_at: str
    message_count: int


class ConversationDetail(BaseModel):
    """Conversation with messages."""

    id: str
    title: str
    created_at: str
    messages: list[dict[str, str]]
    message_count: int


@router.get("", response_model=list[ConversationResponse])
async def list_conversations() -> list[ConversationResponse]:
    """List all conversations with metadata."""
    result = []
    for cid, meta in _conversation_meta.items():
        count = await _memory_store.get_message_count(cid)
        result.append(
            ConversationResponse(
                id=cid,
                title=meta.get("title", "Untitled"),
                created_at=meta.get("created_at", ""),
                message_count=count,
            )
        )
    return result


@router.post("", response_model=ConversationResponse, status_code=201)
async def create_conversation(body: ConversationCreate) -> ConversationResponse:
    """Create a new conversation."""
    conv_id = str(uuid.uuid4())
    now = datetime.now(tz=timezone.utc).isoformat()

    _conversation_meta[conv_id] = {
        "title": body.title,
        "created_at": now,
    }

    logger.info("conversation_created", conversation_id=conv_id, title=body.title)

    return ConversationResponse(
        id=conv_id,
        title=body.title,
        created_at=now,
        message_count=0,
    )


@router.get("/{conversation_id}", response_model=ConversationDetail)
async def get_conversation(conversation_id: str) -> ConversationDetail:
    """Get conversation with all messages."""
    meta = _conversation_meta.get(conversation_id, {})
    messages = await _memory_store.retrieve(conversation_id)
    count = await _memory_store.get_message_count(conversation_id)

    return ConversationDetail(
        id=conversation_id,
        title=meta.get("title", "Untitled"),
        created_at=meta.get("created_at", ""),
        messages=messages,
        message_count=count,
    )


@router.delete("/{conversation_id}", status_code=204)
async def delete_conversation(conversation_id: str) -> None:
    """Delete a conversation and its messages."""
    await _memory_store.delete_conversation(conversation_id)
    _conversation_meta.pop(conversation_id, None)
    logger.info("conversation_deleted", conversation_id=conversation_id)
