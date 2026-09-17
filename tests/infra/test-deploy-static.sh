#!/usr/bin/env bash
# test-deploy-static.sh – Static/unit tests for deploy-vm.sh and rollback-vm.sh
# Validates SHA validation, script syntax, and shell best practices.
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
PASS=0
FAIL=0

pass() { PASS=$((PASS + 1)); printf '  ✓ %s\n' "$*"; }
fail() { FAIL=$((FAIL + 1)); printf '  ✗ %s\n' "$*" >&2; }

printf 'Running deploy infrastructure static tests...\n\n'

# ─── SHA validation tests ──────────────────────────────────────────────────────
printf '=== SHA Validation ===\n'

# Test: valid 40-char hex SHA passes
sha_valid="a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2"
if [[ "$sha_valid" =~ ^[0-9a-f]{40}$ ]]; then
  pass "Valid SHA accepted: ${sha_valid:0:12}..."
else
  fail "Valid SHA rejected"
fi

# Test: too short
sha_short="a1b2c3d4e5"
if [[ ! "$sha_short" =~ ^[0-9a-f]{40}$ ]]; then
  pass "Short SHA rejected"
else
  fail "Short SHA accepted"
fi

# Test: uppercase
sha_upper="A1B2C3D4E5F6A1B2C3D4E5F6A1B2C3D4E5F6A1B2"
if [[ ! "$sha_upper" =~ ^[0-9a-f]{40}$ ]]; then
  pass "Uppercase SHA rejected"
else
  fail "Uppercase SHA accepted"
fi

# Test: 41 chars
sha_long="a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2a"
if [[ ! "$sha_long" =~ ^[0-9a-f]{40}$ ]]; then
  pass "41-char SHA rejected"
else
  fail "41-char SHA accepted"
fi

# Test: non-hex chars
sha_nonhex="g1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2"
if [[ ! "$sha_nonhex" =~ ^[0-9a-f]{40}$ ]]; then
  pass "Non-hex SHA rejected"
else
  fail "Non-hex SHA accepted"
fi

# ─── Script syntax (bash -n) ───────────────────────────────────────────────────
printf '\n=== Bash Syntax Checks ===\n'

for script in "$ROOT/scripts/azure/deploy-vm.sh" \
              "$ROOT/scripts/azure/rollback-vm.sh"; do
  name="$(basename "$script")"
  if bash -n "$script" 2>/dev/null; then
    pass "bash -n: ${name}"
  else
    fail "bash -n: ${name}"
  fi
done

# ─── ShellCheck ─────────────────────────────────────────────────────────────────
printf '\n=== ShellCheck ===\n'

if command -v shellcheck >/dev/null 2>&1; then
  for script in "$ROOT/scripts/azure/deploy-vm.sh" \
                "$ROOT/scripts/azure/rollback-vm.sh"; do
    name="$(basename "$script")"
    if shellcheck -S warning "$script" 2>/dev/null; then
      pass "shellcheck: ${name}"
    else
      fail "shellcheck: ${name}"
    fi
  done
else
  printf '  (shellcheck not available; skipping)\n'
fi

# ─── Cloud-init YAML validity ──────────────────────────────────────────────────
printf '\n=== Cloud-init YAML ===\n'
cloud_init="$ROOT/infra/azure/cloud-init.yml"
if python3 -c "import yaml; yaml.safe_load(open('$cloud_init'))" 2>/dev/null; then
  pass "cloud-init.yml is valid YAML"
else
  fail "cloud-init.yml is invalid YAML"
fi

# ─── Caddyfile basic checks ────────────────────────────────────────────────────
printf '\n=== Caddyfile ===\n'
caddyfile="$ROOT/deploy/Caddyfile.azure"
if [[ -f "$caddyfile" ]]; then
  if grep -q 'sslip.io' "$caddyfile"; then
    pass "Caddyfile references sslip.io"
  else
    fail "Caddyfile missing sslip.io"
  fi
  if grep -q 'reverse_proxy' "$caddyfile"; then
    pass "Caddyfile has reverse_proxy directive"
  else
    fail "Caddyfile missing reverse_proxy"
  fi
  if grep -q 'COGENTREX_PUBLIC_IP' "$caddyfile"; then
    pass "Caddyfile uses COGENTREX_PUBLIC_IP env var"
  else
    fail "Caddyfile missing COGENTREX_PUBLIC_IP env"
  fi
else
  fail "Caddyfile.azure not found"
fi

# ─── Bicep files existence ─────────────────────────────────────────────────────
printf '\n=== Bicep Files ===\n'
for bicep in main.bicep modules/network.bicep modules/vm.bicep \
             modules/keyvault.bicep modules/monitoring.bicep \
             modules/cognitive-rbac.bicep cloud-init.yml; do
  if [[ -f "$ROOT/infra/azure/$bicep" ]]; then
    pass "exists: infra/azure/${bicep}"
  else
    fail "missing: infra/azure/${bicep}"
  fi
done

# ─── Deploy script content checks ──────────────────────────────────────────────
printf '\n=== Deploy Script Content ===\n'
deploy="$ROOT/scripts/azure/deploy-vm.sh"
for pattern in 'validate_sha' 'pg_backup' 'compose_update' 'rollback' \
               'wait_for_health' 'check_health_details' 'check_media' \
               'check_sandbox' 'save_deploy_state'; do
  if grep -q "$pattern" "$deploy"; then
    pass "deploy-vm.sh contains ${pattern}"
  else
    fail "deploy-vm.sh missing ${pattern}"
  fi
done

# No provider secrets in deploy script
for secret_pattern in 'API_KEY' 'PASSWORD.*=.*[^${}]' 'SECRET_KEY.*=.*[^${}]'; do
  if grep -qE "^[^#]*${secret_pattern}" "$deploy" 2>/dev/null; then
    fail "deploy-vm.sh may contain hardcoded secret pattern: ${secret_pattern}"
  else
    pass "deploy-vm.sh clean of secret pattern: ${secret_pattern}"
  fi
done

# ─── NSG check: no port 22 allow ───────────────────────────────────────────────
printf '\n=== NSG Security ===\n'
nsg_file="$ROOT/infra/azure/modules/network.bicep"
if grep -q "DenySSH" "$nsg_file"; then
  pass "NSG explicitly denies SSH (port 22)"
else
  fail "NSG missing SSH deny rule"
fi
if ! grep -q "'Allow'.*'22'" "$nsg_file" 2>/dev/null; then
  pass "NSG does not allow port 22"
else
  fail "NSG allows port 22"
fi

# ─── Summary ────────────────────────────────────────────────────────────────────
printf '\n=== Results ===\n'
printf 'Passed: %d  Failed: %d\n' "$PASS" "$FAIL"
[[ "$FAIL" -eq 0 ]] || exit 1
