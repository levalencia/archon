"""Persistence, hybrid retrieval, and durable threads for the learning tutor."""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, cast

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.learning_tutor.sources import LearningSourceInput
from app.security.persistence_redactor import PersistenceRedactor
from app.services.chunker import Document, EmbeddingService, RecursiveChunker, validate_embedding
from app.services.db_store import (
    LearningChunkRow,
    LearningSourceRow,
    LearningTutorSessionRow,
    LearningTutorTurnRow,
)
from app.services.vector_store import cosine_similarity

_TOKEN = re.compile(r"[a-z0-9_./:-]+")


@dataclass(frozen=True, slots=True)
class LearningEvidence:
    id: str
    source_id: str
    chunk_id: str
    kind: str
    title: str
    text: str
    score: float
    content_hash: str
    revision: str
    locator: dict[str, Any]
    context_keys: tuple[str, ...]

    def public(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "source_id": self.source_id,
            "chunk_id": self.chunk_id,
            "kind": self.kind,
            "title": self.title,
            "excerpt": self.text,
            "score": self.score,
            "content_hash": self.content_hash,
            "source_commit": self.revision,
            "locator": self.locator,
        }


@dataclass(frozen=True, slots=True)
class TutorTurn:
    id: str
    question: str
    answer: str
    context: dict[str, Any]
    evidence: list[dict[str, Any]]
    diagram: dict[str, Any] | None
    metrics: dict[str, Any]
    created_at: datetime


@dataclass(frozen=True, slots=True)
class TutorSession:
    id: str
    owner_id: str
    project_id: str
    context_key: str
    title: str
    turns: tuple[TutorTurn, ...] = ()


