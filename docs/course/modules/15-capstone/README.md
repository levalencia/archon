# Module 15 — Capstone: evidence-first demo and interview defense

> **Documentation status:** Draft
> **Reviewed revision:** `3577b00` documentation review
> **Estimated time:** 180 minutes
> **Canonical concepts:** [bounded-delegation](../../concepts/bounded-delegation.md), [mcp](../../concepts/mcp.md), [authentication](../../concepts/authentication.md), [tracing-opentelemetry](../../concepts/tracing-opentelemetry.md), [backup-restore](../../concepts/backup-restore.md), [rto-rpo](../../concepts/rto-rpo.md)

## Why this module exists

The capstone is not another feature. It is a disciplined claim-to-evidence narrative that joins policy, approvals, ledger, RAG/evaluation, one verifier child, MCP, observability, and local recovery. You will prepare truthful 2-, 15-, and 45-minute walkthroughs and an evidence packet.

## Beginner explanation

The capstone is claim control: say exactly what exists, how it is wired, what tests establish, what was observed, and what remains unverified. A persuasive demo does not merge distinct proof paths or turn local evidence into production claims.

## Prerequisites and vocabulary

### Learn first

- [Module 11: bounded verifier](../11-bounded-delegation/README.md) — model review inside a deterministic boundary.
- [Module 12: governed MCP](../12-governed-mcp/README.md) — external tool governance.
- [Module 13: auth and observability](../13-auth-ui-observability/README.md) — request identity and signals.
- [Module 14: local operations](../14-local-operations/README.md) — startup, CI and recovery evidence.

### Vocabulary

| Term | Beginner definition | Canonical source |
|---|---|---|
| claim ladder | Exists, wired, tested, observed, UI and deployed assessed independently. | [implementation evidence](../../../IMPLEMENTATION-EVIDENCE.md) |
| replay | Read-only reconstruction of persisted ordered events; no model/tool call. | [replay, fork and compare](../../concepts/replay-fork-compare.md) |
| grounding | Rule-based claim/evidence support check. | [groundedness](../../concepts/groundedness.md) |
| recorded evaluation | Dataset-versioned scoring of already persisted runs. | [evaluation harness](../../concepts/evaluation-harness.md) |

## Learning outcomes

After this module, the learner can:

1. select claims supported by direct evidence;
2. run a focused cross-capability acceptance;
3. deliver layered demos without hiding limits;
4. answer design/failure/security/operations follow-ups with exact symbols;
5. identify production gaps rather than hand-wave them;

## Problem and mental model

Build the story as a proof graph. Every claim points to source, test, observed artifact, and limitation. The graph may stop at local observation; never draw an unsupported edge to production. The demo spine is Policy → Run → Approval → Tool → Evidence → Evaluation, with auth/ownership around it and operations beneath it.

The connection to the course spine is explicit: **Policy → Run → Approval → Tool → Evidence → Evaluation**. Inputs are authenticated/scoped data; outputs are typed results plus inspectable evidence; mutable authority never comes from model prose.

## Architecture and components

```mermaid
flowchart LR
  C[Claim] --> S[Source symbol]
  C --> T[Test contract]
  C --> O[Observed artifact]
  C --> L[Explicit limitation]
  U[User scenario] --> A[Auth + ownership]
  A --> P[Policy/approval]
  P --> X[Native or governed MCP tool]
  X --> R[(Run Ledger)]
  R --> RP[read-only replay]
  G[retrieved evidence] --> GR[deterministic grounding]
  GR --> V[optional bounded verifier]
  R --> EV[durable recorded-run evaluation]
  R --> OBS[logs/metrics/traces/UI]
  R --> DR[backup/restore]
```

### Component responsibilities

| Component | Responsibility | Must not be assumed |
|---|---|---|
| Claim ledger | Pair each statement with source, test, observation and limitation. | One artifact proves every evidence dimension. |
| Demo controller | Select a synthetic scenario and fallback evidence before presenting. | A live provider is required for truthful proof. |
| Runtime proof | Show policy/approval/tool and ordered run events. | Replay calls the model or repeats side effects. |
| Quality proof | Show grounding, optional verifier and recorded evaluation separately. | These are one linear ledger-triggered operation. |

