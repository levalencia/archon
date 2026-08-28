# Interview code bookmarks

> **Current-revision boundary:** source and exact test symbols checked for this S8.10 documentation candidate based at `440f08e`. Links target files because line numbers drift; search the exact symbol after opening. Revalidate names after rebases. Candidate documentation is not a final gate result.

## Core request trace

| Order | Exact source bookmark | Why stop here | Exact behavior test bookmark |
|---:|---|---|---|
| 1 | [`backend/app/main.py::create_app`](../../../backend/app/main.py) | App factory, middleware, conditional routers | [`test_health.py::TestHealthEndpoints`](../../../backend/tests/unit/test_health.py) |
| 2 | [`backend/app/main.py::lifespan`](../../../backend/app/main.py) | Startup validation and application-scoped DI | [`test_memory_startup.py::test_startup_rejects_missing_encryption_key_without_leaking_configuration`](../../../backend/tests/unit/test_memory_startup.py) |
| 3 | [`backend/app/routes/chat.py::chat`](../../../backend/app/routes/chat.py) / [`stream.py::chat_stream_real`](../../../backend/app/routes/stream.py) | HTTP/SSE input to runtime construction | [`test_chat.py::TestChatEndpoint`](../../../backend/tests/unit/test_chat.py), [`test_runtime_sse.py`](../../../backend/tests/unit/test_runtime_sse.py) |
| 4 | [`backend/app/runtime/factory.py::RunContext.create`](../../../backend/app/runtime/factory.py) | Immutable owner/run/correlation identity | [`test_runtime_observability.py`](../../../backend/tests/unit/test_runtime_observability.py) |
| 5 | [`backend/app/runtime/factory.py::create_chat_runtime`](../../../backend/app/runtime/factory.py) | Single live policy-aware construction path | [`test_wiring_gaps.py`](../../../backend/tests/unit/test_wiring_gaps.py) |
| 6 | [`backend/app/runtime/engine.py::AgentRuntime.run`](../../../backend/app/runtime/engine.py) | Budgeted model/tool observation loop | [`test_runtime_v2.py::test_typed_tool_round_trip_and_events`](../../../backend/tests/unit/test_runtime_v2.py) |
| 7 | [`backend/app/runtime/engine.py::AgentRuntime._snapshot_provider_tool_calls`](../../../backend/app/runtime/engine.py) | Detach identity/history/execution before yielding | [`test_runtime_policy.py::test_provider_calls_are_snapshotted_before_model_events_can_mutate_them`](../../../backend/tests/unit/test_runtime_policy.py) |
| 8 | [`backend/app/runtime/engine.py::AgentRuntime._prepare_policy_batch`](../../../backend/app/runtime/engine.py) | Validate/authorize a whole native batch first | [`test_runtime_policy.py::test_policy_batch_later_approval_failure_executes_none`](../../../backend/tests/unit/test_runtime_policy.py) |
| 9 | [`backend/app/runtime/engine.py::AgentRuntime._enforce_policy`](../../../backend/app/runtime/engine.py) | Exact-bound allow/ask/deny and fail-closed paths | [`test_runtime_policy.py::test_mismatched_approval_binding_never_executes`](../../../backend/tests/unit/test_runtime_policy.py) |
| 10 | [`backend/app/runtime/engine.py::AgentRuntime._stop`](../../../backend/app/runtime/engine.py) | Emit terminal reason and return typed result | [`test_runtime_v2.py::test_explicit_budget_stop_reasons`](../../../backend/tests/unit/test_runtime_v2.py) |

## Architectural seams

