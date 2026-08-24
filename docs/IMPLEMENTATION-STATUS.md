# Archon Implementation Status

**Last verified:** 2026-08-24  
**Branch basis:** local `main` after typed runtime and workbench integration  
**Acceptance command:** `./scripts/verify.sh`

This document is the source of truth for implementation claims. A source file alone does not make a capability complete.

## Status definitions

- **Implemented:** meaningful code exists.
- **Wired:** the default live request path invokes it.
- **Tested:** deterministic automated tests exercise the live contract.
- **Demo-ready:** the behavior is reliable and visible in the current UI.

## Verified baseline

| Gate | Result |
|---|---|
| Backend Ruff | Pass |
| Backend tests | 294 passed, 15 skipped |
| Backend measured coverage | 69% |
| Svelte and TypeScript checks | 0 errors, 0 warnings |
| Frontend unit tests | 5 passed |
| Frontend browser tests | 2 passed, desktop and mobile |
| Frontend production build | Pass |
| Backend Docker smoke | Pass, `/healthz` |

## Capability matrix

| Capability | Implemented | Wired | Tested | Demo-ready | Notes |
|---|---:|---:|---:|---:|---|
| Typed agent runtime | Yes | Yes | Yes | Yes | Default chat and SSE path |
| Native Anthropic and Foundry tool calls | Yes | Yes | Yes | Yes | Normalized `tool_use` blocks |
| Explicit run stop reasons and budgets | Yes | Yes | Yes | Yes | Iteration, tools, tokens, time |
| Per-request runtime events | Yes | Yes | Yes | Yes | No shared-method monkey-patching |
| Robust frontend SSE parser | Yes | Yes | Yes | Yes | Split chunks, multiline data, terminal flush |
| URL-addressable conversations | Yes | Yes | Yes | Yes | `/chat/[id]` |
| Workbench desktop/mobile shell | Yes | Yes | Yes | Yes | Browser-tested |
| Sanitized Markdown rendering | Yes | Yes | Yes | Yes | DOMPurify after Markdown rendering |
| Unified persistent conversation repository | In progress | No | No | No | Messages and metadata still being consolidated |
| Persistent identity and API keys | Partial | Partial | Partial | No | Current auth uses process memory |
| Resource ownership enforcement | Partial | No | No | No | Required for conversations, docs, artifacts and logs |
| Security headers and CSRF | Implemented | No | Isolated tests | No | Middleware exists but is not installed |
| Default tool permission policy | Partial | Partial | Partial | No | `read_file` remains too permissive |
| Grounded research workflow | In progress | No | No | No | Typed vertical slice under development |
| Evidence and citation verification | Partial | No | Partial | No | Existing evaluators are not the live answer gate |
| Durable replayable run events | Partial | No | Partial | No | Events stream live but are not durably replayed |
| RAG with real durable embeddings | Partial/demo | Yes | Partial | No | Default route uses mock embeddings/in-memory vectors |
| Multi-agent coordinator | Yes | No | Unit only | No | Not part of default chat path |
| OpenTelemetry export | Partial | No | Unit only | No | Export/startup wiring incomplete |
| Rate limiter | Yes | No | Unit only | No | Not installed on the live API path |
| MCP client integration | No | No | No | No | Planned after core reliability work |
| Human approval gates | No | No | No | No | Planned after permission policy |
| Verified cloud deployment | Manifests only | No | No | No | Requires a real deployment and smoke test |

## Active implementation order

1. Unified persistent conversations and messages.
2. Persistent auth, ownership, middleware, and sensitive-tool boundaries.
3. Grounded research workflow and golden evaluations.
4. Durable event replay, approvals, and governed MCP.
5. One bounded specialist delegation workflow.
6. Verified deployment and published benchmark results.

## Known test debt

Fifteen backend tests are currently skipped. They must be replaced, made deterministic, or justified individually before a production-readiness claim. Network-dependent checks must not be part of the deterministic unit gate.

## Claim policy

Documentation and interview material must use these terms precisely:

- **Implemented** does not imply wired.
- **Wired** does not imply tested.
- **Tested** does not imply deployed.
- **Manifest present** does not imply cloud deployment.
- **Mock-backed demo** does not imply production RAG or production security.
