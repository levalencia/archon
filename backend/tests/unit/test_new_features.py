"""Tests for new features: auth, context optimizer, eval upgrades, metrics."""
from __future__ import annotations

import pytest

from app.eval.evaluators import (
    evaluate_cost,
    evaluate_faithfulness,
    evaluate_relevance,
    evaluate_safety,
)
from app.observability.metrics import (
    get_metrics_snapshot,
    get_prometheus_text,
    record_chat_request,
    record_llm_call,
    record_tool_call,
)
from app.security.auth import (
    authenticate_user,
    create_jwt,
    hash_password,
    register_user,
    verify_jwt,
)
from app.services.context_optimizer import (
    ContextOptimizer,
    count_messages_tokens,
    count_tokens,
)


class TestTokenCounting:
    @pytest.mark.unit
    def test_count_tokens(self) -> None:
        assert count_tokens("hello") >= 1
        assert count_tokens("a" * 400) == 100

    @pytest.mark.unit
    def test_count_messages(self) -> None:
        msgs = [
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "world"},
        ]
        tokens = count_messages_tokens(msgs)
        assert tokens > 0


class TestContextOptimizer:
    @pytest.mark.unit
    def test_small_context_unchanged(self) -> None:
        opt = ContextOptimizer(max_tokens=1000, reserve_for_response=100)
        msgs = [{"role": "user", "content": "hi"}]
        result = opt.optimize(msgs)
        assert len(result) == 1

    @pytest.mark.unit
    def test_large_context_trimmed(self) -> None:
        opt = ContextOptimizer(max_tokens=100, reserve_for_response=20)
        msgs = [
            {"role": "system", "content": "You are helpful."},
            {"role": "user", "content": "x" * 200},
            {"role": "assistant", "content": "y" * 200},
            {"role": "user", "content": "latest question"},
        ]
        result = opt.optimize(msgs)
        assert len(result) < len(msgs)
        # System message should be kept
        assert result[0]["role"] == "system"

    @pytest.mark.unit
    def test_get_stats(self) -> None:
        opt = ContextOptimizer(max_tokens=500)
        msgs = [{"role": "user", "content": "test"}]
        stats = opt.get_stats(msgs)
        assert "total_tokens" in stats
        assert "utilization_pct" in stats


class TestAuth:
    @pytest.mark.unit
    def test_hash_password(self) -> None:
        h = hash_password("secret123")
        assert len(h) == 64  # SHA-256 hex

    @pytest.mark.unit
    def test_register_and_authenticate(self) -> None:
        register_user("testuser99", "password99")
        user = authenticate_user("testuser99", "password99")
        assert user is not None
        assert user["username"] == "testuser99"

    @pytest.mark.unit
    def test_wrong_password(self) -> None:
        register_user("testuser98", "correct")
        user = authenticate_user("testuser98", "wrong")
        assert user is None

    @pytest.mark.unit
    def test_jwt_create_and_verify(self) -> None:
        token = create_jwt("user-1", "testuser")
        payload = verify_jwt(token)
        assert payload is not None
        assert payload["sub"] == "user-1"
        assert payload["username"] == "testuser"

    @pytest.mark.unit
    def test_jwt_invalid_token(self) -> None:
        assert verify_jwt("invalid.token.here") is None

    @pytest.mark.unit
    def test_duplicate_username(self) -> None:
        register_user("unique_user_1", "pass")
        with pytest.raises(ValueError, match="already exists"):
            register_user("unique_user_1", "pass2")


class TestEvaluators:
    @pytest.mark.unit
    def test_faithfulness_grounded(self) -> None:
        answer = "Python is a programming language for web development."
        context = "Python is a popular programming language used for web development and data science."
        score = evaluate_faithfulness(answer, context)
        assert score.score > 0.5

    @pytest.mark.unit
    def test_faithfulness_ungrounded(self) -> None:
        answer = "Quantum computing uses qubits for parallel processing."
        context = "Python is a programming language."
        score = evaluate_faithfulness(answer, context)
        assert score.score < 0.5

    @pytest.mark.unit
    def test_relevance_relevant(self) -> None:
        score = evaluate_relevance(
            "Python is used for machine learning and data analysis.",
            "What is Python used for?",
        )
        assert score.score > 0.5

    @pytest.mark.unit
    def test_safety_clean(self) -> None:
        score = evaluate_safety("This is a safe response about Python.")
        assert score.score == 1.0

    @pytest.mark.unit
    def test_safety_pii(self) -> None:
        score = evaluate_safety("Contact john@example.com for details.")
        assert score.score < 1.0

    @pytest.mark.unit
    def test_cost_within_budget(self) -> None:
        score = evaluate_cost(500, max_expected=2000)
        assert score.score == 1.0

    @pytest.mark.unit
    def test_cost_over_budget(self) -> None:
        score = evaluate_cost(5000, max_expected=2000)
        assert score.score < 1.0


class TestMetrics:
    @pytest.mark.unit
    def test_record_and_snapshot(self) -> None:
        record_llm_call("test-model", 100, 500.0)
        record_tool_call("calculator", 50.0)
        record_chat_request(1000.0)

        snapshot = get_metrics_snapshot()
        assert snapshot["totals"]["llm_calls"] > 0
        assert snapshot["totals"]["tool_calls"] > 0

    @pytest.mark.unit
    def test_prometheus_format(self) -> None:
        text = get_prometheus_text()
        assert "archon_llm_calls_total" in text
        assert "archon_tool_calls_total" in text
