"""Durable owner/project-scoped document API."""

from __future__ import annotations

from typing import Any, cast

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from app.delegation import VerificationBudget
from app.observability.logging import get_correlation_id
from app.runtime.factory import budget_model_provider
from app.security.auth import get_current_user
from app.security.compliance import ComplianceViolationError
from app.security.dependencies import enforce_rate_limit
from app.services.db_store import DocumentRow
from app.services.documents import DocumentResourceLimitError
from app.services.grounded_rag import (
    GroundedDeadlineExceededError,
    GroundedDocumentWorkflow,
    GroundedProviderError,
)

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
    run_id: str
    answer: str
    sources: list[dict[str, Any]]
    chunks_retrieved: int
    confidence: float
    grounded: bool
    claims: list[dict[str, Any]]
    citations: list[dict[str, Any]]
    unsupported: list[str]
    metrics: dict[str, Any]
    child_run_id: str | None = None
    verification_status: str | None = None
    verification_tokens: int = 0
    verification_latency_ms: float | None = None
    verification_rejected_count: int = 0


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
    user: dict[str, Any] = Depends(get_current_user),  # noqa: B008
) -> DocumentResponse:
    await enforce_rate_limit(request, user, "documents_upload")
    try:
        request.app.state.compliance.enforce_input(
            body.title + "\n" + body.source + "\n" + body.content
        )
    except ComplianceViolationError as exc:
        raise HTTPException(
            status_code=422, detail="Document rejected by compliance policy"
        ) from exc
    try:
        row = await request.app.state.documents.ingest(
            owner_id=user["user_id"],
            project_id=body.project_id,
            title=body.title,
            source=body.source,
            content=body.content,
        )
    except DocumentResourceLimitError as exc:
        raise HTTPException(status_code=413, detail=str(exc)) from exc
    return _response(row)


@router.post("/query", response_model=RAGResponse)
async def query_documents(
    body: DocumentQuery,
    request: Request,
    user: dict[str, Any] = Depends(get_current_user),  # noqa: B008
) -> RAGResponse:
    await enforce_rate_limit(request, user, "documents_query")
    try:
        request.app.state.compliance.enforce_input(body.question)
    except ComplianceViolationError as exc:
        raise HTTPException(
            status_code=422, detail="Question rejected by compliance policy"
        ) from exc
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
    settings = request.app.state.settings
    workflow = GroundedDocumentWorkflow(
        vector_store=request.app.state.vector_store,
        embedding_service=request.app.state.embedding_service,
        model_provider=request.app.state.model_provider,
        runs=request.app.state.conversations.runs,
        provider=settings.llm_provider,
        model=settings.llm_model,
        top_k=body.top_k,
        verifier=request.app.state.evidence_verifier,
        delegation_envelopes=request.app.state.delegation_envelopes,
        verifier_model=settings.verifier_model,
        compliance=request.app.state.compliance,
        verifier_budget=(
            VerificationBudget(
                input_tokens=settings.verifier_input_tokens,
                output_tokens=settings.verifier_output_tokens,
                timeout_seconds=settings.verifier_timeout_seconds,
                retries=settings.verifier_retries,
            )
            if request.app.state.evidence_verifier is not None
            else None
        ),
        deadline_seconds=settings.rag_deadline_seconds,
        provider_factory=lambda owner_id, project_id, run_id: budget_model_provider(
            request.app.state.model_provider,
            settings=settings,
            repository=request.app.state.conversations,
            user_id=owner_id,
            project_id=project_id,
            run_id=run_id,
        ),
    )
    try:
        result = await workflow.run(
            body.question,
            document_id=body.document_id,
            document_ids=owned_ids,
            owner_id=user["user_id"],
            project_id=body.project_id,
            correlation_id=get_correlation_id(),
        )
    except GroundedDeadlineExceededError as exc:
        raise HTTPException(status_code=504, detail="Grounded answer deadline exceeded") from exc
    except GroundedProviderError as exc:
        raise HTTPException(status_code=503, detail="Grounded answer provider unavailable") from exc
    payload = request.app.state.compliance.enforce_payload(result.to_dict())
    return RAGResponse(**cast(dict[str, Any], payload))


@router.get("", response_model=list[DocumentResponse])
async def list_documents(
    request: Request,
    project_id: str = "default",
    user: dict[str, Any] = Depends(get_current_user),  # noqa: B008
) -> list[DocumentResponse]:
    await enforce_rate_limit(request, user, "documents_list")
    rows = await request.app.state.documents.list(owner_id=user["user_id"], project_id=project_id)
    return [_response(row) for row in rows]


@router.delete("/{document_id}", status_code=204)
async def delete_document(
    document_id: str,
    request: Request,
    project_id: str = "default",
    user: dict[str, Any] = Depends(get_current_user),  # noqa: B008
) -> None:
    await enforce_rate_limit(request, user, "documents_delete")
    deleted = await request.app.state.documents.delete(
        owner_id=user["user_id"], project_id=project_id, document_id=document_id
    )
    if not deleted:
        raise HTTPException(status_code=404, detail="Document not found")
    logger.info("document_deleted", document_id=document_id)
