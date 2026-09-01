"""Durable repositories for skills and project instruction revisions."""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.services.db_store import (
    ProjectInstructionRevisionRow,
    ProjectSkillBindingRow,
    ProjectWorkspaceRow,
    SkillPackageRow,
    SkillRevisionRow,
)
from app.skills.parser import ParsedSkill


class SkillConflictError(ValueError):
    pass


class SkillNotFoundError(LookupError):
    pass


@dataclass(frozen=True, slots=True)
class InstalledSkill:
    package_id: str
    revision_id: str
    revision_number: int
    content_hash: str


class SkillRepository:
    """Owner-scoped package/revision store; revision rows are append-only."""

    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def install(
        self,
        *,
        owner_id: str,
        parsed: ParsedSkill,
        source_url: str,
        source_revision: str,
        trust_state: str = "untrusted",
        review_state: str = "pending",
    ) -> InstalledSkill:
        now = datetime.now(tz=UTC)
        async with self._sessions() as session, session.begin():
            package = await session.scalar(
                select(SkillPackageRow).where(
                    SkillPackageRow.owner_id == owner_id,
                    SkillPackageRow.name == parsed.name,
                )
            )
            if package is None:
                package = SkillPackageRow(
                    id=str(uuid.uuid4()), owner_id=owner_id, name=parsed.name, created_at=now
                )
                session.add(package)
                await session.flush()
            duplicate = await session.scalar(
                select(SkillRevisionRow).where(
                    SkillRevisionRow.package_id == package.id,
                    SkillRevisionRow.content_hash == parsed.content_hash,
                )
            )
            if duplicate is not None:
                return InstalledSkill(
                    package.id, duplicate.id, duplicate.revision_number, duplicate.content_hash
                )
            last = await session.scalar(
                select(SkillRevisionRow.revision_number)
                .where(SkillRevisionRow.package_id == package.id)
                .order_by(SkillRevisionRow.revision_number.desc())
                .limit(1)
            )
            row = SkillRevisionRow(
                id=str(uuid.uuid4()),
                package_id=package.id,
                owner_id=owner_id,
                revision_number=(last or 0) + 1,
                declared_version=parsed.version,
                description=parsed.description,
                content=parsed.raw_content,
                content_hash=parsed.content_hash,
                manifest_hash=parsed.manifest_hash,
                tags_json=json.dumps(parsed.tags, separators=(",", ":")),
                references_json=json.dumps(parsed.references, separators=(",", ":")),
                source_url=source_url,
                source_revision=source_revision,
                trust_state=trust_state,
                review_state=review_state,
                created_at=now,
            )
            session.add(row)
            try:
                await session.flush()
            except IntegrityError as exc:
                raise SkillConflictError("concurrent skill revision conflict") from exc
            return InstalledSkill(package.id, row.id, row.revision_number, row.content_hash)

    async def get_revision(
        self, *, owner_id: str, package_id: str, revision_id: str
    ) -> SkillRevisionRow:
        async with self._sessions() as session:
            row = await session.scalar(
                select(SkillRevisionRow).where(
                    SkillRevisionRow.id == revision_id,
                    SkillRevisionRow.package_id == package_id,
                    SkillRevisionRow.owner_id == owner_id,
                )
            )
            if row is None:
                raise SkillNotFoundError("skill revision not found in owner scope")
            return row

    async def bind(
        self,
        *,
        owner_id: str,
        project_id: str,
        package_id: str,
        revision_id: str,
        enabled: bool = True,
    ) -> None:
        await self.get_revision(owner_id=owner_id, package_id=package_id, revision_id=revision_id)
        now = datetime.now(tz=UTC)
        async with self._sessions() as session, session.begin():
            workspace = await session.get(ProjectWorkspaceRow, (owner_id, project_id))
            if workspace is None:
                session.add(
                    ProjectWorkspaceRow(
                        owner_id=owner_id, project_id=project_id, created_at=now, updated_at=now
                    )
                )
            binding = await session.get(ProjectSkillBindingRow, (owner_id, project_id, package_id))
            if binding is None:
                session.add(
                    ProjectSkillBindingRow(
                        owner_id=owner_id,
                        project_id=project_id,
                        package_id=package_id,
                        revision_id=revision_id,
                        enabled=enabled,
                        created_at=now,
                        updated_at=now,
                    )
                )
            else:
                binding.revision_id = revision_id
                binding.enabled = enabled
                binding.updated_at = now

    async def list_bound(self, *, owner_id: str, project_id: str) -> list[SkillRevisionRow]:
        async with self._sessions() as session:
            result = await session.scalars(
                select(SkillRevisionRow)
                .join(
                    ProjectSkillBindingRow,
                    ProjectSkillBindingRow.revision_id == SkillRevisionRow.id,
                )
                .where(
                    ProjectSkillBindingRow.owner_id == owner_id,
                    ProjectSkillBindingRow.project_id == project_id,
                    ProjectSkillBindingRow.enabled.is_(True),
                    SkillRevisionRow.owner_id == owner_id,
                )
                .order_by(SkillRevisionRow.created_at, SkillRevisionRow.id)
            )
            return list(result)


