"""Owner-scoped, ephemeral approval coordination for live runtimes."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

from app.runtime.factory import RunContext
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

    async def wait_for_decision(
        self, context: RunContext, request: AuthorizationRequest
    ) -> AuthorizationOutcome:
        key = ApprovalKey(
            context.user_id,
            context.conversation_id,
            context.run_id,
            request.tool_call_id,
        )
        future = asyncio.get_running_loop().create_future()
        item = _PendingApproval(key, request.tool_name, request.arguments_hash, future)
        async with self._lock:
            if key in self._pending:
                raise RuntimeError("duplicate pending approval identity")
            self._pending[key] = item
        try:
            approved = await future
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
            self._pending.pop(item.key, None)
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

    async def authorize(self, request: AuthorizationRequest) -> AuthorizationOutcome:
        return await self.broker.wait_for_decision(self.context, request)
