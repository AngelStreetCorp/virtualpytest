#!/usr/bin/env bash
set -euo pipefail

# apply_vaapi_nipogi.sh — write (or remove) the recommended VAAPI policy in
# /opt/virtualpytest/backend_host/src/.env on a backend_host machine.
#
# The recommended policy for nipogi (and any host with a Vega iGPU that runs
# many lean tv_lite streams + a few watched HD tiles) is:
#
#     VAAPI_MODE=full
#     VAAPI_MIN_QUALITY=hd
#     SW_THREADS=1
#
# Why this combination:
#   - low/sd streams (the grid) run in software with one thread each — that's
#     where nipogi hits 48-60 streams at 1x (TASK-95 §8.5, §8.7).
#   - hd / hd_plus streams (the watched tile) run on the GPU — capped at about
#     18-20 HD streams (TASK-95 §8.3, §8.6).
#   - The mixed policy (40 low + 4 hd) carries 44 streams at 1.0x with 44 %
#     idle and 6.4 GB RAM free (TASK-95 §8.6).
#
# The script is idempotent: lines that already match are left untouched; lines
# that differ are replaced. A timestamped backup is written next to the .env
# the first time it touches a host. vpt-stream is restarted at the end so the
# new mode is picked up (one short black window across all streams).
#
# Usage:
#   scripts/apply_vaapi_nipogi.sh [--check] [--unset] <ssh-host> [<ssh-host> ...]
#
#   --check   Report current VAAPI keys per host; change nothing.
#   --unset   Remove the three keys (back to today's default: auto).
#
# Examples:
#   scripts/apply_vaapi_nipogi.sh --check vpt-nipogi
#   scripts/apply_vaapi_nipogi.sh vpt-nipogi
#   scripts/apply_vaapi_nipogi.sh --unset vpt-nipogi
#
# Requirements: the SSH user must have passwordless sudo for `cat`, `cp`, and
# `systemctl restart vpt-stream` on the host (the same surface install_host.sh
# sets up; scripts/patch_host_sudoers.sh brings older hosts up to it).

ENV_PATH=/opt/virtualpytest/backend_host/src/.env
DESIRED_LINES=(
  "VAAPI_MODE=full"
  "VAAPI_MIN_QUALITY=hd"
  "SW_THREADS=1"
)
TARGET_KEYS_REGEX='^(VAAPI_MODE|VAAPI_MIN_QUALITY|SW_THREADS)='

CHECK_ONLY=0
UNSET=0
HOSTS=()
for arg in "$@"; do
  case "$arg" in
    --check) CHECK_ONLY=1 ;;
    --unset) UNSET=1 ;;
    -h|--help) sed -n '3,40p' "$0"; exit 0 ;;
    -*) echo "[vaapi] unknown option: $arg" >&2; exit 2 ;;
    *) HOSTS+=("$arg") ;;
  esac
done

if [[ ${#HOSTS[@]} -eq 0 ]]; then
  echo "[vaapi] no hosts given. Usage: $0 [--check|--unset] <ssh-host> [<ssh-host> ...]" >&2
  exit 2
fi

ssh_run() {
  ssh -o BatchMode=yes "$1" "$2"
}

read_env_keys() {
  # Print the three target keys (or 'unset') as 'KEY=value', one per line, on stdout.
  local host="$1" out
  out=$(ssh_run "$host" "sudo -n grep -E '$TARGET_KEYS_REGEX' '$ENV_PATH' 2>/dev/null || true")
  if [[ -z "$out" ]]; then
    echo "VAAPI_MODE=unset"
    echo "VAAPI_MIN_QUALITY=unset"
    echo "SW_THREADS=unset"
  else
    printf '%s\n' "$out"
  fi
}

keys_match_desired() {
  local host="$1" current current_map desired_map key
  current=$(read_env_keys "$host")
  current_map=$(printf '%s\n' "$current" | sort)
  if [[ "$UNSET" -eq 1 ]]; then
    [[ "$current_map" == "$(printf 'VAAPI_MODE=unset\nVAAPI_MIN_QUALITY=unset\nSW_THREADS=unset\n' | sort)" ]]
  else
    desired_map=$(printf '%s\n' "${DESIRED_LINES[@]}" | sort)
    [[ "$current_map" == "$desired_map" ]]
  fi
}

apply_to_host() {
  local host="$1"
  local stamp backup_path
  stamp=$(date -u +%Y%m%dT%H%M%SZ)
  backup_path="${ENV_PATH}.bak.${stamp}"

  echo "[vaapi] $host: backup -> $backup_path"
  ssh_run "$host" "sudo -n cp '$ENV_PATH' '$backup_path'"

  if [[ "$UNSET" -eq 1 ]]; then
    # Strip any existing target-key lines, leaving everything else alone.
    ssh_run "$host" "sudo -n sed -i -E '/$TARGET_KEYS_REGEX/d' '$ENV_PATH'"
    echo "[vaapi] $host: removed $(printf '%s, ' "${DESIRED_LINES[@]}" | sed 's/, $//')"
  else
    # Append each desired line if absent, replace the value if present.
    local line key val
    for line in "${DESIRED_LINES[@]}"; do
      key="${line%%=*}"
      val="${line#*=}"
      ssh_run "$host" "sudo -n bash -c \"
        if grep -qE '^${key}=' '$ENV_PATH'; then
          sed -i -E 's|^${key}=.*|${key}=${val}|' '$ENV_PATH'
          echo '[vaapi] ${host}: updated ${key}=${val}'
        else
          printf '%s\n' '${line}' >> '$ENV_PATH'
          echo '[vaapi] ${host}: appended ${key}=${val}'
        fi
      \""
    done
  fi

  echo "[vaapi] $host: restart vpt-stream"
  ssh_run "$host" "sudo -n systemctl restart vpt-stream"
  sleep 5
  ssh_run "$host" "systemctl is-active vpt-stream" || {
    echo "[vaapi] $host: vpt-stream did not come back up. Check: ssh $host journalctl -u vpt-stream -n 50" >&2
    return 1
  }
  echo "[vaapi] $host: done"
}

for host in "${HOSTS[@]}"; do
  if keys_match_desired "$host"; then
    echo "[vaapi] $host: already $([[ $UNSET -eq 1 ]] && echo unset || echo 'matches desired policy'); nothing to do"
    continue
  fi
  if [[ "$CHECK_ONLY" -eq 1 ]]; then
    echo "[vaapi] $host: would $([[ $UNSET -eq 1 ]] && echo 'unset VAAPI keys' || echo 'apply VAAPI policy:'; printf '    %s\n' "${DESIRED_LINES[@]}")"
    continue
  fi
  apply_to_host "$host"
done