# Interview preparation

> **Track status:** draft; validate against the current branch before an interview
> **Rule:** every claim needs a source symbol, behavior test, evidence scope, and limitation

This page is a speaking route. Definitions remain canonical in the [concept pages](../concept-map.md); exact implementation anchors live in [code bookmarks](../reference/code-bookmarks.md).

## The answer spine

Use **problem → design → request trace → evidence → trade-off → boundary**. Say “the repository demonstrates” rather than “the system guarantees.” The verified deployment target is production-like local Docker Compose, not a public production service.

## 2-minute walkthrough

1. **Problem (15s):** Archon is a local Agent Reliability Workbench for inspecting and governing agent behavior.
2. **Architecture (25s):** `create_app` constructs scoped persistence, tools, policy, approvals, resilience, and observability; `create_chat_runtime` injects them into `AgentRuntime`.
3. **Request (40s):** `AgentRuntime.run` loops over model responses and native tool calls under iteration, token, tool, and wall-clock budgets. Policy evaluates a detached exact binding; `ASK` requires a durable authorization; events record inspectable outcomes.
4. **Evidence (20s):** the Run Ledger persists ordered events; recorded-run evaluation measures fixtures; RAG returns citations and deterministic claim checks.
5. **Trade-off and boundary (20s):** explicit contracts and fail-closed controls improve auditability but add coordination and persistence complexity. Local tests and Compose evidence do not prove public deployment, scale, provider parity, or model quality.

Bookmarks: [`create_app`](../../../backend/app/main.py), [`create_chat_runtime`](../../../backend/app/runtime/factory.py), [`AgentRuntime.run`](../../../backend/app/runtime/engine.py), [`RunRepository`](../../../backend/app/services/run_ledger.py), [`EvaluationService`](../../../backend/app/eval/service.py).

## 15-minute architecture walkthrough

| Time | Explain/show | Exact bookmark | Evidence question |
|---:|---|---|---|
| 0–2 | Agent boundary and typed provider/tool ports | [`ModelProvider`, `ToolExecutor`](../../../backend/app/runtime/ports.py); [module 00](../modules/00-agent-anatomy/README.md) | What is deterministic versus model-driven? |
| 2–5 | Runtime loop, budgets, events, terminal outcomes | [`AgentRuntime.run`, `RuntimeBudget`, `StopReason`](../../../backend/app/runtime/engine.py); [`test_explicit_budget_stop_reasons`](../../../backend/tests/unit/test_runtime_v2.py) | Which path terminates the run? |
| 5–7 | Tool schema, policy, exact-bound approval | [`SecureToolRegistry`](../../../backend/app/tools/registry.py); [`AgentRuntime._enforce_policy`](../../../backend/app/runtime/engine.py); [`test_mismatched_approval_binding_never_executes`](../../../backend/tests/unit/test_runtime_policy.py) | Can metadata or arguments change after authorization? |
| 7–9 | Durable ordered events and replay/fork/compare | [`RunRepository.append`](../../../backend/app/services/run_ledger.py); [`test_concurrent_append_is_unique_contiguous_and_restart_safe`](../../../backend/tests/unit/test_run_ledger.py) | Is replay re-execution or historical reconstruction? |
| 9–11 | SQL-JSON retrieval, grounded answer, and recorded evaluation | [`SqlJsonVectorStore.search`](../../../backend/app/services/sql_json_vector_store.py); [`GroundedDocumentWorkflow.run`](../../../backend/app/services/grounded_rag.py); [`EvaluationService.evaluate`](../../../backend/app/eval/service.py) | Why is this not pgvector or model-quality proof? |
| 11–12 | Bounded verifier child and durable lineage | [`EvidenceVerifierSpecialist.verify`](../../../backend/app/delegation/service.py); [module 11](../modules/11-bounded-delegation/README.md) | Which boundary is deterministic and which judgment is model-generated? |
| 12–13 | Governed MCP discovery and invocation | [`MCPRuntime`](../../../backend/app/mcp/runtime.py); [module 12](../modules/12-governed-mcp/README.md) | How do policy and approval still apply to MCP tools? |
| 13–14 | Authentication, SSE, and observability | [`get_current_user`](../../../backend/app/security/auth.py); [`CompositeEventSink.emit`](../../../backend/app/observability/runtime_events.py); [module 13](../modules/13-auth-ui-observability/README.md) | How are owner scope and inspectable evidence preserved? |
| 14–15 | Local operations, DR, and honest limits | [module 14](../modules/14-local-operations/README.md); [implementation evidence](../../IMPLEMENTATION-EVIDENCE.md) | Which claims remain local-only or deferred? |