class LearningKnowledgeRepository:
    """Curated, application-owned knowledge persisted separately from user documents."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        embeddings: EmbeddingService,
        redactor: PersistenceRedactor,
        *,
        candidate_limit: int = 10_000,
        chunk_size: int = 1_500,
        chunk_overlap: int = 120,
    ) -> None:
        self._sf = session_factory
        self._embeddings = embeddings
        self._redactor = redactor
        self._candidate_limit = candidate_limit
        self._chunker = RecursiveChunker(chunk_size=chunk_size, chunk_overlap=chunk_overlap)

    async def sync(self, sources: list[LearningSourceInput]) -> dict[str, int]:
        """Idempotently replace changed sources and prune entries absent from the manifest."""
        by_id = {source.id: source for source in sources}
        if len(by_id) != len(sources):
            raise ValueError("Learning source IDs must be unique")
        async with self._sf() as session:
            existing_rows = (await session.scalars(select(LearningSourceRow))).all()
            embedding_rows = (
                await session.execute(
                    select(LearningChunkRow.source_id, LearningChunkRow.metadata_json).where(
                        LearningChunkRow.chunk_index == 0
                    )
                )
            ).all()
        existing = {str(row.id): row for row in existing_rows}
        embedding_spaces = {
            str(source_id): str(metadata_json) for source_id, metadata_json in embedding_rows
        }
        unchanged = {
            source_id
            for source_id, source in by_id.items()
            if source_id in existing
            and str(existing[source_id].content_hash) == source.content_hash
            and str(existing[source_id].source_revision) == source.revision
            and _matches_embedding_space(
                embedding_spaces.get(source_id, ""),
                provider=self._embeddings.capability.provider,
                model=self._embeddings.capability.model,
            )
        }
        changed = [source for source_id, source in by_id.items() if source_id not in unchanged]
        prepared: dict[str, list[tuple[str, int, str, str, str, str]]] = {
            source.id: [] for source in changed
        }
        pending_chunks: list[tuple[str, int, str, str, str]] = []
        for source in changed:
            safe_text = self._redactor.redact_text(source.text).text
            document = Document(
                id=source.id,
                title=source.title,
                content=safe_text,
                source=str(source.locator.get("path") or source.locator.get("artifact_id") or ""),
                metadata={
                    "kind": source.kind,
                    "title": source.title,
                    "revision": source.revision,
                    "locator": source.locator,
                    "context_keys": list(source.context_keys),
                    "embedding_provider": self._embeddings.capability.provider,
                    "embedding_model": self._embeddings.capability.model,
                },
            )
            chunks = self._chunker.chunk(document)
            for index, chunk in enumerate(chunks):
                pending_chunks.append(
                    (
                        source.id,
                        index,
                        chunk.content,
                        chunk.content_hash,
                        json.dumps(chunk.metadata, sort_keys=True, allow_nan=False),
                    )
                )
        for start in range(0, len(pending_chunks), 64):
            batch = pending_chunks[start : start + 64]
            vectors = await self._embeddings.embed_batch([item[2] for item in batch])
            for (source_id, index, content, content_hash, metadata), vector in zip(
                batch, vectors, strict=True
            ):
                chunk_id = hashlib.sha256(
                    f"{source_id}:{index}:{content_hash}".encode()
                ).hexdigest()
                prepared[source_id].append(
                    (
                        chunk_id,
                        index,
                        content,
                        content_hash,
                        metadata,
                        json.dumps(vector, allow_nan=False),
                    )
                )
        now = datetime.now(tz=UTC)
        removed = set(existing) - set(by_id)
        async with self._sf() as session, session.begin():
            if removed:
                await session.execute(
                    delete(LearningChunkRow).where(LearningChunkRow.source_id.in_(removed))
                )
                await session.execute(
                    delete(LearningSourceRow).where(LearningSourceRow.id.in_(removed))
                )
            for source in changed:
                await session.execute(
                    delete(LearningChunkRow).where(LearningChunkRow.source_id == source.id)
                )
                row = await session.get(LearningSourceRow, source.id)
                safe_title = self._redactor.redact_text(source.title).text
                if row is None:
                    row = LearningSourceRow(
                        id=source.id,
                        source_key=source.key,
                        kind=source.kind,
                        title=safe_title,
                        source_revision=source.revision,
                        content_hash=source.content_hash,
                        locator_json=json.dumps(source.locator, sort_keys=True),
                        context_keys_json=json.dumps(list(source.context_keys), sort_keys=True),
                        created_at=now,
                        updated_at=now,
                    )
                    session.add(row)
                else:
                    row.source_key = source.key
                    row.kind = source.kind
                    row.title = safe_title
                    row.source_revision = source.revision
                    row.content_hash = source.content_hash
                    row.locator_json = json.dumps(source.locator, sort_keys=True)
                    row.context_keys_json = json.dumps(list(source.context_keys), sort_keys=True)
                    row.updated_at = now
                await session.flush()
                for chunk_id, index, content, content_hash, metadata, vector in prepared[source.id]:
                    session.add(
                        LearningChunkRow(
                            id=chunk_id,
                            source_id=source.id,
                            chunk_index=index,
                            content=content,
                            content_hash=content_hash,
                            metadata_json=metadata,
                            embedding_json=vector,
                        )
                    )
        return {
            "added": sum(source.id not in existing for source in changed),
            "updated": sum(source.id in existing for source in changed),
            "unchanged": len(unchanged),
            "removed": len(removed),
        }

    async def count_sources(self) -> int:
        async with self._sf() as session:
            return int(
                await session.scalar(select(func.count()).select_from(LearningSourceRow)) or 0
            )

    async def search(
        self,
        question: str,
        *,
        context_keys: set[str] | None = None,
        source_ids: set[str] | None = None,
        top_k: int = 8,
    ) -> list[LearningEvidence]:
        if not question.strip() or not 1 <= top_k <= 50:
            raise ValueError("Invalid learning search request")
        dimensions = self._embeddings.capability.dimensions
        async with self._sf() as session:
            statement = (
                select(LearningChunkRow, LearningSourceRow)
                .join(LearningSourceRow, LearningSourceRow.id == LearningChunkRow.source_id)
                .order_by(LearningChunkRow.id)
                .limit(self._candidate_limit)
            )
            if source_ids is not None:
                if not source_ids:
                    return []
                statement = statement.where(LearningSourceRow.id.in_(source_ids))
            rows = (await session.execute(statement)).all()
        current_provider = self._embeddings.capability.provider
        current_model = self._embeddings.capability.model
        needs_dense = any(
            _matches_embedding_space(
                str(chunk.metadata_json),
                provider=current_provider,
                model=current_model,
            )
            for chunk, _source in rows
        )
        query_vector: list[float] | None = None
        if needs_dense:
            query_vector = validate_embedding(
                await self._embeddings.embed(question), dimensions, source="query embedding"
            )
        query_tokens = _tokens(question)
        phrase = question.strip().lower().rstrip("?.!")
        ranked: list[tuple[float, LearningChunkRow, LearningSourceRow, dict[str, Any]]] = []
        for chunk, source in rows:
            try:
                metadata = json.loads(str(chunk.metadata_json))
                locator = json.loads(str(source.locator_json))
                stored_contexts = tuple(json.loads(str(source.context_keys_json)))
            except (TypeError, ValueError, json.JSONDecodeError):
                continue
            dense = 0.0
            same_embedding_space = (
                metadata.get("embedding_provider") == current_provider
                and metadata.get("embedding_model") == current_model
            )
            if same_embedding_space and query_vector is not None:
                try:
                    vector = validate_embedding(
                        json.loads(str(chunk.embedding_json)),
                        dimensions,
                        source="stored embedding",
                    )
                    dense = (cosine_similarity(query_vector, vector) + 1.0) / 2.0
                except (TypeError, ValueError, json.JSONDecodeError):
                    dense = 0.0
            haystack = f"{source.title}\n{chunk.content}".lower()
            lexical = _lexical_score(query_tokens, phrase, haystack)
            context = 1.0 if context_keys and context_keys.intersection(stored_contexts) else 0.0
            score = 0.5 * dense + 0.4 * lexical + 0.1 * context
            ranked.append(
                (
                    score,
                    chunk,
                    source,
                    {**metadata, "locator": locator, "contexts": stored_contexts},
                )
            )
        ranked.sort(key=lambda item: (-item[0], str(item[1].id)))
        return [
            LearningEvidence(
                id=f"E{index}",
                source_id=str(source.id),
                chunk_id=str(chunk.id),
                kind=str(source.kind),
                title=str(source.title),
                text=str(chunk.content),
                score=round(score, 4),
                content_hash=str(chunk.content_hash),
                revision=str(source.source_revision),
                locator=dict(metadata["locator"]),
                context_keys=tuple(metadata["contexts"]),
            )
            for index, (score, chunk, source, metadata) in enumerate(ranked[:top_k], 1)
        ]


class LearningTutorRepository:
    """Owner-scoped durable tutor sessions and immutable question context snapshots."""

    def __init__(
        self, session_factory: async_sessionmaker[AsyncSession], redactor: PersistenceRedactor
    ) -> None:
        self._sf = session_factory
        self._redactor = redactor

    async def get_or_create_session(
        self, *, owner_id: str, project_id: str, context_key: str, title: str
    ) -> TutorSession:
        async with self._sf() as session, session.begin():
            row = await session.scalar(
                select(LearningTutorSessionRow).where(
                    LearningTutorSessionRow.owner_id == owner_id,
                    LearningTutorSessionRow.project_id == project_id,
                    LearningTutorSessionRow.context_key == context_key,
                )
            )
            if row is None:
                now = datetime.now(tz=UTC)
                row = LearningTutorSessionRow(
                    id=str(uuid.uuid4()),
                    owner_id=owner_id,
                    project_id=project_id,
                    context_key=context_key,
                    title=self._redactor.redact_text(title).text,
                    created_at=now,
                    updated_at=now,
                )
                session.add(row)
                await session.flush()
            return TutorSession(
                id=str(row.id),
                owner_id=str(row.owner_id),
                project_id=str(row.project_id),
                context_key=str(row.context_key),
                title=str(row.title),
            )

    async def store_turn(
        self,
        *,
        session_id: str,
        owner_id: str,
        project_id: str,
        question: str,
        answer: str,
        context: dict[str, Any],
        evidence: list[dict[str, Any]],
        diagram: dict[str, Any] | None,
        metrics: dict[str, Any],
    ) -> TutorTurn:
        async with self._sf() as session, session.begin():
            parent = await session.scalar(
                select(LearningTutorSessionRow).where(
                    LearningTutorSessionRow.id == session_id,
                    LearningTutorSessionRow.owner_id == owner_id,
                    LearningTutorSessionRow.project_id == project_id,
                )
            )
            if parent is None:
                raise ValueError("Tutor session not found")
            now = datetime.now(tz=UTC)
            row = LearningTutorTurnRow(
                id=str(uuid.uuid4()),
                session_id=session_id,
                owner_id=owner_id,
                project_id=project_id,
                question=self._redactor.redact_text(question).text,
                answer=self._redactor.redact_text(answer).text,
                context_json=_redacted_json(self._redactor, context),
                evidence_json=_redacted_json(self._redactor, evidence),
                diagram_json=(
                    _redacted_json(self._redactor, diagram) if diagram is not None else None
                ),
                metrics_json=_redacted_json(self._redactor, metrics),
                created_at=now,
            )
            parent.updated_at = now
            session.add(row)
            await session.flush()
            return _turn(row)

    async def get_session(self, session_id: str, *, owner_id: str) -> TutorSession | None:
        async with self._sf() as session:
            row = await session.scalar(
                select(LearningTutorSessionRow).where(
                    LearningTutorSessionRow.id == session_id,
                    LearningTutorSessionRow.owner_id == owner_id,
                )
            )
            if row is None:
                return None
            turns = (
                await session.scalars(
                    select(LearningTutorTurnRow)
                    .where(
                        LearningTutorTurnRow.session_id == session_id,
                        LearningTutorTurnRow.owner_id == owner_id,
                    )
                    .order_by(LearningTutorTurnRow.created_at, LearningTutorTurnRow.id)
                )
            ).all()
            return TutorSession(
                id=str(row.id),
                owner_id=str(row.owner_id),
                project_id=str(row.project_id),
                context_key=str(row.context_key),
                title=str(row.title),
                turns=tuple(_turn(item) for item in turns),
            )


def _tokens(value: str) -> set[str]:
    return {token for token in _TOKEN.findall(value.lower()) if len(token) > 1}


def _matches_embedding_space(metadata_json: str, *, provider: str, model: str) -> bool:
    try:
        metadata = json.loads(metadata_json)
    except (TypeError, json.JSONDecodeError):
        return False
    return (
        metadata.get("embedding_provider") == provider and metadata.get("embedding_model") == model
    )


def _lexical_score(query_tokens: set[str], phrase: str, haystack: str) -> float:
    if not query_tokens:
        return 0.0
    overlap = len(query_tokens.intersection(_tokens(haystack))) / len(query_tokens)
    phrase_bonus = 0.25 if phrase and phrase in haystack else 0.0
    return min(1.0, overlap + phrase_bonus)


def _redacted_json(redactor: PersistenceRedactor, value: Any) -> str:
    raw = json.dumps(value, sort_keys=True, allow_nan=False)
    return redactor.redact_text(raw).text


def _turn(row: LearningTutorTurnRow) -> TutorTurn:
    return TutorTurn(
        id=str(row.id),
        question=str(row.question),
        answer=str(row.answer),
        context=json.loads(str(row.context_json)),
        evidence=json.loads(str(row.evidence_json)),
        diagram=(
            json.loads(cast(str, row.diagram_json))
            if cast(str | None, row.diagram_json) is not None
            else None
        ),
        metrics=json.loads(str(row.metrics_json)),
        created_at=cast(datetime, row.created_at),
    )
