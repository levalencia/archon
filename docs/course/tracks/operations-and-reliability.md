# Operations and reliability

> **Track status:** draft; validate against the current branch before operating
> **Scope:** verified local/test behavior; public production operation is not established

This route helps a contributor diagnose and explain the local production-like target. It links to canonical teaching rather than duplicating it.

## Read in this order

1. [Typed runtime](../modules/02-typed-runtime/README.md) and [ReAct/stop reasons](../modules/03-react-loop/README.md): know terminal behavior before debugging it.
2. [Policy and approvals](../modules/05-policy-and-approvals/README.md): distinguish an intentional fail-closed stop from an outage.
3. [Run Ledger](../modules/07-run-ledger/README.md): follow ordered durable evidence.
4. [Evaluation](../modules/09-evaluation-harness/README.md): measure a recorded run without rerunning external effects.
5. [Reliability](../modules/10-resilience/README.md): choose retries, idempotency, deadlines, breakers, fallback, and limits deliberately.
6. [Governed MCP](../modules/12-governed-mcp/README.md): inspect external tool discovery, inventory, policy, approval, and invocation boundaries.
7. [Auth, UI, SSE, and observability](../modules/13-auth-ui-observability/README.md): correlate owner scope, events, logs, metrics, traces, and Workbench views.
8. [Local operations and recovery](../modules/14-local-operations/README.md): verify containers, migrations, readiness, backup, restore, and measured recovery observations.

## Operational lookup

| Question | First evidence | Source/reference | Caution |
|---|---|---|---|
| Is the process alive? | `GET /healthz` | [`healthz`](../../../backend/app/main.py), [API map](../reference/api-map.md) | Liveness is not dependency readiness. |
| Can dependencies serve traffic? | `GET /readyz` | [`readyz`](../../../backend/app/main.py) | Readiness checks selected dependencies, not every production SLO. |
| Why did a run stop? | run `stop_reason` and final `run_stopped` | [stop reasons](../reference/stop-reasons.md), [events](../reference/event-catalog.md) | Preserve owner scope and redact payloads. |
| What happened in order? | `/api/runs/{run_id}/events` | [`RunRepository`](../../../backend/app/services/run_ledger.py) | Events are evidence, not hidden reasoning. |
| Is a provider failing repeatedly? | readiness breaker state, logs, metrics | [`CircuitBreaker`](../../../backend/app/security/circuit_breaker.py) | An open breaker is a protective state, not root cause. |
| Is storage at the expected revision? | `alembic current` / `alembic heads` | [database schema](../reference/database-schema.md) | ORM `create_all` and migration history are separate boundaries. |
| Did local recovery work? | timestamped smoke report | [`local-dr-smoke.sh`](../../../scripts/local-dr-smoke.sh), [DR runbook](../../DR-RUNBOOK.md) | A single local drill does not establish an organizational RTO/RPO. |
| Which tests cover the behavior? | behavior-focused test node | [test map](../reference/test-map.md) | Unit tests do not prove provider, load, or deployment behavior. |

## Incident trace

1. Record UTC time, revision, environment, correlation ID, run ID, and owner/project scope; do not paste secrets or raw sensitive payloads.
2. Check liveness, then readiness. Preserve the original status and body.
3. Read the terminal [stop reason](../reference/stop-reasons.md); do not classify policy denial as infrastructure failure.
4. Fetch ordered events and locate the last successful boundary in the [event catalog](../reference/event-catalog.md).
5. Correlate safe logs, metrics, and traces. Treat absent telemetry as an evidence gap.
6. Inspect the relevant source bookmark and focused test, then reproduce with mock/disposable data if safe.
7. Apply the smallest reversible action. Do not reset a breaker or approve a call without understanding owner and exact binding.
8. Capture command, output, cleanup, residual risk, and whether the finding is unit, integration, local Compose, or external evidence.

## Recovery objectives

**RTO** is the target time to restore service; **RPO** is the maximum acceptable data-loss window. Measure restore elapsed time and newest recovered record during a controlled drill. Do not report those observations as guaranteed objectives unless owners, cadence, monitoring, retention, and repeated tests are defined.

## Production-readiness gaps to ask about

Public deployment, multi-host behavior, load/capacity, SLOs and alert ownership, secret rotation, backup schedules and off-site retention, repeated restore evidence, provider parity, migration rollback policy, incident response, and external security review remain separate evidence dimensions. Consult the [current evidence matrix](../../IMPLEMENTATION-EVIDENCE.md) before any status claim.
