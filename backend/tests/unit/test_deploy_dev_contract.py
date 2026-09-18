"""Static contract tests for the Azure dev deployment workflow.

These tests validate the deploy-dev.yml workflow structure without
requiring Azure credentials or a running environment.
"""

from __future__ import annotations

import pathlib
import re

import pytest
import yaml

REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
DEPLOY_DEV_PATH = REPO_ROOT / ".github" / "workflows" / "deploy-dev.yml"
CI_PATH = REPO_ROOT / ".github" / "workflows" / "ci.yml"

# PyYAML parses the bare key `on` as boolean True; helper to normalise.
_ON = True  # yaml.safe_load('on: ...') stores key as True


@pytest.fixture(scope="module")
def deploy_dev() -> dict:
    return yaml.safe_load(DEPLOY_DEV_PATH.read_text())


@pytest.fixture(scope="module")
def ci_workflow() -> dict:
    return yaml.safe_load(CI_PATH.read_text())


# ── Trigger contracts ────────────────────────────────────────────────


class TestTriggers:
    def test_push_only_dev_branch(self, deploy_dev: dict) -> None:
        assert deploy_dev[_ON]["push"]["branches"] == ["dev"]

    def test_workflow_dispatch_enabled(self, deploy_dev: dict) -> None:
        assert (
            "workflow_dispatch" in deploy_dev[_ON]
            or deploy_dev[_ON].get("workflow_dispatch") is None
        )

    def test_no_pull_request_target(self, deploy_dev: dict) -> None:
        assert "pull_request_target" not in deploy_dev[_ON]

    def test_no_pull_request_trigger(self, deploy_dev: dict) -> None:
        assert "pull_request" not in deploy_dev[_ON]


# ── Permissions contracts ────────────────────────────────────────────


class TestPermissions:
    def test_contents_read(self, deploy_dev: dict) -> None:
        assert deploy_dev["permissions"]["contents"] == "read"

    def test_id_token_write(self, deploy_dev: dict) -> None:
        assert deploy_dev["permissions"]["id-token"] == "write"

    def test_minimal_permissions(self, deploy_dev: dict) -> None:
        assert set(deploy_dev["permissions"].keys()) == {"contents", "id-token"}


# ── OIDC contracts ───────────────────────────────────────────────────


class TestOIDCLogin:
    def test_uses_azure_login_v2(self, deploy_dev: dict) -> None:
        deploy_steps = deploy_dev["jobs"]["deploy"]["steps"]
        login_steps = [s for s in deploy_steps if s.get("uses", "").startswith("azure/login@")]
        assert len(login_steps) == 1
        assert login_steps[0]["uses"] == "azure/login@v2"

    def test_oidc_vars_not_secrets(self, deploy_dev: dict) -> None:
        """OIDC must use repository vars, not secrets."""
        raw = DEPLOY_DEV_PATH.read_text()
        assert "secrets.AZURE_CLIENT_ID" not in raw
        assert "secrets.AZURE_TENANT_ID" not in raw
        assert "secrets.AZURE_SUBSCRIPTION_ID" not in raw
        assert "vars.AZURE_CLIENT_ID" in raw
        assert "vars.AZURE_TENANT_ID" in raw
        assert "vars.AZURE_SUBSCRIPTION_ID" in raw

    def test_no_azure_credentials_secret(self, deploy_dev: dict) -> None:
        raw = DEPLOY_DEV_PATH.read_text()
        assert "AZURE_CREDENTIALS" not in raw


# ── Deployment safety contracts ──────────────────────────────────────


class TestDeploySafety:
    def test_deploy_environment_is_development(self, deploy_dev: dict) -> None:
        assert deploy_dev["jobs"]["deploy"]["environment"] == "development"

    def test_deploy_depends_on_image_build(self, deploy_dev: dict) -> None:
        needs = deploy_dev["jobs"]["deploy"]["needs"]
        if isinstance(needs, str):
            needs = [needs]
        assert "backend-image" in needs

    def test_sha_passed_as_parameter_not_interpolated(self, deploy_dev: dict) -> None:
        """The SHA must be passed via --parameters, never interpolated in --scripts."""
        deploy_steps = deploy_dev["jobs"]["deploy"]["steps"]
        run_cmd_steps = [s for s in deploy_steps if "az vm run-command" in s.get("run", "")]
        assert len(run_cmd_steps) == 1
        run_block = run_cmd_steps[0]["run"]
        # --scripts must NOT contain ${{ github.sha }} (shell injection vector)
        scripts_match = re.search(r"--scripts\s+'([^']*)'", run_block)
        assert scripts_match is not None, "--scripts should use single-quoted literal"
        scripts_body = scripts_match.group(1)
        assert "${{" not in scripts_body, (
            "Scripts body must not contain GitHub expression interpolation"
        )
        # SHA delivered via --parameters
        assert "--parameters" in run_block

    def test_concurrency_prevents_parallel_deploys(self, deploy_dev: dict) -> None:
        assert "concurrency" in deploy_dev
        assert deploy_dev["concurrency"].get("cancel-in-progress") is False

    def test_evidence_artifact_uploaded(self, deploy_dev: dict) -> None:
        deploy_steps = deploy_dev["jobs"]["deploy"]["steps"]
        artifact_steps = [s for s in deploy_steps if "upload-artifact" in s.get("uses", "")]
        assert len(artifact_steps) >= 1
        assert artifact_steps[0]["uses"] == "actions/upload-artifact@v4"

    def test_run_command_executes_bash_and_propagates_remote_exit(self, deploy_dev: dict) -> None:
        raw = DEPLOY_DEV_PATH.read_text()
        assert "/bin/bash /tmp/cogentrex-deploy-vm.sh" in raw
        assert "COGENTREX_RUN_COMMAND_EXIT=" in raw
        assert "--output none" not in raw

    def test_smoke_fails_before_parsing_when_health_never_succeeds(self, deploy_dev: dict) -> None:
        raw = DEPLOY_DEV_PATH.read_text()
        assert "health_ok=false" in raw
        assert 'test "$health_ok" = true' in raw


# ── CI trigger contract ──────────────────────────────────────────────


class TestCITrigger:
    def test_ci_pr_targets_include_dev(self, ci_workflow: dict) -> None:
        pr_branches = ci_workflow[_ON]["pull_request"]["branches"]
        assert "dev" in pr_branches

    def test_ci_pr_targets_include_main(self, ci_workflow: dict) -> None:
        pr_branches = ci_workflow[_ON]["pull_request"]["branches"]
        assert "main" in pr_branches


# ── Action version pinning contracts ─────────────────────────────────


class TestActionVersionPinning:
    def test_action_versions_match_ci(self, deploy_dev: dict, ci_workflow: dict) -> None:
        """Actions shared between CI and deploy-dev must use the same version."""

        def _collect_uses(workflow: dict) -> dict[str, str]:
            uses: dict[str, str] = {}
            for job in workflow.get("jobs", {}).values():
                for step in job.get("steps", []):
                    if "uses" in step:
                        action, version = step["uses"].rsplit("@", 1)
                        uses[action] = version
            return uses

        ci_uses = _collect_uses(ci_workflow)
        dev_uses = _collect_uses(deploy_dev)
        shared = set(ci_uses) & set(dev_uses)
        for action in shared:
            assert ci_uses[action] == dev_uses[action], (
                f"{action}: CI pins @{ci_uses[action]} but deploy-dev pins @{dev_uses[action]}"
            )
