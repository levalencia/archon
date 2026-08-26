"""Document management API routes for RAG pipeline.

POST   /api/documents/upload    — Upload and ingest a document
POST   /api/documents/query     — Query documents with RAG
GET    /api/documents           — List ingested documents
DELETE /api/documents/{id}      — Delete a document
"""

from __future__ import annotations

import uuid
from typing import Any

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from app.agents.llm_factory import create_llm_client
from app.observability.logging import safe_value_metadata
from app.security.auth import get_current_user
from app.services.chunker import EmbeddingService
from app.services.rag_pipeline import RAGPipeline
from app.services.vector_store import VectorStore

logger = structlog.get_logger()

router = APIRouter(
    prefix="/api/documents", tags=["documents"], dependencies=[Depends(get_current_user)]
)

# Module-level stores (lazy-initialized)
_vector_store: Any = None
_embedding_service: EmbeddingService | None = None
_document_registry: dict[str, dict] = {}


def _get_vector_store(request: Request) -> Any:
    """Lazy-initialize vector store from app settings."""
    global _vector_store  # noqa: PLW0603
    if _vector_store is not None:
        return _vector_store

    settings = request.app.state.settings
    backend = getattr(settings, "vector_store_backend", "memory")

    if backend == "postgres":
        from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

        from app.services.pgvector_store import PgVectorStore

        engine = create_async_engine(settings.database_url, echo=False)
        sf = async_sessionmaker(engine, expire_on_commit=False)
        _vector_store = PgVectorStore(sf)
        # Store engine for table creation
        _vector_store._engine = engine  # type: ignore[attr-defined]
        logger.info(
            "vector_store_initialized",
            backend="postgres",
            **safe_value_metadata("database_url", settings.database_url),
        )
    else:
        _vector_store = VectorStore()
        logger.info("vector_store_initialized", backend="memory")

    return _vector_store


def _get_embedding_service(request: Request) -> EmbeddingService:
    """Lazy-initialize EmbeddingService from app settings on first request."""
    global _embedding_service  # noqa: PLW0603
    if _embedding_service is None:
        settings = request.app.state.settings
        api_key = settings.embedding_api_key or settings.llm_api_key
        _embedding_service = EmbeddingService(
            provider=settings.embedding_provider,
            model=settings.embedding_model,
            api_key=api_key,
            dimensions=settings.embedding_dimensions,
        )
    return _embedding_service


class DocumentUpload(BaseModel):
    """Document upload request."""

    title: str = Field(..., min_length=1, max_length=500)
    content: str = Field(..., min_length=1)
    source: str = ""


class DocumentQuery(BaseModel):
    """RAG query request."""

    question: str = Field(..., min_length=1, max_length=5000)
    document_id: str | None = None
    top_k: int = Field(default=5, ge=1, le=20)


class DocumentResponse(BaseModel):
    """Document metadata response."""

    id: str
    title: str
    source: str
    chunks: int
    characters: int


class RAGResponse(BaseModel):
    """RAG query response."""

    answer: str
    sources: list[dict]
    chunks_retrieved: int
    confidence: float


@router.post("/upload", response_model=DocumentResponse, status_code=201)
async def upload_document(
    body: DocumentUpload,
    request: Request,
    user: dict = Depends(get_current_user),  # noqa: B008
) -> DocumentResponse:
    """Upload and ingest a document into the RAG pipeline."""
    doc_id = str(uuid.uuid4())
    settings = request.app.state.settings
    llm = create_llm_client(settings)
    store = _get_vector_store(request)

    # Ensure tables exist for postgres backend
    if hasattr(store, "_engine"):
        from app.services.db_store import Base

        async with store._engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    pipeline = RAGPipeline(
        vector_store=store,
        embedding_service=_get_embedding_service(request),
        llm=llm,
    )

    result = await pipeline.ingest_document(
        document_id=doc_id,
        title=body.title,
        content=body.content,
        source=body.source,
    )

    _document_registry[doc_id] = {
        "user_id": user["user_id"],
        "title": body.title,
        "source": body.source,
        "chunks": result["chunks_created"],
        "characters": result["total_characters"],
    }

    return DocumentResponse(
        id=doc_id,
        title=body.title,
        source=body.source,
        chunks=result["chunks_created"],
        characters=result["total_characters"],
    )


@router.post("/query", response_model=RAGResponse)
async def query_documents(
    body: DocumentQuery,
    request: Request,
    user: dict = Depends(get_current_user),  # noqa: B008
) -> RAGResponse:
    """Query ingested documents using RAG pipeline."""
    settings = request.app.state.settings
    llm = create_llm_client(settings)
    store = _get_vector_store(request)

    pipeline = RAGPipeline(
        vector_store=store,
        embedding_service=_get_embedding_service(request),
        llm=llm,
        top_k=body.top_k,
        min_score=-1.0,  # Mock embeddings need low threshold
    )

    owned_ids = {
        doc_id for doc_id, meta in _document_registry.items() if meta["user_id"] == user["user_id"]
    }
    if body.document_id and body.document_id not in owned_ids:
        raise HTTPException(status_code=404, detail="Document not found")

    result = await pipeline.query(
        question=body.question,
        document_id=body.document_id,
        document_ids=owned_ids,
    )

    return RAGResponse(
        answer=result["answer"],
        sources=result["sources"],
        chunks_retrieved=result["chunks_retrieved"],
        confidence=result["confidence"],
    )


@router.get("", response_model=list[DocumentResponse])
async def list_documents(
    user: dict = Depends(get_current_user),  # noqa: B008
) -> list[DocumentResponse]:
    """List all ingested documents."""
    return [
        DocumentResponse(id=doc_id, **{k: v for k, v in meta.items() if k != "user_id"})
        for doc_id, meta in _document_registry.items()
        if meta["user_id"] == user["user_id"]
    ]


@router.delete("/{document_id}", status_code=204)
async def delete_document(
    document_id: str,
    request: Request,
    user: dict = Depends(get_current_user),  # noqa: B008
) -> None:
    """Delete a document and its chunks from the vector store."""
    meta = _document_registry.get(document_id)
    if not meta or meta["user_id"] != user["user_id"]:
        raise HTTPException(status_code=404, detail="Document not found")
    store = _get_vector_store(request)
    await store.delete_document(document_id)
    _document_registry.pop(document_id, None)
    logger.info("document_deleted", document_id=document_id)
