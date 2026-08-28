"""Grounded document retrieval, synthesis, and deterministic claim verification."""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
import uuid
from collections.abc import Mapping
from dataclasses import asdict, dataclass, field
from time import perf_counter
from typing import Any

from app.delegation import (
    MAX_QUOTE_CHARS,
    MAX_TEXT_CHARS,
    ChildVerificationRequest,
    ChildVerificationStatus,
    ClaimInput,
    ClaimVerdictStatus,
    EvidenceSlice,
    EvidenceVerifierSpecialist,
    VerificationBudget,
)
from app.research.models import Claim
from app.runtime.models import Message, Role, TokenUsage
from app.runtime.ports import ModelProvider
from app.security.compliance import MandatoryComplianceService
from app.services.chunker import DocumentChunk, EmbeddingService
from app.services.run_ledger import RunRepository
from app.services.vector_store import VectorStoreProtocol

_NO_EVIDENCE_ANSWER = "I could not find relevant information to answer your question."
_MAX_QUOTE = 1_200
_MAX_MODEL_OUTPUT = 65_536
_MAX_CLAIMS = 20
_MAX_CLAIM_LENGTH = MAX_TEXT_CHARS
_MAX_CITATIONS_PER_CLAIM = 8
_EVIDENCE_ID = re.compile(r"^E[1-9][0-9]*$")
_LINE_CITATIONS = re.compile(r"\[(E[1-9][0-9]*)\]")
_WORD_OR_NUMBER = re.compile(r"[a-z]+|\d+(?:[.,]\d+)*%?")
_NUMBER = re.compile(r"(?<![a-z0-9])\d+(?:[.,]\d+)*%?(?![a-z0-9])")
_NEGATIONS = frozenset({"not", "no", "never", "without"})
_STOP_WORDS = frozenset(
    {
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "by",
        "do",
        "does",
        "for",
        "from",
        "has",
        "have",
        "in",
        "is",
        "it",
        "of",
        "on",
        "or",
        "that",
        "the",
        "this",
        "to",
        "was",
        "were",
        "will",
        "with",
    }
)
_MIN_SUBSTANTIVE_OVERLAP = 0.9


class GroundedProviderError(RuntimeError):
    """The grounded workflow failed after the durable run was safely finalized."""


@dataclass(frozen=True, slots=True)
class DocumentEvidence:
    id: str
    document_id: str
    chunk_id: str
    content_hash: str
    title: str
    score: float
    quote: str
    verification_text: str = field(repr=False, compare=False)

    def public(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "document_id": self.document_id,
            "chunk_id": self.chunk_id,
            "content_hash": self.content_hash,
            "title": self.title,
            "score": self.score,
            "quote": self.quote,
        }


@dataclass(frozen=True, slots=True)
class GroundedResult:
    run_id: str
    answer: str
    sources: tuple[dict[str, Any], ...]
    chunks_retrieved: int
    confidence: float
    grounded: bool
    claims: tuple[dict[str, Any], ...]
    citations: tuple[dict[str, Any], ...]
    unsupported: tuple[str, ...]
    metrics: Mapping[str, Any]
    child_run_id: str | None = None
    verification_status: str | None = None
    verification_tokens: int = 0
    verification_latency_ms: float | None = None
    verification_rejected_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "answer": self.answer,
            "sources": list(self.sources),
            "chunks_retrieved": self.chunks_retrieved,
            "confidence": self.confidence,
            "grounded": self.grounded,
            "claims": list(self.claims),
            "citations": list(self.citations),
            "unsupported": list(self.unsupported),
            "metrics": dict(self.metrics),
            "child_run_id": self.child_run_id,
            "verification_status": self.verification_status,
            "verification_tokens": self.verification_tokens,
            "verification_latency_ms": self.verification_latency_ms,
            "verification_rejected_count": self.verification_rejected_count,
        }


@dataclass(frozen=True, slots=True)
class _RunIdentity:
    run_id: str
    user_id: str
    project_id: str
    conversation_id: str
    correlation_id: str
    provider: str
    model: str


