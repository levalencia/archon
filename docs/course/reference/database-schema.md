# Database schema map

> **Generated snapshot boundary:** manually extracted from SQLAlchemy rows in [`db_store.py`](../../../backend/app/services/db_store.py) and Alembic revisions through head `20260826_08` at Git revision `3577b00`. This is a review aid, not executable DDL. ORM models, migrations, and the schema of a running database are three distinct evidence sources.

## Migration chain

`20260826_01 approval_requests` → `02 memory_facts` → `03 run_ledger` → `04 run_checkpoints` → `05 durable_documents` → `06 durable_evaluations` → `07 run_parent_fk` → `08 mcp_inventory`

See [`backend/alembic/versions`](../../../backend/alembic/versions/20260826_08_mcp_inventory.py). `DatabaseStore.initialize` also calls `Base.metadata.create_all`; that convenience path does not prove a deployed database has applied the Alembic chain.

## Table inventory

| Table / ORM row | Purpose and principal columns | Important boundary |
|---|---|---|
| `users` / `UserRow` | `id`, unique `username`, `email`, `password_hash`, `is_admin` | Password plaintext must never be stored. |
| `api_keys` / `ApiKeyRow` | `id`, unique `key_hash`, `user_id`, `name` | Stores a hash, not the presented key. |
| `conversations` / `ConversationRow` | `id`, `title`, `user_id`, timestamps, active flag | Ownership checks belong in repository/routes. |
| `messages` / `MessageRow` | integer `id`, indexed `conversation_id`, `role`, `content`, timestamp | No database FK is declared here; content can be sensitive. |
| `artifacts` / `ArtifactRow` | conversation/message identity, type/language/content/version | Access must remain conversation/owner scoped. |
| `audit_entries` / `AuditRow` | actor/action/resource/result/security level/correlation | Parameters must be sanitized before persistence. |
| `runs` / `RunRow` | run and scope IDs, parent/fork lineage, provider/model, status, timing, usage, terminal summary, `next_sequence` | Status constrained to running/completed/failed/cancelled; self-FK parent uses `RESTRICT`. |
| `runtime_events` / `RuntimeEventRow` | run/scope IDs, unique `(run_id, sequence)`, kind/version/iteration/redacted payload | FK cascades on run deletion; payload is allowlisted. |
| `run_checkpoints` / `RunCheckpointRow` | source run/sequence, bounded conversation snapshot, policy/memory metadata | Unique owner/source sequence; workspace restoration is explicitly recorded. |
| `fork_drafts` / `ForkDraftRow` | checkpoint/source lineage to unique target conversation | Consumed when the first child run is created. |
| `approval_requests` / `ApprovalRequestRow` | exact run/call/name/hash binding, risks/rule, status and deadlines | No raw arguments; status constrained to pending/approved/denied/expired/cancelled. |
| `memory_scopes` / `MemoryScopeRow` | composite owner/project key, character usage, version | Nonnegative accounting constraints. |
| `memory_facts` / `MemoryFactRow` | fact ID, owner/project, ciphertext, key version, timestamps | Content/provenance are inside ciphertext. |
| `documents` / `DocumentRow` | owner/project metadata, content hash, chunk count/status, embedding capability | Status constrained to processing/ready/failed. |
| `vector_chunks` / `VectorChunkRow` | owner/project/document, content/hash/metadata, `embedding_json` | JSON vector, **not pgvector**; document FK cascades. |
| `eval_runs` / `EvalRunRow` | owner/project, dataset identity/hash, source run IDs, threshold/status/aggregates | Stores safe aggregate metadata; threshold and status constrained. |
| `eval_case_results` / `EvalCaseResultRow` | evaluation/source IDs, case key, pass/score/metrics/checks | Unique case per evaluation; no answers/event payloads. |
| `mcp_servers` / `MCPServerRow` | owner/project/name/profile, stdio transport, enabled/health | Process details belong to deployment profiles, not this table. |
| `mcp_tools` / `MCPToolRow` | server/name, bounded descriptive schema, risk hints, enabled/version | Discovery metadata only; no invocation arguments/results. |

## Relationship sketch

```text
runs 1 ── * runtime_events
runs 1 ── * runs (parent_run_id)
runs 1 ── * run_checkpoints 1 ── * fork_drafts
documents 1 ── * vector_chunks
eval_runs 1 ── * eval_case_results
mcp_servers 1 ── * mcp_tools
```

Other identifiers such as `messages.conversation_id`, `artifacts.conversation_id`, evaluation `source_run_id`, and approval `run_id` are application-level associations unless the current model/migration declares an FK.

## Refresh and verify

From `backend`, inspect `uv run alembic heads` and `uv run alembic current` against a disposable configured database, then compare migration DDL with `Base.metadata`. Never run upgrades against an unknown/shared database for a documentation check. Focused tests: [`test_database.py`](../../../backend/tests/unit/test_database.py), [`test_run_ledger_migration.py`](../../../backend/tests/integration/test_run_ledger_migration.py), [`test_evaluation_migration.py`](../../../backend/tests/integration/test_evaluation_migration.py), and [`test_mcp_inventory_migration.py`](../../../backend/tests/integration/test_mcp_inventory_migration.py).
