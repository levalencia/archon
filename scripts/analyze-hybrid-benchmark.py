#!/usr/bin/env python3
"""Prepare blinded grading packets and analyze paired Single-vs-Team results."""

from __future__ import annotations

import argparse
import glob
import hashlib
import json
import math
import random
import statistics
from collections import defaultdict
from pathlib import Path
from typing import Any, cast

SECURITY_RISK_SIGNALS = (
    "attack",
    "blast radius",
    "defense-in-depth",
    "exfiltration",
    "hipaa",
    "incident",
    "isolation",
    "lateral movement",
    "prompt injection",
    "stride",
    "supply-chain",
    "threat",
    "vulnerab",
)
DIMENSIONS = (
    "instruction_following",
    "groundedness_source_quality",
    "coverage_completeness",
    "unsupported_claim_discipline",
    "actionable_usefulness",
)
MODES = ("single", "team")


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def atomic_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    temporary.replace(path)


def paired_results(results: dict[str, Any], *, calibration_only: bool) -> dict[str, dict[str, Any]]:
    grouped: dict[str, dict[str, Any]] = defaultdict(dict)
    for item in results["results"]:
        if calibration_only and not item.get("calibration"):
            continue
        grouped[item["case_id"]][item["mode"]] = item
    return {case_id: pair for case_id, pair in grouped.items() if set(pair) == {"single", "team"}}


def blinded_label(seed: int, case_id: str) -> dict[str, str]:
    digest = hashlib.sha256(f"blind:{seed}:{case_id}".encode()).digest()
    modes = ["single", "team"]
    if digest[0] % 2:
        modes.reverse()
    return {"A": modes[0], "B": modes[1]}


def prepare(args: argparse.Namespace) -> int:
    results = load_json(args.results)
    dataset = load_json(args.dataset)
    rubric = load_json(args.rubric)
    cases = {item["id"]: item for item in dataset["cases"]}
    pairs = paired_results(results, calibration_only=args.calibration_only)
    expected = 20 if args.calibration_only else 100
    if len(pairs) != expected:
        raise ValueError(f"expected {expected} complete pairs, found {len(pairs)}")

    packets: list[dict[str, Any]] = []
    key: dict[str, dict[str, str]] = {}
    for case_id in sorted(pairs):
        mapping = blinded_label(args.seed, case_id)
        key[case_id] = mapping
        case = cases[case_id]
        packets.append(
            {
                "case_id": case_id,
                "category": case["category"],
                "difficulty": case["difficulty"],
                "prompt": case["prompt"],
                "expected_traits": case["expected_traits"],
                "citation_required": case["citation_required"],
                "responses": {
                    label: pairs[case_id][mode]["response"] for label, mode in mapping.items()
                },
            }
        )

    args.output_dir.mkdir(parents=True, exist_ok=True)
    atomic_json(
        args.output_dir / "blind-key.json",
        {"schema": "archon.hybrid-benchmark-blind-key", "version": 1, "mapping": key},
    )
    for index in range(0, len(packets), args.chunk_size):
        chunk = packets[index : index + args.chunk_size]
        atomic_json(
            args.output_dir / f"blind-packet-{index // args.chunk_size + 1:02d}.json",
            {
                "schema": "archon.hybrid-benchmark-blind-packet",
                "version": 1,
                "dimensions": rubric["primary_quality_rubric"]["dimensions"],
                "scoring_contract": {
                    "dimension_scores": "integer 0, 1, or 2 for every dimension",
                    "traits_satisfied": "integer between zero and expected_traits count",
                    "material_unsupported_claims": "nonnegative integer",
                    "preference": "A, B, or tie",
                },
                "cases": chunk,
            },
        )
    print(f"prepared {len(packets)} blinded cases in {args.output_dir}")
    return 0


def load_scores(patterns: list[str]) -> list[dict[str, Any]]:
    paths = sorted({Path(path) for pattern in patterns for path in glob.glob(pattern)})
    if not paths:
        raise ValueError("no score files matched")
    payloads = [load_json(path) for path in paths]
    for payload in payloads:
        if payload.get("schema") != "archon.hybrid-benchmark-grades":
            raise ValueError("unsupported score file schema")
        if not payload.get("grader_id") or not isinstance(payload.get("cases"), list):
            raise ValueError("score file requires grader_id and cases")
    return payloads