## Startup sequence

```mermaid
sequenceDiagram
  participant Presenter
  participant Revision
  participant LocalStack
  participant Evidence
  Presenter->>Revision: record git SHA and clean status
  Presenter->>Evidence: choose claims and known limits
  Presenter->>LocalStack: start/migrate/wait ready
  LocalStack-->>Presenter: health, readiness, metrics, OTEL signal
  Presenter->>Presenter: rehearse fallback if live provider unavailable
  Note over Presenter: final external providers are not verified
```

Demo preparation pins the revision and claim set before starting the local stack. A failed readiness or optional provider check triggers the predeclared recorded-evidence fallback, never a simulated live success.

## Per-request sequence

```mermaid
sequenceDiagram
  participant User
  participant UI
  participant Runtime
  participant Policy
  participant Tool
  participant Ledger
  participant Replay
  participant Grounding
  participant Verifier
  participant EvalService
  User->>UI: authenticated bounded task
  UI->>Runtime: SSE request + owner/project
  Runtime->>Policy: typed tool/MCP proposal
  alt ask
    Policy-->>UI: exact-bound approval
    UI-->>Policy: owner decision
  else deny
    Policy->>Ledger: denial evidence
  end
  Policy->>Tool: one bounded execution if authorized
  Tool->>Ledger: result metadata/events
  User->>Replay: inspect persisted events (read-only)
  Tool-->>Grounding: retrieved evidence for claims
  Grounding->>Verifier: optional sealed evidence review
  User->>EvalService: map versioned cases to terminal run IDs
  EvalService-->>UI: durable evaluation record
```

Each arrow is optional and separately evidenced. A denied tool never reaches execution; replay is read-only; grounding belongs to the grounded workflow; verifier review is model-generated; recorded evaluation is a later durable operation.

## Four proof paths—do not conflate them

1. **Ledger → replay:** reconstructs stored ordered events and calls neither model nor tools.
2. **Retrieval → grounding:** deterministic rules compare claims with retrieved evidence during the grounded workflow.
3. **Grounding → verifier:** an optional model-generated evidence review runs inside a deterministic schema-validated no-tools boundary.
4. **Ledger → `EvaluationService`:** a separate post-run operation maps versioned dataset cases to successful terminal runs and persists scores.

## State and lifecycle

```mermaid
stateDiagram-v2
  [*] --> Prepared
  Prepared --> Ready: revision + stack + evidence checked
  Ready --> Demonstrating
  Demonstrating --> Complete: claims shown and limits stated
  Demonstrating --> DegradedDemo: optional dependency unavailable
  DegradedDemo --> Complete: deterministic recorded evidence used honestly
  Complete --> Reviewed: questions + artifact checklist
```

These are presentation checkpoints, not product run statuses. The presenter must label live output, deterministic tests and recorded artifacts differently throughout the demo.

## Source walkthrough

| Order | Source symbol | Why inspect it | Implementation status/boundary |
|---:|---|---|---|
| 1 | [`docs/IMPLEMENTATION-EVIDENCE.md:capability matrix`](../../../../docs/IMPLEMENTATION-EVIDENCE.md) | Canonical mutable claim/evidence boundaries. | `implemented` within stated boundary |
| 2 | [`backend/app/runtime/engine.py:AgentRuntime.run`](../../../../backend/app/runtime/engine.py) | Bounded runtime spine. | `implemented` within stated boundary |
| 3 | [`backend/app/security/policy.py:RulePolicyEngine.evaluate`](../../../../backend/app/security/policy.py) | Deterministic tool decision boundary. | `implemented` within stated boundary |
| 4 | [`backend/app/services/run_ledger.py:RunRepository`](../../../../backend/app/services/run_ledger.py) | Durable event/evidence spine. | `implemented` within stated boundary |
| 5 | [`backend/app/delegation/service.py:EvidenceVerifierSpecialist`](../../../../backend/app/delegation/service.py) | One evidence-only child. | `implemented` within stated boundary |
| 6 | [`backend/app/mcp/runtime.py:MCPRuntimeToolProvider`](../../../../backend/app/mcp/runtime.py) | Governed external tool binding. | `implemented` within stated boundary |
| 7 | [`backend/app/observability/runtime_events.py:CompositeEventSink`](../../../../backend/app/observability/runtime_events.py) | Cross-signal observability. | `implemented` within stated boundary |
| 8 | [`scripts/local-dr-smoke.sh:local DR proof`](../../../../scripts/local-dr-smoke.sh) | Recovery and exact evidence comparison. | `implemented` within stated boundary |

