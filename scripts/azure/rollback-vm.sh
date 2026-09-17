#!/usr/bin/env bash
# rollback-vm.sh – Roll back to the previously deployed SHA on the Azure VM.
#
# Usage: rollback-vm.sh [--force SHA]
#
# Without --force, reads the previous SHA from deploy state and invokes deploy-vm.sh.
# With --force, deploys the given SHA directly.
set -Eeuo pipefail
shopt -s inherit_errexit

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
readonly SCRIPT_DIR
readonly APP_ROOT="${COGENTREX_APP_ROOT:-/opt/cogentrex}"
readonly STATE_DIR="${XDG_STATE_HOME:-$APP_ROOT/.state}"
readonly DEPLOY_STATE="${STATE_DIR}/deploy.env"

log() { printf '[%s] %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*"; }
die() { log "FATAL: $*" >&2; exit 1; }

main() {
  local target_sha=""
  local force=false

  while [[ $# -gt 0 ]]; do
    case "$1" in
      --force)
        force=true
        target_sha="${2:-}"
        [[ -n "$target_sha" ]] || die "--force requires a SHA argument"
        shift 2
        ;;
      -h|--help)
        printf 'Usage: rollback-vm.sh [--force SHA]\n'
        exit 0
        ;;
      *)
        die "Unknown argument: $1"
        ;;
    esac
  done

  if [[ "$force" == "true" ]]; then
    log "Force rollback to SHA ${target_sha}"
  else
    if [[ ! -f "$DEPLOY_STATE" ]]; then
      die "No deploy state found at ${DEPLOY_STATE}; cannot determine previous SHA."
    fi

    local current_sha
    local previous_sha
    # shellcheck disable=SC1090
    current_sha="$(source "$DEPLOY_STATE" && printf '%s' "${COGENTREX_DEPLOYED_SHA:-}")"
    # shellcheck disable=SC1090
    previous_sha="$(source "$DEPLOY_STATE" && printf '%s' "${COGENTREX_PREVIOUS_SHA:-}")"
    [[ -n "$current_sha" ]] || die "No deployed SHA found in state file."
    target_sha="$previous_sha"
    [[ "$target_sha" =~ ^[0-9a-f]{40}$ ]] \
      || die "No valid previous SHA in deploy state. Use --force SHA to specify."
    log "Rolling back from ${current_sha} to ${target_sha}"
  fi

  # Delegate to deploy-vm.sh
  exec bash "${SCRIPT_DIR}/deploy-vm.sh" "$target_sha"
}

main "$@"
