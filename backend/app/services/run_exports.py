"""Owner-scoped immutable run exports and revocable read-only grants."""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, cast

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.security.disclosure import DisclosureScanError, DisclosureScanner
from app.services.context_snapshots import ContextSnapshotRepository
from app.services.db_store import EvalRunRow, RunExportRow, RunShareGrantRow
from app.services.run_ledger import RunRepository

SCHEMA_VERSION = 1
PURPOSES = frozenset({"audit", "incident_review", "evaluation", "support"})
_MAX_EVENTS = 10_000
_TOKEN_KEY_DOMAIN = b"archon/run-share-token-key/v1"


def derive_share_token_hmac_key(application_secret: str) -> bytes:
    if not isinstance(application_secret, str) or not application_secret:
        raise ValueError("share token HMAC secret is unavailable")
    return hmac.new(application_secret.encode("utf-8"), _TOKEN_KEY_DOMAIN, hashlib.sha256).digest()


class ExportIntegrityError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class ExportMetadata:
    export_id: str
    run_id: str
    schema_version: int
    content_checksum: str
    manifest_checksum: str
    created_at: datetime


@dataclass(frozen=True, slots=True)
class ShareGrant:
    grant_id: str
    export_id: str
    recipient_user_id: str
    purpose: str
    created_at: datetime
    expires_at: datetime
    revoked_at: datetime | None


def _canonical(value: Any) -> str:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    )


def _checksum(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode()).hexdigest()


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


