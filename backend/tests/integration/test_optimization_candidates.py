"""API lifecycle for bounded, human-approved optimization candidates."""

from __future__ import annotations

import asyncio
from functools import partial
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.config import Settings
from app.main import create_app
from app.security.approval_repository import ApprovalStatus
from app.services.db_store import OptimizationCandidateEventRow


def _register(api: TestClient, username: str) -> dict[str, Any]:
    response = api.post(
        "/api/auth/register",
        json={
            "username": username,
            "password": "valid-password-123",
        },
    )
    assert response.status_code == 201
    return response.json()


async def _evaluation(repository, owner_id: str, project_id: str, suffix: str):
    item = await repository.create(
        owner_id,
        project_id=project_id,
        dataset_id="fixture",
        dataset_version="v1",
        dataset_hash="a" * 64,
        source_run_ids=(f"run-{suffix}-1", f"run-{suffix}-2"),
        threshold=0.8,
        model_revision=f"model-{suffix}",
        provider_revision="provider-v1",
        config_revision=f"config-{suffix}",
    )
    for number in (1, 2):
        await repository.append_case(
            owner_id,
            item.id,
            source_run_id=f"run-{suffix}-{number}",
            case_key=f"case-{number}",
            passed=True,
            score=1.0,
            metrics={
                "latency_ms": 10,
                "total_tokens": 5,
                "cost_usd": 0.001,
                "abstained": False,
                "citation_rate": 1.0,
                "unsupported_rate": 0.0,
                "safety_failure": False,
            },
            checks=(),
        )
    return await repository.finalize(
        owner_id, item.id, status="completed", passed=True, aggregate_metrics={"case_count": 2}
    )


