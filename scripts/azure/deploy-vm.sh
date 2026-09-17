#!/usr/bin/env bash
# deploy-vm.sh – Idempotent parity-preserving deployment for Cogentrex Azure VM.
# Validates a 40-char SHA, clones/fetches a public repo, generates protected env
# via canonical tooling, runs pg_dump backup before update, docker compose update
# preserving volumes, health/ready/media/sandbox checks, and rolls back on failure.
#
# Usage: deploy-vm.sh <40-char-SHA> [--repo URL] [--branch BRANCH]
#
# Environment:
#   COGENTREX_APP_ROOT   – application root (default: /opt/cogentrex)
#   COGENTREX_REPO_URL   – public git repo URL
#   COGENTREX_PUBLIC_IP   – VM public IP for sslip.io hostname
#   COGENTREX_OPENAI_ENDPOINT – Managed Identity OpenAI endpoint
#   COGENTREX_OPENAI_MODEL    – Model deployment name
#   APPLICATIONINSIGHTS_CONNECTION_STRING – App Insights connection string
set -Eeuo pipefail
shopt -s inherit_errexit

# ─── Constants ──────────────────────────────────────────────────────────────────

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export SCRIPT_DIR
readonly APP_ROOT="${COGENTREX_APP_ROOT:-/opt/cogentrex}"
readonly REPO_URL="${COGENTREX_REPO_URL:-https://github.com/levalencia/cogentrex.git}"
readonly STATE_DIR="${XDG_STATE_HOME:-$APP_ROOT/.state}"
readonly BACKUP_DIR="${APP_ROOT}/backups"
readonly DEPLOY_STATE="${STATE_DIR}/deploy.env"
readonly TMPDIR_PERSIST="${TMPDIR:-/var/tmp/cogentrex}"
readonly COMPOSE_PROJECT="cogentrex-azure"
readonly COMPOSE_ENV_FILE="${APP_ROOT}/.env.azure"
readonly COMPOSE_FILE_LOCAL="docker-compose.local.yml"
readonly MEDIA_ROOT="${APP_ROOT}/media"
# Media marker used by install_learning_media_if_absent
export LEARNING_MEDIA_MARKER="cogentrex.learning-library/v1"

# ─── Helpers ────────────────────────────────────────────────────────────────────

