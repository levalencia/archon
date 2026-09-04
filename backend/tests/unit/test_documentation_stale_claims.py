"""Regression checks against stale current-state claims in documentation.

These tests ensure that canonical documentation does not contain outdated
references that were superseded by the PR #10 and PR #11 merges.  They are
deliberately restrictive: a false positive means the documentation drifted
back to a stale claim and must be re-audited.
"""

from __future__ import annotations

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]

# Files in scope for stale-claim regression
CANONICAL_DOCS = [
    ROOT / "README.md",
    ROOT / "docs" / "IMPLEMENTATION-EVIDENCE.md",
    ROOT / "docs" / "REMAINING-DEFERRED-GAPS.md",
    ROOT / "docs" / "ARCHITECTURE-DIAGRAMS.md",
    ROOT / "docs" / "DEMO-SCRIPT.md",
    ROOT / "docs" / "architecture" / "skills-project-instructions.md",
    ROOT / "docs" / "evidence" / "skills-project-instructions-implementation.md",
]


def _read_all_docs() -> dict[str, str]:
    return {str(p.relative_to(ROOT)): p.read_text(encoding="utf-8") for p in CANONICAL_DOCS}


@pytest.mark.unit
class TestNoStaleMainReference:
    """Ensure no document claims `63215bf` is the deployed/current main."""

    def test_no_deployed_main_63215bf(self) -> None:
        for relpath, content in _read_all_docs().items():
            # Allow historical mentions that are clearly labeled
            for line_no, line in enumerate(content.splitlines(), 1):
                if "63215bf" in line:
                    # Only allowed in explicitly historical context
                    assert any(
                        marker in line.lower()
                        for marker in ("historical", "superseded", "previous", "was")
                    ), (
                        f"{relpath}:{line_no} references stale main SHA 63215bf "
                        f"without historical qualifier: {line.strip()!r}"
                    )


@pytest.mark.unit
class TestNoCandidateNotPushedClaim:
    """Ensure docs don't claim skills work is a local unpushed candidate."""

    STALE_PHRASES = [
        "has not been pushed or deployed",
        "not pushed or deployed; deployed main remains",
        "candidate not deployed",
        "It is not pushed or deployed",
        "No push or deployment is claimed",
    ]

    def test_no_stale_unpushed_candidate_claims(self) -> None:
        for relpath, content in _read_all_docs().items():
            for phrase in self.STALE_PHRASES:
                assert phrase not in content, (
                    f"{relpath} contains stale candidate claim: {phrase!r}"
                )


@pytest.mark.unit
class TestMigrationHeadReference:
    """Ensure current-state docs reference migration 22, not 21 as head."""

    CURRENT_STATE_DOCS = [
        ROOT / "README.md",
        ROOT / "docs" / "IMPLEMENTATION-EVIDENCE.md",
        ROOT / "docs" / "REMAINING-DEFERRED-GAPS.md",
    ]

    def test_migration_head_is_22(self) -> None:
        for path in self.CURRENT_STATE_DOCS:
            content = path.read_text(encoding="utf-8")
            relpath = str(path.relative_to(ROOT))
            # Should mention 20260902_22 somewhere
            assert "20260902_22" in content, (
                f"{relpath} does not reference current migration head 20260902_22"
            )


@pytest.mark.unit
class TestCIRunReference:
    """Ensure current evidence references the correct CI run."""

    def test_current_ci_run_referenced(self) -> None:
        evidence = (ROOT / "docs" / "IMPLEMENTATION-EVIDENCE.md").read_text(encoding="utf-8")
        assert "33858051794" in evidence, (
            "IMPLEMENTATION-EVIDENCE.md does not reference current CI run 33858051794"
        )

    def test_current_main_sha_referenced(self) -> None:
        evidence = (ROOT / "docs" / "IMPLEMENTATION-EVIDENCE.md").read_text(encoding="utf-8")
        assert "1f71f0e" in evidence, (
            "IMPLEMENTATION-EVIDENCE.md does not reference current main SHA 1f71f0e"
        )


@pytest.mark.unit
class TestNoProhibitedClaims:
    """Ensure docs do not make claims explicitly prohibited by plan constraints."""

    PROHIBITED = [
        "pgvector",
        "production traffic",
        "SLOs",  # as a claim, not as a mention in limits
        "cloud deployment",
        "native Foundry JSON Schema",
        "cache savings",
    ]

    def test_no_affirmative_prohibited_claims(self) -> None:
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        evidence = (ROOT / "docs" / "IMPLEMENTATION-EVIDENCE.md").read_text(encoding="utf-8")
        for doc_name, content in [("README.md", readme), ("IMPLEMENTATION-EVIDENCE.md", evidence)]:
            lines = content.splitlines()
            for line_no, line in enumerate(lines, 1):
                for claim in self.PROHIBITED:
                    if claim.lower() not in line.lower():
                        continue
                    # Allowed in negation/limitation context (line or 5-line window)
                    negation_markers = (
                        "not",
                        "no",
                        "never",
                        "unclaimed",
                        "deferred",
                        "without",
                        "remain",
                        "omission",
                        "does not",
                        "outside",
                        "deliberately",
                        "explicitly",
                        "limit",
                    )
                    window = " ".join(lines[max(0, line_no - 6) : line_no]).lower()
                    assert any(marker in window for marker in negation_markers), (
                        f"{doc_name}:{line_no} appears to affirm prohibited "
                        f"claim {claim!r}: {line.strip()!r}"
                    )


