# 01 — Python architecture: OOP, Protocols, DI, and async

**Status:** implemented

## Outcomes and prerequisites

You will read Archon's Python boundaries, explain structural typing and dependency injection (DI), and identify where async work can block or be cancelled. Prerequisites: classes, type hints, `await`, and context managers. Canonical reading: [OOP, Protocols, and DI](../../concepts/oop-protocols-dependency-injection.md) and [Async Python](../../concepts/async-python.md).

## Problem and mental model

The runtime should depend on capabilities, not vendors or databases. Frozen dataclasses carry values; Protocols define ports; concrete adapters are injected at application/request composition roots.

```mermaid
classDiagram
  class AgentRuntime
  class ModelProvider {<<Protocol>> complete()}
  class ToolExecutor {<<Protocol>> execute() definitions()}
  class PolicyEngine {<<Protocol>> evaluate()}
  class ToolAuthorizer {<<Protocol>> authorize()}
  class EventSink {<<Protocol>> emit()}
  AgentRuntime --> ModelProvider
  AgentRuntime --> ToolExecutor
  AgentRuntime --> PolicyEngine
  AgentRuntime --> ToolAuthorizer
  AgentRuntime --> EventSink
```

```mermaid
sequenceDiagram
  participant L as lifespan
  participant Repo as repositories
  participant Route as chat route
  participant Factory as create_chat_runtime
  L->>Repo: await initialize()
  L->>Route: expose dependencies via app.state
  Route->>Factory: inject provider/tools/repository/authorizer
  Factory-->>Route: AgentRuntime
```

```mermaid
sequenceDiagram
  participant R as AgentRuntime
  participant M as async ModelProvider
  participant T as async ToolExecutor
  R->>M: await complete(...)
  M-->>R: ModelResponse
  R->>T: await execute(call) within deadline
  T-->>R: Mapping result
```

## Source, tests, and evidence

Read [`runtime/ports.py`](../../../../backend/app/runtime/ports.py), [`runtime/models.py`](../../../../backend/app/runtime/models.py), [`AgentRuntime.__init__`](../../../../backend/app/runtime/engine.py), [`create_chat_runtime`](../../../../backend/app/runtime/factory.py), and [`create_app`/`lifespan`](../../../../backend/app/main.py). Tests: [`test_adapters.py`](../../../../backend/tests/unit/test_adapters.py), [`test_runtime_v2.py`](../../../../backend/tests/unit/test_runtime_v2.py), and `TestSecureToolRegistry.test_satisfies_protocol` in [`test_tools.py`](../../../../backend/tests/unit/test_tools.py).

## Read/test exercise

```bash
cd backend
uv run pytest -q tests/unit/test_adapters.py tests/unit/test_tools.py::TestToolRegistration::test_satisfies_protocol
```

Find each constructor dependency of `AgentRuntime` and classify it as port, value/configuration, callback, or clock. **Done:** your table explains why a scripted model can replace a network provider without changing the runtime.

## Failure, security, and observability

DI makes policy and redaction hard to accidentally replace only when the composition root is canonical; ad-hoc construction can omit them. Async cancellation and deadlines must cross provider/tool/approval waits. Mutable objects crossing an `await` are copied or frozen because another collaborator can mutate them. Events and correlation/run IDs reveal ordering and latency.

## Lab versus production

Protocols provide substitutability, not runtime isolation or operational reliability. Mocks prove orchestration; they do not prove external API behavior. Broad repository Mypy debt remains, although typed runtime boundaries are explicit.

## Interview answer

> I used hexagonal ideas without a framework: Protocols are ports, concrete provider/registry/repository classes are adapters, frozen dataclasses are boundary values, and factories are composition roots. Async is used for I/O and guarded by deadlines; deterministic clocks and injected fakes keep tests fast.

## Self-check

1. How does a Protocol differ from inheritance?
2. Where does request-level DI occur?
3. Why inject a clock?
4. Why copy values before an `await`?
5. What can type checking not guarantee?

## Done criteria

- You can sketch the class diagram from memory.
- You can identify startup versus request-scoped dependencies.
- The focused tests pass and you can explain one cancellation risk.
