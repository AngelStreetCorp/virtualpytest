#!/usr/bin/env bash
# apply_stream_profile.sh — write (or remove) a TASK-102 STREAM_PROFILE in
# /opt/virtualpytest/backend_host/src/.env on a backend_host machine.
#
# The script is the operator-facing entry point for the 3 named profiles
# (TASK-100 + TASK-102). Setting STREAM_PROFILE in the host .env makes the host
# boot into the right bundle (VAAPI_MODE / VAAPI_MIN_QUALITY / SW_THREADS /
# MONITOR_PROFILE / HOST_TIER_CAP) without the operator hand-tuning 5 keys.
#
# Usage:
#   scripts/apply_stream_profile.sh [--check|--unset] <profile> <ssh-host> [<ssh-host> ...]
#
#   --check   Report the current STREAM_PROFILE per host; change nothing.
#   --unset   Remove the STREAM_PROFILE line (back to legacy: hand-tuned keys win).
#
#   profile   One of: stream_local_hd, stream_local_360p, stream_hls_720p, stream_hls_360p
#             (typo'd names are rejected with a non-zero exit; the loader's
#             runtime fallback to stream_hls_720p is a separate concern)
#
# Examples:
#   scripts/apply_stream_profile.sh --check vpt-nipogi
#   scripts/apply_stream_profile.sh stream_hls_720p vpt-nipogi
#   scripts/apply_stream_profile.sh stream_local_hd vpt-lenovo1-hd
#   scripts/apply_stream_profile.sh --unset vpt-nipogi
#
# The script is idempotent: re-running with the same profile is a no-op once
# the .env line matches. A timestamped backup is written next to the .env the
# first time it touches a host. vpt-stream is restarted at the end so the new
# profile is picked up (one short black window across all streams).
#
# Requirements: the SSH user must have passwordless sudo for `cat`, `cp`,
# and `systemctl restart vpt-stream` on the host (the same surface
# install_host.sh sets up; scripts/patch_host_sudoers.sh brings older hosts
# up to it).

set -euo pipefail

ENV_PATH=/opt/virtualpytest/backend_host/src/.env
KEY_REGEX='^STREAM_PROFILE='
VALID_PROFILES=(stream_local_hd stream_local_360p stream_hls_720p stream_hls_360p)

CHECK_ONLY=0
UNSET=0
PROFILE=""
HOSTS=()
for arg in "$@"; do
  case "$arg" in
    --check) CHECK_ONLY=1 ;;
    --unset) UNSET=1 ;;
    -h|--help) sed -n '3,45p' "$0"; exit 0 ;;
    -*) echo "[stream-profile] unknown option: $arg" >&2; exit 2 ;;
    *)
      if [ -z "$PROFILE" ] && [ "$UNSET" -eq 0 ]; then
        PROFILE="$arg"
      else
        HOSTS+=("$arg")
      fi
      ;;
  esac
done

if [ "$UNSET" -eq 0 ] && [ -z "$PROFILE" ]; then
  echo "[stream-profile] missing profile name. Valid: ${VALID_PROFILES[*]}" >&2
  echo "Usage: $0 [--check|--unset] <profile> <ssh-host> [<ssh-host> ...]" >&2
  exit 2
fi

if [ "$UNSET" -eq 0 ]; then
  valid=0
  for p in "${VALID_PROFILES[@]}"; do
    [ "$p" = "$PROFILE" ] && valid=1
  done
  if [ "$valid" -eq 0 ]; then
    echo "[stream-profile] invalid profile '$PROFILE'. Valid: ${VALID_PROFILES[*]}" >&2
    exit 2
  fi
fi

if [ ${#HOSTS[@]} -eq 0 ]; then
  echo "[stream-profile] no hosts given. Usage: $0 [--check|--unset] <profile> <ssh-host> [<ssh-host> ...]" >&2
  exit 2
fi

ssh_run() {
  ssh -o BatchMode=yes "$1" "$2"
}

read_stream_profile() {
  local host="$1" out
  out=$(ssh_run "$host" "sudo -n grep -E '$KEY_REGEX' '$ENV_PATH' 2>/dev/null || true")
  if [ -z "$out" ]; then
    echo "STREAM_PROFILE=unset"
  else
    printf '%s\n' "$out"
  fi
}

profile_matches_desired() {
  local host="$1" current
  current=$(read_stream_profile "$host")
  if [ "$UNSET" -eq 1 ]; then
    [ "$current" = "STREAM_PROFILE=unset" ]
  else
    [ "$current" = "STREAM_PROFILE=${PROFILE}" ]
  fi
}

apply_to_host() {
  local host="$1"
  local stamp backup_path
  stamp=$(date -u +%Y%m%dT%H%M%SZ)
  backup_path="${ENV_PATH}.bak.${stamp}"

  echo "[stream-profile] $host: backup -> $backup_path"
  ssh_run "$host" "sudo -n cp '$ENV_PATH' '$backup_path'"

  if [ "$UNSET" -eq 1 ]; then
    ssh_run "$host" "sudo -n sed -i -E '/$KEY_REGEX/d' '$ENV_PATH'"
    echo "[stream-profile] $host: STREAM_PROFILE removed (back to legacy keys)"
  else
    ssh_run "$host" "sudo -n bash -c \"
      if grep -qE '^STREAM_PROFILE=' '$ENV_PATH'; then
        sed -i -E 's|^STREAM_PROFILE=.*|STREAM_PROFILE=${PROFILE}|' '$ENV_PATH'
        echo '[stream-profile] ${host}: STREAM_PROFILE updated -> ${PROFILE}'
      else
        printf 'STREAM_PROFILE=${PROFILE}\n' >> '$ENV_PATH'
        echo '[stream-profile] ${host}: STREAM_PROFILE appended -> ${PROFILE}'
      fi
    \""
  fi

  echo "[stream-profile] $host: restart vpt-stream"
  ssh_run "$host" "sudo -n systemctl restart vpt-stream"
  sleep 5
  ssh_run "$host" "systemctl is-active vpt-stream" || {
    echo "[stream-profile] $host: vpt-stream did not come back up. Check: ssh $host journalctl -u vpt-stream -n 50" >&2
    return 1
  }
  echo "[stream-profile] $host: done"
}

for host in "${HOSTS[@]}"; do
  if profile_matches_desired "$host"; then
    if [ "$UNSET" -eq 1 ]; then
      echo "[stream-profile] $host: already unset; nothing to do"
    else
      echo "[stream-profile] $host: already STREAM_PROFILE=${PROFILE}; nothing to do"
    fi
    continue
  fi
  if [ "$CHECK_ONLY" -eq 1 ]; then
    current=$(read_stream_profile "$host")
    if [ "$UNSET" -eq 1 ]; then
      echo "[stream-profile] $host: would unset (current: $current)"
    else
      echo "[stream-profile] $host: would set STREAM_PROFILE=${PROFILE} (current: $current)"
    fi
    continue
  fi
  apply_to_host "$host"
done
