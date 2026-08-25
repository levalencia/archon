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
    AuthRepository,
    hash_password,
    verify_password,
)
from app.services.db_store import DatabaseStore


class TestAuth:
    @pytest.mark.unit
    def test_hash_password(self) -> None:
        h = hash_password("secret123")
        assert h.startswith("scrypt$")
        assert verify_password("secret123", h)
        assert not verify_password("wrong", h)

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_register_and_authenticate(self, tmp_path) -> None:
        store = DatabaseStore(f"sqlite+aiosqlite:///{tmp_path}/auth.db")
        await store.initialize()
        repository = AuthRepository(store, "test-secret")
        await repository.register_user("testuser99", "password99")
        user = await repository.authenticate_user("testuser99", "password99")
        assert user is not None
        assert user["username"] == "testuser99"
        await store.close()

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_wrong_password(self, tmp_path) -> None:
        store = DatabaseStore(f"sqlite+aiosqlite:///{tmp_path}/auth.db")
        await store.initialize()
        repository = AuthRepository(store, "test-secret")
        await repository.register_user("testuser98", "correct")
        user = await repository.authenticate_user("testuser98", "wrong")
        assert user is None
        await store.close()

    @pytest.mark.unit
    def test_jwt_create_and_verify(self) -> None:
        repository = AuthRepository(None, "test-secret")  # type: ignore[arg-type]
        token = repository.create_jwt("user-1", "testuser")
        payload = repository.verify_jwt(token)
        assert payload is not None
        assert payload["sub"] == "user-1"
        assert payload["username"] == "testuser"

    @pytest.mark.unit
    def test_jwt_invalid_token(self) -> None:
        repository = AuthRepository(None, "test-secret")  # type: ignore[arg-type]
        assert repository.verify_jwt("invalid.token.here") is None

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_duplicate_username(self, tmp_path) -> None:
        store = DatabaseStore(f"sqlite+aiosqlite:///{tmp_path}/auth.db")
        await store.initialize()
        repository = AuthRepository(store, "test-secret")
        await repository.register_user("unique_user_1", "pass")
        with pytest.raises(ValueError, match="already exists"):
            await repository.register_user("unique_user_1", "pass2")
        await store.close()


class TestEvaluators:
    @pytest.mark.unit
    def test_faithfulness_grounded(self) -> None:
        answer = "Python is a programming language for web development."
        context = (
            "Python is a popular programming language used for web development and data science."
        )
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
        score = evaluate_safety("This is a safe and good response.")
        assert score.score >= 0.5  # spaCy may detect entities

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
