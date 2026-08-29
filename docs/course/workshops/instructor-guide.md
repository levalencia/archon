# Instructor guide

> **Program:** eight 90-minute sessions in the [company workshop track](../tracks/company-workshops.md)
> **Boundary:** teach from a pinned revision; never imply public production readiness from local evidence

## Before the cohort

1. Pin and announce the Git revision. Verify the repository is clean before demos.
2. Read the [syllabus evidence policy](../syllabus.md), all eight prereads, [code bookmarks](../reference/code-bookmarks.md), and [rubric](capstone-rubric.md).
3. On a disposable machine/worktree, follow repository setup, install Python dependencies with `uv`, and run one focused test from each session. Use the frontend only when it serves the learning outcome.
4. Prepare a mock/scripted provider path and disposable SQLite/local data. Treat Docker as optional unless the exercise explicitly needs it.
5. Create an instructor-only copy of [solutions](solutions.md). Do not distribute before artifact submission.
6. Check accessibility: readable terminal theme, shared commands in text, breaks, keyboard access, and an equivalent paper trace for learners unable to run containers.

## Safe secrets and data

- Start from `.env.example`; replace placeholders locally and keep `.env` untracked.
- Prefer mock credentials/providers. Never screen-share tokens, JWTs, cookies, encryption keys, customer text, memory exports, database dumps, or raw event/tool payloads.
- Use synthetic documents and unique disposable users/projects. Verify cleanup after each lab.
- If a secret appears, stop sharing, revoke/rotate it, remove it from artifacts/history where possible, and report through company procedure. Do not continue to “finish the demo.”
- Explain that redaction reduces exposure; it does not make arbitrary sensitive input safe.

## Standard pacing

| Minutes | Activity | Instructor action |
|---:|---|---|
| 0–10 | Retrieval and vocabulary | Ask two preread questions; correct terms by linking canonical concepts. |
| 10–30 | Architecture | Draw boundaries and one failure path; do not lecture from duplicated prose. |
| 30–45 | Demo | Show revision, exact command, expected observation, and limitation before running. |
| 45–70 | Pair exercise | Use driver/navigator roles; give hints from source bookmarks, not answers. |
| 70–82 | Artifact review | Ask for source, test, executable/observed evidence, and residual risk. |
| 82–90 | Self-check/exit ticket | Collect one claim, evidence, limitation, and remaining question. |

For a 60-minute slot, assign preread/self-check asynchronously and keep 15 minutes for the exercise. For a half-day, combine 1–2, 3–4, 5–6, or 7–8 with a 15-minute break and retain artifact review.

## Facilitation

- Begin with the learner problem, then the diagram, then source. Do not start with class names.
- Ask “What does this evidence prove?” and “What does it not prove?” after every demo.
- Rotate pair roles halfway. Invite quiet written answers before calling on individuals.
- Keep a visible parking lot for advanced questions; answer by source inspection or mark “not verified.”
- Never request hidden chain-of-thought. Ask for concise rationale, observable steps, evidence, and trade-offs.
- Correct hype precisely: local Compose ≠ deployed production; JSON cosine ≠ pgvector; error feedback ≠ generic self-reflection; one verifier child ≠ swarm.

## Assessment

Score artifacts with [capstone rubric](capstone-rubric.md). Give formative feedback after each workshop and a final independent score for E8. Require at least level 3 in every dimension; do not average away a missing executable-evidence or honesty dimension. Permit reruns with a new evidence note.

Useful prompts:

- “Point to the exact symbol and test.”
- “What input/state/output crosses this boundary?”
- “What failure is terminal, retried, denied, or merely observed?”
- “Was that result produced now, inherited from a fixture, or quoted from historical evidence?”
- “What would you need before making this claim about production?”

## Troubleshooting

| Symptom | Safe response |
|---|---|
| `uv` unavailable or install blocked | Use the paper/code-reading variant; do not install globally into a managed Python. |
| Docker unavailable | Skip container-dependent demo; use focused unit/integration tests and label the reduced evidence. |
| Startup rejects encryption key | Use a newly generated disposable local key according to repository setup; never paste it into chat/slides/commits. Do not disable the control merely to demo. |
| Provider/network unavailable | Switch to mock/scripted provider and relabel the evidence; never fabricate live output. |
| Database/migration mismatch | Stop; inspect URL, `alembic current`, and `alembic heads` against disposable data. Do not upgrade shared data during class. |
| Port occupied | Identify/stop only the cohort-owned process or use a documented alternate port. Do not kill unknown processes. |
| Test fails | Preserve command/output, narrow to the node, inspect revision/dependencies, and turn the failure into evidence; do not present expected output as actual. |
| Exercise runs long | Stop at the next evidence boundary and submit a partial artifact with explicit gaps. |

## After each session

Collect only sanitized artifacts, record misconceptions and timing, verify cleanup, and update bookmarks only after checking source at a new revision. Mutable test counts and runtime results belong in evidence records, not this guide.
