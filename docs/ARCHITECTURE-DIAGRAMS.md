# Archon — Architecture Diagrams

Visual documentation for understanding the system before writing code.
All diagrams use Mermaid for version control and GitHub rendering.

---

## 1. System Architecture (High-Level)

How all layers connect from user to infrastructure.

```mermaid
graph TB
    subgraph Frontend["Frontend - SvelteKit"]
        CHAT[Chat UI with SSE Streaming]
        TRACE[Trace Viewer - OTel Spans]
        DOCS[Document Upload and RAG Explorer]
        ADMIN[Admin Panel - Metrics and Audit]
    end

    subgraph Gateway["API Gateway - FastAPI"]
        AUTH[JWT and API Key Auth]
        RATE[Redis Rate Limiter]
        CORS[CORS and CSRF and Input Sanitization]
        CORR[Correlation ID Injection]
    end

    subgraph Orchestrator["Agent Orchestrator"]
        COORD[Coordinator Agent - ReAct Loop]
        PLAN[Planner Agent]
        RET[Retriever Agent]
        VAL[Validator Agent]
        SYNTH[Synthesizer Agent]
    end

    subgraph CrossCutting["Cross-Cutting Concerns"]
        CB[Circuit Breaker - per provider]
        TOOLS[Secure Tool Registry]
        MEM[Tiered Memory Manager]
        AUDIT[Structured Audit Logger]
    end

    subgraph Infra["Infrastructure"]
        PG[(PostgreSQL + pgvector)]
        REDIS[(Redis)]
        BLOB[(Azure Blob Storage)]
        OTEL[OpenTelemetry Collector]
        JAEGER[Jaeger - traces]
        PROM[Prometheus - metrics]
    end

    Frontend -->|REST and SSE| Gateway
    Gateway --> Orchestrator
    Orchestrator --> CrossCutting
    CrossCutting --> Infra

    COORD --> PLAN
    COORD --> RET
    COORD --> VAL
    COORD --> SYNTH

    TOOLS --> AUDIT
    MEM --> PG
    MEM --> REDIS
    CB --> REDIS
    RATE --> REDIS
    RET --> PG
    AUDIT --> PG
    OTEL --> JAEGER
    OTEL --> PROM

    style Frontend fill:#1a1a2e,stroke:#58a6ff,color:#c9d1d9
    style Gateway fill:#1a1a2e,stroke:#f39c12,color:#c9d1d9
    style Orchestrator fill:#1a1a2e,stroke:#e94560,color:#c9d1d9
    style CrossCutting fill:#1a1a2e,stroke:#2ecc71,color:#c9d1d9
    style Infra fill:#1a1a2e,stroke:#9b59b6,color:#c9d1d9
```

---

## 2. ReAct Reasoning Loop (Sequence Diagram)

How a single user message flows through the Coordinator agent.

```mermaid
sequenceDiagram
    participant U as User
    participant FE as Svelte Frontend
    participant API as FastAPI Gateway
    participant CO as Coordinator Agent
    participant PL as Planner Agent
    participant RE as Retriever Agent
    participant VA as Validator Agent
    participant SY as Synthesizer Agent
    participant LLM as LLM Provider
    participant DB as PostgreSQL
    participant RED as Redis

    U->>FE: Send message
    FE->>API: POST /api/chat/stream
    API->>API: Auth + Rate Limit + Correlation ID
    API->>CO: dispatch(message, conversation_id)
    
    Note over CO: ReAct Loop begins
    
    CO->>LLM: Think - what should I do?
    LLM-->>CO: Plan - decompose query into sub-tasks
    
    CO->>PL: decompose(query)
    PL->>LLM: Break into sub-questions
    LLM-->>PL: sub_tasks list
    PL-->>CO: sub_tasks

    loop For each sub-task
        CO->>RE: retrieve(sub_task)
        RE->>DB: pgvector similarity search
        DB-->>RE: relevant chunks
        RE->>LLM: rerank results
        LLM-->>RE: ranked results
        RE-->>CO: sources with scores
    end

    CO->>VA: validate(sources, query)
    VA->>VA: PII detection scan
    VA->>VA: Fact consistency check
    VA->>LLM: Are sources sufficient?
    
    alt Sources insufficient
        LLM-->>VA: Need more data
        VA-->>CO: RETRY with feedback
        Note over CO: Loop back to Retriever
    else Sources valid
        LLM-->>VA: Sources OK
        VA-->>CO: APPROVED
    end

    CO->>SY: synthesize(query, validated_sources)
    SY->>LLM: Generate answer with citations
    LLM-->>SY: answer + citations + confidence
    SY-->>CO: final_response

    Note over CO: ReAct Loop ends

    CO->>DB: Store conversation + audit trail
    CO-->>API: stream response via SSE
    API-->>FE: SSE tokens + trace events
    FE-->>U: Rendered answer with sources
```

