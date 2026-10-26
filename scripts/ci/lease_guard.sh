#!/usr/bin/env bash
# Hold the node1-vpt lease while a CI job runs against the LIVE server.
#
# Why this exists: the platform jobs below test the deployed server, not a local build. A deploy
# restarts that server, nginx answers 500 while it is down, and every request in the run fails.
# wait_for_server.sh only guards the START of a job, so a deploy that begins two minutes into a
# six-minute sweep still turns into 100+ bogus assertion failures (run 4177: 518 failed API routes,
# 134 failed backend tests, zero of them a real defect).
#
# This closes the gap from the other side: while the sweep runs, the job holds the same lease a
# deploy needs, so update_core.sh queues the deploy instead of restarting the server underneath us.
#
# Usage (the normal form — acquire, run, release in ONE step so the release cannot be skipped):
#     ./scripts/ci/lease_guard.sh run -- <command...>
# Split form, when the guarded work is several steps:
#     ./scripts/ci/lease_guard.sh acquire ; ... ; ./scripts/ci/lease_guard.sh release
#
# Safety, in the order it matters:
#   - short TTL + heartbeat. The TTL is the dead-man switch: if the runner dies mid-job the lease
#     expires on its own and a dead CI run can never block deploys for longer than the TTL.
#   - released on success, failure AND interrupt (trap). A red test never leaves a lease behind.
#   - never --force, and never kills another agent's lease: we queue with --wait like everyone else.
#   - --shared, because the platform jobs run in parallel on six runners and must not serialise
#     against each other. A deploy still sees every one of them as busy.
#   - if the key secret is missing the job runs UNPROTECTED with a loud warning instead of failing,
#     so adding this cannot break CI on a repo where the secret has not been provisioned yet.
set -uo pipefail

CI_LEASE_HOST="${CI_LEASE_HOST:-192.168.0.1}"
CI_LEASE_USER="${CI_LEASE_USER:-jndoye}"
CI_LEASE_BIN="/home/jndoye/bin/vpt-lease"
CI_LEASE_ENV="${CI_LEASE_ENV:-node1-vpt}"
CI_LEASE_RESOURCE="${CI_LEASE_RESOURCE:-server}"
CI_LEASE_TTL_MIN="${CI_LEASE_TTL_MIN:-10}"
CI_LEASE_BEAT_S="${CI_LEASE_BEAT_S:-60}"
CI_LEASE_AGENT="${CI_LEASE_AGENT:-ci:${GITHUB_RUN_ID:-local}:${GITHUB_JOB:-manual}}"
CI_LEASE_PURPOSE="${CI_LEASE_PURPOSE:-ci-live-sweep-${GITHUB_RUN_ID:-local}}"

STATE_DIR="${RUNNER_TEMP:-/tmp}"
STATE_FILE="${STATE_DIR}/vpt-ci-lease.${GITHUB_RUN_ID:-local}"
PID_FILE="${STATE_DIR}/vpt-ci-lease-hb.${GITHUB_RUN_ID:-local}"
KEY_FILE="${STATE_DIR}/vpt-ci-lease-key.${GITHUB_RUN_ID:-local}"

log() { echo "[lease-guard] $*"; }
warn() { echo "[lease-guard] WARNING: $*" >&2; }

# The private key never touches the repo; it is written from the CI secret with a tight mode.
setup_key() {
  if [ -z "${CI_LEASE_SSH_KEY:-}" ]; then
    return 1
  fi
  mkdir -p "$HOME/.ssh"
  printf '%s\n' "$CI_LEASE_SSH_KEY" > "$KEY_FILE"
  chmod 600 "$KEY_FILE"
  # A stale .pub next to the key makes ssh offer the WRONG public key while signing (same trap the
  # CI reports job documents for ci_reports_key).
  rm -f "$KEY_FILE.pub"
  # keyscan rather than a checked-in host key: the proxmox host key is not secret and is not
  # something CI can verify out of band.
  ssh-keyscan -H "$CI_LEASE_HOST" >> "$HOME/.ssh/known_hosts" 2>/dev/null
  return 0
}

lease_ssh() {
  ssh -i "$KEY_FILE" -o IdentitiesOnly=yes -o BatchMode=yes \
      -o ConnectTimeout=10 -o StrictHostKeyChecking=yes \
      "$CI_LEASE_USER@$CI_LEASE_HOST" "$CI_LEASE_BIN $*"
}

cleanup_key() { rm -f "$KEY_FILE"; }