class DocumentEvidenceRetriever:
    """Typed owner/project-scoped adapter over embedding and vector services."""

    def __init__(
        self,
        vector_store: VectorStoreProtocol,
        embeddings: EmbeddingService,
        *,
        top_k: int,
    ) -> None:
        self._vectors = vector_store
        self._embeddings = embeddings
        self._top_k = top_k

    async def retrieve(
        self,
        question: str,
        *,
        owner_id: str,
        project_id: str,
        document_id: str | None,
        document_ids: set[str],
    ) -> tuple[DocumentEvidence, ...]:
        query_embedding = await self._embeddings.embed(question)
        rows = await self._vectors.search(
            query_embedding,
            owner_id=owner_id,
            project_id=project_id,
            top_k=self._top_k,
            min_score=-1.0,
            document_id=document_id,
            document_ids=document_ids,
        )
        unique: list[tuple[DocumentChunk, float]] = []
        seen: set[tuple[str, str]] = set()
        for row in rows:
            chunk = row.get("chunk")
            if not isinstance(chunk, DocumentChunk):
                continue
            current_hash = chunk.content_hash
            key = (chunk.document_id, current_hash)
            if key in seen:
                continue
            seen.add(key)
            score = row.get("score", 0.0)
            if isinstance(score, bool) or not isinstance(score, (int, float)):
                score = 0.0
            unique.append((chunk, float(score)))
        return tuple(
            DocumentEvidence(
                id=f"E{index}",
                document_id=chunk.document_id,
                chunk_id=chunk.id,
                content_hash=chunk.content_hash,
                title=str(chunk.metadata.get("title", "Unknown"))[:500],
                score=round(score, 4),
                quote=chunk.content[:_MAX_QUOTE],
                verification_text=chunk.content,
            )
            for index, (chunk, score) in enumerate(unique, 1)
        )