class RunExportService:
    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        runs: RunRepository,
        *,
        token_pepper: str,
        scanner: DisclosureScanner | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._sessions = sessions
        self._runs = runs
        self._pepper = derive_share_token_hmac_key(token_pepper)
        self._scanner = scanner or DisclosureScanner()
        self._clock = clock or (lambda: datetime.now(tz=UTC))

    def _now(self) -> datetime:
        return _aware(self._clock())

    def _token_hash(self, token: str) -> str:
        return hmac.new(self._pepper, token.encode(), hashlib.sha256).hexdigest()

    async def _all_events(
        self, owner_id: str, run_id: str
    ) -> tuple[list[dict[str, Any]], bool] | None:
        events: list[dict[str, Any]] = []
        after_sequence = 0
        while len(events) < _MAX_EVENTS:
            limit = min(200, _MAX_EVENTS - len(events))
            page = await self._runs.events(
                owner_id, run_id, limit=limit, after_sequence=after_sequence
            )
            if page is None:
                return None
            if not page.items:
                return events, False
            events.extend(
                {
                    "sequence": item.sequence,
                    "kind": item.kind,
                    "schema_version": item.schema_version,
                    "iteration": item.iteration,
                    "payload": item.payload,
                }
                for item in page.items
            )
            after_sequence = page.items[-1].sequence
            if len(page.items) < limit:
                return events, False
        probe = await self._runs.events(owner_id, run_id, limit=1, after_sequence=after_sequence)
        return events, bool(probe and probe.items)

    async def create_export(self, owner_id: str, run_id: str) -> ExportMetadata | None:
        run = await self._runs.get(owner_id, run_id)
        if run is None:
            return None
        event_result = await self._all_events(owner_id, run_id)
        if event_result is None:
            return None
        events, events_truncated = event_result
        context = await ContextSnapshotRepository(self._sessions).get(
            owner_id=owner_id, project_id=run.project_id, run_id=run_id
        )
        run_data = {
            "run_id": run.run_id,
            "project_id": run.project_id,
            "parent_run_id": run.parent_run_id,
            "fork_source_sequence": run.fork_source_sequence,
            "provider": run.provider,
            "model": run.model,
            "status": run.status,
            "stop_reason": run.stop_reason,
            "answer_summary": run.answer_summary,
            "input_tokens": run.input_tokens,
            "output_tokens": run.output_tokens,
            "total_tokens": run.total_tokens,
            "cost_usd": run.cost_usd,
            "latency_ms": run.latency_ms,
            "iterations": run.iterations,
        }
        context_data = None
        if context is not None:
            context_data = {
                "snapshot_id": context.snapshot_id,
                "schema_version": context.schema_version,
                "selected_message_ids": list(context.selected_message_ids),
                "summarized_message_ids": list(context.summarized_message_ids),
                "memory_ids": list(context.memory_ids),
                "skill_ids": list(context.skill_ids),
                "input_asset_fingerprints": list(context.input_asset_fingerprints),
                "summary_version": context.summary_version,
                "estimated_tokens": context.estimated_tokens,
                "truncation_reason": context.truncation_reason,
                "manifest_hash": context.manifest_hash,
            }
        citations = [
            {"sequence": item["sequence"], "kind": item["kind"], "summary": item["payload"]}
            for item in events
            if item["kind"] in {"evidence_retrieved", "claim_verified", "grounded_answer"}
        ]
        evaluations = await self._evaluation_summaries(owner_id, run_id)
        omissions = [
            "raw_prompts",
            "raw_tool_arguments",
            "raw_tool_results",
            "memory_plaintext",
            "secrets",
            "chain_of_thought",
            "artifacts",
            "approval_credentials",
        ]
        if events_truncated:
            omissions.append(f"events_after_sequence_{events[-1]['sequence']}")
        sections: dict[str, Any] = {
            "run": run_data,
            "events": events,
            "context": context_data,
            "citations": citations,
            "evaluations": evaluations,
            "omissions": omissions,
        }
        scan = self._scanner.scan(sections)
        sections = cast(dict[str, Any], scan.value)
        checksums = {name: _checksum(value) for name, value in sections.items()}
        content_checksum = _checksum(sections)
        export_id = str(uuid.uuid4())
        now = self._now()
        manifest_core = {
            "format": "archon.run-export",
            "schema_version": SCHEMA_VERSION,
            "export_id": export_id,
            "run_id": run_id,
            "created_at": now.isoformat(),
            "disclosure_scan": {
                "performed": True,
                "redaction_count": scan.redaction_count,
                "redaction_types": list(scan.redaction_types),
            },
            "content_checksum": content_checksum,
            "checksums": checksums,
        }
        manifest_checksum = _checksum(manifest_core)
        bundle = {
            "manifest": {**manifest_core, "manifest_checksum": manifest_checksum},
            **sections,
        }
        row = RunExportRow(
            export_id=export_id,
            owner_id=owner_id,
            run_id=run_id,
            schema_version=SCHEMA_VERSION,
            bundle_json=_canonical(bundle),
            content_checksum=content_checksum,
            manifest_checksum=manifest_checksum,
            created_at=now,
        )
        async with self._sessions() as session:
            session.add(row)
            try:
                await session.commit()
            except Exception:
                await session.rollback()
                existing = await session.scalar(
                    select(RunExportRow).where(
                        RunExportRow.owner_id == owner_id,
                        RunExportRow.run_id == run_id,
                        RunExportRow.content_checksum == content_checksum,
                    )
                )
                if existing is None:
                    raise
                row = existing
        return self._export_metadata(row)

    async def _evaluation_summaries(self, owner_id: str, run_id: str) -> list[dict[str, Any]]:
        async with self._sessions() as session:
            rows = (
                await session.scalars(select(EvalRunRow).where(EvalRunRow.owner_id == owner_id))
            ).all()
        return [
            {
                "evaluation_id": row.id,
                "dataset_id": row.dataset_id,
                "dataset_version": row.dataset_version,
                "status": row.status,
                "passed": None if row.passed is None else bool(row.passed),
                "aggregate_metrics": row.aggregate_metrics_json,
            }
            for row in rows
            if run_id in cast(list[str], row.source_run_ids_json)
        ]

    async def list_exports(self, owner_id: str, run_id: str) -> tuple[ExportMetadata, ...]:
        async with self._sessions() as session:
            rows = (
                await session.scalars(
                    select(RunExportRow)
                    .where(RunExportRow.owner_id == owner_id, RunExportRow.run_id == run_id)
                    .order_by(RunExportRow.created_at.desc(), RunExportRow.export_id)
                )
            ).all()
        return tuple(self._export_metadata(row) for row in rows)

    async def download(self, owner_id: str, export_id: str) -> dict[str, Any] | None:
        async with self._sessions() as session:
            row = await session.scalar(
                select(RunExportRow).where(
                    RunExportRow.owner_id == owner_id, RunExportRow.export_id == export_id
                )
            )
        return None if row is None else self._verify_bundle(row)

    async def create_grant(
        self, owner_id: str, export_id: str, recipient_user_id: str, purpose: str, expires_in: int
    ) -> tuple[ShareGrant, str] | None:
        if purpose not in PURPOSES:
            raise ValueError("unsupported share purpose")
        if not recipient_user_id or recipient_user_id == owner_id:
            raise ValueError("a distinct authenticated recipient is required")
        if not 60 <= expires_in <= 604800:
            raise ValueError("expiry must be between 60 seconds and 7 days")
        token = secrets.token_urlsafe(32)
        now = self._now()
        row = RunShareGrantRow(
            grant_id=str(uuid.uuid4()),
            export_id=export_id,
            owner_id=owner_id,
            recipient_user_id=recipient_user_id,
            purpose=purpose,
            token_hash=self._token_hash(token),
            created_at=now,
            expires_at=now + timedelta(seconds=expires_in),
            revoked_at=None,
        )
        async with self._sessions() as session:
            owned = await session.scalar(
                select(RunExportRow.export_id).where(
                    RunExportRow.export_id == export_id, RunExportRow.owner_id == owner_id
                )
            )
            if owned is None:
                return None
            session.add(row)
            await session.commit()
        return self._grant(row), token

    async def list_grants(self, owner_id: str, export_id: str) -> tuple[ShareGrant, ...] | None:
        async with self._sessions() as session:
            owned = await session.scalar(
                select(RunExportRow.export_id).where(
                    RunExportRow.export_id == export_id, RunExportRow.owner_id == owner_id
                )
            )
            if owned is None:
                return None
            rows = (
                await session.scalars(
                    select(RunShareGrantRow)
                    .where(
                        RunShareGrantRow.owner_id == owner_id,
                        RunShareGrantRow.export_id == export_id,
                    )
                    .order_by(RunShareGrantRow.created_at.desc())
                )
            ).all()
        return tuple(self._grant(row) for row in rows)

    async def revoke(self, owner_id: str, grant_id: str) -> bool:
        async with self._sessions() as session:
            result = await session.execute(
                update(RunShareGrantRow)
                .where(
                    RunShareGrantRow.grant_id == grant_id,
                    RunShareGrantRow.owner_id == owner_id,
                    RunShareGrantRow.revoked_at.is_(None),
                )
                .values(revoked_at=self._now())
            )
            await session.commit()
            return bool(getattr(result, "rowcount", 0))

    async def redeem(
        self, recipient_user_id: str, token: str, purpose: str
    ) -> dict[str, Any] | None:
        if purpose not in PURPOSES or not token:
            return None
        digest = self._token_hash(token)
        authorized_at = self._now()
        async with self._sessions() as session, session.begin():
            locked = await session.execute(
                update(RunShareGrantRow)
                .where(
                    RunShareGrantRow.token_hash == digest,
                    RunShareGrantRow.recipient_user_id == recipient_user_id,
                    RunShareGrantRow.purpose == purpose,
                    RunShareGrantRow.revoked_at.is_(None),
                    RunShareGrantRow.expires_at > authorized_at,
                )
                .values(token_hash=RunShareGrantRow.token_hash)
            )
            if getattr(locked, "rowcount", 0) != 1:
                return None
            row = await session.scalar(
                select(RunShareGrantRow).where(RunShareGrantRow.token_hash == digest)
            )
            if row is None:
                return None
            export = await session.scalar(
                select(RunExportRow).where(RunExportRow.export_id == row.export_id)
            )
            if export is None:
                return None
            bundle = self._verify_bundle(export)
            if row.revoked_at is not None or _aware(row.expires_at) <= self._now():
                return None
            return bundle

    def _verify_bundle(self, row: RunExportRow) -> dict[str, Any]:
        try:
            bundle = json.loads(row.bundle_json)
            if not isinstance(bundle, dict) or set(bundle) != {
                "manifest",
                "run",
                "events",
                "context",
                "citations",
                "evaluations",
                "omissions",
            }:
                raise ExportIntegrityError("malformed export bundle")
            manifest = bundle["manifest"]
            if not isinstance(manifest, dict) or set(manifest) != {
                "format",
                "schema_version",
                "export_id",
                "run_id",
                "created_at",
                "disclosure_scan",
                "content_checksum",
                "checksums",
                "manifest_checksum",
            }:
                raise ExportIntegrityError("malformed export manifest")
            if (
                row.schema_version != SCHEMA_VERSION
                or manifest.get("format") != "archon.run-export"
                or manifest.get("schema_version") != row.schema_version
                or manifest.get("export_id") != row.export_id
                or manifest.get("run_id") != row.run_id
                or manifest.get("created_at") != _aware(row.created_at).isoformat()
            ):
                raise ExportIntegrityError("export manifest binding mismatch")
            manifest_core = {
                key: value for key, value in manifest.items() if key != "manifest_checksum"
            }
            if not hmac.compare_digest(
                str(manifest.get("manifest_checksum", "")), row.manifest_checksum
            ) or not hmac.compare_digest(_checksum(manifest_core), row.manifest_checksum):
                raise ExportIntegrityError("export manifest checksum mismatch")
            sections = {key: value for key, value in bundle.items() if key != "manifest"}
            scan = self._scanner.scan(sections)
            if scan.redaction_count or scan.value != sections:
                raise ExportIntegrityError("export failed disclosure rescan")
            expected = {name: _checksum(value) for name, value in sections.items()}
            if (
                not hmac.compare_digest(_checksum(sections), row.content_checksum)
                or manifest.get("content_checksum") != row.content_checksum
                or manifest.get("checksums") != expected
            ):
                raise ExportIntegrityError("export checksum mismatch")
            return cast(dict[str, Any], bundle)
        except ExportIntegrityError:
            raise
        except (
            DisclosureScanError,
            KeyError,
            TypeError,
            ValueError,
            UnicodeError,
            RecursionError,
            json.JSONDecodeError,
        ) as exc:
            raise ExportIntegrityError("malformed export bundle") from exc

    @staticmethod
    def _export_metadata(row: RunExportRow) -> ExportMetadata:
        return ExportMetadata(
            row.export_id,
            row.run_id,
            row.schema_version,
            row.content_checksum,
            row.manifest_checksum,
            row.created_at,
        )

    @staticmethod
    def _grant(row: RunShareGrantRow) -> ShareGrant:
        return ShareGrant(
            row.grant_id,
            row.export_id,
            row.recipient_user_id,
            row.purpose,
            row.created_at,
            row.expires_at,
            row.revoked_at,
        )