def validated_response_score(value: dict[str, Any], expected_trait_count: int) -> dict[str, float]:
    dimensions = value.get("dimensions") or {name: value.get(name) for name in DIMENSIONS}
    if set(dimensions) != set(DIMENSIONS):
        raise ValueError("every score must contain the five rubric dimensions")
    raw_scores = [dimensions[name] for name in DIMENSIONS]
    if any(not isinstance(score, int) for score in raw_scores):
        raise ValueError("dimension scores must be integers")
    scores = [cast(int, score) for score in raw_scores]
    if any(score not in {0, 1, 2} for score in scores):
        raise ValueError("dimension score outside 0..2")
    traits_value = value.get("traits_satisfied")
    if not isinstance(traits_value, int):
        raise ValueError("traits_satisfied must be an integer")
    traits = traits_value
    unsupported = int(value.get("material_unsupported_claims", 0))
    if not 0 <= traits <= expected_trait_count or unsupported < 0:
        raise ValueError("invalid trait or unsupported-claim count")
    return {
        "quality": float(sum(scores)),
        "trait_rate": traits / expected_trait_count,
        "unsupported": float(unsupported),
    }


def percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round((len(ordered) - 1) * fraction)))
    return ordered[index]


def bootstrap_ci(values: list[float], seed: int, iterations: int = 10_000) -> list[float]:
    rng = random.Random(seed)
    means = [statistics.fmean(rng.choice(values) for _ in values) for _ in range(iterations)]
    return [round(percentile(means, 0.025), 4), round(percentile(means, 0.975), 4)]


def sign_test_p_value(wins: int, losses: int) -> float:
    total = wins + losses
    if total == 0:
        return 1.0
    extreme = min(wins, losses)
    probability = sum(math.comb(total, index) for index in range(extreme + 1)) / (2**total)
    return min(1.0, 2 * probability)


def auto_mode(prompt: str) -> str:
    normalized = " ".join(prompt.casefold().split())
    signal_count = sum(1 for signal in SECURITY_RISK_SIGNALS if signal in normalized)
    return "team" if signal_count >= 2 else "single"


def cohen_kappa(labels_a: dict[str, str], labels_b: dict[str, str]) -> float | None:
    common = sorted(set(labels_a) & set(labels_b))
    if not common:
        return None
    labels = ("A", "B", "tie")
    observed = sum(labels_a[key] == labels_b[key] for key in common) / len(common)
    expected = sum(
        (sum(labels_a[key] == label for key in common) / len(common))
        * (sum(labels_b[key] == label for key in common) / len(common))
        for label in labels
    )
    if expected == 1:
        return 1.0
    return (observed - expected) / (1 - expected)


