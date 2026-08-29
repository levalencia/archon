# Runtime stop reasons

> **Generated snapshot boundary:** derived from [`StopReason`](../../../backend/app/runtime/engine.py) at revision `3577b00`. These values describe `AgentRuntime`; specialized grounded/delegated workflows may persist additional textual terminal reasons. Recheck source before treating this as exhaustive.

| Value | Trigger in `AgentRuntime` | Operator/learner interpretation |
|---|---|---|
| `completed` | Provider returns no tool calls | Normal terminal response; quality still requires separate evaluation. |
| `iteration_budget_exhausted` | Loop reaches `max_iterations` | Bounded stop; final synthesis may be attempted within remaining deadline/tokens. |
| `tool_budget_exhausted` | Novel calls would exceed `max_tool_calls` | No over-budget batch member should execute in policy mode. |
| `token_budget_exhausted` | Cumulative provider usage exceeds `max_tokens` | Budget stop, not necessarily provider failure. |
| `time_budget_exhausted` | Absolute runtime deadline expires | Work is bounded; inspect cancellation/cleanup and last event. |
| `policy_denied` | Policy denies, metadata/binding validation fails, or authorization denies | Intentional fail-closed outcome; do not diagnose automatically as outage. |
| `approval_timeout` | Required authorization misses its deadline | The call does not execute; prepared state is cleaned/cancelled. |
| `approval_unavailable` | ASK has no authorizer, broker errors, publication/binding fails, or result is unavailable | Fail closed because safe authorization could not be established. |
| `error` | Unhandled runtime exception | Safe terminal error presence is recorded; raw exception detail is not durable event data. |

## Nearby but distinct statuses

Run rows use `running`, `completed`, `failed`, or `cancelled`. The stop reason and row status are related but are not the same enum. [`GroundedDocumentWorkflow.run`](../../../backend/app/services/grounded_rag.py) records reasons such as `cancelled` and `provider_error`; bounded verifier results have their own typed status/reason codes. Do not force these into `StopReason`.

## Debugging order

1. Read the run row’s status and `stop_reason`.
2. Confirm the last ordered `run_stopped` event in the [event catalog](event-catalog.md).
3. Locate the preceding model/policy/approval/tool event.
4. Check configured [`RuntimeBudget`](../../../backend/app/runtime/engine.py) and the construction path in [`create_chat_runtime`](../../../backend/app/runtime/factory.py).
5. State whether the evidence is unit, integration, local runtime, or deployment evidence.

Focused contracts: [`test_explicit_budget_stop_reasons`](../../../backend/tests/unit/test_runtime_v2.py), [`test_timeout_stop_reason`](../../../backend/tests/unit/test_runtime_v2.py), [`test_policy_deny_is_terminal_and_never_executes`](../../../backend/tests/unit/test_runtime_policy.py), and [`test_authorizer_timeout_is_bounded_and_explicit`](../../../backend/tests/unit/test_runtime_policy.py).