class GroundedDocumentWorkflow:
    """One-provider-call grounded RAG workflow backed by the durable run ledger."""

    def __init__(
        self,
        *,
        vector_store: VectorStoreProtocol,
        embedding_service: EmbeddingService,
        model_provider: ModelProvider,
        runs: RunRepository,
        provider: str,
        model: str,
        top_k: int = 5,
        verifier: EvidenceVerifierSpecialist | None = None,
        verifier_budget: VerificationBudget | None = None,
        verifier_model: str = "verifier-model",
        compliance: MandatoryComplianceService | None = None,
    ) -> None:
        self._retriever = DocumentEvidenceRetriever(vector_store, embedding_service, top_k=top_k)
        self._provider = model_provider
        self._runs = runs
        self._provider_name = provider
        self._model_name = model
        if (verifier is None) != (verifier_budget is None):
            raise ValueError("verifier and verifier_budget must be configured together")
        self._verifier = verifier
        self._verifier_budget = verifier_budget
        self._verifier_model = verifier_model
        self._compliance = compliance

    async def run(
        self,
        question: str,
        *,
        owner_id: str,
        project_id: str,
        correlation_id: str,
        document_id: str | None,
        document_ids: set[str],
    ) -> GroundedResult:
        started = perf_counter()
        identity = _RunIdentity(
            run_id=str(uuid.uuid4()),
            user_id=owner_id,
            project_id=project_id,
            conversation_id=f"document-query:{project_id}"[:255],
            correlation_id=correlation_id,
            provider=self._provider_name,
            model=self._model_name,
        )
        await self._runs.ensure_run(**asdict(identity))
        usage = TokenUsage()
        try:
            evidence = await self._retriever.retrieve(
                question,
                owner_id=owner_id,
                project_id=project_id,
                document_id=document_id,
                document_ids=document_ids,
            )
            await self._append(
                identity,
                "evidence_retrieved",
                {
                    "evidence_ids": [item.id for item in evidence],
                    "document_ids": [item.document_id for item in evidence],
                    "chunk_ids": [item.chunk_id for item in evidence],
                    "content_hashes": [item.content_hash for item in evidence],
                    "scores": [item.score for item in evidence],
                    "evidence_count": len(evidence),
                },
            )
            if not evidence:
                return await self._finish(
                    identity,
                    started=started,
                    evidence=(),
                    claims=(),
                    citations=(),
                    unsupported=(),
                    usage=usage,
                    provider_calls=0,
                )

            response = await self._provider.complete(_prompt(question, evidence), max_tokens=2048)
            usage = response.usage
            parsed = _parse_claims(response.content or "")
            claims, citations, unsupported = await _verify_document_claims(parsed, evidence)
            child_id: str | None = None
            child_status: str | None = None
            child_tokens = 0
            child_latency_ms: float | None = None
            child_rejected_count = 0
            if claims and self._verifier is not None and self._verifier_budget is not None:
                (
                    claims,
                    citations,
                    unsupported,
                    child_id,
                    child_status,
                    child_tokens,
                    child_latency_ms,
                    child_rejected_count,
                ) = await self._verify_with_child(identity, claims, evidence, unsupported)
            return await self._finish(
                identity,
                started=started,
                evidence=evidence,
                claims=claims,
                citations=citations,
                unsupported=unsupported,
                usage=usage,
                provider_calls=1,
                child_run_id=child_id,
                verification_status=child_status,
                verification_tokens=child_tokens,
                verification_latency_ms=child_latency_ms,
                verification_rejected_count=child_rejected_count,
            )
        except asyncio.CancelledError:
            await asyncio.shield(self._stop(identity, usage=usage, error=False, reason="cancelled"))
            raise
        except Exception as exc:
            await self._stop(identity, usage=usage, error=True, reason="provider_error")
            raise GroundedProviderError("Grounded answer unavailable") from exc

    async def _finish(
        self,
        identity: _RunIdentity,
        *,
        started: float,
        evidence: tuple[DocumentEvidence, ...],
        claims: tuple[Claim, ...],
        citations: tuple[DocumentEvidence, ...],
        unsupported: tuple[str, ...],
        usage: TokenUsage,
        provider_calls: int,
        child_run_id: str | None = None,
        verification_status: str | None = None,
        verification_tokens: int = 0,
        verification_latency_ms: float | None = None,
        verification_rejected_count: int = 0,
    ) -> GroundedResult:
        claim_hashes = [_hash(item.text) for item in claims]
        unsupported_hashes = [_hash(item) for item in unsupported]
        await self._append(
            identity,
            "claim_verified",
            {
                "claim_hashes": claim_hashes,
                "unsupported_hashes": unsupported_hashes,
                "cited_evidence_ids": [item.id for item in citations],
                "supported_count": len(claims),
                "unsupported_count": len(unsupported),
            },
        )
        answer = "\n".join(
            f"{claim.text} " + " ".join(f"[{item}]" for item in claim.evidence_ids)
            for claim in claims
        )
        if not answer:
            answer = _NO_EVIDENCE_ANSWER
        if self._compliance is not None:
            answer = self._compliance.enforce_output(answer)
        grounded = bool(claims)
        await self._append(
            identity,
            "grounded_answer",
            {
                "answer_hash": _hash(answer),
                "citation_ids": [item.id for item in citations],
                "supported_count": len(claims),
                "unsupported_count": len(unsupported),
            },
        )
        await self._stop(identity, usage=usage, error=False, reason="completed")
        latency_ms = round((perf_counter() - started) * 1000, 3)
        scores = [item.score for item in evidence]
        sources = tuple(
            {
                "chunk_id": item.chunk_id,
                "document_id": item.document_id,
                "title": item.title,
                "score": item.score,
                "excerpt": item.quote[:200],
            }
            for item in evidence
        )
        return GroundedResult(
            run_id=identity.run_id,
            answer=answer,
            sources=sources,
            chunks_retrieved=len(evidence),
            confidence=round(sum(scores) / len(scores), 4) if scores else 0.0,
            grounded=grounded,
            claims=tuple(
                {"text": item.text, "evidence_ids": list(item.evidence_ids)} for item in claims
            ),
            citations=tuple(item.public() for item in citations),
            unsupported=unsupported,
            metrics={
                "provider": identity.provider,
                "model": identity.model,
                "provider_calls": provider_calls,
                "input_tokens": usage.input_tokens,
                "output_tokens": usage.output_tokens,
                "total_tokens": usage.total_tokens,
                "latency_ms": latency_ms,
                "evidence_count": len(evidence),
                "supported_count": len(claims),
                "unsupported_count": len(unsupported),
            },
            child_run_id=child_run_id,
            verification_status=verification_status,
            verification_tokens=verification_tokens,
            verification_latency_ms=verification_latency_ms,
            verification_rejected_count=verification_rejected_count,
        )

    async def _verify_with_child(
        self,
        identity: _RunIdentity,
        claims: tuple[Claim, ...],
        evidence: tuple[DocumentEvidence, ...],
        unsupported: tuple[str, ...],
    ) -> tuple[
        tuple[Claim, ...],
        tuple[DocumentEvidence, ...],
        tuple[str, ...],
        str,
        str,
        int,
        float | None,
        int,
    ]:
        """Delegate only deterministic claims and fail closed on every child failure."""
        verifier = self._verifier
        budget = self._verifier_budget
        if verifier is None or budget is None:
            raise RuntimeError("verifier is not configured")
        child_id = str(uuid.uuid4())
        cited_ids = tuple(
            dict.fromkeys(evidence_id for claim in claims for evidence_id in claim.evidence_ids)
        )
        by_evidence_id = {item.id: item for item in evidence}
        request = ChildVerificationRequest(
            child_id=child_id,
            parent_run_id=identity.run_id,
            user_id=identity.user_id,
            project_id=identity.project_id,
            policy_id="grounded-evidence-v1",
            model=self._verifier_model,
            claims=tuple(
                ClaimInput(
                    claim_id=f"C{index}",
                    claim_hash=_hash(claim.text),
                    text=claim.text,
                    evidence_ids=claim.evidence_ids,
                )
                for index, claim in enumerate(claims, 1)
            ),
            evidence=tuple(
                EvidenceSlice(
                    evidence_id=item.id,
                    document_id=item.document_id,
                    chunk_id=item.chunk_id,
                    content_hash=_hash(item.verification_text),
                    quote=item.quote[:MAX_QUOTE_CHARS],
                )
                for evidence_id in cited_ids
                if (item := by_evidence_id.get(evidence_id)) is not None
            ),
            budget=budget,
        )
        status = ChildVerificationStatus.FAILED.value
        tokens = 0
        latency_ms: float | None = None
        retained: tuple[Claim, ...] = ()
        try:
            result = await verifier.verify(request)
            status = result.status.value
            tokens = result.usage.total_tokens
            latency_ms = result.latency_ms
            if result.status is ChildVerificationStatus.COMPLETED:
                supported_ids = {
                    verdict.claim_id
                    for verdict in result.verdicts
                    if verdict.status is ClaimVerdictStatus.SUPPORTED
                }
                retained = tuple(
                    claim for index, claim in enumerate(claims, 1) if f"C{index}" in supported_ids
                )
        except Exception:
            # The grounded answer remains available, but no unverified claim may pass.
            retained = ()

        retained_ids = {evidence_id for claim in retained for evidence_id in claim.evidence_ids}
        retained_citations = tuple(item for item in evidence if item.id in retained_ids)
        retained_object_ids = {id(claim) for claim in retained}
        child_rejected = tuple(
            claim.text for claim in claims if id(claim) not in retained_object_ids
        )
        await self._append(
            identity,
            "delegation_completed",
            {
                "child_id": child_id,
                "status": status,
                "supported_count": len(retained),
                "rejected_count": len(child_rejected),
            },
        )
        return (
            retained,
            retained_citations,
            (*unsupported, *child_rejected),
            child_id,
            status,
            tokens,
            latency_ms,
            len(child_rejected),
        )

    async def _append(self, identity: _RunIdentity, kind: str, payload: Mapping[str, Any]) -> None:
        await self._runs.append(**asdict(identity), kind=kind, iteration=1, payload=payload)

    async def _stop(
        self, identity: _RunIdentity, *, usage: TokenUsage, error: bool, reason: str
    ) -> None:
        await self._runs.append(
            **asdict(identity),
            kind="run_stopped",
            iteration=1,
            payload={"reason": reason, "error": error},
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            total_tokens=usage.total_tokens,
        )