---

## 3. Class Diagram (Core Domain Model)

The Protocol-based architecture with dependency injection.

```mermaid
classDiagram
    class LLMClient {
        <<Protocol>>
        +chat(messages, max_tokens) str
    }

    class MemoryStore {
        <<Protocol>>
        +store(conversation_id, role, content)
        +retrieve(conversation_id, limit) list
    }

    class ToolExecutor {
        <<Protocol>>
        +execute(tool_name, parameters) dict
    }

    class AuditLog {
        <<Protocol>>
        +log(agent_id, action, resource, result)
        +get_recent(limit) list
        +search(agent_id, correlation_id) list
    }

    class PermissionChecker {
        <<Protocol>>
        +check(agent_id, resource, action) bool
    }

    class GuardrailEngine {
        <<Protocol>>
        +check_input(text) GuardrailResult
        +check_output(text) GuardrailResult
    }

    class PIIDetector {
        <<Protocol>>
        +detect(text) list of PIIEntity
        +redact(text) str
    }

    class ProductionAgent {
        -llm: LLMClient
        -memory: MemoryStore
        -tools: ToolExecutor
        -audit: AuditLog
        -permissions: PermissionChecker
        -guardrails: GuardrailEngine
        -max_iterations: int
        -token_budget: int
        +run(user_input, conversation_id) AgentResult
        -_react_loop(messages) str
        -_parse_tool_call(response) ToolCall
    }

    class CoordinatorAgent {
        -planner: PlannerAgent
        -retriever: RetrieverAgent
        -validator: ValidatorAgent
        -synthesizer: SynthesizerAgent
        -circuit_breaker: CircuitBreaker
        +orchestrate(query, context) OrchestratorResult
    }

    class FoundryAdapter {
        -api_key: str
        -base_url: str
        -model: str
        +chat(messages, max_tokens) str
    }

    class OpenAIAdapter {
        -api_key: str
        -model: str
        +chat(messages, max_tokens) str
    }

    class MockLLM {
        -responses: list
        +call_history: list
        +chat(messages, max_tokens) str
    }

    class EncryptedMemoryStore {
        -master_key: bytes
        -db_path: str
        +store(conversation_id, role, content)
        +retrieve(conversation_id, limit) list
        -_derive_key(conversation_id) bytes
    }

    class TieredMemoryManager {
        -hot: Redis
        -warm: PostgreSQL
        -cold: PostgreSQL compressed
        +store(conversation_id, role, content)
        +retrieve(conversation_id, limit) list
        +compress_context(messages, token_limit) list
    }

    class SecureToolRegistry {
        -permissions: PermissionChecker
        -audit: AuditLog
        -timeout: int
        +register(name, function, permissions, schema)
        +execute(tool_name, parameters) dict
    }

    class CircuitBreaker {
        -failure_threshold: int
        -recovery_timeout: int
        -state: CLOSED or OPEN or HALF_OPEN
        +call(func, args) result
        +get_stats() CircuitBreakerStats
    }

    class DistributedRateLimiter {
        -redis: Redis
        -prefix: str
        +check_rate_limit(identifier, limit, window) bool
    }

    LLMClient <|.. FoundryAdapter
    LLMClient <|.. OpenAIAdapter
    LLMClient <|.. MockLLM
    MemoryStore <|.. EncryptedMemoryStore
    MemoryStore <|.. TieredMemoryManager
    ToolExecutor <|.. SecureToolRegistry

    ProductionAgent --> LLMClient
    ProductionAgent --> MemoryStore
    ProductionAgent --> ToolExecutor
    ProductionAgent --> AuditLog
    ProductionAgent --> PermissionChecker
    ProductionAgent --> GuardrailEngine

    CoordinatorAgent --> ProductionAgent
    CoordinatorAgent --> CircuitBreaker
    SecureToolRegistry --> PermissionChecker
    SecureToolRegistry --> AuditLog
    DistributedRateLimiter --> Redis
```

