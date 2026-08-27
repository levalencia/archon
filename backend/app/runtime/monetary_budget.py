"""Run-scoped durable monetary enforcement for every typed model call.

The wrapper persists only safe call/accounting metadata. Prompts, messages, tool
arguments, response content, and response contracts never cross this boundary.
"""

from __future__ import annotations

import asyncio
import copy
import hashlib
import inspect
import re
from collections.abc import Awaitable, Sequence
from dataclasses import dataclass
from typing import Any, Generic, TypeVar

from app.observability.cost_tracker import (
    price_model_usage_nusd,
    quote_model_call_nusd,
    validated_pricing_pair,
)
from app.runtime.capabilities import ProviderCapabilities, get_provider_capabilities
from app.runtime.models import Message, ModelResponse, TokenUsage, ToolCall, ToolDefinition
from app.runtime.ports import ModelProvider
from app.runtime.structured_output import ResponseContract
from app.services.monetary_budget import (
    ChargeState,
    ChargeStateConflict,
    MonetaryBudgetRepository,
    ProjectBudgetExceeded,
    QuoteExceeded,
    RunBudgetExceeded,
)

_MAX_BIGINT = 2**63 - 1
_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$")
_T = TypeVar("_T")


def _identifier(value: str, label: str, maximum: int) -> str:
    if not isinstance(value, str) or len(value) > maximum or not _SAFE_ID.fullmatch(value):
        raise ValueError(f"{label} must be a safe non-empty identifier")
    return value


def _amount(value: int, label: str) -> int:
    if type(value) is not int or not 0 <= value <= _MAX_BIGINT:
        raise ValueError(f"{label} must be an integer within the BIGINT range")
    return value


@dataclass(frozen=True, slots=True)
class BudgetRunContext:
    """Immutable owner scope for one run-scoped provider instance."""

    owner_id: str
    project_id: str
    run_id: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "owner_id", _identifier(self.owner_id, "owner_id", 255))
        object.__setattr__(self, "project_id", _identifier(self.project_id, "project_id", 255))
        object.__setattr__(self, "run_id", _identifier(self.run_id, "run_id", 36))


@dataclass(frozen=True, slots=True)
class PricingCandidate:
    """A canonical provider/model pair that may actually service this run."""

    provider: str
    model: str

    def __post_init__(self) -> None:
        provider, model = validated_pricing_pair(self.model, self.provider)
        object.__setattr__(self, "provider", provider)
        object.__setattr__(self, "model", model)


class BudgetedProviderError(RuntimeError):
    """Sanitized stable failure at the budgeted model-provider boundary."""

    code = "budgeted_provider_error"

    def __init__(self) -> None:
        super().__init__(self.code)


class ModelBudgetExhausted(BudgetedProviderError):  # noqa: N818 - domain contract name
    """A call's conservative quote does not fit an immutable run/project limit."""

    code = "model_budget_exhausted"


class DuplicateModelCharge(BudgetedProviderError):  # noqa: N818 - domain contract name
    """The durable charge identity or run ordinal already exists."""

    code = "duplicate_model_charge"


class IndeterminateModelCharge(BudgetedProviderError):  # noqa: N818 - domain contract name
    """A dispatched call cannot be safely and exactly reconciled."""

    code = "indeterminate_model_charge"


class DurableModelChargeStateError(BudgetedProviderError):  # noqa: N818
    """The wrapper could not establish a safe durable terminal charge state."""

    code = "durable_model_charge_state_error"


# Descriptive aliases keep the stable boundary discoverable without multiplying behavior.
BudgetExhaustedError = ModelBudgetExhausted
DuplicateChargeError = DuplicateModelCharge
IndeterminateChargeError = IndeterminateModelCharge


def _charge_id(run_id: str, ordinal: int) -> str:
    """Bind a safe deterministic charge ID to run and ordinal, never to request data."""

    digest = hashlib.sha256(f"{run_id}:{ordinal}".encode()).hexdigest()
    return f"model_v1_{digest}"


@dataclass(frozen=True, slots=True)
class _DurableOutcome(Generic[_T]):
    value: _T | None
    error: BaseException | None
    cancellation: asyncio.CancelledError | None


