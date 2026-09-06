#!/usr/bin/env python3
"""Run the versioned Single-vs-Team benchmark against an authorized Archon endpoint.

Raw responses are written outside the repository. Credentials are generated in memory and
never persisted. The harness checkpoints after every provider-backed run and can resume from
an existing output file with a fresh isolated benchmark identity.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import secrets
import string
import sys
import time
import urllib.error
import urllib.request
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATASET = REPO_ROOT / "benchmarks/hybrid-orchestration/v1/cases.json"
DEFAULT_OUTPUT = Path("/tmp/archon-hybrid-benchmark-v1-results.json")
SCHEMA = "archon.hybrid-orchestration-live-results"
VERSION = 1
MODES = ("single", "team")


def external_output(value: str) -> Path:
    path = Path(value).expanduser().resolve()
    if path == REPO_ROOT or REPO_ROOT in path.parents:
        raise argparse.ArgumentTypeError("raw benchmark output must stay outside the repository")
    return path


def bounded_decimal(value: str) -> Decimal:
    try:
        parsed = Decimal(value)
    except Exception as exc:
        raise argparse.ArgumentTypeError("expected a decimal value") from exc
    if parsed <= 0 or parsed > Decimal("500"):
        raise argparse.ArgumentTypeError("value must be greater than 0 and at most 500")
    return parsed


def bounded_int(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("expected an integer") from exc
    if not 1 <= parsed <= 100:
        raise argparse.ArgumentTypeError("value must be between 1 and 100")
    return parsed


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


def dataset_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_dataset(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    cases = payload.get("cases")
    if payload.get("schema") != "archon.hybrid-orchestration-benchmark-cases":
        raise ValueError("unsupported benchmark dataset schema")
    if payload.get("version") != 1 or not isinstance(cases, list) or len(cases) != 100:
        raise ValueError("benchmark dataset must contain exactly 100 version-one cases")
    ids = [item.get("id") for item in cases]
    if len(set(ids)) != 100 or any(not isinstance(item, str) for item in ids):
        raise ValueError("benchmark case IDs must be unique strings")
    if sum(bool(item.get("calibration")) for item in cases) != 20:
        raise ValueError("benchmark dataset must contain exactly 20 calibration cases")
    return payload


def request_json(
    base_url: str,
    path: str,
    *,
    method: str = "GET",
    payload: dict[str, Any] | None = None,
    token: str | None = None,
    timeout: float = 600.0,
) -> tuple[int, dict[str, Any]]:
    body = None if payload is None else json.dumps(payload).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(
        base_url.rstrip("/") + path,
        data=body,
        headers=headers,
        method=method,
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read()
            return response.status, json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"{path} failed with HTTP {exc.code}: {raw[:500]}") from exc


def register_identity(base_url: str) -> tuple[str, str]:
    suffix = secrets.token_hex(6)
    username = f"hybrid-benchmark-{suffix}"
    password_characters = [
        secrets.choice(string.ascii_lowercase),
        secrets.choice(string.ascii_uppercase),
        secrets.choice(string.digits),
        secrets.choice("!@#$%^&*"),
        *[secrets.choice(string.ascii_letters + string.digits) for _ in range(32)],
    ]
    secrets.SystemRandom().shuffle(password_characters)
    password = "".join(password_characters)
    status, body = request_json(
        base_url,
        "/api/auth/register",
        method="POST",
        payload={
            "username": username,
            "password": password,
            "email": f"{username}@local.test",
        },
        timeout=60,
    )
    if status != 201 or not body.get("access_token"):
        raise RuntimeError("benchmark identity registration failed")
    identity_hash = hashlib.sha256(username.encode()).hexdigest()
    return str(body["access_token"]), identity_hash


def atomic_write(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{secrets.token_hex(4)}.tmp")
    temporary.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def result_cost(base_url: str, token: str, body: dict[str, Any]) -> tuple[Decimal, dict[str, Any]]:
    run_id = str(body.get("run_id") or "")
    if not run_id:
        raise RuntimeError("chat response omitted run_id")
    _, parent = request_json(base_url, f"/api/runs/{run_id}", token=token, timeout=60)
    parent_budget = parent.get("monetary_budget") or {}
    parent_cost = Decimal(str(parent_budget.get("spent_usd") or "0"))
    child_cost = Decimal("0")
    children: list[dict[str, Any]] = []
    for child in body.get("agents_used") or []:
        child_id = str(child.get("child_run_id") or "")
        if not child_id:
            continue
        _, detail = request_json(base_url, f"/api/runs/{child_id}", token=token, timeout=60)
        budget = detail.get("monetary_budget") or {}
        spent = Decimal(str(budget.get("spent_usd") or "0"))
        child_cost += spent
        children.append(
            {
                "child_run_id": child_id,
                "profile_id": child.get("profile_id"),
                "kind": child.get("kind"),
                "status": child.get("status"),
                "reason_code": child.get("reason_code"),
                "tokens_used": child.get("tokens_used"),
                "iterations": child.get("iterations"),
                "cost_usd": str(spent),
                "stop_reason": detail.get("stop_reason"),
            }
        )
    return parent_cost + child_cost, {
        "parent_cost_usd": str(parent_cost),
        "children": children,
        "project_spent_usd": parent_budget.get("project_spent_usd"),
    }


def tool_calls(base_url: str, token: str, run_ids: list[str]) -> list[dict[str, str]]:
    calls: list[dict[str, str]] = []
    for run_id in run_ids:
        _, body = request_json(
            base_url,
            f"/api/runs/{run_id}/events?limit=200",
            token=token,
            timeout=60,
        )
        for event in body.get("items") or []:
            if event.get("kind") != "tool_call_requested":
                continue
            payload = event.get("payload") or {}
            calls.append({"run_id": run_id, "name": str(payload.get("name") or "unknown")})
    return calls


def load_or_create_output(
    path: Path,
    *,
    digest: str,
    dataset_path: Path,
    seed: int,
    cap: Decimal,
) -> dict[str, Any]:
    if path.exists():
        payload = json.loads(path.read_text(encoding="utf-8"))
        if payload.get("schema") != SCHEMA or payload.get("dataset_sha256") != digest:
            raise ValueError("existing output does not match this benchmark dataset")
        return payload
    return {
        "schema": SCHEMA,
        "version": VERSION,
        "created_at": utc_now(),
        "updated_at": utc_now(),
        "dataset": str(dataset_path),
        "dataset_sha256": digest,
        "seed": seed,
        "cost_cap_usd": str(cap),
        "raw_responses": True,
        "credentials_persisted": False,
        "sessions": [],
        "results": [],
        "stopped": None,
    }


def selected_cases(dataset: dict[str, Any], phase: str) -> list[dict[str, Any]]:
    cases = list(dataset["cases"])
    if phase == "calibration":
        return [item for item in cases if item["calibration"]]
    if phase == "remainder":
        return [item for item in cases if not item["calibration"]]
    return cases


def completed_keys(payload: dict[str, Any]) -> set[tuple[str, str]]:
    return {
        (str(item.get("case_id")), str(item.get("mode"))) for item in payload.get("results", [])
    }


def cumulative_cost(payload: dict[str, Any]) -> Decimal:
    return sum(
        (Decimal(str(item.get("cost_usd") or "0")) for item in payload.get("results", [])),
        start=Decimal("0"),
    )


def functional_failure(item: dict[str, Any]) -> str | None:
    if item["http_status"] != 200:
        return f"http_{item['http_status']}"
    if item.get("resolved_mode") != item["mode"]:
        return "routing_mismatch"
    if item.get("degraded"):
        return "degraded"
    allowed = set(item.get("allowed_tools") or [])
    if any(call.get("name") not in allowed for call in item.get("actual_tool_calls") or []):
        return "tool_contract_violation"
    if item["mode"] == "team":
        children = item.get("children") or []
        if len(children) != 2:
            return "child_count"
        if any(child.get("status") != "completed" for child in children):
            return "child_incomplete"
        if any(child.get("stop_reason") != "completed" for child in children):
            return "child_stop_reason"
    return None


def run(args: argparse.Namespace) -> int:
    dataset_path = args.dataset.resolve()
    dataset = load_dataset(dataset_path)
    digest = dataset_hash(dataset_path)
    output = load_or_create_output(
        args.output,
        digest=digest,
        dataset_path=dataset_path,
        seed=args.seed,
        cap=args.cost_cap_usd,
    )
    output["stopped"] = None
    token, identity_hash = register_identity(args.base_url)
    session = {
        "session_id": secrets.token_hex(8),
        "identity_sha256": identity_hash,
        "phase": args.phase,
        "started_at": utc_now(),
    }
    output["sessions"].append(session)
    atomic_write(args.output, output)

    cases = selected_cases(dataset, args.phase)
    if args.limit is not None:
        cases = cases[: args.limit]
    done = completed_keys(output)
    repeated_failure: str | None = None
    repeated_count = 0
    executed_pairs = 0

    for case in cases:
        order = list(MODES)
        chooser = random.Random(f"{args.seed}:{case['id']}")
        chooser.shuffle(order)
        for mode in order:
            key = (case["id"], mode)
            if key in done:
                continue
            reserve = args.team_reserve_usd if mode == "team" else args.single_reserve_usd
            spent_before = cumulative_cost(output)
            if spent_before + reserve >= args.cost_cap_usd:
                output["stopped"] = {
                    "reason": "cost_reserve_would_exceed_cap",
                    "before_usd": str(spent_before),
                    "required_reserve_usd": str(reserve),
                    "at": utc_now(),
                }
                output["updated_at"] = utc_now()
                atomic_write(args.output, output)
                return 3

            started = time.monotonic()
            try:
                status, body = request_json(
                    args.base_url,
                    "/api/chat",
                    method="POST",
                    payload={
                        "message": case["prompt"],
                        "execution_mode": mode,
                        "project_id": "hybrid-benchmark-v1",
                    },
                    token=token,
                    timeout=args.request_timeout_seconds,
                )
                cost, cost_detail = result_cost(args.base_url, token, body)
                run_ids = [str(body.get("run_id") or "")]
                run_ids.extend(
                    str(child.get("child_run_id") or "") for child in cost_detail["children"]
                )
                actual_tool_calls = tool_calls(
                    args.base_url,
                    token,
                    [run_id for run_id in run_ids if run_id],
                )
                item = {
                    "case_id": case["id"],
                    "category": case["category"],
                    "difficulty": case["difficulty"],
                    "calibration": case["calibration"],
                    "tools_profile": case["tools_profile"],
                    "parallelizable_subtasks": case["parallelizable_subtasks"],
                    "allowed_tools": case["tools_allowed"],
                    "actual_tool_calls": actual_tool_calls,
                    "mode": mode,
                    "mode_order": order,
                    "http_status": status,
                    "elapsed_seconds": round(time.monotonic() - started, 3),
                    "run_id": body.get("run_id"),
                    "conversation_id": body.get("conversation_id"),
                    "requested_mode": body.get("requested_mode"),
                    "resolved_mode": body.get("resolved_mode"),
                    "degraded": body.get("orchestration_degraded"),
                    "tokens_used": body.get("tokens_used"),
                    "child_tokens_used": body.get("child_tokens_used"),
                    "total_tokens_with_children": body.get("total_tokens_with_children"),
                    "cost_usd": str(cost),
                    "response": body.get("response", ""),
                    **cost_detail,
                }
                item["functional_failure"] = functional_failure(item)
            except Exception as exc:
                item = {
                    "case_id": case["id"],
                    "category": case["category"],
                    "difficulty": case["difficulty"],
                    "calibration": case["calibration"],
                    "tools_profile": case["tools_profile"],
                    "parallelizable_subtasks": case["parallelizable_subtasks"],
                    "allowed_tools": case["tools_allowed"],
                    "actual_tool_calls": [],
                    "mode": mode,
                    "mode_order": order,
                    "http_status": 0,
                    "elapsed_seconds": round(time.monotonic() - started, 3),
                    "cost_usd": "0",
                    "response": "",
                    "functional_failure": f"request_error:{type(exc).__name__}",
                }
            output["results"].append(item)
            output["updated_at"] = utc_now()
            atomic_write(args.output, output)
            print(
                json.dumps(
                    {
                        "case_id": item["case_id"],
                        "mode": mode,
                        "status": item["http_status"],
                        "degraded": item.get("degraded"),
                        "failure": item.get("functional_failure"),
                        "elapsed_seconds": item["elapsed_seconds"],
                        "tokens": item.get("total_tokens_with_children"),
                        "cost_usd": item["cost_usd"],
                        "cumulative_cost_usd": str(cumulative_cost(output)),
                    },
                    sort_keys=True,
                ),
                flush=True,
            )

            failure = item.get("functional_failure")
            if failure and failure == repeated_failure:
                repeated_count += 1
            elif failure:
                repeated_failure, repeated_count = failure, 1
            else:
                repeated_failure, repeated_count = None, 0
            if repeated_count >= 2:
                output["stopped"] = {
                    "reason": "repeated_systemic_failure",
                    "failure": failure,
                    "at": utc_now(),
                }
                atomic_write(args.output, output)
                return 4

        executed_pairs += 1
        if args.phase == "calibration":
            calibration = [
                item
                for item in output["results"]
                if item.get("calibration") and item.get("case_id") == case["id"]
            ]
            if len(calibration) == 2 and any(
                item.get("functional_failure") for item in calibration
            ):
                invalid_pairs = {
                    item["case_id"]
                    for item in output["results"]
                    if item.get("calibration") and item.get("functional_failure")
                }
                if len(invalid_pairs) > 2:
                    output["stopped"] = {
                        "reason": "calibration_invalid_pair_limit",
                        "invalid_pairs": sorted(invalid_pairs),
                        "at": utc_now(),
                    }
                    atomic_write(args.output, output)
                    return 5

    session["completed_at"] = utc_now()
    session["executed_pairs"] = executed_pairs
    output["updated_at"] = utc_now()
    output["summary"] = {
        "recorded_attempts": len(completed_keys(output)),
        "completed_runs": sum(item.get("http_status") == 200 for item in output["results"]),
        "cumulative_cost_usd": str(cumulative_cost(output)),
        "functional_failures": sum(
            bool(item.get("functional_failure")) for item in output["results"]
        ),
    }
    atomic_write(args.output, output)
    print(f"WROTE {args.output}")
    return 0


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser()
    result.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    result.add_argument("--output", type=external_output, default=DEFAULT_OUTPUT)
    result.add_argument("--base-url", default="http://archon")
    result.add_argument("--phase", choices=("calibration", "remainder", "all"), required=True)
    result.add_argument("--limit", type=bounded_int)
    result.add_argument("--seed", type=int, default=20260905)
    result.add_argument("--cost-cap-usd", type=bounded_decimal, default=Decimal("60"))
    result.add_argument("--single-reserve-usd", type=bounded_decimal, default=Decimal("2"))
    result.add_argument("--team-reserve-usd", type=bounded_decimal, default=Decimal("5"))
    result.add_argument("--request-timeout-seconds", type=float, default=600.0)
    return result


if __name__ == "__main__":
    sys.exit(run(parser().parse_args()))
