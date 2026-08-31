# Live Foundry + RAG Hardening Implementation Plan

> **For Hermes:** Execute in coherent TDD batches, verify each batch on the canonical Mac worktree, and do not upgrade evidence status without runtime proof.

**Goal:** Make Archon's live Foundry path enforce durable budgets, token-aware context lineage, hard deadlines, strict structured output, real document embeddings, live faithfulness verification, and durable at-most-once effect orchestration.

**Architecture:** Preserve the existing typed runtime, repositories, run ledger, and acceptance harnesses. Close integration gaps by enabling proven controls in the managed stack, sharing hard deadline semantics with direct RAG and verifier calls, charging every provider call through one run-scoped budget factory, extending the existing embedding adapter for Foundry model-inference endpoints, and validating the complete upload→embed→retrieve→answer→verify path. Keep universal exactly-once, provider-wide parity, public deployment, and unsupported native JSON Schema claims explicitly out of scope.

**Tech stack:** Python 3.11, FastAPI, Pydantic, SQLAlchemy, PostgreSQL, Redis, Anthropic/Foundry adapter, httpx, pytest, Svelte, Playwright, Docker Compose.

---

## Baseline facts

- Durable monetary reserve/dispatch/reconcile code already exists but is disabled in the managed Compose target and has no live Foundry/PostgreSQL acceptance.
- Token-aware compaction plus metadata-only effective-context lineage already exists and is wired to sync/SSE.
- The typed chat runtime already has cancellation-resistant hard wall-clock deadlines; direct RAG and verifier calls do not share that helper.
- Strict local JSON parsing/schema validation already exists; Foundry advertises JSON mode but not native JSON Schema. The live acceptance harness incorrectly skips the locally validated path when native schema is absent.
- Durable at-most-once effect orchestration already exists but is disabled in the managed Compose target and lacks live PostgreSQL contention evidence.
- The bounded evidence verifier exists but is disabled in Compose, is not charged through the durable monetary wrapper, and uses `asyncio.wait_for` rather than the runtime's cancellation-resistant deadline behavior.
- The external embedding adapter and ingest/query acceptance harness exist. The current Foundry project has no `text-embedding-3-small` deployment (`DeploymentNotFound`), and Compose hardcodes mock embeddings.

## Batch 1 — Managed live runtime controls

**Modify**
- `backend/app/config.py`
- `scripts/generate-local-env.py`
- `docker-compose.local.yml`
- `backend/app/main.py`
- `backend/tests/unit/test_local_env_generator.py`
- `backend/tests/unit/test_local_deployment.py`
- `backend/tests/unit/test_health.py`

**Behavior**
1. Add configurable `agent_deadline_seconds` and RAG deadline setting.
2. Generate independent effect/delegation secrets in the protected temporary env.
3. Enable durable monetary budgets and durable effect ledger in the managed local target.
4. Enable the bounded verifier in live Foundry mode with the configured live model identity.
5. Pass optional embedding configuration only through an explicit allowlist.
6. Expose non-secret readiness flags for budget/effect/verifier/embedding mode.

**Acceptance**
- mock remains available only through explicit operator choice;
- live stack reports all controls enabled;
- generated env remains owner-only and never logs secrets;
- malformed/incomplete optional embedding groups fail before Compose.

## Batch 2 — Shared hard deadline contract

**Create**
- `backend/app/runtime/deadline.py`

**Modify**
- `backend/app/runtime/engine.py`
- `backend/app/delegation/service.py`
- `backend/app/services/grounded_rag.py`
- `backend/app/routes/documents.py`
- focused runtime/RAG/verifier tests

**Behavior**
1. Extract the proven detach-and-consume deadline helper from `AgentRuntime`.
2. Apply one monotonic deadline to embedding retrieval, parent RAG generation, verifier execution, and terminal persistence.
3. Preserve sanitized terminal run state on timeout/cancellation.
4. A cancellation-resistant provider cannot extend the request budget or re-enter bookkeeping.

## Batch 3 — Strict structured-output retry and live evidence

**Modify**
- `backend/app/runtime/engine.py`
- `backend/app/runtime/structured_output.py`
- `backend/scripts/provider_acceptance.py`
- runtime/provider acceptance tests

**Behavior**
1. Add one configurable corrective retry for malformed/schema-invalid terminal output.
2. Never emit or persist invalid structured text.
3. Preserve token, monetary, and deadline budgets across the retry.
4. Split live acceptance into `validated_structured_output` and `native_json_schema` so Foundry JSON-mode + local validation can pass honestly while native schema remains unsupported.
5. Add a repeated long-prompt cache probe; report nonzero hit/savings only if observed.

