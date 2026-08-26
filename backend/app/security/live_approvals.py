"""Owner-scoped, ephemeral approval coordination for live runtimes."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from app.runtime.factory import RunContext
from app.security.approval_repository import ApprovalRecord, ApprovalRepository, ApprovalStatus
from app.security.approvals import AuthorizationOutcome, AuthorizationRequest


@dataclass(frozen=True, slots=True)
class ApprovalKey:
    user_id: str
    conversation_id: str
    run_id: str
    tool_call_id: str


@dataclass(slots=True)
class _PendingApproval:
    key: ApprovalKey
    tool_name: str
    arguments_hash: str
    future: asyncio.Future[bool]


class ApprovalBroker:
    """In-memory one-shot broker that stores only routing identity and argument digests."""

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._pending: dict[ApprovalKey, _PendingApproval] = {}

    def authorizer(self, context: RunContext) -> BrokerToolAuthorizer:
        return BrokerToolAuthorizer(self, context)

    @staticmethod
    def _key(context: RunContext, request: AuthorizationRequest) -> ApprovalKey:
        return ApprovalKey(
            context.user_id,
            context.conversation_id,
            context.run_id,
            request.tool_call_id,
        )

    async def reserve(self, context: RunContext, request: AuthorizationRequest) -> None:
        """Publish an exact owner/request binding before its actionable event is emitted."""
        key = self._key(context, request)
        future = asyncio.get_running_loop().create_future()
        item = _PendingApproval(key, request.tool_name, request.arguments_hash, future)
        async with self._lock:
            if key in self._pending:
                raise RuntimeError("duplicate pending approval identity")
            self._pending[key] = item

    async def wait_for_decision(
        self, context: RunContext, request: AuthorizationRequest
    ) -> AuthorizationOutcome:
        key = self._key(context, request)
        async with self._lock:
            item = self._pending.get(key)
            if (
                item is None
                or item.tool_name != request.tool_name
                or item.arguments_hash != request.arguments_hash
            ):
                raise RuntimeError("approval reservation is missing or does not match")
        try:
            approved = await item.future
            return AuthorizationOutcome(
                approved,
                request.tool_call_id,
                request.tool_name,
                request.arguments_hash,
                "user_approved" if approved else "user_denied",
            )
        finally:
            async with self._lock:
                if self._pending.get(key) is item:
                    self._pending.pop(key, None)

    async def cancel(self, context: RunContext, request: AuthorizationRequest) -> None:
        """Remove one exact reservation without affecting a reused or foreign identity."""
        key = self._key(context, request)
        async with self._lock:
            item = self._pending.get(key)
            if (
                item is None
                or item.tool_name != request.tool_name
                or item.arguments_hash != request.arguments_hash
            ):
                return
            self._pending.pop(key, None)
            if not item.future.done():
                item.future.cancel()

    async def decide_for_owner(self, *, user_id: str, tool_call_id: str, approved: bool) -> bool:
        """Atomically consume an owner's unique pending tool-call decision.

        Missing, foreign, already consumed, and ambiguous IDs deliberately produce the same False
        result so the HTTP adapter cannot disclose another owner's pending work.
        """
        async with self._lock:
            matches = [
                item
                for key, item in self._pending.items()
                if key.user_id == user_id
                and key.tool_call_id == tool_call_id
                and not item.future.done()
            ]
            if len(matches) != 1:
                return False
            item = matches[0]
            item.future.set_result(approved)
            return True

    async def cancel_run(self, context: RunContext) -> None:
        """Cancel and remove all approvals belonging to a disconnected/finished run."""
        async with self._lock:
            matches = [
                item
                for key, item in self._pending.items()
                if key.user_id == context.user_id
                and key.conversation_id == context.conversation_id
                and key.run_id == context.run_id
            ]
            for item in matches:
                self._pending.pop(item.key, None)
                if not item.future.done():
                    item.future.cancel()

    async def pending_count(self) -> int:
        async with self._lock:
            return len(self._pending)


@dataclass(frozen=True, slots=True)
class BrokerToolAuthorizer:
    broker: ApprovalBroker
    context: RunContext

    async def prepare(self, request: AuthorizationRequest) -> None:
        await self.broker.reserve(self.context, request)

    async def authorize(self, request: AuthorizationRequest) -> AuthorizationOutcome:
        return await self.broker.wait_for_decision(self.context, request)

    async def cancel(self, request: AuthorizationRequest) -> None:
        await self.broker.cancel(self.context, request)


class DurableApprovalBroker:
    """DB-backed approval broker whose polling works across processes and restarts."""

    def __init__(
        self,
        repository: ApprovalRepository,
        *,
        timeout_seconds: float = 30.0,
        poll_interval_seconds: float = 0.05,
    ) -> None:
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        if poll_interval_seconds <= 0:
            raise ValueError("poll_interval_seconds must be positive")
        self._repository = repository
        self._ttl = timedelta(seconds=timeout_seconds)
        self._poll_interval_seconds = poll_interval_seconds

    def authorizer(self, context: RunContext) -> DurableBrokerToolAuthorizer:
        return DurableBrokerToolAuthorizer(self, context)

    async def reserve(self, context: RunContext, request: AuthorizationRequest) -> None:
        await self._repository.reserve(
            user_id=context.user_id,
            conversation_id=context.conversation_id,
            run_id=context.run_id,
            tool_call_id=request.tool_call_id,
            tool_name=request.tool_name,
            arguments_hash=request.arguments_hash,
            risk_classes=request.risk_classes,
            matched_rule_id=request.matched_rule_id,
            ttl=self._ttl,
        )

    async def _get(
        self,
        context: RunContext,
        request: AuthorizationRequest,
        *,
        now: datetime | None = None,
    ) -> ApprovalRecord | None:
        return await self._repository.get_exact_binding(
            user_id=context.user_id,
            conversation_id=context.conversation_id,
            run_id=context.run_id,
            tool_call_id=request.tool_call_id,
            tool_name=request.tool_name,
            arguments_hash=request.arguments_hash,
            now=now,
        )

    async def wait_for_decision(
        self, context: RunContext, request: AuthorizationRequest
    ) -> AuthorizationOutcome:
        try:
            record = await self._get(context, request)
            if record is None:
                raise RuntimeError("approval reservation is missing or does not match")
            loop = asyncio.get_running_loop()
            remaining = max(0.0, (record.expires_at - datetime.now(tz=UTC)).total_seconds())
            deadline = loop.time() + remaining
            while record.status is ApprovalStatus.PENDING:
                delay = min(self._poll_interval_seconds, max(0.0, deadline - loop.time()))
                if delay <= 0:
                    record = await self._get(context, request, now=record.expires_at)
                    break
                await asyncio.sleep(delay)
                record = await self._get(context, request)
                if record is None:
                    raise RuntimeError("approval reservation is missing or does not match")
        except asyncio.CancelledError:
            await self.cancel(context, request)
            raise

        if record is None:
            raise RuntimeError("approval reservation is missing or does not match")
        if record.status is ApprovalStatus.APPROVED:
            approved = True
            reason = "user_approved"
        elif record.status is ApprovalStatus.DENIED:
            approved = False
            reason = "user_denied"
        else:
            approved = False
            reason = record.decision_reason or "approval_unavailable"
        return AuthorizationOutcome(
            approved,
            request.tool_call_id,
            request.tool_name,
            request.arguments_hash,
            reason,
        )

    async def cancel(self, context: RunContext, request: AuthorizationRequest) -> None:
        await self._repository.cancel_one(
            user_id=context.user_id,
            conversation_id=context.conversation_id,
            run_id=context.run_id,
            tool_call_id=request.tool_call_id,
            tool_name=request.tool_name,
            arguments_hash=request.arguments_hash,
        )

    async def decide_for_owner(self, *, user_id: str, tool_call_id: str, approved: bool) -> bool:
        status = ApprovalStatus.APPROVED if approved else ApprovalStatus.DENIED
        return await self._repository.decide_unique_for_owner(
            user_id=user_id,
            tool_call_id=tool_call_id,
            status=status,
            reason="user_approved" if approved else "user_denied",
        )

    async def cancel_run(self, context: RunContext) -> None:
        await self._repository.cancel_run(user_id=context.user_id, run_id=context.run_id)

    async def pending_count(self) -> int:
        return await self._repository.pending_count()


@dataclass(frozen=True, slots=True)
class DurableBrokerToolAuthorizer:
    broker: DurableApprovalBroker
    context: RunContext

    async def prepare(self, request: AuthorizationRequest) -> None:
        await self.broker.reserve(self.context, request)

    async def authorize(self, request: AuthorizationRequest) -> AuthorizationOutcome:
        return await self.broker.wait_for_decision(self.context, request)

    async def cancel(self, request: AuthorizationRequest) -> None:
        await self.broker.cancel(self.context, request)