async def _cancellation_resistant(operation: Awaitable[_T]) -> _DurableOutcome[_T]:
    """Run an awaitable to terminal state despite repeated caller cancellation."""

    task = asyncio.ensure_future(operation)
    cancellation: asyncio.CancelledError | None = None
    while not task.done():
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError as error:
            current = asyncio.current_task()
            if current is not None:
                current.uncancel()
            if cancellation is None:
                cancellation = error
        except BaseException:
            # A child failure is read below without another cancellation point.
            break
    try:
        return _DurableOutcome(task.result(), None, cancellation)
    except BaseException as error:
        return _DurableOutcome(None, error, cancellation)


def _stable_cleanup_failure() -> DurableModelChargeStateError:
    """Build a stable error which contains no repository detail."""

    return DurableModelChargeStateError()


def _snapshot_response(response: object) -> ModelResponse:
    """Detach accounting and returned values from delegate-owned state."""

    if type(response) is not ModelResponse:
        raise IndeterminateModelCharge
    usage = response.usage
    if type(usage) is not TokenUsage:
        raise IndeterminateModelCharge
    counts = (
        usage.input_tokens,
        usage.output_tokens,
        usage.cache_read_input_tokens,
        usage.cache_write_input_tokens,
    )
    if (
        type(counts[0]) is not int
        or type(counts[1]) is not int
        or any(count is not None and type(count) is not int for count in counts[2:])
        or any(count is not None and not 0 <= count <= _MAX_BIGINT for count in counts)
        or (counts[2] or 0) + (counts[3] or 0) > counts[0]
    ):
        raise IndeterminateModelCharge
    scalar_values = (
        response.content,
        response.provider_stop_reason,
        response.actual_provider,
        response.actual_model,
    )
    if any(value is not None and type(value) is not str for value in scalar_values):
        raise IndeterminateModelCharge
    if type(response.tool_calls) is not tuple:
        raise IndeterminateModelCharge

    try:
        copied_calls: list[ToolCall] = []
        for call in response.tool_calls:
            if type(call) is not ToolCall or type(call.id) is not str or type(call.name) is not str:
                raise IndeterminateModelCharge
            copied_calls.append(ToolCall(call.id, call.name, copy.deepcopy(dict(call.arguments))))
        return ModelResponse(
            content=response.content,
            tool_calls=tuple(copied_calls),
            usage=TokenUsage(*counts),
            provider_stop_reason=response.provider_stop_reason,
            structured_output=copy.deepcopy(response.structured_output),
            actual_provider=response.actual_provider,
            actual_model=response.actual_model,
        )
    except IndeterminateModelCharge:
        raise
    except Exception:
        raise IndeterminateModelCharge from None


