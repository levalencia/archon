# Fallback

**Status:** partial

## Definition
Fallback selects a secondary provider or degraded response when the preferred path fails. A fallback is correct only if its capabilities and safety semantics satisfy the request.

## Archon implementation
`backend/app/agents/fallback_chain.py::FallbackLLMChain` tries `LLMClient` adapters in order, records per-position failures, and returns the first text response. `llm_factory.create_llm_client` wires configured fallbacks. `ResilientCoordinator` also substitutes stage-specific degraded text after bounded attempts.

## Important limitations
The fallback chain is a legacy text interface and does not preserve typed model tools, images, structured output, usage, or stop-reason parity. When all adapters fail it returns an error summary string rather than a typed failure, and that summary includes exception text. Coordinator’s validation fallback says approved; it must not be treated as a policy/security check. Validate fallback outputs and expose degraded mode.

## Evidence
`backend/tests/unit/test_fallback_wire.py` proves primary selection, secondary fall-through, all-fail text, and factory wiring. `docs/evidence/local-portfolio-benchmark.json` uses injected clients and proves deterministic secondary selection—not real provider parity.

## Interview prompt
“Fallback is a semantic substitution, not just another endpoint; capability and safety parity must be explicit.”
