#!/usr/bin/env python3
"""Opt-in, bounded acceptance checks through Archon's configured model adapter."""
# ruff: noqa: E402 -- direct script execution bootstraps the backend import root.

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.agents.llm_factory import create_llm_client
from app.config import Settings
from app.runtime.capabilities import get_provider_capabilities
from app.runtime.models import Message, Role, ToolDefinition
from app.runtime.structured_output import ResponseContract
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

_MAX_OUTPUT_TOKENS = 128


def _answer(value: object) -> dict[str, str]:
    if type(value) is not dict or value != {"answer": "ok"}:
        raise AcceptanceError("schema_mismatch")
    return value


def _contract() -> ResponseContract:
    return ResponseContract(
        "provider_acceptance",
        "1",
        {
            "type": "object",
            "properties": {"answer": {"type": "string", "const": "ok"}},
            "required": ["answer"],
            "additionalProperties": False,
        },
        _answer,
    )


def preflight(settings: Settings, *, execute_live: bool, injected: bool = False) -> dict[str, Any]:
    provider = normalized_identity(settings.llm_provider)
    mode = "dry_run" if not execute_live else ("deterministic" if injected else "live")
    return {
        "execute_live": execute_live,
        "execution_mode": mode,
        "provider": provider,
        "model": normalized_identity(settings.llm_model),
        "base_host": normalized_host(settings.llm_base_url, provider),
        "credential_present": bool(settings.llm_api_key),
        "fallback_configured": bool(settings.llm_fallback_providers.strip()),
    }


def _configuration_error(settings: Settings) -> str | None:
    provider = settings.llm_provider.strip().lower()
    if provider == "mock":
        return "mock_provider"
    if provider not in {"openai", "anthropic", "foundry", "ollama"}:
        return "unsupported_provider"
    if settings.llm_fallback_providers.strip():
        return "fallback_not_allowed"
    if provider != "ollama" and not settings.llm_api_key:
        return "credential_missing"
    if provider == "foundry" and not settings.llm_base_url:
        return "endpoint_missing"
    if normalized_identity(settings.llm_model) == "unknown":
        return "invalid_model"
    return None


async def _bounded(call: Any, timeout: float) -> Any:
    return await asyncio.wait_for(call, timeout=timeout)