---

## 4. Request Flow (API to Response)

How a single HTTP request traverses all middleware layers.

```mermaid
flowchart TD
    REQ[HTTP Request] --> CORS{CORS Check}
    CORS -->|Pass| CID[Inject Correlation ID]
    CID --> AUTH{JWT or API Key Valid?}
    AUTH -->|No| R401[401 Unauthorized]
    AUTH -->|Yes| RATE{Rate Limit Check}
    RATE -->|Exceeded| R429[429 Too Many Requests]
    RATE -->|OK| SANITIZE[Sanitize Input]
    SANITIZE --> GUARD_IN{Input Guardrail}
    GUARD_IN -->|Blocked| R400[400 Blocked by Guardrail]
    GUARD_IN -->|Pass| AGENT[Agent Orchestrator]
    
    AGENT --> REACT{ReAct Loop}
    REACT --> TOOL{Tool Call?}
    TOOL -->|Yes| PERM{Permission Check}
    PERM -->|Denied| AUDIT_DENY[Audit: Permission Denied]
    AUDIT_DENY --> REACT
    PERM -->|Granted| EXEC[Execute Tool with Timeout]
    EXEC --> AUDIT_OK[Audit: Tool Executed]
    AUDIT_OK --> REACT
    TOOL -->|No - Final Answer| GUARD_OUT{Output Guardrail}
    
    GUARD_OUT -->|PII Detected| REDACT[Redact PII]
    REDACT --> STREAM
    GUARD_OUT -->|Clean| STREAM[SSE Stream Response]
    
    STREAM --> STORE[Store in Memory]
    STORE --> TRACE[Emit OTel Trace]
    TRACE --> R200[200 OK - SSE Stream]

    style REQ fill:#1a1a2e,stroke:#58a6ff,color:#c9d1d9
    style R401 fill:#1a1a2e,stroke:#e94560,color:#e94560
    style R429 fill:#1a1a2e,stroke:#f39c12,color:#f39c12
    style R400 fill:#1a1a2e,stroke:#e94560,color:#e94560
    style R200 fill:#1a1a2e,stroke:#2ecc71,color:#2ecc71
```

---

## 5. Multi-Agent Coordination

How the Coordinator delegates to specialist agents.

```mermaid
flowchart LR
    subgraph Coordinator["Coordinator Agent"]
        DECIDE{Decide next action}
    end

    subgraph Specialists["Specialist Agents"]
        PLAN[Planner - query decomposition]
        RETRIEVE[Retriever - RAG + web search]
        VALIDATE[Validator - fact check + PII + guardrails]
        SYNTHESIZE[Synthesizer - answer + citations]
    end

    DECIDE -->|Complex query| PLAN
    PLAN -->|Sub-tasks| DECIDE

    DECIDE -->|Need data| RETRIEVE
    RETRIEVE -->|Sources| DECIDE

    DECIDE -->|Check quality| VALIDATE
    VALIDATE -->|Approved or Retry| DECIDE

    DECIDE -->|Sources ready| SYNTHESIZE
    SYNTHESIZE -->|Final answer| DECIDE

    style Coordinator fill:#1a1a2e,stroke:#e94560,color:#c9d1d9
    style Specialists fill:#1a1a2e,stroke:#58a6ff,color:#c9d1d9
```

---

## 6. Memory Tiers

How conversation memory flows between hot, warm, and cold storage.

