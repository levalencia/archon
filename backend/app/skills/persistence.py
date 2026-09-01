"""Durable repositories for skills and project instruction revisions."""

from __future__ import annotations

import asyncio
import hashlib
import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.instructions.loaders import InstructionFamily, InstructionSource
from app.services.db_store import (
    ProjectInstructionRevisionRow,
    ProjectInstructionSourceRow,
    ProjectSkillBindingRow,
    ProjectSkillPinRow,
    ProjectWorkspaceRow,
    SkillPackageRow,
    SkillReferenceRow,
    SkillRevisionRow,
)
from app.skills.parser import ParsedSkill


class SkillConflictError(ValueError):
    pass


class ProjectInstructionConflictError(ValueError):
    pass


_MAX_REVISION_WRITE_ATTEMPTS = 3


class SkillNotFoundError(LookupError):
    pass


@dataclass(frozen=True, slots=True)
class InstalledSkill:
    package_id: str
    revision_id: str
    revision_number: int
    content_hash: str
    name: str


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
        reference_contents: dict[str, str] | None = None,
    ) -> InstalledSkill:
        for attempt in range(_MAX_REVISION_WRITE_ATTEMPTS):
            try:
                return await self._install_once(
                    owner_id=owner_id,
                    parsed=parsed,
                    source_url=source_url,
                    source_revision=source_revision,
                    trust_state=trust_state,
                    review_state=review_state,
                    reference_contents=reference_contents,
                )
            except (IntegrityError, OperationalError, SkillConflictError) as exc:
                if attempt + 1 == _MAX_REVISION_WRITE_ATTEMPTS:
                    raise SkillConflictError("concurrent skill revision conflict") from exc
                await asyncio.sleep(0.01 * (attempt + 1))
        raise AssertionError("unreachable")

    async def _install_once(
        self,
        *,
        owner_id: str,
        parsed: ParsedSkill,
        source_url: str,
        source_revision: str,
        trust_state: str = "untrusted",
        review_state: str = "pending",
        reference_contents: dict[str, str] | None = None,
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
            # A harmless write serializes allocation on both PostgreSQL and SQLite.
            await session.execute(
                update(SkillPackageRow)
                .where(SkillPackageRow.id == package.id, SkillPackageRow.owner_id == owner_id)
                .values(created_at=SkillPackageRow.created_at)
            )
            duplicate = await session.scalar(
                select(SkillRevisionRow).where(
                    SkillRevisionRow.package_id == package.id,
                    SkillRevisionRow.content_hash == parsed.content_hash,
                )
            )
            if duplicate is not None:
                return InstalledSkill(
                    package.id,
                    duplicate.id,
                    duplicate.revision_number,
                    duplicate.content_hash,
                    parsed.name,
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
                triggers_json=json.dumps(parsed.triggers, separators=(",", ":")),
                negative_triggers_json=json.dumps(parsed.negative_triggers, separators=(",", ":")),
                required_capability_ids_json=json.dumps(
                    parsed.required_capability_ids, separators=(",", ":")
                ),
                context_cost=parsed.context_cost,
                source_url=source_url,
                source_revision=source_revision,
                trust_state=trust_state,
                review_state=(
                    "pending" if review_state == "approved" and reference_contents else review_state
                ),
                created_at=now,
            )
            session.add(row)
            try:
                await session.flush()
                for path, content in sorted((reference_contents or {}).items()):
                    if path not in parsed.references:
                        raise ValueError("reference content is not declared by the manifest")
                    encoded = content.encode("utf-8")
                    if len(encoded) > 65_536:
                        raise ValueError("skill reference exceeds 65536 bytes")
                    session.add(
                        SkillReferenceRow(
                            revision_id=row.id,
                            owner_id=owner_id,
                            path=path,
                            content=content,
                            content_hash=hashlib.sha256(encoded).hexdigest(),
                            byte_count=len(encoded),
                        )
                    )
                await session.flush()
                if row.review_state != review_state:
                    row.review_state = review_state
                    await session.flush()
            except IntegrityError as exc:
                raise SkillConflictError("concurrent skill revision conflict") from exc
            return InstalledSkill(
                package.id, row.id, row.revision_number, row.content_hash, parsed.name
            )

    async def list_catalog(
        self, *, owner_id: str, query: str = ""
    ) -> list[tuple[SkillPackageRow, SkillRevisionRow]]:
        """Return latest owner revisions without exposing content."""
        async with self._sessions() as session:
            packages = list(
                await session.scalars(
                    select(SkillPackageRow)
                    .where(SkillPackageRow.owner_id == owner_id)
                    .order_by(SkillPackageRow.name)
                )
            )
            result: list[tuple[SkillPackageRow, SkillRevisionRow]] = []
            term = query.casefold().strip()
            for package in packages:
                revision = await session.scalar(
                    select(SkillRevisionRow)
                    .where(
                        SkillRevisionRow.package_id == package.id,
                        SkillRevisionRow.owner_id == owner_id,
                    )
                    .order_by(SkillRevisionRow.revision_number.desc())
                    .limit(1)
                )
                if revision is not None and (
                    not term
                    or term in package.name.casefold()
                    or term in revision.description.casefold()
                    or term in revision.tags_json.casefold()
                ):
                    result.append((package, revision))
            return result

    async def set_review_state(
        self, *, owner_id: str, package_id: str, revision_id: str, review_state: str
    ) -> SkillRevisionRow:
        if review_state not in {"approved", "rejected"}:
            raise ValueError("invalid review state")
        async with self._sessions() as session, session.begin():
            row = await session.scalar(
                select(SkillRevisionRow).where(
                    SkillRevisionRow.id == revision_id,
                    SkillRevisionRow.package_id == package_id,
                    SkillRevisionRow.owner_id == owner_id,
                )
            )
            if row is None:
                raise SkillNotFoundError("skill revision not found in owner scope")
            row.review_state = review_state
            await session.flush()
            return row

    async def binding(
        self, *, owner_id: str, project_id: str, package_id: str
    ) -> ProjectSkillBindingRow | None:
        async with self._sessions() as session:
            return await session.get(ProjectSkillBindingRow, (owner_id, project_id, package_id))

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
        revision_owner_id: str | None = None,
    ) -> None:
        revision_owner = revision_owner_id or owner_id
        if revision_owner != owner_id:
            await self.get_revision(
                owner_id=revision_owner, package_id=package_id, revision_id=revision_id
            )
            await self._bind_shared(
                owner_id=owner_id,
                project_id=project_id,
                revision_id=revision_id,
                revision_owner_id=revision_owner,
                enabled=enabled,
            )
            return
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

    async def _bind_shared(
        self,
        *,
        owner_id: str,
        project_id: str,
        revision_id: str,
        revision_owner_id: str,
        enabled: bool,
    ) -> None:
        now = datetime.now(tz=UTC)
        async with self._sessions() as session, session.begin():
            workspace = await session.get(ProjectWorkspaceRow, (owner_id, project_id))
            if workspace is None:
                session.add(
                    ProjectWorkspaceRow(
                        owner_id=owner_id, project_id=project_id, created_at=now, updated_at=now
                    )
                )
                await session.flush()
            pin = await session.get(ProjectSkillPinRow, (owner_id, project_id, revision_id))
            if pin is None:
                session.add(
                    ProjectSkillPinRow(
                        owner_id=owner_id,
                        project_id=project_id,
                        revision_id=revision_id,
                        revision_owner_id=revision_owner_id,
                        enabled=enabled,
                        created_at=now,
                        updated_at=now,
                    )
                )
            else:
                pin.enabled = enabled
                pin.updated_at = now

    async def list_discoverable(self, *, owner_id: str) -> list[SkillRevisionRow]:
        """Return the approved catalog for administrative/search use, never runtime scope."""
        from app.skills.bundled import ARCHON_OWNER_ID

        async with self._sessions() as session:
            rows = list(
                await session.scalars(
                    select(SkillRevisionRow)
                    .where(
                        SkillRevisionRow.owner_id.in_((owner_id, ARCHON_OWNER_ID)),
                        SkillRevisionRow.review_state == "approved",
                        SkillRevisionRow.trust_state.in_(("allowlisted", "verified")),
                    )
                    .order_by(
                        SkillRevisionRow.owner_id,
                        SkillRevisionRow.package_id,
                        SkillRevisionRow.revision_number.desc(),
                    )
                )
            )
        latest: dict[str, SkillRevisionRow] = {}
        for row in rows:
            latest.setdefault(row.package_id, row)
        return list(latest.values())

    async def list_project_discoverable(
        self, *, owner_id: str, project_id: str
    ) -> list[SkillRevisionRow]:
        """Return only exact revisions enabled for this owner/project runtime."""
        rows = await self.list_bound(owner_id=owner_id, project_id=project_id)
        return [
            row
            for row in rows
            if row.review_state == "approved" and row.trust_state in {"allowlisted", "verified"}
        ]

    async def list_pin_ids(self, *, owner_id: str, project_id: str) -> tuple[str, ...]:
        async with self._sessions() as session:
            local = await session.scalars(
                select(ProjectSkillBindingRow.revision_id).where(
                    ProjectSkillBindingRow.owner_id == owner_id,
                    ProjectSkillBindingRow.project_id == project_id,
                    ProjectSkillBindingRow.enabled.is_(True),
                )
            )
            shared = await session.scalars(
                select(ProjectSkillPinRow.revision_id).where(
                    ProjectSkillPinRow.owner_id == owner_id,
                    ProjectSkillPinRow.project_id == project_id,
                    ProjectSkillPinRow.enabled.is_(True),
                )
            )
            return tuple(sorted((*local.all(), *shared.all())))

    async def get_visible_revision(self, *, owner_id: str, revision_id: str) -> SkillRevisionRow:
        """Catalog visibility lookup; runtime callers use get_project_visible_revision."""
        from app.skills.bundled import ARCHON_OWNER_ID

        async with self._sessions() as session:
            row = await session.scalar(
                select(SkillRevisionRow).where(
                    SkillRevisionRow.id == revision_id,
                    SkillRevisionRow.owner_id.in_((owner_id, ARCHON_OWNER_ID)),
                    SkillRevisionRow.review_state == "approved",
                    SkillRevisionRow.trust_state.in_(("allowlisted", "verified")),
                )
            )
            if row is None:
                raise SkillNotFoundError("skill revision not found in visible scope")
            return row

    async def get_project_visible_revision(
        self, *, owner_id: str, project_id: str, revision_id: str
    ) -> SkillRevisionRow:
        """Revalidate an enabled exact revision in the current project."""
        async with self._sessions() as session:
            row = await session.get(SkillRevisionRow, revision_id)
            if (
                row is None
                or row.review_state != "approved"
                or row.trust_state
                not in {
                    "allowlisted",
                    "verified",
                }
            ):
                raise SkillNotFoundError("skill revision not enabled in project scope")
            if row.owner_id == owner_id:
                binding = await session.get(
                    ProjectSkillBindingRow, (owner_id, project_id, row.package_id)
                )
                visible = binding is not None and binding.enabled and binding.revision_id == row.id
            else:
                pin = await session.get(ProjectSkillPinRow, (owner_id, project_id, row.id))
                visible = pin is not None and pin.enabled and pin.revision_owner_id == row.owner_id
            if not visible:
                raise SkillNotFoundError("skill revision not enabled in project scope")
            return row

    async def get_reference(
        self,
        *,
        owner_id: str,
        project_id: str,
        revision_id: str,
        path: str,
        max_bytes: int,
    ) -> SkillReferenceRow:
        revision = await self.get_project_visible_revision(
            owner_id=owner_id, project_id=project_id, revision_id=revision_id
        )
        async with self._sessions() as session:
            row = await session.scalar(
                select(SkillReferenceRow)
                .join(
                    SkillRevisionRow,
                    (SkillReferenceRow.revision_id == SkillRevisionRow.id)
                    & (SkillReferenceRow.owner_id == SkillRevisionRow.owner_id),
                )
                .where(
                    SkillReferenceRow.revision_id == revision_id,
                    SkillReferenceRow.path == path,
                    SkillReferenceRow.byte_count <= max_bytes,
                    SkillReferenceRow.owner_id == revision.owner_id,
                    SkillRevisionRow.owner_id == revision.owner_id,
                    SkillRevisionRow.review_state == "approved",
                    SkillRevisionRow.trust_state.in_(("allowlisted", "verified")),
                )
            )
            if row is None:
                raise SkillNotFoundError("skill reference not found in visible scope")
            return row

    async def list_bound(self, *, owner_id: str, project_id: str) -> list[SkillRevisionRow]:
        async with self._sessions() as session:
            result = await session.scalars(
                select(SkillRevisionRow)
                .join(
                    ProjectSkillBindingRow,
                    (ProjectSkillBindingRow.revision_id == SkillRevisionRow.id)
                    & (ProjectSkillBindingRow.owner_id == SkillRevisionRow.owner_id),
                )
                .where(
                    ProjectSkillBindingRow.owner_id == owner_id,
                    ProjectSkillBindingRow.project_id == project_id,
                    ProjectSkillBindingRow.enabled.is_(True),
                    SkillRevisionRow.owner_id == owner_id,
                    SkillRevisionRow.review_state == "approved",
                    SkillRevisionRow.trust_state.in_(("allowlisted", "verified")),
                )
                .order_by(SkillRevisionRow.created_at, SkillRevisionRow.id)
            )
            rows = list(result)
            shared = await session.scalars(
                select(SkillRevisionRow)
                .join(
                    ProjectSkillPinRow,
                    (ProjectSkillPinRow.revision_id == SkillRevisionRow.id)
                    & (ProjectSkillPinRow.revision_owner_id == SkillRevisionRow.owner_id),
                )
                .where(
                    ProjectSkillPinRow.owner_id == owner_id,
                    ProjectSkillPinRow.project_id == project_id,
                    ProjectSkillPinRow.enabled.is_(True),
                    SkillRevisionRow.review_state == "approved",
                    SkillRevisionRow.trust_state.in_(("allowlisted", "verified")),
                )
                .order_by(SkillRevisionRow.created_at, SkillRevisionRow.id)
            )
            return [*rows, *shared]


