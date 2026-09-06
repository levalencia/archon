# Single vs Team Benchmark v1

Status: versioned and executed locally against Foundry `claude-opus-4-6` on 2026-09-06.

This benchmark measures when Archon's bounded two-child Team mode provides enough answer-quality benefit to justify its additional latency, cost, and failure surface. It does not assume that Team is better.

## Design

```text
100 versioned cases
├── 10 categories × 10 cases
├── 40 easy / 30 medium / 30 hard
├── 20 calibration cases
└── identical prompts for Single and Team

Each Team run
├── researcher-v1
├── dynamic-analyst-v1
└── parent synthesis-only runtime
```

The ten categories are:

1. direct factual questions;
2. summarization and transformation;
3. multi-source research;
4. architecture comparison;
5. security and threat modeling;
6. code reasoning with self-contained snippets;
7. debugging and incident analysis with synthetic evidence;
8. quantitative/data reasoning with supplied numbers;
9. evaluation and experimental design;
10. product/system planning.

Every category has four easy, three medium, and three hard cases. Cases 001 and 008 in each category form the 20-case calibration set.

## Files

- `cases.json`: immutable prompts, expected traits, categories, difficulty, tool profile, parallelism annotation, and calibration membership.
- `rubric.json`: blind quality rubric, expected-trait normalization, operational metrics, stop conditions, routing thresholds, and specialist gates.
- `scripts/run-hybrid-benchmark.py`: resumable external-output live harness.
- `scripts/analyze-hybrid-benchmark.py`: deterministic blinding, score ingestion, paired statistics, and offline Auto replay.

Raw responses are deliberately excluded from Git. The harness writes them outside the repository and never persists generated credentials.

## Fairness contract

- The prompt is byte-identical across Single and Team.
- Provider and model revision must match within each accepted pair.
- No-tools cases explicitly prohibit tool use.
- Search cases permit `web_search` only, which both modes expose.
- Team remains depth one with exactly two read-only children.
- Mode order is deterministically randomized per case to reduce ordering bias.
- HTTP 200 or `completed` is functional evidence, not a quality score.
- Invalid or degraded runs are retained as failures; they are not silently rerun.

The dataset intentionally contains categories expected to favor Single. A benchmark containing only parallel research tasks would not answer when Team should *not* be used. Results must therefore be stratified by category, difficulty, tool profile, and expected parallelism.

## Cost and stop policy

The operator-authorized ceiling is USD 60 for the full paired run. Based on the three-case acceptance sample, 100 Single+Team pairs were projected near USD 49.06, but that estimate is not a guarantee.

The harness reserves USD 2 before each Single run and USD 5 before each Team run. It stops before a run whose reserve would cross the benchmark ceiling. It also stops after two repeated systemic failures or more than two invalid calibration pairs. There are no automatic provider reruns.

## Run sequence

Prerequisites:

```text
- merged pilot on main
- retained local stack ready at http://archon
- live Foundry provider configured
- hybrid orchestration enabled
- PostgreSQL and Redis preserved
```

Calibration:

```bash
python3 scripts/run-hybrid-benchmark.py \
  --phase calibration \
  --output /tmp/archon-hybrid-benchmark-v1-results.json \
  --cost-cap-usd 60
```

Do not continue merely because all requests returned HTTP 200. Review functional failures, child stop reasons, cost, raw output shape, and blind-scoring reliability first.

Remaining cases after a valid calibration:

```bash
python3 scripts/run-hybrid-benchmark.py \
  --phase remainder \
  --output /tmp/archon-hybrid-benchmark-v1-results.json \
  --cost-cap-usd 60
```

The second command resumes from the same checkpoint and skips completed case/mode pairs.

## Observed result

The completed run produced 200 HTTP-200 responses across 100 Single/Team pairs. Durable
reconciliation found 400 parent/child run rows, 542 reconciled model charges, USD 22.461065000
reconciled spend, and two indeterminate charges whose full USD 0.817118750 reservations keep the
worst-case accounted amount at USD 23.278183750. Five pairs were excluded from answer-quality
comparison: two Single tool-contract violations, two degraded Team runs, and one Single parent that
returned HTTP 200 but ended durably as `failed/provider_error`.

Across 95 valid pairs, blind scoring produced Single 9.6000/10 and Team 9.5895/10. The paired Team
minus Single delta was -0.0105 with bootstrap 95% CI [-0.2526, 0.2211], 12 Team wins, 72 ties, 11
Single wins, and two-sided sign-test p=1.0. Across all 100 executed pairs, including invalid runs
that still consumed resources, Team used 24.64% more tokens, cost 78.18% more, and was 3.5687
times slower on average. The correct broad conclusion is
`functional_pass_quality_not_improved`.

Security threat modeling was the only category to meet the preregistered Team-positive directional
gate: +0.6667 mean quality, 3 wins / 5 ties / 1 loss, 2.5478x latency, and fewer unsupported claims.
Ten-category cells remain small, so this supports a bounded routing rule rather than a universal
superiority claim. No failure cluster met the threshold for adding a specialist.

The sanitized evidence packet is
`docs/evidence/single-vs-team-benchmark-v1-summary.json`. Raw responses, blind keys, and grader
artifacts remain outside Git under `/tmp`.

## Scoring and analysis

Each answer receives 0–2 on:

1. instruction following;
2. groundedness and source quality;
3. coverage and completeness;
4. unsupported-claim discipline;
5. actionable usefulness.

Expected traits are scored as a normalized fraction, not a raw count. Responses should be blinded to mode before quality review. Citation-required cases need URL reachability and claim-support checks. Tool-call-shaped JSON, hidden execution artifacts, dead URLs, domain-only citations, and unsupported numeric claims are explicit defects.

Primary comparison:

```text
paired quality delta = Team score − Single score
```

Report paired bootstrap confidence intervals, a Wilcoxon sensitivity analysis, wins/ties/losses, latency ratio, token delta, cost delta, and failure rate. Ten cases per category are directional; categories with promising or concerning signals need expanded holdouts before production routing changes.

## Auto routing

Auto can be evaluated offline without another 100 provider calls. For every case, select the recorded Single or Team output according to the current deterministic router, then compare that policy with:

- always Single;
- always Team;
- the per-case quality oracle.

Routing changes require at least 75% routing accuracy, mean quality regret no greater than 0.03, and lower cost than always Team.

The original `hybrid-router-v1` routed all 95 valid benchmark cases to Team and achieved 12.63%
routing accuracy. The benchmark-derived `hybrid-router-v2` keeps Single as the default and selects
Team only when at least two independent security-risk signals are present. Offline replay routed 9
cases to Team and 86 to Single, achieved 83.16% routing accuracy and 0.0189 normalized quality
regret, and reduced replay cost by 42.65% and mean latency by 58.16% relative to v1.

## Specialist policy

Do not add profiles based on intuition. Investigate a specialist only when at least three manually confirmed cases in one category score below 0.5 normalized expected-trait coverage in both Single and current Team. A specialist must then demonstrate at least 0.10 mean improvement on a held-out failing set without increasing unsupported claims or security failures.

## Claim boundary

This is a local, provider-backed evaluation of one Archon revision, one provider/model revision, and one bounded Team topology. It does not prove universal multi-agent superiority, production SLOs, public deployment, or the value of additional agents.