def analyze(args: argparse.Namespace) -> int:
    results = load_json(args.results)
    dataset = load_json(args.dataset)
    blind_key = load_json(args.blind_key)["mapping"]
    score_payloads = load_scores(args.scores)
    cases = {item["id"]: item for item in dataset["cases"]}
    all_pairs = paired_results(results, calibration_only=args.calibration_only)
    invalid_pair_ids = sorted(
        case_id
        for case_id, pair in all_pairs.items()
        if any(item.get("functional_failure") for item in pair.values())
    )
    pairs = {
        case_id: pair for case_id, pair in all_pairs.items() if case_id not in invalid_pair_ids
    }

    per_grader: dict[str, dict[str, dict[str, dict[str, float]]]] = defaultdict(dict)
    preferences: dict[str, dict[str, str]] = defaultdict(dict)
    for payload in score_payloads:
        grader = str(payload["grader_id"])
        for scored_case in payload["cases"]:
            case_id = scored_case["case_id"]
            expected_count = len(cases[case_id]["expected_traits"])
            response_scores = scored_case.get("responses") or scored_case.get("scores")
            if not isinstance(response_scores, dict):
                response_scores = {
                    "A": scored_case.get("response_A") or scored_case.get("response_a"),
                    "B": scored_case.get("response_B") or scored_case.get("response_b"),
                }
            if not all(isinstance(response_scores.get(label), dict) for label in ("A", "B")):
                raise ValueError("scored case requires A and B response scores")
            mapped: dict[str, dict[str, float]] = {}
            for label in ("A", "B"):
                mode = blind_key[case_id][label]
                mapped[mode] = validated_response_score(response_scores[label], expected_count)
            per_grader[grader][case_id] = mapped
            preferences[grader][case_id] = scored_case["preference"]

    graders = sorted(per_grader)
    required_ids = set(pairs)
    for grader in graders:
        missing = required_ids - set(per_grader[grader])
        if missing:
            raise ValueError(f"grader {grader} missing {len(missing)} cases")

    rows: list[dict[str, Any]] = []
    for case_id in sorted(required_ids):
        mode_scores: dict[str, dict[str, float]] = {}
        for mode in MODES:
            mode_scores[mode] = {
                metric: statistics.fmean(
                    per_grader[grader][case_id][mode][metric] for grader in graders
                )
                for metric in ("quality", "trait_rate", "unsupported")
            }
        delta = mode_scores["team"]["quality"] - mode_scores["single"]["quality"]
        winner = "team" if delta > 0 else "single" if delta < 0 else "tie"
        pair = pairs[case_id]
        route = auto_mode(cases[case_id]["prompt"])
        oracle = winner if winner != "tie" else min(MODES, key=lambda m: float(pair[m]["cost_usd"]))
        rows.append(
            {
                "case_id": case_id,
                "category": cases[case_id]["category"],
                "difficulty": cases[case_id]["difficulty"],
                "tools_profile": cases[case_id]["tools_profile"],
                "quality": mode_scores,
                "quality_delta": delta,
                "winner": winner,
                "auto_mode": route,
                "oracle_mode": oracle,
                "auto_correct": route == oracle,
                "latency": {mode: float(pair[mode]["elapsed_seconds"]) for mode in MODES},
                "tokens": {
                    mode: int(pair[mode].get("total_tokens_with_children") or 0) for mode in MODES
                },
                "cost": {mode: float(pair[mode]["cost_usd"]) for mode in MODES},
            }
        )

    deltas = [row["quality_delta"] for row in rows]
    wins = sum(row["winner"] == "team" for row in rows)
    losses = sum(row["winner"] == "single" for row in rows)
    ties = len(rows) - wins - losses

    by_category: dict[str, Any] = {}
    for category in sorted({row["category"] for row in rows}):
        selected = [row for row in rows if row["category"] == category]
        by_category[category] = {
            "cases": len(selected),
            "mean_quality_delta": round(
                statistics.fmean(row["quality_delta"] for row in selected), 4
            ),
            "team_wins": sum(row["winner"] == "team" for row in selected),
            "ties": sum(row["winner"] == "tie" for row in selected),
            "single_wins": sum(row["winner"] == "single" for row in selected),
            "mean_latency_ratio": round(
                statistics.fmean(
                    row["latency"]["team"] / row["latency"]["single"] for row in selected
                ),
                4,
            ),
        }

    agreement = None
    if len(graders) >= 2:
        first_labels = {
            case_id: label
            for case_id, label in preferences[graders[0]].items()
            if case_id in required_ids
        }
        second_labels = {
            case_id: label
            for case_id, label in preferences[graders[1]].items()
            if case_id in required_ids
        }
        agreement = round(cohen_kappa(first_labels, second_labels) or 0, 4)
    operational_results = [
        item for item in results["results"] if not args.calibration_only or item.get("calibration")
    ]
    summary = {
        "schema": "archon.hybrid-benchmark-analysis",
        "version": 1,
        "created_from_results_sha256": hashlib.sha256(args.results.read_bytes()).hexdigest(),
        "case_count": len(rows),
        "invalid_pair_count": len(invalid_pair_ids),
        "invalid_pair_ids": invalid_pair_ids,
        "grader_count": len(graders),
        "grader_preference_kappa": agreement,
        "quality": {
            "single_mean": round(
                statistics.fmean(row["quality"]["single"]["quality"] for row in rows), 4
            ),
            "team_mean": round(
                statistics.fmean(row["quality"]["team"]["quality"] for row in rows), 4
            ),
            "mean_delta": round(statistics.fmean(deltas), 4),
            "paired_bootstrap_95_ci": bootstrap_ci(deltas, args.seed),
            "team_wins": wins,
            "ties": ties,
            "single_wins": losses,
            "two_sided_sign_test_p": round(sign_test_p_value(wins, losses), 6),
        },
        "operations": {
            "single_cost_usd": round(
                sum(
                    float(item.get("cost_usd") or 0)
                    for item in operational_results
                    if item["mode"] == "single"
                ),
                6,
            ),
            "team_cost_usd": round(
                sum(
                    float(item.get("cost_usd") or 0)
                    for item in operational_results
                    if item["mode"] == "team"
                ),
                6,
            ),
            "single_tokens": sum(
                int(item.get("total_tokens_with_children") or 0)
                for item in operational_results
                if item["mode"] == "single"
            ),
            "team_tokens": sum(
                int(item.get("total_tokens_with_children") or 0)
                for item in operational_results
                if item["mode"] == "team"
            ),
            "functional_failures": sum(
                bool(item.get("functional_failure")) for item in operational_results
            ),
            "mean_latency_ratio": round(
                statistics.fmean(row["latency"]["team"] / row["latency"]["single"] for row in rows),
                4,
            ),
        },
        "auto_offline": {
            "routing_accuracy": round(sum(row["auto_correct"] for row in rows) / len(rows), 4),
            "normalized_quality_regret": round(
                statistics.fmean(
                    max(
                        row["quality"]["single"]["quality"],
                        row["quality"]["team"]["quality"],
                    )
                    - row["quality"][row["auto_mode"]]["quality"]
                    for row in rows
                )
                / 10,
                4,
            ),
            "cost_usd": round(sum(row["cost"][row["auto_mode"]] for row in rows), 6),
            "mean_latency_seconds": round(
                statistics.fmean(row["latency"][row["auto_mode"]] for row in rows), 4
            ),
            "team_routes": sum(row["auto_mode"] == "team" for row in rows),
            "single_routes": sum(row["auto_mode"] == "single" for row in rows),
        },
        "by_category": by_category,
        "rows": rows,
        "claim_boundary": (
            "Directional local evidence for this provider/model and benchmark revision only."
        ),
    }
    atomic_json(args.output, summary)
    print(f"analyzed {len(rows)} pairs into {args.output}")
    return 0


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser()
    subparsers = result.add_subparsers(dest="command", required=True)

    prepare_parser = subparsers.add_parser("prepare")
    prepare_parser.add_argument("--results", type=Path, required=True)
    prepare_parser.add_argument("--dataset", type=Path, required=True)
    prepare_parser.add_argument("--rubric", type=Path, required=True)
    prepare_parser.add_argument("--output-dir", type=Path, required=True)
    prepare_parser.add_argument("--chunk-size", type=int, default=5)
    prepare_parser.add_argument("--seed", type=int, default=20260905)
    prepare_parser.add_argument("--calibration-only", action="store_true")
    prepare_parser.set_defaults(handler=prepare)

    analyze_parser = subparsers.add_parser("analyze")
    analyze_parser.add_argument("--results", type=Path, required=True)
    analyze_parser.add_argument("--dataset", type=Path, required=True)
    analyze_parser.add_argument("--blind-key", type=Path, required=True)
    analyze_parser.add_argument("--scores", action="append", required=True)
    analyze_parser.add_argument("--output", type=Path, required=True)
    analyze_parser.add_argument("--seed", type=int, default=20260905)
    analyze_parser.add_argument("--calibration-only", action="store_true")
    analyze_parser.set_defaults(handler=analyze)
    return result


if __name__ == "__main__":
    arguments = parser().parse_args()
    raise SystemExit(arguments.handler(arguments))