def test_candidate_requires_exact_single_use_approval_and_records_rollback(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = Settings(
        llm_provider="mock",
        debug=True,
        memory_encryption_enabled=False,
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'candidates.db'}",
    )
    app = create_app(settings)
    with TestClient(app) as api:
        owner = _register(api, "candidate-owner")
        foreign = _register(api, "candidate-foreign")
        headers = {"Authorization": f"Bearer {owner['access_token']}"}
        foreign_headers = {"Authorization": f"Bearer {foreign['access_token']}"}
        assert api.portal is not None
        baseline = api.portal.call(
            partial(
                _evaluation,
                app.state.evaluation_repository,
                owner["user_id"],
                "project-a",
                "before",
            )
        )
        after = api.portal.call(
            partial(
                _evaluation, app.state.evaluation_repository, owner["user_id"], "project-a", "after"
            )
        )
        listed = api.get("/api/evals?project_id=project-a", headers=headers)
        assert listed.status_code == 200
        assert {item["model_revision"] for item in listed.json()["items"]} == {
            "model-before",
            "model-after",
        }
        assert (
            api.post(
                "/api/evals/drift",
                headers=headers,
                json={
                    "project_id": "project-a",
                    "baseline_eval_id": baseline.id,
                    "candidate_eval_id": baseline.id,
                    "minimum_sample_size": 2,
                },
            ).status_code
            == 409
        )
        drift = api.post(
            "/api/evals/drift",
            headers=headers,
            json={
                "project_id": "project-a",
                "baseline_eval_id": baseline.id,
                "candidate_eval_id": after.id,
                "minimum_sample_size": 2,
            },
        )
        assert drift.status_code == 201
        drift_id = drift.json()["id"]
        repeated_drift = api.post(
            "/api/evals/drift",
            headers=headers,
            json={
                "project_id": "project-a",
                "baseline_eval_id": baseline.id,
                "candidate_eval_id": after.id,
                "minimum_sample_size": 2,
            },
        )
        assert repeated_drift.status_code == 201
        assert repeated_drift.json()["id"] == drift_id
        assert (
            api.get(
                f"/api/evals/drift/{drift_id}?project_id=project-b", headers=headers
            ).status_code
            == 404
        )
        assert (
            api.get(
                f"/api/evals/drift/{drift_id}?project_id=project-a", headers=foreign_headers
            ).status_code
            == 404
        )
        created = api.post(
            "/api/evals/candidates",
            headers=headers,
            json={
                "project_id": "project-a",
                "candidate_type": "config",
                "change_summary": "Use bounded retriever revision r2.",
                "proposal_metadata": {"component": "retriever", "revision_hash": "b" * 64},
                "rollback_plan": "Restore declared revision r1 and rerun the immutable cohort.",
                "target_revision": "retriever-r2",
                "baseline_eval_id": baseline.id,
                "candidate_eval_id": after.id,
                "drift_report_id": drift.json()["id"],
            },
        )
        assert created.status_code == 201
        candidate = created.json()
        assert candidate["state"] == "proposed" and candidate["version"] == 1
        candidate_id = candidate["id"]

        assert (
            api.get(
                f"/api/evals/candidates/{candidate_id}?project_id=project-a",
                headers=foreign_headers,
            ).status_code
            == 404
        )
        approval = api.post(
            f"/api/evals/candidates/{candidate_id}/approval",
            headers=headers,
            json={"project_id": "project-a", "expected_version": 1},
        )
        assert approval.status_code == 201
        receipt = approval.json()
        alternate_receipt = api.post(
            f"/api/evals/candidates/{candidate_id}/approval",
            headers=headers,
            json={"project_id": "project-a", "expected_version": 1},
        ).json()
        # Existing approval endpoint makes the explicit human decision.
        decision = api.post(
            f"/api/chat/approve/{receipt['tool_call_id']}",
            headers=headers,
            json={"run_id": candidate_id, "approved": True},
        )
        assert decision.status_code == 200
        approved = api.post(
            f"/api/evals/candidates/{candidate_id}/approve",
            headers=headers,
            json={
                "project_id": "project-a",
                "expected_version": 1,
                "approval_id": receipt["approval_id"],
            },
        )
        assert approved.status_code == 200
        assert approved.json()["state"] == "approved"
        assert (
            api.portal.call(
                app.state.approval_repository.get_status,
                alternate_receipt["approval_id"],
                owner["user_id"],
            )
            is ApprovalStatus.CANCELLED
        )
        replay = api.post(
            f"/api/evals/candidates/{candidate_id}/approve",
            headers=headers,
            json={
                "project_id": "project-a",
                "expected_version": 1,
                "approval_id": receipt["approval_id"],
            },
        )
        assert replay.status_code == 409

        promoted = api.post(
            f"/api/evals/candidates/{candidate_id}/promote",
            headers=headers,
            json={"project_id": "project-a", "expected_version": 2},
        )
        assert promoted.status_code == 200
        assert promoted.json()["state"] == "promoted"
        assert promoted.json()["target_revision"] == "retriever-r2"
        assert (
            api.post(
                f"/api/evals/candidates/{candidate_id}/promote",
                headers=headers,
                json={"project_id": "project-a", "expected_version": 2},
            ).status_code
            == 409
        )

        rolled_back = api.post(
            f"/api/evals/candidates/{candidate_id}/rollback",
            headers=headers,
            json={
                "project_id": "project-a",
                "expected_version": 3,
                "reason_code": "regression_observed",
            },
        )
        assert rolled_back.status_code == 200
        assert rolled_back.json()["state"] == "rolled_back"

        rejected_candidate = api.post(
            "/api/evals/candidates",
            headers=headers,
            json={
                "project_id": "project-a",
                "candidate_type": "config",
                "change_summary": "Try another bounded retriever revision.",
                "proposal_metadata": {"component": "retriever", "revision_hash": "c" * 64},
                "rollback_plan": "Restore retriever-r2.",
                "target_revision": "retriever-r3",
                "baseline_eval_id": baseline.id,
                "candidate_eval_id": after.id,
                "drift_report_id": drift_id,
            },
        ).json()
        pending = api.post(
            f"/api/evals/candidates/{rejected_candidate['id']}/approval",
            headers=headers,
            json={"project_id": "project-a", "expected_version": 1},
        ).json()
        # Simulate a reload: reject without any frontend-held receipt/tool-call data.
        rejected = api.post(
            f"/api/evals/candidates/{rejected_candidate['id']}/reject",
            headers=headers,
            json={
                "project_id": "project-a",
                "expected_version": 1,
                "reason_code": "quality_regression",
            },
        )
        assert rejected.status_code == 200
        assert (
            api.portal.call(
                app.state.approval_repository.get_status,
                pending["approval_id"],
                owner["user_id"],
            )
            is ApprovalStatus.CANCELLED
        )

        async def event_count() -> int:
            async with app.state.conversations.session_factory() as session:
                return int(
                    await session.scalar(
                        select(func.count()).select_from(OptimizationCandidateEventRow)
                    )
                    or 0
                )

        assert api.portal.call(event_count) == 6

        raced_candidate = api.post(
            "/api/evals/candidates",
            headers=headers,
            json={
                "project_id": "project-a",
                "candidate_type": "config",
                "change_summary": "Race-test retriever revision.",
                "proposal_metadata": {"component": "retriever", "revision_hash": "d" * 64},
                "rollback_plan": "Restore retriever-r2.",
                "target_revision": "retriever-r4",
                "baseline_eval_id": baseline.id,
                "candidate_eval_id": after.id,
                "drift_report_id": drift_id,
            },
        ).json()
        original_reserve = app.state.approval_repository.reserve_in_session
        reservation_entered = asyncio.Event()
        release_reservation = asyncio.Event()

        async def paused_reserve(session, **kwargs):
            reservation_entered.set()
            await release_reservation.wait()
            return await original_reserve(session, **kwargs)

        monkeypatch.setattr(app.state.approval_repository, "reserve_in_session", paused_reserve)

        async def race_request_against_reject():
            request = asyncio.create_task(
                app.state.optimization_candidates.request_approval(
                    owner["user_id"],
                    raced_candidate["id"],
                    project_id="project-a",
                    expected_version=1,
                )
            )
            await reservation_entered.wait()
            reject = asyncio.create_task(
                app.state.optimization_candidates.reject(
                    owner["user_id"],
                    raced_candidate["id"],
                    project_id="project-a",
                    expected_version=1,
                    reason_code="quality_regression",
                )
            )
            await asyncio.sleep(0.05)
            assert not reject.done()
            release_reservation.set()
            approval_id, _ = await request
            result = await reject
            status = await app.state.approval_repository.get_status(approval_id, owner["user_id"])
            return result, status

        race_result, race_status = api.portal.call(race_request_against_reject)
        assert race_result.state.value == "rejected"
        assert race_status is ApprovalStatus.CANCELLED


