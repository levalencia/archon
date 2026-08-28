"""Signed, replay-resistant delegation boundary contracts."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import math
import re
import secrets
import time
from dataclasses import asdict, dataclass, replace
from typing import Any

from sqlalchemy import delete
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.services.db_store import DelegationNonceRow

_DOMAIN = b"archon.delegation-envelope.v1\x00"
_KEY_DOMAIN = b"archon.delegation-key.v1\x00"
_SAFE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,254}$")
_NONCE = re.compile(r"^[A-Za-z0-9_-]{8,255}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_SIGNATURE = re.compile(r"^[A-Za-z0-9_-]{43}$")
_BUDGET_KEYS = frozenset(
    {"input_tokens", "output_tokens", "retries", "timeout_seconds", "cost_nusd"}
)


def derive_delegation_hmac_key(application_secret: str, version: int) -> bytes:
    if not isinstance(application_secret, str) or not application_secret:
        raise ValueError("delegation signing secret is unavailable")
    if type(version) is not int or not 1 <= version <= 255:
        raise ValueError("invalid delegation key version")
    return hmac.new(
        application_secret.encode(), _KEY_DOMAIN + bytes((version,)), hashlib.sha256
    ).digest()


class InvalidDelegationEnvelope(ValueError):  # noqa: N818 - public protocol name
    """The delegation was not authentic, fresh, scoped, or unused."""


@dataclass(frozen=True, slots=True)
class DelegationEnvelope:
    parent_run_id: str
    child_run_id: str
    owner_id: str
    project_id: str
    context_hash: str
    budget: tuple[tuple[str, int | float], ...]
    schema_version: int
    issued_at: int
    nonce: str
    key_version: int
    signature: str = ""

    def __post_init__(self) -> None:
        for value in (
            self.parent_run_id,
            self.child_run_id,
            self.owner_id,
            self.project_id,
        ):
            if not isinstance(value, str) or _SAFE.fullmatch(value) is None:
                raise ValueError("envelope contains an invalid identifier")
        if not isinstance(self.nonce, str) or _NONCE.fullmatch(self.nonce) is None:
            raise ValueError("envelope contains an invalid nonce")
        if _SHA256.fullmatch(self.context_hash) is None:
            raise ValueError("context_hash must be a lowercase SHA-256 digest")
        if type(self.schema_version) is not int or self.schema_version != 1:
            raise ValueError("unsupported envelope schema")
        if (
            type(self.issued_at) is not int
            or self.issued_at < 1
            or type(self.key_version) is not int
            or not 1 <= self.key_version <= 255
        ):
            raise ValueError("invalid envelope version or timestamp")
        if self.signature and _SIGNATURE.fullmatch(self.signature) is None:
            raise ValueError("invalid envelope signature")
        if not isinstance(self.budget, tuple) or not self.budget or len(self.budget) > 5:
            raise ValueError("budget must be an immutable non-empty tuple")
        if tuple(sorted(self.budget)) != self.budget or len(dict(self.budget)) != len(self.budget):
            raise ValueError("budget must have sorted unique keys")
        for key, value in self.budget:
            if key not in _BUDGET_KEYS or isinstance(value, bool):
                raise ValueError("invalid budget")
            if key == "timeout_seconds":
                if not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
                    raise ValueError("invalid budget")
            elif (
                type(value) is not int
                or value < 0
                or (key in {"input_tokens", "output_tokens"} and value < 1)
            ):
                raise ValueError("invalid budget")

    def unsigned_payload(self) -> bytes:
        value = asdict(self)
        value.pop("signature")
        value["budget"] = dict(self.budget)
        return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


class DelegationEnvelopeService:
    """Issue and consume domain-separated HMAC envelopes with durable nonce receipts."""

    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        keys: dict[int, bytes],
        *,
        active_key_version: int,
        max_age_seconds: int = 300,
        max_future_skew_seconds: int = 30,
    ) -> None:
        if (
            not keys
            or active_key_version not in keys
            or any(type(version) is not int or not 1 <= version <= 255 for version in keys)
            or any(not isinstance(key, bytes) or len(key) < 32 for key in keys.values())
            or len(set(keys.values())) != len(keys)
        ):
            raise ValueError("delegation keys must be distinct versioned 32-byte values")
        if not 1 <= max_age_seconds <= 86_400 or not 0 <= max_future_skew_seconds <= 300:
            raise ValueError("invalid delegation freshness window")
        self._sessions = sessions
        self._keys = dict(keys)
        self._active = active_key_version
        self._max_age = max_age_seconds
        self._future_skew = max_future_skew_seconds

    def issue(
        self,
        *,
        parent_run_id: str,
        child_run_id: str,
        owner_id: str,
        project_id: str,
        context_hash: str,
        budget: dict[str, int | float],
        now: int | None = None,
        nonce: str | None = None,
    ) -> DelegationEnvelope:
        envelope = DelegationEnvelope(
            parent_run_id=parent_run_id,
            child_run_id=child_run_id,
            owner_id=owner_id,
            project_id=project_id,
            context_hash=context_hash,
            budget=tuple(sorted(budget.items())),
            schema_version=1,
            issued_at=int(time.time()) if now is None else now,
            nonce=nonce or secrets.token_urlsafe(24),
            key_version=self._active,
        )
        signature = self._signature(envelope, self._keys[self._active])
        return replace(envelope, signature=signature)

    async def verify_and_consume(
        self,
        envelope: DelegationEnvelope,
        *,
        owner_id: str,
        project_id: str,
        parent_run_id: str,
        child_run_id: str,
        context_hash: str,
        now: int | None = None,
    ) -> None:
        key = self._keys.get(envelope.key_version)
        # Perform a same-shaped comparison even for unknown versions.
        expected = self._signature(envelope, key or b"\x00" * 32)
        authentic = key is not None and hmac.compare_digest(expected, envelope.signature)
        current = int(time.time()) if now is None else now
        fresh = current - self._max_age <= envelope.issued_at <= current + self._future_skew
        scoped = (
            envelope.owner_id == owner_id
            and envelope.project_id == project_id
            and envelope.parent_run_id == parent_run_id
            and envelope.child_run_id == child_run_id
            and envelope.context_hash == context_hash
        )
        if not authentic or not fresh or not scoped:
            raise InvalidDelegationEnvelope("delegation envelope rejected")
        digest = hashlib.sha256(envelope.signature.encode("ascii")).hexdigest()
        async with self._sessions() as session:
            try:
                async with session.begin():
                    await session.execute(
                        delete(DelegationNonceRow).where(
                            DelegationNonceRow.issued_at
                            < current - self._max_age - self._future_skew
                        )
                    )
                    session.add(
                        DelegationNonceRow(
                            nonce=envelope.nonce,
                            key_version=envelope.key_version,
                            owner_id=envelope.owner_id,
                            project_id=envelope.project_id,
                            parent_run_id=envelope.parent_run_id,
                            child_run_id=envelope.child_run_id,
                            signature_hash=digest,
                            issued_at=envelope.issued_at,
                            received_at=current,
                        )
                    )
                    await session.flush()
            except IntegrityError as exc:
                await session.rollback()
                raise InvalidDelegationEnvelope("delegation envelope rejected") from exc

    @staticmethod
    def context_digest(value: Any) -> str:
        encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
        return hashlib.sha256(encoded).hexdigest()

    @staticmethod
    def _signature(envelope: DelegationEnvelope, key: bytes) -> str:
        digest = hmac.digest(key, _DOMAIN + envelope.unsigned_payload(), "sha256")
        return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
