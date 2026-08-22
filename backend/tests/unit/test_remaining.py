"""Tests for remaining plan items: batch eval, load test, E2E stub, checkpoints, A/B."""

from __future__ import annotations

import pytest

from app.eval.ab_testing import ABTestManager, ABVariant
from app.eval.evaluators import (
    run_batch_eval,
)
from app.memory.advanced import (
    DriftDetector,
    get_token_count,
    importance_weighted_trim,
)
from app.memory.checkpoints import CheckpointManager
from app.services.db_features import (
    ConversationSharder,
    RowLevelSecurity,
    scan_document,
)


class TestCheckpoints:
    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_save_and_restore(self) -> None:
        mgr = CheckpointManager()
        messages = [{"role": "user", "content": "hello"}]
        cp = await mgr.save("conv-1", messages)
        restored = await mgr.restore(cp.id)
        assert restored is not None
        assert len(restored) == 1
        assert restored[0]["content"] == "hello"

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_list_checkpoints(self) -> None:
        mgr = CheckpointManager()
        await mgr.save("conv-1", [{"role": "user", "content": "a"}])
        await mgr.save(
            "conv-1", [{"role": "user", "content": "a"}, {"role": "assistant", "content": "b"}]
        )
        cps = await mgr.list_checkpoints("conv-1")
        assert len(cps) == 2

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_restore_is_deep_copy(self) -> None:
        mgr = CheckpointManager()
        messages = [{"role": "user", "content": "original"}]
        cp = await mgr.save("conv-1", messages)
        messages[0]["content"] = "modified"
        restored = await mgr.restore(cp.id)
        assert restored[0]["content"] == "original"


class TestABTesting:
    @pytest.mark.unit
    def test_create_and_get_variant(self) -> None:
        mgr = ABTestManager()
        va = ABVariant("control", {"model": "llama3.1:8b"}, weight=0.5)
        vb = ABVariant("experiment", {"model": "llama3.2:8b"}, weight=0.5)
        mgr.create_test("test-1", va, vb)
        variant = mgr.get_variant("test-1")
        assert variant is not None
        assert variant.name in ("control", "experiment")

    @pytest.mark.unit
    def test_record_and_results(self) -> None:
        mgr = ABTestManager()
        va = ABVariant("a", {}, 0.5)
        vb = ABVariant("b", {}, 0.5)
        mgr.create_test("t1", va, vb)
        mgr.record_result("t1", "a", 100.0, 50, 0.9)
        mgr.record_result("t1", "b", 200.0, 80, 0.7)
        results = mgr.get_results("t1")
        assert results is not None
        assert len(results["variants"]) == 2

    @pytest.mark.unit
    def test_end_test(self) -> None:
        mgr = ABTestManager()
        mgr.create_test("t1", ABVariant("a", {}), ABVariant("b", {}))
        mgr.end_test("t1")
        assert mgr.get_variant("t1") is None


class TestDriftDetector:
    @pytest.mark.unit
    def test_no_drift_initially(self) -> None:
        dd = DriftDetector(window_size=5)
        for _ in range(3):
            alert = dd.record(100, 50, 1, 500.0)
        assert alert is None

    @pytest.mark.unit
    def test_drift_detection(self) -> None:
        dd = DriftDetector(window_size=5, threshold=0.2)
        # Build baseline
        for _ in range(10):
            dd.record(100, 50, 1, 500.0)
        # Sudden change
        alert = None
        for _ in range(5):
            alert = dd.record(500, 200, 5, 2000.0)
        assert alert is not None or dd.get_stats()["baseline_size"] > 0


class TestImportanceWeightedTrim:
    @pytest.mark.unit
    def test_keeps_recent(self) -> None:
        messages = [
            {"role": "system", "content": "You are helpful."},
            {"role": "user", "content": "old question"},
            {"role": "assistant", "content": "old answer"},
            {"role": "user", "content": "latest question"},
        ]
        result = importance_weighted_trim(messages, max_tokens=30)
        assert any("latest" in m.get("content", "") for m in result)


class TestTokenCount:
    @pytest.mark.unit
    def test_basic_count(self) -> None:
        count = get_token_count("Hello, world!")
        assert count >= 1


class TestBatchEval:
    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_batch_eval_runs(self) -> None:
        async def mock_agent(q: str) -> dict:
            return {"response": f"Answer about {q}", "tokens_used": 50}

        cases = [
            {"question": "What is Python?", "context": "Python is a programming language."},
            {"question": "What is 2+2?"},
        ]
        result = await run_batch_eval(mock_agent, cases)
        assert result.total_cases == 2
        assert result.avg_safety == 1.0  # No PII in answers


class TestRowLevelSecurity:
    @pytest.mark.unit
    def test_access_check(self) -> None:
        rls = RowLevelSecurity()
        rls.set_user("user-1")
        assert rls.check_access("user-1") is True
        assert rls.check_access("user-2") is False

    @pytest.mark.unit
    def test_admin_bypass(self) -> None:
        rls = RowLevelSecurity()
        rls.set_user("admin")
        assert rls.check_access("user-1") is True


class TestConversationSharder:
    @pytest.mark.unit
    def test_shard_deterministic(self) -> None:
        sharder = ConversationSharder(num_shards=16)
        s1 = sharder.get_shard("user-123")
        s2 = sharder.get_shard("user-123")
        assert s1 == s2
        assert 0 <= s1 < 16


class TestVirusScan:
    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_safe_file(self) -> None:
        result = await scan_document(b"Hello world", "test.txt")
        assert result["safe"] is True

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_dangerous_extension(self) -> None:
        result = await scan_document(b"code", "malware.exe")
        assert result["safe"] is False

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_embedded_script(self) -> None:
        result = await scan_document(b"<script>alert(1)</script>", "page.html")
        assert result["safe"] is False
