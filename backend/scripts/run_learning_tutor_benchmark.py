#!/usr/bin/env python3
"""Validate or execute the versioned learning-tutor benchmark.

Live execution is opt-in because it incurs provider cost. Supply an existing
bearer token through an environment variable; credentials are never accepted
as command-line arguments or written to the report.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter
from pathlib import Path
from time import monotonic
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.learning_tutor.evaluation import load_tutor_eval_dataset, score_tutor_response

_DEFAULT_DATASET = Path(__file__).resolve().parents[1] / "evals/learning_tutor/concepts-v1.json"


def _post(base_url: str, token: str, payload: dict[str, Any], timeout: float) -> dict[str, Any]:
    request = Request(
        f"{base_url.rstrip('/')}/api/learning-tutor/answer",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        method="POST",
    )
    with urlopen(request, timeout=timeout) as response:  # noqa: S310 -- explicit operator URL
        decoded = json.loads(response.read())
    if not isinstance(decoded, dict):
        raise ValueError("Tutor endpoint returned a non-object response")
    return decoded


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", type=Path, default=_DEFAULT_DATASET)
    parser.add_argument("--difficulty", choices=("basic", "medium", "hard"))
    parser.add_argument("--case-id", action="append", default=[])
    parser.add_argument("--limit", type=int)
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--base-url", default="http://127.0.0.1")
    parser.add_argument("--token-env", default="COGENTREX_EVAL_TOKEN")
    parser.add_argument("--timeout", type=float, default=180.0)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    dataset = load_tutor_eval_dataset(args.dataset)
    cases = [
        case
        for case in dataset.cases
        if (args.difficulty is None or case.difficulty == args.difficulty)
        and (not args.case_id or case.id in set(args.case_id))
    ]
    if args.limit is not None:
        if args.limit < 1:
            raise SystemExit("--limit must be positive")
        cases = cases[: args.limit]
    if not cases:
        raise SystemExit("No evaluation cases matched")

    counts = Counter(case.difficulty for case in cases)
    if not args.live:
        print(
            json.dumps(
                {
                    "schema": dataset.schema_name,
                    "version": dataset.version,
                    "validated_cases": len(cases),
                    "difficulty_counts": dict(sorted(counts.items())),
                    "mode": "validation-only",
                },
                indent=2,
            )
        )
        return

    token = os.environ.get(args.token_env, "").strip()
    if not token:
        raise SystemExit(f"Live mode requires bearer token in {args.token_env}")

    observations: list[dict[str, Any]] = []
    for case in cases:
        started = monotonic()
        try:
            response = _post(
                args.base_url,
                token,
                {
                    "question": case.question,
                    "project_id": "default",
                    "context": case.context,
                },
                args.timeout,
            )
            score = score_tutor_response(case, response)
            observations.append(
                {
                    "case_id": case.id,
                    "difficulty": case.difficulty,
                    "latency_seconds": round(monotonic() - started, 3),
                    "score": score.model_dump(),
                    "answer_markdown": response.get("answer_markdown", ""),
                    "citations": response.get("citations", []),
                    "metrics": response.get("metrics", {}),
                    "error": None,
                }
            )
        except (HTTPError, URLError, TimeoutError, ValueError) as exc:
            observations.append(
                {
                    "case_id": case.id,
                    "difficulty": case.difficulty,
                    "latency_seconds": round(monotonic() - started, 3),
                    "score": None,
                    "answer_markdown": "",
                    "citations": [],
                    "metrics": {},
                    "error": type(exc).__name__,
                }
            )

    passed = sum(
        item["score"] is not None and item["score"]["deterministic_pass"] for item in observations
    )
    report = {
        "schema": "cogentrex.learning-tutor-eval-report",
        "dataset_version": dataset.version,
        "mode": "live",
        "case_count": len(observations),
        "deterministic_pass_count": passed,
        "deterministic_pass_rate": round(passed / len(observations), 4),
        "observations": observations,
    }
    encoded = json.dumps(report, indent=2, ensure_ascii=False) + "\n"
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(encoded, encoding="utf-8")
    print(encoded, end="")


if __name__ == "__main__":
    main()