@dataclass(frozen=True, slots=True)
class ProjectInstructionSnapshot:
    revision: ProjectInstructionRevisionRow
    sources: tuple[ProjectInstructionSourceRow, ...]


class ProjectInstructionRepository:
    """Owner/project-scoped immutable snapshots with exact ordered source bodies."""

    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    @staticmethod
    def _snapshot_hash(sources: tuple[InstructionSource, ...]) -> str:
        document = [
            {
                "ordinal": ordinal,
                "relative_path": source.relative_path,
                "scope_path": source.scope_path,
                "family": source.family.value,
                "is_override": source.is_override,
                "byte_count": source.byte_count,
                "content_hash": source.content_hash,
            }
            for ordinal, source in enumerate(sources)
        ]
        encoded = json.dumps(
            document, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    @staticmethod
    def _validate_sources(sources: tuple[InstructionSource, ...]) -> None:
        if not sources:
            raise ValueError("project instruction snapshot must have at least one source")
        total = 0
        for source in sources:
            raw = source.content.encode("utf-8")
            if len(raw) != source.byte_count:
                raise ValueError("instruction source byte_count does not match body")
            if hashlib.sha256(raw).hexdigest() != source.content_hash:
                raise ValueError("instruction source hash does not match body")
            total += len(raw)
        if total > 256 * 1024:
            raise ValueError("project instructions exceed 262144 bytes")

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
        source = InstructionSource.from_content(
            content, ".archon/instructions.md", ".", InstructionFamily.MANUAL
        )
        snapshot = await self.append_sources(
            owner_id=owner_id,
            project_id=project_id,
            sources=(source,),
            review_state=review_state,
        )
        return snapshot.revision

    async def append_sources(
        self,
        *,
        owner_id: str,
        project_id: str,
        sources: tuple[InstructionSource, ...],
        review_state: str = "pending",
    ) -> ProjectInstructionSnapshot:
        for attempt in range(_MAX_REVISION_WRITE_ATTEMPTS):
            try:
                return await self._append_sources_once(
                    owner_id=owner_id,
                    project_id=project_id,
                    sources=sources,
                    review_state=review_state,
                )
            except (IntegrityError, OperationalError) as exc:
                if attempt + 1 == _MAX_REVISION_WRITE_ATTEMPTS:
                    raise ProjectInstructionConflictError(
                        "concurrent project instruction revision conflict"
                    ) from exc
                await asyncio.sleep(0.01 * (attempt + 1))
        raise AssertionError("unreachable")

    async def _append_sources_once(
        self,
        *,
        owner_id: str,
        project_id: str,
        sources: tuple[InstructionSource, ...],
        review_state: str = "pending",
    ) -> ProjectInstructionSnapshot:
        self._validate_sources(sources)
        digest = self._snapshot_hash(sources)
        now = datetime.now(tz=UTC)
        async with self._sessions() as session, session.begin():
            workspace = await session.get(ProjectWorkspaceRow, (owner_id, project_id))
            if workspace is None:
                workspace = ProjectWorkspaceRow(
                    owner_id=owner_id, project_id=project_id, created_at=now, updated_at=now
                )
                session.add(workspace)
                await session.flush()
            # Serialize revision-number allocation per owner/project on every supported DB.
            await session.execute(
                update(ProjectWorkspaceRow)
                .where(
                    ProjectWorkspaceRow.owner_id == owner_id,
                    ProjectWorkspaceRow.project_id == project_id,
                )
                .values(updated_at=ProjectWorkspaceRow.updated_at)
            )
            existing = await session.scalar(
                select(ProjectInstructionRevisionRow).where(
                    ProjectInstructionRevisionRow.owner_id == owner_id,
                    ProjectInstructionRevisionRow.project_id == project_id,
                    ProjectInstructionRevisionRow.content_hash == digest,
                )
            )
            if existing is not None:
                snapshot = await self._snapshot_in_session(session, existing)
                if review_state == "approved":
                    existing.review_state = "approved"
                    workspace.current_instruction_revision_id = existing.id
                    workspace.updated_at = now
                return snapshot
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
                content=sources[0].content if len(sources) == 1 else "",
                content_hash=digest,
                review_state=review_state,
                created_at=now,
            )
            session.add(row)
            await session.flush()
            stored: list[ProjectInstructionSourceRow] = []
            for ordinal, source in enumerate(sources):
                source_row = ProjectInstructionSourceRow(
                    id=str(uuid.uuid4()),
                    revision_id=row.id,
                    owner_id=owner_id,
                    project_id=project_id,
                    ordinal=ordinal,
                    relative_path=source.relative_path,
                    scope_path=source.scope_path,
                    family=source.family.value,
                    is_override=source.is_override,
                    byte_count=source.byte_count,
                    content_hash=source.content_hash,
                    content=source.content,
                )
                session.add(source_row)
                stored.append(source_row)
            await session.flush()
            if review_state == "approved":
                workspace.current_instruction_revision_id = row.id
                workspace.updated_at = now
            return ProjectInstructionSnapshot(row, tuple(stored))

    async def ensure_workspace(self, *, owner_id: str, project_id: str) -> ProjectWorkspaceRow:
        now = datetime.now(tz=UTC)
        async with self._sessions() as session, session.begin():
            row = await session.get(ProjectWorkspaceRow, (owner_id, project_id))
            if row is None:
                row = ProjectWorkspaceRow(
                    owner_id=owner_id, project_id=project_id, created_at=now, updated_at=now
                )
                session.add(row)
                await session.flush()
            return row

    async def list_revisions(
        self, *, owner_id: str, project_id: str
    ) -> list[ProjectInstructionRevisionRow]:
        async with self._sessions() as session:
            return list(
                await session.scalars(
                    select(ProjectInstructionRevisionRow)
                    .where(
                        ProjectInstructionRevisionRow.owner_id == owner_id,
                        ProjectInstructionRevisionRow.project_id == project_id,
                    )
                    .order_by(ProjectInstructionRevisionRow.revision_number.desc())
                )
            )

    async def _snapshot_in_session(
        self, session: AsyncSession, row: ProjectInstructionRevisionRow
    ) -> ProjectInstructionSnapshot:
        sources = tuple(
            await session.scalars(
                select(ProjectInstructionSourceRow)
                .where(
                    ProjectInstructionSourceRow.revision_id == row.id,
                    ProjectInstructionSourceRow.owner_id == row.owner_id,
                    ProjectInstructionSourceRow.project_id == row.project_id,
                )
                .order_by(ProjectInstructionSourceRow.ordinal)
            )
        )
        if not sources:
            raise ValueError("instruction snapshot has no durable sources")
        rebuilt: list[InstructionSource] = []
        for expected_ordinal, source in enumerate(sources):
            if source.ordinal != expected_ordinal:
                raise ValueError("instruction snapshot source order is not contiguous")
            candidate = InstructionSource.from_content(
                source.content,
                source.relative_path,
                source.scope_path,
                source.family,
                is_override=source.is_override,
            )
            if (
                candidate.byte_count != source.byte_count
                or candidate.content_hash != source.content_hash
            ):
                raise ValueError("instruction snapshot source integrity check failed")
            rebuilt.append(candidate)
        calculated = self._snapshot_hash(tuple(rebuilt))
        legacy_hash = (
            sources[0].content_hash if len(sources) == 1 and sources[0].family == "manual" else None
        )
        if row.content_hash not in {calculated, legacy_hash}:
            raise ValueError("instruction snapshot manifest integrity check failed")
        return ProjectInstructionSnapshot(row, sources)

    async def get_snapshot(
        self, *, owner_id: str, project_id: str, revision_id: str
    ) -> ProjectInstructionSnapshot | None:
        async with self._sessions() as session:
            row = await session.scalar(
                select(ProjectInstructionRevisionRow).where(
                    ProjectInstructionRevisionRow.id == revision_id,
                    ProjectInstructionRevisionRow.owner_id == owner_id,
                    ProjectInstructionRevisionRow.project_id == project_id,
                )
            )
            return None if row is None else await self._snapshot_in_session(session, row)

    async def get(
        self, *, owner_id: str, project_id: str, revision_id: str
    ) -> ProjectInstructionRevisionRow | None:
        snapshot = await self.get_snapshot(
            owner_id=owner_id, project_id=project_id, revision_id=revision_id
        )
        return None if snapshot is None else snapshot.revision

    async def set_current(
        self, *, owner_id: str, project_id: str, revision_id: str | None
    ) -> ProjectInstructionRevisionRow | None:
        async with self._sessions() as session, session.begin():
            workspace = await session.get(ProjectWorkspaceRow, (owner_id, project_id))
            if workspace is None:
                return None
            row = None
            if revision_id is not None:
                row = await session.scalar(
                    select(ProjectInstructionRevisionRow).where(
                        ProjectInstructionRevisionRow.id == revision_id,
                        ProjectInstructionRevisionRow.owner_id == owner_id,
                        ProjectInstructionRevisionRow.project_id == project_id,
                    )
                )
                if row is None:
                    return None
                await self._snapshot_in_session(session, row)
                row.review_state = "approved"
            workspace.current_instruction_revision_id = revision_id
            workspace.updated_at = datetime.now(tz=UTC)
            await session.flush()
            return row

    async def current_snapshot(
        self, *, owner_id: str, project_id: str
    ) -> ProjectInstructionSnapshot | None:
        async with self._sessions() as session:
            workspace = await session.get(ProjectWorkspaceRow, (owner_id, project_id))
            if workspace is None or workspace.current_instruction_revision_id is None:
                return None
            row = await session.scalar(
                select(ProjectInstructionRevisionRow).where(
                    ProjectInstructionRevisionRow.id == workspace.current_instruction_revision_id,
                    ProjectInstructionRevisionRow.owner_id == owner_id,
                    ProjectInstructionRevisionRow.project_id == project_id,
                )
            )
            return None if row is None else await self._snapshot_in_session(session, row)

    async def current(
        self, *, owner_id: str, project_id: str
    ) -> ProjectInstructionRevisionRow | None:
        snapshot = await self.current_snapshot(owner_id=owner_id, project_id=project_id)
        return None if snapshot is None else snapshot.revision