### Tests to inspect

| Test | Contract proved | What it does not prove |
|---|---|---|
| [`backend/tests/integration/test_live_policy_wiring.py`](../../../../backend/tests/integration/test_live_policy_wiring.py) | live policy/approval path. | Does not prove public deployment, external-provider parity, or production scale. |
| [`backend/tests/integration/test_run_replay_api.py`](../../../../backend/tests/integration/test_run_replay_api.py) | durable replay evidence. | Does not prove public deployment, external-provider parity, or production scale. |
| [`backend/tests/integration/test_verifier_benefit.py`](../../../../backend/tests/integration/test_verifier_benefit.py) | bounded verifier measurement. | Does not prove public deployment, external-provider parity, or production scale. |
| [`backend/tests/integration/test_mcp_runtime.py`](../../../../backend/tests/integration/test_mcp_runtime.py) | governed MCP invocation. | Does not prove public deployment, external-provider parity, or production scale. |
| [`backend/tests/unit/test_otel_tracing_wire.py`](../../../../backend/tests/unit/test_otel_tracing_wire.py) | trace wiring. | Does not prove public deployment, external-provider parity, or production scale. |
| [`backend/tests/unit/test_local_dr.py`](../../../../backend/tests/unit/test_local_dr.py) | recovery contracts. | Does not prove public deployment, external-provider parity, or production scale. |

## Try it: bounded exercise

### Goal

Run the focused contract set and turn each passing test into one precise claim plus one limitation.

### Safety and setup

- Working directory starts at repository root; backend dependencies must be installed with `uv`.
- The focused set uses fixtures/local state. Do not insert real credentials or point fixtures at external services.
- Side effects are test databases/processes cleaned by fixtures; if interrupted, remove only resources you created.

### Steps

```bash
cd backend
uv run pytest -q tests/integration/test_live_policy_wiring.py tests/integration/test_run_replay_api.py tests/integration/test_verifier_benefit.py tests/integration/test_mcp_runtime.py tests/unit/test_otel_tracing_wire.py tests/unit/test_local_dr.py
```

Create a two-column note: **proved invariant** and **not proved**. Include at least one security invariant, one failure path, and one evidence path.

### Done criteria

- [ ] Every focused test passes, or a real environment blocker is recorded without fabricating output.
- [ ] At least three results are tied to exact symbols and assertions.
- [ ] The learner states the local/provider/deployment boundary aloud.
- [ ] Temporary resources are absent or explicitly cleaned.

## Security and failure modes

| Threat or failure | Boundary/control | Failure behavior | Residual risk |
|---|---|---|---|
| Demo overclaim | Claim ladder + exact revision/environment | State “not verified” instead of extrapolating | Audience may still conflate local and production. |
| Secret or personal data on screen | Synthetic account/data; redacted logs; preflight | Abort/clear if sensitive data appears | Screen recording is another data sink. |
| Live provider outage | Deterministic tests and recorded local artifacts | Switch to clearly labeled evidence path | No fabrication of live output. |
| Destructive tool/restore | Use fixtures, exact approval, isolated clean target | Policy denial/guard refusal | Operator error remains possible. |
| Stale evidence | Record SHA, run ID, command, timestamp/environment | Do not apply evidence to a different revision | Docs and runtime may drift. |

Preflight stale revisions, missing artifacts, provider outages, sensitive display data, destructive fixtures and time-boxed fallback transitions before every demonstration.

## Observability and evidence path

```text
correlation ID → authenticated owner/project → typed runtime event → redacted log + durable Run Ledger → metric/OTLP span/UI → evaluation
```

