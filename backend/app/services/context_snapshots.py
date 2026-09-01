"""Durable owner-scoped storage for metadata-only effective-context manifests."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any, cast

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.engine import CursorResult
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.runtime.context_provenance import (
    CapabilityContextRef,
    EffectiveContextManifest,
    InstructionRevisionRef,
    SkillRevisionRef,
)
from app.services.db_store import ContextSnapshotRow


class ContextSnapshotConflictError(RuntimeError):
    def __init__(self) -> None:
        super().__init__("context_snapshot_conflict")


def _json(values: Any) -> str:
    return json.dumps(list(values), ensure_ascii=False, separators=(",", ":"))


def _decode_ids(raw: str, *, integers: bool) -> tuple[Any, ...]:
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        raise ContextSnapshotConflictError from None
    if not isinstance(value, list):
        raise ContextSnapshotConflictError
    if integers:
        if any(type(item) is not int for item in value):
            raise ContextSnapshotConflictError
    elif any(not isinstance(item, str) for item in value):
        raise ContextSnapshotConflictError
    return tuple(value)


class ContextSnapshotRepository:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = session_factory

    @staticmethod
    def _values(manifest: EffectiveContextManifest) -> dict[str, Any]:
        return {
            "snapshot_id": manifest.snapshot_id,
            "schema_version": manifest.schema_version,
            "owner_id": manifest.owner_id,
            "project_id": manifest.project_id,
            "run_id": manifest.run_id,
            "conversation_id": manifest.conversation_id,
            "selected_message_ids_json": _json(manifest.selected_message_ids),
            "summarized_message_ids_json": _json(manifest.summarized_message_ids),
            "memory_ids_json": _json(manifest.memory_ids),
            "skill_ids_json": _json(manifest.skill_ids),
            "instruction_revisions_json": _json(
                [
                    {
                        "revision_id": item.revision_id,
                        "content_hash": item.content_hash,
                        "order": item.order,
                    }
                    for item in manifest.instruction_revisions
                ]
            ),
            "skill_revisions_json": _json(
                [
                    {
                        "capability_id": item.capability_id,
                        "revision_id": item.revision_id,
                        "content_hash": item.content_hash,
                        "reasons": list(item.reasons),
                    }
                    for item in manifest.skill_revisions
                ]
            ),
            "capability_references_json": _json(
                [
                    {
                        "capability_id": item.capability_id,
                        "name": item.name,
                        "permission": item.permission,
                        "reason": item.reason,
                        "schema_hash": item.schema_hash,
                    }
                    for item in manifest.capability_references
                ]
            ),
            "selected_capability_ids_json": _json(manifest.selected_capability_ids),
            "rejected_capability_ids_json": _json(manifest.rejected_capability_ids),
            "context_cost_bytes": manifest.context_cost_bytes,
            "input_asset_fingerprints_json": _json(manifest.input_asset_fingerprints),
            "summary_version": manifest.summary_version,
            "estimated_tokens": manifest.estimated_tokens,
            "truncation_reason": manifest.truncation_reason,
            "manifest_hash": manifest.manifest_hash,
            "created_at": datetime.now(tz=UTC),
        }

    async def record(self, manifest: EffectiveContextManifest) -> EffectiveContextManifest:
        values = self._values(manifest)
        async with self._sessions() as session:
            dialect = session.get_bind().dialect.name
            inserted = False
            try:
                if dialect == "sqlite":
                    result = await session.execute(
                        sqlite_insert(ContextSnapshotRow)
                        .values(**values)
                        .on_conflict_do_nothing(index_elements=["run_id"])
                    )
                    inserted = int(cast(CursorResult[Any], result).rowcount or 0) == 1
                elif dialect == "postgresql":
                    result = await session.execute(
                        postgresql_insert(ContextSnapshotRow)
                        .values(**values)
                        .on_conflict_do_nothing(index_elements=["run_id"])
                    )
                    inserted = int(cast(CursorResult[Any], result).rowcount or 0) == 1
                else:
                    session.add(ContextSnapshotRow(**values))
                    await session.flush()
                    inserted = True
                await session.commit()
            except IntegrityError:
                await session.rollback()

            existing = await session.scalar(
                select(ContextSnapshotRow).where(ContextSnapshotRow.run_id == manifest.run_id)
            )
            if existing is None:
                if inserted:
                    raise ContextSnapshotConflictError
                raise ContextSnapshotConflictError
            if (
                existing.owner_id != manifest.owner_id
                or existing.project_id != manifest.project_id
                or existing.manifest_hash != manifest.manifest_hash
            ):
                raise ContextSnapshotConflictError
            return self._manifest(existing)

    async def get(
        self, *, owner_id: str, project_id: str, run_id: str
    ) -> EffectiveContextManifest | None:
        async with self._sessions() as session:
            row = await session.scalar(
                select(ContextSnapshotRow).where(
                    ContextSnapshotRow.owner_id == owner_id,
                    ContextSnapshotRow.project_id == project_id,
                    ContextSnapshotRow.run_id == run_id,
                )
            )
            return None if row is None else self._manifest(row)

    @staticmethod
    def _manifest(row: ContextSnapshotRow) -> EffectiveContextManifest:
        return EffectiveContextManifest(
            owner_id=row.owner_id,
            project_id=row.project_id,
            run_id=row.run_id,
            conversation_id=row.conversation_id,
            selected_message_ids=cast(
                tuple[int, ...], _decode_ids(row.selected_message_ids_json, integers=True)
            ),
            summarized_message_ids=cast(
                tuple[int, ...], _decode_ids(row.summarized_message_ids_json, integers=True)
            ),
            memory_ids=cast(tuple[str, ...], _decode_ids(row.memory_ids_json, integers=False)),
            skill_ids=cast(tuple[str, ...], _decode_ids(row.skill_ids_json, integers=False)),
            instruction_revisions=tuple(
                InstructionRevisionRef(
                    str(item["revision_id"]), str(item["content_hash"]), int(item["order"])
                )
                for item in json.loads(row.instruction_revisions_json)
            ),
            skill_revisions=tuple(
                SkillRevisionRef(
                    str(item["capability_id"]),
                    str(item["revision_id"]),
                    str(item["content_hash"]),
                    tuple(item["reasons"]),
                )
                for item in json.loads(row.skill_revisions_json)
            ),
            capability_references=tuple(
                CapabilityContextRef(
                    capability_id=str(item["capability_id"]),
                    name=str(item["name"]),
                    permission=str(item["permission"]),
                    reason=str(item["reason"]),
                    schema_hash=str(item["schema_hash"]),
                )
                for item in json.loads(row.capability_references_json)
            ),
            selected_capability_ids=cast(
                tuple[str, ...], _decode_ids(row.selected_capability_ids_json, integers=False)
            ),
            rejected_capability_ids=cast(
                tuple[str, ...], _decode_ids(row.rejected_capability_ids_json, integers=False)
            ),
            context_cost_bytes=row.context_cost_bytes,
            input_asset_fingerprints=cast(
                tuple[str, ...], _decode_ids(row.input_asset_fingerprints_json, integers=False)
            ),
            estimated_tokens=row.estimated_tokens,
            summary_version=row.summary_version,
            truncation_reason=row.truncation_reason,
            schema_version=row.schema_version,
        )
