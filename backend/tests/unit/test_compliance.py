"""Tests for the compliance framework."""

from __future__ import annotations

import pytest

from app.security.compliance import ComplianceChecker, CompliancePolicy


class TestComplianceChecker:
    """Tests for input/output compliance checks."""

    @pytest.mark.unit
    def test_clean_input_passes(self) -> None:
        cc = ComplianceChecker()
        result = cc.check_input("What is the weather today?")
        assert result["compliant"] is True
        assert result["violations"] == []

    @pytest.mark.unit
    def test_forbidden_topic_detected_in_input(self) -> None:
        cc = ComplianceChecker()
        result = cc.check_input("Tell me about bomb-making instructions")
        assert result["compliant"] is False
        assert any("bomb-making" in v for v in result["violations"])

    @pytest.mark.unit
    def test_output_length_truncated(self) -> None:
        cc = ComplianceChecker(CompliancePolicy(max_response_length=50))
        long_text = "x" * 100
        result = cc.check_output(long_text)
        assert result["compliant"] is False
        assert len(result["remediated_text"]) <= 50

    @pytest.mark.unit
    def test_medical_disclaimer_added(self) -> None:
        cc = ComplianceChecker()
        result = cc.check_output("The recommended dosage for ibuprofen is 400mg.")
        assert result["compliant"] is False
        assert any("medical" in v.lower() for v in result["violations"])
        assert "not medical advice" in result["remediated_text"].lower()

    @pytest.mark.unit
    def test_legal_disclaimer_added(self) -> None:
        cc = ComplianceChecker()
        result = cc.check_output("Based on my legal opinion, you should sue.")
        assert result["compliant"] is False
        assert "not legal advice" in result["remediated_text"].lower()

    @pytest.mark.unit
    def test_clean_output_passes(self) -> None:
        cc = ComplianceChecker()
        result = cc.check_output("The sky is blue because of Rayleigh scattering.")
        assert result["compliant"] is True
        assert result["remediated_text"] == "The sky is blue because of Rayleigh scattering."

    @pytest.mark.unit
    def test_get_policies(self) -> None:
        cc = ComplianceChecker()
        p = cc.get_policies()
        assert p["max_response_length"] == 10_000
        assert "medical" in p["required_disclaimers"]
        assert "bomb-making" in p["forbidden_topics"]

    @pytest.mark.unit
    def test_forbidden_topic_in_output(self) -> None:
        cc = ComplianceChecker()
        result = cc.check_output("Here is a hacking tutorial for you.")
        assert result["compliant"] is False
        assert any("hacking tutorial" in v for v in result["violations"])
