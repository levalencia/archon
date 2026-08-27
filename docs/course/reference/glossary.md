# Beginner glossary

> **Vocabulary snapshot:** reviewed against revision `3577b00`. Definitions are orientation only; linked concept pages are canonical.

| Term | Beginner-first meaning | Learn more |
|---|---|---|
| **Agent** | Software that repeatedly asks a model what to do, may call tools, observes results, and stops under program-owned rules. It is more than one model response. | [Agent anatomy](../concepts/agent-anatomy.md) |
| **Agent runtime** | The deterministic program that owns the loop, state, budgets, policy checks, events, and stopping. | [Typed runtime](../concepts/typed-runtime.md) |
| **Harness** | A controlled wrapper that supplies inputs, runs a subject, captures outputs, and scores or checks them consistently. | [Evaluation harness](../concepts/evaluation-harness.md) |
| **ReAct** | “Reason and Act”: alternate model decisions, tool actions, and observations until an answer or bounded stop. Archon stores observable actions, not hidden chain-of-thought. | [ReAct](../concepts/react.md) |
| **Tool** | A named capability with a schema that lets the runtime perform a bounded action outside the model. | [Tool contracts](../concepts/tool-contracts.md) |
| **Tool call** | A provider-decoded tool ID, name, and argument object proposed by a model. It is a request, not permission. | [Tool contracts](../concepts/tool-contracts.md) |
| **JSON Schema** | Machine-readable rules for the allowed shape and types of JSON data. | [JSON Schema](../concepts/json-schema.md) |
| **Budget** | A hard limit on iterations, calls, tokens, time, or output size. | [ReAct](../concepts/react.md) |
| **Stop reason** | A typed explanation of why the runtime ended, such as completion, denial, timeout, or exhausted budget. | [Stop-reason reference](stop-reasons.md) |
| **Grounding** | Constraining an answer to supplied evidence rather than unsupported model knowledge. | [RAG](../concepts/rag.md) |
| **Groundedness** | Whether claims are supported by the evidence supplied for that answer. | [Groundedness](../concepts/groundedness.md) |
| **Faithfulness** | Whether the answer accurately represents its cited context without contradiction or invention. | [Faithfulness](../concepts/faithfulness.md) |
| **Citation** | A reference from a claim to a specific evidence item; a citation is useful only if that item actually supports the claim. | [Citations](../concepts/citations.md) |
| **RAG** | Retrieval-augmented generation: retrieve relevant material, then give it to a model for an evidence-aware answer. | [RAG](../concepts/rag.md) |
| **Retrieval** | Selecting likely relevant records for a question. A high similarity score is not proof of truth. | [Retrieval](../concepts/retrieval.md) |
| **Embedding** | A list of numbers used to compare text similarity. Archon’s current durable store serializes vectors as SQL JSON and computes cosine in Python. | [Embeddings](../concepts/embeddings.md) |
| **Chunk** | A bounded piece of a document stored and retrieved independently. | [Chunking](../concepts/chunking.md) |
| **Evaluation** | A repeatable process that checks outputs or recorded behavior against declared cases and metrics. | [Evaluation harness](../concepts/evaluation-harness.md) |
| **Fixture** | Fixed test or evaluation input. It improves repeatability but is not live-provider or real-world-quality evidence. | [Datasets](../concepts/datasets.md) |
| **Idempotency** | Repeating the same operation has the same intended effect as doing it once. Ledger finalization can be idempotent even when an external tool is not. | [Idempotency](../concepts/idempotency.md) |
| **Retry** | Trying a failed operation again. Safe retries need bounded attempts and side-effect reasoning. | [Retries, timeouts, cancellation](../concepts/retries-timeouts-cancellation.md) |
| **Timeout / deadline** | A limit on how long work may take / the absolute time by which it must finish. | [Retries, timeouts, cancellation](../concepts/retries-timeouts-cancellation.md) |
| **Cancellation** | A caller’s signal that in-progress work should stop and clean up. | [Retries, timeouts, cancellation](../concepts/retries-timeouts-cancellation.md) |
| **Circuit breaker** | A stateful guard that temporarily fails fast after repeated dependency failures, then permits a bounded recovery probe. | [Circuit breaker](../concepts/circuit-breaker.md) |
| **Fallback** | A secondary path used when the preferred dependency fails. It may provide fewer capabilities. | [Fallback](../concepts/fallback.md) |
| **Rate limiting** | Restricting requests within a time window to control abuse and resource use. | [Rate limiting](../concepts/rate-limiting.md) |
| **OOP** | Object-oriented programming: organize behavior and state into objects with explicit responsibilities. | [OOP, Protocols, DI](../concepts/oop-protocols-dependency-injection.md) |
| **Protocol** | A Python structural interface: an object qualifies by providing required methods, without inheriting a base class. | [OOP, Protocols, DI](../concepts/oop-protocols-dependency-injection.md) |
| **DI** | Dependency injection: give a component its collaborators instead of creating hidden concrete dependencies inside it. | [OOP, Protocols, DI](../concepts/oop-protocols-dependency-injection.md) |
| **Async** | Cooperative concurrency using `async`/`await`, useful while waiting for I/O; it does not automatically make CPU work faster. | [Async Python](../concepts/async-python.md) |
| **State machine** | A set of named states and permitted transitions, including terminal outcomes. | [State machines](../concepts/state-machines.md) |
| **Policy** | Deterministic rules that classify a proposed action as allow, ask, or deny. | [Policy engine](../concepts/policy-engine.md) |
| **Approval** | A human/host decision bound to an exact tool-call identity and argument hash. | [Durable approvals](../concepts/durable-approvals.md) |
| **Fail closed** | Refuse the action when validation, policy, approval, or required metadata is missing or broken. |
| **Run Ledger** | Owner-scoped durable records for a run and its ordered, redacted events. | [Run Ledger](../concepts/run-ledger.md) |
| **Replay** | Reconstructing a stored trajectory for inspection; in Archon it does not rerun providers or tools. | [Replay/fork/compare](../concepts/replay-fork-compare.md) |
| **Fork** | Create a new conversation starting from a selected safe checkpoint while retaining lineage. | [Replay/fork/compare](../concepts/replay-fork-compare.md) |
| **MCP** | Model Context Protocol, a standard for discovering and invoking external tools/resources. Discovery does not bypass local policy. | [API map](api-map.md) |
| **SSE** | Server-Sent Events, an HTTP stream where the server sends a sequence of text events to the browser. | [Event catalog](event-catalog.md) |
| **OTEL** | OpenTelemetry, conventions and tooling for producing/exporting traces, metrics, and related telemetry. |
| **Trace / span** | A trace follows one operation across boundaries; a span is one timed step within it. |
| **Correlation ID** | An identifier copied across request, log, event, and trace boundaries to connect evidence. |
| **Liveness** | Whether the process is running enough to answer a probe. |
| **Readiness** | Whether checked dependencies are ready to serve traffic now. |
| **Migration** | A versioned database schema change applied in a defined order. | [Database schema](database-schema.md) |
| **RTO** | Recovery Time Objective: target maximum time to restore service after disruption. |
| **RPO** | Recovery Point Objective: target maximum amount of recent data that may be lost, expressed as time. |
| **Production-like local** | A local setup that resembles production in selected ways; it is not evidence of public deployment, scale, or SLOs. |
| **Self-reflection** | A model critiquing/revising its own reasoning. Archon must not infer generic self-reflection from tool-error feedback, deterministic verification, delegation, or post-run evaluation. |