def _prompt(question: str, evidence: tuple[DocumentEvidence, ...]) -> tuple[Message, ...]:
    context = "\n\n".join(
        f"{item.id} document={item.document_id} chunk={item.chunk_id} "
        f"hash={item.content_hash} title={json.dumps(item.title)}\n{item.quote}"
        for item in evidence
    )
    system = (
        "Use only the evidence below. Return JSON only as "
        '{"claims":[{"text":"one factual claim","evidence_ids":["E1"]}]}. '
        "Split the answer into atomic claim lines. Every claim must explicitly cite one or more "
        "listed E IDs. Do not cite unknown IDs and do not add unsupported claims.\n\n"
        f"EVIDENCE:\n{context}"
    )
    return (Message(Role.SYSTEM, system), Message(Role.USER, question))


def _parse_claims(raw: str) -> tuple[Claim, ...]:
    bounded = raw[:_MAX_MODEL_OUTPUT].strip()
    if not bounded:
        return ()
    decoded: Any = None
    decoder = json.JSONDecoder()
    starts = [index for index, char in enumerate(bounded) if char in "[{"]
    for start in starts[:100]:
        try:
            decoded, _ = decoder.raw_decode(bounded[start:])
            break
        except json.JSONDecodeError:
            continue
    items: Any
    if isinstance(decoded, dict):
        items = decoded.get("claims", [])
    elif isinstance(decoded, list):
        items = decoded
    else:
        items = []
    claims: list[Claim] = []
    if isinstance(items, list):
        for item in items[:_MAX_CLAIMS]:
            if not isinstance(item, dict):
                continue
            text = item.get("text")
            ids = item.get("evidence_ids", item.get("citations", []))
            if not isinstance(text, str) or not text.strip() or not isinstance(ids, list):
                continue
            clean_ids = tuple(
                dict.fromkeys(
                    value
                    for value in ids[:_MAX_CITATIONS_PER_CLAIM]
                    if isinstance(value, str) and _EVIDENCE_ID.fullmatch(value)
                )
            )
            claims.append(Claim(text.strip()[:_MAX_CLAIM_LENGTH], clean_ids))
    if claims or decoded is not None:
        return tuple(claims)
    # Conservative compatibility for providers that emit one cited claim per line.
    for line in bounded.splitlines()[:_MAX_CLAIMS]:
        ids = tuple(dict.fromkeys(_LINE_CITATIONS.findall(line)))[:_MAX_CITATIONS_PER_CLAIM]
        text = _LINE_CITATIONS.sub("", line).strip(" -\t")
        if text and ids:
            claims.append(Claim(text[:_MAX_CLAIM_LENGTH], ids))
    return tuple(claims)


