"""A/B testing framework: route traffic to different models/prompts.

Plan item #108: Route % of traffic to new model/prompt variant.
"""

from __future__ import annotations

import random
import time
from collections import defaultdict

import structlog

logger = structlog.get_logger()


class ABVariant:
    """A variant in an A/B test."""

    def __init__(self, name: str, config: dict, weight: float = 0.5) -> None:
        self.name = name
        self.config = config  # e.g. {"model": "llama3.1:8b", "system_prompt": "..."}
        self.weight = weight
        self.metrics: dict[str, list[float]] = defaultdict(list)

    def record_result(self, latency_ms: float, tokens: int, score: float) -> None:
        self.metrics["latency"].append(latency_ms)
        self.metrics["tokens"].append(tokens)
        self.metrics["score"].append(score)

    def get_stats(self) -> dict:
        def avg(lst: list) -> float:
            return round(sum(lst) / max(len(lst), 1), 2)

        return {
            "name": self.name,
            "samples": len(self.metrics.get("score", [])),
            "avg_latency_ms": avg(self.metrics.get("latency", [])),
            "avg_tokens": avg(self.metrics.get("tokens", [])),
            "avg_score": avg(self.metrics.get("score", [])),
            "config": self.config,
        }


class ABTestManager:
    """Manage A/B tests for model/prompt comparisons."""

    def __init__(self) -> None:
        self._tests: dict[str, dict] = {}

    def create_test(
        self,
        name: str,
        variant_a: ABVariant,
        variant_b: ABVariant,
    ) -> dict:
        self._tests[name] = {
            "name": name,
            "variants": [variant_a, variant_b],
            "created_at": time.time(),
            "active": True,
        }
        logger.info("ab_test_created", name=name)
        return {"name": name, "status": "active"}

    def get_variant(self, test_name: str) -> ABVariant | None:
        """Select a variant based on weights (random routing)."""
        test = self._tests.get(test_name)
        if not test or not test["active"]:
            return None

        variants = test["variants"]
        weights = [v.weight for v in variants]
        total = sum(weights)
        r = random.random() * total

        cumulative = 0
        for variant in variants:
            cumulative += variant.weight
            if r <= cumulative:
                return variant

        return variants[-1]

    def record_result(
        self,
        test_name: str,
        variant_name: str,
        latency_ms: float,
        tokens: int,
        score: float,
    ) -> None:
        test = self._tests.get(test_name)
        if not test:
            return
        for v in test["variants"]:
            if v.name == variant_name:
                v.record_result(latency_ms, tokens, score)
                break

    def get_results(self, test_name: str) -> dict | None:
        test = self._tests.get(test_name)
        if not test:
            return None
        return {
            "name": test["name"],
            "active": test["active"],
            "variants": [v.get_stats() for v in test["variants"]],
        }

    def list_tests(self) -> list[dict]:
        return [
            {
                "name": t["name"],
                "active": t["active"],
                "variants": [v.name for v in t["variants"]],
            }
            for t in self._tests.values()
        ]

    def end_test(self, test_name: str) -> dict | None:
        test = self._tests.get(test_name)
        if test:
            test["active"] = False
            results = self.get_results(test_name)
            logger.info("ab_test_ended", name=test_name)
            return results
        return None
