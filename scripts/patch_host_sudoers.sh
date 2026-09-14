#!/usr/bin/env bash
set -euo pipefail

# patch_host_sudoers.sh — ensure backend_host machines grant vpt_user
# passwordless `systemctl start|stop|restart vpt-*`.
#
# Hosts installed before the dashboard per-service controls only have a
# `restart vpt-*` rule (plus `start|stop stream*`), so the dashboard's
# start/stop icons fail with "sudo: a password is required". This script
# brings their /etc/sudoers.d/virtualpytest up to what install_host.sh now
# writes — idempotently, with a visudo syntax check and a timestamped backup,
# so it is safe to re-run.
#
# Usage:
#   scripts/patch_host_sudoers.sh [--check] <ssh-host> [<ssh-host> ...]
#
#   --check   Report per host whether a patch is needed; change nothing.
#
# Examples:
#   scripts/patch_host_sudoers.sh --check host1 host3
#   scripts/patch_host_sudoers.sh host1 host3
#
# Requirements: the SSH user on each host must have passwordless sudo for
# `cat`, `visudo`, `install`, `cp` (the host pis do). Hosts are referenced
# by ~/.ssh/config alias so no IPs are hardcoded here.

SUDOERS_FILE="/etc/sudoers.d/virtualpytest"

# Single source of truth — must mirror the vpt-* block in
# setup/local/linux/backend_host/install_host.sh. Idempotent: only rules not
# already present (matched as fixed strings) are appended.
DESIRED_RULES=(
  "vpt_user ALL=(root) NOPASSWD: /bin/systemctl start vpt-*, /usr/bin/systemctl start vpt-*"
  "vpt_user ALL=(root) NOPASSWD: /bin/systemctl stop vpt-*, /usr/bin/systemctl stop vpt-*"
  "vpt_user ALL=(root) NOPASSWD: /bin/systemctl restart vpt-*, /usr/bin/systemctl restart vpt-*"
)

CHECK_ONLY=0
HOSTS=()
for arg in "$@"; do
  case "$arg" in
    --check) CHECK_ONLY=1 ;;
    -h|--help) sed -n '3,28p' "$0"; exit 0 ;;
    -*) echo "[sudoers] unknown option: $arg" >&2; exit 2 ;;
    *) HOSTS+=("$arg") ;;
  esac
done

if [[ ${#HOSTS[@]} -eq 0 ]]; then
  echo "[sudoers] no hosts given. Usage: $0 [--check] <ssh-host> [<ssh-host> ...]" >&2
  exit 2
fi

RULES_B64="$(printf '%s\n' "${DESIRED_RULES[@]}" | base64 | tr -d '\n')"

# Remote program. $1 = base64 of desired rules, $2 = SUDOERS_FILE, $3 = check-only.
read -r -d '' REMOTE <<'REMOTE_EOF' || true
set -euo pipefail
RULES_B64="$1"; F="$2"; CHECK="$3"
if ! sudo -n true 2>/dev/null; then
  echo "ERROR: ssh user lacks passwordless sudo on $(hostname)"; exit 3
fi
[ -f "$F" ] || { echo "ERROR: $F missing on $(hostname)"; exit 4; }

work="$(mktemp)"; trap 'rm -f "$work"' EXIT
sudo -n cat "$F" > "$work"

missing=0
while IFS= read -r rule; do
  [ -z "$rule" ] && continue
  if ! grep -qF -- "$rule" "$work"; then
    missing=$((missing + 1))
    printf '%s\n' "$rule" >> "$work"
  fi
done < <(printf '%s' "$RULES_B64" | base64 -d)

if [ "$missing" -eq 0 ]; then echo "OK: already current on $(hostname)"; exit 0; fi
if [ "$CHECK" = "1" ]; then echo "NEEDS-PATCH: $missing rule(s) missing on $(hostname)"; exit 10; fi

sudo visudo -cf "$work" >/dev/null
ts="$(date +%Y%m%d%H%M%S)"
sudo cp -a "$F" "$F.bak.$ts"
sudo install -m 440 -o root -g root "$work" "$F"
echo "PATCHED: added $missing rule(s) on $(hostname) (backup: $F.bak.$ts)"
REMOTE_EOF

rc=0
for host in "${HOSTS[@]}"; do
  echo "=== $host ==="
  if out="$(ssh -o ConnectTimeout=15 "$host" "bash -s -- '$RULES_B64' '$SUDOERS_FILE' '$CHECK_ONLY'" <<<"$REMOTE" 2>&1)"; then
    echo "$out"
  else
    code=$?
    echo "$out"
    # exit 10 = "--check found work to do": informational, not a failure.
    if [[ "$CHECK_ONLY" -eq 1 && $code -eq 10 ]]; then
      :
    else
      echo "[sudoers] $host FAILED (exit $code)" >&2
      rc=1
    fi
  fi
done

exit "$rc"
