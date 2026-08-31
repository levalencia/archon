#!/usr/bin/env python3
"""Opt-in real embedding and vector ingest/query acceptance; never emits credentials."""
# ruff: noqa: E402 -- direct script execution bootstraps the backend import root.

from __future__ import annotations

import argparse
import asyncio
import json
import math
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any, cast

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import Settings
from app.services.chunker import EmbeddingService, validate_embedding
from app.services.rag_pipeline import RAGPipeline
from app.services.vector_store import MemoryVectorStore, cosine_similarity
from scripts.acceptance_support import (
    AcceptanceError,
    bounded_close,
    error_result,
    make_report,
    normalized_host,
    normalized_identity,
    result,
    run_cli_worker,
    utc_now,
    write_report,
)

_PROBE_TEXT = "Archon acceptance vector marker cobalt seven."


class _RecordingEmbedding:
    def __init__(self, service: Any, dimensions: int) -> None:
        self.service = service
        self.dimensions = dimensions
        self.vectors: list[list[float]] = []

    async def embed(self, text: str) -> list[float]:
        vector = validate_embedding(
            await self.service.embed(text), self.dimensions, source="acceptance pipeline embedding"
        )
        self.vectors.append(vector)
        return vector


class _LocalAnswer:
    async def chat(
        self,
        messages: list[dict[str, str]],
        max_tokens: int = 4096,
        temperature: float = 0.7,
    ) -> str:
        del messages, max_tokens, temperature
        return "local retrieval validation"


def preflight(settings: Settings, *, execute_live: bool, injected: bool = False) -> dict[str, Any]:
    mode = "dry_run" if not execute_live else ("deterministic" if injected else "live")
    return {
        "execute_live": execute_live,
        "execution_mode": mode,
        "provider": normalized_identity(settings.embedding_provider),
        "model": normalized_identity(settings.embedding_model),
        "base_host": normalized_host(settings.embedding_base_url, settings.embedding_provider),
        "credential_present": bool(settings.embedding_api_key or settings.llm_api_key),
        "dimensions": settings.embedding_dimensions,
    }


def _configuration_error(settings: Settings) -> str | None:
    if settings.embedding_provider == "mock":
        return "mock_provider"
    if settings.embedding_provider not in {"openai", "foundry"}:
        return "unsupported_provider"
    if not (settings.embedding_api_key or settings.llm_api_key):
        return "credential_missing"
    if normalized_identity(settings.embedding_model) == "unknown":
        return "invalid_model"
    return None


def _service(settings: Settings) -> EmbeddingService:
    return EmbeddingService(
        provider=settings.embedding_provider,
        model=settings.embedding_model,
        api_key=settings.embedding_api_key or settings.llm_api_key,
        dimensions=settings.embedding_dimensions,
        base_url=settings.embedding_base_url,
        allowed_hosts=settings.embedding_allowed_hosts,
        allow_private_endpoint=settings.embedding_allow_private_endpoint,
        api_version=settings.embedding_api_version,
    )


