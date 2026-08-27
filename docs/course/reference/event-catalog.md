# Runtime event catalog

> **Generated snapshot boundary:** derived from [`AgentEventKind`](../../../backend/app/runtime/events.py) and the durable [`_SAFE_FIELDS`](../../../backend/app/services/run_ledger.py) allowlist at revision `3577b00`, schema version `1`. In-memory/SSE payloads may contain transient fields that the ledger deliberately drops. Source code is authoritative.

Every event has `kind`, `iteration`, `data`, and token `usage` in memory. A durable event additionally has run/project/conversation/correlation identity, monotonic `sequence`, `event_at`, and `schema_version`. `safe_event_payload` allowlists and redacts fields; text, raw arguments, raw outputs, exception messages, and chain-of-thought are not durable replay data.

| Kind | Meaning | Durable allowed fields |
|---|---|---|
| `run_started` | Runtime/workflow accepted a run identity | `safe` |
| `iteration_started` | A model-loop iteration began | none |
| `model_response` | Provider returned a typed response | `provider_stop_reason` |
| `model_progress` | Text accompanied tool calls and is non-final progress | none |
| `text_delta` | Text is available to a streaming adapter | none |
| `tool_call_requested` | A native call was captured before execution | `id`, `name`, `arguments_hash` |
| `policy_decided` | Policy returned allow/ask/deny metadata | `id`, `name`, `arguments_hash`, `risk_classes`, `matched_rule_id`, `action`, `reason_code` |
| `approval_required` | An exact-bound ASK request awaits a decision | `id`, `name`, `arguments_hash`, `risk_classes`, `matched_rule_id` |
| `approval_decided` | Bound authorization completed | `id`, `name`, `arguments_hash`, `approved`, `reason_code` |
| `tool_denied` | A tool was blocked | `id`, `name`, `arguments_hash`, `action`, `reason_code`, `status` |
| `tool_call_completed` | Tool execution produced success/error metadata | `id`, `name`, `arguments_hash`, `output_hash`, `output_size`, `status` |
| `tool_progress` | Chunk position for a large tool result | `id`, `name`, `status`, `offset`, `total` |
| `evidence_retrieved` | Grounded workflow selected bounded evidence | `evidence_ids`, `document_ids`, `chunk_ids`, `content_hashes`, `scores`, `evidence_count` |
| `claim_verified` | Deterministic checks classified claims | `claim_hashes`, `unsupported_hashes`, `cited_evidence_ids`, `supported_count`, `unsupported_count` |
| `grounded_answer` | Workflow finalized supported claims/citations | `answer_hash`, `citation_ids`, `supported_count`, `unsupported_count` |
| `delegation_requested` | One bounded verifier child was requested | child/parent IDs, owner/project, policy, claim/evidence IDs and hashes, counts, status/reason, input/output tokens |
| `delegation_completed` | The bounded verifier child finished | child/parent IDs, claim/evidence IDs/hashes, counts, supported/rejected/escalated counts, status/reasons, token totals |
| `run_stopped` | Terminal reason and safe error presence | `reason`, boolean `error` |

## Ordering and interpretation

- `sequence` is allocated by [`RunRepository.append`](../../../backend/app/services/run_ledger.py), not by wall-clock sorting.
- Terminal ledger status is frozen; appends after terminal state are rejected.
- An event proves the recorded boundary occurred under that revision/configuration. It does not prove model quality, external side effects, production scale, or that omitted sensitive payloads can be reconstructed.
- `model_progress` and tool-error observations are ReAct feedback, not proof of generic self-reflection.

## Focused tests

- [`test_redaction_and_allowlist_leave_no_raw_sensitive_payload`](../../../backend/tests/unit/test_run_ledger.py)
- [`test_concurrent_append_is_unique_contiguous_and_restart_safe`](../../../backend/tests/unit/test_run_ledger.py)
- [`test_policy_events_never_serialize_raw_arguments_or_output`](../../../backend/tests/unit/test_runtime_policy.py)
- [`test_delegation_event_payload_drops_text_quotes_context_and_secrets`](../../../backend/tests/unit/test_delegation_contract.py)