| Evidence | Link or command | Claim supported | Scope/limit |
|---|---|---|---|
| Canonical status | [Implementation evidence](../../../IMPLEMENTATION-EVIDENCE.md) | Separates exists/wired/tested/observed/UI/deployed. | Mutable evidence; inspect revision. |
| Architecture | [Architecture diagrams](../../../ARCHITECTURE-DIAGRAMS.md) | Wider component and trust boundaries. | Diagram is not runtime observation. |
| Focused tests | command above | Deterministic contracts and failure paths. | Fixture/local scope. |

Never expose credentials, raw provider exceptions, tool payloads, personal data, or hidden chain-of-thought as “evidence.”

## Lab vs production

| Dimension | Demonstrated in repository/lab | Required or unverified for production |
|---|---|---|
| Deployment | Local/test paths and artifacts. | Public ingress, multi-host operation, SLO/on-call; public deployment is deferred. |
| Data and scale | Bounded fixtures and local persistent data. | Capacity, retention, sustained load and multi-replica behavior. |
| Providers | Deterministic/mock/local dependencies as explicitly linked. | Final external providers were not verified. |
| Security/operations | Tested ownership, validation, policy and redaction controls. | Independent audit, rotation, production alerting and incident drills. |

The defensible product is an evidence-rich local Agent Reliability Workbench. Exact CI revision/run evidence and local OTEL/DR observations are maintained in [implementation evidence](../../../IMPLEMENTATION-EVIDENCE.md), not duplicated here. Public deployment remains deferred. Final external-provider behavior, production traffic, indexed vector serving and SLOs are unverified.

## Interview answer

### 30-second answer

> I frame Archon as an evidence-first local reliability workbench, not a deployed platform. The typed runtime sends every tool—including allowlisted MCP stdio tools—through deterministic policy and exact approvals, persists owner-scoped run evidence, evaluates grounded outputs, and optionally invokes one no-tools verifier child. Auth, SSE, redacted logs, process metrics and OTLP spans make a request inspectable. Compose and a clean restore drill prove local operability. I show source, test, observed artifact and limitation for every claim.

### Deeper follow-ups

- **How do you avoid overclaiming?** Separate existence, wiring, tests, observations, UI and deployment for every claim.
- **Why four proof paths?** Replay, grounding, model review and recorded evaluation answer different questions and run at different times.
- **What if live output fails?** Switch to clearly labeled deterministic tests or recorded artifacts; never fabricate provider output.
- **What remains?** External acceptance, threat/audit work, hosted operations, representative scale and adopted SLO/recovery objectives.

## Self-check

1. What is your strongest architecture claim?
2. What is deliberately not implemented?
3. How do you recover if a live demo fails?
4. How do you prove ownership?
5. Which observation is local only?
6. What production work comes next?

<details>
<summary>Answer guide</summary>

1. Policy/approval and durable evidence are on the live typed runtime path for native and governed MCP tools.
2. Dynamic swarms/generic reflection, public deployment, MCP HTTP/OAuth, production SLOs and indexed production vector serving.
3. Use deterministic focused tests or recorded artifacts, label them accurately, and never invent provider output.
4. Authenticated user IDs are bound into repository/resource lookups; cross-owner tests expect scoped misses.
5. OTEL collector span, Compose smoke, DR timings, benchmark and MCP stdio fixture observations.
6. Threat-model/audit, external-provider acceptance, hosted telemetry/alerts, multi-instance tests, backup schedule/off-site/PITR, public deployment and SLO drills.

</details>

## Further reading

- Canonical concepts: [bounded-delegation](../../concepts/bounded-delegation.md), [mcp](../../concepts/mcp.md), [authentication](../../concepts/authentication.md), [tracing-opentelemetry](../../concepts/tracing-opentelemetry.md), [backup-restore](../../concepts/backup-restore.md), [rto-rpo](../../concepts/rto-rpo.md)
- [Implementation evidence](../../../IMPLEMENTATION-EVIDENCE.md)
- [Architecture diagrams](../../../ARCHITECTURE-DIAGRAMS.md)
- [Next step](../../README.md)

## Done criteria

You can draw startup, request, state and evidence flows; name exact source/test boundaries; run the exercise safely; explain security and failures; and distinguish implemented local evidence from deferred production claims.