class DurableBudgetedProvider:
    """Run-scoped provider wrapper with durable reserve/dispatch/reconcile accounting."""

    def __init__(
        self,
        delegate: ModelProvider,
        repository: MonetaryBudgetRepository,
        context: BudgetRunContext,
        run_limit_nusd: int,
        project_limit_nusd: int,
        max_input_tokens: int,
        pricing_candidates: Sequence[PricingCandidate],
    ) -> None:
        if not isinstance(context, BudgetRunContext):
            raise TypeError("context must be a BudgetRunContext")
        if isinstance(pricing_candidates, (str, bytes)):
            raise ValueError("pricing_candidates must be a non-empty sequence")
        candidates = tuple(pricing_candidates)
        if not candidates:
            raise ValueError("pricing_candidates must not be empty")
        if any(not isinstance(candidate, PricingCandidate) for candidate in candidates):
            raise TypeError("pricing_candidates must contain PricingCandidate values")
        if len(set(candidates)) != len(candidates):
            raise ValueError("pricing_candidates must not contain duplicates")

        self._delegate = delegate
        self._repository = repository
        self._context = context
        self._run_limit_nusd = _amount(run_limit_nusd, "run_limit_nusd")
        self._project_limit_nusd = _amount(project_limit_nusd, "project_limit_nusd")
        self._max_input_tokens = _amount(max_input_tokens, "max_input_tokens")
        self._pricing_candidates = candidates
        self._allowed_pairs = frozenset((item.provider, item.model) for item in candidates)
        self._quote_pairs = tuple((item.provider, item.model) for item in candidates)
        self._opened = False
        self._open_lock = asyncio.Lock()
        self._ordinal_lock = asyncio.Lock()
        self._next_ordinal = 0

        # Preserve capability declarations exactly as the existing typed wrappers do.
        self.capabilities = get_provider_capabilities(delegate)
        self.routes_capabilities = (
            inspect.getattr_static(delegate, "routes_capabilities", False) is True
        )

    @property
    def context(self) -> BudgetRunContext:
        return self._context

    @property
    def run_limit_nusd(self) -> int:
        return self._run_limit_nusd

    @property
    def project_limit_nusd(self) -> int:
        return self._project_limit_nusd

    @property
    def max_input_tokens(self) -> int:
        return self._max_input_tokens

    @property
    def pricing_candidates(self) -> tuple[PricingCandidate, ...]:
        return self._pricing_candidates

    async def _ensure_open(self) -> None:
        if self._opened:
            return
        async with self._open_lock:
            if self._opened:
                return
            context = self._context
            await self._repository.open_run(
                context.owner_id,
                context.project_id,
                context.run_id,
                self._run_limit_nusd,
                self._project_limit_nusd,
            )
            self._opened = True

    async def _allocate_ordinal(self) -> int:
        async with self._ordinal_lock:
            ordinal = self._next_ordinal
            if ordinal > 2**31 - 1:
                raise OverflowError("model call ordinal is exhausted")
            self._next_ordinal += 1
            return ordinal

    def _quoted_candidate(self, max_tokens: int) -> tuple[int, PricingCandidate]:
        quote = quote_model_call_nusd(
            self._quote_pairs,
            self._max_input_tokens,
            max_tokens,
        )
        # Persist a priceable pair whose no-cache price equals the reservation.
        quoted = max(
            self._pricing_candidates,
            key=lambda candidate: price_model_usage_nusd(
                candidate.model,
                candidate.provider,
                self._max_input_tokens,
                max_tokens,
            ),
        )
        return quote, quoted

    async def _mark_indeterminate_if_active(self, charge_id: str, reason: str) -> None:
        """Inspect first and preserve every already-terminal durable state."""

        context = self._context
        charge = await self._repository.get(
            charge_id,
            owner_id=context.owner_id,
            project_id=context.project_id,
            run_id=context.run_id,
        )
        if charge is None:
            raise ChargeStateConflict
        if charge.state not in (ChargeState.RESERVED, ChargeState.DISPATCHED):
            return
        try:
            await self._repository.mark_indeterminate(
                charge_id,
                context.owner_id,
                context.project_id,
                context.run_id,
                reason,
            )
        except ChargeStateConflict:
            # A terminal transition may have won after the inspection. Verify it.
            charge = await self._repository.get(
                charge_id,
                owner_id=context.owner_id,
                project_id=context.project_id,
                run_id=context.run_id,
            )
            if charge is None or charge.state in (ChargeState.RESERVED, ChargeState.DISPATCHED):
                raise

    async def _recover_failed_dispatch(self, charge_id: str) -> None:
        """Release proven pre-dispatch work and fail closed for an ambiguous commit."""

        context = self._context
        charge = await self._repository.get(
            charge_id,
            owner_id=context.owner_id,
            project_id=context.project_id,
            run_id=context.run_id,
        )
        if charge is None:
            raise ChargeStateConflict
        if charge.state is ChargeState.RESERVED:
            await self._repository.release(
                charge_id,
                context.owner_id,
                context.project_id,
                context.run_id,
            )
        elif charge.state is ChargeState.DISPATCHED:
            await self._repository.mark_indeterminate(
                charge_id,
                context.owner_id,
                context.project_id,
                context.run_id,
                "dispatch_interrupted",
            )

    async def complete(
        self,
        messages: Sequence[Message],
        tools: Sequence[ToolDefinition] = (),
        *,
        max_tokens: int = 4096,
        response_contract: ResponseContract | None = None,
        response_format: str | None = None,
        required_capabilities: ProviderCapabilities | None = None,
    ) -> ModelResponse:
        """Reserve and reconcile one model call without retaining request payload data."""

        if response_contract is not None and response_format is not None:
            raise ValueError("response_contract and response_format are mutually exclusive")

        # Validate and calculate before opening/allocating so malformed calls have no ledger effect.
        quote, quoted_candidate = self._quoted_candidate(max_tokens)
        kwargs: dict[str, Any] = {"max_tokens": max_tokens}
        if response_contract is not None:
            kwargs["response_contract"] = response_contract
        if response_format is not None:
            kwargs["response_format"] = response_format
        if self.routes_capabilities and required_capabilities is not None:
            kwargs["required_capabilities"] = required_capabilities

        await self._ensure_open()
        ordinal = await self._allocate_ordinal()
        charge_id = _charge_id(self._context.run_id, ordinal)
        context = self._context
        reserve_outcome = await _cancellation_resistant(
            self._repository.reserve_call(
                charge_id,
                context.owner_id,
                context.project_id,
                context.run_id,
                ordinal,
                quote,
                quoted_candidate.provider,
                quoted_candidate.model,
            )
        )
        if reserve_outcome.error is not None:
            if reserve_outcome.cancellation is not None:
                raise reserve_outcome.cancellation
            if isinstance(reserve_outcome.error, (ProjectBudgetExceeded, RunBudgetExceeded)):
                raise ModelBudgetExhausted from None
            raise reserve_outcome.error
        reservation = reserve_outcome.value
        assert reservation is not None
        if reserve_outcome.cancellation is not None:
            if reservation.should_dispatch:
                release_outcome = await _cancellation_resistant(
                    self._repository.release(
                        charge_id,
                        context.owner_id,
                        context.project_id,
                        context.run_id,
                    )
                )
                if release_outcome.error is not None:
                    raise _stable_cleanup_failure() from IndeterminateModelCharge()
            raise reserve_outcome.cancellation
        if not reservation.should_dispatch:
            raise DuplicateModelCharge

        # This transition is the final operation before dispatch. Any failure or
        # caller cancellation is recovered without ever invoking the delegate.
        dispatch_outcome = await _cancellation_resistant(
            self._repository.mark_dispatched(
                charge_id,
                context.owner_id,
                context.project_id,
                context.run_id,
            )
        )
        dispatch_failure = dispatch_outcome.cancellation or dispatch_outcome.error
        if dispatch_failure is not None:
            recovery = await _cancellation_resistant(self._recover_failed_dispatch(charge_id))
            if recovery.error is not None:
                raise _stable_cleanup_failure() from IndeterminateModelCharge()
            if isinstance(dispatch_failure, asyncio.CancelledError):
                raise dispatch_failure
            if recovery.cancellation is not None:
                raise recovery.cancellation
            raise dispatch_failure

        try:
            response = await self._delegate.complete(messages, tools, **kwargs)
            snapshot = _snapshot_response(response)

            actual_provider = snapshot.actual_provider
            actual_model = snapshot.actual_model
            if actual_provider is None or actual_model is None:
                if (
                    len(self._pricing_candidates) != 1
                    or actual_provider is not None
                    or actual_model is not None
                ):
                    raise IndeterminateModelCharge
                fallback = self._pricing_candidates[0]
                actual_provider = fallback.provider
                actual_model = fallback.model

            try:
                actual_pair = validated_pricing_pair(actual_model, actual_provider)
            except (TypeError, ValueError):
                raise IndeterminateModelCharge from None
            if actual_pair not in self._allowed_pairs:
                raise IndeterminateModelCharge

            usage = snapshot.usage
            reconcile_outcome = await _cancellation_resistant(
                self._repository.reconcile(
                    charge_id,
                    context.owner_id,
                    context.project_id,
                    context.run_id,
                    None,
                    usage.input_tokens,
                    usage.output_tokens,
                    usage.cache_read_input_tokens,
                    usage.cache_write_input_tokens,
                    provider=actual_pair[0],
                    model=actual_pair[1],
                )
            )
            if reconcile_outcome.cancellation is not None:
                raise reconcile_outcome.cancellation
            if reconcile_outcome.error is not None:
                if isinstance(
                    reconcile_outcome.error, (QuoteExceeded, ChargeStateConflict, ValueError)
                ):
                    raise IndeterminateModelCharge from None
                raise reconcile_outcome.error
            return snapshot
        except BaseException as original:
            reason = (
                "call_cancelled" if isinstance(original, asyncio.CancelledError) else "call_failed"
            )
            cleanup = await _cancellation_resistant(
                self._mark_indeterminate_if_active(charge_id, reason)
            )
            if cleanup.error is not None:
                raise _stable_cleanup_failure() from IndeterminateModelCharge()
            if isinstance(original, asyncio.CancelledError):
                raise original
            if cleanup.cancellation is not None:
                raise cleanup.cancellation from None
            raise


# Alternate explicit names used by callers discussing calls rather than charges.
BudgetExhausted = ModelBudgetExhausted
DuplicateModelCall = DuplicateModelCharge
IndeterminateModelCall = IndeterminateModelCharge
