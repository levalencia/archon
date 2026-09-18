"""Static contracts for the Azure dev deployment lane.

These tests intentionally validate security and parity properties without requiring
Azure credentials. Live Azure evidence is recorded separately in the deployment plan.
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
AZURE = ROOT / "infra" / "azure"
WORKFLOWS = ROOT / ".github" / "workflows"


def _read(path: Path) -> str:
    assert path.is_file(), f"missing deployment artifact: {path.relative_to(ROOT)}"
    return path.read_text(encoding="utf-8")


def test_deployment_plan_is_approved_and_preserves_sandbox_parity() -> None:
    plan = _read(ROOT / ".azure" / "deployment-plan.md")
    assert "Status: Development deployment verified" in plan
    assert "network_mode:none" in plan
    assert "custom seccomp" in plan
    assert "dev.cogentrex.com" in plan
    assert "Provider-live access is not enabled" in plan


def test_bicep_declares_hardened_vm_boundary_without_embedded_secrets() -> None:
    bicep = "\n".join(path.read_text() for path in sorted(AZURE.rglob("*.bicep")))
    lowered = bicep.lower()
    for resource_type in (
        "microsoft.network/virtualnetworks",
        "microsoft.network/networksecuritygroups",
        "microsoft.network/publicipaddresses",
        "microsoft.compute/virtualmachines",
        "microsoft.managedidentity/userassignedidentities",
        "microsoft.containerregistry/registries",
        "microsoft.keyvault/vaults",
        "microsoft.operationalinsights/workspaces",
    ):
        assert resource_type in lowered
    assert "standard_b2s" in lowered
    assert "disablepasswordauthentication: true" in lowered
    network = _read(AZURE / "modules" / "network.bicep")
    assert "DenySSH" in network
    assert "destinationPortRange: '22'" in network
    assert "password=" not in lowered
    assert "api_key" not in lowered


def test_key_vault_name_stays_within_azure_length_limit() -> None:
    main = _read(AZURE / "main.bicep")
    assert "var kvName = 'ctxkv${take(nameSuffix, 8)}'" in main
    assert "${prefix}-kv-${nameSuffix}" not in main


def test_same_sha_reconciles_runtime_configuration() -> None:
    deploy = _read(ROOT / "scripts" / "azure" / "deploy-vm.sh")
    same_sha = deploy.split('if [[ "$previous_sha" == "$target_sha" ]]', 1)[1].split("\n  fi", 1)[0]
    assert "generate_env" in same_sha
    assert "compose_update" in same_sha
    assert "configure_caddy" in same_sha


def test_bootstrap_installs_docker_caddy_and_uses_managed_identity() -> None:
    bootstrap = _read(AZURE / "cloud-init.yml")
    assert "docker-ce" in bootstrap
    assert "InstallAzureCLIDeb" in bootstrap
    assert "/opt/cogentrex" in bootstrap
    assert "ssh" not in bootstrap.lower()
    deploy = _read(ROOT / "scripts" / "azure" / "deploy-vm.sh")
    assert "caddy:2.10.2-alpine@sha256:" in deploy


def test_deploy_script_is_sha_pinned_backed_up_and_idempotent() -> None:
    deploy = _read(ROOT / "scripts" / "azure" / "deploy-vm.sh")
    assert "^[0-9a-f]{40}$" in deploy
    assert 'git -C "$repo_dir" checkout --detach --force' in deploy
    assert "pg_dump" in deploy
    assert "docker compose" in deploy
    assert "--no-build" in deploy
    assert "docker-compose.azure.yml" in deploy
    assert "az acr login" in deploy
    assert "healthz" in deploy
    assert "readyz" in deploy
    assert "sandbox" in deploy
    assert "rollback" in deploy.lower()
    assert "set -Eeuo pipefail" in deploy
    assert '"$release_script" install' in deploy
    assert '--target "$MEDIA_ROOT"' in deploy
    assert "installed_source" in deploy
    assert "desired_source" in deploy
    assert '"$installed_source" == "$desired_source"' in deploy
    assert "Backup failed; proceeding" not in deploy
    assert "check_sandbox || true" not in deploy
    assert 'chmod -R u+rwX,go+rX "$MEDIA_ROOT"' in deploy
    assert "set_env_value COGENTREX_LLM_PROVIDER openai" in deploy
    assert "set_env_value COGENTREX_LLM_AUTH_MODE azure_identity" in deploy
    assert "DeepSeek-V4-Flash" in deploy
    assert "/etc/caddy/Caddyfile" in deploy
    assert "caddy:2.10.2-alpine@sha256:" in deploy
    assert '"$caddy_image" caddy validate' in deploy
    assert '"$caddy_image" caddy run' in deploy
    assert "--network host" in deploy


def test_dev_workflow_uses_oidc_and_never_long_lived_azure_credentials() -> None:
    workflow = _read(WORKFLOWS / "deploy-dev.yml")
    assert "id-token: write" in workflow
    assert "contents: read" in workflow
    assert "azure/login" in workflow
    assert "AZURE_CLIENT_ID" in workflow
    assert "AZURE_TENANT_ID" in workflow
    assert "AZURE_SUBSCRIPTION_ID" in workflow
    assert "AZURE_CREDENTIALS" not in workflow
    assert "branches: [dev]" in workflow
    assert "environment: development" in workflow
    assert "github.sha" in workflow
    assert "vm run-command invoke" in workflow
    assert 'show "$1:scripts/azure/deploy-vm.sh"' in workflow
    assert "/tmp/cogentrex-deploy-vm.sh" in workflow
    assert "docker-compose.prod.yml" not in workflow
    assert "az acr login" in workflow
    assert workflow.count("docker push") >= 3


def test_github_oidc_uses_federated_managed_identity_without_directory_app_registration() -> None:
    bicep = "\n".join(path.read_text() for path in sorted(AZURE.rglob("*.bicep"))).lower()
    configure = _read(ROOT / "scripts" / "azure" / "configure-github-oidc.sh")
    assert "userassignedidentities/federatedidentitycredentials" in bicep
    main = _read(AZURE / "main.bicep")
    assert "repo:levalencia@6962857/cogentrex@1342041970:environment:development" in main
    assert "githubIdentityClientId" in _read(AZURE / "main.bicep")
    assert "az ad app" not in configure
    assert "az ad sp" not in configure
    assert "AZURE_CLIENT_ID" in configure


def test_backend_image_contains_azure_identity_runtime_dependency() -> None:
    pyproject = _read(ROOT / "backend" / "pyproject.toml")
    runtime_dependencies = pyproject.split("[project.optional-dependencies]", 1)[0]
    assert "azure-identity" in runtime_dependencies


def test_compose_passes_managed_identity_auth_mode() -> None:
    compose = _read(ROOT / "docker-compose.local.yml")
    assert "COGENTREX_LLM_AUTH_MODE" in compose
    assert "COGENTREX_OPENAI_NATIVE_TOOLS_ENABLED" in compose


def test_ci_runs_for_pull_requests_targeting_dev() -> None:
    ci = _read(WORKFLOWS / "ci.yml")
    assert "branches: [main, dev]" in ci


def test_cloud_deployment_keeps_local_compose_as_parity_target() -> None:
    deploy = _read(ROOT / "scripts" / "azure" / "deploy-vm.sh")
    assert "docker-compose.local.yml" in deploy
    for service in (
        "gateway",
        "frontend",
        "backend",
        "sandbox-runner",
        "postgres",
        "redis",
        "otel-collector",
    ):
        assert service in _read(ROOT / "docker-compose.local.yml")
