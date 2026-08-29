#!/usr/bin/env python3
"""Opt-in multimodal acceptance through Archon's image and provider boundaries."""
# ruff: noqa: E402 -- direct script execution bootstraps the backend import root.

from __future__ import annotations

import argparse
import asyncio
import base64
import io
import json
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

from PIL import Image

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.agents.llm_factory import create_llm_client
from app.config import Settings
from app.runtime.capabilities import get_provider_capabilities
from app.runtime.images import ImageAttachmentStore, ImageLimits
from app.runtime.models import Message, Role
from scripts.acceptance_support import (
    AcceptanceError,
    bounded_close,
    error_result,
    make_report,
    result,
    run_cli_worker,
    utc_now,
    write_report,
)
from scripts.provider_acceptance import _configuration_error, preflight

_MAX_OUTPUT_TOKENS = 64


def tiny_image_data_uri() -> str:
    """Generate a metadata-free 1x1 PNG in memory; no artifact is persisted."""
    buffer = io.BytesIO()
    Image.new("RGB", (1, 1), (255, 0, 0)).save(buffer, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buffer.getvalue()).decode("ascii")


async def run_multimodal(
    settings: Settings,
    *,
    execute_live: bool,
    timeout: float = 20.0,
    provider: Any | None = None,
    clock: Callable[[], str] = utc_now,
) -> dict[str, Any]:
    started = clock()
    before = preflight(settings, execute_live=execute_live, injected=provider is not None)
    if not execute_live:
        checks = [
            result(
                "image_input",
                "skipped",
                error_code="live_opt_in_required",
                error_category="preflight",
            )
        ]
        return make_report(
            kind="multimodal",
            started_at=started,
            finished_at=clock(),
            preflight=before,
            results=checks,
        )
    config_error = _configuration_error(settings)
    if config_error is not None:
        checks = [
            result("image_input", "fail", error_code=config_error, error_category="preflight")
        ]
        return make_report(
            kind="multimodal",
            started_at=started,
            finished_at=clock(),
            preflight=before,
            results=checks,
        )

    checks: list[dict[str, Any]] = []
    try:
        client: Any = provider if provider is not None else create_llm_client(settings)
        capabilities = get_provider_capabilities(client)
    except Exception as exc:
        checks.append(error_result("image_input", exc))
        return make_report(
            kind="multimodal",
            started_at=started,
            finished_at=clock(),
            preflight=before,
            results=checks,
        )
    try:
        if not capabilities.images:
            checks.append(
                result(
                    "image_input",
                    "skipped",
                    error_code="unsupported_capability",
                    error_category="capability",
                )
            )
        else:
            try:
                store = ImageAttachmentStore(
                    ImageLimits(
                        max_bytes=4096, max_width=8, max_height=8, max_pixels=64, max_count=1
                    )
                )
                attachment = store.add_data_uri(
                    tiny_image_data_uri(),
                    owner_id="acceptance",
                    project_id="acceptance",
                    filename="probe.png",
                    persist=False,
                )
                response = await asyncio.wait_for(
                    client.complete(
                        [
                            Message(
                                Role.USER,
                                "Name the dominant color in one lowercase word.",
                                images=(attachment.data_uri,),
                            )
                        ],
                        max_tokens=_MAX_OUTPUT_TOKENS,
                    ),
                    timeout=timeout,
                )
                content = response.content
                normalized = content.strip().lower() if isinstance(content, str) else ""
                if normalized != "red" or len(content or "") > 256:
                    raise AcceptanceError("invalid_image_response")
                checks.append(
                    result(
                        "image_input",
                        "pass",
                        metrics={
                            "images": 1,
                            "width": attachment.width,
                            "height": attachment.height,
                        },
                    )
                )
            except Exception as exc:
                checks.append(error_result("image_input", exc))
    finally:
        cleanup_error = await bounded_close(client, timeout)
        if cleanup_error is not None:
            checks.append(error_result("provider_cleanup", cleanup_error))
    return make_report(
        kind="multimodal", started_at=started, finished_at=clock(), preflight=before, results=checks
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
                kind="multimodal",
                execute_live=args.execute_live,
                operation_timeout=args.timeout,
                operation_count=2,
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
            kind="multimodal",
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
            results=[error_result("image_input", exc)],
        )
        write_report(args.output, report)
        print(json.dumps({"schema": report["schema"], "status": report["status"]}, sort_keys=True))
        return 1
    report = await run_multimodal(settings, execute_live=args.execute_live, timeout=args.timeout)
    write_report(args.output, report, secrets=(settings.llm_api_key,))
    print(json.dumps({"schema": report["schema"], "status": report["status"]}, sort_keys=True))
    return 1 if report["status"] == "fail" else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
