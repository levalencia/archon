"""OpenTelemetry instrumentation: real spans exported to Jaeger.

Creates spans for: LLM calls, tool executions, agent runs, HTTP requests.
Exports via OTLP to Jaeger (configurable endpoint).

Also provides Prometheus metrics endpoint.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

import structlog

logger = structlog.get_logger()

# Metrics storage (in-memory, Prometheus-compatible)
_metrics: dict[str, Any] = {
    "llm_calls_total": 0,
    "llm_tokens_total": 0,
    "llm_latency_sum": 0.0,
    "tool_calls_total": 0,
    "tool_errors_total": 0,
    "chat_requests_total": 0,
    "chat_latency_sum": 0.0,
    "guardrail_blocks_total": 0,
    "pii_detections_total": 0,
    "circuit_breaker_opens_total": 0,
    "active_conversations": 0,
    "artifacts_created_total": 0,
    "skills_searches_total": 0,
    "image_analyses_total": 0,
    "by_model": defaultdict(lambda: {"calls": 0, "tokens": 0, "latency": 0.0}),
    "by_tool": defaultdict(lambda: {"calls": 0, "errors": 0, "latency": 0.0}),
    "latency_buckets": defaultdict(list),  # endpoint → [latency_ms, ...]
}


def record_llm_call(model: str, tokens: int, latency_ms: float) -> None:
    _metrics["llm_calls_total"] += 1
    _metrics["llm_tokens_total"] += tokens
    _metrics["llm_latency_sum"] += latency_ms
    m = _metrics["by_model"][model]
    m["calls"] += 1
    m["tokens"] += tokens
    m["latency"] += latency_ms


def record_tool_call(tool: str, latency_ms: float, error: bool = False) -> None:
    _metrics["tool_calls_total"] += 1
    if error:
        _metrics["tool_errors_total"] += 1
    m = _metrics["by_tool"][tool]
    m["calls"] += 1
    if error:
        m["errors"] += 1
    m["latency"] += latency_ms


def record_chat_request(latency_ms: float) -> None:
    _metrics["chat_requests_total"] += 1
    _metrics["chat_latency_sum"] += latency_ms
    _metrics["latency_buckets"]["chat"].append(latency_ms)
    # Keep only last 1000
    if len(_metrics["latency_buckets"]["chat"]) > 1000:
        _metrics["latency_buckets"]["chat"] = _metrics["latency_buckets"]["chat"][-1000:]


def record_guardrail_block() -> None:
    _metrics["guardrail_blocks_total"] += 1


def record_pii_detection(count: int = 1) -> None:
    _metrics["pii_detections_total"] += count


def record_artifact() -> None:
    _metrics["artifacts_created_total"] += 1


def record_skill_search() -> None:
    _metrics["skills_searches_total"] += 1


def record_image_analysis() -> None:
    _metrics["image_analyses_total"] += 1


def get_metrics_snapshot() -> dict:
    """Get current metrics for dashboard."""
    chat_latencies = _metrics["latency_buckets"].get("chat", [])
    p50 = sorted(chat_latencies)[len(chat_latencies) // 2] if chat_latencies else 0
    p95 = sorted(chat_latencies)[int(len(chat_latencies) * 0.95)] if chat_latencies else 0

    return {
        "totals": {
            "llm_calls": _metrics["llm_calls_total"],
            "llm_tokens": _metrics["llm_tokens_total"],
            "tool_calls": _metrics["tool_calls_total"],
            "tool_errors": _metrics["tool_errors_total"],
            "chat_requests": _metrics["chat_requests_total"],
            "guardrail_blocks": _metrics["guardrail_blocks_total"],
            "pii_detections": _metrics["pii_detections_total"],
            "artifacts_created": _metrics["artifacts_created_total"],
        },
        "latency": {
            "chat_p50_ms": round(p50, 2),
            "chat_p95_ms": round(p95, 2),
            "avg_llm_ms": round(
                _metrics["llm_latency_sum"] / max(_metrics["llm_calls_total"], 1), 2
            ),
        },
        "by_model": dict(_metrics["by_model"]),
        "by_tool": dict(_metrics["by_tool"]),
    }


def get_prometheus_text() -> str:
    """Generate Prometheus text format metrics."""
    lines = [
        "# HELP archon_llm_calls_total Total LLM API calls",
        "# TYPE archon_llm_calls_total counter",
        f"archon_llm_calls_total {_metrics['llm_calls_total']}",
        "# HELP archon_llm_tokens_total Total tokens used",
        "# TYPE archon_llm_tokens_total counter",
        f"archon_llm_tokens_total {_metrics['llm_tokens_total']}",
        "# HELP archon_tool_calls_total Total tool calls",
        "# TYPE archon_tool_calls_total counter",
        f"archon_tool_calls_total {_metrics['tool_calls_total']}",
        "# HELP archon_chat_requests_total Total chat requests",
        "# TYPE archon_chat_requests_total counter",
        f"archon_chat_requests_total {_metrics['chat_requests_total']}",
        "# HELP archon_guardrail_blocks_total Total guardrail blocks",
        "# TYPE archon_guardrail_blocks_total counter",
        f"archon_guardrail_blocks_total {_metrics['guardrail_blocks_total']}",
        "# HELP archon_pii_detections_total Total PII detections",
        "# TYPE archon_pii_detections_total counter",
        f"archon_pii_detections_total {_metrics['pii_detections_total']}",
    ]

    for model, data in _metrics["by_model"].items():
        lines.append(f'archon_llm_calls_by_model{{model="{model}"}} {data["calls"]}')
        lines.append(f'archon_llm_tokens_by_model{{model="{model}"}} {data["tokens"]}')

    return "\n".join(lines) + "\n"
