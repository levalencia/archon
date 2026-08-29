# Workshop exercises

> Run only in a disposable local worktree/data environment. Record revision, command, observation, source, test, limitation, and cleanup using the [student guide](student-guide.md). These tasks link to canonical modules for explanations.

## E1: Lifecycle map

Read [module 00](../modules/00-agent-anatomy/README.md) and [`AgentRuntime.run`](../../../backend/app/runtime/engine.py). Draw input → model → optional policy/approval/tool → observation → terminal result, marking deterministic/model/external boundaries. Add `run_started`, one intermediate event, and `run_stopped` from the [event catalog](../reference/event-catalog.md).

**Done:** every arrow has an owner; one failure path and one non-claim are present.

## E2: Dependency trace

Read [module 01](../modules/01-python-architecture/README.md). Trace [`create_chat_runtime`](../../../backend/app/runtime/factory.py) constructor arguments to the Protocols in [`runtime/ports.py`](../../../backend/app/runtime/ports.py). Identify one concrete provider, tool executor, event sink, and authorizer without claiming inheritance where composition is used.

```bash
cd backend
uv run pytest -q tests/unit/test_protocols.py tests/unit/test_wiring_gaps.py
```

**Done:** diagram arrows point from consumer to contract/injected collaborator; actual result and test scope are recorded.

## E3: Stop-reason matrix

Read [modules 02](../modules/02-typed-runtime/README.md) and [03](../modules/03-react-loop/README.md). Predict all nine [stop reasons](../reference/stop-reasons.md), then run:

```bash
cd backend
uv run pytest -q \
  tests/unit/test_runtime_v2.py::test_explicit_budget_stop_reasons \
  tests/unit/test_runtime_v2.py::test_timeout_stop_reason
```

Annotate which branches may attempt final synthesis and why tool-error feedback is not generic self-reflection.

**Done:** prediction/result differences and one unproved property are documented.

## E4: Policy probe

Read [modules 04](../modules/04-tools-and-schemas/README.md) and [05](../modules/05-policy-and-approvals/README.md). Build a table for ALLOW, ASK-approved, ASK-timeout, DENY, and mismatched binding: expected execution, events, and stop reason.

```bash
cd backend
uv run pytest -q \
  tests/unit/test_runtime_policy.py::test_allow_orders_policy_event_before_execution_and_preserves_native_id \
  tests/unit/test_runtime_policy.py::test_mismatched_approval_binding_never_executes \
  tests/unit/test_runtime_policy.py::test_policy_deny_is_terminal_and_never_executes
```

**Done:** table names tool-call ID, canonical name, and arguments hash as the exact binding; no raw secret appears.

## E5: Context boundary

Read [module 06](../modules/06-context-and-memory/README.md) and the [`MemoryFactRow`](../../../backend/app/services/db_store.py) schema. Classify sample data as request-local, conversation message, encrypted memory fact, safe ledger metadata, or forbidden. Inspect—not copy—the ciphertext assertion:

```bash
cd backend
uv run pytest -q tests/unit/test_scoped_encrypted_memory.py::test_two_users_and_projects_are_isolated_and_raw_db_has_no_plaintext
```

**Done:** artifact shows owner/project, lifetime, encryption/redaction, deletion/export, and residual risks.

## E6: Evidence timeline

Read [module 07](../modules/07-run-ledger/README.md). From test source or a safe instructor-provided local run, construct an ordered timeline with sequence, kind, safe payload purpose, and terminal state.

```bash
cd backend
uv run pytest -q \
  tests/unit/test_run_ledger.py::test_concurrent_append_is_unique_contiguous_and_restart_safe \
  tests/unit/test_run_ledger.py::test_redaction_and_allowlist_leave_no_raw_sensitive_payload
```

**Done:** distinguish event sequence from timestamps; state that replay/compare are stored-only and fork restores no workspace.

## E7: Grounded evaluation

Read [modules 08](../modules/08-rag-grounding/README.md) and [09](../modules/09-evaluation-harness/README.md). Trace one supported and one unsupported claim through retrieval, citation, deterministic verification, events, and recorded-run scoring.

```bash
cd backend
uv run pytest -q \
  tests/unit/test_grounded_rag.py::test_supported_claim_is_answered_with_verified_citation \
  tests/unit/test_recorded_evaluations.py::test_scores_good_and_bad_recorded_runs_by_explicit_case_key
```

**Done:** explain SQL-JSON/Python cosine, fixture identity, and why neither score proves truth or broad model quality.

## E8: Reliability capstone

Read [module 10](../modules/10-resilience/README.md). Choose one controlled failure: breaker transition, limiter rejection, cancellation, timeout, fallback, or duplicate finalization. Predict the control and evidence, run a focused test from the [test map](../reference/test-map.md), then deliver a 15-minute walkthrough using [interview preparation](../tracks/interview-preparation.md).

**Artifact:** architecture trace, actual command/output summary, exact source/test bookmarks, incident-style timeline, trade-off, production gaps, and cleanup.

**Done:** score at least 3 in every [rubric](capstone-rubric.md) dimension; a partial or failed run is acceptable when reported honestly with useful evidence.
