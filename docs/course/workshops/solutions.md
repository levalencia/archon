# Workshop solution guide

> **Instructor use:** withhold until learners submit. These are evaluation keys, not copy-ready artifacts or canonical concept explanations. Accept equivalent evidence-backed answers at the pinned revision.

## E1

A complete map places `AgentRuntime`—not the model—in control of budgets, policy, event emission, and stop reasons. The provider proposes native calls; policy/approval gates them; the executor acts; a tool observation returns to the loop. A valid failure branch ends in denial, timeout, or error. Do not reward hidden chain-of-thought claims.

## E2

Expected seams: `ModelProvider.complete`, `ToolExecutor.execute/definitions`, `ToolAuthorizer.authorize`, and `EventSink.emit`. `create_chat_runtime` injects a provider, `SecureToolRegistry`, composite sink, policy engine, optional authorizer, and budget into `AgentRuntime`. Protocol conformance is structural; composition is not inheritance. Test execution is bounded to injected/test doubles.

## E3

The nine runtime values are `completed`, iteration/tool/token/time budget exhausted, `policy_denied`, `approval_timeout`, `approval_unavailable`, and `error`. Exhausted iteration/tool/token paths may call `_finalize`; direct completion, policy/approval failures, deadline, and exceptions use `_stop`. Error observations can prompt another ReAct step but do not implement a general critique/rewrite mechanism.

## E4

ALLOW executes after policy metadata and exact binding checks. ASK executes only after an approval whose tool-call ID, canonical tool name, and arguments hash match. Timeout/unavailable/denial/mismatch execute nothing and fail closed. Strong artifacts show event order and never include raw arguments/results in durable evidence.

## E5

Request-local state dies with the request; conversation messages persist as conversation content; memory facts persist ciphertext under owner/project and key version; ledger payloads persist only allowlisted/redacted metadata. Forbidden examples include plaintext secrets in logs/events, shared-owner reads, and key material in artifacts. Encryption does not solve endpoint authorization, retention, endpoint compromise, or key operations.

## E6

The repository allocates sequence atomically and stores an event in the same transaction. `safe_event_payload` rejects unknown kinds, allowlists fields, redacts, and converts errors to presence booleans. Terminal state prevents later append/overwrite. Replay reconstructs stored safe data; compare computes stored differences; fork creates bounded conversation lineage with `workspace_restoration: none`.

## E7

Expected flow: scoped document chunks → JSON vector candidates → cosine computed in Python → bounded evidence → one claims response → hash/citation/lexical/number/polarity checks → retained claims/citations or abstention → safe events → deterministic evaluation of completed recorded runs. Similarity is ranking, deterministic support is not semantic truth, and a fixed fixture is not broad quality evidence.

## E8

There is no single correct failure. A passing artifact predicts behavior, identifies the owning control, provides the exact source symbol and focused behavior test, records actual output, traces safe evidence, explains a trade-off, and limits the conclusion. Examples: breaker state is process-local; local limiter is one process; fallback may lose typed capabilities; ledger idempotency does not make external side effects idempotent; a timeout path does not prove a universal deadline.

## Feedback key

- If a learner gives definitions without a trace, ask for input/state/output and the exact symbol.
- If they show a green test without scope, ask what collaborators were doubled.
- If they show a diagram without execution, score executable evidence independently.
- If they overclaim, require a corrected sentence; reward explicit uncertainty.
- If they expose data or secrets, stop assessment and follow the instructor incident procedure.

Apply the [capstone rubric](capstone-rubric.md); do not infer a total score by averaging away any dimension below level 3.
