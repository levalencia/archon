# Liveness and readiness

> **Documentation status:** Draft
> **Concept status:** `implemented`
> **Status boundary:** `/healthz` reports process liveness; `/readyz` checks required local dependencies and configured telemetry. These probes do not establish an availability SLA or every provider workflow.
> **Used by:** [Module 14](../modules/14-local-operations/README.md)

## Two questions

- **Liveness:** should the process be restarted? Keep this shallow so a database outage does not create restart loops.
- **Readiness:** should this instance receive traffic? Check dependencies required by the configured mode.

```mermaid
flowchart LR
  H[/healthz] --> A[process alive]
  R[/readyz] --> DB[database]
  R --> RL[rate limiter]
  R --> OT[configured OTEL state]
  R --> CAP[capability metadata]
  DB --> D{ready?}
  RL --> D
  OT --> D
```

The endpoints are operational probes, not authenticated Core API jobs and not run-ledger events. Capability metadata makes disabled/degraded modes visible. A 200 readiness response establishes only the checks performed at that instant.

## Source and tests

- [`create_app` health/readiness routes](../../../backend/app/main.py) define HTTP behavior.
- [`lifespan`](../../../backend/app/main.py) constructs dependencies before service.
- [`test_enabled_verifier_is_app_scoped_and_readiness_is_safe`](../../../backend/tests/unit/test_health.py) checks safe capability reporting.
- [`test_real_otel_dependencies_and_span_assertion_are_part_of_the_target`](../../../backend/tests/unit/test_local_deployment.py) checks the local target contract.
- Evidence: [implementation evidence](../../IMPLEMENTATION-EVIDENCE.md).

## Interview answer

“Liveness says the process can answer; readiness gates traffic on configured required dependencies. Neither is a synthetic end-to-end transaction, a historical uptime claim, or an SLA.”