```mermaid
flowchart TB
    MSG[New Message] --> HOT[Hot Tier - Redis]
    HOT -->|Last 20 messages| CONTEXT[Context Window]
    
    HOT -->|After 1 hour or 50 messages| WARM[Warm Tier - PostgreSQL]
    WARM -->|Encrypted with per-conversation key| STORE[(Encrypted Storage)]
    
    WARM -->|After 7 days| COLD[Cold Tier - Compressed PostgreSQL]
    COLD -->|Summarized by LLM| SUMMARY[Compressed Summary]
    
    CONTEXT --> AGENT[Agent ReAct Loop]
    
    AGENT -->|Need older context?| RETRIEVAL{Semantic Search}
    RETRIEVAL --> WARM
    RETRIEVAL --> COLD
    
    subgraph Encryption["Per-Conversation Encryption"]
        MASTER[Master Key] --> PBKDF2[PBKDF2 Key Derivation]
        PBKDF2 --> CONV_KEY[Conversation Key]
        CONV_KEY --> AES[AES-GCM Encrypt/Decrypt]
    end

    STORE --> AES

    style HOT fill:#1a1a2e,stroke:#e94560,color:#e94560
    style WARM fill:#1a1a2e,stroke:#f39c12,color:#f39c12
    style COLD fill:#1a1a2e,stroke:#58a6ff,color:#58a6ff
```

---

## 7. Security Layers

All security checks from input to output.

```mermaid
flowchart TB
    INPUT[User Input] --> S1[Rate Limiting - Redis sliding window]
    S1 --> S2[Authentication - JWT or API Key]
    S2 --> S3[Input Sanitization - XSS and SQL injection]
    S3 --> S4[Input Guardrail - prompt injection detection]
    S4 --> S5[PII Detection - regex + spaCy NER]
    
    S5 --> AGENT[Agent Processing]
    
    AGENT --> S6[Permission Check - Path.resolve + trailing slash]
    S6 --> S7[Tool Sandboxing - subprocess + timeout]
    S7 --> S8[Circuit Breaker - fail fast on dead service]
    
    S8 --> OUTPUT[Agent Output]
    
    OUTPUT --> S9[Output Guardrail - harmful content filter]
    S9 --> S10[PII Redaction - scrub before display]
    S10 --> S11[Audit Log - correlation ID + security level]
    S11 --> S12[OTel Trace - PII scrubbed before export]
    
    S12 --> RESPONSE[Clean Response to User]

    style S1 fill:#1a1a2e,stroke:#f39c12,color:#f39c12
    style S2 fill:#1a1a2e,stroke:#f39c12,color:#f39c12
    style S3 fill:#1a1a2e,stroke:#e94560,color:#e94560
    style S4 fill:#1a1a2e,stroke:#e94560,color:#e94560
    style S5 fill:#1a1a2e,stroke:#e94560,color:#e94560
    style S6 fill:#1a1a2e,stroke:#e94560,color:#e94560
    style S7 fill:#1a1a2e,stroke:#e94560,color:#e94560
    style S8 fill:#1a1a2e,stroke:#e94560,color:#e94560
    style S9 fill:#1a1a2e,stroke:#2ecc71,color:#2ecc71
    style S10 fill:#1a1a2e,stroke:#2ecc71,color:#2ecc71
    style S11 fill:#1a1a2e,stroke:#58a6ff,color:#58a6ff
    style S12 fill:#1a1a2e,stroke:#58a6ff,color:#58a6ff
```

---

## 8. RAG Pipeline

Document upload to grounded answer.

```mermaid
flowchart LR
    subgraph Ingestion["Document Ingestion"]
        UPLOAD[Upload PDF/DOCX] --> VIRUS[Virus Scan]
        VIRUS --> EXTRACT[Extract Text]
        EXTRACT --> CHUNK[Recursive Chunking with overlap]
        CHUNK --> EMBED[Generate Embeddings]
        EMBED --> STORE[(pgvector Storage)]
    end

    subgraph Query["Query Pipeline"]
        QUERY[User Question] --> QEMBED[Embed Query]
        QEMBED --> SEARCH[Hybrid Search: vector + BM25]
        SEARCH --> RERANK[Cross-Encoder Reranking]
        RERANK --> TOP_K[Top-K Chunks]
    end

    subgraph Answer["Answer Generation"]
        TOP_K --> PROMPT[Build Prompt with Sources]
        PROMPT --> LLM[LLM Generate]
        LLM --> CITE[Extract Citations]
        CITE --> VERIFY[Fact Verification]
        VERIFY --> RESPONSE[Answer with Sources]
    end

    style Ingestion fill:#1a1a2e,stroke:#2ecc71,color:#c9d1d9
    style Query fill:#1a1a2e,stroke:#58a6ff,color:#c9d1d9
    style Answer fill:#1a1a2e,stroke:#f39c12,color:#c9d1d9
```