async def _verify_document_claims(
    claims: tuple[Claim, ...], evidence: tuple[DocumentEvidence, ...]
) -> tuple[tuple[Claim, ...], tuple[DocumentEvidence, ...], tuple[str, ...]]:
    # Recheck the immutable snapshot immediately before applying deliberately
    # conservative deterministic support checks. This is not semantic NLI.
    current = tuple(
        item
        for item in evidence
        if item.content_hash == hashlib.sha256(item.verification_text.encode()).hexdigest()[:16]
    )
    by_id = {item.id: item for item in current}
    supported: list[Claim] = []
    unsupported: list[str] = []
    for claim in claims:
        if _supports_claim(claim, current):
            supported.append(claim)
        else:
            unsupported.append(claim.text)
    cited = tuple(
        by_id[evidence_id]
        for evidence_id in dict.fromkeys(
            evidence_id for claim in supported for evidence_id in claim.evidence_ids
        )
    )
    return tuple(supported), cited, tuple(unsupported)


def _normalize_support_text(value: str) -> str:
    normalized = value.lower().replace("’", "'")
    normalized = re.sub(r"\bwon't\b", "will not", normalized)
    normalized = re.sub(r"\bcan't\b", "can not", normalized)
    normalized = re.sub(r"\bcannot\b", "can not", normalized)
    return re.sub(r"n't\b", " not", normalized)


def _substantive_tokens(value: str) -> set[str]:
    return {
        token
        for token in _WORD_OR_NUMBER.findall(_normalize_support_text(value))
        if token not in _STOP_WORDS and token not in _NEGATIONS
    }


def _numeric_literals(value: str) -> set[str]:
    return set(_NUMBER.findall(_normalize_support_text(value)))


def _negated(value: str) -> bool:
    return bool(_NEGATIONS & set(_WORD_OR_NUMBER.findall(_normalize_support_text(value))))


def _supports_claim(claim: Claim, evidence: tuple[DocumentEvidence, ...]) -> bool:
    """Accept only known citations with conservative lexical, numeric, and polarity support."""
    by_id = {item.id: item for item in evidence}
    if not claim.evidence_ids or any(item not in by_id for item in claim.evidence_ids):
        return False
    sources = [by_id[item] for item in claim.evidence_ids]
    claim_tokens = _substantive_tokens(claim.text)
    if not claim_tokens:
        return False
    evidence_tokens: set[str] = set()
    relevant_polarities: set[bool] = set()
    for source in sources:
        source_tokens = _substantive_tokens(source.verification_text)
        evidence_tokens.update(source_tokens)
        # Ignore unrelated cited prose when determining polarity, but reject mixed
        # polarity among excerpts that overlap materially with the claim.
        if len(claim_tokens & source_tokens) / len(claim_tokens) >= 0.5:
            relevant_polarities.add(_negated(source.verification_text))
    overlap = len(claim_tokens & evidence_tokens) / len(claim_tokens)
    if overlap < _MIN_SUBSTANTIVE_OVERLAP:
        return False
    evidence_numbers = set().union(
        *(_numeric_literals(source.verification_text) for source in sources)
    )
    if not _numeric_literals(claim.text).issubset(evidence_numbers):
        return False
    return relevant_polarities == {_negated(claim.text)}


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()
