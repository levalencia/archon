# Async Python

## Definition

A coroutine yields control while waiting for I/O. `await` enables concurrency; it does not make CPU work parallel, and cancellation does not undo an external side effect.

```mermaid
sequenceDiagram
  participant R as Runtime coroutine
  participant Loop as Event loop
  participant P as Provider/tool/DB
  R->>P: await operation
  R-->>Loop: yield control
  P-->>R: result / exception / cancellation
```

## Archon practice

`ModelProvider.complete`, `ToolExecutor.execute`, `ToolAuthorizer.authorize`, and `EventSink.emit` are async ports. `AgentRuntime._within_deadline` bounds waits; the registry uses `asyncio.wait_for`, moving synchronous handlers to an executor. `DurableApprovalBroker.wait_for_decision` polls asynchronously and persists cancellation.

Inspect [`runtime/ports.py`](../../../backend/app/runtime/ports.py), [`AgentRuntime`](../../../backend/app/runtime/engine.py), [`SecureToolRegistry.execute`](../../../backend/app/tools/registry.py), and [`DurableApprovalBroker`](../../../backend/app/security/live_approvals.py). Tests: [`test_runtime_budget_regressions.py`](../../../backend/tests/unit/test_runtime_budget_regressions.py), [`test_tools.py`](../../../backend/tests/unit/test_tools.py), and [`test_durable_live_approvals.py`](../../../backend/tests/unit/test_durable_live_approvals.py).

## Failure rules

Propagate `CancelledError` after cleanup; use monotonic clocks for durations; bound network/tool waits; never assume timeout rolled back work. Snapshot mutable inputs before yielding to an untrusted collaborator. Async improves utilization, not correctness by itself.
