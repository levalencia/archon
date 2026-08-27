# Metrics

> **Documentation status:** Draft
> **Concept status:** `implemented`
> **Status boundary:** Prometheus samples are generated from a process-local registry. No durable multi-replica aggregation, alerting, or SLO evidence is implemented.
> **Used by:** [Module 13](../modules/13-auth-ui-observability/README.md)

## What metrics answer

Metrics aggregate behavior across events: counts, current values, and latency distributions. Unlike [structured logs](structured-logging.md), they intentionally discard per-request detail. Unlike [traces](tracing-opentelemetry.md), they do not preserve a request path.

Archon maps typed runtime events into bounded metric names and labels, then exposes Prometheus text. Labels avoid user IDs, run IDs, prompts, URLs, and arbitrary error text because unbounded cardinality and sensitive dimensions make metrics unsafe and expensive.

## Signal flow

```mermaid
flowchart LR
  E[AgentEvent] --> A[RuntimeMetricsAdapter]
  A --> C[counters]
  A --> H[latency observations]
  C --> P[/metrics Prometheus text]
  H --> P
```

CI and disaster-recovery measurements are not emitted as authenticated agent-runtime metrics. They come from workflow/script artifacts and have their own evidence boundaries.

## Source and tests

- [`backend/app/observability/metrics.py`](../../../backend/app/observability/metrics.py) defines the registry and `get_prometheus_text`.
- [`CompositeEventSink.emit`](../../../backend/app/observability/runtime_events.py) sends typed events to adapters.
- [`create_app`](../../../backend/app/main.py) exposes the metrics endpoint and application wiring.
- [`test_exact_event_to_metric_span_and_correlation_mapping`](../../../backend/tests/unit/test_runtime_observability.py) checks event-to-signal mapping.
- [`test_error_timeout_event_marks_metrics_and_spans`](../../../backend/tests/unit/test_runtime_observability.py) checks failure accounting.
- Evidence: [implementation evidence](../../IMPLEMENTATION-EVIDENCE.md).

## Interview answer

“Metrics provide low-cardinality aggregate health and behavior from runtime events. The current registry is process-local, so it proves instrumentation shape in tested/local paths—not fleet-wide aggregation, alert delivery, or an SLO.”
