"""Run-scoped durable at-most-once orchestration for effectful tools."""

from __future__ import annotations

import asyncio
import copy
import hashlib
import json
from dataclasses import dataclass

from app.runtime.effect_ledger import EffectIdentityInput, EffectState, bind_effect_identity
from app.runtime.models import ToolCall
from app.runtime.monetary_budget import _cancellation_resistant
from app.services.effect_ledger import EffectRepository
from app.tools.registry import SecureToolRegistry


class IndeterminateToolEffect(RuntimeError):
    code = "indeterminate_tool_effect"

    def __init__(self) -> None:
        super().__init__(self.code)


@dataclass(frozen=True, slots=True)
class EffectRunContext:
    owner_id: str
    project_id: str
    run_id: str


def _output_evidence(output: dict[str, object]) -> tuple[dict[str, object], str, int]:
    try:
        snapshot = copy.deepcopy(output)
        encoded = json.dumps(
            snapshot,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
            default=lambda value: f"<{type(value).__name__}>",
        ).encode("utf-8")
    except (TypeError, ValueError, UnicodeEncodeError, RecursionError):
        raise IndeterminateToolEffect from None
    if len(encoded) > 1_048_576:
        raise IndeterminateToolEffect from None
    return snapshot, hashlib.sha256(encoded).hexdigest(), len(encoded)


class DurableEffectToolExecutor:
    """Reserve effect identity after policy approval and immediately before dispatch."""

    def __init__(
        self,
        delegate: SecureToolRegistry,
        repository: EffectRepository,
        context: EffectRunContext,
        identity_secret: bytes,
    ) -> None:
        if not isinstance(delegate, SecureToolRegistry):
            raise TypeError("durable effect executor requires SecureToolRegistry")
        if not isinstance(context, EffectRunContext):
            raise TypeError("context must be EffectRunContext")
        if not isinstance(identity_secret, bytes) or len(identity_secret) < 32:
            raise ValueError("effect identity secret must contain at least 32 bytes")
        self._delegate = delegate
        self._repository = repository
        self._context = context
        self._identity_secret = bytes(identity_secret)

    def definitions(self):
        return self._delegate.definitions()

    def policy_request(self, call: ToolCall):
        return self._delegate.policy_request(call)

    def tool_requires_approval(self, name: str) -> bool:
        return self._delegate.tool_requires_approval(name)

    async def _mark_indeterminate(self, effect_id: str, code: str) -> None:
        record = await self._repository.get(
            effect_id,
            owner_id=self._context.owner_id,
            project_id=self._context.project_id,
            run_id=self._context.run_id,
        )
        if record is not None and record.state is EffectState.RESERVED:
            await self._repository.mark_indeterminate(effect_id, code)

    async def execute(self, call: ToolCall) -> dict[str, object]:
        spec = self._delegate.effect_spec(call)
        if not spec.effectful:
            return await self._delegate.execute(call)

        context = self._context
        binding = bind_effect_identity(
            EffectIdentityInput(
                owner_id=context.owner_id,
                project_id=context.project_id,
                run_id=context.run_id,
                tool_name=call.name,
                arguments=call.arguments,
                resources=spec.resources,
                input_schema=spec.input_schema,
                tool_call_id=call.id,
            ),
            self._identity_secret,
        )
        reservation_outcome = await _cancellation_resistant(self._repository.reserve(binding))
        if reservation_outcome.error is not None:
            if reservation_outcome.cancellation is not None:
                raise reservation_outcome.cancellation
            raise reservation_outcome.error
        reservation = reservation_outcome.value
        assert reservation is not None
        if reservation_outcome.cancellation is not None:
            if reservation.should_execute:
                released = await _cancellation_resistant(
                    self._repository.fail(binding.effect_id, "dispatch_cancelled")
                )
                if released.error is not None:
                    raise IndeterminateToolEffect from None
            raise reservation_outcome.cancellation
        if not reservation.should_execute:
            return {
                "status": "duplicate_effect_blocked",
                "effect_id": reservation.effect_id,
                "effect_state": reservation.state.value,
            }

        try:
            output = await self._delegate.execute_effect(call, effect_id=binding.effect_id)
            snapshot, output_hash, output_size = _output_evidence(output)
            committed = await _cancellation_resistant(
                self._repository.commit(binding.effect_id, output_hash, output_size)
            )
            if committed.error is not None:
                cleanup = await _cancellation_resistant(
                    self._mark_indeterminate(binding.effect_id, "commit_failed")
                )
                if cleanup.error is not None:
                    raise IndeterminateToolEffect from None
                raise IndeterminateToolEffect from None
            if committed.cancellation is not None:
                raise committed.cancellation
            return snapshot
        except PermissionError:
            failed = await _cancellation_resistant(
                self._repository.fail(binding.effect_id, "permission_denied")
            )
            if failed.error is not None:
                raise IndeterminateToolEffect from None
            raise
        except BaseException as error:
            cleanup = await _cancellation_resistant(
                self._mark_indeterminate(binding.effect_id, "dispatch_interrupted")
            )
            if cleanup.error is not None:
                raise IndeterminateToolEffect from None
            if isinstance(error, asyncio.CancelledError):
                raise error
            if cleanup.cancellation is not None:
                raise cleanup.cancellation from None
            raise