## Batch 4 — Budget every live model call

**Modify**
- `backend/app/runtime/factory.py`
- `backend/app/services/grounded_rag.py`
- `backend/app/delegation/service.py`
- budget wiring/integration tests

**Behavior**
1. Extract a run-scoped budget-wrapper factory.
2. Use it for chat, direct RAG generation, and verifier child calls.
3. Reserve conservatively, reconcile provider-reported actual usage, preserve actual winning provider/model, and fail closed on unknown pricing.
4. Keep one project limit shared across parent and verifier child runs.

## Batch 5 — Foundry embeddings and live upload/retrieval

**Modify**
- `backend/app/config.py`
- `backend/app/services/chunker.py`
- `backend/scripts/embedding_smoke.py`
- `scripts/generate-local-env.py`
- `docker-compose.local.yml`
- embedding tests

**Behavior**
1. Add `foundry` embedding transport with API-key auth and explicit API version; retain secure DNS/host allowlisting and no redirects.
2. Require an explicit embedding deployment/model and exact dimensions.
3. Pass optional embedding values through the managed env allowlist.
4. Run direct vector, persisted ingest, and actual query-vector retrieval acceptance.
5. Keep document upload/query unavailable or visibly non-production when embeddings are mock; never silently imply live semantics.

**External dependency**
- Deploy an embedding model (recommended `text-embedding-3-small`) in the existing Foundry project. This is a cloud/cost action and requires explicit authorization before execution.

## Batch 6 — Faithfulness evidence

**Modify**
- `backend/app/delegation/service.py`
- `backend/app/services/grounded_rag.py`
- `backend/app/routes/documents.py`
- RAG/evaluation tests and fixtures

**Behavior**
1. Reuse the bounded no-tools verifier as the faithfulness judge.
2. Bind it to a strict `ResponseContract`, one corrective retry, shared deadline, and durable monetary budget.
3. Record supported/rejected/escalated counts and a bounded faithfulness score/method.
4. Fail closed: rejected/escalated claims never enter the final answer.
5. Live test one supported and one unsupported document question.

## Batch 7 — PostgreSQL control-plane acceptance

**Create**
- `backend/app/acceptance/live_controls.py`

**Modify**
- `scripts/local-deploy-smoke.sh`
- effect/budget integration tests

**Behavior**
1. Exercise concurrent project-budget reservations against real PostgreSQL; aggregate reservations never exceed the limit.
2. Exercise duplicate effect reservation from independent sessions; exactly one caller receives dispatch permission.
3. Verify committed/indeterminate receipts and safe duplicate tombstones.
4. Clean acceptance rows and emit only bounded PASS metadata.
5. Continue claiming durable at-most-once orchestration, never universal exactly-once external effects.

## Batch 8 — Evidence, learning, NotebookLM, and UI

**Modify**
- `docs/implementation/CAPABILITY-ACCEPTANCE.yaml`
- `docs/course/concept-catalog.yaml`
- relevant `docs/course/concepts/*.md` and module READMEs
- `docs/IMPLEMENTATION-EVIDENCE.md`
- `docs/REMAINING-DEFERRED-GAPS.md`
- `docs/visual-learning/notebooklm-*`
- generated Studio/source-pack manifests
- Evidence UI only if required to show live/conditional dimensions clearly
- `ARCHON_CONTEXT.md`, operational skill, external handoff after merge

**Rules**
- Upgrade only individually proven dimensions.
- Keep native Foundry JSON Schema unsupported if it remains unsupported.
- Keep prompt-cache savings partial unless a nonzero cache read/write is observed.
- Keep universal exactly-once and production RTO/SLO claims out of scope.
- Distinguish live LLM from live embeddings.

## Final acceptance

1. Focused unit/security/integration suites.
2. Full `scripts/verify.sh` on exact clean commit.
3. Managed live Foundry startup with durable budgets/effects/verifier enabled.
4. Authenticated live chat with positive token usage and persisted nonzero budget spend.
5. Live structured-output local-validation probe; native schema reported independently.
6. Repeated prompt-cache probe with honest counters.
7. Real document upload → real embedding → retrieval → grounded answer → faithfulness verdict.
8. PostgreSQL budget/effect contention probe.
9. Desktop/mobile UI and Evidence status validation.
10. Exact-HEAD adversarial review, then request push/merge authorization.
