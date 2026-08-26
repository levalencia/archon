"""Persistent conversation management API routes."""

from __future__ import annotations

import uuid

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from app.observability.logging import safe_value_metadata
from app.security.auth import get_current_user
from app.services.conversations import ConversationRepository

logger = structlog.get_logger()
router = APIRouter(prefix="/api/conversations", tags=["conversations"])


class ConversationCreate(BaseModel):
    title: str = Field(default="New Conversation", max_length=200)


class ConversationResponse(BaseModel):
    id: str
    title: str
    created_at: str
    message_count: int


class ConversationDetail(BaseModel):
    id: str
    title: str
    created_at: str
    messages: list[dict[str, str]]
    message_count: int


def get_conversation_repository(request: Request) -> ConversationRepository:
    return request.app.state.conversations


@router.get("", response_model=list[ConversationResponse])
async def list_conversations(
    request: Request,
    user: dict = Depends(get_current_user),  # noqa: B008
) -> list[ConversationResponse]:
    rows = await get_conversation_repository(request).list(user["user_id"])
    return [ConversationResponse(**row) for row in rows]


@router.post("", response_model=ConversationResponse, status_code=201)
async def create_conversation(
    body: ConversationCreate,
    request: Request,
    user: dict = Depends(get_current_user),  # noqa: B008
) -> ConversationResponse:
    conv_id = str(uuid.uuid4())
    conversation = await get_conversation_repository(request).create(
        conv_id, body.title, user["user_id"]
    )
    logger.info(
        "conversation_created",
        conversation_id=conv_id,
        **safe_value_metadata("title", body.title),
    )
    return ConversationResponse(**conversation)


@router.get("/{conversation_id}", response_model=ConversationDetail)
async def get_conversation(
    conversation_id: str,
    request: Request,
    user: dict = Depends(get_current_user),  # noqa: B008
) -> ConversationDetail:
    conversation = await get_conversation_repository(request).get(conversation_id, user["user_id"])
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return ConversationDetail(**conversation)


@router.delete("/{conversation_id}", status_code=204)
async def delete_conversation(
    conversation_id: str,
    request: Request,
    user: dict = Depends(get_current_user),  # noqa: B008
) -> None:
    deleted = await get_conversation_repository(request).delete(conversation_id, user["user_id"])
    if not deleted:
        raise HTTPException(status_code=404, detail="Conversation not found")
    logger.info("conversation_deleted", conversation_id=conversation_id)
