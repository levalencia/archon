# Test map

> **Current-revision boundary:** curated from test files present at revision `3577b00`. Test names are exact node bookmarks where shown. This map does not report a mutable total or claim the suite currently passes; run the named command in your environment.

Use the narrowest behavior test first. A unit test proves its bounded contract with its doubles; integration tests add real repository/route boundaries; local smoke evidence adds configured local services. None alone proves public production, scale, or provider quality.

| Capability | Focused tests | What they establish | Not established |
|---|---|---|---|
| Typed runtime and budgets | [`test_runtime_v2.py::test_typed_tool_round_trip_and_events`](../../../backend/tests/unit/test_runtime_v2.py), `::test_explicit_budget_stop_reasons`, `::test_timeout_stop_reason` | Typed round trip, event order, bounded stop reasons | External provider behavior |
| Runtime deadline edges | [`test_runtime_budget_regressions.py`](../../../backend/tests/unit/test_runtime_budget_regressions.py) | Deadline/token/finalization regressions | Universal deadlines outside tested paths |
| Policy and exact binding | [`test_runtime_policy.py::test_policy_deny_is_terminal_and_never_executes`](../../../backend/tests/unit/test_runtime_policy.py), `::test_mismatched_approval_binding_never_executes`, `::test_policy_batch_later_approval_failure_executes_none` | Fail closed, immutable binding, batch atomic-before-execute behavior | Human process quality |
| Durable approvals | [`test_durable_live_approvals.py::test_exact_run_binding_and_concurrent_decision_has_one_winner`](../../../backend/tests/unit/test_durable_live_approvals.py), `::test_database_schema_has_no_raw_arguments` | Cross-process persistence/concurrency, no raw arguments | Multi-region coordination |
| Encrypted scoped memory | [`test_scoped_encrypted_memory.py::test_two_users_and_projects_are_isolated_and_raw_db_has_no_plaintext`](../../../backend/tests/unit/test_scoped_encrypted_memory.py), `::test_restart_decrypts_and_wrong_key_and_tampering_fail_closed` | Scope, ciphertext, restart/tamper behavior | Operational key rotation ceremony |
| Run Ledger | [`test_run_ledger.py::test_concurrent_append_is_unique_contiguous_and_restart_safe`](../../../backend/tests/unit/test_run_ledger.py), `::test_redaction_and_allowlist_leave_no_raw_sensitive_payload`, `::test_finalize_is_idempotent_and_cannot_overwrite_terminal_run` | Sequence, privacy projection, terminal idempotency | WORM/signature or cross-region ordering |
| Replay/fork/compare | [`test_run_replay_api.py`](../../../backend/tests/integration/test_run_replay_api.py), [`test_run_fork_compare.py`](../../../backend/tests/integration/test_run_fork_compare.py), [`test_run_lineage.py`](../../../backend/tests/unit/test_run_lineage.py) | Owner-scoped stored trajectory and lineage | Re-execution or workspace restore |
| Grounded RAG | [`test_grounded_rag.py::test_supported_claim_is_answered_with_verified_citation`](../../../backend/tests/unit/test_grounded_rag.py), `::test_claim_support_is_conservative_about_negation_numbers_and_partial_claims`, `::test_tampered_persisted_evidence_is_skipped_before_provider_call` | Citation and deterministic support controls | Semantic truth or live embedding quality |
| SQL-JSON vectors | [`test_embedding_hardening.py`](../../../backend/tests/unit/test_embedding_hardening.py), [`test_rag.py`](../../../backend/tests/unit/test_rag.py) | Dimension/finite/scoping/search contracts | pgvector or indexed vector scaling |
| Recorded evaluations | [`test_recorded_evaluations.py::test_scores_good_and_bad_recorded_runs_by_explicit_case_key`](../../../backend/tests/unit/test_recorded_evaluations.py), `::test_results_survive_restart_compare_without_runtime_dependencies_and_store_no_raw_data`; [`test_evaluation_fixtures.py`](../../../backend/tests/unit/test_evaluation_fixtures.py) | Fixture identity, deterministic scoring, durable safe results | Broad model-quality benchmark |
| Circuit breaker | [`test_pii_circuit_breaker.py`](../../../backend/tests/security/test_pii_circuit_breaker.py) | state transitions, recovery probe, cancellation behavior | Shared multi-process breaker state |
| Rate limiting | [`test_rate_limiter.py`](../../../backend/tests/unit/test_rate_limiter.py), [`test_route_rate_limits.py`](../../../backend/tests/integration/test_route_rate_limits.py) | local/Redis and route admission contracts | Distributed capacity beyond test setup |
| Fallback | [`test_fallback_wire.py`](../../../backend/tests/unit/test_fallback_wire.py) | primary/secondary selection and wiring | Typed capability parity |
| MCP | [`test_mcp_runtime.py`](../../../backend/tests/integration/test_mcp_runtime.py), [`test_mcp_inventory.py`](../../../backend/tests/integration/test_mcp_inventory.py), [`test_mcp_stdio.py`](../../../backend/tests/integration/test_mcp_stdio.py) | bounded discovery/inventory/runtime paths | Arbitrary server safety or network transports |
| Verifier delegation | [`test_evidence_verifier.py::test_valid_call_is_isolated_bounded_and_durable`](../../../backend/tests/unit/test_evidence_verifier.py), [`test_verifier_benefit.py`](../../../backend/tests/integration/test_verifier_benefit.py) | one evidence-only bounded child and measured fixture | Dynamic swarm or generic reflection |
| Observability | [`test_runtime_observability.py`](../../../backend/tests/unit/test_runtime_observability.py), [`test_otel_tracing_wire.py::test_otel_exporter_receives_spans_when_wired`](../../../backend/tests/unit/test_otel_tracing_wire.py), [`test_operational_log_privacy.py`](../../../backend/tests/unit/test_operational_log_privacy.py) | event/log/span wiring and privacy | Collector durability/SLO |
| Health and startup | [`test_health.py`](../../../backend/tests/unit/test_health.py), [`test_memory_startup.py`](../../../backend/tests/unit/test_memory_startup.py) | liveness/readiness and fail-closed configuration | Orchestrator behavior |
| Local deployment/DR | [`test_local_deployment.py`](../../../backend/tests/unit/test_local_deployment.py), [`test_local_dr.py`](../../../backend/tests/unit/test_local_dr.py) | manifests/scripts contain tested safeguards | Actual restore unless smoke was executed; public production |
| Sandbox | [`test_docker_sandbox.py::test_fixed_docker_argv_has_all_boundaries_and_no_content`](../../../backend/tests/unit/test_docker_sandbox.py), `::test_enabled_startup_fails_closed_on_preflight` | fixed execution boundary and fail-closed startup | Host-independent isolation guarantee |

## Running a bookmark

```bash
cd backend
uv run pytest -q tests/unit/test_runtime_v2.py::test_explicit_budget_stop_reasons
```

Record revision, Python/dependency environment, command, exit status, and relevant output. Do not put credentials in test output or workshop artifacts.
