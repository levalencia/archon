"""Durable owner/project-scoped document API."""

from __future__ import annotations

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from app.agents.llm_factory import create_llm_client
from app.security.auth import get_current_user
from app.security.dependencies import enforce_rate_limit
from app.services.db_store import DocumentRow
from app.services.rag_pipeline import RAGPipeline

logger = structlog.get_logger()
router = APIRouter(prefix="/api/documents", tags=["documents"])


class DocumentUpload(BaseModel):
    title: str = Field(..., min_length=1, max_length=500)
    content: str = Field(..., min_length=1)
    source: str = ""
    project_id: str = Field(default="default", min_length=1, max_length=255)


class DocumentQuery(BaseModel):
    question: str = Field(..., min_length=1, max_length=5000)
    document_id: str | None = None
    top_k: int = Field(default=5, ge=1, le=20)
    project_id: str = Field(default="default", min_length=1, max_length=255)


class DocumentResponse(BaseModel):
    id: str
    title: str
    source: str
    chunks: int
    characters: int


class RAGResponse(BaseModel):
    answer: str
    sources: list[dict]
    chunks_retrieved: int
    confidence: float


def _response(row: DocumentRow) -> DocumentResponse:
    return DocumentResponse(
        id=str(row.id),
        title=str(row.title),
        source=str(row.source),
        chunks=int(row.chunks),
        characters=int(row.characters),
    )


@router.post("/upload", response_model=DocumentResponse, status_code=201)
async def upload_document(
    body: DocumentUpload,
    request: Request,
    user: dict = Depends(get_current_user),  # noqa: B008
) -> DocumentResponse:
    await enforce_rate_limit(request, user, "documents_upload")
    row = await request.app.state.documents.ingest(
        owner_id=user["user_id"],
        project_id=body.project_id,
        title=body.title,
        source=body.source,
        content=body.content,
    )
    return _response(row)


@router.post("/query", response_model=RAGResponse)
async def query_documents(
    body: DocumentQuery,
    request: Request,
    user: dict = Depends(get_current_user),  # noqa: B008
) -> RAGResponse:
    await enforce_rate_limit(request, user, "documents_query")
    repository = request.app.state.documents
    if (
        body.document_id is not None
        and await repository.get(
            owner_id=user["user_id"], project_id=body.project_id, document_id=body.document_id
        )
        is None
    ):
        raise HTTPException(status_code=404, detail="Document not found")
    owned_ids = await repository.owned_ids(owner_id=user["user_id"], project_id=body.project_id)
    pipeline = RAGPipeline(
        vector_store=request.app.state.vector_store,
        embedding_service=request.app.state.embedding_service,
        llm=create_llm_client(request.app.state.settings),
        top_k=body.top_k,
        min_score=-1.0,
    )
    result = await pipeline.query(
        question=body.question,
        document_id=body.document_id,
        document_ids=owned_ids,
        owner_id=user["user_id"],
        project_id=body.project_id,
    )
    return RAGResponse(**result)


@router.get("", response_model=list[DocumentResponse])
async def list_documents(
    request: Request,
    project_id: str = "default",
    user: dict = Depends(get_current_user),  # noqa: B008
) -> list[DocumentResponse]:
    await enforce_rate_limit(request, user, "documents_list")
    rows = await request.app.state.documents.list(owner_id=user["user_id"], project_id=project_id)
    return [_response(row) for row in rows]


@router.delete("/{document_id}", status_code=204)
async def delete_document(
    document_id: str,
    request: Request,
    project_id: str = "default",
    user: dict = Depends(get_current_user),  # noqa: B008
) -> None:
    await enforce_rate_limit(request, user, "documents_delete")
    deleted = await request.app.state.documents.delete(
        owner_id=user["user_id"], project_id=project_id, document_id=document_id
    )
    if not deleted:
        raise HTTPException(status_code=404, detail="Document not found")
    logger.info("document_deleted", document_id=document_id)
