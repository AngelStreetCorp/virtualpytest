#!/usr/bin/env bash
set -euo pipefail

# pick_720p_variants.sh — for every DEVICE<N>_VIDEO URL on a backend host whose
# master HLS playlist exposes a 1280x720 variant, rewrite the URL in
# /opt/virtualpytest/backend_host/src/.env to point at the 720p variant.
#
# Why: nipogi's 24-stream software ceiling is bound by the 1080p H.264 decode
# cost (TASK-95 §8.8). Streams whose CDN exposes a 720p variant cost ~38% less
# CPU per stream when pulled at 720p, freeing the headroom to add more devices.
# Streams whose CDN does NOT expose a 720p variant (single-variant HLS, SMIL,
# github raw) are left untouched. Idempotent: lines that already point at a
# 720p variant are left alone.
#
# Usage:
#   scripts/pick_720p_variants.sh [--check] <ssh-host> [<ssh-host> ...]
#
#   --check   Report which devices WOULD be rewritten; change nothing.
#   (default) Apply the rewrites; restart vpt-stream once at the end.
#
# Requirements: passwordless sudo for `cat` and `cp` on the host, the same
# surface install_host.sh sets up. No Python on the host required.

ENV_PATH=/opt/virtualpytest/backend_host/src/.env
LOCAL_RESOLVER="scripts/hls_pick_720p.py"

CHECK_ONLY=0
HOSTS=()
for arg in "$@"; do
  case "$arg" in
    --check) CHECK_ONLY=1 ;;
    -h|--help) sed -n '3,28p' "$0"; exit 0 ;;
    -*) echo "[720p] unknown option: $arg" >&2; exit 2 ;;
    *) HOSTS+=("$arg") ;;
  esac
done

if [[ ${#HOSTS[@]} -eq 0 ]]; then
  echo "[720p] no hosts given. Usage: $0 [--check] <ssh-host> [<ssh-host> ...]" >&2
  exit 2
fi

if [[ ! -f "$LOCAL_RESOLVER" ]]; then
  echo "[720p] $LOCAL_RESOLVER not found (run from repo root)" >&2
  exit 2
fi

REPO_ROOT="$(cd "$(dirname "$LOCAL_RESOLVER")/.." && pwd)"
RESOLVER="${REPO_ROOT}/${LOCAL_RESOLVER}"

apply_to_host() {
  local host="$1"
  local stamp backup_path
  stamp=$(date -u +%Y%m%dT%H%M%SZ)
  backup_path="${ENV_PATH}.bak.${stamp}"
  echo "[720p] $host: backup -> $backup_path"
  ssh -o BatchMode=yes "$host" "sudo -n cp '$ENV_PATH' '$backup_path'"

  # Pull DEVICE<N>_VIDEO and DEVICE<N>_NAME lines, strip the optional quotes,
  # and pipe them through a small Python joiner that emits (idx<TAB>name<TAB>url)
  # rows for every device. Then the local resolver picks the 720p variant.
  local map
  map=$(
    ssh -o BatchMode=yes "$host" "sudo -n grep -E '^DEVICE[0-9]+_(VIDEO|NAME)=' '$ENV_PATH'" |
    python3 -c '
import sys, re
videos, names = {}, {}
for line in sys.stdin:
    line = line.rstrip("\n")
    m = re.match(r"^DEVICE(\d+)_(VIDEO|NAME)=(.*)$", line)
    if not m: continue
    idx, kind, val = m.group(1), m.group(2), m.group(3)
    if (val.startswith(chr(34)) and val.endswith(chr(34))):
        val = val[1:-1]
    if kind == "VIDEO": videos[idx] = val
    else:                names[idx]  = val
for idx in sorted(videos, key=lambda x: int(x)):
    name = names.get(idx, "")
    sys.stdout.write("%s\t%s\t%s\n" % (idx, name, videos[idx]))
' |
    python3 "$RESOLVER" --tsv
  ) || {
    echo "[720p] $host: resolver failed" >&2
    return 1
  }

  local changes=() skips=() no_masters=() errors=()
  local sed_lines=""
  while IFS=$'\x1f' read -r idx dname new_url reason; do
    [[ -z "$idx" ]] && continue
    case "$reason" in
      OK)
        changes+=("DEVICE${idx} (${dname}): -> 1280x720")
        # Escape only `&`, `\`, and the `|` separator for sed. Forward
        # slashes are fine because the script uses `|` as the sed delimiter
        # (s|...|...|). The earlier over-escape of `/` produced `\/` in the
        # output, which HLS clients can't fetch.
        local esc="${new_url//&/\\&}"
        esc="${esc//\\/\\\\}"
        esc="${esc//|/\\|}"
        sed_lines+="s|^DEVICE${idx}_VIDEO=.*\$|DEVICE${idx}_VIDEO=${esc}|;"$'\n'
        ;;
      ALREADY_720P)
        skips+=("DEVICE${idx} (${dname}): already 720p")
        ;;
      NO_MASTER)
        no_masters+=("DEVICE${idx} (${dname}): single-variant source")
        ;;
      NO_720P)
        skips+=("DEVICE${idx} (${dname}): master exists, no 1280x720 variant")
        ;;
      *)
        errors+=("DEVICE${idx} (${dname}): ${reason}")
        ;;
    esac
  done <<< "$map"

  echo "[720p] $host: plan"
  for line in "${changes[@]:-}"; do [[ -n "$line" ]] && echo "  CHANGE  $line"; done
  for line in "${skips[@]:-}"; do [[ -n "$line" ]] && echo "  SKIP    $line"; done
  for line in "${no_masters[@]:-}"; do [[ -n "$line" ]] && echo "  SKIP    $line"; done
  for line in "${errors[@]:-}"; do [[ -n "$line" ]] && echo "  ERROR   $line"; done

  if [[ "$CHECK_ONLY" -eq 1 ]]; then
    return 0
  fi

  if [[ ${#changes[@]} -eq 0 ]]; then
    echo "[720p] $host: no changes to apply"
    return 0
  fi

  echo "[720p] $host: applying ${#changes[@]} substitution(s)"
  ssh -o BatchMode=yes "$host" "sudo -n bash -s" <<EOF
cp '$ENV_PATH' '${ENV_PATH}.pre-720p'
sed -i -E -e '${sed_lines}' '$ENV_PATH'
EOF
  echo "[720p] $host: restart vpt-stream"
  ssh -o BatchMode=yes "$host" "sudo -n systemctl restart vpt-stream"
  sleep 5
  ssh -o BatchMode=yes "$host" "systemctl is-active vpt-stream" >/dev/null || {
    echo "[720p] $host: vpt-stream did not come back up. Check: ssh $host journalctl -u vpt-stream -n 50" >&2
    return 1
  }
  echo "[720p] $host: done"
}

for host in "${HOSTS[@]}"; do
  apply_to_host "$host"
done