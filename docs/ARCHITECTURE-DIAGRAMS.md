# Archon Architecture Diagrams

These diagrams describe the current evidence-backed system. Historical diagrams that implied pgvector, Azure Blob, Jaeger, dynamic swarms, or host-process sandboxing were removed because those paths were not the verified product.

Skills + Project Instructions and core-table reconciliation are merged to `main`
at `1f71f0e`. No public deployment is claimed.

## 1. Agent Reliability Workbench

```mermaid
flowchart LR
    User --> UI[SvelteKit Workbench]
    UI -->|REST + SSE| API[FastAPI]

    subgraph Control[Agent control plane]
        Runtime[Typed AgentRuntime]
        Policy[Rule policy engine]
        Approval[Durable approvals]
        Registry[Secure tool registry]
        MCP[Governed MCP stdio + HTTP]
        Sandbox[Optional Docker sandbox]
    end

    API --> Runtime
    Runtime --> Policy
    Policy -->|ALLOW| Registry
    Policy -->|ASK| Approval
    Approval -->|exact approved binding| Registry
    Registry --> MCP
    Registry --> Sandbox

    Runtime --> Ledger[(Run Ledger)]
    Runtime --> Evidence[Grounded evidence]
    Evidence --> Eval[Recorded-run evaluation]
    Ledger --> UI
    Eval --> UI
```

The primary lifecycle is:

```text
Policy → Run → Approval → Tool → Evidence → Evaluation
```

## 2. Tool-call policy and approval sequence

```mermaid
sequenceDiagram
    participant U as User
    participant UI as Workbench
    participant R as AgentRuntime
    participant P as PolicyEngine
    participant A as ApprovalRepository
    participant T as SecureToolRegistry
    participant L as RunLedger

    U->>UI: send message
    UI->>R: chat / stream
    R->>L: RUN_STARTED
    R->>P: tool name + risks + resources
    P-->>R: ALLOW / ASK / DENY
    R->>L: POLICY_DECIDED

    alt ASK
        R->>A: reserve exact user/run/call/name/args hash
        R->>L: APPROVAL_REQUIRED
        UI->>A: approve or deny
        A-->>R: one-shot exact decision
        R->>L: APPROVAL_DECIDED
    end

    alt allowed or approved
        R->>T: execute immutable bound call
        T-->>R: bounded result
        R->>L: TOOL_CALL_COMPLETED
    else denied/unavailable
        R->>L: TOOL_DENIED + terminal stop
    end

    R-->>UI: answer + inspectable evidence
```

Unknown metadata and unavailable authorizers fail closed. Approval does not authorize a different tool name, call ID, or argument hash.

## 3. Durable run and evaluation data

```mermaid
flowchart TD
    Chat[Sync/SSE chat] --> Run[(runs)]
    Chat --> Events[(runtime_events)]
    Events --> Replay[Stored-only replay]
    Run --> Fork[Fork checkpoint + lineage]
    Run --> Compare[Run comparison]

    Documents[(documents)] --> Chunks[(vector_chunks JSON embeddings)]
    Chunks --> Search[Cosine in Python]
    Search --> Claims[Claim/evidence verification]
    Claims --> Grounded[Grounded answer + citations]
    Grounded --> Run

    Run --> Eval[(evaluation_runs/results)]
    Fixture[Versioned eval fixture] --> Eval
    Eval --> Report[History/report/compare UI]
```

`vector_chunks` stores JSON embeddings. This is `sql-json-cosine`, not pgvector.

## 4. Bounded verifier child

```mermaid
flowchart LR
    Parent[Grounded parent run] --> Select[Supported candidate claims]
    Select --> Contract[Evidence-only child request]
    Contract --> Child[Verifier child run]
    Child --> Verdict[Strict structured verdicts]
    Verdict --> Filter[Fail-closed claim filter]
    Filter --> Answer[Final grounded answer]

    Budget[Input/output/time/retry budget] --> Child
    NoTools[Empty tool set] --> Child
    Parent -->|parent_run_id| Child
    Child --> Ledger[(Run Ledger)]
```

