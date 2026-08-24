"""Persistent conversation management API routes."""

from __future__ import annotations

import uuid

import structlog
from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

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
async def list_conversations(request: Request) -> list[ConversationResponse]:
    rows = await get_conversation_repository(request).list()
    return [ConversationResponse(**row) for row in rows]


@router.post("", response_model=ConversationResponse, status_code=201)
async def create_conversation(body: ConversationCreate, request: Request) -> ConversationResponse:
    conv_id = str(uuid.uuid4())
    conversation = await get_conversation_repository(request).create(conv_id, body.title)
    logger.info("conversation_created", conversation_id=conv_id, title=body.title)
    return ConversationResponse(**conversation)


@router.get("/{conversation_id}", response_model=ConversationDetail)
async def get_conversation(conversation_id: str, request: Request) -> ConversationDetail:
    conversation = await get_conversation_repository(request).get(conversation_id)
    if conversation is None:
        return ConversationDetail(
            id=conversation_id,
            title="Untitled",
            created_at="",
            messages=[],
            message_count=0,
        )
    return ConversationDetail(**conversation)


@router.delete("/{conversation_id}", status_code=204)
async def delete_conversation(conversation_id: str, request: Request) -> None:
    await get_conversation_repository(request).delete(conversation_id)
    logger.info("conversation_deleted", conversation_id=conversation_id)
