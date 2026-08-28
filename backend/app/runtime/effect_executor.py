"""Run-scoped durable at-most-once orchestration for effectful tools."""

from __future__ import annotations

import asyncio
import copy
import hashlib
import json
import math
from dataclasses import dataclass

from app.runtime.effect_ledger import EffectIdentityInput, EffectState, bind_effect_identity
from app.runtime.models import ToolCall
from app.runtime.monetary_budget import _cancellation_resistant
from app.security.policy import ResourcePattern, canonical_arguments_hash, canonical_tool_name
from app.services.effect_ledger import EffectRepository
from app.tools.registry import SecureToolRegistry


class EffectDispatchRejectedError(RuntimeError):
    code = "effect_dispatch_rejected"

    def __init__(self) -> None:
        super().__init__(self.code)


class IndeterminateToolEffectError(RuntimeError):
    code = "indeterminate_tool_effect"

    def __init__(self) -> None:
        super().__init__(self.code)


@dataclass(frozen=True, slots=True)
class EffectRunContext:
    owner_id: str
    project_id: str
    run_id: str


def _output_evidence(output: dict[str, object]) -> tuple[dict[str, object], str, int]:
    stack: list[tuple[object, int]] = [(output, 0)]
    ancestors: set[int] = set()
    nodes = 0
    string_bytes = 0
    while stack:
        value, depth = stack.pop()
        nodes += 1
        if depth > 32 or nodes > 4096:
            raise IndeterminateToolEffectError from None
        if value is None or type(value) is bool:
            continue
        if type(value) is int:
            if len(str(abs(value))) > 1000:
                raise IndeterminateToolEffectError from None
            continue
        if type(value) is float:
            if not math.isfinite(value):
                raise IndeterminateToolEffectError from None
            continue
        if type(value) is str:
            try:
                size = len(value.encode("utf-8"))
            except UnicodeEncodeError:
                raise IndeterminateToolEffectError from None
            if size > 16_384:
                raise IndeterminateToolEffectError from None
            string_bytes += size
            if string_bytes > 1_048_576:
                raise IndeterminateToolEffectError from None
            continue
        if type(value) is dict:
            identity = id(value)
            if identity in ancestors:
                raise IndeterminateToolEffectError from None
            ancestors.add(identity)
            for key, item in value.items():
                if type(key) is not str:
                    raise IndeterminateToolEffectError from None
                stack.append((key, depth + 1))
                stack.append((item, depth + 1))
            continue
        if type(value) is list:
            identity = id(value)
            if identity in ancestors:
                raise IndeterminateToolEffectError from None
            ancestors.add(identity)
            stack.extend((item, depth + 1) for item in value)
            continue
        raise IndeterminateToolEffectError from None

    try:
        snapshot = copy.deepcopy(output)
        encoded = json.dumps(
            snapshot,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    except (TypeError, ValueError, UnicodeEncodeError, RecursionError):
        raise IndeterminateToolEffectError from None
    if len(encoded) > 1_048_576:
        raise IndeterminateToolEffectError from None
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
        self._approved_resources: dict[tuple[str, str, str], tuple[ResourcePattern, ...]] = {}

    @staticmethod
    def _call_key(call: ToolCall) -> tuple[str, str, str]:
        return (
            call.id,
            canonical_tool_name(call.name),
            canonical_arguments_hash(call.arguments),
        )

    def definitions(self):
        return self._delegate.definitions()

    def policy_request(self, call: ToolCall):
        request = self._delegate.policy_request(call)
        self._approved_resources[self._call_key(call)] = request.resources
        return request

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
        approved_resources = self._approved_resources.pop(self._call_key(call), None)
        spec = self._delegate.effect_spec(call, approved_resources=approved_resources)
        if not spec.effectful:
            return await self._delegate.execute(call)
        self._delegate.enforce_effect_compliance(call)

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
                    raise IndeterminateToolEffectError from None
            raise reservation_outcome.cancellation
        if not reservation.should_execute:
            return {
                "status": "duplicate_effect_blocked",
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
                    raise IndeterminateToolEffectError from None
                raise IndeterminateToolEffectError from None
            if committed.cancellation is not None:
                raise committed.cancellation
            return snapshot
        except PermissionError:
            failed = await _cancellation_resistant(
                self._repository.fail(binding.effect_id, "permission_denied")
            )
            if failed.error is not None:
                raise IndeterminateToolEffectError from None
            raise EffectDispatchRejectedError from None
        except BaseException as error:
            cleanup = await _cancellation_resistant(
                self._mark_indeterminate(binding.effect_id, "dispatch_interrupted")
            )
            if cleanup.error is not None:
                raise IndeterminateToolEffectError from None
            if isinstance(error, asyncio.CancelledError):
                raise error
            if cleanup.cancellation is not None:
                raise cleanup.cancellation from None
            if isinstance(error, Exception):
                raise IndeterminateToolEffectError from None
            raise