# ---------------------------------------------------------------------------
# Semantic regression checks for specific stale-claim patterns
# ---------------------------------------------------------------------------

COURSE_DOCS = [
    ROOT / "docs" / "course" / "concepts" / "cost-usage-budgets.md",
    ROOT / "docs" / "course" / "concepts" / "react.md",
    ROOT / "docs" / "course" / "reference" / "database-schema.md",
    ROOT / "docs" / "course" / "concept-map.md",
]


def _read_course_docs() -> dict[str, str]:
    return {
        str(p.relative_to(ROOT)): p.read_text(encoding="utf-8") for p in COURSE_DOCS if p.exists()
    }


@pytest.mark.unit
class TestReflectionNotClaimedAbsent:
    """Generic reflection is implemented; docs must not claim it absent."""

    STALE_ABSENT_CLAIMS = [
        "not implemented in Archon",
        "Not implemented as a generic capability",
        "not a dependency backed by a generic implementation claim",
    ]

    def test_no_stale_reflection_absent(self) -> None:
        for relpath, content in {**_read_all_docs(), **_read_course_docs()}.items():
            for phrase in self.STALE_ABSENT_CLAIMS:
                assert phrase not in content, (
                    f"{relpath} claims generic reflection is absent: {phrase!r}"
                )


@pytest.mark.unit
class TestEmbeddingNotClaimedMock:
    """Live embeddings are proven; docs must not claim they are still mock."""

    STALE_MOCK_CLAIMS = [
        "embedding provider remained `mock`",
        "embedding provider remained mock",
        "Embeddings remain mock",
        "no live embedding request was made",
        "live embeddings or native JSON Schema",
    ]

    def test_no_stale_mock_embedding_claims(self) -> None:
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        for phrase in self.STALE_MOCK_CLAIMS:
            assert phrase not in readme, f"README.md contains stale embedding claim: {phrase!r}"


@pytest.mark.unit
class TestNoLocalCandidatePrefix:
    """Skills are merged; evidence must not label them 'Local candidate:'."""

    def test_no_local_candidate_prefix(self) -> None:
        evidence = (ROOT / "docs" / "IMPLEMENTATION-EVIDENCE.md").read_text(encoding="utf-8")
        assert "Local candidate:" not in evidence, (
            "IMPLEMENTATION-EVIDENCE.md still uses 'Local candidate:' for merged capability"
        )


@pytest.mark.unit
class TestDatabaseSchemaHead:
    """database-schema.md must reference the current migration head."""

    def test_schema_references_head_22(self) -> None:
        schema = (ROOT / "docs" / "course" / "reference" / "database-schema.md").read_text(
            encoding="utf-8"
        )
        assert "20260902_22" in schema, (
            "database-schema.md does not reference current migration head 20260902_22"
        )
        assert "20260826_08" not in schema or "→" in schema.split("20260826_08")[1][:20], (
            "database-schema.md still references 08 as the head"
        )


@pytest.mark.unit
class TestCostBudgetDiagramAccuracy:
    """cost-usage-budgets.md must describe serialized-request input estimation."""

    def test_mentions_serialized_input_estimate(self) -> None:
        cost = (ROOT / "docs" / "course" / "concepts" / "cost-usage-budgets.md").read_text(
            encoding="utf-8"
        )
        assert (
            "estimate_request_input_tokens" in cost or "Serialized-request input estimate" in cost
        ), "cost-usage-budgets.md does not describe the serialized-request input estimation step"
        assert "headroom" in cost.lower(), "cost-usage-budgets.md does not mention quote headroom"


@pytest.mark.unit
class TestReactToolBudgetAlignment:
    """react.md must document tool-budget alignment across system prompt and RuntimeBudget."""

    def test_tool_budget_alignment_documented(self) -> None:
        react = (ROOT / "docs" / "course" / "concepts" / "react.md").read_text(encoding="utf-8")
        assert "agent_max_tool_calls" in react, (
            "react.md does not document Settings.agent_max_tool_calls alignment"
        )
        assert "_append_unexecuted_tool_results" in react or "synthetic" in react.lower(), (
            "react.md does not document synthetic TOOL results for over-budget calls"
        )