| Topic | Contract → implementation/wiring | Exact test |
|---|---|---|
| Provider/tool abstraction | [`runtime/ports.py::ModelProvider`, `ToolExecutor`, `ToolAuthorizer`](../../../backend/app/runtime/ports.py) → injected by [`create_chat_runtime`](../../../backend/app/runtime/factory.py) | [`test_protocols.py`](../../../backend/tests/unit/test_protocols.py) |
| Tool registry | [`tools/registry.py::SecureToolRegistry.register`, `execute`, `policy_request`](../../../backend/app/tools/registry.py) | [`test_tools.py::TestToolInputValidation`](../../../backend/tests/unit/test_tools.py) |
| Policy | [`security/policy.py::PolicyEngine.evaluate`](../../../backend/app/security/policy.py) → [`default_policy.py::default_policy_engine`](../../../backend/app/security/default_policy.py) | [`test_runtime_policy.py::test_default_policy_is_explicit_and_fail_closed`](../../../backend/tests/unit/test_runtime_policy.py) |
| Durable approval | [`live_approvals.py::DurableApprovalBroker.authorizer`](../../../backend/app/security/live_approvals.py) → [`approval_repository.py::ApprovalRepository`](../../../backend/app/security/approval_repository.py) | [`test_durable_live_approvals.py::test_exact_run_binding_and_concurrent_decision_has_one_winner`](../../../backend/tests/unit/test_durable_live_approvals.py) |
| Runtime events | [`runtime/events.py::AgentEventKind`, `AgentEvent`, `EventSink`](../../../backend/app/runtime/events.py) → [`runtime_events.py::CompositeEventSink.emit`](../../../backend/app/observability/runtime_events.py) | [`test_runtime_observability.py`](../../../backend/tests/unit/test_runtime_observability.py) |
| Durable ledger | [`services/run_ledger.py::safe_event_payload`, `RunRepository.append`](../../../backend/app/services/run_ledger.py) | [`test_run_ledger.py::test_redaction_and_allowlist_leave_no_raw_sensitive_payload`](../../../backend/tests/unit/test_run_ledger.py) |
| Encrypted memory | [`memory/scoped.py::ScopedEncryptedMemoryRepository`](../../../backend/app/memory/scoped.py) | [`test_scoped_encrypted_memory.py::test_two_users_and_projects_are_isolated_and_raw_db_has_no_plaintext`](../../../backend/tests/unit/test_scoped_encrypted_memory.py) |
| Retrieval | [`services/grounded_rag.py::DocumentEvidenceRetriever.retrieve`](../../../backend/app/services/grounded_rag.py) → [`sql_json_vector_store.py::SqlJsonVectorStore.search`](../../../backend/app/services/sql_json_vector_store.py) | [`test_grounded_rag.py::test_tampered_persisted_evidence_is_skipped_before_provider_call`](../../../backend/tests/unit/test_grounded_rag.py) |
| Grounded answer | [`services/grounded_rag.py::GroundedDocumentWorkflow.run`](../../../backend/app/services/grounded_rag.py) | [`test_grounded_rag.py::test_supported_claim_is_answered_with_verified_citation`](../../../backend/tests/unit/test_grounded_rag.py) |
| Recorded evaluation | [`eval/service.py::EvaluationService.evaluate`](../../../backend/app/eval/service.py) | [`test_recorded_evaluations.py::test_scores_good_and_bad_recorded_runs_by_explicit_case_key`](../../../backend/tests/unit/test_recorded_evaluations.py) |
| Circuit breaker | [`security/circuit_breaker.py::CircuitBreaker.call`](../../../backend/app/security/circuit_breaker.py) | [`test_pii_circuit_breaker.py`](../../../backend/tests/security/test_pii_circuit_breaker.py) |
| MCP runtime | [`mcp/runtime.py::MCPRuntimeToolProvider`](../../../backend/app/mcp/runtime.py) | [`test_mcp_runtime.py`](../../../backend/tests/integration/test_mcp_runtime.py) |
| Bounded verifier | [`delegation/service.py::EvidenceVerifierSpecialist.verify`](../../../backend/app/delegation/service.py) | [`test_evidence_verifier.py::test_valid_call_is_isolated_bounded_and_durable`](../../../backend/tests/unit/test_evidence_verifier.py) |
| Authenticated export/share | [`services/run_exports.py::RunExportService`](../../../backend/app/services/run_exports.py) → [`routes/runs.py`, `routes/shares.py`](../../../backend/app/routes/runs.py) | [`test_run_exports.py::test_export_owner_isolation_hash_only_grant_and_revocation`](../../../backend/tests/security/test_run_exports.py) |
| Governed optimization | [`eval/drift.py`, `eval/candidates.py`](../../../backend/app/eval/drift.py) → [`routes/evaluations.py`](../../../backend/app/routes/evaluations.py) | [`test_optimization_candidates.py`](../../../backend/tests/integration/test_optimization_candidates.py) |

## Negative-space bookmarks

The six deliberate omissions have no implementation bookmark to imply. Use [Remaining Deferred Gaps](../../REMAINING-DEFERRED-GAPS.md) for their required architecture and status-changing evidence. In particular, authenticated recipient-bound sharing is not public anonymous sharing, and an approved promotion record is not autonomous production mutation.

## Three interview routes

- **2 minutes:** `create_app` → `create_chat_runtime` → `AgentRuntime.run` → `RunRepository.append`; mention policy and one honest limitation.
- **15 minutes:** add snapshots, policy batch, exact approval, grounded workflow, evaluation, and breaker; show one test for each major claim.
- **45 minutes:** follow all core-request rows and four relevant seams, run focused tests, inspect one ordered event timeline, and finish with local-vs-production gaps.

Use the scripted structure and timing in the [interview track](../tracks/interview-preparation.md). Full explanations remain in modules and concepts; this page is deliberately only an index.