---

## 9. Circuit Breaker State Machine

Protection against dead LLM providers.

```mermaid
stateDiagram-v2
    [*] --> CLOSED

    CLOSED --> OPEN: failure_count >= threshold
    CLOSED --> CLOSED: success - reset counter

    OPEN --> HALF_OPEN: recovery_timeout expires
    OPEN --> OPEN: all requests rejected instantly

    HALF_OPEN --> CLOSED: trial call succeeds
    HALF_OPEN --> OPEN: trial call fails - restart timer
```

---

## 10. Deployment Architecture

From local development to production.

```mermaid
flowchart LR
    subgraph Local["Local Dev"]
        DC[docker-compose.yml]
        DC --> PG_L[(PostgreSQL)]
        DC --> RED_L[(Redis)]
        DC --> JAEGER_L[Jaeger]
        DC --> BE_L[FastAPI Backend]
        DC --> FE_L[SvelteKit Frontend]
    end

    subgraph CI["GitHub Actions CI"]
        LINT[Ruff Lint]
        TYPE[Mypy Type Check]
        TEST[Pytest - 100+ tests]
        SEC[pip-audit Security Scan]
        EVAL[Promptfoo Quality Gate]
        BUILD[Docker Build]
    end

    subgraph Azure["Azure Production"]
        ACA[Azure Container Apps]
        ACA --> PG_A[(Azure PostgreSQL Flex)]
        ACA --> RED_A[(Azure Cache for Redis)]
        ACA --> BLOB[(Azure Blob Storage)]
        ACA --> MON[Azure Monitor - traces + metrics]
        ACA --> ACR[Azure Container Registry]
    end

    Local -->|git push| CI
    CI -->|All green| Azure

    style Local fill:#1a1a2e,stroke:#2ecc71,color:#c9d1d9
    style CI fill:#1a1a2e,stroke:#f39c12,color:#c9d1d9
    style Azure fill:#1a1a2e,stroke:#58a6ff,color:#c9d1d9
```

---

## 11. Development Phases Timeline

```mermaid
gantt
    title Archon Development - 12 Weeks
    dateFormat  YYYY-MM-DD
    axisFormat  %b %d

    section Phase 0 - Scaffold
    Monorepo + Docker + CI      :p0, 2026-08-25, 7d

    section Phase 1 - Core Chat
    ReAct Agent + FastAPI        :p1a, after p0, 7d
    Svelte Chat UI + SSE         :p1b, after p1a, 7d

    section Phase 2 - Security
    PII + Guardrails + Perms     :p2, after p1b, 7d

    section Phase 3 - RAG
    Doc Upload + Chunking        :p3a, after p2, 7d
    Vector Search + Reranking    :p3b, after p3a, 7d

    section Phase 4 - Multi-Agent
    Specialist Agents            :p4a, after p3b, 7d
    Coordination + Handoff       :p4b, after p4a, 7d

    section Phase 5 - Observability
    OTel + Jaeger + Metrics      :p5, after p4b, 7d

    section Phase 6 - Memory
    Tiered + Compression         :p6, after p5, 7d

    section Phase 7 - Eval
    Harness + Quality Gates      :p7, after p6, 7d

    section Phase 8 - Deploy
    Azure + K8s Manifests        :p8, after p7, 7d
```

---

## Diagram Index

| # | Diagram | Type | What it explains |
|---|---------|------|-----------------|
| 1 | System Architecture | Component | How all layers connect |
| 2 | ReAct Reasoning Loop | Sequence | A single message through the agent system |
| 3 | Class Diagram | Class | Protocol-based DI, all interfaces and implementations |
| 4 | Request Flow | Flowchart | HTTP request through all middleware layers |
| 5 | Multi-Agent Coordination | Flowchart | How Coordinator delegates to specialists |
| 6 | Memory Tiers | Flowchart | Hot/warm/cold storage with encryption |
| 7 | Security Layers | Flowchart | All 12 security checks from input to output |
| 8 | RAG Pipeline | Flowchart | Document ingestion to grounded answer |
| 9 | Circuit Breaker | State | CLOSED/OPEN/HALF_OPEN state machine |
| 10 | Deployment | Flowchart | Local dev to Azure production |
| 11 | Timeline | Gantt | 12-week development phases |