class ProjectInstructionRepository:
    """Project-scoped append-only instruction history with a durable current pointer."""

    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def append(
        self,
        *,
        owner_id: str,
        project_id: str,
        content: str,
        review_state: str = "approved",
    ) -> ProjectInstructionRevisionRow:
        if not content.strip():
            raise ValueError("project instructions must not be empty")
        encoded = content.encode("utf-8")
        if len(encoded) > 256 * 1024:
            raise ValueError("project instructions exceed 262144 bytes")
        digest = hashlib.sha256(encoded).hexdigest()
        now = datetime.now(tz=UTC)
        async with self._sessions() as session, session.begin():
            workspace = await session.get(ProjectWorkspaceRow, (owner_id, project_id))
            if workspace is None:
                workspace = ProjectWorkspaceRow(
                    owner_id=owner_id, project_id=project_id, created_at=now, updated_at=now
                )
                session.add(workspace)
                await session.flush()
            existing = await session.scalar(
                select(ProjectInstructionRevisionRow).where(
                    ProjectInstructionRevisionRow.owner_id == owner_id,
                    ProjectInstructionRevisionRow.project_id == project_id,
                    ProjectInstructionRevisionRow.content_hash == digest,
                )
            )
            if existing is not None:
                workspace.current_instruction_revision_id = existing.id
                workspace.updated_at = now
                return existing
            last = await session.scalar(
                select(ProjectInstructionRevisionRow.revision_number)
                .where(
                    ProjectInstructionRevisionRow.owner_id == owner_id,
                    ProjectInstructionRevisionRow.project_id == project_id,
                )
                .order_by(ProjectInstructionRevisionRow.revision_number.desc())
                .limit(1)
            )
            row = ProjectInstructionRevisionRow(
                id=str(uuid.uuid4()),
                owner_id=owner_id,
                project_id=project_id,
                revision_number=(last or 0) + 1,
                content=content,
                content_hash=digest,
                review_state=review_state,
                created_at=now,
            )
            session.add(row)
            await session.flush()
            workspace.current_instruction_revision_id = row.id
            workspace.updated_at = now
            return row

    async def current(
        self, *, owner_id: str, project_id: str
    ) -> ProjectInstructionRevisionRow | None:
        async with self._sessions() as session:
            workspace = await session.get(ProjectWorkspaceRow, (owner_id, project_id))
            if workspace is None or workspace.current_instruction_revision_id is None:
                return None
            return await session.scalar(
                select(ProjectInstructionRevisionRow).where(
                    ProjectInstructionRevisionRow.id == workspace.current_instruction_revision_id,
                    ProjectInstructionRevisionRow.owner_id == owner_id,
                    ProjectInstructionRevisionRow.project_id == project_id,
                )
            )