async def run_acceptance(
    settings: Settings,
    *,
    execute_live: bool,
    timeout: float = 20.0,
    provider: Any | None = None,
    clock: Callable[[], str] = utc_now,
) -> dict[str, Any]:
    """Run checks; injection exists only for deterministic transport/provider tests."""
    started = clock()
    before = preflight(settings, execute_live=execute_live, injected=provider is not None)
    config_error = _configuration_error(settings)
    if not execute_live:
        checks = [
            result(
                "structured_output",
                "skipped",
                error_code="live_opt_in_required",
                error_category="preflight",
            ),
            result(
                "native_tool_call",
                "skipped",
                error_code="live_opt_in_required",
                error_category="preflight",
            ),
            result(
                "cache_metrics",
                "skipped",
                error_code="live_opt_in_required",
                error_category="preflight",
            ),
        ]
        return make_report(
            kind="model", started_at=started, finished_at=clock(), preflight=before, results=checks
        )
    if config_error is not None:
        checks = [
            result(name, "fail", error_code=config_error, error_category="preflight")
            for name in ("structured_output", "native_tool_call", "cache_metrics")
        ]
        return make_report(
            kind="model", started_at=started, finished_at=clock(), preflight=before, results=checks
        )

    checks: list[dict[str, Any]] = []
    responses: list[Any] = []
    try:
        client: Any = provider if provider is not None else create_llm_client(settings)
        capabilities = get_provider_capabilities(client)
    except Exception as exc:
        checks = [
            error_result(name, exc)
            for name in ("structured_output", "native_tool_call", "cache_metrics")
        ]
        return make_report(
            kind="model",
            started_at=started,
            finished_at=clock(),
            preflight=before,
            results=checks,
        )
    try:
        if not capabilities.json_schema:
            checks.append(
                result(
                    "structured_output",
                    "skipped",
                    error_code="unsupported_capability",
                    error_category="capability",
                )
            )
        else:
            try:
                contract = _contract()
                response = await _bounded(
                    client.complete(
                        [Message(Role.USER, 'Return exactly JSON {"answer":"ok"}.')],
                        max_tokens=_MAX_OUTPUT_TOKENS,
                        response_contract=contract,
                    ),
                    timeout,
                )
                parsed = contract.parse_and_validate(response.content or "")
                responses.append(response)
                checks.append(
                    result(
                        "structured_output",
                        "pass",
                        metrics={"schema_valid": parsed == {"answer": "ok"}},
                    )
                )
            except Exception as exc:
                checks.append(error_result("structured_output", exc))

        if not capabilities.native_tools:
            checks.append(
                result(
                    "native_tool_call",
                    "skipped",
                    error_code="unsupported_capability",
                    error_category="capability",
                )
            )
        else:
            try:
                tool = ToolDefinition(
                    "acceptance_probe",
                    "Return the supplied bounded value.",
                    {
                        "type": "object",
                        "properties": {"value": {"const": "ok"}},
                        "required": ["value"],
                        "additionalProperties": False,
                    },
                )
                response = await _bounded(
                    client.complete(
                        [
                            Message(
                                Role.USER,
                                "Call acceptance_probe once with value ok; do not answer in text.",
                            )
                        ],
                        [tool],
                        max_tokens=_MAX_OUTPUT_TOKENS,
                    ),
                    timeout,
                )
                calls = response.tool_calls
                if (
                    len(calls) != 1
                    or calls[0].name != "acceptance_probe"
                    or dict(calls[0].arguments) != {"value": "ok"}
                ):
                    raise AcceptanceError("invalid_tool_response")
                responses.append(response)
                checks.append(result("native_tool_call", "pass", metrics={"tool_calls": 1}))
            except Exception as exc:
                checks.append(error_result("native_tool_call", exc))

        if not capabilities.cache_usage:
            checks.append(
                result(
                    "cache_metrics",
                    "skipped",
                    error_code="unsupported_capability",
                    error_category="capability",
                )
            )
        else:
            reads = [
                response.usage.cache_read_input_tokens
                for response in responses
                if response.usage.cache_read_input_tokens is not None
            ]
            writes = [
                response.usage.cache_write_input_tokens
                for response in responses
                if response.usage.cache_write_input_tokens is not None
            ]
            if not reads and not writes:
                checks.append(
                    result(
                        "cache_metrics",
                        "skipped",
                        error_code="not_reported",
                        error_category="provider",
                    )
                )
            else:
                checks.append(
                    result(
                        "cache_metrics",
                        "pass",
                        metrics={"read_tokens": sum(reads), "write_tokens": sum(writes)},
                    )
                )
    finally:
        cleanup_error = await bounded_close(client, timeout)
        if cleanup_error is not None:
            checks.append(error_result("provider_cleanup", cleanup_error))
    return make_report(
        kind="model", started_at=started, finished_at=clock(), preflight=before, results=checks
    )


def _args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--execute-live", action="store_true")
    parser.add_argument("--output", required=True)
    parser.add_argument("--timeout", type=float, default=20.0)
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
                kind="model",
                execute_live=args.execute_live,
                operation_timeout=args.timeout,
                operation_count=3,
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
            kind="model",
            started_at=utc_now(),
            finished_at=utc_now(),
            preflight={
                "execute_live": args.execute_live,
                "execution_mode": "configuration_error",
                "provider": "unknown",
                "model": "unknown",
                "base_host": "invalid",
                "credential_present": False,
                "fallback_configured": False,
            },
            results=[
                error_result(name, exc)
                for name in ("structured_output", "native_tool_call", "cache_metrics")
            ],
        )
        write_report(args.output, report)
        print(json.dumps({"schema": report["schema"], "status": report["status"]}, sort_keys=True))
        return 1
    report = await run_acceptance(settings, execute_live=args.execute_live, timeout=args.timeout)
    write_report(args.output, report, secrets=(settings.llm_api_key,))
    print(json.dumps({"schema": report["schema"], "status": report["status"]}, sort_keys=True))
    return 1 if report["status"] == "fail" else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
