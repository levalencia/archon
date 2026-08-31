# Archon 3–5 Minute Demo Script

## Demo claim

> Archon is a local Agent Reliability Workbench that makes policy, approvals, tool execution, evidence and evaluation inspectable. This demo proves the local control plane; it does not claim public deployment or external-model quality.

## Before recording

- Use synthetic data only.
- Never show `.env`, tokens, keys, Docker inspect output, or raw credentials.
- Start from a clean worktree.
- Prefer a completed local smoke and the committed evidence JSON if live Docker timing is unpredictable.
- Keep browser zoom and terminal text readable.

## 0:00–0:30 — Frame the problem

Show the README title and architecture flow.

Say:

> Agent demos often show only a final answer. Archon records why an action was allowed, whether approval matched the exact call, what evidence supported the answer, and how the run evaluated afterward.

Point to:

```text
Policy → Run → Approval → Tool → Evidence → Evaluation
```

## 0:30–1:20 — Inspect one run

Open the Workbench on desktop width.

1. Select a conversation.
2. Show the answer-first center panel.
3. Expand the compact execution summary.
4. Open the Run inspector and show ordered events, stop reason, latency and token fields.
5. Open Evidence and show source IDs/citations and unsupported-claim status.

Say:

> Reload does not erase the trajectory. The Run Ledger is owner-scoped, ordered and append-only. Replay is stored-only, so inspecting history cannot rerun tools.

## 1:20–2:05 — Policy and approval

Use the benchmark evidence or a prepared approval flow.

Show these two observations in `docs/evidence/local-portfolio-benchmark.json`:

- no authorizer → `approval_unavailable`, handler calls `0`;
- exact approval → `completed`, handler calls `1`.

Say:

> Approval is bound to user, run, native tool-call ID, canonical tool name and argument hash. A changed call cannot reuse the decision. Unknown side effects fail closed.

If showing optional code execution, state that it is disabled in the verified Compose target and has no host fallback.

## 2:05–2:45 — Grounding and evaluation

Open Evaluations or the benchmark grounding scenario.

Show:

- accepted claim: `Alpha uses Python3 [E1]`;
- rejected overclaim: `Alpha uses Python3 and Rust`;
- persisted terminal run events.

Say:

> The benchmark uses the actual GroundedDocumentWorkflow with scripted local adapters. It proves unsupported-claim filtering and durable evidence, not general model quality.

Mention that retrieval is SQL JSON cosine, not pgvector.

## 2:45–3:20 — Governed MCP

Open **Skills & Integrations**.

Show server profile, health, discovered inventory, read-only/destructive indicators and an individual tool toggle.

Say:

> Archon uses the official MCP 2.1.1 stdio SDK. Users select allowlisted profiles; commands and secrets are not persisted. Enabled tools still pass through the same runtime policy and approval path, with a final enabled/schema/profile recheck before execution.

Do not imply Streamable HTTP, OAuth or public server deployment.

## 3:20–4:10 — Local operations and DR

Show `docker-compose.local.yml` services and the two committed evidence reports.

Say:

> The verified target publishes only a loopback gateway. PostgreSQL, Redis and OTEL stay internal. The smoke proved migrations, Redis readiness, auth, metrics and a real exported agent-run span.

Then show DR metrics:

- backup: 0.69 s;
- observed clean restore-to-ready: 24.787 s;
- zero selected-record differences at the snapshot boundary;
- restored conversation, run/events, document/chunk and terminal approval.

Clarify that these are one development-machine observation, not production SLOs.

## 4:10–4:40 — Close with limits

Show the limitations section.

Say:

> This is not publicly deployed. Remote CI is green at `9696ad8`, but real external-provider behavior was not rerun in this evidence cycle. The value is that those limits are explicit, while the local reliability paths are executable and measured.

## Live commands

Full acceptance:

```bash
./scripts/verify.sh
```

Local deployment smoke:

```bash
./scripts/local-deploy-smoke.sh
```

DR:

```bash
./scripts/local-dr-smoke.sh /tmp/archon-dr-report.json
```

Benchmark:

```bash
cd backend
uv run python scripts/portfolio_benchmark.py \
  --output /tmp/archon-portfolio-benchmark.json \
  --iterations 10
```

## Fallback if live Docker is slow

Use committed local evidence rather than pretending the live command completed:

- `docs/evidence/local-dr-report.json`
- `docs/evidence/local-portfolio-benchmark.json`
- `docs/IMPLEMENTATION-EVIDENCE.md`

State the revision and that the evidence was recorded locally. Do not edit screenshots or terminal output to manufacture a green result.
