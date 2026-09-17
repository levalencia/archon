# Cogentrex Azure Deployment Plan

Status: Validated — deployment authorized
Date: 2026-09-17
Branch: `feat/azure-public-deployment`
Source revision: `048706a7a9b4f29eecb631659b236ad5a672f2c6`
Target subscription: `6331e1e6-713f-4b7a-8665-99dfd16207c5`
Target resource group: `cogentrex`
Preferred region: Sweden Central, subject to policy/quota/service checks

This plan supersedes the 2026-08-27 local-only/deferred decision after Luis explicitly authorized Azure resource creation, GitHub Actions deployment, and a public development environment on 2026-09-17. The previous plan remains available in Git history.

## 1. Goal

Publish Cogentrex through GitHub Actions while preserving the existing seven-service behavior and the sandbox controls: network isolation, custom seccomp, capability drop, read-only filesystem, resource limits, and Unix-socket IPC.

## 2. Required delivery behavior

- Pull requests target `dev` and run the complete CI gate.
- A successful merge to `dev` deploys an immutable revision to a live development URL.
- Production promotion is a separate `dev` to `main` pull request and protected deployment.
- GitHub authenticates to Azure through OIDC; no long-lived Azure credential secret.
- Images are built in GitHub Actions, pushed to ACR with immutable SHA tags/digests, and pulled by managed identity.
- Deployment includes readiness, authenticated browser smoke, rollback and evidence capture.
- Existing local operation remains supported and unchanged.

## 3. Architecture decision

### Recommended first target: Azure Linux VM plus Docker Compose

Rationale:

- Preserves current Docker sandbox semantics with minimal code change.
- Avoids falsely claiming equivalent sandbox isolation on Azure Container Apps.
- Allows the existing gateway, frontend, backend, PostgreSQL, Redis, sandbox and OTEL services to run together.
- Provides a bounded dev/public deployment while a later managed-services migration is evaluated separately.

### Rejected for initial parity target

- Azure Container Apps sidecar sandbox: lacks documented equivalents for custom seccomp, `network_mode:none`, `cap_drop:ALL` and read-only root filesystem.
- AKS initial target: can preserve the controls but introduces disproportionate cost and Kubernetes/operations scope for the first public deployment.

## 4. Proposed Azure resources

- Existing resource group `cogentrex`.
- Existing AI Services account/project `cogentrex` in Sweden Central.
- Azure Container Registry.
- Linux VM sized after measured local resource usage; no SKU selected before quota/pricing validation.
- Managed OS/data disk for Compose volumes.
- Static public IP.
- Network Security Group exposing only HTTP/HTTPS; no public SSH if Azure Run Command is sufficient.
- Key Vault for runtime secrets, accessed by VM managed identity.
- Log Analytics/Application Insights destination for OTEL.
- Azure DNS records only if the existing registrar configuration is intentionally migrated; otherwise preserve GoDaddy DNS and update only required records.
- Azure Budget/alerts before public live-provider enablement.

## 5. Public application profile

- `dev.cogentrex.com`: development deployment after merge to `dev`.
- `cogentrex.com`: production promotion after explicit approval.
- Rich learning media installed and mounted read-only.
- Initial infrastructure smoke uses deterministic mock mode.
- Approved development live provider: the existing Foundry AI Services account in Sweden Central, OpenAI-compatible endpoint `https://cogentrex.services.ai.azure.com/openai/v1`, deployment `DeepSeek-V4-Flash`.
- Authentication uses the VM system-assigned Managed Identity and the `https://ai.azure.com/.default` scope; no provider API key is copied to GitHub, disk, logs, or Key Vault.
- Public live access remains gated by rate, monetary-budget and abuse-control acceptance.

## 6. CI/CD design

1. PR to `dev`: current backend/frontend gates plus Compose config, image, sandbox and security checks.
2. Merge to `dev`: build gateway/backend/frontend/sandbox images, push immutable SHA tags to ACR.
3. Azure OIDC login.
4. VM managed identity pulls images.
5. Protected env generated from Key Vault references on VM without rendering secret values.
6. Compose pull/up with migration preflight and backup.
7. Readiness, auth, `/learn`, media, sandbox, OTEL and browser smoke.
8. On failure, restore previous image digest/Compose revision.
9. Record deployed SHA, image digests and smoke evidence.
10. PR from `dev` to `main`: repeat gates, protected production approval, deploy to `cogentrex.com`.

## 7. Required code/repository changes

- Cloud Compose override using registry images instead of local builds.
- Environment template containing secret references only.
- Deployment and rollback scripts with exact project scoping.
- Bicep for Azure resources and RBAC.
- GitHub Actions OIDC workflows for CI and deploy.
- Dev/production GitHub Environments and branch protection/rulesets.
- Domain/TLS configuration and smoke tests.
- Public-demo budget/rate/signup policy before live-provider access.
- Documentation and evidence updates only after observed deployment.

## 8. Acceptance gates

- Existing local tests and local-stack behavior remain green.
- Sandbox probes pass on the Azure host with real `network:none`, seccomp, read-only filesystem, capability and resource limits.
- No secret is printed, committed or stored as a long-lived GitHub Azure credential.
- Dev deployment is reachable through HTTPS and reports the exact deployed SHA.
- `/healthz` and `/readyz` pass.
- Authentication and tenant boundaries pass.
- `/learn`, rich media and signed streaming pass.
- One safe sandbox execution passes and network egress is denied.
- OTEL reaches Application Insights without message content.
- Failed deployment rollback is rehearsed.
- Provider-live access is not enabled until cost/abuse gates pass.

## 9. Approved decisions and remaining credential boundary

- Approved target: `dev.cogentrex.com` first; production `cogentrex.com` later.
- Approved architecture: Azure VM plus Docker Compose to preserve sandbox parity.
- Approved branch model: permanent `dev` integration branch; production promotion by `dev` to `main` pull request.
- Cost posture: smallest VM SKU that passes measured seven-service acceptance; exact SKU subject to quota and memory validation.
- DeepSeek uses Managed Identity; no provider credential transfer is required. Any future provider that requires a static credential remains a user-managed Key Vault input.

## 10. Workflow state

- [x] Existing architecture and CI audited.
- [x] Initial deployment-plan skeleton created.
- [x] Requirements approved.
- [x] Azure policies, quotas, region and SKU validated.
- [x] Infrastructure generated.
- [x] Application changes implemented test-first.
- [x] Azure validation completed and recorded.
- [x] Deployment approved.
- [ ] Development deployment verified.
- [ ] Production cutover approved and verified.

## 11. Validation proof

- `az bicep build --file infra/azure/main.bicep`: PASS.
- Azure deployment group `what-if`: PASS; existing AI Services resources ignored, new VM/network/ACR/Key Vault/monitoring resources proposed.
- Azure template validation: PASS.
- Formal post-plan Azure template validation: PASS (`Succeeded`, no error).
- First provisioning attempt: FAIL before application deployment because the generated Key Vault name exceeded Azure's 24-character limit; VM/network/ACR/monitoring were created successfully and retained.
- Recovery: added a deterministic Key Vault naming regression test, shortened the generated name to `ctxkv` plus an eight-character suffix, then reran Bicep build, focused tests, Azure validation, and what-if: PASS.
- Azure static deployment contracts: 35 PASS.
- Focused backend deployment/provider/pricing contracts: 92 PASS.
- Full backend suite: 1,815 PASS, 7 skipped.
- Canonical unit gate: 775 PASS, 1,047 deselected, 66.83% coverage.
- Frontend check, Vitest and production build: PASS.
- No Azure resources have been created by this plan yet.