log() { printf '[%s] %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*"; }
die() { log "FATAL: $*" >&2; exit 1; }

validate_sha() {
  local sha="$1"
  if [[ ! "$sha" =~ ^[0-9a-f]{40}$ ]]; then
    die "Invalid SHA: must be exactly 40 lowercase hex characters, got '${sha}'"
  fi
}

current_deployed_sha() {
  if [[ -f "$DEPLOY_STATE" ]]; then
    # shellcheck disable=SC1090
    (source "$DEPLOY_STATE" && printf '%s' "${COGENTREX_DEPLOYED_SHA:-}")
  fi
}

save_deploy_state() {
  local sha="$1"
  local ts
  ts="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  mkdir -p "$(dirname "$DEPLOY_STATE")"
  local tmp
  tmp="$(mktemp "${DEPLOY_STATE}.XXXXXX")"
  chmod 600 "$tmp"
  {
    printf 'COGENTREX_DEPLOYED_SHA=%s\n' "$sha"
    printf 'COGENTREX_DEPLOY_TIMESTAMP=%s\n' "$ts"
    printf 'COGENTREX_COMPOSE_PROJECT=%s\n' "$COMPOSE_PROJECT"
  } > "$tmp"
  mv -f "$tmp" "$DEPLOY_STATE"
  chmod 600 "$DEPLOY_STATE"
}

# ─── Clone / Fetch ──────────────────────────────────────────────────────────────

ensure_repo() {
  local sha="$1"
  local repo_dir="${APP_ROOT}/repo"

  if [[ -d "${repo_dir}/.git" ]]; then
    log "Fetching latest from origin..."
    git -C "$repo_dir" fetch origin --prune
  else
    log "Cloning repository..."
    git clone "$REPO_URL" "$repo_dir"
  fi

  log "Checking out SHA ${sha}..."
  git -C "$repo_dir" checkout "$sha" --force
  git -C "$repo_dir" submodule update --init --recursive
}

# ─── Learning Media ─────────────────────────────────────────────────────────────

install_learning_media_if_absent() {
  local marker_file="${MEDIA_ROOT}/.cogentrex-learning-library"
  if [[ -f "$marker_file" ]]; then
    log "Learning media already installed."
    return 0
  fi

  # Check if release artifact exists in repo
  local repo_dir="${APP_ROOT}/repo"
  local release_script="${repo_dir}/scripts/learning-media-release.py"
  if [[ -x "$release_script" ]] || [[ -f "$release_script" ]]; then
    log "Installing learning media from release script..."
    python3 "$release_script" --output-dir "$MEDIA_ROOT" || {
      log "WARNING: Learning media installation failed; continuing without media."
      return 0
    }
  else
    log "No learning media release script found; skipping media installation."
  fi
}

# ─── Protected Env Generation ───────────────────────────────────────────────────

generate_env() {
  local repo_dir="${APP_ROOT}/repo"
  local env_gen="${repo_dir}/scripts/generate-local-env.py"

  if [[ ! -f "$env_gen" ]]; then
    die "Environment generator not found at ${env_gen}"
  fi

  # Create env file if it doesn't exist; retain existing secrets across deploys
  if [[ ! -f "$COMPOSE_ENV_FILE" ]]; then
    touch "$COMPOSE_ENV_FILE"
    chmod 600 "$COMPOSE_ENV_FILE"
  fi

  local gen_args=(python3 "$env_gen" "$COMPOSE_ENV_FILE"
    --learning-media-root "$MEDIA_ROOT"
  )

  # If a provider env file exists, use it
  local provider_env="${APP_ROOT}/.env.provider"
  if [[ -f "$provider_env" ]]; then
    gen_args+=(--provider-env "$provider_env")
  fi

  "${gen_args[@]}"

  # Append Azure-specific overrides (Managed Identity, no provider secrets)
  {
    printf '\n# Azure VM overrides (managed identity)\n'
    if [[ -n "${COGENTREX_OPENAI_ENDPOINT:-}" ]]; then
      printf 'COGENTREX_LLM_BASE_URL=%s\n' "$COGENTREX_OPENAI_ENDPOINT"
    fi
    if [[ -n "${COGENTREX_OPENAI_MODEL:-}" ]]; then
      printf 'COGENTREX_LLM_MODEL=%s\n' "$COGENTREX_OPENAI_MODEL"
    fi
    if [[ -n "${APPLICATIONINSIGHTS_CONNECTION_STRING:-}" ]]; then
      printf 'APPLICATIONINSIGHTS_CONNECTION_STRING=%s\n' "$APPLICATIONINSIGHTS_CONNECTION_STRING"
    fi
  } >> "$COMPOSE_ENV_FILE"
  chmod 600 "$COMPOSE_ENV_FILE"
}

# ─── Backup ─────────────────────────────────────────────────────────────────────

pg_backup() {
  local sha="$1"
  local ts
  ts="$(date -u +%Y%m%dT%H%M%SZ)"
  local dump_file="${BACKUP_DIR}/cogentrex-${sha:0:12}-${ts}.dump"

  mkdir -p "$BACKUP_DIR"
  chmod 700 "$BACKUP_DIR"

  local repo_dir="${APP_ROOT}/repo"
  local backup_script="${repo_dir}/scripts/local-backup.sh"

  if [[ -f "$backup_script" ]]; then
    log "Running pg_dump backup via canonical script..."
    bash "$backup_script" "$COMPOSE_PROJECT" "$COMPOSE_ENV_FILE" "$dump_file" || {
      log "WARNING: Backup failed; proceeding with deployment."
      return 0
    }
    log "Backup saved: ${dump_file}"
  else
    # Fallback: direct pg_dump through compose
    log "Running pg_dump backup (direct)..."
    local compose=(docker compose --env-file "$COMPOSE_ENV_FILE"
      -f "${APP_ROOT}/repo/${COMPOSE_FILE_LOCAL}" -p "$COMPOSE_PROJECT")
    if "${compose[@]}" exec -T postgres pg_dump -U cogentrex -d cogentrex -Fc \
        --no-owner --no-acl > "$dump_file" 2>/dev/null; then
      chmod 600 "$dump_file"
      log "Backup saved: ${dump_file}"
    else
      log "WARNING: Backup failed (no running postgres?); proceeding."
      rm -f "$dump_file"
    fi
  fi
}

# ─── Docker Compose Update ──────────────────────────────────────────────────────

compose_update() {
  local repo_dir="${APP_ROOT}/repo"
  local compose=(docker compose --env-file "$COMPOSE_ENV_FILE"
    -f "${repo_dir}/${COMPOSE_FILE_LOCAL}" -p "$COMPOSE_PROJECT")

  log "Building images..."
  "${compose[@]}" build

  log "Pulling external images..."
  "${compose[@]}" pull --ignore-buildable 2>/dev/null || true

  log "Starting services (preserving volumes)..."
  "${compose[@]}" up -d --wait --remove-orphans
}

# ─── Health Checks ──────────────────────────────────────────────────────────────

wait_for_health() {
  local base_url="$1"
  local max_wait="${2:-120}"
  local endpoints=("healthz" "readyz")

  for endpoint in "${endpoints[@]}"; do
    log "Waiting for /${endpoint}..."
    local elapsed=0
    while (( elapsed < max_wait )); do
      if curl --fail --silent --show-error "${base_url}/${endpoint}" >/dev/null 2>&1; then
        log "/${endpoint} is healthy."
        break
      fi
      sleep 2
      elapsed=$(( elapsed + 2 ))
    done
    if (( elapsed >= max_wait )); then
      die "/${endpoint} did not become healthy within ${max_wait}s"
    fi
  done
}

check_health_details() {
  local base_url="$1"

  log "Verifying /healthz response..."
  curl --fail --silent --show-error "${base_url}/healthz" | python3 -c '
import json, sys
d = json.load(sys.stdin)
assert d["status"] == "alive", f"healthz status: {d['status']}"
print("  healthz: alive, provider=" + d.get("llm_provider", "?") + " model=" + d.get("llm_model", "?"))
'

  log "Verifying /readyz response..."
  curl --fail --silent --show-error "${base_url}/readyz" | python3 -c '
import json, sys
d = json.load(sys.stdin)
deps = d["dependencies"]
assert d["status"] == "ready", f"readyz status: {d['status']}"
assert deps["conversation_repository"] == "up"
assert deps["rate_limiter"]["status"] == "up"
print("  readyz: ready, db=up, redis=up")
'
}

check_media() {
  local base_url="$1"
  if [[ -f "${MEDIA_ROOT}/.cogentrex-learning-library" ]]; then
    log "Checking /learn media endpoint..."
    if curl --fail --silent --show-error "${base_url}/learn" >/dev/null 2>&1; then
      log "  /learn endpoint accessible."
    else
      log "WARNING: /learn endpoint not accessible."
    fi
  fi
}

check_sandbox() {
  local repo_dir="${APP_ROOT}/repo"
  local compose=(docker compose --env-file "$COMPOSE_ENV_FILE"
    -f "${repo_dir}/${COMPOSE_FILE_LOCAL}" -p "$COMPOSE_PROJECT")

  log "Checking sandbox container controls..."
  if "${compose[@]}" exec -T sandbox-runner python3 -c \
    "import socket; socket.create_connection(('8.8.8.8', 53), timeout=3)" 2>/dev/null; then
    die "Sandbox network isolation FAILED: egress should be denied"
  else
    log "  Sandbox network isolation: verified (egress denied)."
  fi
}

# ─── Rollback ───────────────────────────────────────────────────────────────────

rollback() {
  local previous_sha="$1"
  if [[ -z "$previous_sha" ]]; then
    die "No previous SHA available for rollback."
  fi
  log "ROLLING BACK to SHA ${previous_sha}..."
  ensure_repo "$previous_sha"
  compose_update
  wait_for_health "http://127.0.0.1:80" 120
  save_deploy_state "$previous_sha"
  log "Rollback to ${previous_sha} complete."
}

# ─── Main ───────────────────────────────────────────────────────────────────────

main() {
  local target_sha="${1:-}"
  if [[ -z "$target_sha" ]]; then
    die "Usage: deploy-vm.sh <40-char-SHA> [--repo URL]"
  fi
  shift

  # Parse optional args
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --repo) COGENTREX_REPO_URL="$2"; shift 2 ;;
      *) die "Unknown argument: $1" ;;
    esac
  done

  validate_sha "$target_sha"

  local previous_sha
  previous_sha="$(current_deployed_sha)"

  if [[ "$previous_sha" == "$target_sha" ]]; then
    log "SHA ${target_sha} is already deployed. Re-running health checks..."
    wait_for_health "http://127.0.0.1:80" 60
    check_health_details "http://127.0.0.1:80"
    log "Deployment verified."
    exit 0
  fi

  log "Deploying SHA ${target_sha}..."
  [[ -n "$previous_sha" ]] && log "Previous SHA: ${previous_sha}"

  # Persistent directories
  mkdir -p "$TMPDIR_PERSIST" "$STATE_DIR" "$BACKUP_DIR"
  chmod 700 "$TMPDIR_PERSIST" "$STATE_DIR" "$BACKUP_DIR"
  export TMPDIR="$TMPDIR_PERSIST"
  export XDG_STATE_HOME="$STATE_DIR"

  # Step 1: Clone/fetch and checkout
  ensure_repo "$target_sha"

  # Step 2: Install learning media if absent
  install_learning_media_if_absent

  # Step 3: Generate/retain protected env
  generate_env

  # Step 4: Backup before update (only if stack is running)
  if [[ -n "$previous_sha" ]]; then
    pg_backup "$previous_sha"
  fi

  # Step 5: Docker compose update (preserving volumes)
  if ! compose_update; then
    log "ERROR: Compose update failed."
    if [[ -n "$previous_sha" ]]; then
      rollback "$previous_sha"
    fi
    exit 1
  fi

  # Step 6: Health checks
  if ! wait_for_health "http://127.0.0.1:80" 120; then
    log "ERROR: Health checks failed after deployment."
    if [[ -n "$previous_sha" ]]; then
      rollback "$previous_sha"
    fi
    exit 1
  fi

  if ! check_health_details "http://127.0.0.1:80"; then
    log "ERROR: Detailed health checks failed."
    if [[ -n "$previous_sha" ]]; then
      rollback "$previous_sha"
    fi
    exit 1
  fi

  # Step 7: Media & sandbox checks (non-fatal warnings)
  check_media "http://127.0.0.1:80" || true
  check_sandbox || true

  # Step 8: Record deployment
  save_deploy_state "$target_sha"

  log "Deployment of ${target_sha} complete."
  log "Previous SHA: ${previous_sha:-none}"
  log "Public URL: https://${COGENTREX_PUBLIC_IP:-<unknown>}.sslip.io"
}

main "$@"