def test_candidate_rejects_raw_prompt_metadata_and_is_authenticated(tmp_path) -> None:
    settings = Settings(
        llm_provider="mock",
        debug=True,
        memory_encryption_enabled=False,
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'candidate-errors.db'}",
    )
    app = create_app(settings)
    with TestClient(app) as api:
        body = {
            "project_id": "project-a",
            "candidate_type": "prompt",
            "change_summary": "Change prompt revision only.",
            "proposal_metadata": {"raw_prompt": "do not persist me"},
            "rollback_plan": "Restore prompt revision p1.",
            "target_revision": "prompt-p2",
            "baseline_eval_id": "missing-a",
            "candidate_eval_id": "missing-b",
        }
        assert api.post("/api/evals/candidates", json=body).status_code == 401
        owner = _register(api, "metadata-owner")
        response = api.post(
            "/api/evals/candidates",
            headers={"Authorization": f"Bearer {owner['access_token']}"},
            json=body,
        )
        # Sensitive content is rejected before evidence lookup and never persisted.
        assert response.status_code == 422
        assert "prompt" in response.json()["detail"]

        for alias in ("prompt_text", "api-key", "access_token", "authorization"):
            body["proposal_metadata"] = {alias: "not persisted"}
            response = api.post(
                "/api/evals/candidates",
                headers={"Authorization": f"Bearer {owner['access_token']}"},
                json=body,
            )
            assert response.status_code == 422
            assert "not allowed" in response.json()["detail"]

        body["proposal_metadata"] = {"template_revision": "alice@example.com"}
        response = api.post(
            "/api/evals/candidates",
            headers={"Authorization": f"Bearer {owner['access_token']}"},
            json=body,
        )
        assert response.status_code == 422
        assert response.json()["detail"] == "proposal_metadata contains sensitive data"

        body["proposal_metadata"] = {"template_revision": "template-v2"}
        body["change_summary"] = "Send findings to alice@example.com"
        response = api.post(
            "/api/evals/candidates",
            headers={"Authorization": f"Bearer {owner['access_token']}"},
            json=body,
        )
        assert response.status_code == 422
        assert response.json()["detail"] == "change_summary contains sensitive data"