## 45-minute deep dive

Use the 15-minute route, then add these evidence stops:

1. **Startup and DI (4m):** trace [`lifespan`](../../../backend/app/main.py) and [`create_chat_runtime`](../../../backend/app/runtime/factory.py). Explain Protocol-based composition using [module 01](../modules/01-python-architecture/README.md).
2. **Provider-to-tool trust boundary (6m):** inspect snapshots in [`AgentRuntime._snapshot_provider_tool_calls`](../../../backend/app/runtime/engine.py), policy preparation, and execution in `run`. Read [`test_invalid_later_provider_call_fails_closed_before_any_call_executes`](../../../backend/tests/unit/test_runtime_policy.py).
3. **Approval lifecycle (4m):** follow [`DurableApprovalBroker.authorizer`](../../../backend/app/security/live_approvals.py) and [`ApprovalRepository`](../../../backend/app/security/approval_repository.py). Use [`test_exact_run_binding_and_concurrent_decision_has_one_winner`](../../../backend/tests/unit/test_durable_live_approvals.py).
4. **Evidence ledger (5m):** follow runtime event → [`CompositeEventSink.emit`](../../../backend/app/observability/runtime_events.py) → [`RunRepository.append`](../../../backend/app/services/run_ledger.py) → `/api/runs/{run_id}/events`. Explain sequence allocation, owner scope, redaction, replay, fork, and compare.
5. **Knowledge and evaluation (6m):** trace document ingestion, [`SqlJsonVectorStore`](../../../backend/app/services/sql_json_vector_store.py), [`GroundedDocumentWorkflow`](../../../backend/app/services/grounded_rag.py), and [`EvaluationService`](../../../backend/app/eval/service.py). Keep retrieval, groundedness, faithfulness, citation, and durable post-run evaluation distinct.
6. **Bounded verifier (4m):** show evidence-only child input, model-generated verdict, schema validation, budgets, no-tools isolation, and parent-child lineage using [module 11](../modules/11-bounded-delegation/README.md).
7. **Governed MCP (4m):** trace stdio initialization, inventory normalization, enablement, policy, exact-bound approval, invocation, and sanitized event output using [module 12](../modules/12-governed-mcp/README.md).
8. **Auth and observability (5m):** trace JWT identity and ownership into SSE, safe events, logs, metrics, traces, and Workbench inspection using [module 13](../modules/13-auth-ui-observability/README.md).
9. **Failure and recovery (4m):** contrast retry, idempotency, deadline, breaker, fallback, rate limiting, readiness, migration, backup, and restore using [modules 10](../modules/10-resilience/README.md) and [14](../modules/14-local-operations/README.md).
10. **Close honestly (3m):** use [module 15](../modules/15-capstone/README.md) to state measured evidence and limits: local-only deployment, mock final provider/embeddings, no pgvector, and no generic self-reflection.

## Likely follow-ups

- **Why Protocols and DI?** Replace provider, executor, sink, and authorizer without making the control loop depend on concrete adapters; tests can inject bounded doubles.
- **Is error feedback self-reflection?** No. Tool-error feedback allows another ReAct step; deterministic claim verification, one bounded verifier child, and post-run evaluation are separate mechanisms.
- **Why persist events?** To inspect ordered behavior, compare runs, and evaluate recorded inputs without relying on hidden chain-of-thought.
- **Biggest risk?** A mutable or mismatched tool identity crossing authorization. The runtime snapshots and revalidates identifiers and argument hashes, then fails closed.
- **What would production require?** Direct evidence for deployment, SLOs, capacity, backup cadence, restore drills, secret rotation, provider parity, incident response, and external traffic.

## Practice contract

For each duration, record yourself, stay within ±10%, cite at least three exact symbols and two behavior tests, state one trade-off and two unverified boundaries, and correct uncertainty rather than inventing evidence. Use the [capstone rubric](../workshops/capstone-rubric.md) for scoring.
