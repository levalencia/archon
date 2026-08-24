# Archon Implementation Status

**Last verified:** 2026-08-24  
**Branch basis:** local `main` at `9462518` after runtime hardening and remaining-work plan  
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
| Backend tests | 371 passed, 0 skipped |
| Backend measured coverage | 74% |
| Svelte and TypeScript checks | 0 errors, 0 warnings |
| Frontend unit tests | 6 passed |
| Frontend browser tests | 2 passed, desktop and mobile |
| Frontend production build | Pass |
| Backend Docker smoke | Pass, `/healthz` |
| Live Foundry and Brave regression | Pass: 5 distinct searches, 0 duplicates, 3 iterations, `completed` |

## Capability matrix

| Capability | Implemented | Wired | Tested | Demo-ready | Notes |
|---|---:|---:|---:|---:|---|
| Typed agent runtime | Yes | Yes | Yes | Yes | Default chat and SSE path |
| Native Anthropic and Foundry tool calls | Yes | Yes | Yes | Yes | Normalized `tool_use` blocks |
| Explicit run stop reasons and budgets | Yes | Yes | Yes | Yes | Iteration, tools, tokens, time; forced tool-free final synthesis |
| Per-request runtime events | Yes | Yes | Yes | Yes | No shared-method monkey-patching |
| Robust frontend SSE parser | Yes | Yes | Yes | Yes | Split chunks, multiline data, terminal flush |
| URL-addressable conversations | Yes | Yes | Yes | Yes | `/chat/[id]` |
| Workbench desktop/mobile shell | Yes | Yes | Yes | Yes | Browser-tested |
| Sanitized Markdown rendering | Yes | Yes | Yes | Yes | DOMPurify after Markdown rendering |
| Unified persistent conversation repository | Yes | Yes | Yes | Yes | Shared by conversation CRUD, chat, stream, and history |
| Persistent identity and API keys | Yes | Yes | Yes | Yes | Salted scrypt, standard HS256 JWT, hashed API keys |
| Resource ownership enforcement | Yes | Yes | Yes | Yes | Conversation, document, artifact, log and admin boundaries tested |
| Security headers and CSRF | Yes | Yes | Yes | Yes | Cookie double-submit; Bearer/API-key exemption |
| Default tool permission policy | Partial | Yes | Yes | Partial | File reads are workspace-contained; general approval UI remains planned |
| Grounded research workflow | Yes | Yes | Yes | Partial | Offline cited workflow plus live Foundry and Brave runtime regression |
| Evidence and citation verification | Yes | Yes | Yes | Partial | 12 golden cases; currently used by `/v1/research` |
| Durable replayable run events | Partial | No | Partial | No | Events stream live but are not durably replayed |
| RAG with real durable embeddings | Partial/demo | Yes | Partial | No | Default route uses mock embeddings/in-memory vectors |
| Multi-agent coordinator | Yes | No | Unit only | No | Not part of default chat path |
| OpenTelemetry export | Yes | Configurable | Yes | Partial | Composite runtime sink; exporter activates when configured |
| Rate limiter | Yes | No | Unit only | No | Not installed on the live API path |
| MCP client integration | No | No | No | No | Planned after core reliability work |
| Human approval gates | No | No | No | No | Planned after permission policy |
| Verified cloud deployment | Manifests only | No | No | No | Requires a real deployment and smoke test |

## Active implementation order

1. Durable, owner-scoped run-event replay in API and Workbench.
2. Permission policy and human approval flow for sensitive tools.
3. Governed MCP adapter using the existing typed tool contract.
4. One bounded specialist delegation workflow.
5. Verified deployment and published benchmark results.

## Known test debt

All previously skipped backend tests have deterministic replacements. The current backend suite reports zero skipped tests. Live provider checks remain separate from the deterministic CI gate.

## Claim policy

Documentation and interview material must use these terms precisely:

- **Implemented** does not imply wired.
- **Wired** does not imply tested.
- **Tested** does not imply deployed.
- **Manifest present** does not imply cloud deployment.
- **Mock-backed demo** does not imply production RAG or production security.
