#!/usr/bin/env bash
set -Eeuo pipefail

SUBSCRIPTION_ID=${AZURE_SUBSCRIPTION_ID:?AZURE_SUBSCRIPTION_ID is required}
RESOURCE_GROUP=${AZURE_RESOURCE_GROUP:-cogentrex}
OUTPUT_FILE=${AZURE_OUTPUT_FILE:-.azure/deployment-outputs.json}
GITHUB_REPOSITORY=${GITHUB_REPOSITORY:-levalencia/cogentrex}
GITHUB_ENVIRONMENT=${GITHUB_ENVIRONMENT:-development}


[[ -r "$OUTPUT_FILE" ]] || { printf 'Deployment outputs are missing\n' >&2; exit 66; }

value() {
  python3 - "$OUTPUT_FILE" "$1" <<'PY'
import json
import sys
from pathlib import Path
outputs = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
print(outputs[sys.argv[2]]["value"])
PY
}

TENANT_ID=$(az account show --subscription "$SUBSCRIPTION_ID" --query tenantId -o tsv)
VM_NAME=$(value vmName)
VM_ID=$(value vmId)
PUBLIC_HOSTNAME=$(value publicIpFqdn)
KEY_VAULT_NAME=$(value keyVaultName)
ACR_ID=$(value acrId)
ACR_NAME=$(value acrName)
ACR_LOGIN_SERVER=$(value acrLoginServer)
APP_ID=$(value githubIdentityClientId)
SP_OBJECT_ID=$(value githubIdentityPrincipalId)
RG_ID=$(az group show --subscription "$SUBSCRIPTION_ID" --name "$RESOURCE_GROUP" --query id -o tsv)

verify_role() {
  local role="$1"
  local scope="$2"
  local count
  count=$(az role assignment list --assignee-object-id "$SP_OBJECT_ID" --scope "$scope" \
    --query "[?roleDefinitionName=='$role'] | length(@)" -o tsv)
  [[ "$count" != "0" ]] || {
    printf 'Missing role %s at scope %s\n' "$role" "$scope" >&2
    exit 1
  }
}

verify_role "Virtual Machine Contributor" "$VM_ID"
verify_role "AcrPush" "$ACR_ID"
verify_role "Reader" "$RG_ID"

gh api --method PUT "repos/${GITHUB_REPOSITORY}/environments/${GITHUB_ENVIRONMENT}" >/dev/null
set_var() {
  gh variable set "$1" --body "$2" --env "$GITHUB_ENVIRONMENT" --repo "$GITHUB_REPOSITORY"
}
set_var AZURE_CLIENT_ID "$APP_ID"
set_var AZURE_TENANT_ID "$TENANT_ID"
set_var AZURE_SUBSCRIPTION_ID "$SUBSCRIPTION_ID"
set_var AZURE_DEV_RESOURCE_GROUP "$RESOURCE_GROUP"
set_var AZURE_DEV_VM_NAME "$VM_NAME"
set_var AZURE_DEV_PUBLIC_HOSTNAME "$PUBLIC_HOSTNAME"
set_var AZURE_DEV_SMOKE_URL "https://${PUBLIC_HOSTNAME}"
set_var AZURE_DEV_KEY_VAULT_NAME "$KEY_VAULT_NAME"
set_var AZURE_DEV_ACR_NAME "$ACR_NAME"
set_var AZURE_DEV_ACR_LOGIN_SERVER "$ACR_LOGIN_SERVER"

printf 'GITHUB_OIDC=PASS\n'
printf 'DEVELOPMENT_URL=https://%s\n' "$PUBLIC_HOSTNAME"
