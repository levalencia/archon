"""Run-scoped durable monetary enforcement for every typed model call.

The wrapper persists only safe call/accounting metadata. Prompts, messages, tool
arguments, response content, and response contracts never cross this boundary.
"""

from __future__ import annotations

import asyncio
import hashlib
import inspect
import re
from collections.abc import Awaitable, Sequence
from contextlib import suppress
from dataclasses import dataclass
from typing import Any, TypeVar

from app.observability.cost_tracker import (
    price_model_usage_nusd,
    quote_model_call_nusd,
    validated_pricing_pair,
)
from app.runtime.capabilities import ProviderCapabilities, get_provider_capabilities
from app.runtime.models import Message, ModelResponse, TokenUsage, ToolDefinition
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


# Descriptive aliases keep the stable boundary discoverable without multiplying behavior.
BudgetExhaustedError = ModelBudgetExhausted
DuplicateChargeError = DuplicateModelCharge
IndeterminateChargeError = IndeterminateModelCharge


def _charge_id(run_id: str, ordinal: int) -> str:
    """Bind a safe deterministic charge ID to run and ordinal, never to request data."""

    digest = hashlib.sha256(f"{run_id}:{ordinal}".encode()).hexdigest()
    return f"model_v1_{digest}"


async def _cancellation_resistant(operation: Awaitable[_T]) -> _T:
    """Finish one durable transition before allowing caller cancellation to propagate."""

    task = asyncio.ensure_future(operation)
    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError:
        # shield keeps the transition alive. Once the delivered cancellation has
        # been caught, awaiting its task ensures persistence before we re-raise.
        return await task


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

    async def _mark_indeterminate(self, charge_id: str, reason: str) -> None:
        context = self._context
        await _cancellation_resistant(
            self._repository.mark_indeterminate(
                charge_id,
                context.owner_id,
                context.project_id,
                context.run_id,
                reason,
            )
        )

    async def _recover_failed_dispatch(self, charge_id: str) -> None:
        """Resolve only a durably observed pre-dispatch state; otherwise fail closed."""

        context = self._context
        charge = await self._repository.get(
            charge_id,
            owner_id=context.owner_id,
            project_id=context.project_id,
            run_id=context.run_id,
        )
        if charge is None:
            return
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
        try:
            reservation = await self._repository.reserve_call(
                charge_id,
                context.owner_id,
                context.project_id,
                context.run_id,
                ordinal,
                quote,
                quoted_candidate.provider,
                quoted_candidate.model,
            )
        except (ProjectBudgetExceeded, RunBudgetExceeded):
            raise ModelBudgetExhausted from None
        if not reservation.should_dispatch:
            raise DuplicateModelCharge

        # This durable transition is intentionally the final operation before the provider await.
        try:
            await self._repository.mark_dispatched(
                charge_id,
                context.owner_id,
                context.project_id,
                context.run_id,
            )
        except BaseException:
            # Inspect persisted state rather than guessing whether an interrupted
            # database await committed. Only a proven reservation is released.
            with suppress(Exception):
                await _cancellation_resistant(self._recover_failed_dispatch(charge_id))
            raise
        try:
            response = await self._delegate.complete(messages, tools, **kwargs)
        except asyncio.CancelledError:
            # Accounting trouble must not replace the provider's established exception boundary.
            with suppress(Exception):
                await self._mark_indeterminate(charge_id, "provider_cancelled")
            raise
        except Exception:
            # Accounting trouble must not replace the provider's established exception boundary.
            with suppress(Exception):
                await self._mark_indeterminate(charge_id, "provider_error")
            raise

        if not isinstance(response, ModelResponse):
            await self._mark_indeterminate(charge_id, "invalid_response")
            raise IndeterminateModelCharge

        actual_provider = response.actual_provider
        actual_model = response.actual_model
        if actual_provider is None or actual_model is None:
            if (
                len(self._pricing_candidates) != 1
                or actual_provider is not None
                or actual_model is not None
            ):
                await self._mark_indeterminate(charge_id, "missing_actual_identity")
                raise IndeterminateModelCharge
            fallback = self._pricing_candidates[0]
            actual_provider = fallback.provider
            actual_model = fallback.model

        try:
            actual_pair = validated_pricing_pair(actual_model, actual_provider)
        except (TypeError, ValueError):
            await self._mark_indeterminate(charge_id, "invalid_actual_identity")
            raise IndeterminateModelCharge from None
        if actual_pair not in self._allowed_pairs:
            await self._mark_indeterminate(charge_id, "unexpected_actual_identity")
            raise IndeterminateModelCharge

        usage = response.usage
        if not isinstance(usage, TokenUsage):
            await self._mark_indeterminate(charge_id, "invalid_usage")
            raise IndeterminateModelCharge
        counts = (
            usage.input_tokens,
            usage.output_tokens,
            usage.cache_read_input_tokens,
            usage.cache_write_input_tokens,
        )
        if any(
            count is not None and (type(count) is not int or not 0 <= count <= _MAX_BIGINT)
            for count in counts
        ) or (usage.cache_read_input_tokens or 0) + (usage.cache_write_input_tokens or 0) > (
            usage.input_tokens
        ):
            await self._mark_indeterminate(charge_id, "invalid_usage")
            raise IndeterminateModelCharge
        try:
            await self._repository.reconcile(
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
        except QuoteExceeded:
            # The repository has already durably made this charge indeterminate.
            raise IndeterminateModelCharge from None
        except ChargeStateConflict:
            # A conflicting durable terminal state cannot safely be rewritten.
            raise IndeterminateModelCharge from None
        except ValueError:
            await self._mark_indeterminate(charge_id, "reconcile_failed")
            raise IndeterminateModelCharge from None
        return response


# Alternate explicit names used by callers discussing calls rather than charges.
BudgetExhausted = ModelBudgetExhausted
DuplicateModelCall = DuplicateModelCharge
IndeterminateModelCall = IndeterminateModelCharge