The child receives selected claims/evidence only, has no tools, and cannot approve a claim when output is malformed, timed out, failed, or over budget.

## 5. Governed MCP

```mermaid
flowchart LR
    Profiles[Allowlisted stdio / HTTP profiles] --> Client[Governed MCP clients]
    Client --> Inventory[(Owner/project server + tool inventory)]
    Inventory --> Enable[Per-tool enablement]
    Enable --> Adapter[Runtime tool adapter]
    Adapter --> Policy[Existing policy + approval]
    Policy --> Client
    Client --> Ledger[(Policy/tool events)]
    Inventory --> UI[Skills & Integrations UI]
```

Commands, arguments, environment variables, and secrets are not user-controlled server records. Profile changes invalidate stale inventory; tool schema and enabled state are rechecked immediately before execution.

## 6. Skills, instructions, and exact context provenance

```mermaid
flowchart LR
    Request[Owner + project + request] --> Prepare[Shared sync/SSE context preparation]
    Snapshots[(Approved instruction snapshots)] --> Prepare
    Bindings[(Exact project skill bindings)] --> Prepare
    Bundled[Ten bundled skills] --> Bindings
    Native[Native descriptors] --> Discover[Metadata-first discovery]
    MCP2[Governed stdio/HTTP MCP descriptors] --> Discover
    GodMode[Optional metadata-only GodMode] -.-> Discover
    Discover --> Filter[Project preference + policy visibility]
    Filter --> Prepare
    Prepare --> Provider[Model provider]
    Prepare --> Context[(Run Ledger effective-context snapshot)]
```

Instructions and skills provide context, never authority. Discovery returns
bounded metadata; execution still requires the normal policy/approval path.
The Run Ledger stores exact revision IDs, ordering, reasons, capability IDs and
schema hashes—not raw instruction/skill bodies or hidden reasoning.

## 7. Verified local deployment

```mermaid
flowchart TB
    Browser -->|127.0.0.1: configurable| Gateway[nginx-unprivileged
read-only]
    Gateway --> Frontend[SvelteKit adapter-node
non-root]
    Gateway --> Backend[FastAPI + Alembic
non-root/read-only
linux/amd64]

    Backend --> Postgres[(PostgreSQL 16
internal only)]
    Backend --> Redis[(Redis 7
internal only)]
    Backend -->|OTLP gRPC| Collector[OTEL Collector
internal only]

    Postgres --> Volume[(Named volume)]
    Collector --> Debug[Local debug exporter]
```

The backend defaults to `linux/amd64` in this target because the ARM image reproduced a native `cryptography` SIGILL on the verified Mac. All referenced images are pinned by digest. Only the gateway publishes a loopback port.

## 8. Backup and clean restore

```mermaid
sequenceDiagram
    participant S as Source Compose project
    participant P as Source PostgreSQL
    participant B as Backup scripts
    participant D as Fresh destination project
    participant V as Verification

    S->>P: create user/conversation/run/document/approval
    B->>P: pg_dump custom format
    B->>B: chmod 0600 + SHA-256 + metadata
    S->>S: down --volumes
    D->>D: start fresh PostgreSQL/Redis/OTEL
    B->>D: verify checksum + reject non-empty target + pg_restore
    D->>D: start backend/frontend/gateway
    V->>D: login + API ID checks + SQL count/hash checks
    V->>V: record RTO/RPO and cleanup
```

## 9. Trust boundaries

```mermaid
flowchart TD
    External[User/provider/MCP data] --> Validate[Typed validation + bounds]
    Validate --> Redact[PII/secret persistence redaction]
    Redact --> Persist[(Owner/project-scoped storage)]

    External --> Policy[Risk/resource policy]
    Policy --> Approval[Exact approval boundary]
    Approval --> Execution[Registry or isolated Docker]

    Execution --> Events[Allowlisted/redacted events]
    Events --> Persist
    Persist --> UI[Authenticated evidence UI]
```

Local Docker, the host Docker daemon, the memory master key, and the env file remain trusted operational boundaries. A local smoke does not prove resistance to every container-runtime or host compromise.