# Echoes the new lease id. Empty output means "no lease" and the caller must run unprotected.
acquire() {
  if ! setup_key; then
    warn "CI_LEASE_SSH_KEY is not set - running UNPROTECTED against the live server."
    warn "A deploy during this job can restart the server and fail these tests spuriously."
    return 0
  fi

  # --wait: queue behind a running deploy instead of failing (never poll, never ask, never force).
  # --expect: lets the registry answer "who is using it and when is it free".
  local out id rc
  out=$(lease_ssh claim "$CI_LEASE_ENV" "$CI_LEASE_RESOURCE" \
          --agent "$CI_LEASE_AGENT" --provider github-actions \
          --purpose "$CI_LEASE_PURPOSE" --kind server --shared \
          --ttl "$CI_LEASE_TTL_MIN" --expect "$CI_LEASE_TTL_MIN" --wait 2>&1)
  rc=$?
  id=$(printf '%s\n' "$out" | grep -oE '^[0-9a-f]{8}$' | head -1)
  if [ "$rc" -ne 0 ] || [ -z "$id" ]; then
    # Fail OPEN here on purpose: a lease service we cannot reach must not turn every platform job
    # red. The job still runs; we lose the protection for this run and say so loudly.
    warn "could not claim $CI_LEASE_ENV/$CI_LEASE_RESOURCE (rc=$rc) - running UNPROTECTED."
    printf '%s\n' "$out" | sed 's/^/[lease-guard]   /' >&2
    return 0
  fi

  printf '%s' "$id" > "$STATE_FILE"
  log "holding $CI_LEASE_ENV/$CI_LEASE_RESOURCE as $id (ttl ${CI_LEASE_TTL_MIN}m, agent $CI_LEASE_AGENT)"
  return 0
}

# One heartbeat + renew. A subcommand rather than an inline loop so the detached loop in the
# split form can re-enter this script instead of needing the functions exported into a child shell.
beat() {
  lease_ssh heartbeat "$1" --active >/dev/null 2>&1 || true
  lease_ssh renew "$1" --ttl "$CI_LEASE_TTL_MIN" >/dev/null 2>&1 || true
}

# Renews in the background for as long as the job runs. renew --ttl is what keeps the TTL sliding;
# heartbeat --active marks the holder busy so the lease does not decay into a pin.
#
# `--detached` is for the split form (acquire in one step, release in a later one): the runner is
# the same VM across steps, so a nohup'd loop outlives the shell that started it and its pid lands
# in PID_FILE for `release` to kill. The TTL still bounds it if the job dies without releasing.
start_heartbeat() {
  local id="$1" detach="${2:-}"
  if [ "$detach" = "detached" ]; then
    nohup bash -c '
      while :; do
        sleep "$1"
        "$0" beat "$2" >/dev/null 2>&1 || exit 0
      done
    ' "$0" "$CI_LEASE_BEAT_S" "$id" >/dev/null 2>&1 &
    echo $! > "$PID_FILE"
    disown 2>/dev/null || true
    return 0
  fi
  (
    while :; do
      sleep "$CI_LEASE_BEAT_S"
      beat "$id"
    done
  ) &
  HEARTBEAT_PID=$!
}

stop_heartbeat() {
  if [ -n "${HEARTBEAT_PID:-}" ]; then
    kill "$HEARTBEAT_PID" 2>/dev/null || true
    wait "$HEARTBEAT_PID" 2>/dev/null || true
    HEARTBEAT_PID=""
  fi
}

stop_detached_heartbeat() {
  if [ -f "$PID_FILE" ]; then
    local pid
    pid=$(cat "$PID_FILE")
    [ -n "$pid" ] && kill "$pid" 2>/dev/null
    rm -f "$PID_FILE"
  fi
}

release() {
  stop_detached_heartbeat
  local id=""
  [ -f "$STATE_FILE" ] && id=$(cat "$STATE_FILE")
  if [ -z "$id" ]; then
    cleanup_key
    return 0
  fi
  lease_ssh release "$id" >/dev/null 2>&1 && log "released $id" || warn "could not release $id (it expires within ${CI_LEASE_TTL_MIN}m)"
  rm -f "$STATE_FILE"
  cleanup_key
}

cmd_run() {
  if [ "${1:-}" != "--" ]; then
    echo "usage: lease_guard.sh run -- <command...>" >&2
    return 2
  fi
  shift
  [ "$#" -gt 0 ] || { echo "lease_guard.sh: no command given" >&2; return 2; }

  acquire
  local id=""
  [ -f "$STATE_FILE" ] && id=$(cat "$STATE_FILE")

  if [ -n "$id" ]; then
    start_heartbeat "$id"
    # EXIT covers a red test; INT/TERM cover a cancelled job. Every path releases.
    trap 'stop_heartbeat; release' EXIT INT TERM
  fi

  "$@"
  local rc=$?

  stop_heartbeat
  release
  trap - EXIT INT TERM
  return $rc
}

cmd_acquire() {
  acquire
  local id=""
  [ -f "$STATE_FILE" ] && id=$(cat "$STATE_FILE")
  # Split form: the guarded work is in this step, the release is a later `if: always()` step, so
  # the heartbeat has to outlive this shell. `beat` re-enters this script with the key already in
  # place (setup_key ran above, and the key file lives in RUNNER_TEMP for the whole job).
  [ -n "$id" ] && start_heartbeat "$id" detached
  return 0
}

cmd_release() { release; }

case "${1:-}" in
  run)        shift; cmd_run "$@" ;;
  acquire)    cmd_acquire ;;
  release)    cmd_release ;;
  beat)       shift; [ "$#" -ge 1 ] && beat "$1" ;;
  *)          echo "usage: lease_guard.sh {run -- <command...>|acquire|release}" >&2; exit 2 ;;
esac