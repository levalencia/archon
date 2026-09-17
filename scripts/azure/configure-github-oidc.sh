#!/usr/bin/env bash
set -Eeuo pipefail

SUBSCRIPTION_ID=${AZURE_SUBSCRIPTION_ID:?AZURE_SUBSCRIPTION_ID is required}
RESOURCE_GROUP=${AZURE_RESOURCE_GROUP:-cogentrex}
OUTPUT_FILE=${AZURE_OUTPUT_FILE:-.azure/deployment-outputs.json}
GITHUB_REPOSITORY=${GITHUB_REPOSITORY:-levalencia/cogentrex}
GITHUB_ENVIRONMENT=${GITHUB_ENVIRONMENT:-development}
APP_DISPLAY_NAME=${AZURE_GITHUB_APP_NAME:-cogentrex-github-dev}

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
RG_ID=$(az group show --subscription "$SUBSCRIPTION_ID" --name "$RESOURCE_GROUP" --query id -o tsv)

APP_ID=$(az ad app list --filter "displayName eq '$APP_DISPLAY_NAME'" --query '[0].appId' -o tsv)
if [[ -z "$APP_ID" ]]; then
  APP_ID=$(az ad app create --display-name "$APP_DISPLAY_NAME" --query appId -o tsv)
fi
APP_OBJECT_ID=$(az ad app show --id "$APP_ID" --query id -o tsv)
SP_OBJECT_ID=$(az ad sp list --filter "appId eq '$APP_ID'" --query '[0].id' -o tsv)
if [[ -z "$SP_OBJECT_ID" ]]; then
  SP_OBJECT_ID=$(az ad sp create --id "$APP_ID" --query id -o tsv)
fi

credential_name="github-cogentrex-development"
existing=$(az ad app federated-credential list --id "$APP_OBJECT_ID" \
  --query "[?name=='$credential_name'] | length(@)" -o tsv)
if [[ "$existing" == "0" ]]; then
  credential_file=$(mktemp)
  trap 'rm -f "$credential_file"' EXIT
  python3 - "$credential_file" "$credential_name" "$GITHUB_REPOSITORY" "$GITHUB_ENVIRONMENT" <<'PY'
import json
import sys
from pathlib import Path
path, name, repository, environment = sys.argv[1:]
Path(path).write_text(json.dumps({
    "name": name,
    "issuer": "https://token.actions.githubusercontent.com",
    "subject": f"repo:{repository}:environment:{environment}",
    "audiences": ["api://AzureADTokenExchange"],
}), encoding="utf-8")
PY
  az ad app federated-credential create --id "$APP_OBJECT_ID" \
    --parameters "$credential_file" --output none
fi

ensure_role() {
  local role="$1"
  local scope="$2"
  local count
  count=$(az role assignment list --assignee-object-id "$SP_OBJECT_ID" --scope "$scope" \
    --query "[?roleDefinitionName=='$role'] | length(@)" -o tsv)
  if [[ "$count" == "0" ]]; then
    az role assignment create --assignee-object-id "$SP_OBJECT_ID" \
      --assignee-principal-type ServicePrincipal --role "$role" --scope "$scope" --output none
  fi
}

ensure_role "Virtual Machine Contributor" "$VM_ID"
ensure_role "AcrPush" "$ACR_ID"
ensure_role "Reader" "$RG_ID"

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