async def run_acceptance(
    settings: Settings,
    *,
    execute_live: bool,
    timeout: float = 30.0,
    embedding_service: Any | None = None,
    clock: Callable[[], str] = utc_now,
) -> dict[str, Any]:
    started = clock()
    before = preflight(settings, execute_live=execute_live, injected=embedding_service is not None)
    if not execute_live:
        checks = [
            result(
                "embedding",
                "skipped",
                error_code="live_opt_in_required",
                error_category="preflight",
            ),
            result(
                "ingest_query",
                "skipped",
                error_code="live_opt_in_required",
                error_category="preflight",
            ),
        ]
        return make_report(
            kind="embedding",
            started_at=started,
            finished_at=clock(),
            preflight=before,
            results=checks,
        )
    config_error = _configuration_error(settings)
    if config_error is not None:
        checks = [
            result(name, "fail", error_code=config_error, error_category="preflight")
            for name in ("embedding", "ingest_query")
        ]
        return make_report(
            kind="embedding",
            started_at=started,
            finished_at=clock(),
            preflight=before,
            results=checks,
        )

    dimensions = settings.embedding_dimensions
    checks: list[dict[str, Any]] = []
    direct: list[float] | None = None
    try:
        service = embedding_service if embedding_service is not None else _service(settings)
    except Exception as exc:
        checks = [error_result(name, exc) for name in ("embedding", "ingest_query")]
        return make_report(
            kind="embedding",
            started_at=started,
            finished_at=clock(),
            preflight=before,
            results=checks,
        )
    try:
        service.validate_configuration()
        try:
            direct = validate_embedding(
                await asyncio.wait_for(service.embed(_PROBE_TEXT), timeout=timeout),
                dimensions,
                source="acceptance embedding",
            )
            norm = math.sqrt(sum(value * value for value in direct))
            if norm <= 0 or not math.isfinite(norm):
                raise ValueError("zero embedding norm")
            checks.append(
                result(
                    "embedding",
                    "pass",
                    metrics={
                        "dimensions": len(direct),
                        "finite": True,
                        "nonzero": True,
                        "norm_positive": True,
                    },
                )
            )
        except Exception as exc:
            checks.append(error_result("embedding", exc))

        if direct is None:
            checks.append(
                result(
                    "ingest_query",
                    "fail",
                    error_code="embedding_prerequisite_failed",
                    error_category="validation",
                )
            )
        else:
            try:
                store = MemoryVectorStore(
                    dimensions=dimensions, candidate_limit=4, max_chunks_per_document=1
                )
                recording = _RecordingEmbedding(service, dimensions)
                pipeline = RAGPipeline(
                    store,
                    cast(EmbeddingService, recording),
                    _LocalAnswer(),
                    top_k=1,
                    min_score=0.0001,
                )
                ingest = await asyncio.wait_for(
                    pipeline.ingest_document(
                        "acceptance-document",
                        "Acceptance",
                        _PROBE_TEXT,
                        owner_id="acceptance",
                        project_id="acceptance",
                    ),
                    timeout=timeout,
                )
                query = await asyncio.wait_for(
                    pipeline.query(
                        _PROBE_TEXT,
                        document_id="acceptance-document",
                        owner_id="acceptance",
                        project_id="acceptance",
                    ),
                    timeout=timeout,
                )
                stored = next(iter(store._chunks.values())).embedding
                stored_vector = validate_embedding(stored, dimensions, source="stored embedding")
                if len(recording.vectors) != 2:
                    raise AcceptanceError("invalid_embedding_call_count")
                ingested_vector, query_vector = recording.vectors
                query_norm = math.sqrt(sum(value * value for value in query_vector))
                query_similarity = cosine_similarity(query_vector, stored_vector)
                ingested_similarity = cosine_similarity(direct, ingested_vector)
                source_score = query["sources"][0]["score"] if query["sources"] else 0.0
                if ingest["chunks_created"] != 1 or query["chunks_retrieved"] != 1:
                    raise AcceptanceError("invalid_vector_retrieval")
                if (
                    query_norm <= 0
                    or not math.isfinite(query_norm)
                    or not math.isfinite(query_similarity)
                    or query_similarity <= 0
                    or not math.isfinite(ingested_similarity)
                    or ingested_similarity <= 0
                    or not isinstance(source_score, (int, float))
                    or not math.isfinite(float(source_score))
                    or source_score <= 0
                ):
                    raise AcceptanceError("invalid_query_similarity")
                checks.append(
                    result(
                        "ingest_query",
                        "pass",
                        metrics={
                            "chunks_ingested": 1,
                            "chunks_retrieved": 1,
                            "query_nonzero": True,
                            "query_similarity_positive": True,
                            "retrieved_score_positive": True,
                            "dimensions": dimensions,
                        },
                    )
                )
            except Exception as exc:
                checks.append(error_result("ingest_query", exc))
    except Exception as exc:
        checks.extend(error_result(name, exc) for name in ("embedding", "ingest_query"))
    finally:
        cleanup_error = await bounded_close(service, timeout)
        if cleanup_error is not None:
            checks.append(error_result("embedding_cleanup", cleanup_error))
    # Defensive uniqueness if setup failed before the first check.
    unique = {item["name"]: item for item in checks}
    ordered = [unique[name] for name in ("embedding", "ingest_query")]
    if "embedding_cleanup" in unique:
        ordered.append(unique["embedding_cleanup"])
    return make_report(
        kind="embedding", started_at=started, finished_at=clock(), preflight=before, results=ordered
    )


def _args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--execute-live", action="store_true")
    parser.add_argument("--output", required=True)
    parser.add_argument("--timeout", type=float, default=30.0)
    args = parser.parse_args()
    if not 0.1 <= args.timeout <= 60.0:
        parser.error("--timeout must be between 0.1 and 60 seconds")
    return args


async def main() -> int:
    args = _args()
    if not args.worker:
        worker_arguments = ["--output", args.output, "--timeout", str(args.timeout)]
        if args.execute_live:
            worker_arguments.append("--execute-live")
        try:
            code, report = run_cli_worker(
                __file__,
                worker_arguments,
                output=args.output,
                kind="embedding",
                execute_live=args.execute_live,
                operation_timeout=args.timeout,
                operation_count=4,
            )
        except ValueError:
            print(json.dumps({"schema": "archon.provider-acceptance", "status": "fail"}))
            return 2
        print(json.dumps({"schema": report["schema"], "status": report["status"]}, sort_keys=True))
        return code
    try:
        settings = Settings()
    except Exception as exc:
        report = make_report(
            kind="embedding",
            started_at=utc_now(),
            finished_at=utc_now(),
            preflight={
                "execute_live": args.execute_live,
                "execution_mode": "configuration_error",
                "provider": "unknown",
                "model": "unknown",
                "base_host": "invalid",
                "credential_present": False,
                "dimensions": 1,
            },
            results=[error_result(name, exc) for name in ("embedding", "ingest_query")],
        )
        write_report(args.output, report)
        print(json.dumps({"schema": report["schema"], "status": report["status"]}, sort_keys=True))
        return 1
    report = await run_acceptance(settings, execute_live=args.execute_live, timeout=args.timeout)
    secrets = (settings.embedding_api_key, settings.llm_api_key)
    write_report(args.output, report, secrets=secrets)
    print(json.dumps({"schema": report["schema"], "status": report["status"]}, sort_keys=True))
    return 1 if report["status"] == "fail" else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
