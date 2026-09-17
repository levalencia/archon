#!/usr/bin/env bash
set -Eeuo pipefail

SUBSCRIPTION_ID=${AZURE_SUBSCRIPTION_ID:?AZURE_SUBSCRIPTION_ID is required}
RESOURCE_GROUP=${AZURE_RESOURCE_GROUP:-cogentrex}
LOCATION=${AZURE_LOCATION:-swedencentral}
SSH_PUBLIC_KEY_FILE=${AZURE_SSH_PUBLIC_KEY_FILE:?AZURE_SSH_PUBLIC_KEY_FILE is required}
OUTPUT_FILE=${AZURE_OUTPUT_FILE:-.azure/deployment-outputs.json}

[[ -r "$SSH_PUBLIC_KEY_FILE" ]] || { printf 'SSH public key is not readable\n' >&2; exit 66; }
mkdir -p "$(dirname "$OUTPUT_FILE")"

az deployment group create \
  --subscription "$SUBSCRIPTION_ID" \
  --resource-group "$RESOURCE_GROUP" \
  --name "cogentrex-dev-infra" \
  --template-file infra/azure/main.bicep \
  --parameters location="$LOCATION" \
  --parameters adminSshPublicKey="$(<"$SSH_PUBLIC_KEY_FILE")" \
  --query properties.outputs \
  --output json > "$OUTPUT_FILE"
chmod 600 "$OUTPUT_FILE"

python3 - "$OUTPUT_FILE" <<'PY'
import json
import sys
from pathlib import Path

outputs = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
for required in (
    "vmName",
    "vmId",
    "publicIpAddress",
    "publicIpFqdn",
    "keyVaultName",
    "acrId",
    "acrName",
    "acrLoginServer",
    "githubIdentityClientId",
    "githubIdentityPrincipalId",
    "githubIdentityId",
):
    if not outputs.get(required, {}).get("value"):
        raise SystemExit(f"missing deployment output: {required}")
print("AZURE_PROVISION=PASS")
print(f"PUBLIC_HOSTNAME={outputs['publicIpFqdn']['value']}")
PY
